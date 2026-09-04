# -*- coding: utf-8 -*-
"""巨轮（julun.cc）。文档：《AI 开放平台接口对接文档》v2.1，2026-08-26。

  · 文本 `/v1/chat/completions`（OpenAI 兼容，走 core/llm.py，本类不管）
  · 图片 `POST /v1/images/generations`（OpenAI 兼容，**同步**）
  · 视频 异步三步：提交 → 轮询 → 下载

视频**一个服务、五种请求格式**，按模型名分派（见 `SPEC`）：

| 格式 | 形状 |
|---|---|
| `metadata` | `metadata:{content[], duration, ratio, resolution}` |
| `url_media` | `seconds` + `image_urls[]` / `video_urls[]` / `audio_urls[]` |
| `openai_refs` | `duration` + `aspect_ratio` + `image_refs[]` |
| `grok` | `duration` + `extra:{aspect_ratio, resolution, reference_images[{url,role}]}` |
| `simple` | `model` + `prompt` + `seconds`（h3，走 `/v1/video/generations`）|

⚠ 对着文档才知道的几个坑：

1. **模型名带空格、中文、全角括号** —— `grok-imagine-video-1.5（按次）` 是**全角**的，
   `Quality V4 · 480p/720p (可@图/视频/音频)` 带间隔号。照抄，别手打。
2. **grok 不认 `seconds`**，只认 `duration`；比例分辨率必须在 `extra` 里。
3. `sd2.5` 和 `dubai_sd25_170` 都固定 30 秒，但**行为不同**：前者传别的会被
   平台悄悄覆盖，后者**直接 400**。所以一律先纠正到 30。
4. **查询响应套一层**：`{"code":"success","data":{status,progress,result_url}}`，
   状态**大写** `IN_PROGRESS`/`SUCCESS`/`FAILURE`，进度是字符串 `"100%"`。
5. `SD2.0 1080P 933` **至少要 1 张参考图**。
6. 上传的素材**只保留 72 小时**。
"""

from __future__ import annotations

import os
import time
from typing import Callable, Optional

from ..apiutil import ApiError, extract_image_items
from .base import ImageTask, Provider, VideoTask

UPLOAD_MAX_MB = 210
UPLOAD_EXTS = ("jpg", "jpeg", "png", "webp", "mp4", "mov", "m4v",
               "webm", "avi", "mkv", "mp3", "wav", "m4a", "aac")

R6 = ["16:9", "9:16", "1:1", "21:9", "3:4", "4:3"]
R5 = ["16:9", "1:1", "9:16", "3:4", "4:3"]

# 文档 5.3「各模型请求规格」整张表。**逐项抄进来**：这些不是建议，
# 超了会 invalid_duration 或 400，而那之前的排队是白等的。
# (格式, 时长规则, 分辨率, 比例, 图上限, 视频上限, 音频上限, 备注)
SPEC = {
    "SD2.0 Fast": ("metadata", (4, 15), ["720p", "480p"], R6, 9, 0, 0, ""),
    "SD2.0 1080P 933": ("metadata", (15, 15), ["1080P"], ["16:9", "9:16"], 9, 3, 3,
                        "至少 1 张参考图；默认开配音"),
    "sd-2-c8": ("metadata", (10, 15, [10, 15]), ["720p"], ["16:9", "9:16", "1:1"], 9, 3, 3,
                "只有 10 或 15 秒"),
    "sd-2-c6": ("metadata", (4, 15), ["720p"], ["16:9", "9:16", "1:1"], 9, 3, 3, ""),
    "Seedance 图生视频": ("url_media", (4, 15), ["720p"], ["16:9"], 9, 3, 3, "时长必填"),
    "sd2-mini": ("url_media", (4, 15), ["720p"], ["16:9"], 9, 3, 3, ""),
    "Seedance MINI 933": ("url_media", (4, 15), ["720p"], ["16:9"], 9, 3, 3, ""),
    "Quality V4 · 480p/720p (可@图/视频/音频)":
        ("url_media", (5, 15, [5, 10, 15]), ["480p", "720p"], ["auto"] + R5, 9, 3, 3,
         "480p 支持 5/10/15；720p 只有 10 秒"),
    "wan3.0th": ("url_media", (4, 30), ["720p"], R5, 10, 5, 5,
                 "**按秒计费** 0.14 元/秒；音频必须 WAV"),
    "seedance-2.5-deal": ("url_media", (4, 15), ["720p"], R5, 30, 10, 10, "音频必须 WAV"),
    "sd2-c7": ("openai_refs", (5, 15), ["720p"], R6, 9, 0, 0, ""),
    "sd2.5": ("openai_refs", (30, 30), ["720p"], R6, 10, 0, 0,
              "固定 30 秒；传别的会被平台悄悄覆盖"),
    "dubai_sd25_170": ("openai_refs", (30, 30), ["720p"], R6, 10, 0, 0,
                       "固定 30 秒，**传别的直接 400**；人脸账号每日 00:00 重置"),
    "grok-imagine-video-1.5（按次）":
        ("grok", (6, 3600), ["720p", "480p"], ["16:9", "9:16", "1:1"], 7, 0, 0,
         "时长必填、不认 seconds；比例分辨率放 extra"),
    "grok-imagine-video-1.5-preview":
        ("grok", (6, 3600), ["720p", "480p"], ["16:9", "9:16", "1:1"], 7, 0, 0, "同上"),
    "minimax-h3 768p": ("simple", (6, 10, [6, 10]), ["768p"], [], 1, 0, 0,
                        "走 /v1/video/generations；参考图只 1 张"),
    "minimax-h3 2k": ("simple", (6, 10, [6, 10]), ["2k"], [], 1, 0, 0, "同上"),
}
VIDEO_MODELS = list(SPEC)
IMAGE_MODELS = ["doubao-seedream-5-0-260128"]


def spec_of(model: str) -> tuple:
    """模型 → 规格。认不出的按 url_media（这家最通用的一套）。"""
    return SPEC.get(model, ("url_media", (4, 15), ["720p"], R5, 9, 3, 3, ""))


def fit_duration(model: str, want: int, *, log=None) -> int:
    """按规格表收敛时长。改了要说 —— 悄悄改会让人对不上账。"""
    rule = spec_of(model)[1]
    lo, hi = rule[0], rule[1]
    allowed = rule[2] if len(rule) > 2 else None
    sec = int(want or lo)
    if allowed:
        if sec not in allowed:
            near = min(allowed, key=lambda a: abs(a - sec))
            if log:
                log(f"巨轮 {model} 只支持 {allowed} 秒，已把 {sec} 纠正为 {near}")
            return near
        return sec
    if sec < lo or sec > hi:
        near = max(lo, min(hi, sec))
        if log:
            log(f"巨轮 {model} 时长范围 {lo}–{hi} 秒，已把 {sec} 纠正为 {near}")
        return near
    return sec


class JulunProvider(Provider):
    id = "julun"
    name = "巨轮 julun.cc"
    aliases = ("julun.cc", "巨轮", "jl")
    default_base_url = "https://julun.cc"
    supports = ("image", "video")
    # 视频参考素材**必须公网可访问**（文档 5.3 通用约束），本机图得先传对象存储，
    # 或用本类的 upload_asset() 换成平台 URL。
    ref_mode = "url"

    def capabilities(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "default_base_url": self.default_base_url,
            "supports": list(self.supports),
            "image": {
                "models": IMAGE_MODELS,
                "default_model": IMAGE_MODELS[0],
                "sizes": [""],
                "default_size": "",
                "max_refs": 0,
                "ref_mode": "url",
                "notes": "OpenAI 兼容、**同步**返回。平台**固定一次出 1 张**（n 传别的没用），"
                         "0.04 元/张，失败不扣费。size 按 OpenAI 语义透传，不支持的值会 400。",
            },
            "video": {
                "models": VIDEO_MODELS,
                "default_model": "sd2.5",
                "ratios": R6,
                "durations": list(range(4, 31)),
                "default_duration": 10,
                "resolutions": ["720p", "480p", "768p", "1080P", "2k"],
                "max_refs": 30,
                "ref_mode": "url",
                "specs": {m: {"format": s[0], "duration": s[1], "resolutions": s[2],
                              "ratios": s[3], "max_images": s[4], "max_videos": s[5],
                              "max_audios": s[6], "note": s[7]}
                          for m, s in SPEC.items()},
                "notes": "⚠ **五种请求格式按模型分派**（metadata / url_media / openai_refs / "
                         "grok / simple），选模型即选格式。每个模型的时长、比例、素材上限"
                         "都不一样，见 specs —— 本类在**提交前**校验，超了当场报，"
                         "不让排队时间白花。参考素材必须公网可访问（可用 upload_asset() "
                         "换成平台 URL，**保留 72 小时**）。失败任务不扣费、自动退款。",
            },
            "notes": "模型名带空格、中文和**全角括号**（grok-imagine-video-1.5（按次）），"
                     "照抄别手打。域名不通时可临时用 http://107.148.118.228:3000。",
        }

    # -- 上传素材（本地 → 平台 URL，72 小时）-----------------------------
    def upload_asset(self, path: str, *, log: Callable = print) -> str:
        if not os.path.isfile(path):
            raise ApiError(f"找不到文件: {path}")
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        if ext not in UPLOAD_EXTS:
            raise ApiError(f"巨轮只收 {'/'.join(UPLOAD_EXTS)}，不收 .{ext}")
        size = os.path.getsize(path)
        if size > UPLOAD_MAX_MB * 1024 * 1024:
            raise ApiError(f"{os.path.basename(path)} 有 {size / 1048576:.1f}MB，"
                           f"超过 {UPLOAD_MAX_MB}MB 上限")
        with open(path, "rb") as fh:
            blob = fh.read()
        ctype = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                 "webp": "image/webp", "mp4": "video/mp4",
                 "wav": "audio/wav", "mp3": "audio/mpeg"}.get(ext, "application/octet-stream")
        data = self.session.request(
            "POST", "/v1/video/uploads",
            files=[("file", (os.path.basename(path), blob, ctype))],
            retries=1, timeout=900)
        url = data.get("url", "") if isinstance(data, dict) else ""
        if not url:
            raise ApiError(f"上传没返回 url: {str(data)[:300]}")
        log(f"巨轮 素材已上传（72 小时内有效）: {url}")
        return url

    # ---------------------------------------------------------------- video
    def build_video_body(self, task: VideoTask, *, log=None) -> tuple:
        """按模型所属格式拼 body，并在提交前校验规格。返回 (路径, body)。"""
        model = task.model or "sd2.5"
        fmt, _rule, res_list, ratios, cap_i, cap_v, cap_a, note = spec_of(model)
        if not (task.prompt or "").strip():
            raise ApiError("巨轮 prompt 必填", status=0, kind="task_fatal")

        sec = fit_duration(model, task.duration, log=log)
        ratio = (task.ratio or "").strip() or (ratios[0] if ratios else "16:9")
        res = (task.resolution or "").strip() or (res_list[0] if res_list else "720p")

        refs = list(task.refs or [])
        vids = [v for v in (task.extra.get("video_refs") or task.extra.get("videos") or []) if v]
        auds = [a for a in (task.extra.get("audio_refs") or task.extra.get("audios") or []) if a]

        local = [r for r in refs if not str(r).startswith(("http://", "https://"))]
        if local:
            raise ApiError(
                f"巨轮的参考素材必须**公网可访问**，这一项有 {len(local)} 张是本机图。"
                f"本该有 {len(refs)} 张参考图 —— 少了出来的就不是同一个人，所以不出这条。"
                f"去「设置 → 参考图上传」配对象存储，或先用 upload_asset() 传成平台 URL。",
                status=0, kind="task_fatal")

        problems = []
        if len(refs) > cap_i:
            problems.append(f"参考图最多 {cap_i} 张，收到 {len(refs)} 张")
        if vids and cap_v == 0:
            problems.append(f"{model} 不支持参考视频，收到 {len(vids)} 条")
        elif len(vids) > cap_v:
            problems.append(f"参考视频最多 {cap_v} 条，收到 {len(vids)} 条")
        if auds and cap_a == 0:
            problems.append(f"{model} 不支持参考音频，收到 {len(auds)} 条")
        elif len(auds) > cap_a:
            problems.append(f"参考音频最多 {cap_a} 条，收到 {len(auds)} 条")
        if ratios and ratio not in ratios:
            problems.append(f"比例只支持 {'、'.join(ratios)}，收到 {ratio}")
        if model == "SD2.0 1080P 933" and not refs:
            problems.append("这个模型至少要 1 张参考图")
        if problems:
            raise ApiError(
                f"巨轮 {model} 的参数不符合规格表：" + "；".join(problems)
                + (f"（该模型：{note}）" if note else ""),
                status=0, kind="task_fatal")

        path = "/v1/videos"
        if fmt == "metadata":
            meta = {"duration": sec, "ratio": ratio, "resolution": res}
            content = list(refs)
            for v in vids:
                content.append({"role": "reference_video", "type": "video_url",
                                "video_url": {"url": v}})
            for a in auds:
                content.append({"role": "reference_audio", "type": "audio_url",
                                "audio_url": {"url": a}})
            if content:
                meta["content"] = content
            if "generate_audio" in task.extra:
                meta["generate_audio"] = bool(task.extra["generate_audio"])
            body = {"model": model, "prompt": task.prompt, "metadata": meta}
        elif fmt == "url_media":
            body = {"model": model, "prompt": task.prompt, "seconds": sec,
                    "ratio": ratio, "resolution": res}
            if refs:
                body["image_urls"] = refs
            if vids:
                body["video_urls"] = vids
            if auds:
                body["audio_urls"] = auds
        elif fmt == "openai_refs":
            body = {"model": model, "prompt": task.prompt, "duration": sec,
                    "aspect_ratio": ratio}
            if refs:
                body["image_refs"] = refs
        elif fmt == "grok":
            # 文档：**不支持 seconds**；比例分辨率必须在 extra 里，放顶层无效
            extra = {"aspect_ratio": ratio, "resolution": res}
            body = {"model": model, "prompt": task.prompt, "duration": sec, "extra": extra}
            if len(refs) == 1:
                body["input_reference"] = refs[0]
            elif refs:
                if task.extra.get("first_last"):
                    if len(refs) < 2:
                        raise ApiError("首尾帧要 2 张图", status=0, kind="task_fatal")
                    # 文档：first_frame 与 last_frame **必须成对**，
                    # 且**不能与 reference_image 混用**
                    extra["reference_images"] = [
                        {"url": refs[0], "role": "first_frame"},
                        {"url": refs[1], "role": "last_frame"},
                    ]
                else:
                    extra["reference_images"] = [
                        {"url": u, "role": "reference_image"} for u in refs]
        else:                                        # simple（h3）
            path = "/v1/video/generations"           # 文档：h3 推荐这个端点
            body = {"model": model, "prompt": task.prompt, "seconds": sec}
            if refs:
                # 上面的 cap_i 校验已经把「超过 1 张」拦掉了，这里不做截断 ——
                # 截断等于悄悄少一个人出镜，而且不报错。
                body["image_urls"] = refs
        return path, body

    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 6, poll_timeout: int = 1800) -> dict:
        model = task.model or "sd2.5"
        path, body = self.build_video_body(task, log=log)
        fmt = spec_of(model)[0]
        log(f"巨轮 {model}（{fmt} 格式）→ POST {path}")
        data = self.session.request("POST", path, json_body=body, retries=2, timeout=300)
        task_id = ""
        if isinstance(data, dict):
            task_id = str(data.get("task_id") or data.get("id") or "")
        if not task_id:
            raise ApiError(f"提交没返回任务 ID：{str(data)[:300]}")

        url = self._poll(task_id, poll_interval, poll_timeout, log=log, cancel=cancel)
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id, "model": model}

    def _poll(self, task_id: str, interval: int, timeout: int, *, log, cancel=None) -> str:
        """查询响应**套一层**、状态**大写**、进度是字符串 —— 通用轮询器认不出，单独写。"""
        start, last = time.time(), ""
        while time.time() - start < timeout:
            if cancel and cancel():
                raise ApiError("用户已取消")
            data = self.session.request("GET", f"/v1/videos/{task_id}",
                                        retries=1, timeout=60)
            inner = (data or {}).get("data") or {}
            status = str(inner.get("status") or "").upper()
            if status != last:
                log(f"巨轮 {task_id}: {status} {inner.get('progress', '')}")
                last = status
            if status == "FAILURE":
                raise ApiError(
                    f"巨轮任务失败：{inner.get('fail_reason') or str(data)[:300]}"
                    f"（失败不扣费，平台自动原路退回）")
            if status == "SUCCESS":
                url = inner.get("result_url") or ""
                if url:
                    return url
                return f"{self.session.base_url.rstrip('/')}/v1/videos/{task_id}/content"
            time.sleep(interval)
        raise ApiError(f"巨轮任务超时：{task_id}（一般 1–3 分钟，高峰更久）",
                       status=0, kind="retryable")

    # ---------------------------------------------------------------- image
    def generate_image(self, task: ImageTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 900) -> dict:
        model = task.model or IMAGE_MODELS[0]
        if not (task.prompt or "").strip():
            raise ApiError("巨轮 prompt 必填", status=0, kind="task_fatal")
        if task.refs:
            # 文档四只写了文生图，没有图生图入口。丢掉参考图会静默出一张
            # 不相干的图，那比不出更糟 —— 让优先级链换支持图生图的家。
            raise ApiError(
                f"巨轮的出图接口**只有文生图**（文档四没有图生图入口），"
                f"这一项带了 {len(task.refs)} 张参考图。"
                f"少了参考图出来的就不是同一个人，所以不出这张图 —— "
                f"把这类活排给支持图生图的服务商。",
                status=0, kind="task_fatal")

        body = {"model": model, "prompt": task.prompt, "n": 1,   # 平台固定 1 张
                "response_format": "url"}
        if (task.size or "").strip():
            body["size"] = task.size.strip()
        log(f"巨轮 图片 {model}: size={body.get('size', '(不传)')}")
        data = self.session.request("POST", "/v1/images/generations",
                                    json_body=body, retries=2, timeout=300)
        items = extract_image_items(data)
        if not items:
            raise ApiError(f"没返回图片：{str(data)[:300]}")
        self.session.save_item(items[0], dest)
        return {"task_id": "", "source": items[0][:200], "provider": self.id, "model": model}
