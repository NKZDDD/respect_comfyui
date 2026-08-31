"""Respect ComfyUI 扩展 - Gate（`https://api-gate.astralmindai.com`）节点。

协议与 `script-to-video-studio/core/providers/gate.py` 同源（依据《Gate接入文档》
和公开 Schema `GET /public/model_group/info`），两边规格表由脚本比对保持一致。

- 图片 `POST /v1/images/generations`（**同步**）
- 视频 `POST /api/multimodal/create_task` 提交 → `POST /api/multimodal/get_result` 查询

⚠ 三个只有对着 Schema 才知道的坑：

1. **图片不是一套字段硬套所有模型**：
   · Kling 用 `resolution` + `aspect_ratio`（没有 `size`），数量字段叫 `num_images`
   · Qwen 的尺寸分隔符是 `*` 不是 `x`
   · `seedream-4-5` 自定义尺寸下限比本插件默认的 1024x1536 高，只能给 `2K`/`4K`
   · Seedream / Kling 一族**不收 `n`**
   照发服务端会拒绝，或者**静默忽略**——后者更麻烦，你以为设了尺寸其实没设。
2. **GPT 两个图片模型（gpt-image-1 / gpt-image-2）在当前 Schema 里只做文生图**，
   接了参考图不是少几张的问题，是这条路根本没有参考图。
3. **视频的请求体是 `inputs[]` + `metadata{}`，不是扁平字段**：每条素材在
   `inputs` 里独立一项、各带 `format`（`first_frame`/`last_frame`/
   `reference_image`/`reference_video`/`reference_audio`），视频参数放 `metadata`。
   文档原话：「未被模型声明的参数会被**静默丢弃**或被下游拒绝」——
   发扁平的后果是任务建得起来、task_id 也拿得到，但提示词和参考图可能一个都没进去。
4. **查询是 `POST /api/multimodal/get_result`**，body 要 `model` + `taskId`（小驼峰）。
   ⚠ 曾经查的 `GET /v1/videos/{id}` 在文档里**根本不存在**，而 Gate 是 litellm 搭的，
   `/v1/videos/*` 在 litellm 里是 **OpenAI 直通路由** —— 于是它把我们的 task_id
   转发去了 `api.openai.com`，超时回 500。地址是 Gate 拼的，不是 base_url 配错了。
5. 视频参考素材只收**下游能取到的公网 URL**；提交/查询端点都**不在 `/v1` 下**。
"""

from __future__ import annotations

import json
import time

from .utils import (RespectAPIError, api_request, download_to_output,
                    dynamic_image_inputs, dynamic_url_inputs, ensure_config,
                    expand_image_frames, extract_data_array_images,
                    extract_image_payloads, resolve_image_to_tensor,
                    tensor_to_b64, tensors_concat)

CATEGORY = "Respect/Gate"
BASE_HINT = "base_url 填 https://api-gate.astralmindai.com"

GATE_IMAGE_MODELS = [
    "nano-banana", "nano-banana-pro", "seedream-5-0-lite", "nano-banana-2",
    "seedream-5-0-pro", "gpt-image-2", "nano-banana-2-lite", "seedream-4-0",
    "kling-image-o3", "qwen-image-2.0-pro", "qwen-image-2.0", "seedream-4-5",
    "kling-image-v3", "gpt-image-1",
]
GATE_VIDEO_MODELS = [
    "seedance-2.5-official", "seedance-2.0-standard-official",
    "seedance-2.0-fast-official", "seedance-2.0-mini", "seedance-2.0-standard",
    "seedance-2.5", "seedance-2.0-fast",
]
GATE_IMAGE_SIZES = ["1024x1536", "1536x1024", "1024x1024"]
GATE_RATIOS = ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9", "adaptive"]
GATE_RESOLUTIONS = ["720p", "480p"]

# 每个图片模型能收几张参考图。0 = 这条路只做文生图。
GATE_IMAGE_REF_LIMITS = {
    "nano-banana": 14, "nano-banana-pro": 14, "seedream-5-0-lite": 14,
    "nano-banana-2": 14, "seedream-5-0-pro": 10,
    "nano-banana-2-lite": 14, "gpt-image-2": 0, "gpt-image-1": 0,
    "kling-image-v3": 1,
}
GATE_NO_N = {"seedream-5-0-lite", "seedream-5-0-pro", "seedream-4-0",
             "seedream-4-5", "kling-image-o3", "kling-image-v3"}
GATE_KLING = {"kling-image-o3", "kling-image-v3"}


def _gate_root(cfg) -> str:
    """去掉 `/v1` 的根地址。

    `normalized_base()` 会**给 base_url 补上 `/v1`**，而 Gate 的提交端点是
    `/api/multimodal/create_task` —— 不在 `/v1` 下。直接交给 api_request 拼会拼成
    `…/v1/api/multimodal/create_task`（404），所以这里自己拼绝对地址。
    """
    return cfg.normalized_base().rsplit("/v1", 1)[0]


# 逐模型硬约束，**直接来自 /public/model_group/info 实拉**（2026-08-31）。
# 文档正文写「图片最多 9 张」只对 2.0 系成立，后面跟着「具体以模型 Schema 为准」。
#
# `banned` 是这家**主动声明**的不支持参数。Schema 里 seed 那条原话：
#   "Unsupported by Seedance 2.0 series; declared for explicit validation
#    instead of silent dropping."
# 它宁可显式拒绝也不静默丢弃。我们照做。
GATE_VIDEO_SPEC = {
    "seedance-2.0-fast": dict(
        duration=(4, 15), resolutions=["480p", "720p", "1080p", "4k"],
        max_images=9, max_videos=3, max_audios=3,
        banned=["camera_fixed", "draft", "frames", "seed", "service_tier"],
        audio_requires=["image_url", "video_url"]),
    "seedance-2.0-fast-official": dict(
        duration=(4, 15), resolutions=["480p", "720p"],
        max_images=9, max_videos=3, max_audios=3,
        banned=["camera_fixed", "draft", "frames", "seed", "service_tier"],
        audio_requires=["image_url", "video_url"]),
    "seedance-2.0-mini": dict(
        duration=(4, 15), resolutions=["480p", "720p"],
        max_images=9, max_videos=3, max_audios=3,
        banned=["camera_fixed", "draft", "frames", "seed", "service_tier"],
        audio_requires=["image_url", "video_url"]),
    "seedance-2.0-standard": dict(
        duration=(4, 15), resolutions=["480p", "720p", "1080p", "4k"],
        max_images=9, max_videos=3, max_audios=3,
        banned=["camera_fixed", "draft", "frames", "seed", "service_tier"],
        audio_requires=["image_url", "video_url"]),
    "seedance-2.0-standard-official": dict(
        duration=(4, 15), resolutions=["480p", "720p", "1080p", "4k"],
        max_images=9, max_videos=3, max_audios=3,
        banned=["camera_fixed", "draft", "frames", "seed", "service_tier"],
        audio_requires=["image_url", "video_url"]),
    "seedance-2.5": dict(
        duration=(4, 30), resolutions=["480p", "720p"],
        max_images=30, max_videos=10, max_audios=10,
        banned=["draft"], audio_requires=None),
    "seedance-2.5-official": dict(
        duration=(4, 30), resolutions=["480p", "720p"],
        max_images=30, max_videos=10, max_audios=10,
        banned=["draft"], audio_requires=None),
}


def gate_spec(model: str) -> dict:
    """认不出的按 2.0 系最保守的一套走，别拿猜的上限放行。"""
    return GATE_VIDEO_SPEC.get(model, GATE_VIDEO_SPEC["seedance-2.0-mini"])


def _ratio_for_size(size: str) -> str:
    """`宽x高` → Kling 要的宽高比字段。"""
    try:
        w, h = (int(x) for x in str(size).lower().split("x", 1))
    except (TypeError, ValueError):
        return "1:1"
    pairs = {(9, 16): "9:16", (16, 9): "16:9", (1, 1): "1:1",
             (4, 3): "4:3", (3, 4): "3:4", (3, 2): "3:2", (2, 3): "2:3"}
    return min(pairs.items(), key=lambda kv: abs(w / h - kv[0][0] / kv[0][1]))[1]


def _image_shape(model: str, size: str) -> dict:
    """按模型给出**它自己认的**尺寸字段。

    发错的后果分两种，第二种更麻烦：
      · 服务端直接拒绝 —— 至少你知道出事了
      · 服务端**静默忽略** —— 你以为设了尺寸，其实出的是它的默认值
    """
    wanted = str(size or "1024x1536")
    if model in GATE_KLING:
        return {"resolution": "1K", "aspect_ratio": _ratio_for_size(wanted)}
    if model.startswith("qwen-image-2.0"):
        return {"size": wanted.replace("x", "*").replace("X", "*")}
    if model == "seedream-4-5":
        return {"size": wanted if wanted in ("2K", "4K") else "2K"}
    return {"size": wanted}


class RespectGateImage:
    """Gate 图片。`POST /v1/images/generations`，同步返回。"""

    DESCRIPTION = ("Gate 图片(base_url=https://api-gate.astralmindai.com)。14 个模型，"
                   "**尺寸字段按模型不同**(Kling 用 resolution+aspect_ratio、Qwen 用 * 分隔、"
                   "seedream-4-5 只收 2K/4K)；gpt-image-1/2 只做文生图。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": BASE_HINT}),
                "model": (GATE_IMAGE_MODELS, {"default": "seedream-5-0-pro"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "size": (GATE_IMAGE_SIZES, {"default": "1024x1536",
                                            "tooltip": "会按模型转成它认的字段；seedream-4-5 只收 2K/4K，会自动改成 2K"}),
                "n": ("INT", {"default": 1, "min": 1, "max": 4,
                              "tooltip": "Kling 走 num_images；Seedream 一族不收这个字段，会自动不发"}),
            },
            "optional": {
                "image_1": ("IMAGE", {"tooltip": "参考图；接批次会展开。gpt-image-1/2 不收参考图，接了会报错而不是悄悄丢"}),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 14, "step": 1,
                                       "tooltip": "参考图接口数量；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("image", "image_url", "model_used", "image_urls", "count")
    OUTPUT_TOOLTIPS = ("所有返回的图拼成的批次", "第一张的链接", "实际用的模型",
                       "全部链接，每行一个", "这次拿到几张")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, size, n,
                 custom_model="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        frames = expand_image_frames(dynamic_image_inputs(kwargs))
        limit = GATE_IMAGE_REF_LIMITS.get(model, 14)
        if frames and not limit:
            raise RespectAPIError(
                f"Gate 的 {model} 在当前 Schema 里**只做文生图**，接了 {len(frames)} 张参考图。\n"
                f"少了参考图出来的就不是同一个人，所以这一条不出，不会悄悄丢掉。\n"
                f"要用参考图请换 Seedream / Nano Banana / Qwen / Kling 系模型。")
        if len(frames) > limit:
            raise RespectAPIError(
                f"Gate 的 {model} 最多 {limit} 张参考图，这一项接了 {len(frames)} 张。\n"
                f"**不会自动裁掉多的** —— 裁掉哪张都会让画面里少一个人，而且不报错。")

        body: dict = {"model": model, "prompt": prompt}
        body.update(_image_shape(model, size))
        if model in GATE_KLING:
            body["num_images"] = int(n)
        elif model not in GATE_NO_N:
            body["n"] = int(n)
        if frames:
            refs = [b for f in frames for b in tensor_to_b64(f, fmt="PNG", max_side=2048)]
            body["image"] = refs[0] if len(refs) == 1 else refs

        shape = body.get("size") or f"{body.get('resolution')} {body.get('aspect_ratio')}"
        print(f"[Respect] Gate 图片 {model}: 尺寸字段={shape} 参考图{len(frames)}张")
        resp = api_request(cfg, "POST", "/v1/images/generations",
                           json_body=body, retries=1, timeout=max(cfg.timeout, 600))
        data = resp.json() if resp.content else {}
        items = extract_data_array_images(data) or extract_image_payloads(data)
        if not items:
            raise RespectAPIError(
                f"Gate 没返回可用图片：{json.dumps(data, ensure_ascii=False)[:400]}")

        tensors = [t for t in (resolve_image_to_tensor(i, cfg) for i in items) if t is not None]
        if not tensors:
            raise RespectAPIError(
                f"Gate 返回了 {len(items)} 项，但一项都解析不成图片。\n"
                f"上面那行 `[Respect] 图片解析失败：…` 写了具体原因。\n"
                f"首项开头：{str(items[0])[:120]}…")
        urls = [i for i in items if isinstance(i, str) and i.startswith("http")]
        return (tensors_concat(tensors), urls[0] if urls else "", model,
                "\n".join(urls), len(tensors))


class RespectGateVideo:
    """Gate 视频。`POST /api/multimodal/create_task` → `POST /api/multimodal/get_result`。"""

    DESCRIPTION = ("Gate 视频(base_url=https://api-gate.astralmindai.com)。请求体是 "
                   "**inputs[]+metadata{}**，不是扁平字段；查询走 POST get_result。"
                   "2.5 系 4-30 秒/30图·10视频·10音频；2.0 系 4-15 秒/9图·3视频·3音频。"
                   "⚠ 参考素材只收**下游能取到的公网 URL**。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": BASE_HINT}),
                "model": (GATE_VIDEO_MODELS, {"default": "seedance-2.5"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "seconds": ("INT", {"default": 15, "min": 4, "max": 30,
                                    "tooltip": "2.5 系 4-30；2.0 系只到 15（超了当场报，不白等排队）"}),
                "ratio": (GATE_RATIOS, {"default": "9:16"}),
                "resolution": (GATE_RESOLUTIONS, {"default": "720p",
                                                  "tooltip": "1080p/4k 只有 2.0-standard 和 2.0-fast 有"}),
                "poll_interval": ("INT", {"default": 5, "min": 2, "max": 60,
                                          "tooltip": "文档建议 2~5 秒"}),
                "poll_timeout": ("INT", {"default": 2400, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "ref_url_1": ("STRING", {"default": "", "multiline": False,
                                         "placeholder": "参考图公网 URL（只收 http/https）"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "video_urls": ("STRING", {"default": "", "multiline": True,
                                          "placeholder": "参考视频 URL，每行一个"}),
                "audio_urls": ("STRING", {"default": "", "multiline": True,
                                          "placeholder": "参考音频 URL，每行一个。⚠2.0 系必须同时给图或视频"}),
                "generate_audio": ("BOOLEAN", {"default": True}),
                "watermark": ("BOOLEAN", {"default": False}),
                "first_last": ("BOOLEAN", {"default": False,
                                           "tooltip": "开启后前两张参考图当首帧/末帧（format=first_frame/last_frame）"}),
                "priority": ("INT", {"default": 0, "min": 0, "max": 9,
                                     "tooltip": "0~9，越大越优先"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 30, "step": 1,
                                       "tooltip": "参考图 URL 接口数量；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("在线视频 URL", "下载到本地的路径", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, seconds, ratio, resolution,
                 poll_interval, poll_timeout, auto_download,
                 video_urls="", audio_urls="", generate_audio=True, watermark=False,
                 first_last=False, priority=0, custom_model="", save_dir="",
                 filename="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        spec = gate_spec(model)
        images = dynamic_url_inputs(kwargs)
        videos = [ln.strip() for ln in (video_urls or "").splitlines() if ln.strip()]
        audios = [ln.strip() for ln in (audio_urls or "").splitlines() if ln.strip()]
        sec, lo, hi = int(seconds), *spec["duration"]

        problems = []
        if not lo <= sec <= hi:
            problems.append(f"时长只支持 {lo}–{hi} 秒，填的是 {sec} 秒")
        if resolution not in spec["resolutions"]:
            problems.append(f"分辨率只支持 {'、'.join(spec['resolutions'])}，选的是 {resolution}")
        for got, cap, what in ((images, spec["max_images"], "图片"),
                               (videos, spec["max_videos"], "视频"),
                               (audios, spec["max_audios"], "音频")):
            if len(got) > cap:
                problems.append(f"{what}素材最多 {cap} 个，给了 {len(got)} 个")
        if audios and spec["audio_requires"] and not (images or videos):
            problems.append(f"{model} 的音频素材必须搭配参考图或参考视频一起给（Schema 的 x-requires-any-of）")
        bad = [r for r in images + videos + audios
               if not str(r).startswith(("http://", "https://"))]
        if bad:
            problems.append(f"参考素材必须是**下游能取到的公网 URL**，有 {len(bad)} 条不是")
        if first_last and len(images) < 2:
            problems.append("开了首尾帧但参考图不足 2 张")
        if problems:
            raise RespectAPIError(
                f"Gate {model} 的参数不符合它的 Schema：\n  · " + "\n  · ".join(problems)
                + "\n现在就停，别让排队时间和钱白花。")

        # 每条素材是 inputs[] 里**独立一项**，各带自己的 format —— 不是数组字段
        inputs = [{"name": "prompt", "value": prompt, "format": "text"}]
        for n, url in enumerate(images):
            fmt = "reference_image"
            if first_last:
                fmt = "first_frame" if n == 0 else "last_frame" if n == 1 else "reference_image"
            inputs.append({"name": "image_url", "value": url, "format": fmt})
        for url in videos:
            inputs.append({"name": "video_url", "value": url, "format": "reference_video"})
        for url in audios:
            inputs.append({"name": "audio_url", "value": url, "format": "reference_audio"})

        body = {
            "model": model,
            "inputs": inputs,
            "metadata": {"ratio": ratio, "duration": sec, "resolution": resolution,
                         "watermark": bool(watermark),
                         "generate_audio": bool(generate_audio)},
        }
        if int(priority):
            body["priority"] = int(priority)

        print(f"[Respect] Gate 视频 {model}: {sec}s {resolution} {ratio} "
              f"素材 {len(inputs) - 1} 项（图{len(images)}/视频{len(videos)}/音频{len(audios)}）")
        resp = api_request(cfg, "POST", f"{_gate_root(cfg)}/api/multimodal/create_task",
                           json_body=body, retries=1, timeout=300)
        data = resp.json() if resp.content else {}
        task_id = str(data.get("task_id") or "") if isinstance(data, dict) else ""
        if not task_id:
            raise RespectAPIError(
                f"Gate 创建任务没返回 task_id：{json.dumps(data, ensure_ascii=False)[:400]}")

        video_url = _gate_poll(cfg, model, task_id, int(poll_interval), int(poll_timeout))
        local = ""
        if auto_download and video_url:
            try:
                local = download_to_output(video_url, cfg, prefix="gate_video",
                                           save_dir=save_dir, filename=filename)
            except Exception as exc:                        # noqa: BLE001
                print(f"[Respect] Gate 视频下载失败（链接仍可用）：{exc}")
        return (video_url, local, task_id)


def _gate_result_url(payload) -> str:
    """从 get_result 响应取成片地址。

    文档 4.4 的成功响应把它放在两处，两处都取：
      results[].parameters[] 里 name == "video_url" 的 value（官方列出的取值口）
      results[].result.content.video_url
    """
    if not isinstance(payload, dict):
        return ""
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        for par in item.get("parameters") or []:
            if (isinstance(par, dict) and par.get("name") == "video_url"
                    and isinstance(par.get("value"), str)
                    and par["value"].startswith("http")):
                return par["value"]
        url = ((item.get("result") or {}).get("content") or {}).get("video_url")
        if isinstance(url, str) and url.startswith("http"):
            return url
    return ""


def _gate_poll(cfg, model: str, task_id: str, interval: int, timeout: int) -> str:
    """查询任务。**POST /api/multimodal/get_result，body 要 model + taskId（小驼峰）。**

    ⚠ 这里以前查的是 `GET /v1/videos/{id}` —— 那个端点在 Gate 的文档里**根本没有**，
    是编的。而 Gate 是 litellm 搭的网关，`/v1/videos/*` 在 litellm 里是 **OpenAI 直通
    路由**，于是它把我们的 task_id 转发去了 `api.openai.com/v1/videos/{uuid}`，
    超时回 500，日志刷一屏 `litellm.APIConnectionError`。
    地址是 Gate 拼的，不是 base_url 配错了。
    """
    start, last, stuck = time.time(), "", 0
    while time.time() - start < timeout:
        try:
            resp = api_request(cfg, "POST", f"{_gate_root(cfg)}/api/multimodal/get_result",
                               json_body={"model": model, "taskId": task_id},
                               retries=1, timeout=60)
            data = resp.json() if resp.content else {}
            stuck = 0
        except Exception as exc:                            # noqa: BLE001
            # 同一个错一直回 = 端点/参数不对，不是网络抖动。别拖满超时。
            stuck += 1
            if stuck >= 3:
                raise RespectAPIError(
                    f"Gate 查询任务连续 {stuck} 次同样失败，停止等待：{exc}\n"
                    f"任务 {task_id} 可能仍在它那边跑。这类错重试无意义 —— "
                    f"多半是端点或参数不对。")
            print(f"[Respect] Gate 查询出错（第 {stuck} 次，继续）：{exc}")
            time.sleep(interval)
            continue

        status = str(data.get("status") or "").lower() if isinstance(data, dict) else ""
        if status != last:
            print(f"[Respect] Gate {task_id}: {status or '(无状态字段)'}")
            last = status
        if status == "failed":
            raise RespectAPIError(
                f"Gate 任务失败：{json.dumps(data.get('error'), ensure_ascii=False)[:300]}")
        url = _gate_result_url(data)
        if url:
            return url
        if status == "success":
            raise RespectAPIError(
                f"Gate 说任务成功了，但 results 里没有 video_url："
                f"{json.dumps(data, ensure_ascii=False)[:400]}")
        time.sleep(interval)
    raise RespectAPIError(f"Gate 任务超时：{task_id}（文档建议 2~5 秒轮询，可调大 poll_timeout）")


NODE_CLASS_MAPPINGS = {
    "RespectGateImage": RespectGateImage,
    "RespectGateVideo": RespectGateVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectGateImage": "Respect Gate 图片",
    "RespectGateVideo": "Respect Gate 视频",
}
