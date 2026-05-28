"""小裴 ComfyUI 扩展插件入口。

集成 https://api.aicopy.top 中转 API：
- 图片：文生图、单图参考、多图参考、GPT 本地版、多模态对话兜底
- 视频：Firefly Sora2 / VEO3.1 / Runway 4.5 / 即梦 SD2

环境变量：`XIAOPEI_API_KEY` 或 `AICOPY_API_KEY` 可作为默认 API Key。
"""

from __future__ import annotations

from . import api_settings, image_nodes, video_nodes


NODE_CLASS_MAPPINGS: dict = {}
NODE_DISPLAY_NAME_MAPPINGS: dict = {}

for module in (api_settings, image_nodes, video_nodes):
    NODE_CLASS_MAPPINGS.update(getattr(module, "NODE_CLASS_MAPPINGS", {}))
    NODE_DISPLAY_NAME_MAPPINGS.update(getattr(module, "NODE_DISPLAY_NAME_MAPPINGS", {}))


__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]
