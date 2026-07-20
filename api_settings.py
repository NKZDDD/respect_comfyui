"""Respect ComfyUI 扩展 - API 配置与模型列表节点。"""

from __future__ import annotations

from typing import Any

from .utils import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT,
    DEFAULT_UPLOAD_BASE,
    RespectAPIError,
    RespectConfig,
    api_request,
    ensure_config,
)


CATEGORY = "Respect"


class RespectApiSettings:
    """中转 API 配置节点。

    输出 `RESPECT_CONFIG`，供后续图片 / 视频节点使用。
    api_key 留空时会读取环境变量 `RESPECT_API_KEY` 或 `AICOPY_API_KEY`。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_key": ("STRING", {"default": "", "multiline": False, "placeholder": "Bearer Token，可留空读环境变量"}),
                "base_url": ("STRING", {"default": DEFAULT_BASE_URL, "multiline": False}),
                "timeout": ("INT", {"default": DEFAULT_TIMEOUT, "min": 30, "max": 3600}),
            },
            "optional": {
                "proxy": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，http(s)://host:port"}),
                "upload_base_url": ("STRING", {"default": DEFAULT_UPLOAD_BASE, "multiline": False, "placeholder": "参考图上传地址（Seedance/grok-video 用），默认 api.aione.help"}),
            },
        }

    RETURN_TYPES = ("RESPECT_CONFIG",)
    RETURN_NAMES = ("api_config",)
    FUNCTION = "build"
    CATEGORY = CATEGORY

    def build(self, api_key: str, base_url: str, timeout: int, proxy: str = "", upload_base_url: str = "") -> tuple[RespectConfig]:
        cfg = RespectConfig(
            api_key=(api_key or "").strip(),
            base_url=(base_url or DEFAULT_BASE_URL).strip(),
            timeout=int(timeout),
            proxy=(proxy or "").strip(),
            upload_base_url=(upload_base_url or "").strip(),
        )
        if not cfg.resolve_api_key():
            print("[Respect] 警告：未提供 api_key 且未检测到 RESPECT_API_KEY / AICOPY_API_KEY 环境变量")
        return (cfg,)


class RespectLoadModels:
    """请求 `/v1/models`，把模型 ID 列表用换行符拼成字符串输出。"""

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG",),
            },
            "optional": {
                "filter": ("STRING", {"default": "", "multiline": False, "placeholder": "包含关键字过滤，可留空"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("model_list", "count")
    FUNCTION = "load"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def load(self, api_config: Any, filter: str = "") -> tuple[str, str]:
        cfg = ensure_config(api_config)
        try:
            resp = api_request(cfg, "GET", "/v1/models", retries=2)
            data = resp.json()
        except RespectAPIError as exc:
            return (f"加载失败: {exc}", "0")

        items = data.get("data", []) if isinstance(data, dict) else []
        ids = [m.get("id", "") for m in items if isinstance(m, dict) and m.get("id")]
        key = (filter or "").strip().lower()
        if key:
            ids = [i for i in ids if key in i.lower()]
        return ("\n".join(ids), str(len(ids)))


NODE_CLASS_MAPPINGS = {
    "RespectApiSettings": RespectApiSettings,
    "RespectLoadModels": RespectLoadModels,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectApiSettings": "Respect API 设置",
    "RespectLoadModels": "Respect 加载模型列表",
}
