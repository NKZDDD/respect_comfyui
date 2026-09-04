# -*- coding: utf-8 -*-
"""零视工坊（zeroapi.ai-ren.cn）。

对齐 respect_comfyui/zeroapi_nodes.py 的四个节点：
  · 图片        POST /v1/images/generations（异步，轮询）；接参考图走 /v1/images/edits
  · Sora/VEO    POST /v1/videos，参考图进 input_reference（多张用 | 分隔）
  · 图生视频    POST /v1/videos，参考图进 image / images[]
  · SD2 新接口  POST /v1/videos，duration+aspect_ratio 必填，**参考素材只收 HTTPS URL**

两个坑是实测踩出来的，别去掉：
  1. 比例必须**显式**发 aspect_ratio + ratio。只给 size 让服务端推断，
     推断失败会静默回落成横屏 16:9 —— 接口不报错，就是画面躺倒了。
  2. seconds 这个字段该站要**字符串**，发数字会 400 invalid_json。
     而 SD2 新接口用的是 duration，且要 int。同名不同型，别混。
"""

from __future__ import annotations

from typing import Callable, Optional

from ..apiutil import (ApiError, extract_image_items, extract_task_id,
                       extract_video_url)
from .base import ImageTask, Provider, VideoTask

# 文档允许的六种比例
RATIOS = ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9"]
_RATIO_VALUES = {"21:9": 21 / 9, "16:9": 16 / 9, "4:3": 4 / 3, "1:1": 1.0,
                 "3:4": 3 / 4, "9:16": 9 / 16}

# Sora/VEO 系：参考图走 input_reference（| 分隔）
SORA_MODELS = ["veo_3_1-fast", "veo_3_1-fast-fl", "sora-2", "sora-2-pro"]
# 图生视频系：参考图走 image / images[]，接受 base64
I2V_MODELS = ["seedance_2_fast_480p", "vad3", "omni_flash", "grok-1.5"]
# Seedance 满血（客服确认 sd2-fast / sd2-pro **共用同一套规格**）：
# duration 只能 5/10/15 且是**字符串**；比例由 **size** 决定（无 aspect_ratio 字段）；
# images 公网链接和 data:base64 都收；固定 720P 专线。
SD2_MODELS = ["sd2-fast", "sd2-pro"]
SD2_DURATIONS = [5, 10, 15]
_SD2_RATIO_TO_SIZE = {"9:16": "720x1280", "16:9": "1280x720", "1:1": "1024x1024",
                      "3:4": "960x1280", "4:3": "1280x960", "21:9": "2560x1080"}

I2V_DURATIONS = [4, 5, 8, 10, 12, 15, 20]


def _ratio_of(want: str) -> str:
    """把 '9:16' 或 '1080x1920' 都归一成官方比例名。认不出返回空串。"""
    s = (want or "").strip().lower().replace("×", "x")
    if s in _RATIO_VALUES:
        return s
    try:
        w, h = s.split("x")[:2]
        val = int(w) / int(h)
    except Exception:                                   # noqa: BLE001
        return ""
    return min(_RATIO_VALUES.items(), key=lambda kv: abs(kv[1] - val))[0]


def _snap(val: int, allowed: list, log: Callable, model: str, field: str) -> int:
    if val in allowed:
        return val
    near = min(allowed, key=lambda a: abs(a - val))
    log(f"零视 {model} 的 {field} 只能是 {allowed}，已把 {val} 纠正为 {near}")
    return near


class ZeroApiProvider(Provider):
    id = "zeroapi"
    name = "零视工坊 zeroapi.ai-ren.cn"
    default_base_url = "https://zeroapi.ai-ren.cn"
    supports = ("image", "video")
    # 全部模型都能直接吃图片内容：Seedance 满血(sd2-*) 经客服确认 images 也收 data:base64，
    # 所以不再把它列进 url_only_models（那是按旧文档写的，会逼用户去配对象存储）。
    url_only_models = ()

    def capabilities(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "default_base_url": self.default_base_url,
            "supports": list(self.supports),
            "image": {
                "models": ["gpt-image-2", "gpt-image-2-4k", "nano_banana_2", "nano_banana_pro"],
                "default_model": "gpt-image-2",
                "sizes": ["1024x1536", "1024x1024", "1536x1024", "2048x2048"],
                "default_size": "1024x1536",
                "max_refs": 9,
                "ref_mode": "data_uri",
                "notes": "异步出图，自动轮询。接了参考图会改走 /v1/images/edits。",
            },
            "video": {
                "models": I2V_MODELS + SORA_MODELS + SD2_MODELS,
                "default_model": "seedance_2_fast_480p",
                "ratios": RATIOS,
                "durations": I2V_DURATIONS,
                "default_duration": 10,
                "resolutions": [""],
                "max_refs": 9,
                "ref_mode": "data_uri",
                "notes": "vad3/omni_flash/grok-1.5/seedance 系：比例显式发 aspect_ratio+ratio"
                         "（只给尺寸让它猜会静默变横屏）。"
                         "sd2-fast / sd2-pro（Seedance 满血）是另一套：比例由 **size** 决定、"
                         "duration 是字符串、images 收链接也收 base64 —— 本地故事板可直接用。",
            },
            "notes": "和 ComfyUI 里的「零视工坊」四个节点同源。",
        }

    # ---------------------------------------------------------------- image
    def generate_image(self, task: ImageTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 900) -> dict:
        model = task.model or "gpt-image-2"
        body = {
            "model": model,
            "prompt": task.prompt,
            "size": task.size or "1024x1536",
            "n": int(task.n or 1),
            "response_format": "url",
        }
        if task.refs:
            # 有参考图 → edits。该站没在文档里列，但按 OpenAI 兼容惯例可用；
            # 这里仍走 json 而非 multipart，因为参考图已经是 data URI 了。
            body["images"] = task.refs[:9]
            path = "/v1/images/edits"
        else:
            path = "/v1/images/generations"
        data = self.session.request("POST", path, json_body=body, retries=2, timeout=600)
        items = extract_image_items(data)
        task_id = extract_task_id(data)
        if not items:
            if not task_id:
                raise ApiError("提交没返回图片也没返回 task_id")
            items = self.session.poll("/v1/images/{id}", task_id, picker=extract_image_items,
                                      interval=poll_interval, timeout=poll_timeout,
                                      content_path_tpl="/v1/images/{id}/content",
                                      log=log, cancel=cancel)
        self.session.save_item(items[0], dest)
        return {"task_id": task_id, "source": items[0][:200], "provider": self.id,
                "model": model}

    # ---------------------------------------------------------------- video
    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 10, poll_timeout: int = 2400) -> dict:
        model = task.model or "seedance_2_fast_480p"
        refs = list(task.refs or [])[:9]
        ratio = _ratio_of(task.ratio) or "9:16"
        dur = int(task.duration or 10)

        if model in SD2_MODELS:
            body = self._sd2_body(model, task.prompt, dur, ratio, refs, log)
        elif model in SORA_MODELS:
            body = self._sora_body(model, task.prompt, dur, ratio, refs)
        else:
            body = self._i2v_body(model, task.prompt, dur, ratio, refs, log)

        data = self.session.request("POST", "/v1/videos", json_body=body,
                                    retries=2, timeout=300)
        url = extract_video_url(data)
        task_id = extract_task_id(data)
        if not url:
            if not task_id:
                raise ApiError("提交没返回视频地址也没返回 task_id")
            url = self.session.poll("/v1/videos/{id}", task_id, picker=extract_video_url,
                                    interval=poll_interval, timeout=poll_timeout,
                                    content_path_tpl="/v1/videos/{id}/content",
                                    log=log, cancel=cancel)
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id, "model": model}

    # -- 三种接口的 body 各不相同，分开写比塞一堆 if 清楚 -------------------
    def _with_ratio(self, body: dict, ratio: str) -> dict:
        # 两个别名都发：文档写 aspect_ratio，实测部分模型读 ratio
        body["aspect_ratio"] = ratio
        body["ratio"] = ratio
        return body

    def _i2v_body(self, model, prompt, dur, ratio, refs, log) -> dict:
        dur = _snap(dur, I2V_DURATIONS, log, model, "duration")
        # duration 给数字、seconds 给字符串（该站 seconds 是 string，发数字会 400）
        body = self._with_ratio({"model": model, "prompt": prompt,
                                 "duration": dur, "seconds": str(dur),
                                 "stream": False}, ratio)
        if len(refs) == 1:
            body["image"] = refs[0]
        elif refs:
            body["images"] = refs
        return body

    def _sora_body(self, model, prompt, dur, ratio, refs) -> dict:
        body = self._with_ratio({"model": model, "prompt": prompt}, ratio)
        if dur > 0:
            body["seconds"] = str(dur)          # 字符串，同上
        if refs:
            body["input_reference"] = "|".join(refs)
        return body

    def _sd2_body(self, model, prompt, dur, ratio, refs, log) -> dict:
        """Seedance 满血（sd2-fast / sd2-pro 共用），按官方客服确认的规格：

        ```json
        {"model":"sd2-pro","prompt":"…","images":["data:image/png;base64,…","https://…"],
         "duration":"10","size":"1280x720","stream":false}
        ```
        三个和站内那份分模型文档不一样、且是踩过的坑：
          · **比例由 `size` 决定**，该接口**没有 aspect_ratio 字段** ——
            之前发 aspect_ratio 而不发 size，字段被忽略、比例随上游默认，
            表现就是「同样参数一会儿横屏一会儿竖屏」。
          · `duration` 是**字符串**（"10"），不是 int。
          · `images` **公网链接和 data:base64 都收**，本地图不用非得配对象存储。
        """
        sec = _snap(dur, SD2_DURATIONS, log, model, "duration")
        body = {"model": model, "prompt": prompt,
                "duration": str(sec),                   # 字符串
                "size": _SD2_RATIO_TO_SIZE.get(ratio, "720x1280"),   # 比例只能靠它
                "stream": False}
        if refs:
            body["images"] = refs                        # URL 或 data URI 都行
        return body
