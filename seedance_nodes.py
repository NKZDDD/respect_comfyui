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
    tensor_to_b64,
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
    """把参考图上传换公网 URL。默认发 {upload_base}/v1/uploads（字段 image），/v1/upload 兜底。"""
    data = _tensor_to_jpeg_bytes(tensor, max_side=1536, quality=90)
    if not data:
        raise RespectAPIError(f"参考图{index} 为空，无法上传")
    base = cfg.resolve_upload_base()
    last_err: Optional[Exception] = None
    for endpoint in ("/v1/uploads", "/v1/upload"):
        url = f"{base}{endpoint}"
        try:
            resp = api_request(
                cfg, "POST", url,
                files=[("image", (f"ref_{index}.jpg", data, "image/jpeg"))],
                retries=1, timeout=max(cfg.timeout, 300),
            )
        except RespectAPIError as exc:
            last_err = exc
            continue
        try:
            payload = resp.json()
        except Exception:
            last_err = RespectAPIError(f"上传返回非 JSON: {resp.text[:200]}")
            continue
        token = _extract_upload_token(payload)
        if token:
            return token
        last_err = RespectAPIError(f"上传未返回可用引用(url/name): {json.dumps(payload, ensure_ascii=False)[:300]}")
    raise last_err or RespectAPIError("参考图上传失败")


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


# ---------------------------------------------------------------------------
# grok-video 分支（新接口：单模型 grok-video + 公网图上传 + 分端点）
# ---------------------------------------------------------------------------


GROK3_MODELS = ["grok-imagine-video-1.5-fast", "grok-imagine-1.0-video", "grok-imagine-video-1.5-preview"]
GROK_VIDEO_ASPECTS = ["9:16", "16:9", "1:1", "2:3", "3:2"]
GROK_VIDEO_RES = ["720P", "480P"]
GROK_VIDEO_DURATIONS = ["6", "10", "15"]
GROK_VIDEO_MODES = ["文生视频", "图生视频"]


def _tag_image_prompt(prompt: str, n: int) -> str:
    p = prompt or ""
    if "@image" in p.lower() or n <= 0:
        return p
    tags = " ".join(f"@image{i + 1}" for i in range(n))
    return f"{p} {tags}".strip()


def _grok_video_submit_poll(cfg, endpoint: str, body: dict = None, files=None,
                            poll_interval: int = 5, poll_timeout: int = 1800) -> tuple[str, str]:
    """grok-video 专用：POST(JSON 或 multipart) 后按 status_url > {endpoint}/{task_id} 轮询。"""
    if files is not None:
        resp = api_request(cfg, "POST", endpoint, files=files, retries=2, timeout=max(cfg.timeout, 300))
    else:
        resp = api_request(cfg, "POST", endpoint, json_body=body, retries=2, timeout=max(cfg.timeout, 300))
    data = resp.json() if resp.content else {}
    direct = _async_extract_url(data)
    task_id = _sd2_extract_task_id(data)
    status_url = ""
    if isinstance(data, dict):
        status_url = data.get("status_url") or (data.get("data") or {}).get("status_url") or ""
    if direct:
        return direct, task_id
    if status_url:
        poll_path = status_url
    elif task_id:
        poll_path = f"{endpoint}/{task_id}"
    else:
        raise RespectAPIError(f"提交未返回 status_url / task_id / 视频URL: {json.dumps(data, ensure_ascii=False)[:400]}")

    start = time.time()
    last = ""
    while time.time() - start < poll_timeout:
        try:
            r = api_request(cfg, "GET", poll_path, retries=1, timeout=60)
        except RespectAPIError as exc:
            print(f"[Respect] grok-video 轮询错误，继续重试: {exc}")
            time.sleep(poll_interval)
            continue
        d = r.json() if r.content else {}
        u = _async_extract_url(d)
        status = _async_status(d)
        if status and status != last:
            print(f"[Respect] grok-video 任务 {task_id or poll_path} 状态: {status}")
            last = status
        if status in _ASYNC_FAIL:
            raise RespectAPIError(f"任务失败: {json.dumps(d, ensure_ascii=False)[:400]}")
        if u and (not status or status in _ASYNC_DONE):
            return u, task_id
        time.sleep(poll_interval)
    raise RespectAPIError(f"任务超时: {task_id or poll_path}")


class RespectGrokVideoNew:
    """Grok 视频（统一三模型接口，走 `/v1/videos` + `/v1/videos/{id}` 轮询）。

    - grok-imagine-video-1.5-fast / grok-imagine-1.0-video：文生或图生，seconds 只支持 6/10
    - grok-imagine-video-1.5-preview：必须图生，seconds 1~15
    图生视频时参考图（first_frame，通常接 image2 出的图）直接以 multipart `input_reference[]` 上传，
    无需公网图床。auto_download 会把结果下载到本地并输出 local_path（预览请连 local_path）。
    """

    DESCRIPTION = (
        "Grok 视频三模型统一接口。图生视频接 first_frame（1.0-video / 1.5-fast 可再接 ref_image_2..4 传多张，"
        "重复 input_reference[] 上传；1.5-preview 只用 1 张）。seconds：1.0/1.5-fast 用 6/10。预览/后续用 local_path。"
    )

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "连 Respect API 设置"}),
                "model": (GROK3_MODELS, {"default": "grok-imagine-video-1.5-fast", "tooltip": "1.5-preview 必须图生；1.0/1.5-fast 时长只支持 6/10"}),
                "prompt": ("STRING", {"default": "", "multiline": True, "tooltip": "视频描述（英文更稳）"}),
                "generation_mode": (GROK_VIDEO_MODES, {"default": "文生视频", "tooltip": "图生视频需接 first_frame 参考图"}),
                "duration": ("INT", {"default": 10, "min": 1, "max": 15, "tooltip": "秒数：1.5-preview 支持 1~15；1.0-video/1.5-fast 仅 6/10（非法会就近取）"}),
                "aspect_ratio": (GROK_VIDEO_ASPECTS, {"default": "16:9", "tooltip": "画幅比例"}),
                "resolution": (GROK_VIDEO_RES, {"default": "720P", "tooltip": "清晰度"}),
                "poll_interval": ("INT", {"default": 5, "min": 2, "max": 60, "tooltip": "轮询间隔（秒）"}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200, "tooltip": "最长等待（秒）"}),
                "auto_download": ("BOOLEAN", {"default": True, "tooltip": "完成后把视频下载到本地并输出 local_path"}),
            },
            "optional": {
                "first_frame": ("IMAGE", {"tooltip": "参考图1（首帧），multipart input_reference[] 上传"}),
                "ref_image_2": ("IMAGE", {"tooltip": "参考图2（仅 1.0-video / 1.5-fast 支持多张；1.5-preview 只用第1张）"}),
                "ref_image_3": ("IMAGE", {"tooltip": "参考图3（仅 1.0-video / 1.5-fast）"}),
                "ref_image_4": ("IMAGE", {"tooltip": "参考图4（仅 1.0-video / 1.5-fast）"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了覆盖上方模型", "tooltip": "手填任意 grok 视频模型名"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect", "tooltip": "本地保存目录"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳", "tooltip": "本地保存文件名"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("在线视频 URL", "下载到本地的路径（预览/后续用这个）", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, generation_mode, duration, aspect_ratio, resolution,
                 poll_interval, poll_timeout, auto_download,
                 first_frame=None, ref_image_2=None, ref_image_3=None, ref_image_4=None,
                 custom_model="", save_dir="", filename=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        sec_i = int(duration)
        if "1.5-preview" not in model and sec_i not in (6, 10):
            sec_i = 6 if sec_i < 8 else 10  # 1.0-video / 1.5-fast 仅支持 6/10，就近取
        sec = str(sec_i)
        res_name = "720p" if str(resolution).upper().startswith("720") else "480p"
        res_hd = "HD" if res_name == "720p" else "SD"
        need_image = (generation_mode == "图生视频") or ("1.5-preview" in model)

        if need_image:
            imgs = [t for t in (first_frame, ref_image_2, ref_image_3, ref_image_4)
                    if t is not None and (not hasattr(t, "numel") or t.numel() > 0)]
            if not imgs:
                raise RespectAPIError("图生视频 / 1.5-preview 需要提供参考图（first_frame）")
            if "1.5-preview" in model:
                imgs = imgs[:1]  # 1.5-preview 只支持 1 张
            files = [
                ("model", (None, model)),
                ("prompt", (None, prompt)),
                ("seconds", (None, sec)),
                ("size", (None, aspect_ratio)),
                ("resolution_name", (None, res_name)),
            ]
            for i, t in enumerate(imgs, start=1):
                jpeg = _tensor_to_jpeg_bytes(t, max_side=1536, quality=90)
                if jpeg:
                    files.append(("input_reference[]", (f"ref_{i}.jpg", jpeg, "image/jpeg")))
            print(f"[Respect] grok-video(坤鸡) {model} 图生: {len(imgs)} 张参考图")
            url, task_id = _grok_video_submit_poll(cfg, "/v1/videos", files=files,
                                                   poll_interval=int(poll_interval), poll_timeout=int(poll_timeout))
        else:
            body = {"model": model, "prompt": prompt, "seconds": sec,
                    "aspect_ratio": aspect_ratio, "resolution": res_hd}
            url, task_id = _grok_video_submit_poll(cfg, "/v1/videos", body=body,
                                                   poll_interval=int(poll_interval), poll_timeout=int(poll_timeout))

        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="grokvideo", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] grok-video 下载失败: {exc}")
        return (url, local, task_id or "")


# ---------------------------------------------------------------------------
# Grok-Video 小裴分支（单模型 grok-video，公网图上传，多参考走 /v1/video/generations）
# ---------------------------------------------------------------------------


GROK_XP_ASPECTS = ["16:9", "9:16", "3:2"]
GROK_XP_DURATIONS = ["6", "10", "15"]
GROK_XP_MODES = ["文生视频", "首帧生成视频", "多参考图生成视频"]


class RespectGrokVideoXiaopei:
    """Grok-Video 小裴分支（aicopy 后端，单模型 grok-video，参考图先上传换公网 URL）。

    - 文生视频 → POST /v1/videos：seconds(字符串)+size:720p+aspect_ratio
    - 首帧生成视频 → POST /v1/videos：input_reference(公网URL)+seconds+size（不传 aspect_ratio）
    - 多参考图(2–5张) → POST /v1/video/generations：images:[urls]+duration(数字)+size+aspect_ratio
    时长：文生/首帧 6/10/15；多参考 6/10（选 15 自动降 10）。分辨率固定 720p。
    """

    DESCRIPTION = (
        "小裴 grok-video 分支（aicopy 后端）。参考图走『公网URL上传』；多参考图(2-5张)用 "
        "/v1/video/generations。与坤鸡分支不通用——用哪个看你的 API key 对应哪个后端。"
    )

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "连 Respect API 设置（aicopy 后端）"}),
                "model": ("STRING", {"default": "grok-video", "multiline": False, "tooltip": "小裴 grok-video 模型名"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "generation_mode": (GROK_XP_MODES, {"default": "文生视频", "tooltip": "首帧/多参考图需接参考图"}),
                "duration": (GROK_XP_DURATIONS, {"default": "10", "tooltip": "秒数；多参考图仅 6/10"}),
                "aspect_ratio": (GROK_XP_ASPECTS, {"default": "16:9"}),
                "poll_interval": ("INT", {"default": 5, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "first_frame": ("IMAGE", {"tooltip": "首帧模式的参考图"}),
                "ref_image_1": ("IMAGE",),
                "ref_image_2": ("IMAGE",),
                "ref_image_3": ("IMAGE",),
                "ref_image_4": ("IMAGE",),
                "ref_image_5": ("IMAGE",),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("在线视频 URL", "下载到本地的路径（预览/后续用这个）", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, generation_mode, duration, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 first_frame=None, ref_image_1=None, ref_image_2=None, ref_image_3=None,
                 ref_image_4=None, ref_image_5=None, save_dir="", filename=""):
        cfg = ensure_config(api_config)
        model = (model or "grok-video").strip() or "grok-video"
        sec = int(duration)

        if generation_mode == "文生视频":
            endpoint = "/v1/videos"
            body = {"model": model, "prompt": prompt, "seconds": str(sec), "size": "720p", "aspect_ratio": aspect_ratio}
        elif generation_mode == "首帧生成视频":
            if first_frame is None:
                raise RespectAPIError("首帧生成视频需要提供 first_frame")
            ref_url = _upload_reference(cfg, first_frame, 1)
            endpoint = "/v1/videos"
            body = {"model": model, "prompt": prompt, "input_reference": ref_url, "seconds": str(sec), "size": "720p"}
        else:  # 多参考图生成视频
            urls = _upload_all(cfg, [ref_image_1, ref_image_2, ref_image_3, ref_image_4, ref_image_5])[:5]
            if len(urls) < 2:
                raise RespectAPIError("多参考图生成视频需要 2–5 张参考图")
            if sec == 15:
                sec = 10  # 多参考仅支持 6/10
            endpoint = "/v1/video/generations"
            body = {"model": model, "prompt": _tag_image_prompt(prompt, len(urls)),
                    "images": urls, "duration": sec, "size": "720p", "aspect_ratio": aspect_ratio}

        url, task_id = _grok_video_submit_poll(cfg, endpoint, body=body,
                                               poll_interval=int(poll_interval), poll_timeout=int(poll_timeout))
        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="grokvideo_xp", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] grok-video(小裴) 下载失败: {exc}")
        return (url, local, task_id or "")


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


# ---------------------------------------------------------------------------
# HappyHorse 快乐马 2.0 —— happyhorse
# ---------------------------------------------------------------------------


HAPPYHORSE_VARIANTS = [
    "happyhorse-1.1-t2v-720p", "happyhorse-1.1-t2v-1080p",
    "happyhorse-1.1-i2v-720p", "happyhorse-1.1-i2v-1080p",
    "happyhorse-1.1-r2v-720p", "happyhorse-1.1-r2v-1080p",
    "happyhorse-1.0-t2v-720p", "happyhorse-1.0-t2v-1080p",
    "happyhorse-1.0-i2v-720p", "happyhorse-1.0-i2v-1080p",
    "happyhorse-1.0-r2v-720p", "happyhorse-1.0-r2v-1080p",
]
HAPPYHORSE_ASPECTS = ["16:9", "9:16", "1:1", "4:3", "3:4", "4:5", "5:4", "9:21", "21:9"]


def _happyhorse_mode(variant: str) -> str:
    v = str(variant or "")
    if "-i2v-" in v:
        return "首帧生成视频"
    if "-r2v-" in v:
        return "多参考图生成视频"
    return "文生视频"


class RespectHappyHorseVideo:
    """HappyHorse 快乐马 2.0（`POST /v1/videos`，参考图先上传换公网 URL）。

    模型变体名已编码 版本/模式/清晰度：t2v=文生、i2v=首帧、r2v=多参考(≤9)；-1080p/-720p 定清晰度。
    生成模式由变体自动推断。节点最多接 7 张参考图（上游支持 9）。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "model_variant": (HAPPYHORSE_VARIANTS, {"default": "happyhorse-1.1-t2v-720p"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": ("INT", {"default": 5, "min": 4, "max": 15}),
                "aspect_ratio": (HAPPYHORSE_ASPECTS, {"default": "16:9"}),
                "poll_interval": ("INT", {"default": 5, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "first_frame": ("IMAGE",),
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

    def generate(self, api_config, model_variant, prompt, duration, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 first_frame=None, ref_image_1=None, ref_image_2=None, ref_image_3=None,
                 ref_image_4=None, ref_image_5=None, ref_image_6=None, ref_image_7=None,
                 custom_model="", save_dir="", filename=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model_variant
        mode = _happyhorse_mode(model_variant)
        resolution = "1080P" if str(model).endswith("-1080p") else "720P"

        refs = [ref_image_1, ref_image_2, ref_image_3, ref_image_4, ref_image_5, ref_image_6, ref_image_7]
        tensors = _collect_mode_tensors(mode, first_frame, None, refs)
        image_urls = _upload_all(cfg, tensors)[:9]

        parameters: dict = {"duration": int(duration), "resolution": resolution, "watermark": False}
        if mode != "首帧生成视频":
            parameters["ratio"] = aspect_ratio or "16:9"
        body: dict = {"model": model, "prompt": prompt, "parameters": parameters}
        if mode == "首帧生成视频":
            if not image_urls:
                raise RespectAPIError("HappyHorse 图生视频（i2v）必须提供首帧图片")
            body["image_url"] = image_urls[0]
        elif mode == "多参考图生成视频":
            if not image_urls:
                raise RespectAPIError("HappyHorse 参考生视频（r2v）必须提供至少一张参考图")
            body["reference_images"] = image_urls[:9]

        direct, task_id = _submit_async_video(cfg, body, timeout=300)
        return _finalize_sd(cfg, direct, task_id, poll_interval, poll_timeout,
                            auto_download, "happyhorse", save_dir, filename)


# ---------------------------------------------------------------------------
# 可灵+快乐马+omni 低价渠道（按次）—— low_cost_multi
# ---------------------------------------------------------------------------


LOW_COST_VARIANTS = ["kling", "happy-horse-1.1", "gemini-omni"]
LOW_COST_MODES = {
    "kling": ["文生视频", "首帧生成视频", "首尾帧生成视频"],
    "happy-horse-1.1": ["文生视频", "多参考图生成视频"],
    "gemini-omni": ["文生视频", "首帧生成视频"],
}
LOW_COST_LIMIT = {"kling": 2, "happy-horse-1.1": 9, "gemini-omni": 1}
LOW_COST_ASPECTS = ["16:9", "9:16", "1:1"]
LOW_COST_ALL_MODES = ["文生视频", "首帧生成视频", "首尾帧生成视频", "多参考图生成视频"]


def _low_cost_size(aspect_ratio: str) -> str:
    return {"16:9": "1280x720", "9:16": "720x1280", "1:1": "720x720"}.get(str(aspect_ratio or "").strip(), "1280x720")


def _append_image_placeholders(prompt: str, n: int) -> str:
    result = str(prompt or "").strip()
    for i in range(1, int(n or 0) + 1):
        if not re.search(rf"@Image\s*{i}(?!\d)", result, re.IGNORECASE):
            result = f"{result} @Image{i}".strip()
    return result


class RespectLowCostMultiVideo:
    """可灵+快乐马+omni 低价渠道（按次）。`POST /v1/videos`，固定 15 秒，参考图先上传换公网 URL。

    - kling：文生/首帧/首尾帧，≤2 图
    - happy-horse-1.1：文生/多参考，≤9 图
    - gemini-omni：文生/首帧，≤1 图
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "model_variant": (LOW_COST_VARIANTS, {"default": "kling"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "generation_mode": (LOW_COST_ALL_MODES, {"default": "文生视频"}),
                "aspect_ratio": (LOW_COST_ASPECTS, {"default": "16:9"}),
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
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model_variant, prompt, generation_mode, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 first_frame=None, last_frame=None,
                 ref_image_1=None, ref_image_2=None, ref_image_3=None, ref_image_4=None,
                 ref_image_5=None, ref_image_6=None, ref_image_7=None,
                 save_dir="", filename=""):
        cfg = ensure_config(api_config)
        allowed = LOW_COST_MODES.get(model_variant, LOW_COST_ALL_MODES)
        if generation_mode not in allowed:
            raise RespectAPIError(f"{model_variant} 仅支持这些模式: {', '.join(allowed)}")

        refs = [ref_image_1, ref_image_2, ref_image_3, ref_image_4, ref_image_5, ref_image_6, ref_image_7]
        tensors = _collect_mode_tensors(generation_mode, first_frame, last_frame, refs)
        image_urls = _upload_all(cfg, tensors)
        limit = LOW_COST_LIMIT.get(model_variant, 9)
        if len(image_urls) > limit:
            raise RespectAPIError(f"{model_variant} 最多支持 {limit} 张参考图")

        body: dict = {
            "model": model_variant,
            "prompt": _append_image_placeholders(prompt, len(image_urls)),
            "duration": 15,
            "size": _low_cost_size(aspect_ratio),
            "audio": True,
        }
        if image_urls:
            body["image_refs"] = image_urls

        direct, task_id = _submit_async_video(cfg, body, timeout=300)
        return _finalize_sd(cfg, direct, task_id, poll_interval, poll_timeout,
                            auto_download, "lowcost", save_dir, filename)


# ---------------------------------------------------------------------------
# 通用异步视频（统一 /v1/videos：image_url + extra_images，URL/base64，不用图床）
# ---------------------------------------------------------------------------


UNI_VIDEO_MODELS = ["seedance-2-0", "seedance-2-0-fast", "video1-pro-720p", "grok-imagine-video-1.5-fast"]
UNI_VIDEO_ASPECTS = ["16:9", "9:16", "1:1", "21:9", "3:4", "4:3", "2:3", "3:2"]


def _uni_ref(tensor, url_text: str = "") -> str:
    """优先用填的公网 URL；否则把 tensor 转 base64 data URL（内联，不用图床）。"""
    if (url_text or "").strip():
        return url_text.strip()
    if tensor is not None and (not hasattr(tensor, "numel") or tensor.numel() > 0):
        b = tensor_to_b64(tensor[:1], fmt="JPEG", quality=90, max_side=1536)
        return b[0] if b else ""
    return ""


def _uni_lines(s: str) -> list[str]:
    return [ln.strip() for ln in (s or "").splitlines() if ln.strip()]


class RespectSeedanceUniversal:
    """通用异步视频（统一 `/v1/videos` 提交 + `/v1/videos/{id}` 轮询）。

    适配「章鱼哥式」通用网关：seedance-2-0 / -fast、video1-pro-720p、grok-imagine-video-1.5-fast 等。
    参考图走 `image_url` + `extra_images`：优先用你填的公网 URL，否则把接入的 IMAGE 转 base64 内联（**不经图床，不会 401**）。
    """

    DESCRIPTION = ("通用异步视频 /v1/videos（seedance-2-0 等）。参考图 image_url+extra_images：填了 URL 用 URL，"
                   "否则接入的 IMAGE 自动转 base64 内联，不用图床。duration 4-15。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "连 Respect API 设置（base_url 填该通用网关）"}),
                "model": (UNI_VIDEO_MODELS, {"default": "seedance-2-0"}),
                "prompt": ("STRING", {"default": "", "multiline": True, "tooltip": "≤2500 字；多参考用 @Image1/@Image2 引用"}),
                "duration": ("INT", {"default": 8, "min": 4, "max": 15}),
                "aspect_ratio": (UNI_VIDEO_ASPECTS, {"default": "16:9"}),
                "poll_interval": ("INT", {"default": 8, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "first_frame": ("IMAGE", {"tooltip": "主参考图/首帧 → image_url(@Image1)；转 base64 内联"}),
                "ref_image_2": ("IMAGE", {"tooltip": "追加参考图 → extra_images(@Image2)"}),
                "ref_image_3": ("IMAGE",),
                "ref_image_4": ("IMAGE",),
                "image_url": ("STRING", {"default": "", "multiline": False, "placeholder": "可选公网URL，填了覆盖 first_frame"}),
                "extra_image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "追加参考图公网URL，每行一个（≤9）"}),
                "extra_video_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考视频URL，每行一个（≤3）"}),
                "extra_audio_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考音频URL，每行一个（≤3）"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了覆盖上方模型"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("在线视频 URL", "下载到本地的路径（预览/后续用这个）", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, duration, aspect_ratio, poll_interval, poll_timeout, auto_download,
                 first_frame=None, ref_image_2=None, ref_image_3=None, ref_image_4=None,
                 image_url="", extra_image_urls="", extra_video_urls="", extra_audio_urls="",
                 custom_model="", save_dir="", filename=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        body: dict = {"model": model, "prompt": prompt, "duration": int(duration), "aspect_ratio": aspect_ratio}

        main = _uni_ref(first_frame, image_url)
        if main:
            body["image_url"] = main

        extras: list[str] = _uni_lines(extra_image_urls)
        for t in (ref_image_2, ref_image_3, ref_image_4):
            r = _uni_ref(t)
            if r:
                extras.append(r)
        if extras:
            body["extra_images"] = extras[:9]

        vids = _uni_lines(extra_video_urls)[:3]
        if vids:
            body["extra_videos"] = vids
        auds = _uni_lines(extra_audio_urls)[:3]
        if auds:
            body["extra_audios"] = auds

        direct, task_id = _submit_async_video(cfg, body, timeout=300)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="uni_video", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] 通用视频下载失败: {exc}")
        return (url, local, task_id or "")


NODE_CLASS_MAPPINGS = {
    "RespectSD2AllVideo": RespectSD2AllVideo,
    "RespectSeedance9Video": RespectSeedance9Video,
    "RespectSeedanceFourRefVideo": RespectSeedanceFourRefVideo,
    "RespectSeedanceUniversal": RespectSeedanceUniversal,
    "RespectGrokVideoNew": RespectGrokVideoNew,
    "RespectGrokVideoXiaopei": RespectGrokVideoXiaopei,
    "RespectHappyHorseVideo": RespectHappyHorseVideo,
    "RespectLowCostMultiVideo": RespectLowCostMultiVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectSD2AllVideo": "Respect SD2.0 全系列视频",
    "RespectSeedance9Video": "Respect Seedance9 九图/稳定版视频",
    "RespectSeedanceFourRefVideo": "Respect Seedance 四参考图视频",
    "RespectSeedanceUniversal": "Respect Seedance 通用异步视频",
    "RespectGrokVideoNew": "Respect Grok-Video 视频（坤鸡分支）",
    "RespectGrokVideoXiaopei": "Respect Grok-Video 视频（小裴分支）",
    "RespectHappyHorseVideo": "Respect HappyHorse 快乐马视频",
    "RespectLowCostMultiVideo": "Respect 低价多渠道视频（可灵/快乐马/omni）",
}
