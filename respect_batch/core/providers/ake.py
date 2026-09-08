# -*- coding: utf-8 -*-
"""阿珂 snumom.com 统一视频 API。

文档版本：用户提供的《snumom 视频 API》（2026-08-30）。

  · 创建 POST /v1/videos
  · 查询 GET  /v1/videos/{task_id}
  · 下载 GET  /v1/videos/{task_id}/content

统一协议的重要约束：seconds 是字符串；图片/视频/音频都是带 url 的对象数组；
aspect_ratio 与 size 分开。万相 3.0 的提示词增强默认开启，参考图顺序对应“图1、图2”。
"""

from __future__ import annotations

from typing import Callable, Optional

from ..apiutil import ApiError, extract_task_id, extract_video_url, extract_image_items
from .base import Provider, VideoTask, ImageTask

VIDEO_MODELS = [
    "sd2.0", "sd-2.5", "minimax_h3-1080p", "minimax_h3-2K",
    "minimax_h3-768p", "grok-imagine-video-1.5（按次）",
    "wan3.0-video", "wan3.0-video-prime", "wan3.0-image", "wan3.0-image-prime",
    "grok-imagine-video-1.5", "grok-imagine-video-1.5-preview", "wan-3.0",
]
RATIOS = ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9", "adaptive"]
RESOLUTIONS = ["", "480P", "720P", "1080P"]


def _remote(ref: str) -> bool:
    return str(ref or "").startswith(("http://", "https://"))


def _duration(model: str, want: int) -> int:
    if model == 'sd-2.5':
        return 30
    if model == 'sd2.0':
        return min(15, max(5, int(want or 8)))
    sec = int(want or 5)
    if model.startswith("wan3.0-"):
        return min(30, max(2, sec))
    if model == "wan-3.0":
        return min(60, max(1, sec))
    if model.startswith("grok-imagine-video-1.5"):
        return min(15, max(4, sec))
    if model.startswith("minimax_h3-"):
        return min(15, max(4, sec))
    return min(10, max(4, sec)) if "h3" in model.lower() else max(1, sec)


def _limits(model: str) -> tuple[int, int, int]:
    """返回图片/视频/音频上限。0 表示该类素材不支持。"""
    if model == 'sd2.0':
        return 9, 3, 3
    if model == 'sd-2.5':
        return 10, 0, 0
    if model.startswith("wan3.0-video"):
        return 10, 5, 5
    if model.startswith("wan3.0-image"):
        return 10, 0, 5
    if model == "wan-3.0":
        return 9, 3, 3
    if model.startswith("grok-imagine-video-1.5"):
        return 7, 0, 0
    if model.startswith("minimax_h3-"):
        return 9, 3, 3
    return 4, 0, 0


class AkeProvider(Provider):
    id = "ake"
    name = "阿珂 snumom.com"
    aliases = ("snumom", "阿珂", "ako")
    default_base_url = "https://snumom.com"
    supports = ("image", "video")
    # 文档的三类 reference_* 都要求服务端可访问的 URL。
    ref_mode = "url"

    def capabilities(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "default_base_url": self.default_base_url,
            "supports": list(self.supports),
            # 2026-09-08 官方 /api/pricing：该模型仅文生图 1K，openai 端点。
            "image": {"models": ["grok-imagine-image-quality-lite"],
                "default_model": "grok-imagine-image-quality-lite", "max_refs": 0,
                "sizes": [], "ref_mode": "url", "notes": "Grok 图片模型仅支持文生图 1K，不支持参考图。"},
            "video": {
                "models": VIDEO_MODELS,
                "default_model": "wan3.0-video",
                "ratios": RATIOS,
                "durations": list(range(2, 31)),
                "default_duration": 15,
                "resolutions": RESOLUTIONS,
                "max_refs": 10,
                "ref_mode": "url",
                "model_options": {
                    "sd2.0": {"durations": list(range(5, 16)), "default_duration": 8,
                        "max_refs": 9, "resolutions": [""], "default_ratio": "16:9"},
                    "sd-2.5": {"durations": [30], "default_duration": 30,
                        "max_refs": 10, "resolutions": ["720p"], "default_ratio": "16:9"},
                    "minimax_h3-1080p": {"durations": list(range(4, 16)), "default_duration": 5,
                        "max_refs": 9, "resolutions": ["1920x1080"]},
                    "minimax_h3-2K": {"durations": list(range(4, 16)), "default_duration": 5,
                        "max_refs": 9, "resolutions": ["2K"]},
                    "minimax_h3-768p": {"durations": list(range(4, 16)), "default_duration": 5,
                        "max_refs": 9, "resolutions": ["768P"]},
                    "grok-imagine-video-1.5（按次）": {"durations": list(range(4, 16)),
                        "max_refs": 7, "resolutions": ["480P", "720P", "1080P"]},
                    "wan3.0-video": {"durations": list(range(2, 31)), "max_refs": 10},
                    "wan3.0-video-prime": {"durations": list(range(2, 31)), "max_refs": 10},
                    "wan3.0-image": {"durations": list(range(2, 31)), "max_refs": 10},
                    "wan3.0-image-prime": {"durations": list(range(2, 31)), "max_refs": 10},
                    "grok-imagine-video-1.5": {
                        "durations": list(range(4, 16)), "max_refs": 7},
                    "grok-imagine-video-1.5-preview": {
                        "durations": list(range(4, 16)), "max_refs": 7},
                    "wan-3.0": {"durations": list(range(1, 61)), "max_refs": 9},
                },
                "notes": "seconds 必须按字符串发送；reference_images 是 {url,role?} 对象数组。"
                         "wan3.0-video* 支持 10 图/5 视频/5 音频，wan3.0-image* 不支持参考视频；"
                         "Grok 最多 7 图且不支持视频/音频。万相 3.0 未指定 size 时默认 1080P。",
            },
            "notes": "模型清单最终以控制台和 GET /v1/models 为准。万相创建时预扣，"
                     "必须显式传 seconds，不能用 -1 智能时长。",
        }

    def generate_image(self, task: ImageTask, dest: str, *, log: Callable = print,
                       cancel=None, **kwargs) -> dict:
        if task.refs:
            raise ApiError('此模型只支持文生图，不支持参考图', status=0, kind='task_fatal')
        model = task.model or 'grok-imagine-image-quality-lite'
        data = self.session.request('POST', '/v1/chat/completions', json_body={
            'model': model, 'messages': [{'role': 'user', 'content': task.prompt}],
            'stream': False}, retries=1, timeout=600)
        items = extract_image_items(data)
        if not items:
            raise ApiError('图片接口没有返回可下载图片')
        self.session.save_item(items[0], dest)
        return {'provider': self.id, 'model': model}

    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 2400) -> dict:
        model = (task.model or "wan3.0-video").strip()
        sec = _duration(model, task.duration)
        if sec != int(task.duration or 5):
            log(f"阿珂 {model} 时长范围有限，已把 {task.duration} 秒收敛为 {sec} 秒")

        img_max, video_max, audio_max = _limits(model)
        refs = list(task.refs or [])
        bad = [r for r in refs if not _remote(r)]
        if bad:
            raise ApiError(
                f"阿珂 reference_images 只收公网 URL；本任务有 {len(bad)} 张不是公网链接。"
                "请在设置里配置参考图对象存储，不能少图后继续生成。",
                status=0, kind="task_fatal")
        if len(refs) > img_max:
            raise ApiError(f"阿珂 {model} 最多 {img_max} 张参考图，本任务有 {len(refs)} 张；"
                           "不能静默裁图，否则人物/场景绑定会丢失。",
                           status=0, kind="task_fatal")

        videos = list(task.extra.get("video_refs") or task.extra.get("videos") or [])
        audios = list(task.extra.get("audio_refs") or task.extra.get("audios") or [])
        if videos and not video_max:
            raise ApiError(f"阿珂 {model} 不支持参考视频", status=0, kind="task_fatal")
        if audios and not audio_max:
            raise ApiError(f"阿珂 {model} 不支持参考音频", status=0, kind="task_fatal")
        if len(videos) > video_max or len(audios) > audio_max:
            raise ApiError(f"阿珂 {model} 素材超限：视频 {len(videos)}/{video_max}，"
                           f"音频 {len(audios)}/{audio_max}", status=0, kind="task_fatal")
        if any(not _remote(r) for r in videos + audios):
            raise ApiError("阿珂参考视频/音频也必须是公网 URL", status=0, kind="task_fatal")

        body: dict = {"model": model, "prompt": task.prompt or "", "seconds": str(sec)}
        if task.resolution:
            body["size"] = task.resolution.upper().replace("X", "x")
        if task.ratio:
            body["aspect_ratio"] = task.ratio
        if refs:
            roles = list(task.extra.get("image_roles") or [])
            body["reference_images"] = [
                dict({"url": ref}, **({"role": roles[i]} if i < len(roles) and roles[i] else {}))
                for i, ref in enumerate(refs)
            ]
        if videos:
            durations = list(task.extra.get("video_durations") or [])
            body["reference_videos"] = [
                dict({"url": ref}, **({"duration": durations[i]}
                                      if i < len(durations) and durations[i] else {}))
                for i, ref in enumerate(videos)
            ]
        if audios:
            body["reference_audios"] = [{"url": ref} for ref in audios]
        if model.startswith("wan3.0-") and "prompt_extend" in task.extra:
            body["prompt_extend"] = bool(task.extra["prompt_extend"])

        # 官方 2026-09-08 文档：这两条新线路使用独立的扁平参考字段。
        if model == 'sd2.0':
            body = {'model': model, 'prompt': task.prompt or '', 'duration': sec,
                    'aspect_ratio': task.ratio or '16:9'}
            for field, values in [('image_refs', refs), ('video_refs', videos), ('audio_refs', audios)]:
                if values:
                    body[field] = values
            if audios and not (refs or videos):
                raise ApiError('sd2.0 音频必须搭配图片或视频', status=0, kind='task_fatal')
        elif model == 'sd-2.5':
            body = {'model': model, 'prompt': task.prompt or '', 'images': refs,
                    'resolution': '720p', 'aspect_ratio': task.ratio or '16:9'}

        log(f"阿珂 {model}: seconds='{sec}' size={body.get('size', '默认')} "
            f"aspect_ratio={body.get('aspect_ratio', '默认')} "
            f"图{len(refs)}/视频{len(videos)}/音频{len(audios)}")
        data = self.session.request("POST", "/v1/videos", json_body=body,
                                    # 创建接口没有幂等键，网络层不能自动重发，否则可能重复扣费。
                                    retries=1, timeout=300)
        task_id = extract_task_id(data)
        url = extract_video_url(data)
        if not url:
            if not task_id:
                raise ApiError(f"提交没返回任务 ID: {str(data)[:300]}")
            url = self.session.poll("/v1/videos/{id}", task_id, picker=extract_video_url,
                                    content_path_tpl="/v1/videos/{id}/content",
                                    interval=poll_interval, timeout=poll_timeout,
                                    log=log, cancel=cancel)
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id, "model": model}
