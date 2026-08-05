"""Respect ComfyUI 扩展 - 小裴 API 视频分支（按 3.3.25 文档补齐）。

`seedance_nodes.py` / `video_nodes.py` 已覆盖：Grok 常规、HappyHorse 官方、低价多渠道、
SD2.0 全系原不卡蒸（按秒）。本模块补齐文档里字段结构**明显不同**的其余分支：

| 节点 | 文档分支 | 关键字段 |
|---|---|---|
| SD2 全系/火山官方（按秒） | #13 #14 | `start_image_url` / `end_image_url` / `extra_images` / `extra_videos` / `extra_audios` |
| SD2 最低渠道（卡蒸） | #15 | **双端点**：文生·单首帧 → `/v1/videos`(`input_reference`)；其余 → `/v1/video/generations`(`image_references[]`) |
| VEO 视频生成 | #9 | `image_urls`（1张=首帧，2张=首尾帧）+ 固定 `resolution:720p` `generate_audio:true` |
| Omni 视频生成/编辑 | #8 | `first_image_url` / `last_image_url` / `images`(≤5) / `video_url` / `videos`(≤2)，固定 `seconds:"10"` |
| SD 轮换渠道 | #10 | `first_frame_url` / `last_frame_url` / `reference_image_urls` / `reference_videos` / `reference_audios` |
| SD2 按次 / ad渠道 | #11 #12 | **嵌套** `input{prompt, media:[{type,url}]}` + `seconds` + `size`(WxH) |
| Grok 16/20秒 | #4 | `seconds`(字符串) + `size`(WxH) + `image_reference`（单首帧），轮询优先用返回的 `status_url` |

共同点：都 `POST /v1/videos`（除注明的多参考路径），轮询 `GET /v1/videos/{task_id}`，
参考素材要公网 URL 的一律走「共享素材上传」(`_upload_reference` / `_upload_local_file`)。
"""

from __future__ import annotations

import json
import time
import uuid

from .utils import RespectAPIError, api_request, download_to_output, ensure_config
from .seedance_nodes import _upload_local_file, _upload_reference
from .video_nodes import (
    _ASYNC_DONE,
    _ASYNC_FAIL,
    _async_extract_url,
    _async_poll,
    _async_status,
    _sd2_extract_task_id,
)

CATEGORY = "Respect/小裴"

XP_ASPECTS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"]
XP_MODES = ["文生视频", "首帧生成视频", "首尾帧生成视频", "多参考图生成视频", "首帧+参考图生成视频"]

# --- 各分支模型（照 3.3.25 文档第 2 节的「实际 model 值」原样） ---
XP_SD2_NATIVE_MODELS = [           # #13 全系原卡蒸（按秒）
    "sd2-480fast（全系按秒）", "sd2-480max（全系按秒）",
    "sd2-720fast（全系按秒）", "sd2-720max（全系按秒）",
    "sd2-1080fast（全系按秒）", "sd2-1080max（全系按秒）",
]
XP_SD2_VOLC_MODELS = [             # #14 官方即梦全系卡蒸（按秒）
    "火山官方sd2-480fast（按秒）", "火山官方sd2-480max（按秒）",
    "火山官方sd2-720fast（按秒）", "火山官方sd2-720max（按秒）",
    "火山官方sd2-1080max（按秒）",
]
XP_SD2_LOWEST_MODELS = [           # #15 sd-2.0 最低渠道（卡蒸）
    "sd-2.0-480满血（卡蒸）最低渠道", "sd-2.0-480fast（卡蒸）最低渠道",
    "sd-2.0-720满血（卡蒸）最低渠道", "sd-2.0-720fast（卡蒸）最低渠道",
    "sd-2.0-1080满血（卡蒸）最低渠道",
]
XP_SD_ROTATE_MODELS = [            # #10 sd 轮换渠道（动态调价）
    "sd-720fast-不卡蒸（按次）", "sd-720满血-较快（按次）", "sd-720满血-不卡蒸（按次）",
    "sd-720fast（按秒）", "sd-720满血（按秒）",
]
XP_SD2_PERUSE_MODELS = [           # #11 全系渠道卡蒸（按次）
    "sd-480-fast-渠道9:16（按次）", "sd-480-fast-渠道16:9（按次）",
    "sd-720-fast-渠道9:16（按次）", "sd-720-fast-渠道16:9（按次）",
    "sd-720-max-渠道9:16（按次）", "sd-720-max-渠道16:9（按次）",
]
XP_SD2_AD_MODELS = [               # #12 全系 ad 渠道卡蒸（按次）
    "sd2.0-480fast-ad渠道16x9", "sd2.0-480fast-ad渠道9x16",
    "sd2.0-480满血-ad渠道16x9", "sd2.0-480满血-ad渠道9x16",
    "sd2.0-720fast-ad渠道16x9", "sd2.0-720fast-ad渠道9x16",
    "sd2.0-720满血-ad渠道16x9", "sd2.0-720满血-ad渠道9x16",
    "sd2.0-1080满血-ad渠道16x9", "sd2.0-1080满血-ad渠道9x16",
]
XP_OMNI_MODELS = [                 # #8 omni
    "omni-fast-视频生成（无水印）", "omni-fast-视频生成（带水印）",
    "omni-fast-视频编辑（无水印）", "omni-fast-视频编辑（带水印）",
]
XP_GROK16_MODELS = ["grok-1.5-支持16s", "grok-1.0-支持16s"]   # #4
XP_GROK16_SECONDS = ["6", "10", "12", "16", "20"]
XP_GROK16_SIZES = {                # 文档给的比例→size 对照
    "9:16": "720x1280", "16:9": "1280x720", "1:1": "1024x1024",
    "4:7": "1024x1792", "7:4": "1792x1024",
}
XP_SD2_PERUSE_SIZES = ["480x854", "854x480", "720x1280", "1280x720", "1080x1920", "1920x1080"]
XP_RESOLUTIONS = ["480p", "720p", "1080p"]


# ---------------------------------------------------------------------------
# 共用小工具
# ---------------------------------------------------------------------------


def _xp_lines(s: str, cap: int = 3) -> list[str]:
    return [ln.strip() for ln in (s or "").splitlines() if ln.strip()][:cap]


def _xp_media_urls(cfg, tensors: list, url_text: str, cap: int = 9) -> list[str]:
    """参考图 → 公网 URL 列表：填了 URL 优先，否则把 IMAGE 上传换 URL。"""
    urls = _xp_lines(url_text, cap)
    if urls:
        return urls
    out: list[str] = []
    for i, t in enumerate(tensors, start=1):
        if t is None or (hasattr(t, "numel") and t.numel() == 0):
            continue
        out.append(_upload_reference(cfg, t, i))
        if len(out) >= cap:
            break
    return out


def _xp_local_or_urls(cfg, url_text: str, path_text: str, cap: int = 3) -> list[str]:
    """参考视频/音频：URL 直用；本地路径自动上传换 URL。"""
    out = _xp_lines(url_text, cap)
    for p in _xp_lines(path_text, cap):
        if len(out) >= cap:
            break
        out.append(_upload_local_file(cfg, p))
    return out[:cap]


def _xp_brief(body: dict) -> str:
    def shrink(v):
        if isinstance(v, str):
            if v.startswith("data:"):
                return f"<{v.split(',', 1)[0]} {len(v)}字符>"
            return v if len(v) <= 90 else v[:87] + "…"
        if isinstance(v, list):
            return [shrink(x) for x in v]
        if isinstance(v, dict):
            return {k: shrink(x) for k, x in v.items()}
        return v
    return json.dumps({k: shrink(v) for k, v in body.items()}, ensure_ascii=False)


def _xp_submit(cfg, path: str, body: dict, headers: dict | None = None) -> tuple[str, str, str]:
    """提交并返回 (直链URL, task_id, status_url)。status_url 用于 Grok 16秒分支优先轮询。"""
    print(f"[Respect] 小裴 提交 {path}  body={_xp_brief(body)}")
    resp = api_request(cfg, "POST", path, json_body=body, headers=headers,
                       retries=2, timeout=max(cfg.timeout, 300))
    data = resp.json() if resp.content else {}
    status_url = ""
    for k in ("status_url", "statusUrl", "task_url"):
        v = data.get(k) if isinstance(data, dict) else None
        if isinstance(v, str) and v.startswith("http"):
            status_url = v
            break
    return _async_extract_url(data), _sd2_extract_task_id(data), status_url


def _xp_poll_url(cfg, status_url: str, interval: int, timeout: int) -> str:
    """按创建响应给的 status_url 轮询（Grok 16 秒分支）。"""
    start, last = time.time(), ""
    while time.time() - start < timeout:
        try:
            resp = api_request(cfg, "GET", status_url, retries=1, timeout=60)
        except RespectAPIError as exc:
            print(f"[Respect] status_url 轮询出错，继续重试: {exc}")
            time.sleep(interval)
            continue
        data = resp.json() if resp.content else {}
        status, url = _async_status(data), _async_extract_url(data)
        if status and status != last:
            print(f"[Respect] 任务状态: {status}")
            last = status
        if status in _ASYNC_FAIL:
            raise RespectAPIError(f"任务失败: {json.dumps(data, ensure_ascii=False)[:400]}")
        if url and (not status or status in _ASYNC_DONE):
            return url
        time.sleep(interval)
    raise RespectAPIError("status_url 轮询超时")


def _xp_finish(cfg, url: str, task_id: str, prefix: str, auto_download: bool,
               save_dir: str, filename: str) -> tuple[str, str, str]:
    local = ""
    if auto_download and url:
        try:
            local = download_to_output(url, cfg, prefix=prefix, save_dir=save_dir, filename=filename)
        except Exception as exc:
            print(f"[Respect] {prefix} 下载失败: {exc}")
    return (url, local, task_id or "")


def _xp_common_inputs(models: list, default_model: str, *, aspects=None,
                      duration=(6, 4, 15), with_mode=True) -> dict:
    """各分支共用的 required 部分，减少重复。"""
    req: dict = {
        "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 默认 https://api.aicopy.top"}),
        "model": (models, {"default": default_model}),
        "prompt": ("STRING", {"default": "", "multiline": True}),
    }
    if with_mode:
        req["generation_mode"] = (XP_MODES, {"default": "首帧生成视频"})
    if duration:
        d, lo, hi = duration
        req["duration"] = ("INT", {"default": d, "min": lo, "max": hi})
    req["aspect_ratio"] = (aspects or XP_ASPECTS, {"default": "9:16"})
    req["poll_interval"] = ("INT", {"default": 5, "min": 2, "max": 60})
    req["poll_timeout"] = ("INT", {"default": 1800, "min": 60, "max": 7200})
    req["auto_download"] = ("BOOLEAN", {"default": True})
    return req


def _xp_ref_inputs(n_images: int = 4, *, with_media: bool = True) -> dict:
    """共用 optional：n 个 IMAGE 槽 + URL 直填 + 参考视频/音频。"""
    opt: dict = {f"image_{i + 1}": ("IMAGE",) for i in range(n_images)}
    opt["image_urls"] = ("STRING", {"default": "", "multiline": True,
                                    "placeholder": "参考图公网URL，每行一个（填了优先于上面的 IMAGE，≤9）"})
    if with_media:
        opt["video_urls"] = ("STRING", {"default": "", "multiline": True, "placeholder": "参考视频URL，每行一个（≤3）"})
        opt["video_paths"] = ("STRING", {"default": "", "multiline": True, "placeholder": "本地视频路径，每行一个（自动上传换URL）"})
        opt["audio_urls"] = ("STRING", {"default": "", "multiline": True, "placeholder": "参考音频URL，每行一个（≤3）"})
        opt["audio_paths"] = ("STRING", {"default": "", "multiline": True, "placeholder": "本地音频路径，每行一个（自动上传换URL）"})
    opt["custom_model"] = ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了覆盖上方模型"})
    opt["save_dir"] = ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"})
    opt["filename"] = ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"})
    return opt


_RET = ("STRING", "STRING", "STRING")
_RET_NAMES = ("video_url", "local_path", "task_id")
_RET_TIPS = ("在线视频 URL", "下载到本地的路径（预览/拼接用这个）", "任务 ID")


# ---------------------------------------------------------------------------
# #13 #14  SD2 全系原卡蒸（按秒） / 官方即梦全系卡蒸（按秒）
# ---------------------------------------------------------------------------


class RespectXPSd2Native:
    """小裴 SD2 全系卡蒸（按秒）+ 火山官方即梦。文档 #13 #14，两者字段一致。

    `POST /v1/videos`：`duration` + `aspect_ratio` +
    模式字段（首帧 `image_url`&`start_image_url`；首尾帧 `start_image_url`+`end_image_url`；
    多参考图第一张 `image_url`、其余 `extra_images`）+ `extra_videos` / `extra_audios`（各≤3）。
    图片最多 9 张。
    """

    DESCRIPTION = ("小裴 SD2 全系卡蒸/火山官方（按秒）。start_image_url+end_image_url 首尾帧、"
                   "extra_images(≤9)/extra_videos(≤3)/extra_audios(≤3)。参考素材自动上传换公网URL。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": _xp_common_inputs(XP_SD2_NATIVE_MODELS + XP_SD2_VOLC_MODELS,
                                          "sd2-720fast（全系按秒）", duration=(6, 4, 15)),
            "optional": _xp_ref_inputs(4),
        }

    RETURN_TYPES, RETURN_NAMES, OUTPUT_TOOLTIPS = _RET, _RET_NAMES, _RET_TIPS
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, generation_mode, duration, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 image_urls="", video_urls="", video_paths="", audio_urls="", audio_paths="",
                 custom_model="", save_dir="", filename="", **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        imgs = _xp_media_urls(cfg, [kwargs.get(f"image_{i + 1}") for i in range(9)], image_urls, 9)

        body: dict = {"model": model, "prompt": prompt,
                      "duration": int(duration), "aspect_ratio": aspect_ratio}
        if generation_mode == "首帧生成视频":
            if not imgs:
                raise RespectAPIError("首帧生成视频需要 1 张参考图")
            body["image_url"] = imgs[0]
            body["start_image_url"] = imgs[0]
        elif generation_mode == "首尾帧生成视频":
            if len(imgs) < 2:
                raise RespectAPIError("首尾帧需要 2 张图（第1张首帧、第2张尾帧）")
            body["start_image_url"], body["end_image_url"] = imgs[0], imgs[1]
        elif generation_mode == "多参考图生成视频":
            if not imgs:
                raise RespectAPIError("多参考图至少需要 1 张")
            body["image_url"] = imgs[0]
            if imgs[1:]:
                body["extra_images"] = imgs[1:]
        elif generation_mode == "首帧+参考图生成视频":
            if not imgs:
                raise RespectAPIError("首帧+参考图至少需要 1 张")
            body["image_url"] = imgs[0]
            body["start_image_url"] = imgs[0]
            if imgs[1:]:
                body["extra_images"] = imgs[1:]
        # 文生视频：不带图

        vids = _xp_local_or_urls(cfg, video_urls, video_paths)
        if vids:
            body["extra_videos"] = vids
        auds = _xp_local_or_urls(cfg, audio_urls, audio_paths)
        if auds:
            body["extra_audios"] = auds

        direct, task_id, _ = _xp_submit(cfg, "/v1/videos", body)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        return _xp_finish(cfg, url, task_id, "xp_sd2native", auto_download, save_dir, filename)


# ---------------------------------------------------------------------------
# #15  sd-2.0 最低渠道（卡蒸）—— 双端点分流
# ---------------------------------------------------------------------------


class RespectXPSd2Lowest:
    """小裴 sd-2.0 最低渠道（卡蒸）。文档 #15：**按模式走两个不同端点**。

    - 文生 / 单首帧 → `POST /v1/videos`，首帧放 `input_reference{image_url}`
    - 首尾帧 / 多参考图 / 首帧+参考 → `POST /v1/video/generations`，
      `image_references[]`（索引0=首帧、索引1=尾帧）+ `video_references` / `audio_references`
      轮询也换成 `GET /v1/video/generations/{task_id}`
    创建都带唯一 `Idempotency-Key`。
    """

    DESCRIPTION = ("小裴 sd-2.0 最低渠道（卡蒸）。文生/单首帧走 /v1/videos(input_reference)；"
                   "首尾帧/多参考走 /v1/video/generations(image_references[]) 并按该路径轮询。带 Idempotency-Key。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        req = _xp_common_inputs(XP_SD2_LOWEST_MODELS, "sd-2.0-720fast（卡蒸）最低渠道", duration=(6, 4, 15))
        req["resolution"] = (XP_RESOLUTIONS, {"default": "720p"})
        return {"required": req, "optional": _xp_ref_inputs(4)}

    RETURN_TYPES, RETURN_NAMES, OUTPUT_TOOLTIPS = _RET, _RET_NAMES, _RET_TIPS
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, generation_mode, duration, aspect_ratio,
                 poll_interval, poll_timeout, auto_download, resolution="720p",
                 image_urls="", video_urls="", video_paths="", audio_urls="", audio_paths="",
                 custom_model="", save_dir="", filename="", **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        imgs = _xp_media_urls(cfg, [kwargs.get(f"image_{i + 1}") for i in range(9)], image_urls, 9)
        headers = {"Idempotency-Key": uuid.uuid4().hex}

        base: dict = {"model": model, "prompt": prompt, "duration": int(duration),
                      "resolution": resolution, "aspect_ratio": aspect_ratio}
        multi = generation_mode in ("首尾帧生成视频", "多参考图生成视频", "首帧+参考图生成视频")

        if not multi:
            body = dict(base)
            if generation_mode == "首帧生成视频":
                if not imgs:
                    raise RespectAPIError("首帧生成视频需要 1 张参考图")
                body["input_reference"] = {"image_url": imgs[0]}
            direct, task_id, _ = _xp_submit(cfg, "/v1/videos", body, headers=headers)
            url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        else:
            if generation_mode == "首尾帧生成视频" and len(imgs) < 2:
                raise RespectAPIError("首尾帧需要 2 张图（索引0=首帧、索引1=尾帧）")
            if not imgs:
                raise RespectAPIError("该模式至少需要 1 张参考图")
            body = dict(base)
            body["image_references"] = imgs[:2] if generation_mode == "首尾帧生成视频" else imgs
            vids = _xp_local_or_urls(cfg, video_urls, video_paths)
            if vids:
                body["video_references"] = vids
            auds = _xp_local_or_urls(cfg, audio_urls, audio_paths)
            if auds:
                body["audio_references"] = auds
            direct, task_id, _ = _xp_submit(cfg, "/v1/video/generations", body, headers=headers)
            url = direct or _xp_poll_generations(cfg, task_id, int(poll_interval), int(poll_timeout))
        return _xp_finish(cfg, url, task_id, "xp_sd2lowest", auto_download, save_dir, filename)


# ---------------------------------------------------------------------------
# #9  VEO 视频生成
# ---------------------------------------------------------------------------


XP_VEO_DURATIONS = [4, 6, 8]
XP_VEO_ASPECTS = ["16:9", "9:16", "1:1"]


class RespectXPVeo:
    """小裴 VEO 视频生成。文档 #9：模型固定 `veo视频生成`。

    `POST /v1/videos`，固定 `resolution:"720p"` + `generate_audio:true`；
    参考图放 **`image_urls` 数组**：首帧=1 张；首尾帧=按「首帧、尾帧」顺序放 2 张；文生则不带该字段。
    """

    DESCRIPTION = ("小裴 VEO 视频生成（model 固定 veo视频生成）。4/6/8 秒，固定 720p + generate_audio；"
                   "image_urls 数组：1张=首帧，2张=首尾帧（顺序即首、尾）。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 默认 https://api.aicopy.top"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "generation_mode": (["文生视频", "首帧生成视频", "首尾帧生成视频"], {"default": "首帧生成视频"}),
                "duration": ("INT", {"default": 8, "min": 4, "max": 8, "tooltip": "只支持 4 / 6 / 8"}),
                "aspect_ratio": (XP_VEO_ASPECTS, {"default": "9:16"}),
                "poll_interval": ("INT", {"default": 6, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "first_frame": ("IMAGE", {"tooltip": "首帧"}),
                "last_frame": ("IMAGE", {"tooltip": "尾帧（首尾帧模式用）"}),
                "image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "首帧/首尾帧公网URL，每行一个（填了优先）"}),
                "generate_audio": ("BOOLEAN", {"default": True, "tooltip": "文档固定 true"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "默认 veo视频生成"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES, RETURN_NAMES, OUTPUT_TOOLTIPS = _RET, _RET_NAMES, _RET_TIPS
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, prompt, generation_mode, duration, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 first_frame=None, last_frame=None, image_urls="", generate_audio=True,
                 custom_model="", save_dir="", filename=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or "veo视频生成"
        dur = int(duration)
        if dur not in XP_VEO_DURATIONS:
            near = min(XP_VEO_DURATIONS, key=lambda d: abs(d - dur))
            print(f"[Respect] VEO 只支持 {XP_VEO_DURATIONS} 秒，已把 {dur} 纠正为 {near}")
            dur = near

        body: dict = {"model": model, "prompt": prompt, "aspect_ratio": aspect_ratio,
                      "resolution": "720p", "duration": dur, "generate_audio": bool(generate_audio)}
        if generation_mode != "文生视频":
            urls = _xp_media_urls(cfg, [first_frame, last_frame], image_urls, 2)
            need = 2 if generation_mode == "首尾帧生成视频" else 1
            if len(urls) < need:
                raise RespectAPIError(f"{generation_mode} 需要 {need} 张图（首尾帧顺序：首帧、尾帧）")
            body["image_urls"] = urls[:need]

        direct, task_id, _ = _xp_submit(cfg, "/v1/videos", body)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        return _xp_finish(cfg, url, task_id, "xp_veo", auto_download, save_dir, filename)


# ---------------------------------------------------------------------------
# #8  Omni 视频生成 / 视频编辑
# ---------------------------------------------------------------------------


XP_OMNI_MODES = ["文生视频", "首帧生成视频", "首尾帧生成视频", "多图生成视频", "单视频编辑", "双视频编辑"]


class RespectXPOmni:
    """小裴 Omni（视频生成 / 视频编辑，含带/无水印共 4 个单位）。文档 #8。

    `POST /v1/videos`，**固定 `seconds:"10"`**。字段按模式：
    首帧 `first_image_url`；首尾帧 `first_image_url`+`last_image_url`；
    多图 `images`（≤5）；单视频编辑 `video_url`；双视频编辑 `videos`（≤2）。
    **视频编辑要选 `omni-fast-视频编辑…` 那两个单位**（生成单位不吃视频）。
    """

    DESCRIPTION = ("小裴 Omni 生成/编辑（固定10秒）。首帧 first_image_url、首尾帧 +last_image_url、"
                   "多图 images≤5、单视频编辑 video_url、双视频编辑 videos≤2。编辑模式请选『视频编辑』单位。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 默认 https://api.aicopy.top"}),
                "model": (XP_OMNI_MODELS, {"default": "omni-fast-视频生成（无水印）"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "generation_mode": (XP_OMNI_MODES, {"default": "首帧生成视频"}),
                "aspect_ratio": (["16:9", "9:16"], {"default": "9:16"}),
                "poll_interval": ("INT", {"default": 6, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "image_1": ("IMAGE", {"tooltip": "首帧 / 多图第1张"}),
                "image_2": ("IMAGE", {"tooltip": "尾帧 / 多图第2张"}),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "image_5": ("IMAGE",),
                "image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考图公网URL，每行一个（填了优先，多图≤5）"}),
                "video_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "待编辑视频URL，每行一个（单编辑1条/双编辑2条）"}),
                "video_paths": ("STRING", {"default": "", "multiline": True, "placeholder": "本地视频路径，每行一个（自动上传换URL）"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了覆盖上方模型"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES, RETURN_NAMES, OUTPUT_TOOLTIPS = _RET, _RET_NAMES, _RET_TIPS
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, generation_mode, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 image_urls="", video_urls="", video_paths="",
                 custom_model="", save_dir="", filename="", **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        body: dict = {"model": model, "prompt": prompt,
                      "aspect_ratio": aspect_ratio, "seconds": "10"}   # 文档固定 10 秒

        if generation_mode in ("单视频编辑", "双视频编辑"):
            if "视频编辑" not in model:
                print(f"[Respect] 提醒：{generation_mode} 建议选 omni-fast-视频编辑… 单位，当前是 {model}")
            vids = _xp_local_or_urls(cfg, video_urls, video_paths, 2)
            if not vids:
                raise RespectAPIError("视频编辑需要提供待编辑视频（URL 或本地路径）")
            if generation_mode == "单视频编辑":
                body["video_url"] = vids[0]
            else:
                if len(vids) < 2:
                    raise RespectAPIError("双视频编辑需要 2 条视频")
                body["videos"] = vids[:2]
        elif generation_mode != "文生视频":
            imgs = _xp_media_urls(cfg, [kwargs.get(f"image_{i + 1}") for i in range(5)], image_urls, 5)
            if not imgs:
                raise RespectAPIError(f"{generation_mode} 需要参考图")
            if generation_mode == "首帧生成视频":
                body["first_image_url"] = imgs[0]
            elif generation_mode == "首尾帧生成视频":
                if len(imgs) < 2:
                    raise RespectAPIError("首尾帧需要 2 张图（第1张首帧、第2张尾帧）")
                body["first_image_url"], body["last_image_url"] = imgs[0], imgs[1]
            else:                                    # 多图生成视频
                body["images"] = imgs[:5]

        direct, task_id, _ = _xp_submit(cfg, "/v1/videos", body)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        return _xp_finish(cfg, url, task_id, "xp_omni", auto_download, save_dir, filename)


# ---------------------------------------------------------------------------
# #10  SD 轮换渠道（动态调价）
# ---------------------------------------------------------------------------


class RespectXPSdRotate:
    """小裴 SD 轮换渠道（动态调价）。文档 #10：`POST /v1/videos`，固定 `resolution:"720p"`。

    字段：单首帧 `first_frame_url`；首尾帧 +`last_frame_url`；
    多参考图 `reference_image_urls`；首帧+参考 = `first_frame_url` + 其余进 `reference_image_urls`；
    另支持 `reference_videos` / `reference_audios`（各≤3）。
    按次单位固定 15 秒，按秒单位 4–15。
    """

    DESCRIPTION = ("小裴 SD 轮换渠道（动态调价，固定720p）。first_frame_url/last_frame_url、"
                   "reference_image_urls、reference_videos/reference_audios(各≤3)。按次单位固定15秒。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        req = _xp_common_inputs(XP_SD_ROTATE_MODELS, "sd-720fast（按秒）",
                                aspects=["16:9", "9:16"], duration=(8, 4, 15))
        return {"required": req, "optional": _xp_ref_inputs(4)}

    RETURN_TYPES, RETURN_NAMES, OUTPUT_TOOLTIPS = _RET, _RET_NAMES, _RET_TIPS
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, generation_mode, duration, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 image_urls="", video_urls="", video_paths="", audio_urls="", audio_paths="",
                 custom_model="", save_dir="", filename="", **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        imgs = _xp_media_urls(cfg, [kwargs.get(f"image_{i + 1}") for i in range(9)], image_urls, 9)

        sec = int(duration)
        if "按次" in model and sec != 15:
            print(f"[Respect] {model} 是按次单位，时长固定 15 秒（已忽略 {sec}）")
            sec = 15
        body: dict = {"model": model, "prompt": prompt, "aspect_ratio": aspect_ratio,
                      "seconds": str(sec), "resolution": "720p"}

        if generation_mode == "首帧生成视频":
            if not imgs:
                raise RespectAPIError("首帧生成视频需要 1 张参考图")
            body["first_frame_url"] = imgs[0]
        elif generation_mode == "首尾帧生成视频":
            if len(imgs) < 2:
                raise RespectAPIError("首尾帧需要 2 张图（第1张首帧、第2张尾帧）")
            body["first_frame_url"], body["last_frame_url"] = imgs[0], imgs[1]
        elif generation_mode == "多参考图生成视频":
            if not imgs:
                raise RespectAPIError("多参考图至少需要 1 张")
            body["reference_image_urls"] = imgs
        elif generation_mode == "首帧+参考图生成视频":
            if not imgs:
                raise RespectAPIError("首帧+参考图至少需要 1 张")
            body["first_frame_url"] = imgs[0]
            if imgs[1:]:
                body["reference_image_urls"] = imgs[1:]

        vids = _xp_local_or_urls(cfg, video_urls, video_paths)
        if vids:
            body["reference_videos"] = vids
        auds = _xp_local_or_urls(cfg, audio_urls, audio_paths)
        if auds:
            body["reference_audios"] = auds

        direct, task_id, _ = _xp_submit(cfg, "/v1/videos", body)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        return _xp_finish(cfg, url, task_id, "xp_sdrotate", auto_download, save_dir, filename)


# ---------------------------------------------------------------------------
# #11 #12  SD2 按次 / ad渠道（嵌套 input{media:[...]} 结构）
# ---------------------------------------------------------------------------


class RespectXPSd2PerUse:
    """小裴 SD2 按次 / ad渠道（卡蒸）。文档 #11 #12 —— **结构和别的分支完全不同**。

    ```json
    {"model":"…", "prompt":"…", "seconds":"15", "size":"480x854",
     "input": {"prompt":"…", "media":[{"type":"reference_image","url":"…"},
                                      {"type":"reference_video","url":"…"},
                                      {"type":"reference_audio","url":"…"}]}}
    ```
    比例/分辨率由**单位名**固定（所以只需选对模型），时长固定 15 秒；
    图片≤9、视频/音频各≤3；**只接受公网 HTTPS 素材**（IMAGE 会自动上传换 URL）。
    """

    DESCRIPTION = ("小裴 SD2 按次/ad渠道（卡蒸）。嵌套 input{prompt, media:[{type,url}]} 结构，"
                   "固定15秒，size 由单位名决定；图≤9、视频/音频各≤3，素材自动上传换公网URL。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 默认 https://api.aicopy.top"}),
                "model": (XP_SD2_PERUSE_MODELS + XP_SD2_AD_MODELS, {"default": "sd-720-fast-渠道9:16（按次）"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "size": (XP_SD2_PERUSE_SIZES, {"default": "720x1280", "tooltip": "要和所选单位的比例/分辨率一致"}),
                "poll_interval": ("INT", {"default": 5, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": _xp_ref_inputs(4),
        }

    RETURN_TYPES, RETURN_NAMES, OUTPUT_TOOLTIPS = _RET, _RET_NAMES, _RET_TIPS
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, size, poll_interval, poll_timeout, auto_download,
                 image_urls="", video_urls="", video_paths="", audio_urls="", audio_paths="",
                 custom_model="", save_dir="", filename="", **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model

        media: list[dict] = []
        for u in _xp_media_urls(cfg, [kwargs.get(f"image_{i + 1}") for i in range(9)], image_urls, 9):
            media.append({"type": "reference_image", "url": u})
        for u in _xp_local_or_urls(cfg, video_urls, video_paths):
            media.append({"type": "reference_video", "url": u})
        for u in _xp_local_or_urls(cfg, audio_urls, audio_paths):
            media.append({"type": "reference_audio", "url": u})

        body: dict = {"model": model, "prompt": prompt, "seconds": "15", "size": size,
                      "input": {"prompt": prompt}}
        if media:
            body["input"]["media"] = media

        direct, task_id, _ = _xp_submit(cfg, "/v1/videos", body)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        return _xp_finish(cfg, url, task_id, "xp_sd2peruse", auto_download, save_dir, filename)


# ---------------------------------------------------------------------------
# #4  Grok 支持 16/20 秒
# ---------------------------------------------------------------------------


class RespectXPGrok16:
    """小裴 Grok 长时长分支（6/10/12/16/20 秒）。文档 #4。

    `POST /v1/videos`：`seconds`（**字符串**）+ `size`（WxH，由比例换算）；
    `grok-1.5-支持16s` 图生**只传一张首帧到 `image_reference`**；`grok-1.0-支持16s` 是纯文生（不发图片字段）。
    轮询优先用创建响应里的 `status_url`，没有再退回 `GET /v1/videos/{task_id}`。
    """

    DESCRIPTION = ("小裴 Grok 16/20秒分支。seconds 是字符串、size 按比例换算；1.5 图生只吃单张 "
                   "image_reference，1.0 为纯文生。轮询优先用返回的 status_url。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 默认 https://api.aicopy.top"}),
                "model": (XP_GROK16_MODELS, {"default": "grok-1.5-支持16s"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "seconds": (XP_GROK16_SECONDS, {"default": "16"}),
                "aspect_ratio": (list(XP_GROK16_SIZES), {"default": "9:16"}),
                "poll_interval": ("INT", {"default": 3, "min": 2, "max": 60, "tooltip": "文档建议 3 秒"}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "first_frame": ("IMAGE", {"tooltip": "仅 grok-1.5-支持16s 有效，单张首帧"}),
                "image_url": ("STRING", {"default": "", "multiline": False, "placeholder": "首帧公网URL（填了优先）"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了覆盖上方模型"}),
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，直接指定 size 如 720x1280"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES, RETURN_NAMES, OUTPUT_TOOLTIPS = _RET, _RET_NAMES, _RET_TIPS
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, seconds, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 first_frame=None, image_url="", custom_model="", custom_size="",
                 save_dir="", filename=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        size = (custom_size or "").strip() or XP_GROK16_SIZES.get(aspect_ratio, "720x1280")

        body: dict = {"model": model, "prompt": prompt, "seconds": str(seconds), "size": size}
        if "1.0" in model:
            if first_frame is not None or (image_url or "").strip():
                print(f"[Respect] {model} 是纯文生分支，已忽略参考图（文档：不发图片字段）")
        else:
            ref = (image_url or "").strip()
            if not ref and first_frame is not None:
                ref = _upload_reference(cfg, first_frame, 1)
            if ref:
                body["image_reference"] = ref          # 只吃单张首帧

        direct, task_id, status_url = _xp_submit(cfg, "/v1/videos", body)
        if direct:
            url = direct
        elif status_url:
            print(f"[Respect] 用创建返回的 status_url 轮询: {status_url}")
            url = _xp_poll_url(cfg, status_url, int(poll_interval), int(poll_timeout))
        else:
            url = _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        return _xp_finish(cfg, url, task_id, "xp_grok16", auto_download, save_dir, filename)


NODE_CLASS_MAPPINGS = {
    "RespectXPSd2Native": RespectXPSd2Native,
    "RespectXPSd2Lowest": RespectXPSd2Lowest,
    "RespectXPSd2PerUse": RespectXPSd2PerUse,
    "RespectXPSdRotate": RespectXPSdRotate,
    "RespectXPVeo": RespectXPVeo,
    "RespectXPOmni": RespectXPOmni,
    "RespectXPGrok16": RespectXPGrok16,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectXPSd2Native": "Respect 小裴 SD2 全系/火山官方（按秒）",
    "RespectXPSd2Lowest": "Respect 小裴 SD2 最低渠道（双端点）",
    "RespectXPSd2PerUse": "Respect 小裴 SD2 按次/ad渠道（嵌套input）",
    "RespectXPSdRotate": "Respect 小裴 SD 轮换渠道（动态调价）",
    "RespectXPVeo": "Respect 小裴 VEO 视频生成",
    "RespectXPOmni": "Respect 小裴 Omni 生成/编辑",
    "RespectXPGrok16": "Respect 小裴 Grok 16/20秒",
}


def _xp_poll_generations(cfg, task_id: str, interval: int, timeout: int) -> str:
    """多参考路径的轮询：GET /v1/video/generations/{task_id}（注意不是 /v1/videos/…）。"""
    start, last = time.time(), ""
    while time.time() - start < timeout:
        try:
            resp = api_request(cfg, "GET", f"/v1/video/generations/{task_id}", retries=1, timeout=60)
        except RespectAPIError as exc:
            print(f"[Respect] /v1/video/generations 轮询出错，继续重试: {exc}")
            time.sleep(interval)
            continue
        data = resp.json() if resp.content else {}
        status, url = _async_status(data), _async_extract_url(data)
        if status and status != last:
            print(f"[Respect] 任务 {task_id} 状态: {status}")
            last = status
        if status in _ASYNC_FAIL:
            raise RespectAPIError(f"任务失败: {json.dumps(data, ensure_ascii=False)[:400]}")
        if url and (not status or status in _ASYNC_DONE):
            return url
        time.sleep(interval)
    raise RespectAPIError(f"任务超时: {task_id}")
