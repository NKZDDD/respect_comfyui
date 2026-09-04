# -*- coding: utf-8 -*-
"""一手 / ONE API（www.weijinapi.top）。**只做视频**。

标准流程（文档原话）：
  1. `GET /v1/models` 拿当前 Key 能用的模型**和能力**
  2. `POST /v1/videos` 创建任务，保存公开任务 ID
  3. `GET /v1/videos/{task_id}` 查进度
  4. `GET /v1/videos/{task_id}/content` 下载

这家和别家最不一样的一点：**模型能力是接口给的，不是写死的**。
`/v1/models` 每个模型带 `durations_seconds` / `ratios` / `max_images` /
`max_videos` / `max_audios` / `audio_requires_image` / `pricing`，
文档明确写「字段缺失时以后台模型说明为准，**不要自行猜测**」——
所以这里不硬编码模型清单，capabilities() 只给空列表 + 说明，
真实清单由前端调 list_models() 拉。

另外三条硬规矩（文档明写）：
  · 统一用 `seconds`，**不要**用 `duration_seconds`
  · **不要**提交旧式 `size` 倍率字段
  · 图片/音频只收「服务器能直接访问的 HTTPS 地址」；**只有视频**有上传接口
    （`POST /api/upload/video`，单文件 ≤50MB）
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from ..apiutil import ApiError, extract_task_id, extract_video_url
from .base import Provider, VideoTask

RATIOS = ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9"]
UPLOAD_LIMIT = 50 * 1024 * 1024      # 视频上传单文件上限


class YishouProvider(Provider):
    id = "yishou"
    name = "一手 ONE API www.weijinapi.top"
    aliases = ("oneapi", "one-api", "weijin", "weijinapi")
    default_base_url = "https://www.weijinapi.top"
    supports = ("video",)
    # 参考图/音频只收公网 HTTPS（没有图片上传接口）；视频可以本地上传换链接
    ref_mode = "url"

    def capabilities(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "default_base_url": self.default_base_url,
            "supports": list(self.supports),
            "video": {
                # 故意留空：这家的模型和能力由 GET /v1/models 决定，写死会过期。
                # 前端拿到空列表会去调 list_models()。
                "models": [],
                "default_model": "",
                "ratios": RATIOS,
                "durations": [5, 10, 15],
                "default_duration": 15,
                "resolutions": [""],
                "max_refs": 9,
                "ref_mode": "url",
                "notes": "模型清单和能力（秒数/比例/图片视频音频上限/单价）来自 GET /v1/models，"
                         "**先拉列表再选**，别照抄别家的模型名。"
                         "参考图和音频只收公网 HTTPS 地址（这家没有图片上传接口）；"
                         "参考视频可用 POST /api/upload/video 上传（≤50MB）换链接。"
                         "统一用 seconds，不传 size。",
            },
            "notes": "纯视频服务商。创建超时不要盲目重试 —— 可能已经计费建单，先去查任务。",
        }

    # ---------------------------------------------------------------- models
    def model_specs(self) -> list:
        """带能力字段的模型清单（比基类的 list_models 多返回限制/价格）。"""
        try:
            data = self.session.request("GET", "/v1/models", retries=1, timeout=30)
        except ApiError:
            return []
        out = []
        for m in (data.get("data") or []):
            if not m.get("id"):
                continue
            out.append({
                "id": m.get("id"),
                "display_name": m.get("display_name") or m.get("id"),
                "resolution": m.get("resolution", ""),
                "durations": m.get("durations_seconds") or [],
                "ratios": m.get("ratios") or [],
                "max_images": m.get("max_images", 0),
                "max_videos": m.get("max_videos", 0),
                "max_audios": m.get("max_audios", 0),
                "audio_requires_image": bool(m.get("audio_requires_image")),
                "pricing": m.get("pricing") or {},
            })
        return out

    # ---------------------------------------------------------------- upload
    def upload_video(self, path: str) -> str:
        """本地参考视频 → 公网 HTTPS 地址（放进创建任务的 videos 数组）。"""
        if not os.path.isfile(path):
            raise ApiError(f"找不到文件: {path}")
        size = os.path.getsize(path)
        if size > UPLOAD_LIMIT:
            raise ApiError(f"{os.path.basename(path)} 有 {size / 1048576:.1f}MB，"
                           f"超过一手的 50MB 上传上限")
        with open(path, "rb") as fh:
            data = self.session.request(
                "POST", "/api/upload/video",
                files=[("file", (os.path.basename(path), fh.read(), "video/mp4"))],
                retries=1, timeout=600)
        url = extract_video_url(data) or (data.get("url") if isinstance(data, dict) else "")
        if not url:
            raise ApiError(f"视频上传没返回地址: {str(data)[:300]}")
        return url

    # ---------------------------------------------------------------- video
    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 15, poll_timeout: int = 2400) -> dict:
        model = (task.model or "").strip()
        if not model:
            raise ApiError("一手必须显式指定模型 —— 先调 GET /v1/models 看当前 Key 能用哪些"
                           "（不同 Key 可用模型不同，没有可猜的默认值）",
                           status=0, kind="task_fatal")

        refs = list(task.refs or [])
        local = [r for r in refs if not str(r).startswith(("http://", "https://"))]
        if local:
            raise ApiError(
                f"一手的参考图只收公网 HTTPS 地址，这一项给的 {len(local)} 张是本地图"
                f"（这家没有图片上传接口）。去「设置 → 参考图上传」配对象存储，"
                f"配好后本机图会自动传成链接；或把这类活排给收本地图的服务商。",
                status=0, kind="task_fatal")

        body: dict = {
            "model": model,
            "prompt": task.prompt or "",
            "seconds": int(task.duration or 15),      # 文档：统一用 seconds，别用 duration_seconds
            "aspect_ratio": task.ratio or "9:16",     # 必填
        }
        if refs:
            body["images"] = refs
        videos = [v for v in (task.extra.get("video_refs") or task.extra.get("videos") or []) if v]
        audios = [a for a in (task.extra.get("audio_refs") or task.extra.get("audios") or []) if a]
        if videos:
            body["videos"] = videos
        if audios:
            body["audios"] = audios
            if not refs:
                log("提醒：部分模型的 audio_requires_image=true，用音频时必须同时给图片"
                    "（以 GET /v1/models 返回的能力为准）")
        # resolution 文档说「模型固定分辨率时建议省略」——只有显式要求才发
        if task.resolution:
            body["resolution"] = task.resolution

        log(f"一手 {model}: seconds={body['seconds']} aspect_ratio={body['aspect_ratio']} "
            f"图{len(refs)}/视频{len(videos)}/音频{len(audios)}")
        data = self.session.request("POST", "/v1/videos", json_body=body, retries=2, timeout=300)

        url = extract_video_url(data)
        task_id = extract_task_id(data)
        if not url:
            if not task_id:
                raise ApiError(f"提交没返回任务 ID: {str(data)[:300]}")
            url = self.session.poll("/v1/videos/{id}", task_id, picker=extract_video_url,
                                    interval=poll_interval, timeout=poll_timeout,
                                    content_path_tpl="/v1/videos/{id}/content",
                                    log=log, cancel=cancel)
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id, "model": model}
