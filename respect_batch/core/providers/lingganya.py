# -*- coding: utf-8 -*-
"""灵感鸭（www.lingganyaapi.com）。提交 → 查询 → 取成品。

注意两个端点的 async 参数不一样：**图片带 `?async=true`、视频不带**。
这家的统一文档写明所有任务默认异步、async 非必需；但图片那页文档标了必填。
"""

from __future__ import annotations

import json
from typing import Callable, Optional

from ..apiutil import ApiError, extract_image_items, extract_task_id, extract_video_url
from .base import ImageTask, Provider, VideoTask

# 视频模型：照该站「模型表」原样。
# 注意 veo 是下划线 veo_3_1_fast，和零视那边的 veo_3_1-fast 不一样，别互相抄。
VIDEO_MODELS = [
    "sd-2.0", "sd-fast", "sd-2.0-special", "sd-fast-special",
    "grok-imagine-video-1.5-preview", "grok-video-1.5-special", "grok-image-video-special",
    "gemini_omni_flash", "gemini-omni-flash-special",
    "veo_3_1_fast", "veo_3_1_fast_hd", "veo_3_1_fast_fl_hd",
    "sora-2", "sora-2-pro", "sora-2-vip",
]

# 每个模型的硬约束。seconds 是**固定档位**不是任意值——这是最容易踩的坑：
# 程序默认 duration=15，直接发给 sora-2（只收 4/8/12）或 veo（只收 8）就是 400。
VIDEO_SPECS: dict = {
    "sora-2": {"seconds": [4, 8, 12], "max_images": 1},
    "sora-2-pro": {"seconds": [12], "max_images": 1},
    "sora-2-vip": {"seconds": [12], "max_images": 1},
    "gemini_omni_flash": {"seconds": [10], "max_images": 7},
    "gemini-omni-flash-special": {"seconds": [10], "max_images": 7},
    "veo_3_1_fast": {"seconds": [8], "max_images": 3},
    "veo_3_1_fast_hd": {"seconds": [8], "max_images": 3},
    "veo_3_1_fast_fl_hd": {"seconds": [8], "max_images": 2},
    "grok-imagine-video-1.5-preview": {"seconds": [10, 15], "max_images": 1, "need_image": True},
    "grok-video-1.5-special": {"seconds": [10, 15], "max_images": 1, "need_image": True},
    "grok-image-video-special": {"seconds": [10, 15], "max_images": 7},
    # SD 系：resolution 顶层必填；有 images 时 extra.reference_mode 必填（media / frame）
    # frame 模式只能 2 张（首帧+尾帧），media 模式最多 9 张
    "sd-2.0": {"seconds": list(range(4, 16)), "max_images": 9,
               "resolution": ["1080p", "720p"], "ref_mode": True},
    "sd-fast": {"seconds": list(range(4, 16)), "max_images": 9,
                "resolution": ["720p", "480p"], "ref_mode": True},
    "sd-2.0-special": {"seconds": list(range(5, 16)), "max_images": 9,
                       "resolution": ["1080p", "720p"], "ref_mode": True},
    "sd-fast-special": {"seconds": list(range(5, 16)), "max_images": 9,
                        "resolution": ["720p", "480p"], "ref_mode": True},
}

IMAGE_MODELS = ["gpt-image-2", "gpt-image-2-special", "gpt-image-2-4k",
                "nano_banana_2", "nano_banana_pro"]


def brief_body(body: dict) -> str:
    """把请求体压成一行：base64 和长串截断。出 400 时对着这个查参数。"""
    def shrink(v):
        if isinstance(v, str):
            if v.startswith("data:"):
                return f"<{v.split(',', 1)[0]} {len(v)}字符>"
            return v if len(v) <= 80 else v[:77] + "…"
        if isinstance(v, list):
            return [shrink(x) for x in v]
        if isinstance(v, dict):
            return {k: shrink(x) for k, x in v.items()}
        return v
    return json.dumps({k: shrink(v) for k, v in body.items()}, ensure_ascii=False)


def self_check(body: dict) -> list:
    """按真实模型表逐条自检，生成「该查什么」清单。

    这家的 400 只回一句「生成内容或参数不符合要求」，什么都看不出来。
    与其让人干瞪眼，不如把我们知道的硬约束逐条比一遍，指出到底哪一项不合。
    """
    model = str(body.get("model") or "")
    spec = VIDEO_SPECS.get(model)
    tips = []
    if model and spec is None:
        tips.append(f"model={model} 不在这家的模型表里。视频可用的是："
                    f"{'、'.join(list(VIDEO_SPECS)[:8])} 等")
    elif spec:
        if str(body.get("seconds")) not in [str(s) for s in spec["seconds"]]:
            tips.append(f"时长 {body.get('seconds')} 不是 {model} 的合法档位，只能 {spec['seconds']}")
        imgs = body.get("images") or []
        if len(imgs) > spec["max_images"]:
            tips.append(f"参考图 {len(imgs)} 张超上限：{model} 最多 {spec['max_images']} 张")
        if spec.get("need_image") and not imgs:
            tips.append(f"{model} 必须带至少 1 张参考图")
        if not spec.get("resolution") and body.get("resolution"):
            tips.append(f"{model} 不该带 resolution 字段（只有 sd-* 系需要）")
        if spec.get("ref_mode") and imgs:
            mode = str((body.get("extra") or {}).get("reference_mode") or "")
            if mode not in ("media", "frame"):
                tips.append(f"{model} 有参考图时必须说明参考方式："
                            f"media（素材参考）或 frame（首尾帧）")
            elif mode == "frame" and len(imgs) != 2:
                tips.append(f"参考方式选了 frame（首尾帧）就要正好 2 张图，当前 {len(imgs)} 张")
    tips.append("也可能是提示词或参考图被内容审核拦下了（报错里「生成内容」排在最前面就是）"
                "——把露骨的词换成中性说法，或换一张参考图")
    tips.append("模型名的写法各家不同：这家是 veo_3_1_fast（下划线）、gemini_omni_flash，"
                "别照抄别家网关的写法")
    return tips


def fit_video(body: dict, log=print) -> dict:
    """按模型规格纠正请求体：seconds 吸附到合法档位、参考图裁到上限、缺图报错。

    宁可自动纠正 + 明确记一行日志，也不要把明知不合法的参数发出去换一个 400。
    自定义模型名（不在表里）原样放过，交给服务端判断。
    """
    model = str(body.get("model") or "")
    spec = VIDEO_SPECS.get(model)
    if not spec:
        return body

    allowed = spec["seconds"]
    try:
        sec = int(str(body.get("seconds")))
    except Exception:                                   # noqa: BLE001
        sec = allowed[-1]
    if sec not in allowed:
        near = min(allowed, key=lambda a: abs(a - sec))
        log(f"灵感鸭 {model} 的时长只能是 {allowed} 秒，已把 {sec} 纠正为 {near}")
        sec = near
    # sd 系文档要整数，其余按官方示例给字符串（两者都被接受，保持与示例一致）
    body["seconds"] = sec if model.startswith("sd") else str(sec)

    imgs = body.get("images") or []
    cap = spec["max_images"]
    if spec.get("ref_mode") and imgs:
        extra = body.setdefault("extra", {})
        mode = str(extra.get("reference_mode") or "").strip().lower()
        if mode not in ("media", "frame"):
            mode = "frame" if len(imgs) == 2 else "media"
            log(f"灵感鸭 {model} 带参考图时必须说明参考方式，已自动填 {mode}"
                f"（frame=首尾帧 / media=素材参考）")
        extra["reference_mode"] = mode
        if mode == "frame":
            cap = 2
    if len(imgs) > cap:
        log(f"灵感鸭 {model} 最多 {cap} 张参考图，已裁掉多余 {len(imgs) - cap} 张")
        body["images"] = imgs[:cap]
    if spec.get("need_image") and not body.get("images"):
        raise ApiError(f"灵感鸭 {model} 必须给至少 1 张参考图，"
                       f"但这个任务一张都没有。检查环节6 的资产绑定，或换一个模型。")

    # resolution 只有 sd 系需要且必填；其余模型不该带
    res_allowed = spec.get("resolution")
    if res_allowed:
        if str(body.get("resolution") or "") not in res_allowed:
            log(f"灵感鸭 {model} 的分辨率只能 {res_allowed}，已设为 {res_allowed[0]}")
            body["resolution"] = res_allowed[0]
    else:
        body.pop("resolution", None)
    return body


class LingganyaProvider(Provider):
    id = "lingganya"
    name = "灵感鸭 lingganyaapi.com"
    default_base_url = "https://www.lingganyaapi.com"
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
                "max_refs": 9,
                "ref_mode": "data_uri",
                "notes": "size 是像素。参考图官方要 URL，data URI 实测可用。",
            },
            "video": {
                "models": VIDEO_MODELS,
                "default_model": "sd-2.0",
                "ratios": ["9:16", "16:9", "1:1", "4:3", "3:4"],
                "durations": [4, 5, 8, 10, 12, 15],
                "default_duration": 12,
                "resolutions": ["", "1080p", "720p", "480p"],
                "max_refs": 9,
                "ref_mode": "data_uri",
                "notes": "每个模型的时长是固定档位不是随便填：sora-2 只有 4/8/12、"
                         "veo 只有 8、gemini 只有 10、SD 系 4-15 随意。填错会自动吸附到"
                         "最近的合法值并记一行日志。SD 系带参考图时会自动补 reference_mode"
                         "（2 张=首尾帧 / 多张=素材参考）。"
                         "⚠ sora-2 通道实测极不稳定（随机 task_failed），不建议用于批量。",
            },
            "notes": "图片生产实测稳定；视频建议改用其它服务商。",
        }

    # ---------------------------------------------------------------- image
    def generate_image(self, task: ImageTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 900) -> dict:
        body = {
            "model": task.model or "gpt-image-2",
            "prompt": task.prompt,
            "size": task.size or "1024x1536",
            "n": int(task.n or 1),
        }
        if task.refs:
            body["images"] = task.refs[:9]
        data = self.session.request("POST", "/v1/images/generations", json_body=body,
                                    params={"async": "true"}, retries=2, timeout=300)
        items = extract_image_items(data)
        task_id = extract_task_id(data)
        if not items:
            if not task_id:
                raise ApiError("提交未返回 task_id 或图片")
            items = self.session.poll("/v1/images/{id}", task_id,
                                      picker=extract_image_items,
                                      interval=poll_interval, timeout=poll_timeout,
                                      content_path_tpl="/v1/images/{id}/content",
                                      log=log, cancel=cancel)
        self.session.save_item(items[0], dest)
        return {"task_id": task_id, "source": items[0][:200], "provider": self.id,
                "model": body["model"]}

    # ---------------------------------------------------------------- video
    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 10, poll_timeout: int = 2400) -> dict:
        model = task.model or "sd-2.0"
        is_sd = model.lower().startswith("sd")
        body = {
            "model": model,
            "prompt": task.prompt,
            "size": task.ratio or "9:16",
            "seconds": int(task.duration),
        }
        if task.refs:
            body["images"] = task.refs[:9]
        res = (task.resolution or "").strip() or ("720p" if is_sd else "")
        if res:
            body["resolution"] = res
        if task.extra.get("reference_mode"):
            body.setdefault("extra", {})["reference_mode"] = task.extra["reference_mode"]
        # 按模型规格纠正：时长吸附档位、参考图裁到上限、该带的字段补上、不该带的去掉
        body = fit_video(body, log=log)
        log(f"提交 {brief_body(body)}")
        try:
            # 视频不带 ?async=true：这家统一文档写明所有任务默认异步、async 非必需。
            # 图片那页文档标了必填，所以图片仍然带 —— 两个端点不一样，别统一。
            data = self.session.request("POST", "/v1/videos", json_body=body,
                                        retries=2, timeout=300)
        except ApiError as exc:
            # 这家的 400 只回一句笼统话，把自检清单挂上去，诊断卡里直接能看到
            exc.extra_fix = self_check(body)
            raise
        url = extract_video_url(data)
        task_id = extract_task_id(data)
        if not url:
            if not task_id:
                raise ApiError("提交未返回 task_id 或视频URL")
            url = self.session.poll("/v1/videos/{id}", task_id, picker=extract_video_url,
                                    interval=poll_interval, timeout=poll_timeout,
                                    content_path_tpl="/v1/videos/{id}/content",
                                    log=log, cancel=cancel)
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id, "model": model}
