# -*- coding: utf-8 -*-
"""M86 / New API（yiyun.xiaoge.uk）。

OpenAI 兼容中转，当前三条业务线：
  · 对话   POST /v1/chat/completions（本程序不用，走 core/llm.py）
  · 图片   POST /v1/images/generations —— `seed-image-1.0`，**同步**返回 data[].url
  · 视频   POST /v1/videos —— `seed-2.0`，异步；GET /v1/videos/{id} 轮询

三个和别家不一样、最容易写错的点：
  1. **图片的 `size` 是比例**（`1:1`/`2:3`/`9:16`…），不是像素。传 "1024x1536"
     它认不出来 → 本类会自动换算成最接近的比例。
  2. **视频的比例字段叫 `ratio`**。文档明说 `size` 只是"客户端兼容字段，建议优先用 ratio"，
     发 aspect_ratio 没用（那是别家的写法）。
  3. 参考图在 JSON 里是 **URL 数组**；本地图片要走 **multipart**（同一个 `images`
     字段重复多次）。本类会自动判断：拿到 data URI 就解码成字节走 multipart，
     拿到链接就走 JSON —— 所以配不配对象存储都能用。

计费：`seed-2.0` 固定 $1.2/次，5～15 秒同价（所以默认给 15 秒，别浪费）。
"""

from __future__ import annotations

import base64
from typing import Callable, Optional

from ..apiutil import ApiError, extract_image_items, extract_task_id, extract_video_url
from .base import ImageTask, Provider, VideoTask

VIDEO_MODELS = ["seed-2.0"]
IMAGE_MODELS = ["seed-image-1.0"]

# 文档列的两套比例（图片没有 21:9，视频没有 2:3）
IMAGE_RATIOS = ["1:1", "2:3", "3:4", "4:3", "9:16", "16:9"]
VIDEO_RATIOS = ["1:1", "3:4", "4:3", "9:16", "16:9", "21:9"]

_RATIO_VALUES = {"21:9": 21 / 9, "16:9": 16 / 9, "4:3": 4 / 3, "1:1": 1.0,
                 "3:4": 3 / 4, "2:3": 2 / 3, "9:16": 9 / 16}


def _to_ratio(want: str, allowed: list, default: str) -> str:
    """'9:16' 直接用；'1024x1536' 这种像素换算成最接近的比例（这家只认比例）。"""
    s = (want or "").strip().lower().replace("×", "x")
    if s in allowed:
        return s
    val = _RATIO_VALUES.get(s, 0.0)
    if not val:
        try:
            w, h = s.split("x")[:2]
            val = int(w) / int(h)
        except Exception:                                   # noqa: BLE001
            return default
    return min(allowed, key=lambda r: abs(_RATIO_VALUES[r] - val))


def _data_uri_to_bytes(ref: str) -> tuple:
    """data:image/png;base64,xxx → (bytes, filename, content_type)。不是 data URI 返回 None。"""
    if not ref.startswith("data:"):
        return ()
    head, _, payload = ref.partition(",")
    ctype = head[5:].split(";")[0] or "image/jpeg"
    ext = {"image/png": "png", "image/webp": "webp"}.get(ctype, "jpg")
    try:
        return (base64.b64decode(payload), f"ref.{ext}", ctype)
    except Exception:                                       # noqa: BLE001
        return ()


class M86Provider(Provider):
    id = "m86"
    name = "M86 / New API yiyun.xiaoge.uk"
    aliases = ("newapi", "yiyun", "xiaoge", "seed")
    default_base_url = "https://yiyun.xiaoge.uk"
    supports = ("image", "video")
    # 视频：本地图解码成字节走 multipart、公网链接走 JSON —— 两种都行，所以是 data_uri。
    # 图片：ref_images 字段**只收公网链接**，见下面的 needs_url。
    ref_mode = "data_uri"

    def needs_url(self, model: str = "", media: str = "image") -> bool:
        # 出图的 ref_images 只认链接。不声明的话，没配对象存储时解析器会给
        # data URI，然后被 generate_image 丢掉 —— 图照出但没有参考图，
        # 状态资产的脸就不是父资产本人了，而且任务标 ok 没人知道。
        return media == "image"

    def capabilities(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "default_base_url": self.default_base_url,
            "supports": list(self.supports),
            "image": {
                "models": IMAGE_MODELS,
                "default_model": "seed-image-1.0",
                # 这家的 size 就是比例，直接把比例当尺寸给前端选
                "sizes": IMAGE_RATIOS,
                "default_size": "9:16",
                "max_refs": 9,
                "ref_mode": "url",
                "notes": "同步出图（无需轮询）。**size 填比例**不是像素，给像素会自动换算。"
                         "参考图字段是 ref_images，只收公网链接、且模型支持时才生效。",
            },
            "video": {
                "models": VIDEO_MODELS,
                "default_model": "seed-2.0",
                "ratios": VIDEO_RATIOS,
                "durations": [5, 10, 15],
                "default_duration": 15,
                "resolutions": [""],
                "max_refs": 9,
                "ref_mode": "data_uri",
                "notes": "比例字段是 **ratio**（不是 aspect_ratio）。本地参考图自动走 multipart 上传，"
                         "公网链接走 JSON。计费固定 $1.2/次，5～15 秒同价，默认给满 15 秒。",
            },
            "notes": "OpenAI 兼容站。对话模型（seed-chat/glm-5.2/claude-sonnet-5）可在 LLM 设置里直接用。",
        }

    # ---------------------------------------------------------------- image
    def generate_image(self, task: ImageTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 900) -> dict:
        model = task.model or "seed-image-1.0"
        ratio = _to_ratio(task.size, IMAGE_RATIOS, "9:16")
        body = {
            "model": model,
            "prompt": task.prompt,
            "size": ratio,                       # 这家的 size = 比例
            "n": int(task.n or 1),
            "response_format": "url",
        }
        # ref_images 文档写明是 URL 数组，本地图（data URI）它不收。
        # 丢了不能只 log 一句照样出图 —— 状态资产要靠父资产与依赖资产定身份，少一张出来
        # 就不是同一个人，而且任务标 ok 没人知道。报错让优先级链换下一家。
        urls = [r for r in (task.refs or []) if not r.startswith("data:")]
        dropped = len(task.refs or []) - len(urls)
        if dropped:
            raise ApiError(
                f"M86 出图的 ref_images 只收公网链接，这一项给的 {dropped} 张是本地图。"
                f"本该有 {len(task.refs)} 张参考图，能用的只有 {len(urls)} 张 —— "
                f"少了参考图出来的就不是同一个人/同一个东西，所以不出这张图。"
                f"去「设置 → 参考图上传」配对象存储（配好后本机图会自动传成链接），"
                f"或者把这类活排给收本地图的服务商。",
                status=0, kind="task_fatal")
        if urls:
            body["ref_images"] = urls[:9]

        data = self.session.request("POST", "/v1/images/generations", json_body=body,
                                    retries=2, timeout=600)
        items = extract_image_items(data)
        if not items:
            raise ApiError(f"出图没返回可用结果: {str(data)[:300]}")
        self.session.save_item(items[0], dest)
        return {"task_id": extract_task_id(data), "source": items[0][:200],
                "provider": self.id, "model": model}

    # ---------------------------------------------------------------- video
    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 10, poll_timeout: int = 2400) -> dict:
        model = task.model or "seed-2.0"
        ratio = _to_ratio(task.ratio, VIDEO_RATIOS, "9:16")
        sec = int(task.duration or 15)
        if not 1 <= sec <= 15:
            log(f"M86 {model} 时长按 1–15 秒处理，已把 {sec} 收敛到 15")
            sec = 15
        refs = list(task.refs or [])[:9]

        fields = {"model": model, "prompt": task.prompt, "seconds": str(sec), "ratio": ratio}
        local = [b for b in (_data_uri_to_bytes(r) for r in refs) if b]

        if local:
            # 本地图 → multipart，同一个 images 字段重复多次（文档示例就是这么写的）
            files = [(k, (None, v)) for k, v in fields.items()]
            for i, (blob, fname, ctype) in enumerate(local, start=1):
                files.append(("images", (f"frame_{i:02d}.{fname.rsplit('.', 1)[-1]}", blob, ctype)))
            log(f"M86 视频：{len(local)} 张本地参考图走 multipart，ratio={ratio} seconds={sec}")
            data = self.session.request("POST", "/v1/videos", files=files, retries=2, timeout=300)
        else:
            body = dict(fields)
            urls = [r for r in refs if r.startswith("http")]
            if urls:
                body["images"] = urls
            log(f"M86 视频：ratio={ratio} seconds={sec} 参考图={len(urls)} 张(URL)")
            data = self.session.request("POST", "/v1/videos", json_body=body,
                                        retries=2, timeout=300)

        url = extract_video_url(data)
        task_id = extract_task_id(data)
        if not url:
            if not task_id:
                raise ApiError(f"提交没返回视频地址也没返回 task_id: {str(data)[:300]}")
            url = self.session.poll("/v1/videos/{id}", task_id, picker=extract_video_url,
                                    interval=poll_interval, timeout=poll_timeout,
                                    content_path_tpl="/v1/videos/{id}/content",
                                    log=log, cancel=cancel)
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id, "model": model}
