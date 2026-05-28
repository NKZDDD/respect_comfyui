"""小裴 ComfyUI 扩展 - 视频生成节点。

接口逻辑详见 `小裴视频文档.md`。
"""

from __future__ import annotations

import io
import json
import time
from typing import Any, Optional

import torch

from .utils import (
    XiaopeiAPIError,
    api_request,
    collect_stream_text,
    download_to_output,
    ensure_config,
    extract_video_urls,
    tensor_to_b64,
    tensor_to_pil,
)


CATEGORY = "小裴/Xiaopei"


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
        raise XiaopeiAPIError(f"未能从响应中提取视频 URL: {snippet}")
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


class XiaopeiFireflySora2:
    """Firefly Sora2 视频生成。模型 ID 由参数自动拼接：
    `firefly-sora2[-pro]-{秒数}s-{比例x}`。
    填了 `custom_model` 时优先使用，方便手动指定任意官方模型名。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("XIAOPEI_CONFIG",),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": (SORA2_DURATIONS, {"default": "8"}),
                "aspect_ratio": (SORA2_ASPECTS, {"default": "16:9"}),
                "use_pro": ("BOOLEAN", {"default": False}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "first_frame": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了优先使用，如 firefly-sora2-pro-12s-16x9"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/xiaopei，相对路径基于 output，支持绝对路径"}),
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
                print(f"[Xiaopei] Sora2 视频下载失败: {exc}")
        return (url, local, model)


# ---------------------------------------------------------------------------
# VEO 3.1
# ---------------------------------------------------------------------------


VEO31_DURATIONS = ["4", "6", "8"]
VEO31_ASPECTS = ["16:9", "9:16"]
VEO31_RESOLUTIONS = ["720p", "1080p"]
VEO31_VARIANTS = ["default", "fast", "ref"]


class XiaopeiFireflyVeo31:
    """Firefly VEO 3.1 视频生成。
    模型 ID 拼接：`firefly-veo31[-fast|-ref]-{秒数}s-{比例x}-{清晰度}`。
    填了 `custom_model` 时优先使用，方便手动指定 pro / components / 4k 等变体。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("XIAOPEI_CONFIG",),
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
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/xiaopei，相对路径基于 output，支持绝对路径"}),
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
                print(f"[Xiaopei] VEO3.1 视频下载失败: {exc}")
        return (url, local, model)


# ---------------------------------------------------------------------------
# Runway 4.5
# ---------------------------------------------------------------------------


RUNWAY45_DURATIONS = ["5", "10"]
RUNWAY45_ASPECTS = ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "9:21"]


class XiaopeiFireflyRunway45:
    """Firefly Runway 4.5 视频生成。
    模型 ID：`firefly-runway45-{秒数}s-{比例x}-720p`。
    填了 `custom_model` 时优先使用。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("XIAOPEI_CONFIG",),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": (RUNWAY45_DURATIONS, {"default": "5"}),
                "aspect_ratio": (RUNWAY45_ASPECTS, {"default": "16:9"}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "first_frame": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了优先使用，如 firefly-runway45-10s-21x9-720p"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/xiaopei，相对路径基于 output，支持绝对路径"}),
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
                print(f"[Xiaopei] Runway 4.5 视频下载失败: {exc}")
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
        except XiaopeiAPIError as exc:
            print(f"[Xiaopei] SD2 轮询错误，继续重试: {exc}")
            time.sleep(interval)
            continue
        data = resp.json() if resp.content else {}
        status = str(data.get("status", "")).lower()
        if status and status != last_status:
            print(f"[Xiaopei] SD2 任务 {task_id} 状态: {status}")
            last_status = status
        if status in ("completed", "succeeded", "success"):
            url = _sd2_extract_direct_url(data)
            if url:
                return url
            base = cfg.normalized_base().rsplit("/v1", 1)[0]
            return f"{base}/v1/videos/{task_id}/content"
        if status in ("failed", "cancelled", "canceled", "error"):
            raise XiaopeiAPIError(f"SD2 任务失败: {json.dumps(data, ensure_ascii=False)[:600]}")
        time.sleep(interval)
    raise XiaopeiAPIError(f"SD2 任务超时: {task_id}")


class XiaopeiSD2Video:
    """即梦 / SD2 视频生成。

    无参考图走 JSON `/v1/videos`；有参考图自动切换到 multipart 上传。
    然后轮询 `/v1/videos/{task_id}` 直到完成。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("XIAOPEI_CONFIG",),
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
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/xiaopei，相对路径基于 output，支持绝对路径"}),
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
            raise XiaopeiAPIError(f"SD2 提交未返回 task_id 或视频 URL: {json.dumps(data, ensure_ascii=False)[:600]}")

        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="sd2", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Xiaopei] SD2 视频下载失败: {exc}")

        return (url, local, task_id or "")


# ---------------------------------------------------------------------------
# 通用视频保存
# ---------------------------------------------------------------------------


class XiaopeiSaveVideo:
    """把视频 URL 下载到指定位置。可以单独使用。

    - `save_dir` 留空 → `ComfyUI/output/xiaopei/`
    - `save_dir` 相对路径 → 基于 ComfyUI output 目录
    - `save_dir` 绝对路径 → 直接使用，例如 `D:\\videos\\veo31`
    - `filename` 留空 → 自动 `<prefix>_<时间戳>_<6位hash>.mp4`
    - `filename` 非空 → 直接用，没扩展名自动补 `.mp4`
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("XIAOPEI_CONFIG",),
                "video_url": ("STRING", {"default": "", "multiline": False, "forceInput": True}),
            },
            "optional": {
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/xiaopei，相对路径基于 output，支持绝对路径"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳；无扩展名自动补 .mp4"}),
                "prefix": ("STRING", {"default": "xiaopei", "multiline": False, "placeholder": "仅当 filename 为空时用于自动命名"}),
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
        prefix: str = "xiaopei",
    ) -> tuple[str]:
        if not video_url:
            return ("",)
        cfg = ensure_config(api_config)
        try:
            path = download_to_output(
                video_url,
                cfg,
                prefix=prefix or "xiaopei",
                save_dir=save_dir,
                filename=filename,
            )
            print(f"[Xiaopei] 视频已保存: {path}")
            return (path,)
        except Exception as exc:
            print(f"[Xiaopei] 视频保存失败: {exc}")
            return ("",)


NODE_CLASS_MAPPINGS = {
    "XiaopeiFireflySora2": XiaopeiFireflySora2,
    "XiaopeiFireflyVeo31": XiaopeiFireflyVeo31,
    "XiaopeiFireflyRunway45": XiaopeiFireflyRunway45,
    "XiaopeiSD2Video": XiaopeiSD2Video,
    "XiaopeiSaveVideo": XiaopeiSaveVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "XiaopeiFireflySora2": "小裴 Firefly Sora2 视频",
    "XiaopeiFireflyVeo31": "小裴 Firefly VEO3.1 视频",
    "XiaopeiFireflyRunway45": "小裴 Firefly Runway 4.5 视频",
    "XiaopeiSD2Video": "小裴 即梦/SD2 视频",
    "XiaopeiSaveVideo": "小裴 保存视频",
}
