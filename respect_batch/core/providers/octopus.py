# -*- coding: utf-8 -*-
"""章鱼哥。对齐 respect_comfyui/octopus_nodes.py。

这家最特别的一点：**图片和视频全走同一个端点** `POST /v1/videos` 异步提交
+ `GET /v1/videos/{task_id}` 轮询。别照抄别家的 images/videos 分流写法。

图片 body：{model, prompt, size 或 aspect_ratio, images[]}  → 结果是图片直链
视频 body：{model, prompt, size, images[]}
参考图用 base64 data URL；图片最多 8 张，omni 系最多 7 张。
"""

from __future__ import annotations

from typing import Callable, Optional

from ..apiutil import ApiError, extract_task_id, extract_video_url
from .base import ImageTask, Provider, VideoTask

IMAGE_MODELS = ["gpt-image-2", "gpt-image-2-2K", "gpt-image-2-4K",
                "nano_banana_2", "nano_banana_pro-1K", "nano_banana_pro-2K",
                "nano_banana_pro-4K"]
VIDEO_MODELS = ["veo_3_1-fast", "veo_3_1-fast-fl", "veo_3_1-fast-hd",
                "veo_3_1-fast-4K", "veo_3_1-lite", "veo_3_1",
                "sora-2-12s", "omni_flash-10s"]
IMAGE_ASPECTS = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"]
VIDEO_SIZES = ["720x1280", "1080x1920", "1280x720", "1920x1080", "1024x1024"]


def _cap(model: str) -> int:
    """omni 系参考图上限 7，其余 8。"""
    return 7 if "omni" in (model or "").lower() else 8


class OctopusProvider(Provider):
    id = "octopus"
    name = "章鱼哥"
    default_base_url = ""          # 网关地址各人不同，必须在设置页填
    supports = ("image", "video")

    def capabilities(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "default_base_url": self.default_base_url,
            "supports": list(self.supports),
            "image": {
                "models": IMAGE_MODELS,
                "default_model": "gpt-image-2",
                "sizes": ["1024x1536", "1024x1024", "1536x1024"],
                "default_size": "1024x1536",
                "max_refs": 8,
                "ref_mode": "data_uri",
                "notes": "图片也走 /v1/videos 异步端点（这家的统一设计）。"
                         "给了像素尺寸就用 size，否则用 aspect_ratio。",
            },
            "video": {
                "models": VIDEO_MODELS,
                "default_model": "veo_3_1-fast",
                "ratios": ["9:16", "16:9", "1:1"],
                "durations": [0],
                "default_duration": 0,
                "resolutions": [""],
                "max_refs": 8,
                "ref_mode": "data_uri",
                "notes": "⚠ 时长写在模型名里（sora-2-12s、omni_flash-10s），"
                         "不单独传 duration/seconds。veo 系不带时长后缀，用服务端默认。"
                         "size 传像素（如 720x1280），不是比例。",
            },
            "notes": "base_url 必填（网关地址各人不同）。图片/视频同一个端点。",
        }

    # ---------------------------------------------------------------- 共用
    def _submit_poll(self, body: dict, dest: str, *, log, cancel,
                     poll_interval: int, poll_timeout: int) -> dict:
        data = self.session.request("POST", "/v1/videos", json_body=body,
                                    retries=2, timeout=300)
        url = extract_video_url(data)
        task_id = extract_task_id(data)
        if not url:
            if not task_id:
                raise ApiError("提交没返回结果地址也没返回 task_id")
            url = self.session.poll("/v1/videos/{id}", task_id, picker=extract_video_url,
                                    interval=poll_interval, timeout=poll_timeout,
                                    content_path_tpl="/v1/videos/{id}/content",
                                    log=log, cancel=cancel)
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id,
                "model": body["model"]}

    # ---------------------------------------------------------------- image
    def generate_image(self, task: ImageTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 900) -> dict:
        model = task.model or "gpt-image-2"
        body = {"model": model, "prompt": task.prompt}
        size = (task.size or "").strip()
        if size and "x" in size.lower():
            body["size"] = size
        else:
            body["aspect_ratio"] = size or "auto"
        if task.refs:
            body["images"] = task.refs[:_cap(model)]
        return self._submit_poll(body, dest, log=log, cancel=cancel,
                                 poll_interval=poll_interval, poll_timeout=poll_timeout)

    # ---------------------------------------------------------------- video
    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 10, poll_timeout: int = 2400) -> dict:
        model = task.model or "veo_3_1-fast"
        # 这家的 size 要像素，不是比例。比例转成竖/横的常用尺寸。
        size = (task.resolution or "").strip()
        if not size:
            size = {"9:16": "720x1280", "16:9": "1280x720",
                    "1:1": "1024x1024"}.get(task.ratio or "9:16", "720x1280")
        body = {"model": model, "prompt": task.prompt, "size": size}
        if task.refs:
            body["images"] = task.refs[:_cap(model)]
        if task.duration:
            log(f"注意：这家的时长写在模型名里（如 sora-2-12s），"
                f"duration={task.duration} 不会发出去；要改时长请换模型")
        return self._submit_poll(body, dest, log=log, cancel=cancel,
                                 poll_interval=poll_interval, poll_timeout=poll_timeout)
