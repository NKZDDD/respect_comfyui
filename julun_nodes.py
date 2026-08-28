"""Respect ComfyUI 扩展 - 巨轮（`https://julun.cc`）节点。

文档：《AI 开放平台接口对接文档》v2.1，2026-08-26

- 文本对话 `/v1/chat/completions`（OpenAI 兼容，直接用『Respect Chat 对话』节点即可，
  base_url 填 `https://julun.cc`，这里不重复做）
- 图片 `POST /v1/images/generations`（OpenAI 兼容，同步）
- 视频：**异步三步**，提交 → 轮询 → 下载

视频这块**一个端点、五种请求格式**，靠模型名分派（见 `JULUN_SPEC`）：

| 格式 | 形状 | 用它的模型 |
|---|---|---|
| `metadata` | `metadata:{content[], duration, ratio, resolution}` | SD2.0 Fast / 1080P 933 / sd-2-c8 / sd-2-c6 |
| `url_media` | `seconds` + `image_urls[]`/`video_urls[]`/`audio_urls[]` | sd2-mini / MINI 933 / Quality V4 / wan3.0th / seedance-2.5-deal / Seedance 图生视频 |
| `openai_refs` | `duration` + `aspect_ratio` + `image_refs[]` | sd2-c7 / sd2.5 / dubai_sd25_170 |
| `grok` | `duration` + `extra:{aspect_ratio, resolution, reference_images[{url,role}]}` | grok 两个 |
| `simple` | 只要 `model` + `prompt` + `seconds` | minimax-h3 两个（走 `/v1/video/generations`）|

⚠ 几个只有实际对着文档才知道的坑：

1. **模型名带空格、中文、甚至全角括号** —— `grok-imagine-video-1.5（按次）` 是全角的，
   `Quality V4 · 480p/720p (可@图/视频/音频)` 带间隔号和半角括号。**照抄，别手打**。
2. **grok 格式不认 `seconds`**，只认 `duration`；比例和分辨率必须放 `extra` 里，
   放顶层无效。
3. **`sd2.5` 和 `dubai_sd25_170` 都固定 30 秒，但行为不同**：前者传别的值会被
   平台**悄悄覆盖**成 30，后者会**直接 400**。所以这里一律先纠正到 30。
4. **查询响应套了一层**：`{"code":"success","data":{status,progress,result_url}}`，
   状态是**大写** `IN_PROGRESS`/`SUCCESS`/`FAILURE`，进度是字符串 `"100%"`。
5. `SD2.0 1080P 933` **至少要 1 张参考图**，没有会失败。
"""

from __future__ import annotations

import json
import os
import time

from .utils import (RespectAPIError, api_request, download_to_output,
                    dynamic_url_inputs, ensure_config,
                    expand_image_frames, extract_image_payloads,
                    resolve_image_to_tensor, tensor_to_b64, tensors_concat)

CATEGORY = "Respect/巨轮"
BASE_HINT = "base_url 填 https://julun.cc（域名不通时可临时用 http://107.148.118.228:3000）"

# 上传素材：单文件 210MB、保留 72 小时
JULUN_UPLOAD_MAX_MB = 210
JULUN_UPLOAD_EXTS = ("jpg", "jpeg", "png", "webp", "mp4", "mov", "m4v",
                     "webm", "avi", "mkv", "mp3", "wav", "m4a", "aac")

R6 = ["16:9", "9:16", "1:1", "21:9", "3:4", "4:3"]
R5 = ["16:9", "1:1", "9:16", "3:4", "4:3"]

# 文档 5.3「各模型请求规格」整张表。**每一项都写进来**，因为这些约束
# 不是「建议」——超了会 400 或 invalid_duration，而 400 之前的等待是白等的。
# fmt: (格式, 时长规则, 分辨率, 比例, 图上限, 视频上限, 音频上限, 备注)
JULUN_SPEC = {
    "SD2.0 Fast": ("metadata", (4, 15), ["720p", "480p"], R6, 9, 0, 0, ""),
    "SD2.0 1080P 933": ("metadata", (15, 15), ["1080P"], ["16:9", "9:16"], 9, 3, 3,
                        "**至少 1 张参考图**；默认开配音，不要可传 generate_audio=false"),
    "sd-2-c8": ("metadata", (10, 15, [10, 15]), ["720p"], ["16:9", "9:16", "1:1"], 9, 3, 3,
                "只有 10 或 15 秒"),
    "sd-2-c6": ("metadata", (4, 15), ["720p"], ["16:9", "9:16", "1:1"], 9, 3, 3, ""),
    "Seedance 图生视频": ("url_media", (4, 15), ["720p"], ["16:9"], 9, 3, 3, "时长必填"),
    "sd2-mini": ("url_media", (4, 15), ["720p"], ["16:9"], 9, 3, 3, ""),
    "Seedance MINI 933": ("url_media", (4, 15), ["720p"], ["16:9"], 9, 3, 3, ""),
    "Quality V4 · 480p/720p (可@图/视频/音频)":
        ("url_media", (5, 15, [5, 10, 15]), ["480p", "720p"],
         ["auto"] + R5, 9, 3, 3, "480p 支持 5/10/15；**720p 只有 10 秒**"),
    "wan3.0th": ("url_media", (4, 30), ["720p"], R5, 10, 5, 5,
                 "**按秒计费** 0.14 元/秒；音频必须 WAV"),
    "seedance-2.5-deal": ("url_media", (4, 15), ["720p"], R5, 30, 10, 10, "音频必须 WAV"),
    "sd2-c7": ("openai_refs", (5, 15), ["720p"], R6, 9, 0, 0, ""),
    "sd2.5": ("openai_refs", (30, 30), ["720p"], R6, 10, 0, 0,
              "**固定 30 秒**；传别的值平台会悄悄覆盖成 30"),
    "dubai_sd25_170": ("openai_refs", (30, 30), ["720p"], R6, 10, 0, 0,
                       "**固定 30 秒，传别的直接 400**；用有限人脸账号，每日 00:00 重置"),
    "grok-imagine-video-1.5（按次）":
        ("grok", (6, 3600), ["720p", "480p"], ["16:9", "9:16", "1:1"], 7, 0, 0,
         "时长必填、**不认 seconds**；比例和分辨率放 extra 里"),
    "grok-imagine-video-1.5-preview":
        ("grok", (6, 3600), ["720p", "480p"], ["16:9", "9:16", "1:1"], 7, 0, 0,
         "同上"),
    "minimax-h3 768p": ("simple", (6, 10, [6, 10]), ["768p"], [], 1, 0, 0,
                        "走 /v1/video/generations；参考图只 1 张"),
    "minimax-h3 2k": ("simple", (6, 10, [6, 10]), ["2k"], [], 1, 0, 0, "同上"),
}
JULUN_VIDEO_MODELS = list(JULUN_SPEC)
JULUN_IMAGE_MODELS = ["doubao-seedream-5-0-260128"]
JULUN_GROK_ROLES = ["reference_image", "首尾帧(first_frame+last_frame)"]

_ALL_RATIOS = ["(按模型默认)", "auto"] + R6
_ALL_RES = ["(按模型默认)", "480p", "720p", "768p", "1080P", "2k"]


def _lines(s: str, cap: int) -> list:
    return [ln.strip() for ln in (s or "").splitlines() if ln.strip()][:cap]


def _spec(model: str) -> tuple:
    """模型 → 规格。认不出的按 url_media 走（这家最通用的一套）。"""
    return JULUN_SPEC.get(model, ("url_media", (4, 15), ["720p"], R5, 9, 3, 3, ""))


def _fit_duration(model: str, want: int) -> int:
    """按规格表收敛时长。**只在有明确依据时改**，并且改了要说。"""
    rule = _spec(model)[1]
    lo, hi = rule[0], rule[1]
    allowed = rule[2] if len(rule) > 2 else None
    sec = int(want)
    if allowed:
        if sec not in allowed:
            near = min(allowed, key=lambda a: abs(a - sec))
            print(f"[Respect] 巨轮 {model} 只支持 {allowed} 秒，已把 {sec} 纠正为 {near}")
            return near
        return sec
    if sec < lo or sec > hi:
        near = max(lo, min(hi, sec))
        print(f"[Respect] 巨轮 {model} 时长范围 {lo}–{hi} 秒，已把 {sec} 纠正为 {near}")
        return near
    return sec


def _julun_poll(cfg, task_id: str, interval: int, timeout: int) -> str:
    """轮询任务。

    这家的查询响应**套了一层**：`{"code":"success","data":{…}}`，
    状态是**大写** `IN_PROGRESS`/`SUCCESS`/`FAILURE`，进度是字符串 `"100%"`，
    成片地址在 `data.result_url`（只有 SUCCESS 才有）。
    通用解析器认不出这套，所以单独写。
    """
    start, last = time.time(), ""
    while time.time() - start < timeout:
        resp = api_request(cfg, "GET", f"/v1/videos/{task_id}", retries=1, timeout=60)
        data = resp.json() if resp.content else {}
        inner = (data.get("data") or {}) if isinstance(data, dict) else {}
        status = str(inner.get("status") or "").upper()
        if status != last:
            print(f"[Respect] 巨轮 {task_id}: {status} {inner.get('progress', '')}")
            last = status
        if status == "FAILURE":
            reason = inner.get("fail_reason") or ""
            raise RespectAPIError(
                f"巨轮任务失败：{reason or json.dumps(data, ensure_ascii=False)[:300]}\n"
                f"（文档：失败任务**不扣费**，会自动原路退回）")
        if status == "SUCCESS":
            url = inner.get("result_url") or ""
            if url:
                return url
            # 文档说 result_url 只在 SUCCESS 时给；没给就退回下载端点
            base = cfg.normalized_base().rsplit("/v1", 1)[0]
            return f"{base}/v1/videos/{task_id}/content"
        time.sleep(interval)
    raise RespectAPIError(f"巨轮任务超时：{task_id}（文档说一般 1–3 分钟，高峰更久，可调大 poll_timeout）")


# ---------------------------------------------------------------------------
# ① 巨轮 视频（17 个模型，五种格式自动分派）
# ---------------------------------------------------------------------------


class RespectJulunVideo:
    """巨轮 视频（文档五）。17 个模型、**五种请求格式**，选模型就等于选格式。

    参考素材**必须公网可访问**——可以先用『巨轮 上传素材』节点换成平台 URL
    （保留 72 小时），也可以接『Respect 对象存储上传』。

    每个模型的时长/比例/素材上限都按文档 5.3 的规格表在**提交前**校验，
    超了当场说清楚 —— 这家的时长不合规会回 `invalid_duration`，
    而那之前的排队时间是白等的。
    """

    DESCRIPTION = ("巨轮视频（julun.cc）。17 个模型五种格式自动分派（metadata/url_media/"
                   "openai_refs/grok/simple）；时长比例素材上限按文档规格表提交前校验。"
                   "参考素材只收公网URL，可用『巨轮 上传素材』换。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": BASE_HINT}),
                "model": (JULUN_VIDEO_MODELS, {"default": "sd2.5", "tooltip": "选模型即选请求格式；各自的时长/素材上限见规格表"}),
                "prompt": ("STRING", {"default": "", "multiline": True, "tooltip": "文档建议 ≤2000 字，超长会 prompt_too_long"}),
                "duration": ("INT", {"default": 10, "min": 4, "max": 3600, "tooltip": "按所选模型的规格自动纠正；grok 系可到 3600"}),
                "aspect_ratio": (_ALL_RATIOS, {"default": "(按模型默认)"}),
                "resolution": (_ALL_RES, {"default": "(按模型默认)"}),
                "poll_interval": ("INT", {"default": 6, "min": 3, "max": 60, "tooltip": "文档建议 3–10 秒"}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "参考图公网URL（接『巨轮 上传素材』或『对象存储上传』）"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "extra_image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "追加参考图URL，每行一个"}),
                "video_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考视频URL，每行一个（仅部分模型支持）"}),
                "audio_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考音频URL，每行一个（wan3.0th/seedance-2.5-deal 要 WAV）"}),
                "grok_ref_mode": (JULUN_GROK_ROLES, {"default": "reference_image", "tooltip": "仅 grok 系：选首尾帧时前 2 张分别当首帧/末帧，且**不能和普通参考图混用**"}),
                "generate_audio": (["(不传)", "true", "false"], {"default": "(不传)", "tooltip": "仅 SD2.0 1080P 933 支持；其余模型请勿传"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型（名字带空格/全角括号，照抄别手打）"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 30, "step": 1, "tooltip": "参考图URL接口数量；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("成片地址（平台代理，要鉴权）", "下载到本地的路径", "任务 ID —— 出问题拿这个对账")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, duration, aspect_ratio, resolution,
                 poll_interval, poll_timeout, auto_download,
                 extra_image_urls="", video_urls="", audio_urls="",
                 grok_ref_mode="reference_image", generate_audio="(不传)",
                 custom_model="", save_dir="", filename="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        fmt, _rule, res_list, ratios, cap_i, cap_v, cap_a, note = _spec(model)
        sec = _fit_duration(model, duration)
        ratio = ratios[0] if aspect_ratio.startswith("(") and ratios else aspect_ratio
        res = res_list[0] if resolution.startswith("(") and res_list else resolution

        imgs = dynamic_url_inputs(kwargs) + _lines(extra_image_urls, 30)
        vids, auds = _lines(video_urls, 10), _lines(audio_urls, 10)
        bad = [u for u in imgs + vids + auds if not u.startswith(("http://", "https://"))]
        if bad:
            raise RespectAPIError(
                f"巨轮的参考素材必须**公网可访问**，这些不是：{bad[:2]}\n"
                f"用『Respect 巨轮 上传素材』把本地文件换成平台 URL（保留 72 小时），"
                f"或接『Respect 对象存储上传』。")

        problems = []
        if len(imgs) > cap_i:
            problems.append(f"参考图最多 {cap_i} 张，收到 {len(imgs)} 张")
        if vids and cap_v == 0:
            problems.append(f"{model} **不支持参考视频**，收到 {len(vids)} 条")
        elif len(vids) > cap_v:
            problems.append(f"参考视频最多 {cap_v} 条，收到 {len(vids)} 条")
        if auds and cap_a == 0:
            problems.append(f"{model} **不支持参考音频**，收到 {len(auds)} 条")
        elif len(auds) > cap_a:
            problems.append(f"参考音频最多 {cap_a} 条，收到 {len(auds)} 条")
        if ratios and ratio not in ratios:
            problems.append(f"比例只支持 {'、'.join(ratios)}，收到 {ratio}")
        if model == "SD2.0 1080P 933" and not imgs:
            problems.append("这个模型**至少要 1 张参考图**")
        if problems:
            raise RespectAPIError(
                f"巨轮 {model} 的参数不符合规格表：" + "；".join(problems)
                + (f"\n（该模型说明：{note}）" if note else ""))

        # ---- 按格式拼 body ----
        path = "/v1/videos"
        if fmt == "metadata":
            meta: dict = {"duration": sec, "ratio": ratio, "resolution": res}
            content = list(imgs)
            for v in vids:
                content.append({"role": "reference_video", "type": "video_url",
                                "video_url": {"url": v}})
            for a in auds:
                content.append({"role": "reference_audio", "type": "audio_url",
                                "audio_url": {"url": a}})
            if content:
                meta["content"] = content
            if generate_audio in ("true", "false"):
                meta["generate_audio"] = (generate_audio == "true")
            body = {"model": model, "prompt": prompt, "metadata": meta}
        elif fmt == "url_media":
            body = {"model": model, "prompt": prompt, "seconds": sec,
                    "ratio": ratio, "resolution": res}
            if imgs:
                body["image_urls"] = imgs
            if vids:
                body["video_urls"] = vids
            if auds:
                body["audio_urls"] = auds
        elif fmt == "openai_refs":
            body = {"model": model, "prompt": prompt, "duration": sec,
                    "aspect_ratio": ratio}
            if imgs:
                body["image_refs"] = imgs
        elif fmt == "grok":
            # 文档：grok **不认 seconds**；比例分辨率必须在 extra 里
            extra: dict = {"aspect_ratio": ratio, "resolution": res}
            if len(imgs) == 1:
                body = {"model": model, "prompt": prompt, "duration": sec,
                        "input_reference": imgs[0], "extra": extra}
            else:
                if imgs:
                    if grok_ref_mode.startswith("首尾帧"):
                        if len(imgs) < 2:
                            raise RespectAPIError("首尾帧要 2 张图（第1张首帧、第2张末帧）")
                        # 文档：first_frame 与 last_frame **必须成对**，且不能和
                        # reference_image 混用 —— 混了会被拒
                        extra["reference_images"] = [
                            {"url": imgs[0], "role": "first_frame"},
                            {"url": imgs[1], "role": "last_frame"},
                        ]
                        if len(imgs) > 2:
                            print(f"[Respect] 巨轮 grok 首尾帧模式只用前 2 张"
                                  f"（首尾帧不能和普通参考图混用），已忽略 {len(imgs) - 2} 张")
                    else:
                        extra["reference_images"] = [
                            {"url": u, "role": "reference_image"} for u in imgs]
                body = {"model": model, "prompt": prompt, "duration": sec, "extra": extra}
        else:                                        # simple（h3）
            path = "/v1/video/generations"           # 文档：h3 推荐走这个端点
            body = {"model": model, "prompt": prompt, "seconds": sec}
            if imgs:
                body["image_urls"] = imgs[:1]        # h3 只收 1 张

        print(f"[Respect] 巨轮 {model}（{fmt} 格式）: {sec}秒 {ratio} {res} "
              f"图{len(imgs)}/视频{len(vids)}/音频{len(auds)}")
        print(f"[Respect]   POST {path}")
        resp = api_request(cfg, "POST", path, json_body=body,
                           retries=2, timeout=max(cfg.timeout, 300))
        data = resp.json() if resp.content else {}
        task_id = ""
        if isinstance(data, dict):
            task_id = str(data.get("task_id") or data.get("id") or "")
        if not task_id:
            raise RespectAPIError(f"提交没返回任务 ID: {json.dumps(data, ensure_ascii=False)[:400]}")
        print(f"[Respect] 巨轮 任务已提交: {task_id}")

        url = _julun_poll(cfg, task_id, int(poll_interval), int(poll_timeout))
        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="julun",
                                           save_dir=save_dir, filename=filename)
            except Exception as exc:                            # noqa: BLE001
                print(f"[Respect] 巨轮 视频下载失败: {exc}")
        return (url, local, task_id)


# ---------------------------------------------------------------------------
# ② 巨轮 图片（OpenAI 兼容，同步）
# ---------------------------------------------------------------------------


class RespectJulunImage:
    """巨轮 图片（文档四）。`POST /v1/images/generations`，OpenAI 兼容、**同步**返回。

    平台**固定一次出 1 张**（`n` 传别的没用），按张计费 0.04 元，失败不扣费。
    """

    DESCRIPTION = ("巨轮图片（julun.cc）。OpenAI 兼容同步接口，模型 doubao-seedream-5-0-260128；"
                   "平台固定一次 1 张，0.04 元/张，失败不扣费。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": BASE_HINT}),
                "model": (JULUN_IMAGE_MODELS, {"default": JULUN_IMAGE_MODELS[0]}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
            },
            "optional": {
                "size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，OpenAI 语义；不支持的值上游会 400"}),
                "response_format": (["url", "b64_json"], {"default": "url"}),
                "watermark": ("BOOLEAN", {"default": False, "tooltip": "文档默认关闭"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "image_url")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, size="", response_format="url",
                 watermark=False, custom_model=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        body: dict = {"model": model, "prompt": prompt, "n": 1,
                      "response_format": response_format}
        if (size or "").strip():
            body["size"] = size.strip()
        if watermark:
            body["watermark"] = True

        print(f"[Respect] 巨轮 图片 {model}: size={body.get('size', '(不传)')}")
        resp = api_request(cfg, "POST", "/v1/images/generations", json_body=body,
                           retries=2, timeout=max(cfg.timeout, 300))
        data = resp.json() if resp.content else {}
        items = extract_image_payloads(data)
        if not items:
            raise RespectAPIError(f"未能从响应中提取图片: {json.dumps(data, ensure_ascii=False)[:400]}")
        tensors = [t for t in (resolve_image_to_tensor(i, cfg) for i in items) if t is not None]
        if not tensors:
            raise RespectAPIError(f"取到结果但无法解析为图片: {str(items)[:300]}")
        first = next((i for i in items if isinstance(i, str) and i.startswith("http")), "")
        return (tensors_concat(tensors), first)


# ---------------------------------------------------------------------------
# ③ 巨轮 上传素材（本地文件 → 平台 URL，保留 72 小时）
# ---------------------------------------------------------------------------


class RespectJulunUpload:
    """巨轮 上传参考素材（文档 5.9）。`POST /v1/video/uploads`，multipart，字段名 `file`。

    本地图/视频/音频 → 平台公网 URL，直接填进视频节点的参考素材框。
    单文件 ≤210MB，**保留 72 小时**，过期要重传。

    接 IMAGE 或填本地路径都行；两个都给时以 `file_path` 为准。
    """

    DESCRIPTION = ("巨轮 POST /v1/video/uploads：本地素材 → 平台URL（≤210MB，**保留72小时**）。"
                   "接 IMAGE 或填 file_path 都行。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": BASE_HINT}),
            },
            "optional": {
                "image": ("IMAGE", {"tooltip": "接 IMAGE 会转成 PNG 上传"}),
                "file_path": ("STRING", {"default": "", "multiline": False, "placeholder": "本地文件路径（填了优先于上面的 IMAGE）"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("url",)
    OUTPUT_TOOLTIPS = ("平台 URL，填进视频节点的参考素材框（72 小时内有效）",)
    FUNCTION = "upload"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def upload(self, api_config, image=None, file_path=""):
        import base64

        cfg = ensure_config(api_config)
        path = (file_path or "").strip().strip('"')
        if path:
            if not os.path.isfile(path):
                raise RespectAPIError(f"找不到文件: {path}")
            ext = os.path.splitext(path)[1].lstrip(".").lower()
            if ext not in JULUN_UPLOAD_EXTS:
                raise RespectAPIError(
                    f"巨轮只收 {'/'.join(JULUN_UPLOAD_EXTS)}，不收 .{ext}")
            size = os.path.getsize(path)
            if size > JULUN_UPLOAD_MAX_MB * 1024 * 1024:
                raise RespectAPIError(f"{os.path.basename(path)} 有 {size / 1048576:.1f}MB，"
                                      f"超过 {JULUN_UPLOAD_MAX_MB}MB 上限")
            with open(path, "rb") as fh:
                blob = fh.read()
            name = os.path.basename(path)
            ctype = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                     "webp": "image/webp", "mp4": "video/mp4", "mov": "video/quicktime",
                     "wav": "audio/wav", "mp3": "audio/mpeg"}.get(ext, "application/octet-stream")
        else:
            frames = expand_image_frames([image] if image is not None else [])
            if not frames:
                raise RespectAPIError("接一张 IMAGE 或填 file_path")
            b64 = tensor_to_b64(frames[0], fmt="PNG", max_side=2048)
            if not b64:
                raise RespectAPIError("IMAGE 转换失败")
            blob = base64.b64decode(b64[0].split(",", 1)[1])
            name, ctype = "upload.png", "image/png"

        resp = api_request(cfg, "POST", "/v1/video/uploads",
                           files=[("file", (name, blob, ctype))],
                           retries=1, timeout=max(cfg.timeout, 900))
        data = resp.json() if resp.content else {}
        url = data.get("url", "") if isinstance(data, dict) else ""
        if not url:
            raise RespectAPIError(f"上传没返回 url: {json.dumps(data, ensure_ascii=False)[:300]}")
        print(f"[Respect] 巨轮 素材已上传（72 小时内有效）: {url}")
        return (url,)


NODE_CLASS_MAPPINGS = {
    "RespectJulunVideo": RespectJulunVideo,
    "RespectJulunImage": RespectJulunImage,
    "RespectJulunUpload": RespectJulunUpload,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectJulunVideo": "Respect 巨轮 视频（17模型/5种格式）",
    "RespectJulunImage": "Respect 巨轮 图片（doubao-seedream）",
    "RespectJulunUpload": "Respect 巨轮 上传素材（→平台URL/72h）",
}
