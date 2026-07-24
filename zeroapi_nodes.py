"""Respect ComfyUI 扩展 - 零视工坊(zeroapi.ai-ren.cn) 专用节点。

零视工坊全部走 `POST /v1/videos` 提交 + `GET /v1/videos/{id}` 轮询（完成时 `url` = 无水印视频）。
在 Respect API 设置里把 base_url 填 `https://zeroapi.ai-ren.cn`，再用这些节点。

各能力 body 字段不同：
- Sora2/VEO 创建视频：{prompt, model, size, input_reference(多图用|分隔), remix_id}
- 图生视频：{model, prompt, image / images[], duration, size, stream}
参考图优先用公网 URL（接对象存储上传），否则把接入的 IMAGE 转 base64 内联。
"""

from __future__ import annotations

from typing import Any, Optional

import torch

from .utils import RespectAPIError, download_to_output, ensure_config, tensor_to_b64
from .video_nodes import _async_poll, _submit_async_video

CATEGORY = "Respect"


def _ref_b64_or_url(tensor, url: str = "") -> str:
    """优先用填的公网 URL；否则把 tensor 转 base64 data URL。"""
    if (url or "").strip():
        return url.strip()
    if tensor is not None and (not hasattr(tensor, "numel") or tensor.numel() > 0):
        b = tensor_to_b64(tensor[:1], fmt="JPEG", quality=90, max_side=1536)
        return b[0] if b else ""
    return ""


def _collect_refs(image_tensors, url_texts) -> list[str]:
    """图片 tensor(转base64) 在前、公网 URL 在后，保序去空。"""
    refs: list[str] = []
    for t in image_tensors:
        r = _ref_b64_or_url(t)
        if r:
            refs.append(r)
    for u in url_texts:
        if isinstance(u, str) and u.strip():
            refs.append(u.strip())
    return refs


ZERO_SIZES = ["1280x720", "1920x1080", "720x1280", "1080x1920", "1024x1024", "1280x960", "960x1280", "832x480", "480x832"]


# ---------------------------------------------------------------------------
# 零视工坊 Sora2 / VEO 创建视频
# ---------------------------------------------------------------------------

ZERO_SORA_MODELS = ["veo_3_1-fast", "veo_3_1-fast-fl", "sora-2", "sora-2-pro"]


class RespectZeroSoraVeo:
    """零视工坊 Sora2 / VEO 创建视频。`POST /v1/videos` 提交 + 轮询。

    body：{prompt, model, size, input_reference(多图用|分隔), remix_id}。
    参考图/首尾帧：图片槽转 base64、URL 槽直用，合并后用 | 分隔填 input_reference。
    """

    DESCRIPTION = ("零视工坊 Sora2/VEO(base_url=zeroapi.ai-ren.cn)。model=veo_3_1-fast/-fl/sora-2，size=WxH，"
                   "首尾帧/参考图→input_reference(|分隔)，remix_id 可把 veo 续到15秒。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://zeroapi.ai-ren.cn"}),
                "model": (ZERO_SORA_MODELS, {"default": "veo_3_1-fast"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "size": (ZERO_SIZES, {"default": "1280x720", "tooltip": "输出尺寸 宽x高"}),
                "poll_interval": ("INT", {"default": 8, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "first_frame": ("IMAGE", {"tooltip": "首帧 → input_reference 第1个"}),
                "last_frame": ("IMAGE", {"tooltip": "尾帧 → input_reference 第2个"}),
                "ref_image_3": ("IMAGE",),
                "ref_image_4": ("IMAGE",),
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "参考图公网URL(接对象存储上传)"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "remix_id": ("STRING", {"default": "", "multiline": False, "placeholder": "可选：已有 veo 任务ID，续到15秒"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了优先使用"}),
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，自定义 宽x高，覆盖上面"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, size, poll_interval, poll_timeout, auto_download,
                 first_frame=None, last_frame=None, ref_image_3=None, ref_image_4=None,
                 ref_url_1="", ref_url_2="", ref_url_3="", ref_url_4="",
                 remix_id="", custom_model="", custom_size="", save_dir="", filename=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        size = (custom_size or "").strip() or size

        refs = _collect_refs([first_frame, last_frame, ref_image_3, ref_image_4],
                             [ref_url_1, ref_url_2, ref_url_3, ref_url_4])
        body: dict = {"model": model, "prompt": prompt, "size": size}
        if refs:
            body["input_reference"] = "|".join(refs)
        if (remix_id or "").strip():
            body["remix_id"] = remix_id.strip()

        direct, task_id = _submit_async_video(cfg, body, timeout=300)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="zero_soraveo", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] 零视工坊 Sora/VEO 下载失败: {exc}")
        return (url, local, task_id or "")


# ---------------------------------------------------------------------------
# 零视工坊 图生视频 (vad3 / seedance_2 / omni_flash / grok-1.5)
# ---------------------------------------------------------------------------

ZERO_I2V_MODELS = ["seedance_2_fast_480p", "vad3", "omni_flash", "grok-1.5"]


class RespectZeroImg2Video:
    """零视工坊 图生视频。`POST /v1/videos` 提交 + 轮询。

    body：{model, prompt, image / images[], duration, size, stream}。
    单张 → image；多张 → images[]。参考图优先公网 URL，否则 IMAGE 转 base64。
    """

    DESCRIPTION = ("零视工坊 图生视频(base_url=zeroapi.ai-ren.cn)。model=seedance_2_fast_480p/vad3/omni_flash/grok-1.5，"
                   "duration 4-20(seedance 4-15，其它多为10/20)，size=WxH，单图 image/多图 images[]。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://zeroapi.ai-ren.cn"}),
                "model": (ZERO_I2V_MODELS, {"default": "seedance_2_fast_480p"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": ("INT", {"default": 10, "min": 4, "max": 20, "tooltip": "秒数；seedance 4-15，其它常见 10/20"}),
                "size": (ZERO_SIZES, {"default": "1280x720"}),
                "poll_interval": ("INT", {"default": 8, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "first_frame": ("IMAGE", {"tooltip": "首帧/参考图（单张→image，多张→images[]）"}),
                "ref_image_2": ("IMAGE",),
                "ref_image_3": ("IMAGE",),
                "ref_image_4": ("IMAGE",),
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "参考图公网URL(接对象存储上传)"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了优先使用"}),
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，自定义 宽x高"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, duration, size, poll_interval, poll_timeout, auto_download,
                 first_frame=None, ref_image_2=None, ref_image_3=None, ref_image_4=None,
                 ref_url_1="", ref_url_2="", ref_url_3="", ref_url_4="",
                 custom_model="", custom_size="", save_dir="", filename=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        size = (custom_size or "").strip() or size

        imgs = _collect_refs([first_frame, ref_image_2, ref_image_3, ref_image_4],
                             [ref_url_1, ref_url_2, ref_url_3, ref_url_4])
        body: dict = {"model": model, "prompt": prompt, "size": size, "duration": int(duration), "stream": False}
        if len(imgs) == 1:
            body["image"] = imgs[0]
        elif len(imgs) > 1:
            body["images"] = imgs

        direct, task_id = _submit_async_video(cfg, body, timeout=300)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="zero_i2v", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] 零视工坊 图生视频 下载失败: {exc}")
        return (url, local, task_id or "")


NODE_CLASS_MAPPINGS = {
    "RespectZeroSoraVeo": RespectZeroSoraVeo,
    "RespectZeroImg2Video": RespectZeroImg2Video,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectZeroSoraVeo": "Respect 零视工坊 Sora2/VEO 视频",
    "RespectZeroImg2Video": "Respect 零视工坊 图生视频",
}
