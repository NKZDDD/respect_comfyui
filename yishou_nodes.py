"""Respect ComfyUI 扩展 - 一手 / ONE API（`https://www.weijinapi.top`）节点。**只做视频**。

文档给的标准流程：
1. `GET /v1/models` 拿当前 Key 能用的模型**和能力**
2. `POST /v1/videos` 创建任务
3. `GET /v1/videos/{task_id}` 查进度（queued / in_progress / completed / failed）
4. `GET /v1/videos/{task_id}/content` 下载

这家最不一样的一点：**模型能力是接口给的，不是写死的**。每个模型带
`durations_seconds` / `ratios` / `max_images` / `max_videos` / `max_audios` /
`audio_requires_image` / `pricing`，文档明说「字段缺失时以后台说明为准，**不要自行猜测**」。
所以这里不内置模型下拉，`model` 是文本框，配套一个「一手 模型能力」节点先查清楚再填。

三条硬规矩（文档原文）：
- 统一用 `seconds`，**不要** `duration_seconds`
- **不要**提交旧式 `size` 倍率字段
- 图片/音频只收「服务器能直接访问的 HTTPS 地址」；**只有视频**能上传
  （`POST /api/upload/video`，单文件 ≤50MB）
"""

from __future__ import annotations

import json
import os

from .utils import (RespectAPIError, api_request, download_to_output,
                    dynamic_url_inputs, ensure_config)
from .video_nodes import _async_extract_url, _async_poll, _sd2_extract_task_id

CATEGORY = "Respect/一手"

YISHOU_RATIOS = ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9"]
UPLOAD_LIMIT = 50 * 1024 * 1024


def _ys_lines(s: str, cap: int) -> list:
    return [ln.strip() for ln in (s or "").splitlines() if ln.strip()][:cap]


# ---------------------------------------------------------------------------
# ① 一手 模型能力（先查清楚能用什么，再去填视频节点）
# ---------------------------------------------------------------------------


class RespectYishouModels:
    """一手 模型能力查询（`GET /v1/models`）。

    这家不同 Key 能用的模型不同，且**秒数/比例/素材上限/单价都由接口给**。
    先跑这个节点看清单，再把 `id` 填到视频节点的 `model` 里。
    """

    DESCRIPTION = "一手 GET /v1/models：列出当前 Key 可用模型及其秒数/比例/图片视频音频上限/单价。"

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://www.weijinapi.top"}),
            },
            "optional": {
                "filter": ("STRING", {"default": "", "multiline": False, "placeholder": "按关键字过滤模型 id/名称"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("report", "model_ids", "count")
    OUTPUT_TOOLTIPS = ("可读的能力表（接『显示文字』看）", "模型 id 列表，每行一个", "数量")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, api_config, filter=""):
        cfg = ensure_config(api_config)
        resp = api_request(cfg, "GET", "/v1/models", retries=1, timeout=60)
        data = resp.json() if resp.content else {}
        rows, ids = [], []
        kw = (filter or "").strip().lower()
        for m in (data.get("data") or []):
            mid = m.get("id") or ""
            if not mid:
                continue
            name = m.get("display_name") or mid
            if kw and kw not in mid.lower() and kw not in str(name).lower():
                continue
            ids.append(mid)
            pr = m.get("pricing") or {}
            price = f"{pr.get('mode', '?')} {pr.get('amount', '?')}{pr.get('currency', '')}" if pr else "价格未给"
            rows.append(
                f"{mid}\n"
                f"    名称={name}  分辨率={m.get('resolution', '?')}\n"
                f"    秒数={m.get('durations_seconds') or '未给'}  比例={m.get('ratios') or '未给'}\n"
                f"    图≤{m.get('max_images', 0)} 视频≤{m.get('max_videos', 0)} 音频≤{m.get('max_audios', 0)}"
                f"{'（用音频必须同时给图）' if m.get('audio_requires_image') else ''}\n"
                f"    计费={price}"
            )
        if not rows:
            report = "没拿到模型（检查 base_url / api_key，或该 Key 无可用模型）"
        else:
            report = f"一手可用模型 {len(rows)} 个：\n\n" + "\n\n".join(rows)
            report += "\n\n注：字段缺失时以后台模型说明为准，不要自行猜测。"
        print(f"[Respect] 一手 模型 {len(ids)} 个: {', '.join(ids[:8])}{'…' if len(ids) > 8 else ''}")
        return (report, "\n".join(ids), len(ids))


# ---------------------------------------------------------------------------
# ② 一手 视频
# ---------------------------------------------------------------------------


class RespectYishouVideo:
    """一手 视频（`POST /v1/videos` + `GET /v1/videos/{task_id}` 轮询）。

    body：`{model, prompt, seconds, aspect_ratio, images[], videos[], audios[]}`。
    `seconds` 和 `aspect_ratio` **必须是该模型支持的值**（先用「一手 模型能力」查）。
    参考图/音频只收公网 HTTPS；参考视频可用「一手 上传视频」节点换链接。
    """

    DESCRIPTION = ("一手 ONE API 视频。model 必填(先用『一手 模型能力』查)；统一用 seconds、不传 size；"
                   "参考图/音频只收公网HTTPS，参考视频可用『一手 上传视频』换链接。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://www.weijinapi.top"}),
                "model": ("STRING", {"default": "", "multiline": False, "placeholder": "完整模型 ID（从『一手 模型能力』里抄）", "tooltip": "不同 Key 可用模型不同，没有可猜的默认值"}),
                "prompt": ("STRING", {"default": "", "multiline": True, "tooltip": "没有参考素材时必填"}),
                "seconds": ("INT", {"default": 15, "min": 1, "max": 60, "tooltip": "必须是该模型 durations_seconds 里的值"}),
                "aspect_ratio": (YISHOU_RATIOS, {"default": "9:16", "tooltip": "必须是该模型 ratios 里的值"}),
                "poll_interval": ("INT", {"default": 15, "min": 5, "max": 60, "tooltip": "文档推荐 10~30 秒"}),
                "poll_timeout": ("INT", {"default": 2400, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "参考图 HTTPS URL（接对象存储上传）"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "extra_image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "追加参考图URL，每行一个"}),
                "video_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考视频URL，每行一个（用『一手 上传视频』得到）"}),
                "audio_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考音频URL，每行一个（只收公网HTTPS）"}),
                "resolution": ("STRING", {"default": "", "multiline": False, "placeholder": "留空即可；模型固定分辨率时文档建议省略"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 30, "step": 1, "tooltip": "参考图URL接口数量；改完点节点上的『更新输入口』按钮增减 ref_url_N（上限以该模型 max_images 为准）"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("在线视频 URL", "下载到本地的路径（预览/拼接用这个）", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, seconds, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 extra_image_urls="", video_urls="", audio_urls="", resolution="",
                 save_dir="", filename="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (model or "").strip()
        if not model:
            raise RespectAPIError(
                "model 必填 —— 一手不同 Key 可用模型不同，没有可猜的默认值。\n"
                "先接一个『Respect 一手 模型能力』节点跑一次，把里面的模型 id 抄过来。")

        # ref_url_N 数量由 inputcount + 「更新输入口」决定，按数字顺序取
        imgs = dynamic_url_inputs(kwargs)
        imgs += _ys_lines(extra_image_urls, 30)
        vids, auds = _ys_lines(video_urls, 10), _ys_lines(audio_urls, 10)

        bad = [u for u in imgs + vids + auds if not u.startswith(("http://", "https://"))]
        if bad:
            raise RespectAPIError(
                f"参考素材必须是服务器能直接访问的 HTTPS 地址，这些不是：{bad[:2]}\n"
                f"图片/音频请接『Respect 对象存储上传』拿链接；视频可用『Respect 一手 上传视频』。")
        if not (prompt or "").strip() and not imgs:
            raise RespectAPIError("没有参考素材时 prompt 必填（文档：条件必填）")

        body: dict = {
            "model": model,
            "prompt": prompt or "",
            "seconds": int(seconds),          # 文档：统一用 seconds，别用 duration_seconds
            "aspect_ratio": aspect_ratio,     # 必填
        }
        if imgs:
            body["images"] = imgs
        if vids:
            body["videos"] = vids
        if auds:
            body["audios"] = auds
            if not imgs:
                print("[Respect] 提醒：部分模型 audio_requires_image=true，用音频时必须同时给图片"
                      "（以『一手 模型能力』返回的为准）")
        if (resolution or "").strip():
            body["resolution"] = resolution.strip()   # 文档：模型固定分辨率时建议省略

        print(f"[Respect] 一手 提交 {model}: seconds={seconds} aspect_ratio={aspect_ratio} "
              f"图{len(imgs)}/视频{len(vids)}/音频{len(auds)}")
        print(f"[Respect] body={json.dumps(body, ensure_ascii=False)[:400]}")
        resp = api_request(cfg, "POST", "/v1/videos", json_body=body,
                           retries=2, timeout=max(cfg.timeout, 300))
        data = resp.json() if resp.content else {}
        url = _async_extract_url(data)
        task_id = _sd2_extract_task_id(data)
        if not url:
            if not task_id:
                raise RespectAPIError(f"提交没返回任务 ID: {json.dumps(data, ensure_ascii=False)[:400]}")
            # 文档：创建超时不要盲目重投，先拿 task_id 去查（可能已经计费建单）
            url = _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))

        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="yishou", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] 一手 视频下载失败: {exc}")
        return (url, local, task_id or "")


# ---------------------------------------------------------------------------
# ③ 一手 上传视频（本地 mp4 → 公网 HTTPS，放进 videos 数组）
# ---------------------------------------------------------------------------


class RespectYishouUploadVideo:
    """一手 上传参考视频（`POST /api/upload/video`，单文件 ≤50MB）。

    返回的 HTTPS 地址直接填进视频节点的 `参考视频URL`。
    **图片和音频没有上传接口** —— 那两类请用『Respect 对象存储上传』。
    """

    DESCRIPTION = "一手 POST /api/upload/video：本地 mp4(≤50MB) → 公网HTTPS，供视频节点的 videos 用。"

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://www.weijinapi.top"}),
                "file_path": ("STRING", {"default": "", "multiline": False, "placeholder": "本地视频路径（可接『选择/上传本地视频』或视频节点的 local_path）"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_url",)
    FUNCTION = "upload"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def upload(self, api_config, file_path):
        cfg = ensure_config(api_config)
        path = (file_path or "").strip().strip('"')
        if not os.path.isfile(path):
            raise RespectAPIError(f"找不到文件: {path}")
        size = os.path.getsize(path)
        if size > UPLOAD_LIMIT:
            raise RespectAPIError(f"{os.path.basename(path)} 有 {size / 1048576:.1f}MB，"
                                  f"超过一手的 50MB 上传上限")
        with open(path, "rb") as fh:
            blob = fh.read()
        resp = api_request(cfg, "POST", "/api/upload/video",
                           files=[("file", (os.path.basename(path), blob, "video/mp4"))],
                           retries=1, timeout=max(cfg.timeout, 600))
        data = resp.json() if resp.content else {}
        url = _async_extract_url(data) or (data.get("url") if isinstance(data, dict) else "")
        if not url:
            raise RespectAPIError(f"上传没返回地址: {json.dumps(data, ensure_ascii=False)[:300]}")
        print(f"[Respect] 一手 视频已上传: {url}")
        return (url,)


NODE_CLASS_MAPPINGS = {
    "RespectYishouVideo": RespectYishouVideo,
    "RespectYishouModels": RespectYishouModels,
    "RespectYishouUploadVideo": RespectYishouUploadVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectYishouVideo": "Respect 一手 视频",
    "RespectYishouModels": "Respect 一手 模型能力（先查再填）",
    "RespectYishouUploadVideo": "Respect 一手 上传视频（≤50MB）",
}
