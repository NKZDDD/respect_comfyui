"""Respect ComfyUI 扩展 - 图片生成 / 编辑节点。

封装 api.aicopy.top 的图片生成与编辑接口。
"""

from __future__ import annotations

import json
from typing import Any, Optional

import torch

from .utils import (
    ASPECT_RATIOS,
    RESOLUTIONS,
    RespectAPIError,
    api_request,
    aspect_to_x,
    ensure_config,
    extract_image_payloads,
    lookup_size,
    model_has_size,
    resolve_image_to_tensor,
    tensor_to_b64,
    tensors_concat,
)

CATEGORY = "Respect"


# ---------------------------------------------------------------------------
# 模型家族 -> model ID
# ---------------------------------------------------------------------------


IMAGE_FAMILIES = [
    "自定义/custom",
    "firefly-nano-banana",
    "firefly-nano-banana-pro",
    "firefly-nano-banana2",
    "gpt-image-1",
    "grok-imagine-1.0",
    "grok-imagine-1.0-edit",
]


def build_image_model_id(family: str, resolution: str, aspect: str, custom: str = "") -> str:
    family = (family or "").strip()
    if family in ("", "自定义/custom"):
        return (custom or "").strip()
    asp = aspect_to_x(aspect or "1:1")
    res = (resolution or "1k").lower()
    if family == "firefly-nano-banana":
        return f"firefly-nano-banana-{res}-{asp}"
    if family == "firefly-nano-banana-pro":
        return f"firefly-nano-banana-pro-{res}-{asp}"
    if family == "firefly-nano-banana2":
        return f"firefly-nano-banana2-{res}-{asp}"
    if family == "gpt-image-1":
        return f"firefly-gpt-image-{res}-{asp}"
    if family == "grok-imagine-1.0":
        return "grok-imagine-1.0"
    if family == "grok-imagine-1.0-edit":
        return "grok-imagine-1.0-edit"
    return family


# ---------------------------------------------------------------------------
# 通用解析
# ---------------------------------------------------------------------------


def _parse_response_to_tensor(data: Any, cfg, raw_text: str = "") -> torch.Tensor:
    payloads = extract_image_payloads(data)
    if not payloads and raw_text:
        payloads = extract_image_payloads(raw_text)
    if not payloads:
        snippet = json.dumps(data, ensure_ascii=False)[:600] if not isinstance(data, str) else data[:600]
        raise RespectAPIError(f"未能从响应中提取图片: {snippet}")
    tensors: list[torch.Tensor] = []
    for item in payloads:
        t = resolve_image_to_tensor(item, cfg)
        if t is not None:
            tensors.append(t)
    if not tensors:
        raise RespectAPIError("提取到的图片资源全部下载失败")
    return tensors_concat(tensors)


# ---------------------------------------------------------------------------
# 标准文生图 / 单图参考
# ---------------------------------------------------------------------------


class RespectImageGenerate:
    """标准图片生成节点。

    走 `/v1/images/generations`。如传入单张 reference_image，会附加到 `image` 字段
    （部分 Grok 风格通道使用，详见 §4.1）。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "model_family": (IMAGE_FAMILIES, {"default": "firefly-nano-banana"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "1:1"}),
                "resolution": (RESOLUTIONS, {"default": "1k"}),
                "n": ("INT", {"default": 1, "min": 1, "max": 4}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0x7fffffff}),
            },
            "optional": {
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "model_family=自定义/custom 时填"}),
                "reference_image": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(
        self,
        api_config: Any,
        model_family: str,
        prompt: str,
        aspect_ratio: str,
        resolution: str,
        n: int,
        seed: int,
        custom_model: str = "",
        reference_image: Optional[torch.Tensor] = None,
    ) -> tuple[torch.Tensor, str]:
        cfg = ensure_config(api_config)
        model = build_image_model_id(model_family, resolution, aspect_ratio, custom_model)
        if not model:
            raise RespectAPIError("请选择模型家族或填写 custom_model")

        body: dict = {
            "model": model,
            "prompt": prompt,
            "n": int(n),
        }
        if not model_has_size(model):
            body["size"] = lookup_size(resolution, aspect_ratio)

        if reference_image is not None and reference_image.numel() > 0:
            b64_list = tensor_to_b64(reference_image[:1], fmt="JPEG", quality=85, max_side=1024)
            if b64_list:
                raw = b64_list[0].split(",", 1)[1]
                body["image"] = raw

        resp = api_request(cfg, "POST", "/v1/images/generations", json_body=body, retries=3)
        data = resp.json()
        image_tensor = _parse_response_to_tensor(data, cfg)
        return (image_tensor, model)


# ---------------------------------------------------------------------------
# 多图参考 (/v1/responses)
# ---------------------------------------------------------------------------


class RespectImageMultiRef:
    """多图参考节点，走 `/v1/responses`，最多 7 张参考图。"""

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "model": ("STRING", {"default": "GPT本地版", "multiline": False}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "1:1"}),
                "resolution": (RESOLUTIONS, {"default": "1k"}),
            },
            "optional": {
                "image_1": ("IMAGE",),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "image_5": ("IMAGE",),
                "image_6": ("IMAGE",),
                "image_7": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(
        self,
        api_config: Any,
        model: str,
        prompt: str,
        aspect_ratio: str,
        resolution: str,
        **kwargs: Any,
    ) -> tuple[torch.Tensor, str]:
        cfg = ensure_config(api_config)

        content: list[dict] = []
        for i in range(1, 8):
            img = kwargs.get(f"image_{i}")
            if img is None or (hasattr(img, "numel") and img.numel() == 0):
                continue
            b64_list = tensor_to_b64(img[:1], fmt="JPEG", quality=85, max_side=1280)
            if not b64_list:
                continue
            content.append({"type": "input_image", "image_url": b64_list[0]})

        if prompt:
            content.append({"type": "input_text", "text": prompt})

        body = {
            "model": model,
            "input": [{"role": "user", "content": content}],
            "tools": [{"type": "image_generation", "size": lookup_size(resolution, aspect_ratio)}],
            "tool_choice": {"type": "image_generation"},
        }
        resp = api_request(cfg, "POST", "/v1/responses", json_body=body, retries=3)
        data = resp.json()
        image_tensor = _parse_response_to_tensor(data, cfg)
        return (image_tensor, model)


# ---------------------------------------------------------------------------
# GPT 本地版 / 应急通道 (优先 /responses，失败降级 /images/generations)
# ---------------------------------------------------------------------------


GPT_LOCAL_MODELS = [
    "GPT本地版", "GPT本地版1k", "GPT本地版2k", "GPT本地版4k",
    "GPT本地版-通道1", "GPT本地版1k-通道1", "GPT本地版2k-通道1", "GPT本地版4k-通道1",
    "GPT本地版-通道2", "GPT本地版1k-通道2", "GPT本地版2k-通道2", "GPT本地版4k-通道2",
    "GPT本地版-通道3", "GPT本地版1k-通道3", "GPT本地版2k-通道3", "GPT本地版4k-通道3",
    "gpt-image-2应急通道",
    "gpt-image-2应急通道01", "gpt-image-2应急通道02", "gpt-image-2应急通道03",
    "gpt-image-2应急通道04", "gpt-image-2应急通道05", "gpt-image-2应急通道06",
]


class RespectGPTLocalImage:
    """GPT 本地版 / 应急通道生图。

    `GPT本地版` 开头会优先调用 `/v1/responses`，失败后降级到 `/v1/images/generations`；
    其余应急模型直接走 `/v1/images/generations`。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "model": (GPT_LOCAL_MODELS, {"default": "GPT本地版"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "1:1"}),
                "resolution": (RESOLUTIONS, {"default": "1k"}),
                "n": ("INT", {"default": 1, "min": 1, "max": 4}),
            },
            "optional": {
                "reference_image": ("IMAGE",),
                "extra_image": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了优先使用，覆盖上方下拉"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(
        self,
        api_config: Any,
        model: str,
        prompt: str,
        aspect_ratio: str,
        resolution: str,
        n: int,
        reference_image: Optional[torch.Tensor] = None,
        extra_image: Optional[torch.Tensor] = None,
        custom_model: str = "",
    ) -> tuple[torch.Tensor, str]:
        cfg = ensure_config(api_config)
        custom_model = (custom_model or "").strip()
        if custom_model:
            model = custom_model
        size = lookup_size(resolution, aspect_ratio)
        use_responses = model.startswith("GPT本地版")

        if use_responses:
            try:
                return (self._call_responses(cfg, model, prompt, size, reference_image, extra_image), model)
            except RespectAPIError as exc:
                print(f"[Respect] /responses 调用失败，降级 /images/generations: {exc}")

        body: dict = {
            "model": model,
            "prompt": prompt,
            "n": int(n),
            "size": size,
            "response_format": "b64_json",
        }
        if reference_image is not None and reference_image.numel() > 0:
            b64_list = tensor_to_b64(reference_image[:1], fmt="JPEG", quality=85, max_side=1024)
            if b64_list:
                body["image"] = b64_list[0].split(",", 1)[1]
        resp = api_request(cfg, "POST", "/v1/images/generations", json_body=body, retries=3)
        return (_parse_response_to_tensor(resp.json(), cfg), model)

    def _call_responses(
        self,
        cfg,
        model: str,
        prompt: str,
        size: str,
        ref1: Optional[torch.Tensor],
        ref2: Optional[torch.Tensor],
    ) -> torch.Tensor:
        content: list[dict] = []
        for ref in (ref1, ref2):
            if ref is None or (hasattr(ref, "numel") and ref.numel() == 0):
                continue
            b64_list = tensor_to_b64(ref[:1], fmt="JPEG", quality=85, max_side=1280)
            if b64_list:
                content.append({"type": "input_image", "image_url": b64_list[0]})
        if prompt:
            content.append({"type": "input_text", "text": prompt})

        body = {
            "model": model,
            "input": [{"role": "user", "content": content}],
            "tools": [{"type": "image_generation", "size": size}],
            "tool_choice": {"type": "image_generation"},
        }
        resp = api_request(cfg, "POST", "/v1/responses", json_body=body, retries=2)
        return _parse_response_to_tensor(resp.json(), cfg)


# ---------------------------------------------------------------------------
# Chat completions 多模态兜底
# ---------------------------------------------------------------------------


class RespectImageChat:
    """通过 `/v1/chat/completions` 多模态调用并从文本中解析图片地址，
    适合 firefly-nano-banana 等通过 chat 流式返回的模型。"""

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "model": ("STRING", {"default": "firefly-nano-banana-1k-1x1"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "stream": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "image_1": ("IMAGE",),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "raw_text")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(
        self,
        api_config: Any,
        model: str,
        prompt: str,
        stream: bool,
        image_1: Optional[torch.Tensor] = None,
        image_2: Optional[torch.Tensor] = None,
        image_3: Optional[torch.Tensor] = None,
    ) -> tuple[torch.Tensor, str]:
        cfg = ensure_config(api_config)
        content: list[dict] = []
        for img in (image_1, image_2, image_3):
            if img is None or (hasattr(img, "numel") and img.numel() == 0):
                continue
            b64_list = tensor_to_b64(img[:1], fmt="JPEG", quality=85, max_side=1280)
            if b64_list:
                content.append({"type": "image_url", "image_url": {"url": b64_list[0]}})
        if prompt:
            content.append({"type": "text", "text": prompt})

        body = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "stream": bool(stream),
        }
        resp = api_request(
            cfg,
            "POST",
            "/v1/chat/completions",
            json_body=body,
            stream=bool(stream),
            retries=2,
        )

        if stream:
            from .utils import collect_stream_text
            full_text = collect_stream_text(resp)
            tensor = _parse_response_to_tensor(full_text, cfg, raw_text=full_text)
            return (tensor, full_text)

        data = resp.json()
        try:
            text_blob = data["choices"][0]["message"].get("content", "") or ""
            if isinstance(text_blob, list):
                text_blob = json.dumps(text_blob, ensure_ascii=False)
        except Exception:
            text_blob = json.dumps(data, ensure_ascii=False)
        tensor = _parse_response_to_tensor(data, cfg, raw_text=text_blob)
        return (tensor, text_blob)


NODE_CLASS_MAPPINGS = {
    "RespectImageGenerate": RespectImageGenerate,
    "RespectImageMultiRef": RespectImageMultiRef,
    "RespectGPTLocalImage": RespectGPTLocalImage,
    "RespectImageChat": RespectImageChat,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectImageGenerate": "Respect 图片生成",
    "RespectImageMultiRef": "Respect 多参考图编辑",
    "RespectGPTLocalImage": "Respect GPT本地版生图",
    "RespectImageChat": "Respect 多模态对话生图",
}
