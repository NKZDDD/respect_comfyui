"""小裴 ComfyUI 扩展 - API 配置与模型列表节点。"""

from __future__ import annotations

from typing import Any

from .utils import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT,
    XiaopeiAPIError,
    XiaopeiConfig,
    api_request,
    ensure_config,
)


CATEGORY = "小裴/Xiaopei"


class XiaopeiApiSettings:
    """中转 API 配置节点。

    输出 `XIAOPEI_CONFIG`，供后续图片 / 视频节点使用。
    api_key 留空时会读取环境变量 `XIAOPEI_API_KEY` 或 `AICOPY_API_KEY`。
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
            },
        }

    RETURN_TYPES = ("XIAOPEI_CONFIG",)
    RETURN_NAMES = ("api_config",)
    FUNCTION = "build"
    CATEGORY = CATEGORY

    def build(self, api_key: str, base_url: str, timeout: int, proxy: str = "") -> tuple[XiaopeiConfig]:
        cfg = XiaopeiConfig(
            api_key=(api_key or "").strip(),
            base_url=(base_url or DEFAULT_BASE_URL).strip(),
            timeout=int(timeout),
            proxy=(proxy or "").strip(),
        )
        if not cfg.resolve_api_key():
            print("[Xiaopei] 警告：未提供 api_key 且未检测到 XIAOPEI_API_KEY / AICOPY_API_KEY 环境变量")
        return (cfg,)


class XiaopeiLoadModels:
    """请求 `/v1/models`，把模型 ID 列表用换行符拼成字符串输出。"""

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("XIAOPEI_CONFIG",),
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
        except XiaopeiAPIError as exc:
            return (f"加载失败: {exc}", "0")

        items = data.get("data", []) if isinstance(data, dict) else []
        ids = [m.get("id", "") for m in items if isinstance(m, dict) and m.get("id")]
        key = (filter or "").strip().lower()
        if key:
            ids = [i for i in ids if key in i.lower()]
        return ("\n".join(ids), str(len(ids)))


NODE_CLASS_MAPPINGS = {
    "XiaopeiApiSettings": XiaopeiApiSettings,
    "XiaopeiLoadModels": XiaopeiLoadModels,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "XiaopeiApiSettings": "小裴 API 设置",
    "XiaopeiLoadModels": "小裴 加载模型列表",
}
