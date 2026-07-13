"""Respect ComfyUI 扩展 - 视频生成节点。

封装 api.aicopy.top 的视频生成接口。
"""

from __future__ import annotations

import io
import json
import time
from typing import Any, Optional

import torch

from .utils import (
    RespectAPIError,
    api_request,
    collect_stream_text,
    download_to_output,
    ensure_config,
    extract_video_urls,
    tensor_to_b64,
    tensor_to_pil,
)


CATEGORY = "Respect"


# ---------------------------------------------------------------------------
# 公用辅助
# ---------------------------------------------------------------------------


def _tensor_to_jpeg_bytes(tensor: torch.Tensor, max_side: int = 1280, quality: int = 90) -> bytes:
    pil_list = tensor_to_pil(tensor[:1])
    if not pil_list:
        return b""
    pil = pil_list[0]
    w, h = pil.size
    long_side = max(w, h)
    if long_side > max_side:
        scale = max_side / float(long_side)
        pil = pil.resize((int(w * scale), int(h * scale)))
    buf = io.BytesIO()
    if pil.mode != "RGB":
        pil = pil.convert("RGB")
    pil.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _resolve_video_url(payload: Any, raw_text: str = "") -> str:
    urls = extract_video_urls(payload)
    if not urls and raw_text:
        urls = extract_video_urls(raw_text)
    if not urls:
        snippet = raw_text or (json.dumps(payload, ensure_ascii=False)[:600] if not isinstance(payload, str) else payload[:600])
        raise RespectAPIError(f"未能从响应中提取视频 URL: {snippet}")
    return urls[0]


def _call_chat_video(
    cfg,
    model: str,
    prompt: str,
    images: list[Optional[torch.Tensor]],
    *,
    aspect_ratio: str = "",
    video_length: int = 0,
    resolution: str = "",
    stream: bool = True,
) -> tuple[str, str]:
    """Sora2 / VEO3.1 / Runway 4.5 共用的 chat completions 调用。返回 (video_url, raw_text)。"""
    content: list[dict] = []
    for img in images:
        if img is None or (hasattr(img, "numel") and img.numel() == 0):
            continue
        b64_list = tensor_to_b64(img[:1], fmt="JPEG", quality=88, max_side=1536)
        if b64_list:
            content.append({"type": "image_url", "image_url": {"url": b64_list[0]}})
    if prompt:
        content.append({"type": "text", "text": prompt})

    body: dict = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "stream": bool(stream),
    }
    if aspect_ratio:
        body["aspect_ratio"] = aspect_ratio
    if video_length:
        body["video_length"] = int(video_length)
    if resolution:
        body["resolution"] = resolution

    resp = api_request(
        cfg,
        "POST",
        "/v1/chat/completions",
        json_body=body,
        stream=bool(stream),
        retries=2,
        timeout=max(cfg.timeout, 1800),
    )
    if stream:
        text = collect_stream_text(resp)
        url = _resolve_video_url(text, raw_text=text)
        return (url, text)
    data = resp.json()
    text_blob = ""
    try:
        text_blob = data["choices"][0]["message"].get("content", "") or ""
        if isinstance(text_blob, list):
            text_blob = json.dumps(text_blob, ensure_ascii=False)
    except Exception:
        text_blob = json.dumps(data, ensure_ascii=False)
    url = _resolve_video_url(data, raw_text=text_blob)
    return (url, text_blob)


# ---------------------------------------------------------------------------
# Sora2
# ---------------------------------------------------------------------------


SORA2_DURATIONS = ["4", "8", "12"]
SORA2_ASPECTS = ["16:9", "9:16"]


class RespectFireflySora2:
    """Firefly Sora2 视频生成。模型 ID 由参数自动拼接：
    `firefly-sora2[-pro]-{秒数}s-{比例x}`。
    填了 `custom_model` 时优先使用，方便手动指定任意官方模型名。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": (SORA2_DURATIONS, {"default": "8"}),
                "aspect_ratio": (SORA2_ASPECTS, {"default": "16:9"}),
                "use_pro": ("BOOLEAN", {"default": False}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "first_frame": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了优先使用，如 firefly-sora2-pro-12s-16x9"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect，相对路径基于 output，支持绝对路径"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳；无扩展名自动补 .mp4"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(
        self,
        api_config: Any,
        prompt: str,
        duration: str,
        aspect_ratio: str,
        use_pro: bool,
        auto_download: bool,
        first_frame: Optional[torch.Tensor] = None,
        custom_model: str = "",
        save_dir: str = "",
        filename: str = "",
    ) -> tuple[str, str, str]:
        cfg = ensure_config(api_config)
        custom_model = (custom_model or "").strip()
        if custom_model:
            model = custom_model
        else:
            family = "firefly-sora2-pro" if use_pro else "firefly-sora2"
            model = f"{family}-{duration}s-{aspect_ratio.replace(':', 'x')}"

        url, _ = _call_chat_video(
            cfg,
            model,
            prompt,
            [first_frame],
            aspect_ratio=aspect_ratio,
            video_length=int(duration),
            stream=True,
        )
        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="sora2", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] Sora2 视频下载失败: {exc}")
        return (url, local, model)


# ---------------------------------------------------------------------------
# VEO 3.1
# ---------------------------------------------------------------------------


VEO31_DURATIONS = ["4", "6", "8"]
VEO31_ASPECTS = ["16:9", "9:16"]
VEO31_RESOLUTIONS = ["720p", "1080p"]
VEO31_VARIANTS = ["default", "fast", "ref"]


class RespectFireflyVeo31:
    """Firefly VEO 3.1 视频生成。
    模型 ID 拼接：`firefly-veo31[-fast|-ref]-{秒数}s-{比例x}-{清晰度}`。
    填了 `custom_model` 时优先使用，方便手动指定 pro / components / 4k 等变体。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": (VEO31_DURATIONS, {"default": "6"}),
                "aspect_ratio": (VEO31_ASPECTS, {"default": "16:9"}),
                "resolution": (VEO31_RESOLUTIONS, {"default": "720p"}),
                "variant": (VEO31_VARIANTS, {"default": "default"}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "first_frame": ("IMAGE",),
                "last_frame": ("IMAGE",),
                "ref_image_1": ("IMAGE",),
                "ref_image_2": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了优先使用，如 firefly-veo31-pro-8s-16x9-1080p"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect，相对路径基于 output，支持绝对路径"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳；无扩展名自动补 .mp4"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(
        self,
        api_config: Any,
        prompt: str,
        duration: str,
        aspect_ratio: str,
        resolution: str,
        variant: str,
        auto_download: bool,
        first_frame: Optional[torch.Tensor] = None,
        last_frame: Optional[torch.Tensor] = None,
        ref_image_1: Optional[torch.Tensor] = None,
        ref_image_2: Optional[torch.Tensor] = None,
        custom_model: str = "",
        save_dir: str = "",
        filename: str = "",
    ) -> tuple[str, str, str]:
        cfg = ensure_config(api_config)
        custom_model = (custom_model or "").strip()
        if custom_model:
            model = custom_model
        else:
            variant_part = "" if variant == "default" else f"-{variant}"
            model = f"firefly-veo31{variant_part}-{duration}s-{aspect_ratio.replace(':', 'x')}-{resolution}"

        url, _ = _call_chat_video(
            cfg,
            model,
            prompt,
            [first_frame, last_frame, ref_image_1, ref_image_2],
            aspect_ratio=aspect_ratio,
            video_length=int(duration),
            resolution=resolution,
            stream=True,
        )
        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="veo31", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] VEO3.1 视频下载失败: {exc}")
        return (url, local, model)


# ---------------------------------------------------------------------------
# Runway 4.5
# ---------------------------------------------------------------------------


RUNWAY45_DURATIONS = ["5", "10"]
RUNWAY45_ASPECTS = ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "9:21"]


class RespectFireflyRunway45:
    """Firefly Runway 4.5 视频生成。
    模型 ID：`firefly-runway45-{秒数}s-{比例x}-720p`。
    填了 `custom_model` 时优先使用。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": (RUNWAY45_DURATIONS, {"default": "5"}),
                "aspect_ratio": (RUNWAY45_ASPECTS, {"default": "16:9"}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "first_frame": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了优先使用，如 firefly-runway45-10s-21x9-720p"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect，相对路径基于 output，支持绝对路径"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳；无扩展名自动补 .mp4"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(
        self,
        api_config: Any,
        prompt: str,
        duration: str,
        aspect_ratio: str,
        auto_download: bool,
        first_frame: Optional[torch.Tensor] = None,
        custom_model: str = "",
        save_dir: str = "",
        filename: str = "",
    ) -> tuple[str, str, str]:
        cfg = ensure_config(api_config)
        custom_model = (custom_model or "").strip()
        if custom_model:
            model = custom_model
        else:
            model = f"firefly-runway45-{duration}s-{aspect_ratio.replace(':', 'x')}-720p"

        url, _ = _call_chat_video(
            cfg,
            model,
            prompt,
            [first_frame],
            aspect_ratio=aspect_ratio,
            video_length=int(duration),
            resolution="720p",
            stream=True,
        )
        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="runway45", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] Runway 4.5 视频下载失败: {exc}")
        return (url, local, model)


# ---------------------------------------------------------------------------
# SD2 / 即梦 (异步任务)
# ---------------------------------------------------------------------------


SD2_MODELS = [
    "sd2-720p-fast", "sd2-720p", "sd2-1080p-fast", "sd2-1080p",
    "sd2-720p-min-fast", "sd2-720p-min",
]
SD2_ASPECTS = ["16:9", "9:16", "1:1", "4:3", "3:4"]


SD2_SIZE_TABLE = {
    "720p": {"16:9": "1280x720", "9:16": "720x1280", "1:1": "720x720", "4:3": "720x720", "3:4": "720x720"},
    "1080p": {"16:9": "1920x1080", "9:16": "1080x1920", "1:1": "1080x1080", "4:3": "1080x1080", "3:4": "1080x1080"},
}


def _sd2_size(model: str, aspect: str) -> str:
    tier = "1080p" if "1080p" in model else "720p"
    return SD2_SIZE_TABLE[tier].get(aspect, "1280x720")


def _sd2_extract_task_id(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for k in ("id", "task_id", "video_id"):
        v = data.get(k)
        if isinstance(v, (str, int)) and str(v):
            return str(v)
    inner = data.get("data")
    if isinstance(inner, dict):
        for k in ("id", "task_id", "video_id"):
            v = inner.get(k)
            if isinstance(v, (str, int)) and str(v):
                return str(v)
    return ""


def _sd2_extract_direct_url(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for k in ("result_url", "video_url", "url", "download_url", "file_url"):
        v = data.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
    output = data.get("output")
    if isinstance(output, dict):
        for k in ("url", "video_url", "download_url"):
            v = output.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
    return ""


def _sd2_poll(cfg, task_id: str, interval: int = 5, timeout: int = 1800) -> str:
    start = time.time()
    last_status = ""
    while time.time() - start < timeout:
        try:
            resp = api_request(cfg, "GET", f"/v1/videos/{task_id}", retries=1, timeout=60)
        except RespectAPIError as exc:
            print(f"[Respect] SD2 轮询错误，继续重试: {exc}")
            time.sleep(interval)
            continue
        data = resp.json() if resp.content else {}
        status = str(data.get("status", "")).lower()
        if status and status != last_status:
            print(f"[Respect] SD2 任务 {task_id} 状态: {status}")
            last_status = status
        if status in ("completed", "succeeded", "success"):
            url = _sd2_extract_direct_url(data)
            if url:
                return url
            base = cfg.normalized_base().rsplit("/v1", 1)[0]
            return f"{base}/v1/videos/{task_id}/content"
        if status in ("failed", "cancelled", "canceled", "error"):
            raise RespectAPIError(f"SD2 任务失败: {json.dumps(data, ensure_ascii=False)[:600]}")
        time.sleep(interval)
    raise RespectAPIError(f"SD2 任务超时: {task_id}")


class RespectSD2Video:
    """即梦 / SD2 视频生成。

    无参考图走 JSON `/v1/videos`；有参考图自动切换到 multipart 上传。
    然后轮询 `/v1/videos/{task_id}` 直到完成。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "model": (SD2_MODELS, {"default": "sd2-720p-fast"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": ("INT", {"default": 5, "min": 4, "max": 15}),
                "aspect_ratio": (SD2_ASPECTS, {"default": "16:9"}),
                "poll_interval": ("INT", {"default": 5, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "ref_image_1": ("IMAGE",),
                "ref_image_2": ("IMAGE",),
                "ref_image_3": ("IMAGE",),
                "ref_image_4": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了优先使用，例如新模型 sd2-4k"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect，相对路径基于 output，支持绝对路径"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳；无扩展名自动补 .mp4"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(
        self,
        api_config: Any,
        model: str,
        prompt: str,
        duration: int,
        aspect_ratio: str,
        poll_interval: int,
        poll_timeout: int,
        auto_download: bool,
        ref_image_1: Optional[torch.Tensor] = None,
        ref_image_2: Optional[torch.Tensor] = None,
        ref_image_3: Optional[torch.Tensor] = None,
        ref_image_4: Optional[torch.Tensor] = None,
        custom_model: str = "",
        save_dir: str = "",
        filename: str = "",
    ) -> tuple[str, str, str]:
        cfg = ensure_config(api_config)
        custom_model = (custom_model or "").strip()
        if custom_model:
            model = custom_model
        size = _sd2_size(model, aspect_ratio)
        duration = int(duration)
        if "min" in model and duration < 5:
            duration = 5

        refs: list[bytes] = []
        for img in (ref_image_1, ref_image_2, ref_image_3, ref_image_4):
            if img is None or (hasattr(img, "numel") and img.numel() == 0):
                continue
            data = _tensor_to_jpeg_bytes(img)
            if data:
                refs.append(data)

        if "min" in model and len(refs) > 4:
            refs = refs[:4]

        if refs:
            files = [
                ("model", (None, model)),
                ("prompt", (None, prompt)),
                ("seconds", (None, str(duration))),
                ("duration", (None, str(duration))),
                ("video_length", (None, str(duration))),
                ("size", (None, size)),
            ]
            field_names = ["input_reference", "input_reference_2", "input_reference_3", "input_reference_4"]
            for name, data in zip(field_names, refs):
                files.append((name, (f"{name}.jpg", data, "image/jpeg")))
            resp = api_request(cfg, "POST", "/v1/videos", files=files, retries=2, timeout=max(cfg.timeout, 300))
        else:
            body = {
                "model": model,
                "prompt": prompt,
                "seconds": str(duration),
                "duration": duration,
                "video_length": duration,
                "size": size,
            }
            resp = api_request(cfg, "POST", "/v1/videos", json_body=body, retries=2, timeout=max(cfg.timeout, 300))

        data = resp.json() if resp.content else {}
        direct = _sd2_extract_direct_url(data)
        task_id = _sd2_extract_task_id(data)

        if direct:
            url = direct
        elif task_id:
            url = _sd2_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        else:
            raise RespectAPIError(f"SD2 提交未返回 task_id 或视频 URL: {json.dumps(data, ensure_ascii=False)[:600]}")

        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="sd2", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] SD2 视频下载失败: {exc}")

        return (url, local, task_id or "")


# ---------------------------------------------------------------------------
# 通用视频保存
# ---------------------------------------------------------------------------


class RespectSaveVideo:
    """把视频 URL 下载到指定位置。可以单独使用。

    - `save_dir` 留空 → `ComfyUI/output/respect/`
    - `save_dir` 相对路径 → 基于 ComfyUI output 目录
    - `save_dir` 绝对路径 → 直接使用，例如 `D:\\videos\\veo31`
    - `filename` 留空 → 自动 `<prefix>_<时间戳>_<6位hash>.mp4`
    - `filename` 非空 → 直接用，没扩展名自动补 `.mp4`
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "video_url": ("STRING", {"default": "", "multiline": False, "forceInput": True}),
            },
            "optional": {
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect，相对路径基于 output，支持绝对路径"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳；无扩展名自动补 .mp4"}),
                "prefix": ("STRING", {"default": "respect", "multiline": False, "placeholder": "仅当 filename 为空时用于自动命名"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("local_path",)
    FUNCTION = "save"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def save(
        self,
        api_config: Any,
        video_url: str,
        save_dir: str = "",
        filename: str = "",
        prefix: str = "respect",
    ) -> tuple[str]:
        if not video_url:
            return ("",)
        cfg = ensure_config(api_config)
        try:
            path = download_to_output(
                video_url,
                cfg,
                prefix=prefix or "respect",
                save_dir=save_dir,
                filename=filename,
            )
            print(f"[Respect] 视频已保存: {path}")
            return (path,)
        except Exception as exc:
            print(f"[Respect] 视频保存失败: {exc}")
            return ("",)


# ===========================================================================
# 新增模型（06.06 小裴/正寒接口更新）：Kling3 / Sora V3 / Grok
# ===========================================================================


def _img_data_urls(images: list[Optional[torch.Tensor]], max_side: int = 1536, quality: int = 88) -> list[str]:
    """多张 IMAGE -> base64 data URL 列表（用于异步接口的 reference_images / images）。"""
    urls: list[str] = []
    for img in images:
        if img is None or (hasattr(img, "numel") and img.numel() == 0):
            continue
        b64 = tensor_to_b64(img[:1], fmt="JPEG", quality=quality, max_side=max_side)
        if b64:
            urls.append(b64[0])
    return urls


# --- 异步 /v1/videos 通用：URL / 状态提取 + 提交 + 轮询 --------------------


def _async_extract_url(data: Any) -> str:
    """从异步视频响应中尽量提取直链视频 URL（兼容多字段与嵌套）。"""
    if not isinstance(data, dict):
        return ""
    for k in ("result_url", "video_url", "url", "download_url", "file_url"):
        v = data.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
    video = data.get("video")
    if isinstance(video, dict):
        v = video.get("url")
        if isinstance(v, str) and v.startswith("http"):
            return v
    for parent in ("data", "output", "result"):
        inner = data.get(parent)
        if isinstance(inner, dict):
            u = _async_extract_url(inner)
            if u:
                return u
    return ""


_ASYNC_DONE = ("completed", "succeeded", "success", "done", "finished", "complete", "generated")
_ASYNC_FAIL = ("failed", "cancelled", "canceled", "error", "fail")


def _async_status(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for k in ("status", "state", "task_status", "job_status"):
        v = data.get(k)
        if isinstance(v, str) and v:
            return v.lower()
    inner = data.get("data")
    if isinstance(inner, dict):
        for k in ("status", "state", "task_status", "job_status"):
            v = inner.get(k)
            if isinstance(v, str) and v:
                return v.lower()
    return ""


def _submit_async_video(cfg, body: dict, timeout: int = 300) -> tuple[str, str]:
    """POST /v1/videos，返回 (直链 URL, task_id)。"""
    resp = api_request(cfg, "POST", "/v1/videos", json_body=body, retries=2, timeout=max(cfg.timeout, timeout))
    data = resp.json() if resp.content else {}
    return (_async_extract_url(data), _sd2_extract_task_id(data))


def _async_poll(cfg, task_id: str, interval: int = 5, timeout: int = 1800) -> str:
    start = time.time()
    last = ""
    while time.time() - start < timeout:
        try:
            resp = api_request(cfg, "GET", f"/v1/videos/{task_id}", retries=1, timeout=60)
        except RespectAPIError as exc:
            print(f"[Respect] 轮询错误，继续重试: {exc}")
            time.sleep(interval)
            continue
        data = resp.json() if resp.content else {}
        url = _async_extract_url(data)
        status = _async_status(data)
        if status and status != last:
            print(f"[Respect] 任务 {task_id} 状态: {status}")
            last = status
        if status in _ASYNC_FAIL:
            raise RespectAPIError(f"任务失败: {json.dumps(data, ensure_ascii=False)[:600]}")
        if url and (not status or status in _ASYNC_DONE):
            return url
        if status in _ASYNC_DONE:
            base = cfg.normalized_base().rsplit("/v1", 1)[0]
            return url or f"{base}/v1/videos/{task_id}/content"
        time.sleep(interval)
    raise RespectAPIError(f"任务超时: {task_id}")


def _finalize_async(cfg, direct: str, task_id: str, *, poll_interval: int, poll_timeout: int,
                    auto_download: bool, prefix: str, save_dir: str, filename: str) -> tuple[str, str, str]:
    if direct:
        url = direct
    elif task_id:
        url = _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
    else:
        raise RespectAPIError("提交未返回 task_id 或视频 URL")
    local = ""
    if auto_download and url:
        try:
            local = download_to_output(url, cfg, prefix=prefix, save_dir=save_dir, filename=filename)
        except Exception as exc:
            print(f"[Respect] {prefix} 视频下载失败: {exc}")
    return (url, local, task_id or "")


# ---------------------------------------------------------------------------
# Kling3 / Kling3-Omni（chat completions SSE，同 VEO31/Sora2 机制）
# ---------------------------------------------------------------------------


KLING3_VARIANTS = ["kling3", "kling3omni"]
KLING3_ASPECTS = ["16:9", "9:16", "1:1"]
KLING3_RESOLUTIONS = ["1080p", "720p"]
KLING3_MODES = ["文生视频", "首帧生成视频", "首尾帧生成视频"]


class RespectFireflyKling3:
    """Firefly 可灵3.0 / 可灵3.0 Omni 视频。
    模型 ID：`firefly-kling3[omni]-{秒数}s-{比例x}-{清晰度}`。
    走 `/v1/chat/completions` 流式。`custom_model` 填了优先使用。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "variant": (KLING3_VARIANTS, {"default": "kling3"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": ("INT", {"default": 5, "min": 1, "max": 60}),
                "aspect_ratio": (KLING3_ASPECTS, {"default": "16:9"}),
                "resolution": (KLING3_RESOLUTIONS, {"default": "1080p"}),
                "generation_mode": (KLING3_MODES, {"default": "文生视频"}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "first_frame": ("IMAGE",),
                "last_frame": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，如 firefly-kling3-15s-16x9-1080p"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(
        self,
        api_config: Any,
        variant: str,
        prompt: str,
        duration: int,
        aspect_ratio: str,
        resolution: str,
        generation_mode: str,
        auto_download: bool,
        first_frame: Optional[torch.Tensor] = None,
        last_frame: Optional[torch.Tensor] = None,
        custom_model: str = "",
        save_dir: str = "",
        filename: str = "",
    ) -> tuple[str, str, str]:
        cfg = ensure_config(api_config)
        custom_model = (custom_model or "").strip()
        if custom_model:
            model = custom_model
        else:
            family = "firefly-kling3omni" if variant == "kling3omni" else "firefly-kling3"
            model = f"{family}-{int(duration)}s-{aspect_ratio.replace(':', 'x')}-{resolution}"

        if generation_mode == "首帧生成视频":
            if first_frame is None:
                raise RespectAPIError("首帧生成视频需要提供 first_frame")
            imgs = [first_frame]
        elif generation_mode == "首尾帧生成视频":
            if first_frame is None or last_frame is None:
                raise RespectAPIError("首尾帧生成视频需要同时提供 first_frame 和 last_frame")
            imgs = [first_frame, last_frame]
        else:
            imgs = []

        url, _ = _call_chat_video(
            cfg, model, prompt, imgs,
            aspect_ratio=aspect_ratio, video_length=int(duration), resolution=resolution, stream=True,
        )
        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="kling3", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] Kling3 视频下载失败: {exc}")
        return (url, local, model)


# ---------------------------------------------------------------------------
# Sora V3（异步 /v1/videos + video_config 轮询）
# ---------------------------------------------------------------------------


SORA_V3_MODELS = ["sora-v3-fast", "sora-v3-pro"]
SORA_V3_ASPECTS = ["16:9", "9:16", "1:1"]
SORA_V3_RESOLUTIONS = ["720p", "480p"]
SORA_V3_MODES = ["文生视频", "首帧生成视频", "首尾帧生成视频", "参考图生成视频", "多参考图生成视频"]
_SORA_REF_MODE = {
    "首帧生成视频": "start_frame",
    "首尾帧生成视频": "start_end",
    "参考图生成视频": "image_reference",
    "多参考图生成视频": "image_reference",
    "文生视频": "auto",
}
_SORA_SIZE = {
    "720p": {"16:9": "1280x720", "9:16": "720x1280", "1:1": "720x720"},
    "480p": {"16:9": "854x480", "9:16": "480x854", "1:1": "480x480"},
}


class RespectSoraV3Video:
    """Sora V3 (pro/fast) 异步视频。`POST /v1/videos` 提交后轮询 `GET /v1/videos/{id}`。
    支持 文生 / 首帧 / 首尾帧 / 参考图 / 多参考图（最多 4 张）。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "model": (SORA_V3_MODELS, {"default": "sora-v3-fast"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": ("INT", {"default": 6, "min": 1, "max": 60}),
                "aspect_ratio": (SORA_V3_ASPECTS, {"default": "16:9"}),
                "resolution": (SORA_V3_RESOLUTIONS, {"default": "720p"}),
                "generation_mode": (SORA_V3_MODES, {"default": "文生视频"}),
                "poll_interval": ("INT", {"default": 5, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "first_frame": ("IMAGE",),
                "last_frame": ("IMAGE",),
                "ref_image_1": ("IMAGE",),
                "ref_image_2": ("IMAGE",),
                "ref_image_3": ("IMAGE",),
                "ref_image_4": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了优先使用"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(
        self,
        api_config: Any,
        model: str,
        prompt: str,
        duration: int,
        aspect_ratio: str,
        resolution: str,
        generation_mode: str,
        poll_interval: int,
        poll_timeout: int,
        auto_download: bool,
        first_frame: Optional[torch.Tensor] = None,
        last_frame: Optional[torch.Tensor] = None,
        ref_image_1: Optional[torch.Tensor] = None,
        ref_image_2: Optional[torch.Tensor] = None,
        ref_image_3: Optional[torch.Tensor] = None,
        ref_image_4: Optional[torch.Tensor] = None,
        custom_model: str = "",
        save_dir: str = "",
        filename: str = "",
    ) -> tuple[str, str, str]:
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        size = _SORA_SIZE.get(resolution, {}).get(aspect_ratio, "1280x720")
        ref_mode = _SORA_REF_MODE.get(generation_mode, "auto")
        duration = int(duration)

        if generation_mode == "首帧生成视频":
            if first_frame is None:
                raise RespectAPIError("首帧生成视频需要提供 first_frame")
            imgs = [first_frame]
        elif generation_mode == "首尾帧生成视频":
            if first_frame is None or last_frame is None:
                raise RespectAPIError("首尾帧生成视频需要同时提供 first_frame 和 last_frame")
            imgs = [first_frame, last_frame]
        elif generation_mode == "参考图生成视频":
            imgs = [ref_image_1]
        elif generation_mode == "多参考图生成视频":
            imgs = [ref_image_1, ref_image_2, ref_image_3, ref_image_4]
        else:
            imgs = []

        body: dict = {
            "model": model,
            "prompt": prompt,
            "duration": duration,
            "seconds": str(duration),
            "size": size,
            "video_config": {
                "aspect_ratio": aspect_ratio,
                "resolution_name": resolution,
                "reference_mode": ref_mode,
            },
        }
        ref_urls = _img_data_urls(imgs)
        if ref_urls:
            body["reference_images"] = ref_urls

        direct, task_id = _submit_async_video(cfg, body, timeout=300)
        return _finalize_async(
            cfg, direct, task_id,
            poll_interval=poll_interval, poll_timeout=poll_timeout,
            auto_download=auto_download, prefix="sora_v3", save_dir=save_dir, filename=filename,
        )


# ---------------------------------------------------------------------------
# Grok 视频（异步 /v1/videos，1.0 类 / 1.5 preview 类两种 body）
# ---------------------------------------------------------------------------


# 变体即 model_id（按 07.06 源码；custom_model 可覆盖）
GROK_VIDEO_VARIANTS = [
    "grok-imagine-1.0-video",
    "grok-1.0-官转接口",
    "grok-1.0-备用接口",
    "grok-imagine-video-1.5-fast",
    "grok-imagine-video-preview",
    "grok-imagine-video-1.5-preview",
    "grok-1.5-官转接口",
    "grok-1.5-备用接口",
]
# 1.0 体：duration + video_config + reference_images（文生/首帧/多参考≤7）
_GROK_ONE_CLASS = {
    "grok-imagine-1.0-video", "grok-1.0-官转接口", "grok-1.0-备用接口",
    "grok-imagine-video-1.5-fast",
}
# 1.5 体：seconds + size + images（仅首帧）
_GROK_FIRSTFRAME_CLASS = {
    "grok-imagine-video-preview", "grok-imagine-video-1.5-preview",
    "grok-1.5-官转接口", "grok-1.5-备用接口",
}
# 1.5 体里不把首帧重复第二次的（官转/备用）
_GROK_NO_DUP = {"grok-1.5-官转接口", "grok-1.5-备用接口"}
GROK_BODY_STYLES = ["auto", "1.0类", "1.5类"]
GROK_ASPECTS = ["16:9", "9:16", "3:2", "1:1"]
GROK_RESOLUTIONS = ["720p", "1080p", "480p"]
GROK_MODES = ["文生视频", "首帧生成视频", "多参考图生成视频"]
_GROK_SIZE = {
    "16:9": "1280x720", "9:16": "720x1280", "1:1": "1024x1024",
    "3:2": "1792x1024", "2:3": "1024x1792",
}
_GROK_15_DURATIONS = (6, 10, 15)


def _grok_clamp_15_duration(vl: int) -> int:
    vl = int(vl or 6)
    if vl in _GROK_15_DURATIONS:
        return vl
    lower = [d for d in _GROK_15_DURATIONS if d <= vl]
    return max(lower) if lower else 6


def _grok_resolution_hdsd(resolution: str) -> str:
    return "SD" if str(resolution or "").lower() in ("480p", "sd") else "HD"


class RespectGrokVideo:
    """Grok 视频系列（异步 `/v1/videos`）。

    按 07.06 源码分两种请求体：
    - **1.0 体**（grok-imagine-1.0-video / grok-1.0-官转/备用 / **grok-imagine-video-1.5-fast**）：
      body 带 duration + resolution(HD/SD) + video_config + reference_images(base64)，
      支持 文生 / 首帧 / 多参考图（最多 7 张）。
    - **1.5 体**（preview / 1.5-preview / 1.5-官转 / 1.5-备用）：
      body 用 seconds + size + images，**仅首帧**；官转/备用不重复首帧，其余重复 2 次。

    `custom_model` 填了优先使用。`body_style`：auto 按已知变体判断（自定义则含 preview 视为 1.5 体），
    也可手动指定 1.0类 / 1.5类。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "model_variant": (GROK_VIDEO_VARIANTS, {"default": "grok-imagine-1.0-video"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": ("INT", {"default": 6, "min": 1, "max": 60}),
                "aspect_ratio": (GROK_ASPECTS, {"default": "16:9"}),
                "resolution": (GROK_RESOLUTIONS, {"default": "720p"}),
                "generation_mode": (GROK_MODES, {"default": "文生视频"}),
                "poll_interval": ("INT", {"default": 5, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了优先使用，如 grok-imagine-video-1.5-fast"}),
                "body_style": (GROK_BODY_STYLES, {"default": "auto"}),
                "first_frame": ("IMAGE",),
                "ref_image_1": ("IMAGE",),
                "ref_image_2": ("IMAGE",),
                "ref_image_3": ("IMAGE",),
                "ref_image_4": ("IMAGE",),
                "ref_image_5": ("IMAGE",),
                "ref_image_6": ("IMAGE",),
                "ref_image_7": ("IMAGE",),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(
        self,
        api_config: Any,
        model_variant: str,
        prompt: str,
        duration: int,
        aspect_ratio: str,
        resolution: str,
        generation_mode: str,
        poll_interval: int,
        poll_timeout: int,
        auto_download: bool,
        custom_model: str = "",
        body_style: str = "auto",
        first_frame: Optional[torch.Tensor] = None,
        ref_image_1: Optional[torch.Tensor] = None,
        ref_image_2: Optional[torch.Tensor] = None,
        ref_image_3: Optional[torch.Tensor] = None,
        ref_image_4: Optional[torch.Tensor] = None,
        ref_image_5: Optional[torch.Tensor] = None,
        ref_image_6: Optional[torch.Tensor] = None,
        ref_image_7: Optional[torch.Tensor] = None,
        save_dir: str = "",
        filename: str = "",
    ) -> tuple[str, str, str]:
        cfg = ensure_config(api_config)
        model_id = (custom_model or "").strip() or model_variant
        duration = int(duration)

        if body_style == "1.5类":
            is_15 = True
        elif body_style == "1.0类":
            is_15 = False
        elif model_id in _GROK_FIRSTFRAME_CLASS:
            is_15 = True
        elif model_id in _GROK_ONE_CLASS:
            is_15 = False
        else:  # 自定义：含 preview 视为仅首帧 1.5 体，否则按 1.0 体
            is_15 = "preview" in model_id.lower()

        if is_15:
            # 1.5 体：仅首帧，seconds + size + images
            if first_frame is None:
                raise RespectAPIError("该模型（1.5 体）仅支持首帧生成视频，需要提供 first_frame")
            vl = _grok_clamp_15_duration(duration)
            urls = _img_data_urls([first_frame])
            images = list(urls)
            if model_id not in _GROK_NO_DUP and urls:
                images.append(urls[0])  # 非官转/备用：首帧重复 2 次
            body: dict = {
                "model": model_id,
                "prompt": prompt,
                "seconds": str(vl),
                "size": _GROK_SIZE.get(aspect_ratio, "1280x720"),
                "images": images,
            }
        else:
            # 1.0 体：duration + resolution(HD/SD) + video_config + reference_images
            res_up = _grok_resolution_hdsd(resolution)
            if generation_mode == "首帧生成视频":
                if first_frame is None:
                    raise RespectAPIError("首帧生成视频需要提供 first_frame")
                imgs = [first_frame]
            elif generation_mode == "多参考图生成视频":
                imgs = [ref_image_1, ref_image_2, ref_image_3, ref_image_4,
                        ref_image_5, ref_image_6, ref_image_7]
            else:
                imgs = []
            body = {
                "model": model_id,
                "prompt": prompt,
                "duration": duration,
                "video_length": duration,
                "aspect_ratio": aspect_ratio,
                "resolution": res_up,
                "video_config": {
                    "video_length": duration,
                    "aspect_ratio": aspect_ratio,
                    "resolution": res_up,
                    "preset": "normal",
                },
            }
            ref_urls = _img_data_urls(imgs, max_side=1536)[:7]
            if ref_urls:
                body["reference_images"] = ref_urls

        direct, task_id = _submit_async_video(cfg, body, timeout=300)
        url, local, _ = _finalize_async(
            cfg, direct, task_id,
            poll_interval=poll_interval, poll_timeout=poll_timeout,
            auto_download=auto_download, prefix="grok", save_dir=save_dir, filename=filename,
        )
        return (url, local, model_id)


NODE_CLASS_MAPPINGS = {
    "RespectFireflySora2": RespectFireflySora2,
    "RespectFireflyVeo31": RespectFireflyVeo31,
    "RespectFireflyRunway45": RespectFireflyRunway45,
    "RespectFireflyKling3": RespectFireflyKling3,
    "RespectSoraV3Video": RespectSoraV3Video,
    "RespectGrokVideo": RespectGrokVideo,
    "RespectSD2Video": RespectSD2Video,
    "RespectSaveVideo": RespectSaveVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectFireflySora2": "Respect Firefly Sora2 视频",
    "RespectFireflyVeo31": "Respect Firefly VEO3.1 视频",
    "RespectFireflyRunway45": "Respect Firefly Runway 4.5 视频",
    "RespectFireflyKling3": "Respect Firefly 可灵3.0 视频",
    "RespectSoraV3Video": "Respect Sora V3 视频",
    "RespectGrokVideo": "Respect Grok 视频",
    "RespectSD2Video": "Respect 即梦/SD2 视频",
    "RespectSaveVideo": "Respect 保存视频",
}
