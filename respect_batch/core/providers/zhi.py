# -*- coding: utf-8 -*-
"""智（zhi168.it.com）—— 图 + 视频都做，走积分计费。

和别家差异最大的三点（2026-08 文档）：

  1. **鉴权是 `X-API-Key` 头**，不是 Bearer —— 这也是 HttpSession 加
     auth_style 的原因。
  2. **模型不是名字，是数字 ID**（`model_code`，整数），而且**按账号分配**：
     你账号里有哪些模型、ID 是几，得用 Key 调
     `GET /api/v1/available-models` 才知道（模型展示页也行）。
     所以前端的模型框是自由输入 —— 填数字 ID（如 37）。启动前有校验：
     填错了会在「跑之前检查」里拦下，不用等几百步之后才 422。
  3. 素材全收 `*_urls` 公网数组：参考图 `reference_image_urls`（图片最多 8 张）、
     音频 `audio_urls`、视频 `video_urls` —— 单张参考图也用数组，没有
     input_reference 那种单数字段。

接口形状：
  POST /api/v1/video-tasks   GET /api/v1/video-tasks/{id}
  POST /api/v1/image-tasks   GET /api/v1/image-tasks/{id}
  响应 {task_id:18, status:"processing", estimated_points:"80.0000", result_url:""}
  成功后 result_url 给成品；没有单独的 content 下载端点。

状态：pending / submitted / processing 生成中；succeeded 成功；
failed / canceled 失败 —— 全在 apiutil 的终态表里，轮询层照常工作。

计费：创建时冻结积分，成功确认扣费、失败自动释放；**视频按提交的
duration_seconds 计费，不按实际成片秒数** —— 时长别乱填大的。
图片 prompt 要大于 6 个字（上游 422 硬校验）。
"""

from __future__ import annotations

from typing import Callable, Optional

from ..apiutil import ApiError, extract_task_id, extract_video_url
from .base import ImageTask, Provider, VideoTask

# 图片参考图上限 8 张（文档「创建图片任务」字段表）；视频侧文档没写上限，不裁。
IMAGE_MAX_REFS = 8


def model_code(model: str) -> int:
    """模型框里的值 → 这家的整数 model_code。

    前端是自由输入框（这家的模型是账号分配的数字 ID，静态列表给不了），
    所以这里负责说清「填错了」—— 越早说清越好，422 排查起来毫无线索。
    """
    s = str(model or "").strip()
    try:
        return int(s)
    except ValueError:
        raise ApiError(
            f"「{s or '（空）'}」不是这家认的模型 —— 智（zhi168）的模型是"
            f"**数字 ID**（如 37）。拿 Key 调 GET /api/v1/available-models，"
            f"或去网页端的模型展示页，看你账号里分配了哪些 ID。",
            status=0, kind="task_fatal")


def _ratio_of(size: str) -> str:
    """内部尺寸（如 1024x1536）→ 这家图片接口要的 aspect_ratio。

    图片接口没有 size 字段、按模型配置收比例；文档给的例子是
    auto / 1:1 / 16:9 / 9:16。归到最近的一档（比例差不多就行，
    具体可用哪些以模型配置为准，上游不认会 422 说清）。
    """
    try:
        w, h = (int(x) for x in str(size or "").lower().split("x")[:2])
    except (ValueError, TypeError):
        return "1:1"
    if w >= h * 1.2:
        return "16:9"
    if h >= w * 1.2:
        return "9:16"
    return "1:1"


class ZhiProvider(Provider):
    id = "zhi"
    name = "智 zhi168.it.com（图 + 视频）"
    aliases = ("智", "zhi168", "zhi168.it.com")
    default_base_url = "https://www.zhi168.it.com"
    supports = ("image", "video")
    # 素材全收 *_urls 公网数组（本机图得先配对象存储）
    ref_mode = "url"

    def __init__(self, api_key: str = "", base_url: str = "", proxy: str = "",
                 timeout: int = 900):
        super().__init__(api_key, base_url, proxy, timeout)
        # 这家不用 Bearer —— 文档明确 X-API-Key 头
        self.session.auth_style = "x-api-key"

    def capabilities(self) -> dict:
        note = ("模型是**账号分配的数字 ID**（如 37）—— 在模型框直接填数字，"
                "拿 Key 调 GET /api/v1/available-models 或看网页端模型展示页。"
                "跑之前的检查会核对这个 ID 在不在你账号里。")
        return {
            "id": self.id,
            "name": self.name,
            "default_base_url": self.default_base_url,
            "supports": list(self.supports),
            "video": {
                "models": [],              # 动态：按账号分配，见 note
                "default_model": "",
                "ratios": ["9:16", "16:9", "1:1", "4:3", "3:4"],
                "durations": [4, 5, 6, 8, 10, 12, 15, 20, 30, 60],
                "default_duration": 10,
                "resolutions": ["720p", "1080p"],
                "max_refs": IMAGE_MAX_REFS,
                "ref_mode": "url",
                "notes": note + " 比例/清晰度按模型配置可选；时长 1–300 秒。"
                         "参考素材全收公网 URL 数组（reference_image_urls /"
                         " audio_urls / video_urls），无首尾帧专用字段。"
                         "**按提交的时长计费，不按实际成片秒数** —— 时长别乱填大的。",
            },
            "image": {
                "models": [],              # 动态：按账号分配，见 note
                "default_model": "",
                "sizes": ["1024x1536", "1536x1024", "1024x1024"],
                "default_size": "1024x1536",
                "max_refs": IMAGE_MAX_REFS,
                "ref_mode": "url",
                "notes": note + " 尺寸会自动换成比例（竖→9:16 横→16:9 方→1:1），"
                         "具体可用比例以模型配置为准。参考图最多 8 张，"
                         "必须是公网 URL。prompt 要大于 6 个字。每次 1 张。",
            },
            "notes": "积分计费：创建冻结、成功扣费、失败退还。"
                     "素材 URL 必须是服务端可访问的公网地址。",
        }

    # ------------------------------------------------------------ 模型清单
    def list_models(self) -> list:
        """拉**你账号里**分配到的模型（数字 ID 字符串，图和视频混在一起）。

        这家的模型不是全局的 —— 账号 A 有 37、账号 B 未必。所以启动前的
        模型校验靠这里：填的 ID 不在你账号里，跑之前就会拦下。
        """
        data = self.session.request("GET", "/api/v1/available-models",
                                    retries=1, timeout=30)
        rows = data if isinstance(data, list) else ((data or {}).get("data") or [])
        return sorted(str(m.get("id")) for m in rows
                      if isinstance(m, dict) and m.get("id") is not None)

    # ---------------------------------------------------------------- video
    def build_video_body(self, task: VideoTask) -> dict:
        refs = [r for r in (task.refs or [])
                if str(r).startswith(("http://", "https://"))]
        vids = [v for v in (task.extra.get("video_refs") or task.extra.get("videos") or [])
                if str(v).startswith(("http://", "https://"))]
        auds = [a for a in (task.extra.get("audio_refs") or task.extra.get("audios") or [])
                if str(a).startswith(("http://", "https://"))]
        body: dict = {
            "model_code": model_code(task.model),
            "prompt": task.prompt or "",
            "aspect_ratio": task.ratio or "9:16",
            "resolution": (task.resolution or "").strip().lower() or "720p",
            # 按提交值计费 —— 夹在 1-300，别让一次手滑烧穿积分
            "duration_seconds": max(1, min(300, int(task.duration or 10))),
        }
        if refs:
            body["reference_image_urls"] = refs
        if vids:
            body["video_urls"] = vids
        if auds:
            body["audio_urls"] = auds
        # with_audio 不发：默认 false。要配音用 audio_urls 传素材，
        # 但成片要不要声音由它控制 —— 流水线出的是无声分段，不动它。
        return body

    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 10, poll_timeout: int = 3600) -> dict:
        model = str(task.model or "").strip()
        body = self.build_video_body(task)
        log(f"智 模型{body['model_code']} → POST /api/v1/video-tasks"
            f"（{body['aspect_ratio']} {body['resolution']} {body['duration_seconds']}s）")
        data = self.session.request("POST", "/api/v1/video-tasks",
                                    json_body=body, retries=2, timeout=300)
        url = extract_video_url(data)
        task_id = extract_task_id(data)
        if not url:
            if not task_id:
                raise ApiError(f"提交没返回任务 ID: {str(data)[:300]}")
            # 没有单独的 content 端点 —— 成品就在查询响应的 result_url 里
            url = self.session.poll("/api/v1/video-tasks/{id}", task_id,
                                    picker=extract_video_url,
                                    interval=poll_interval, timeout=poll_timeout,
                                    log=log, cancel=cancel)
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id, "model": model}

    # ---------------------------------------------------------------- image
    def build_image_body(self, task: ImageTask) -> dict:
        refs = [r for r in (task.refs or []) if str(r).startswith(("http://", "https://"))]
        body: dict = {
            "model_code": model_code(task.model),
            "prompt": task.prompt or "",
            "aspect_ratio": _ratio_of(task.size),
            "image_count": 1,               # 异步接口固定 1，多张要多次提交
        }
        if refs:
            body["reference_image_urls"] = refs[:IMAGE_MAX_REFS]
        return body

    def generate_image(self, task: ImageTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 900) -> dict:
        model = str(task.model or "").strip()
        body = self.build_image_body(task)
        log(f"智 模型{body['model_code']} → POST /api/v1/image-tasks"
            f"（{body['aspect_ratio']} 参考图{len(body.get('reference_image_urls', []))}张）")
        data = self.session.request("POST", "/api/v1/image-tasks",
                                    json_body=body, retries=2, timeout=300)
        url = extract_video_url(data)
        task_id = extract_task_id(data)
        if not url:
            if not task_id:
                raise ApiError(f"提交没返回任务 ID: {str(data)[:300]}")
            url = self.session.poll("/api/v1/image-tasks/{id}", task_id,
                                    picker=extract_video_url,
                                    interval=poll_interval, timeout=poll_timeout,
                                    log=log, cancel=cancel)
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id, "model": model}
