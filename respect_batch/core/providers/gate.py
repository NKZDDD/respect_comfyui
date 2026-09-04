# -*- coding: utf-8 -*-
"""Gate（api-gate.astralmindai.com）图片、视频与模型清单接入。

依据用户提供的《Gate接入文档》和公开模型 Schema：
  · GET  /public/model_group/info       公开模型及参数 Schema
  · POST /v1/images/generations        图片生成/编辑
  · POST /api/multimodal/create_task   创建异步视频任务
  · GET  /v1/videos/{id}               查询视频任务
  · GET  /v1/videos/{id}/content       下载视频

视频 Schema 中 Seedance 2.5 支持 4–30 秒、30 图、10 视频、10 音频；2.0 系列
支持 4–15 秒、9 图、3 视频、3 音频。视频 reference 字段为纯字符串数组。
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from ..apiutil import ApiError, extract_image_items, extract_task_id
from .base import ImageTask, Provider, VideoTask

IMAGE_MODELS = [
    "nano-banana", "nano-banana-pro", "seedream-5-0-lite", "nano-banana-2",
    "seedream-5-0-pro", "gpt-image-2", "nano-banana-2-lite", "seedream-4-0",
    "kling-image-o3", "qwen-image-2.0-pro", "qwen-image-2.0", "seedream-4-5",
    "kling-image-v3", "gpt-image-1",
]
VIDEO_MODELS = [
    "seedance-2.5-official", "seedance-2.0-standard-official",
    "seedance-2.0-fast-official", "seedance-2.0-mini", "seedance-2.0-standard",
    "seedance-2.5", "seedance-2.0-fast",
]
IMAGE_SIZES = ["1024x1536", "1536x1024", "1024x1024"]
RATIOS = ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9", "adaptive"]

# /public/model_group/info 的图片 Schema 不是一套字段硬套所有模型：GPT 不收
# reference image，Kling 用 num_images/resolution，Qwen 的尺寸分隔符还是“*”。
# 在适配层明确转换，不能把服务端会拒绝（或静默忽略）的字段照发出去。
IMAGE_REF_LIMITS = {
    "nano-banana": 14, "nano-banana-pro": 14, "seedream-5-0-lite": 14,
    "nano-banana-2": 14, "seedream-5-0-pro": 10,
    "nano-banana-2-lite": 14, "gpt-image-2": 0, "gpt-image-1": 0,
    "kling-image-v3": 1,
}
_NO_N = {"seedream-5-0-lite", "seedream-5-0-pro", "seedream-4-0",
         "seedream-4-5", "kling-image-o3", "kling-image-v3"}
_KLING = {"kling-image-o3", "kling-image-v3"}


# 逐模型硬约束，**直接来自 /public/model_group/info 实拉**（2026-08-31）。
# 文档正文写「图片最多 9 张」只对 2.0 系成立，它后面跟着「具体以模型 Schema 为准」。
#
# `banned` 是这家**主动声明**的不支持参数。Schema 里 seed 那条的原话：
#   "Unsupported by Seedance 2.0 series; declared for explicit validation
#    instead of silent dropping."
# —— 它宁可显式拒绝也不静默丢弃。我们照做：传了就报，不替它兜。
GATE_VIDEO_SPEC = {
    "seedance-2.0-fast": dict(
        duration=(4, 15), resolutions=["480p", "720p", "1080p", "4k"],
        max_images=9, max_videos=3, max_audios=3,
        banned=["camera_fixed", "draft", "frames", "seed", "service_tier"],
        audio_requires=["image_url", "video_url"]),
    "seedance-2.0-fast-official": dict(
        duration=(4, 15), resolutions=["480p", "720p"],
        max_images=9, max_videos=3, max_audios=3,
        banned=["camera_fixed", "draft", "frames", "seed", "service_tier"],
        audio_requires=["image_url", "video_url"]),
    "seedance-2.0-mini": dict(
        duration=(4, 15), resolutions=["480p", "720p"],
        max_images=9, max_videos=3, max_audios=3,
        banned=["camera_fixed", "draft", "frames", "seed", "service_tier"],
        audio_requires=["image_url", "video_url"]),
    "seedance-2.0-standard": dict(
        duration=(4, 15), resolutions=["480p", "720p", "1080p", "4k"],
        max_images=9, max_videos=3, max_audios=3,
        banned=["camera_fixed", "draft", "frames", "seed", "service_tier"],
        audio_requires=["image_url", "video_url"]),
    "seedance-2.0-standard-official": dict(
        duration=(4, 15), resolutions=["480p", "720p", "1080p", "4k"],
        max_images=9, max_videos=3, max_audios=3,
        banned=["camera_fixed", "draft", "frames", "seed", "service_tier"],
        audio_requires=["image_url", "video_url"]),
    "seedance-2.5": dict(
        duration=(4, 30), resolutions=["480p", "720p"],
        max_images=30, max_videos=10, max_audios=10,
        banned=["draft"], audio_requires=None),
    "seedance-2.5-official": dict(
        duration=(4, 30), resolutions=["480p", "720p"],
        max_images=30, max_videos=10, max_audios=10,
        banned=["draft"], audio_requires=None),
}
# metadata 里能放的（文档 4.2「常用 metadata 参数」）。不在这张表里的一律不发 ——
# 文档 3 行原话：「未被模型声明的参数会被静默丢弃或被下游拒绝」。
GATE_META_KEYS = ("ratio", "duration", "resolution", "watermark", "generate_audio",
                  "return_last_frame", "safety_identifier", "execution_expires_after",
                  "camera_fixed", "seed", "output_format", "omni_reference_task_type",
                  "service_tier", "biz_id")
GATE_DONE, GATE_FAIL = ("success",), ("failed",)


def gate_spec(model: str) -> dict:
    """认不出的按 2.0 系最保守的一套走，别拿猜的上限放行。"""
    return GATE_VIDEO_SPEC.get(model, GATE_VIDEO_SPEC["seedance-2.0-mini"])


def _is_25(model: str) -> bool:
    return str(model).startswith("seedance-2.5")


def _ratio_for_size(size: str) -> str:
    """把项目的 WIDTHxHEIGHT 转为 Kling 接口的宽高比字段。"""
    try:
        w, h = (int(x) for x in str(size).lower().split("x", 1))
    except (TypeError, ValueError):
        return "1:1"
    pairs = {(9, 16): "9:16", (16, 9): "16:9", (1, 1): "1:1",
             (4, 3): "4:3", (3, 4): "3:4", (3, 2): "3:2", (2, 3): "2:3"}
    return min(pairs.items(), key=lambda item: abs(w / h - item[0][0] / item[0][1]))[1]


def _image_shape(model: str, size: str) -> dict:
    """按 Gate 当前公开 Schema 生成每个图片模型能接受的尺寸字段。"""
    wanted = str(size or "1024x1536")
    if model in _KLING:
        return {"resolution": "1K", "aspect_ratio": _ratio_for_size(wanted)}
    if model.startswith("qwen-image-2.0"):
        return {"size": wanted.replace("x", "*").replace("X", "*")}
    if model == "seedream-4-5":
        # 该模型自定义尺寸下限高于项目的默认 1024x1536；2K 是文档默认安全值。
        return {"size": wanted if wanted in ("2K", "4K") else "2K"}
    return {"size": wanted}


class GateProvider(Provider):
    id = "gate"
    name = "Gate api-gate.astralmindai.com"
    aliases = ("astralmind", "astralmindai", "Gate", "盖特")
    default_base_url = "https://api-gate.astralmindai.com"
    supports = ("image", "video")
    # 图片 Schema 明确收公网 URL / Base64；视频 image_url 必须是网关能取到的 URL。
    ref_mode = "data_uri"

    def __init__(self, api_key: str = "", base_url: str = "", proxy: str = "",
                 timeout: int = 900):
        # 实测 Windows 系统代理可能令该域名在 TLS 握手时 EOF，直连正常。用户若在
        # config 里显式填了代理仍尊重其配置；没填则不偷偷继承系统代理。
        super().__init__(api_key, base_url, proxy or "direct", timeout)

    def needs_url(self, model: str = "", media: str = "image") -> bool:
        return media == "video"

    def capabilities(self) -> dict:
        # 直接读实拉的 Schema 表，别再按「名字里有没有 2.5」猜
        video_options = {
            m: {"durations": list(range(gate_spec(m)["duration"][0],
                                        gate_spec(m)["duration"][1] + 1)),
                "max_refs": gate_spec(m)["max_images"],
                "max_video_refs": gate_spec(m)["max_videos"],
                "max_audio_refs": gate_spec(m)["max_audios"],
                "resolutions": gate_spec(m)["resolutions"],
                "unsupported": gate_spec(m)["banned"]}
            for m in VIDEO_MODELS
        }
        return {
            "id": self.id,
            "name": self.name,
            "default_base_url": self.default_base_url,
            "supports": list(self.supports),
            "image": {
                "models": IMAGE_MODELS,
                # 默认选能吃多参考图的模型；GPT 两个图片模型在当前 Schema 中只做文生图。
                "default_model": "seedream-5-0-pro",
                "sizes": IMAGE_SIZES,
                "default_size": "1024x1536",
                "max_refs": 14,
                "ref_mode": "data_uri",
                "model_options": {
                    model: {"max_refs": limit} for model, limit in IMAGE_REF_LIMITS.items()
                },
                "notes": "POST /v1/images/generations。参考图字段为 image，单张可传字符串，"
                         "多张传数组；支持公网 URL 或 Base64 Data URL。各模型精确尺寸/参考图"
                         "上限以公开 Schema 为准。",
            },
            "video": {
                "models": VIDEO_MODELS,
                "default_model": "seedance-2.5",
                "ratios": RATIOS,
                "durations": list(range(4, 31)),
                "default_duration": 15,
                "resolutions": ["480p", "720p"],
                "max_refs": 30,
                "max_video_refs": 10,
                "max_audio_refs": 10,
                "ref_mode": "url",
                "model_options": video_options,
                "notes": "POST /api/multimodal/create_task，请求体是 **inputs[] + metadata{}**"
                         "（不是扁平字段）：每条素材在 inputs 里独立一项、各带 format"
                         "（first_frame / last_frame / reference_image / reference_video /"
                         " reference_audio），视频参数放 metadata。查询是 "
                         "**POST /api/multimodal/get_result**，body 要 model + taskId"
                         "（小驼峰）。Seedance 2.5：4–30 秒、30 图/10 视频/10 音频；"
                         "2.0 系：4–15 秒、9 图/3 视频/3 音频，且**只给音频不给图/视频会被拒**。"
                         "各模型禁用参数见 GATE_VIDEO_SPEC['banned']。",
            },
            "notes": "公开 Schema 会持续变化，list_models() 每次从 /public/model_group/info "
                     "读取；静态列表仅用于界面首次打开。默认直连，不继承 Windows 系统代理；"
                     "Gate 同一个 Key 也可配置为 LLM Base URL。",
        }

    def list_models(self) -> list:
        try:
            data = self.session.request("GET", "/public/model_group/info",
                                        retries=2, timeout=30)
        except ApiError:
            return []
        return sorted({str(m.get("model_group")) for m in (data.get("data") or [])
                       if m.get("model_group")})

    def generate_image(self, task: ImageTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 900) -> dict:
        model = (task.model or "gpt-image-2").strip()
        refs = list(task.refs or [])
        limit = IMAGE_REF_LIMITS.get(model, 14)
        if refs and not limit:
            raise ApiError(f"Gate {model} 当前 Schema 不支持参考图；请改用 Seedream、"
                           "Nano Banana、Qwen 或 Kling 模型。",
                           status=0, kind="task_fatal")
        if len(refs) > limit:
            raise ApiError(f"Gate {model} 最多 {limit} 张参考图，本任务有 {len(refs)} 张；"
                           "不能静默裁图。", status=0, kind="task_fatal")

        body: dict = {"model": model, "prompt": task.prompt or ""}
        body.update(_image_shape(model, task.size))
        if model in _KLING:
            body["num_images"] = int(task.n or 1)
        elif model not in _NO_N:
            body["n"] = int(task.n or 1)
        if refs:
            body["image"] = refs[0] if len(refs) == 1 else refs
        for key in ("quality", "image_size", "aspect_ratio", "output_format",
                    "background", "output_compression", "seed"):
            if key in task.extra:
                body[key] = task.extra[key]
        shape = body.get("size") or (f"{body.get('resolution')} {body.get('aspect_ratio')}")
        log(f"Gate 图片 {model}: size={shape} n={task.n or 1} 参考图{len(refs)}张")
        data = self.session.request("POST", "/v1/images/generations",
                                    json_body=body, retries=1, timeout=600)
        items = extract_image_items(data)
        if not items:
            raise ApiError(f"Gate 图片接口没返回可用图片: {str(data)[:300]}")
        self.session.save_item(items[0], dest)
        return {"task_id": extract_task_id(data), "source": items[0][:200],
                "provider": self.id, "model": model}

    def build_video_body(self, task: VideoTask, model: str) -> dict:
        """按文档 4.1 拼请求体：`inputs[]` + `metadata{}`。

        ⚠ 这里以前发的是**扁平字段**（`prompt`/`duration`/`ratio`/`image_url:[…]`），
        文档里没有任何一个在那个位置。而文档 3 行原话是「未被模型声明的参数会被
        **静默丢弃**或被下游拒绝」—— 所以那样发出去，任务建得起来、task_id 也拿得到，
        但提示词和参考图很可能一个都没进去。片子出得来，只是跟你要的没关系。
        """
        spec = gate_spec(model)
        prompt = (task.prompt or "").strip()
        if not prompt:
            raise ApiError("Gate 视频的 prompt 必填", status=0, kind="task_fatal")

        images = list(task.refs or [])
        videos = list(task.extra.get("video_refs") or task.extra.get("videos") or [])
        audios = list(task.extra.get("audio_refs") or task.extra.get("audios") or [])
        lo, hi = spec["duration"]
        sec = int(task.duration or 15)
        ratio = task.ratio or "adaptive"
        res = (task.resolution or "720p").lower()

        problems = []
        if not lo <= sec <= hi:
            problems.append(f"时长只支持 {lo}–{hi} 秒，收到 {sec} 秒")
        if ratio not in RATIOS:
            problems.append(f"比例只支持 {'、'.join(RATIOS)}，收到 {ratio}")
        if res not in spec["resolutions"]:
            problems.append(f"分辨率只支持 {'、'.join(spec['resolutions'])}，收到 {res}")
        for got, cap, what in ((images, spec["max_images"], "图片"),
                               (videos, spec["max_videos"], "视频"),
                               (audios, spec["max_audios"], "音频")):
            if len(got) > cap:
                problems.append(f"{what}素材最多 {cap} 个，收到 {len(got)} 个")
        # Schema 的 x-requires-any-of：2.0 系只给音频、不给图/视频会被拒
        if audios and spec["audio_requires"] and not (images or videos):
            problems.append(f"{model} 的音频素材必须搭配参考图或参考视频一起给")
        bad = [r for r in images + videos + audios
               if not str(r).startswith(("http://", "https://"))]
        if bad:
            problems.append(f"参考素材必须是**下游能取到的公网 URL**，有 {len(bad)} 条不是")
        # 这家自己声明的不支持参数：传了就报，不替它兜（Schema 原话是宁可显式拒绝
        # 也不静默丢弃）。静默丢的后果是你以为锁了镜头，实际没锁，而且不报错。
        banned = [k for k in spec["banned"] if k in task.extra]
        if banned:
            problems.append(f"{model} 不支持 {'、'.join(banned)}（这家自己声明的），请去掉")
        if problems:
            raise ApiError(f"Gate {model} 的参数不符合它的 Schema：" + "；".join(problems),
                           status=0, kind="task_fatal")

        # 每条素材是 inputs[] 里**独立一项**，各带自己的 format —— 不是数组字段
        inputs = [{"name": "prompt", "value": prompt, "format": "text"}]
        first_last = bool(task.extra.get("first_last")) and len(images) >= 2
        for n, url in enumerate(images):
            fmt = "reference_image"
            if first_last:
                fmt = "first_frame" if n == 0 else "last_frame" if n == 1 else "reference_image"
            inputs.append({"name": "image_url", "value": url, "format": fmt})
        for url in videos:
            inputs.append({"name": "video_url", "value": url, "format": "reference_video"})
        for url in audios:
            inputs.append({"name": "audio_url", "value": url, "format": "reference_audio"})

        meta = {"ratio": ratio, "duration": sec, "resolution": res,
                "watermark": bool(task.extra.get("watermark", False)),
                "generate_audio": bool(task.extra.get("generate_audio", True))}
        # 只放文档列过、且这个模型没禁的键
        for k in GATE_META_KEYS:
            if k in task.extra and k not in meta and k not in spec["banned"]:
                meta[k] = task.extra[k]

        body = {"model": model, "inputs": inputs, "metadata": meta}
        if "priority" in task.extra:
            body["priority"] = max(0, min(9, int(task.extra["priority"])))
        for k in ("callback_url", "callback_headers", "callback_secret"):
            if task.extra.get(k):
                body[k] = task.extra[k]
        return body

    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 2400) -> dict:
        model = (task.model or "seedance-2.5").strip()
        body = self.build_video_body(task, model)
        n_img = sum(1 for i in body["inputs"] if i["name"] == "image_url")
        log(f"Gate 视频 {model}: {body['metadata']['duration']}s "
            f"{body['metadata']['resolution']} {body['metadata']['ratio']} "
            f"素材 {len(body['inputs']) - 1} 项（图 {n_img}）")
        data = self.session.request("POST", "/api/multimodal/create_task",
                                    json_body=body, retries=1, timeout=300)
        task_id = str((data or {}).get("task_id") or "")
        if not task_id:
            raise ApiError(f"Gate 创建任务没返回 task_id: {str(data)[:300]}")

        url = self._poll_result(model, task_id, poll_interval, poll_timeout,
                                log=log, cancel=cancel)
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id, "model": model}

    def _poll_result(self, model: str, task_id: str, interval: int, timeout: int,
                     *, log, cancel=None) -> str:
        """查询任务。**POST /api/multimodal/get_result，body 要 model + taskId。**

        ⚠ 这里以前查的是 `GET /v1/videos/{id}` —— 那个端点在 Gate 的文档里
        **根本不存在**，是我们自己编的。而 Gate 是 litellm 搭的网关，`/v1/videos/*`
        在 litellm 里是 **OpenAI 直通路由**，于是它把我们的 task_id 转发去了
        `api.openai.com/v1/videos/{uuid}`，超时回 500。用户看到的就是一屏
        `litellm.APIConnectionError: openai - Connection timeout to host
        https://api.openai.com/...` —— 地址是 Gate 拼的，不是我们配错了 base_url。

        注意参数名是 **taskId（小驼峰）**，不是 task_id；而且**必须带 model**。
        """
        start, last = time.time(), ""
        stuck = 0
        while time.time() - start < timeout:
            if cancel and cancel():
                raise ApiError("用户已取消")
            try:
                data = self.session.request(
                    "POST", "/api/multimodal/get_result",
                    json_body={"model": model, "taskId": task_id},
                    retries=1, timeout=60)
                stuck = 0
            except ApiError as exc:
                # 同一个错一直回 = 端点/参数不对，不是抖动。别拖满 40 分钟。
                stuck += 1
                if stuck >= 3:
                    raise ApiError(
                        f"Gate 查询任务连续 {stuck} 次同样失败，停止等待：{exc}\n"
                        f"（任务 {task_id} 可能仍在它那边跑；这类错重试无意义，"
                        f"多半是端点或参数不对）", status=0, kind="task_fatal") from exc
                log(f"Gate 查询出错（第 {stuck} 次，继续）：{exc}")
                time.sleep(interval)
                continue

            status = str((data or {}).get("status") or "").lower()
            if status != last:
                log(f"Gate {task_id}: {status or '(无状态字段)'}")
                last = status
            if status in GATE_FAIL:
                raise ApiError(f"Gate 任务失败：{(data or {}).get('error') or str(data)[:300]}",
                               status=0, kind="task_fatal")
            url = _gate_result_url(data)
            if url:
                return url
            if status in GATE_DONE:
                raise ApiError(
                    f"Gate 说任务成功了，但 results 里没有 video_url："
                    f"{str(data)[:400]}", status=0, kind="task_fatal")
            time.sleep(interval)
        raise ApiError(f"Gate 任务超时：{task_id}（建议 2~5 秒轮询，长任务可调大 poll_timeout）",
                       status=0, kind="retryable")


def _gate_result_url(payload) -> str:
    """从 get_result 响应里取成片地址。

    文档 4.4 的成功响应把它放在两个地方，两处都取（前者是官方列出的取值口）：
      results[].parameters[]  里 name == "video_url" 的 value
      results[].result.content.video_url
    """
    if not isinstance(payload, dict):
        return ""
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        for par in item.get("parameters") or []:
            if (isinstance(par, dict) and par.get("name") == "video_url"
                    and isinstance(par.get("value"), str)
                    and par["value"].startswith("http")):
                return par["value"]
        content = ((item.get("result") or {}).get("content") or {})
        url = content.get("video_url")
        if isinstance(url, str) and url.startswith("http"):
            return url
    return ""
