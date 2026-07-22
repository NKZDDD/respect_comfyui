"""Respect ComfyUI 扩展 - 章鱼哥 API（统一异步）节点。

章鱼哥所有生成（图片/视频）都走同一套异步：
- 创建：POST /v1/videos  {model, prompt, aspect_ratio 或 size, images:[base64/URL]}
- 查询：GET  /v1/videos/{task_id}  → status: queued→processing→completed/failed，完成后取 url / video_url

模型：
- 图片：gpt-image-2 / -2K / -4K、nano_banana_2、nano_banana_pro-1K/-2K/-4K
- 视频：sora-2-12s、omni_flash-10s、veo_3_1-fast/-fl/-hd/-4K/-lite、veo_3_1
参考图用 images[] 传 base64 data URL（图片≤8 张，omni≤7）。base_url 填章鱼哥网关。
"""

from __future__ import annotations

import json
from typing import Any, Optional

import torch

from .utils import (
    RespectAPIError,
    api_request,
    ensure_config,
    resolve_image_to_tensor,
    tensor_to_b64,
    tensors_concat,
    download_to_output,
)
from .video_nodes import _submit_async_video, _async_poll

CATEGORY = "Respect/章鱼哥"

OCTOPUS_IMAGE_MODELS = [
    "gpt-image-2", "gpt-image-2-2K", "gpt-image-2-4K",
    "nano_banana_2", "nano_banana_pro-1K", "nano_banana_pro-2K", "nano_banana_pro-4K",
]
OCTOPUS_IMAGE_ASPECTS = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"]
OCTOPUS_VIDEO_MODELS = [
    "sora-2-12s", "omni_flash-10s",
    "veo_3_1-fast", "veo_3_1-fast-fl", "veo_3_1-fast-hd", "veo_3_1-fast-4K", "veo_3_1-lite", "veo_3_1",
]
OCTOPUS_VIDEO_SIZES = ["1280x720", "720x1280", "1920x1080", "1080x1920", "1024x1024"]


def _octopus_image_refs(images: list[Optional[torch.Tensor]], max_side: int = 1536) -> list[str]:
    """多张 IMAGE -> base64 data URL 列表（章鱼哥 images[] 用）。"""
    out: list[str] = []
    for img in images:
        if img is None or (hasattr(img, "numel") and img.numel() == 0):
            continue
        b64 = tensor_to_b64(img[:1], fmt="JPEG", quality=90, max_side=max_side)
        if b64:
            out.append(b64[0])
    return out


# ---------------------------------------------------------------------------
# ① 章鱼哥 异步图片
# ---------------------------------------------------------------------------


class RespectOctopusImage:
    """章鱼哥 异步图片（POST /v1/videos 创建 + 轮询）。返回 IMAGE。

    - 有参考图（image_1..4）→ 图生图（images[] base64，最多 8 张）
    - `size` 填了用 size（如 1456x816），否则用 `aspect_ratio`（auto=自动）
    """

    DESCRIPTION = "章鱼哥异步图片：POST /v1/videos 提交→轮询→取 url→下载成 IMAGE。gpt-image-2 / nano_banana 系列。"

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "连 Respect API 设置（base_url 填章鱼哥网关）"}),
                "model": (OCTOPUS_IMAGE_MODELS, {"default": "gpt-image-2"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "aspect_ratio": (OCTOPUS_IMAGE_ASPECTS, {"default": "auto", "tooltip": "size 为空时用它；auto=自动"}),
                "poll_interval": ("INT", {"default": 4, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 600, "min": 30, "max": 3600}),
            },
            "optional": {
                "size": ("STRING", {"default": "", "multiline": False, "placeholder": "如 1456x816，填了覆盖 aspect_ratio", "tooltip": "像素尺寸，和 aspect_ratio 二选一"}),
                "image_1": ("IMAGE",),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了覆盖上方模型"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "url", "task_id")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, aspect_ratio, poll_interval, poll_timeout,
                 size="", image_1=None, image_2=None, image_3=None, image_4=None, custom_model=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        body: dict = {"model": model, "prompt": prompt}
        size = (size or "").strip()
        if size:
            body["size"] = size
        elif aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        refs = _octopus_image_refs([image_1, image_2, image_3, image_4])
        if refs:
            body["images"] = refs

        direct, task_id = _submit_async_video(cfg, body, timeout=300)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        tensor = resolve_image_to_tensor(url, cfg)
        if tensor is None:
            raise RespectAPIError(f"结果图下载失败: {url}")
        return (tensors_concat([tensor]), url, task_id or "")


# ---------------------------------------------------------------------------
# ② 章鱼哥 异步视频
# ---------------------------------------------------------------------------


class RespectOctopusVideo:
    """章鱼哥 异步视频（POST /v1/videos 创建 + 轮询）。Sora / Omni / Veo。

    参考图用 images[] base64（omni≤7；veo 首尾帧 1~2 张、参考 ≤3）。`size` 决定横竖屏/分辨率。
    """

    DESCRIPTION = "章鱼哥异步视频：POST /v1/videos 提交→轮询→取 video_url→下载本地。sora-2 / omni_flash / veo_3_1 系列。"

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "连 Respect API 设置（base_url 填章鱼哥网关）"}),
                "model": (OCTOPUS_VIDEO_MODELS, {"default": "sora-2-12s"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "size": (OCTOPUS_VIDEO_SIZES, {"default": "1280x720", "tooltip": "横竖屏/分辨率；也可用 custom_size 自定义"}),
                "poll_interval": ("INT", {"default": 5, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "如 1920x1080，填了覆盖上方 size"}),
                "image_1": ("IMAGE",),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
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

    def generate(self, api_config, model, prompt, size, poll_interval, poll_timeout, auto_download,
                 custom_size="", image_1=None, image_2=None, image_3=None, image_4=None,
                 custom_model="", save_dir="", filename=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        size = (custom_size or "").strip() or size
        body: dict = {"model": model, "prompt": prompt, "size": size}
        refs = _octopus_image_refs([image_1, image_2, image_3, image_4])
        if refs:
            body["images"] = refs

        direct, task_id = _submit_async_video(cfg, body, timeout=300)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="octopus", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] 章鱼哥视频下载失败: {exc}")
        return (url, local, task_id or "")


# ---------------------------------------------------------------------------
# ③ 章鱼哥 任务查询（提交→稍后查询 的真·异步用）
# ---------------------------------------------------------------------------


class RespectOctopusQuery:
    """章鱼哥 任务查询：给 task_id，轮询 GET /v1/videos/{id} 直到完成，取结果 url。

    用于「先提交、稍后查询」的异步流；`download` 打开则把结果下载到本地。
    """

    DESCRIPTION = "章鱼哥任务查询：输入 task_id，轮询到 completed 取 url（可下载）。配合创建节点的 task_id 输出做异步。"

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "task_id": ("STRING", {"default": "", "multiline": False, "forceInput": True, "tooltip": "创建节点输出的 task_id"}),
                "poll_interval": ("INT", {"default": 5, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 30, "max": 7200}),
                "download": ("BOOLEAN", {"default": True, "tooltip": "把结果下载到本地并输出 local_path"}),
            },
            "optional": {
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("url", "local_path")
    FUNCTION = "query"
    CATEGORY = CATEGORY

    def query(self, api_config, task_id, poll_interval, poll_timeout, download,
              save_dir="", filename=""):
        cfg = ensure_config(api_config)
        task_id = (task_id or "").strip()
        if not task_id:
            raise RespectAPIError("task_id 为空")
        url = _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        local = ""
        if download and url:
            try:
                local = download_to_output(url, cfg, prefix="octopus", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] 章鱼哥结果下载失败: {exc}")
        return (url, local)


NODE_CLASS_MAPPINGS = {
    "RespectOctopusImage": RespectOctopusImage,
    "RespectOctopusVideo": RespectOctopusVideo,
    "RespectOctopusQuery": RespectOctopusQuery,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectOctopusImage": "Respect 章鱼哥 异步图片",
    "RespectOctopusVideo": "Respect 章鱼哥 异步视频",
    "RespectOctopusQuery": "Respect 章鱼哥 任务查询",
}
