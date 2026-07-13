"""Respect ComfyUI 扩展 - Seedance / SD 2.0 全系列视频节点（07.06 更新）。

这几类模型的参考图**必须是公网 URL**（不接受 base64），所以节点会先把 IMAGE 上传到
`{base_url}/v1/uploads` 换成引用（优先公网 URL，兼容返回 name），再提交生成任务。

- sd2.0 全系列(按秒)  `sd2_all`    → POST /v1/videos，body 带 metadata{modeType,ratio,enableSound}+images
- Seedance9 九图/官方稳定 `seedance9` → POST /v1/videos（fast 与 官方稳定 两种 body）
- Seedance 四参考图版   `seedance`   → POST /v1/video/generations（start/end/image_url(s)）
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

import torch

from .utils import (
    RespectAPIError,
    api_request,
    download_to_output,
    ensure_config,
)
from .video_nodes import (
    _async_extract_url,
    _async_poll,
    _async_status,
    _sd2_extract_task_id,
    _submit_async_video,
    _tensor_to_jpeg_bytes,
    _ASYNC_DONE,
    _ASYNC_FAIL,
)

CATEGORY = "Respect"


# ---------------------------------------------------------------------------
# 公网图上传：IMAGE -> {base_url}/v1/uploads -> 引用（URL 优先，兼容 name）
# ---------------------------------------------------------------------------


def _extract_upload_token(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    inner = data.get("data") if isinstance(data.get("data"), dict) else {}
    for src in (data, inner):
        for k in ("image_url", "url", "file_url", "download_url"):
            v = src.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
        for k in ("image_urls", "urls"):
            v = src.get(k)
            if isinstance(v, list) and v and isinstance(v[0], str) and v[0].startswith("http"):
                return v[0]
    # 回退：API(1).md 的 name 协议
    for src in (data, inner):
        v = src.get("name")
        if isinstance(v, str) and v:
            return v
    return ""


def _upload_reference(cfg, tensor: torch.Tensor, index: int = 1) -> str:
    data = _tensor_to_jpeg_bytes(tensor, max_side=1536, quality=90)
    if not data:
        raise RespectAPIError(f"参考图{index} 为空，无法上传")
    resp = api_request(
        cfg, "POST", "/v1/uploads",
        files=[("file", (f"ref_{index}.jpg", data, "image/jpeg"))],
        retries=2, timeout=max(cfg.timeout, 300),
    )
    try:
        payload = resp.json()
    except Exception:
        raise RespectAPIError(f"上传返回非 JSON: {resp.text[:200]}")
    token = _extract_upload_token(payload)
    if not token:
        raise RespectAPIError(f"上传未返回可用引用(url/name): {json.dumps(payload, ensure_ascii=False)[:300]}")
    return token


def _upload_all(cfg, tensors: list[Optional[torch.Tensor]]) -> list[str]:
    tokens: list[str] = []
    idx = 0
    for t in tensors:
        if t is None or (hasattr(t, "numel") and t.numel() == 0):
            continue
        idx += 1
        tokens.append(_upload_reference(cfg, t, idx))
    return tokens


def _collect_mode_tensors(
    mode: str,
    first_frame: Optional[torch.Tensor],
    last_frame: Optional[torch.Tensor],
    refs: list[Optional[torch.Tensor]],
) -> list[Optional[torch.Tensor]]:
    """按生成模式收集需要上传的图（顺序即 image 1/2/3...）。"""
    valid_refs = [r for r in refs if r is not None and (not hasattr(r, "numel") or r.numel() > 0)]
    if mode == "首帧生成视频":
        if first_frame is None:
            raise RespectAPIError("首帧生成视频需要提供 first_frame")
        return [first_frame]
    if mode == "首尾帧生成视频":
        if first_frame is None or last_frame is None:
            raise RespectAPIError("首尾帧生成视频需要同时提供 first_frame 和 last_frame")
        return [first_frame, last_frame]
    if mode == "多参考图生成视频":
        if not valid_refs:
            raise RespectAPIError("多参考图生成视频需要至少一张参考图")
        return list(valid_refs)
    if mode == "首帧+参考图生成视频":
        if first_frame is None:
            raise RespectAPIError("首帧+参考图生成视频需要提供 first_frame")
        if not valid_refs:
            raise RespectAPIError("首帧+参考图生成视频需要至少一张参考图")
        return [first_frame] + list(valid_refs)
    return []  # 文生视频


def _tag_prompt(prompt: str, mode: str, n_images: int) -> str:
    """按源码给 prompt 追加 @图N 标记（提升这些模型的参考图识别）。"""
    p = prompt or ""
    if mode == "首帧生成视频":
        if "当前图片为视频固定首帧" not in p:
            p = f"{p} @图1 当前图片为视频固定首帧".strip()
    elif mode == "首尾帧生成视频":
        if "当前图片为视频固定首帧" not in p:
            p = f"{p} @图1 当前图片为视频固定首帧 @图2 当前图片为视频固定尾帧".strip()
    elif mode == "多参考图生成视频":
        if "@图" not in p and n_images:
            tags = " ".join(f"@图{i + 1}" for i in range(n_images))
            p = f"{p} {tags}".strip()
    elif mode == "首帧+参考图生成视频":
        if "当前图片为视频固定首帧" not in p:
            p = f"{p} @图1 当前图片为视频固定首帧".strip()
        if n_images > 1 and "@图2" not in p:
            tags = " ".join(f"@图{i + 1}" for i in range(1, n_images))
            p = f"{p} {tags}".strip()
    return p


# ---------------------------------------------------------------------------
# SD2.0 全系列(按秒) —— sd2_all
# ---------------------------------------------------------------------------


SD2_ALL_MODELS = [
    "sd2-1080p", "sd2-1080p-fast", "sd2-1080p-mini",
    "sd2-720p", "sd2-720p-fast", "sd2-720p-mini",
]
SD_ASPECTS = ["16:9", "9:16", "1:1"]
SD_ALL_MODES = ["文生视频", "首帧生成视频", "首尾帧生成视频", "多参考图生成视频", "首帧+参考图生成视频"]


def _sd_mode_type(mode: str, has_image: bool) -> str:
    if mode == "首尾帧生成视频":
        return "frames2video"
    if has_image:
        return "image2video"
    return "text2video"


class RespectSD2AllVideo:
    """SD2.0 全系列(按秒)。`POST /v1/videos`，参考图先上传换公网 URL。

    模型：sd2-1080p / -fast / -mini、sd2-720p / -fast / -mini。最多 9 张图。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "model": (SD2_ALL_MODELS, {"default": "sd2-1080p-fast"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": ("INT", {"default": 5, "min": 4, "max": 15}),
                "aspect_ratio": (SD_ASPECTS, {"default": "16:9"}),
                "generation_mode": (SD_ALL_MODES, {"default": "文生视频"}),
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
                "ref_image_5": ("IMAGE",),
                "ref_image_6": ("IMAGE",),
                "ref_image_7": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了优先使用"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, duration, aspect_ratio, generation_mode,
                 poll_interval, poll_timeout, auto_download,
                 first_frame=None, last_frame=None,
                 ref_image_1=None, ref_image_2=None, ref_image_3=None, ref_image_4=None,
                 ref_image_5=None, ref_image_6=None, ref_image_7=None,
                 custom_model="", save_dir="", filename=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        refs = [ref_image_1, ref_image_2, ref_image_3, ref_image_4, ref_image_5, ref_image_6, ref_image_7]
        tensors = _collect_mode_tensors(generation_mode, first_frame, last_frame, refs)[:9]
        image_urls = _upload_all(cfg, tensors)
        final_prompt = _tag_prompt(prompt, generation_mode, len(image_urls))

        body: dict = {
            "model": model,
            "prompt": final_prompt,
            "duration": int(duration),
            "metadata": {
                "modeType": _sd_mode_type(generation_mode, bool(image_urls)),
                "ratio": aspect_ratio or "16:9",
                "enableSound": "on",
            },
        }
        if image_urls:
            body["images"] = image_urls

        direct, task_id = _submit_async_video(cfg, body, timeout=300)
        return _finalize_sd(cfg, direct, task_id, poll_interval, poll_timeout,
                            auto_download, "sd2", save_dir, filename)


# ---------------------------------------------------------------------------
# Seedance9 九图版 / 官方稳定版 —— seedance9
# ---------------------------------------------------------------------------


SEEDANCE9_MODELS = [
    "seedance2.0-fast",
    "官方稳定seedance-2.0-720p-fast",
    "官方稳定seedance-2.0-720p-max",
]
SEEDANCE9_MODES = ["文生视频", "首帧生成视频", "首尾帧生成视频", "多参考图生成视频", "首帧+参考图生成视频"]


class RespectSeedance9Video:
    """Seedance9 九图版 / 官方稳定版。`POST /v1/videos`，参考图先上传换公网 URL，最多 9 张。

    `seedance2.0-fast` 走 fast body；`官方稳定*` 走 official_compat body（metadata.mode_type）。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "model": (SEEDANCE9_MODELS, {"default": "seedance2.0-fast"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": ("INT", {"default": 15, "min": 4, "max": 15}),
                "aspect_ratio": (SD_ASPECTS, {"default": "16:9"}),
                "generation_mode": (SEEDANCE9_MODES, {"default": "文生视频"}),
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
                "ref_image_5": ("IMAGE",),
                "ref_image_6": ("IMAGE",),
                "ref_image_7": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了优先使用"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, duration, aspect_ratio, generation_mode,
                 poll_interval, poll_timeout, auto_download,
                 first_frame=None, last_frame=None,
                 ref_image_1=None, ref_image_2=None, ref_image_3=None, ref_image_4=None,
                 ref_image_5=None, ref_image_6=None, ref_image_7=None,
                 custom_model="", save_dir="", filename=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        official = model.startswith("官方稳定")
        refs = [ref_image_1, ref_image_2, ref_image_3, ref_image_4, ref_image_5, ref_image_6, ref_image_7]
        tensors = _collect_mode_tensors(generation_mode, first_frame, last_frame, refs)[:9]
        image_urls = _upload_all(cfg, tensors)
        final_prompt = _tag_prompt(prompt, generation_mode, len(image_urls))
        vl = int(duration or 15)

        if official:
            mode_type = "text2video"
            if generation_mode == "首尾帧生成视频":
                mode_type = "frames2video"
            elif image_urls:
                mode_type = "image2video"
            metadata: dict = {"resolution": "720p", "size": aspect_ratio or "16:9", "mode_type": mode_type}
            body: dict = {
                "model": model,
                "prompt": final_prompt,
                "seconds": str(vl),
                "size": aspect_ratio or "16:9",
                "n": 1,
                "metadata": metadata,
            }
            if image_urls:
                body["image"] = image_urls[0]
            if len(image_urls) > 1:
                metadata["images"] = image_urls[1:]
        else:
            body = {
                "model": model,
                "prompt": final_prompt,
                "resolution": "720p",
                "duration": vl,
                "seconds": str(vl),
                "aspect_ratio": aspect_ratio or "16:9",
                "client_task_id": f"comfyui-{uuid.uuid4().hex}",
            }
            if len(image_urls) == 1:
                body["image_url"] = image_urls[0]
            elif len(image_urls) > 1:
                body["image_urls"] = image_urls

        direct, task_id = _submit_async_video(cfg, body, timeout=300)
        return _finalize_sd(cfg, direct, task_id, poll_interval, poll_timeout,
                            auto_download, "seedance9", save_dir, filename)


# ---------------------------------------------------------------------------
# Seedance 四参考图版 —— seedance（端点 /v1/video/generations）
# ---------------------------------------------------------------------------


SEEDANCE_FOUR_MODELS = ["video-2.0-fast", "video-2.0"]
SEEDANCE_FOUR_MODES = ["文生视频", "首帧生成视频", "首尾帧生成视频", "多参考图生成视频"]


def _seedance_size(aspect_ratio: str) -> str:
    ar = (aspect_ratio or "16:9").strip()
    if ar == "9:16":
        return "720x1280"
    if ar == "1:1":
        return "720x720"
    return "1280x720"


def _seedance_submit_poll(cfg, body: dict, poll_interval: int, poll_timeout: int) -> tuple[str, str]:
    """四参考图版专用：POST /v1/video/generations + 轮询 /v1/video/generations/{id}。"""
    resp = api_request(cfg, "POST", "/v1/video/generations", json_body=body,
                       retries=2, timeout=max(cfg.timeout, 300))
    data = resp.json() if resp.content else {}
    url = _async_extract_url(data)
    task_id = _sd2_extract_task_id(data)
    if url:
        return url, task_id
    if not task_id:
        raise RespectAPIError(f"提交未返回 task_id 或视频 URL: {json.dumps(data, ensure_ascii=False)[:400]}")

    start = time.time()
    last = ""
    while time.time() - start < poll_timeout:
        try:
            r = api_request(cfg, "GET", f"/v1/video/generations/{task_id}", retries=1, timeout=60)
        except RespectAPIError as exc:
            print(f"[Respect] Seedance 轮询错误，继续重试: {exc}")
            time.sleep(poll_interval)
            continue
        d = r.json() if r.content else {}
        u = _async_extract_url(d)
        status = _async_status(d)
        if status and status != last:
            print(f"[Respect] Seedance 任务 {task_id} 状态: {status}")
            last = status
        if status in _ASYNC_FAIL:
            raise RespectAPIError(f"任务失败: {json.dumps(d, ensure_ascii=False)[:400]}")
        if u and (not status or status in _ASYNC_DONE):
            return u, task_id
        time.sleep(poll_interval)
    raise RespectAPIError(f"任务超时: {task_id}")


class RespectSeedanceFourRefVideo:
    """Seedance 四参考图版（video-2.0 / -fast）。端点 `POST /v1/video/generations`。

    参考图先上传换公网 URL；固定 15 秒、720p。最多 4 张参考图。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "model": (SEEDANCE_FOUR_MODELS, {"default": "video-2.0-fast"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "aspect_ratio": (SD_ASPECTS, {"default": "16:9"}),
                "generation_mode": (SEEDANCE_FOUR_MODES, {"default": "首帧生成视频"}),
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

    def generate(self, api_config, model, prompt, aspect_ratio, generation_mode,
                 poll_interval, poll_timeout, auto_download,
                 first_frame=None, last_frame=None,
                 ref_image_1=None, ref_image_2=None, ref_image_3=None, ref_image_4=None,
                 custom_model="", save_dir="", filename=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model

        body: dict = {
            "model": model,
            "prompt": prompt,
            "duration": 15,
            "aspect_ratio": aspect_ratio or "16:9",
            "resolution": "720p",
            "size": _seedance_size(aspect_ratio),
            "async": True,
        }

        if generation_mode == "首帧生成视频":
            if first_frame is None:
                raise RespectAPIError("首帧生成视频需要提供 first_frame")
            body["start_image_url"] = _upload_reference(cfg, first_frame, 1)
        elif generation_mode == "首尾帧生成视频":
            if first_frame is None or last_frame is None:
                raise RespectAPIError("首尾帧生成视频需要同时提供 first_frame 和 last_frame")
            body["start_image_url"] = _upload_reference(cfg, first_frame, 1)
            body["end_image_url"] = _upload_reference(cfg, last_frame, 2)
        elif generation_mode == "多参考图生成视频":
            refs = [ref_image_1, ref_image_2, ref_image_3, ref_image_4]
            urls = _upload_all(cfg, refs)[:4]
            if not urls:
                raise RespectAPIError("多参考图生成视频需要至少一张参考图（最多 4 张）")
            if len(urls) == 1:
                body["image_url"] = urls[0]
            else:
                body["image_urls"] = urls
            prompt = _tag_prompt(prompt, generation_mode, len(urls))
            body["prompt"] = prompt
        # 文生视频：不带图（该系列可能要求至少 1 张图，视上游而定）

        url, task_id = _seedance_submit_poll(cfg, body, int(poll_interval), int(poll_timeout))
        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="seedance", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] Seedance 视频下载失败: {exc}")
        return (url, local, task_id or "")


# ---------------------------------------------------------------------------
# 共用收尾（/v1/videos 系）
# ---------------------------------------------------------------------------


def _finalize_sd(cfg, direct, task_id, poll_interval, poll_timeout,
                 auto_download, prefix, save_dir, filename) -> tuple[str, str, str]:
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


NODE_CLASS_MAPPINGS = {
    "RespectSD2AllVideo": RespectSD2AllVideo,
    "RespectSeedance9Video": RespectSeedance9Video,
    "RespectSeedanceFourRefVideo": RespectSeedanceFourRefVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectSD2AllVideo": "Respect SD2.0 全系列视频",
    "RespectSeedance9Video": "Respect Seedance9 九图/稳定版视频",
    "RespectSeedanceFourRefVideo": "Respect Seedance 四参考图视频",
}
