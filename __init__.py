"""Respect ComfyUI 扩展插件入口。

集成 https://api.aicopy.top 中转 API，并提供基础工具节点：
- 图片：文生图、单图参考、多图参考、GPT 本地版、多模态对话兜底
- 视频：Firefly Sora2 / VEO3.1 / Runway 4.5 / 即梦 SD2
- 基础：ZIP 批量加载图片 / 视频（递增 / 递减 / 随机 / 固定）

- 预览：查看图像 / 查看视频

所有节点位于 ComfyUI 分类 `Respect` 下。
环境变量 `RESPECT_API_KEY` 或 `AICOPY_API_KEY` 可作为默认 API Key。
"""

from __future__ import annotations

from . import (
    api_settings,
    image_nodes,
    video_nodes,
    loader_nodes,
    preview_nodes,
    llm_nodes,
    seedance_nodes,
)


NODE_CLASS_MAPPINGS: dict = {}
NODE_DISPLAY_NAME_MAPPINGS: dict = {}

for module in (api_settings, image_nodes, video_nodes, loader_nodes, preview_nodes, llm_nodes, seedance_nodes):
    NODE_CLASS_MAPPINGS.update(getattr(module, "NODE_CLASS_MAPPINGS", {}))
    NODE_DISPLAY_NAME_MAPPINGS.update(getattr(module, "NODE_DISPLAY_NAME_MAPPINGS", {}))


# 前端资源目录（视频预览播放器）
WEB_DIRECTORY = "./web"

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
