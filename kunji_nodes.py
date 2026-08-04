"""Respect ComfyUI 扩展 - 坤鸡 图片（`https://img.yunfei.best`）专用节点。

按坤鸡「图生图接口」文档：

- 图生图：`POST /v1/images/edits`，`multipart/form-data`
  必填 `image`(file) / `model`(如 gpt-image-2) / `prompt` / `response_format`(示例 b64_json)，可选 `size`
  返回 `data[0].b64_json`
- 文生图：无参考图时走 `POST /v1/images/generations`（JSON，同一套字段）

坤鸡的**视频**用 `Respect Grok-Video 视频（坤鸡分支）`，注意两者 base_url 可能不同：
图片是 `https://img.yunfei.best`，视频是你的坤鸡视频网关地址。
"""

from __future__ import annotations

import base64
import json


from .utils import (
    RespectAPIError,
    api_request,
    dynamic_image_inputs,
    ensure_config,
    expand_image_frames,
    extract_image_payloads,
    resolve_image_to_tensor,
    tensor_to_b64,
    tensors_concat,
)

CATEGORY = "Respect/坤鸡"

KUNJI_IMAGE_MODELS = ["gpt-image-2", "gpt-image-1", "nano-banana"]
KUNJI_SIZES = ["1024x1024", "1536x1024", "1024x1536", "2048x2048", "1792x1024", "1024x1792"]
KUNJI_FORMATS = ["b64_json", "url"]


class RespectKunjiImage:
    """坤鸡 图片（`img.yunfei.best`）。接了参考图走 `/v1/images/edits`（multipart），否则 `/v1/images/generations`。

    `response_format` 文档要求必填，示例用 `b64_json`（返回 `data[0].b64_json`）。
    参考图数量可变：填 `inputcount` 后点节点上的「更新输入口」；每个槽接 IMAGE 批次会展开成多张。
    """

    DESCRIPTION = ("坤鸡图片(base_url=https://img.yunfei.best)。有参考图→/v1/images/edits(multipart，重复 image 字段)，"
                   "无参考图→/v1/images/generations。response_format 必填(b64_json)。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://img.yunfei.best"}),
                "model": (KUNJI_IMAGE_MODELS, {"default": "gpt-image-2", "tooltip": "上新模型用 custom_model 填"}),
                "prompt": ("STRING", {"default": "", "multiline": True, "tooltip": "图片编辑/生成提示词（必填）"}),
                "size": (KUNJI_SIZES, {"default": "1024x1024", "tooltip": "图片尺寸；可用 custom_size 覆盖"}),
                "response_format": (KUNJI_FORMATS, {"default": "b64_json", "tooltip": "文档必填，示例 b64_json"}),
            },
            "optional": {
                "image_1": ("IMAGE", {"tooltip": "参考图（接了就走 /v1/images/edits）"}),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "n": ("INT", {"default": 1, "min": 1, "max": 10, "tooltip": "生成数量（文档未列，按 OpenAI 惯例）"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，如 2048x2048"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 32, "step": 1, "tooltip": "参考图接口数量；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, size, response_format,
                 n=1, custom_model="", custom_size="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        size = (custom_size or "").strip() or size
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        frames = expand_image_frames(dynamic_image_inputs(kwargs))
        if frames:
            files: list = [
                ("model", (None, model)),
                ("prompt", (None, prompt)),
                ("size", (None, size)),
                ("response_format", (None, response_format)),
                ("n", (None, str(int(n)))),
            ]
            for i, frame in enumerate(frames):
                b64 = tensor_to_b64(frame, fmt="PNG", max_side=2048)
                if not b64:
                    continue
                raw = base64.b64decode(b64[0].split(",", 1)[1])
                # 文档是单个 image 字段；多张按 OpenAI 惯例重复该字段
                files.append(("image", (f"ref_{i + 1}.png", raw, "image/png")))
            resp = api_request(cfg, "POST", "/v1/images/edits", files=files,
                               retries=2, timeout=max(cfg.timeout, 300))
        else:
            body = {
                "model": model, "prompt": prompt, "size": size,
                "response_format": response_format, "n": int(n),
            }
            resp = api_request(cfg, "POST", "/v1/images/generations", json_body=body,
                               retries=2, timeout=max(cfg.timeout, 300))

        data = resp.json() if resp.content else {}
        items = extract_image_payloads(data)
        if not items:
            raise RespectAPIError(f"未能从响应中提取图片: {json.dumps(data, ensure_ascii=False)[:400]}")
        tensors = [t for t in (resolve_image_to_tensor(i, cfg) for i in items) if t is not None]
        if not tensors:
            raise RespectAPIError(f"取到结果但无法解析为图片: {str(items)[:300]}")
        return (tensors_concat(tensors), model)


NODE_CLASS_MAPPINGS = {
    "RespectKunjiImage": RespectKunjiImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectKunjiImage": "Respect 坤鸡 图片（img.yunfei.best）",
}
