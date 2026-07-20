"""Respect ComfyUI 扩展 - LLM 文本 / 多模态 / Claude 节点。

面向 OpenAI 兼容 + Anthropic 兼容的中转网关（如 一花Codex / llm.xxttt.com）：

- `POST /v1/chat/completions`  → 文本 / 代码 / 多模态对话（gpt-5.x、codex、deepseek、qwen、kimi…）
- `POST /v1/responses`         → Codex 风格纯文本 / 代码（wire_api=responses）
- `POST /v1/images/generations`→ gpt-image-1 / 1.5 / 2 文生图
- `POST /v1/messages`          → Anthropic 协议 Claude 文本（x-api-key + anthropic-version）

配置时把 `Respect API 设置` 的 base_url 填成网关地址，例如 `https://llm.xxttt.com`
（OpenAI 端点会自动补 /v1；Anthropic 节点会去掉 /v1 后拼 /v1/messages）。
"""

from __future__ import annotations

import io
import json
import re
from typing import Any, Optional

import torch

from .utils import (
    DEFAULT_USER_AGENT,
    RespectAPIError,
    api_request,
    aspect_to_x,
    ensure_config,
    extract_image_payloads,
    iter_sse_lines,
    resolve_image_to_tensor,
    tensor_to_b64,
    tensor_to_pil,
    tensors_concat,
)

CATEGORY = "Respect/LLM"


# ---------------------------------------------------------------------------
# 公共解析
# ---------------------------------------------------------------------------


def _build_multimodal_content(prompt: str, images: list[Optional[torch.Tensor]], max_side: int = 1280) -> list[dict]:
    """OpenAI chat 多模态 content：图片在前，文本在后。"""
    content: list[dict] = []
    for img in images:
        if img is None or (hasattr(img, "numel") and img.numel() == 0):
            continue
        b64_list = tensor_to_b64(img[:1], fmt="JPEG", quality=88, max_side=max_side)
        if b64_list:
            content.append({"type": "image_url", "image_url": {"url": b64_list[0]}})
    if prompt:
        content.append({"type": "text", "text": prompt})
    return content


def _openai_chat_text(data: Any) -> str:
    try:
        msg = data["choices"][0]["message"]
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [c["text"] for c in content if isinstance(c, dict) and isinstance(c.get("text"), str)]
            return "".join(parts)
    except Exception:
        pass
    return ""


def _collect_chat_stream(resp) -> str:
    parts: list[str] = []
    for chunk in iter_sse_lines(resp):
        try:
            obj = json.loads(chunk)
        except Exception:
            continue
        try:
            delta = obj["choices"][0].get("delta") or {}
            content = delta.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for it in content:
                    if isinstance(it, dict) and isinstance(it.get("text"), str):
                        parts.append(it["text"])
        except Exception:
            continue
    return "".join(parts)


def _responses_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    if isinstance(data.get("output_text"), str) and data["output_text"]:
        return data["output_text"]
    parts: list[str] = []
    out = data.get("output")
    if isinstance(out, list):
        for item in out:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and isinstance(c.get("text"), str):
                        parts.append(c["text"])
            elif isinstance(item.get("text"), str):
                parts.append(item["text"])
    return "".join(parts)


def _collect_responses_stream(resp) -> str:
    parts: list[str] = []
    for chunk in iter_sse_lines(resp):
        try:
            obj = json.loads(chunk)
        except Exception:
            continue
        if obj.get("type") == "response.output_text.delta":
            d = obj.get("delta")
            if isinstance(d, str):
                parts.append(d)
    return "".join(parts)


def _anthropic_text(data: Any) -> str:
    parts: list[str] = []
    content = data.get("content") if isinstance(data, dict) else None
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str):
                parts.append(b["text"])
    return "".join(parts)


def _collect_anthropic_stream(resp) -> str:
    parts: list[str] = []
    for chunk in iter_sse_lines(resp):
        try:
            obj = json.loads(chunk)
        except Exception:
            continue
        if obj.get("type") == "content_block_delta":
            d = obj.get("delta") or {}
            if d.get("type") == "text_delta" and isinstance(d.get("text"), str):
                parts.append(d["text"])
    return "".join(parts)


def _anthropic_headers(cfg) -> dict:
    return {
        "x-api-key": cfg.resolve_api_key(),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }


def _images_to_tensor(data: Any, cfg) -> torch.Tensor:
    payloads = extract_image_payloads(data)
    tensors: list[torch.Tensor] = []
    for item in payloads:
        t = resolve_image_to_tensor(item, cfg)
        if t is not None:
            tensors.append(t)
    if not tensors:
        snippet = json.dumps(data, ensure_ascii=False)[:600] if not isinstance(data, str) else data[:600]
        raise RespectAPIError(f"未能从响应中提取图片: {snippet}")
    return tensors_concat(tensors)


# ---------------------------------------------------------------------------
# response_format / json_schema 结构化输出
# ---------------------------------------------------------------------------


RESPONSE_FORMATS = ["text", "json_object", "json_schema"]


def _parse_json_loose(s: str) -> Any:
    s = (s or "").strip()
    if not s:
        return None
    m = re.search(r"```(?:json)?\s*(.+?)```", s, re.DOTALL | re.IGNORECASE)
    if m:
        s = m.group(1).strip()
    return json.loads(s)


def _parsed_schema(schema_str: str) -> dict:
    try:
        schema = _parse_json_loose(schema_str)
    except Exception as exc:
        raise RespectAPIError(f"json_schema 不是合法 JSON: {exc}")
    if not isinstance(schema, dict):
        raise RespectAPIError("json_schema 模式需要在 json_schema 里填一个 JSON Schema 对象")
    return schema


def _openai_response_format(response_format: str, schema_str: str, schema_name: str) -> Optional[dict]:
    """OpenAI /v1/chat/completions 的 response_format。"""
    if response_format == "json_object":
        return {"type": "json_object"}
    if response_format == "json_schema":
        schema = _parsed_schema(schema_str)
        # 用户可能直接填了完整 {name, schema, strict} 包装
        if "schema" in schema and "name" in schema:
            js = schema
        else:
            js = {"name": (schema_name or "response").strip() or "response", "schema": schema, "strict": True}
        return {"type": "json_schema", "json_schema": js}
    return None


def _responses_text_format(response_format: str, schema_str: str, schema_name: str) -> Optional[dict]:
    """OpenAI /v1/responses 的 text.format。"""
    if response_format == "json_object":
        return {"type": "json_object"}
    if response_format == "json_schema":
        schema = _parsed_schema(schema_str)
        if "schema" in schema and "name" in schema:
            fmt = {"type": "json_schema"}
            fmt.update({k: schema[k] for k in ("name", "schema", "strict") if k in schema})
            return fmt
        return {"type": "json_schema", "name": (schema_name or "response").strip() or "response",
                "schema": schema, "strict": True}
    return None


def _claude_json_instruction(response_format: str, schema_str: str) -> str:
    """Anthropic 无原生 response_format，用系统提示强制 JSON。"""
    if response_format not in ("json_object", "json_schema"):
        return ""
    instr = "You must respond with a single valid JSON value and nothing else. Do not use markdown code fences."
    if response_format == "json_schema" and (schema_str or "").strip():
        instr += " The JSON must conform to this JSON Schema:\n" + schema_str.strip()
    return instr


# ---------------------------------------------------------------------------
# OpenAI Chat Completions —— 文本 / 代码 / 多模态
# ---------------------------------------------------------------------------


class RespectChatLLM:
    """OpenAI 兼容 `/v1/chat/completions` 文本对话。

    返回纯文本。可选挂 1~3 张图片做多模态输入（gpt-5.x 视觉、视觉模型）。
    模型名从网关「模型列表」复制，例如 gpt-5.5 / gpt-5.3-codex / deepseek-ai/DeepSeek-V4-Pro。
    temperature < 0 表示不发送该字段（codex / reasoning 模型建议留 -1）。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "model": ("STRING", {"default": "gpt-5.5", "multiline": False}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "stream": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "system_prompt": ("STRING", {"default": "", "multiline": True}),
                "temperature": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 2.0, "step": 0.1}),
                "max_tokens": ("INT", {"default": 0, "min": 0, "max": 200000}),
                "response_format": (RESPONSE_FORMATS, {"default": "text"}),
                "json_schema": ("STRING", {"default": "", "multiline": True, "placeholder": "response_format=json_schema 时填 JSON Schema"}),
                "schema_name": ("STRING", {"default": "response", "multiline": False}),
                "image_1": ("IMAGE",),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "chat"
    CATEGORY = CATEGORY

    def chat(
        self,
        api_config: Any,
        model: str,
        prompt: str,
        stream: bool,
        system_prompt: str = "",
        temperature: float = -1.0,
        max_tokens: int = 0,
        response_format: str = "text",
        json_schema: str = "",
        schema_name: str = "response",
        image_1: Optional[torch.Tensor] = None,
        image_2: Optional[torch.Tensor] = None,
        image_3: Optional[torch.Tensor] = None,
    ) -> tuple[str]:
        cfg = ensure_config(api_config)
        messages: list[dict] = []
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})

        imgs = [image_1, image_2, image_3]
        has_img = any(i is not None and getattr(i, "numel", lambda: 0)() > 0 for i in imgs)
        if has_img:
            messages.append({"role": "user", "content": _build_multimodal_content(prompt, imgs)})
        else:
            messages.append({"role": "user", "content": prompt})

        body: dict = {"model": model, "messages": messages, "stream": bool(stream)}
        if temperature >= 0:
            body["temperature"] = float(temperature)
        if max_tokens > 0:
            body["max_tokens"] = int(max_tokens)
        fmt = _openai_response_format(response_format, json_schema, schema_name)
        if fmt:
            body["response_format"] = fmt

        resp = api_request(
            cfg, "POST", "/v1/chat/completions",
            json_body=body, stream=bool(stream), retries=2,
            timeout=max(cfg.timeout, 300),
        )
        if stream:
            return (_collect_chat_stream(resp),)
        text = _openai_chat_text(resp.json())
        if not text:
            raise RespectAPIError(f"响应中无文本内容: {json.dumps(resp.json(), ensure_ascii=False)[:600]}")
        return (text,)


# ---------------------------------------------------------------------------
# OpenAI Responses —— Codex 纯文本 / 代码
# ---------------------------------------------------------------------------


class RespectResponsesLLM:
    """OpenAI 兼容 `/v1/responses`（Codex wire_api=responses）。

    适合 gpt-5.3-codex / gpt-5.3-codex-spark 等代码模型，返回纯文本。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "model": ("STRING", {"default": "gpt-5.3-codex", "multiline": False}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "stream": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "instructions": ("STRING", {"default": "", "multiline": True, "placeholder": "系统级指令，可留空"}),
                "max_output_tokens": ("INT", {"default": 0, "min": 0, "max": 200000}),
                "response_format": (RESPONSE_FORMATS, {"default": "text"}),
                "json_schema": ("STRING", {"default": "", "multiline": True, "placeholder": "response_format=json_schema 时填 JSON Schema"}),
                "schema_name": ("STRING", {"default": "response", "multiline": False}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "respond"
    CATEGORY = CATEGORY

    def respond(
        self,
        api_config: Any,
        model: str,
        prompt: str,
        stream: bool,
        instructions: str = "",
        max_output_tokens: int = 0,
        response_format: str = "text",
        json_schema: str = "",
        schema_name: str = "response",
    ) -> tuple[str]:
        cfg = ensure_config(api_config)
        body: dict = {
            "model": model,
            "input": prompt,
            "stream": bool(stream),
        }
        if instructions.strip():
            body["instructions"] = instructions
        if max_output_tokens > 0:
            body["max_output_tokens"] = int(max_output_tokens)
        fmt = _responses_text_format(response_format, json_schema, schema_name)
        if fmt:
            body["text"] = {"format": fmt}

        resp = api_request(
            cfg, "POST", "/v1/responses",
            json_body=body, stream=bool(stream), retries=2,
            timeout=max(cfg.timeout, 300),
        )
        if stream:
            return (_collect_responses_stream(resp),)
        text = _responses_text(resp.json())
        if not text:
            raise RespectAPIError(f"响应中无文本内容: {json.dumps(resp.json(), ensure_ascii=False)[:600]}")
        return (text,)


# ---------------------------------------------------------------------------
# aicopy gpt-image-2（image2）—— 文生图 / 图生图
# ---------------------------------------------------------------------------


# gpt-image-1-direct：直连 openai_images，model_id 拼成 gpt-image-{res}-{aspect}（带内嵌尺寸）
GPT_IMAGE_MODELS = ["gpt-image-2", "gpt-image-1-direct", "gpt-image-1.5", "gpt-image-1"]
# image2 在 api.aicopy.top 上支持的宽高比（文档 §8）
GPT_IMAGE2_ASPECTS = ["1:1", "5:4", "4:5", "9:16", "16:9", "21:9", "4:3", "3:4", "3:2", "2:3"]
GPT_IMAGE2_RESOLUTIONS = ["1k", "2k", "4k"]
_RES_LONG_EDGE = {"1k": 1024, "2k": 2048, "4k": 4096}
# 带内嵌尺寸的 model_id（gpt-image-1-direct / firefly-*）用的长边档
_EXPLICIT_LONG_EDGE = {"1k": 1536, "2k": 2048, "4k": 3840}


def _aicopy_image2_size(aspect_ratio: str, resolution: str) -> str:
    """按 aicopy 文档把 比例+分辨率档 换算成 `宽x高`（长边 1k=1024 / 2k=2048 / 4k=4096）。

    例：1k 1:1=1024x1024、1k 16:9=1024x576、2k 16:9=2048x1152、2k 9:16=1152x2048。
    宽高对齐到 16 的倍数。
    """
    long_edge = _RES_LONG_EDGE.get((resolution or "1k").lower(), 1024)
    try:
        wr, hr = aspect_ratio.replace("x", ":").split(":")
        wr, hr = float(wr), float(hr)
    except Exception:
        wr, hr = 1.0, 1.0
    if wr <= 0 or hr <= 0:
        wr, hr = 1.0, 1.0

    def _round16(v: float) -> int:
        return max(16, int(round(v / 16.0)) * 16)

    if wr >= hr:
        width = long_edge
        height = _round16(long_edge * hr / wr)
    else:
        height = long_edge
        width = _round16(long_edge * wr / hr)
    return f"{width}x{height}"


def _explicit_fallback_size(aspect_ratio: str, resolution: str) -> str:
    """带内嵌尺寸的 model_id 用的尺寸（长边 1k=1536 / 2k=2048 / 4k=3840）。"""
    long_edge = _EXPLICIT_LONG_EDGE.get((resolution or "").lower())
    if not long_edge:
        return _aicopy_image2_size(aspect_ratio, resolution)
    try:
        wr, hr = aspect_ratio.replace("x", ":").split(":")
        wr, hr = float(wr), float(hr)
    except Exception:
        return _aicopy_image2_size(aspect_ratio, resolution)
    if wr <= 0 or hr <= 0:
        return _aicopy_image2_size(aspect_ratio, resolution)

    def _round16(v: float) -> int:
        return max(16, int(round(v / 16.0)) * 16)

    if wr >= hr:
        return f"{long_edge}x{_round16(long_edge * hr / wr)}"
    return f"{_round16(long_edge * wr / hr)}x{long_edge}"


def _image2_payload_size(model_id: str, aspect_ratio: str, resolution: str) -> str:
    """镜像插件 _build_images_payload：内嵌尺寸 model_id 用 1536/2048/3840 档，否则 1024/2048/4096 档。"""
    if re.search(r"-\d+k-\d+x\d+$", str(model_id).lower()):
        return _explicit_fallback_size(aspect_ratio, resolution)
    return _aicopy_image2_size(aspect_ratio, resolution)


def _tensor_to_png_bytes(tensor: torch.Tensor, max_side: int = 1536) -> bytes:
    pil_list = tensor_to_pil(tensor[:1])
    if not pil_list:
        return b""
    pil = pil_list[0]
    w, h = pil.size
    long_side = max(w, h)
    if max_side > 0 and long_side > max_side:
        scale = max_side / float(long_side)
        pil = pil.resize((int(w * scale), int(h * scale)))
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


class RespectOpenAIImage:
    """aicopy image2（gpt-image-2）文生图 / 图生图。

    按 api.aicopy.top 文档发送 `size` + `aspect_ratio` + `resolution(1k/2k/4k)`：
    - 不接参考图 → `POST /v1/images/generations`（纯文生图）
    - 接了 1~4 张参考图 → `POST /v1/images/edits`（multipart，每张参考图作为一个 `image` 字段）

    尺寸按文档换算：长边 1k=1024 / 2k=2048 / 4k=4096（如 2k 16:9 → 2048x1152）。
    `custom_model` / `custom_size` 填了优先使用。返回 IMAGE。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "model": (GPT_IMAGE_MODELS, {"default": "gpt-image-2"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "aspect_ratio": (GPT_IMAGE2_ASPECTS, {"default": "1:1"}),
                "resolution": (GPT_IMAGE2_RESOLUTIONS, {"default": "1k"}),
                "n": ("INT", {"default": 1, "min": 1, "max": 4}),
            },
            "optional": {
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了优先使用"}),
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，如 2048x2048，填了覆盖比例+分辨率换算的 size"}),
                "image_1": ("IMAGE",),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "model_used", "size_used")
    FUNCTION = "generate"
    CATEGORY = "Respect"

    def generate(
        self,
        api_config: Any,
        model: str,
        prompt: str,
        aspect_ratio: str,
        resolution: str,
        n: int,
        custom_model: str = "",
        custom_size: str = "",
        image_1: Optional[torch.Tensor] = None,
        image_2: Optional[torch.Tensor] = None,
        image_3: Optional[torch.Tensor] = None,
        image_4: Optional[torch.Tensor] = None,
    ) -> tuple[torch.Tensor, str, str]:
        cfg = ensure_config(api_config)
        aspect_x = aspect_to_x(aspect_ratio)
        res = (resolution or "1k").lower()

        custom_model = (custom_model or "").strip()
        if custom_model:
            model = custom_model
        elif model == "gpt-image-1-direct":
            # 直连：model_id 拼成 gpt-image-{res}-{aspect}
            model = f"gpt-image-{res}-{aspect_x}"
        if not model:
            raise RespectAPIError("请选择模型或填写 custom_model")

        size = (custom_size or "").strip() or _image2_payload_size(model, aspect_x, res)

        refs: list[bytes] = []
        for img in (image_1, image_2, image_3, image_4):
            if img is None or (hasattr(img, "numel") and img.numel() == 0):
                continue
            data = _tensor_to_png_bytes(img)
            if data:
                refs.append(data)

        if refs:
            # 图生图 / 多图编辑：multipart 上传到 /v1/images/edits
            files: list = [
                ("model", (None, model)),
                ("prompt", (None, prompt)),
                ("n", (None, str(int(n)))),
                ("size", (None, size)),
                ("aspect_ratio", (None, aspect_x)),
                ("resolution", (None, res)),
            ]
            for i, data in enumerate(refs):
                # 文档要求每张参考图都用名为 image 的字段（重复出现）
                files.append(("image", (f"ref_{i + 1}.png", data, "image/png")))
            resp = api_request(
                cfg, "POST", "/v1/images/edits",
                files=files, retries=3, timeout=max(cfg.timeout, 300),
            )
        else:
            body: dict = {
                "model": model,
                "prompt": prompt,
                "n": int(n),
                "size": size,
                "aspect_ratio": aspect_x,
                "resolution": res,
            }
            resp = api_request(cfg, "POST", "/v1/images/generations", json_body=body, retries=3)

        return (_images_to_tensor(resp.json(), cfg), model, size)


# ---------------------------------------------------------------------------
# Anthropic Messages —— Claude
# ---------------------------------------------------------------------------


def _anthropic_image_blocks(images: list[Optional[torch.Tensor]], max_side: int = 1280) -> list[dict]:
    blocks: list[dict] = []
    for img in images:
        if img is None or (hasattr(img, "numel") and img.numel() == 0):
            continue
        b64_list = tensor_to_b64(img[:1], fmt="JPEG", quality=88, max_side=max_side)
        if not b64_list:
            continue
        raw = b64_list[0].split(",", 1)[1]
        blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": raw},
        })
    return blocks


class RespectClaudeLLM:
    """Anthropic 兼容 `/v1/messages` 文本对话（Claude 分组）。

    使用 x-api-key + anthropic-version 请求头。base_url 填网关根地址即可
    （例如 https://llm.xxttt.com，节点内部拼 /v1/messages）。
    max_tokens 为 Anthropic 必填字段。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
                "model": ("STRING", {"default": "claude-sonnet-4-6", "multiline": False}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "max_tokens": ("INT", {"default": 4096, "min": 1, "max": 200000}),
                "stream": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "system_prompt": ("STRING", {"default": "", "multiline": True}),
                "temperature": ("FLOAT", {"default": -1.0, "min": -1.0, "max": 1.0, "step": 0.1}),
                "response_format": (RESPONSE_FORMATS, {"default": "text"}),
                "json_schema": ("STRING", {"default": "", "multiline": True, "placeholder": "json_schema 模式：Anthropic 无原生支持，靠系统提示强制"}),
                "image_1": ("IMAGE",),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "chat"
    CATEGORY = CATEGORY

    def chat(
        self,
        api_config: Any,
        model: str,
        prompt: str,
        max_tokens: int,
        stream: bool,
        system_prompt: str = "",
        temperature: float = -1.0,
        response_format: str = "text",
        json_schema: str = "",
        image_1: Optional[torch.Tensor] = None,
        image_2: Optional[torch.Tensor] = None,
        image_3: Optional[torch.Tensor] = None,
    ) -> tuple[str]:
        cfg = ensure_config(api_config)

        content: list[dict] = _anthropic_image_blocks([image_1, image_2, image_3])
        if prompt:
            content.append({"type": "text", "text": prompt})
        if not content:
            content.append({"type": "text", "text": ""})

        # Anthropic 无原生 response_format，用系统提示强制 JSON
        sys_text = system_prompt or ""
        json_instr = _claude_json_instruction(response_format, json_schema)
        if json_instr:
            sys_text = (sys_text + "\n\n" + json_instr).strip() if sys_text.strip() else json_instr

        body: dict = {
            "model": model,
            "max_tokens": int(max_tokens),
            "messages": [{"role": "user", "content": content}],
            "stream": bool(stream),
        }
        if sys_text.strip():
            body["system"] = sys_text
        if temperature >= 0:
            body["temperature"] = float(temperature)

        resp = api_request(
            cfg, "POST", "/v1/messages",
            json_body=body, stream=bool(stream), retries=2,
            timeout=max(cfg.timeout, 300),
            headers=_anthropic_headers(cfg),
        )
        if stream:
            return (_collect_anthropic_stream(resp),)
        text = _anthropic_text(resp.json())
        if not text:
            raise RespectAPIError(f"响应中无文本内容: {json.dumps(resp.json(), ensure_ascii=False)[:600]}")
        return (text,)


NODE_CLASS_MAPPINGS = {
    "RespectChatLLM": RespectChatLLM,
    "RespectResponsesLLM": RespectResponsesLLM,
    "RespectOpenAIImage": RespectOpenAIImage,
    "RespectClaudeLLM": RespectClaudeLLM,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectChatLLM": "Respect Chat 对话 (OpenAI)",
    "RespectResponsesLLM": "Respect Responses 代码 (Codex)",
    "RespectOpenAIImage": "Respect image2 文生图/图生图 (aicopy)",
    "RespectClaudeLLM": "Respect Claude 对话 (Anthropic)",
}
