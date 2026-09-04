# -*- coding: utf-8 -*-
"""好漫剧（www.75api.com）。文档：《好漫剧API对接文档》2026-08-24。

New API 网关，但**七个分支用了四种协议**，选模型就等于选协议 ——
所以本类按模型名分派，见 `branch_of()`：

| 分支 | 端点 | 格式 | 结果在哪 |
|---|---|---|---|
| GROK | `/v1/videos` | **multipart** `input_reference[]` 文件 | 轮询 `/v1/videos/{id}` |
| minimax_h3 | `/v1/videos` | **JSON** `images` 链接数组 | 同上，完成带 `video_url` |
| Omni-flash | `/v1/video/generations` | JSON | 同路径轮询，**状态嵌两层** |
| Sora2 / VEO | `/v1/chat/completions` | JSON | content 里的 `<video src=…>`，**同步** |
| 香蕉 | `/v1/chat/completions` | JSON | content 里的 markdown `![](url)` |
| GPT-image-2 | `/v1/images/generations` `/edits` | JSON / multipart | `data[0].b64_json` |

**最容易搞错的一处**：GROK 和 minimax_h3 **同一个端点**，一个 multipart 一个 JSON。
发错不会得到"格式错误"这种明白话，多半是参考图整个被丢掉 —— 图照出、人不对。

⚠ **模型名有两套，只有 2 个重合**。文档写的（`grok-video-6s`、`sora2-12s-16x9`…）
和 `/api/pricing` 实拉的（`grok-1.5-fast-10s`、`sora3-933`…）对不上，
只有 `gpt-image-2` 和 `minimax_h3` 两边都有。文档自己的示例也印证网关会改名：
请求 `sora2-12s-16x9`、响应回 `firefly-sora2-12s-16x9`。两套都列进来了。
"""

from __future__ import annotations

import base64
import os
import re
import time
from typing import Callable, Optional

from ..apiutil import (ApiError, extract_image_items, extract_task_id,
                       extract_video_url)
from .base import ImageTask, Provider, VideoTask

# --- 模型清单（文档名在前，pricing 实拉名在后）-----------------------------
GROK_MODELS = ["grok-video-10s", "grok-video-6s", "grok-video-12s",
               "grok-1.5-fast-10s", "grok-imagine-video-1.5-preview"]
# sd-* 是 pricing 有、文档没写的：同端点，按 h3 的 JSON 形状试（错了 400，不计费）
H3_MODELS = ["minimax_h3", "sd-2.5-c1", "sd-2-c1", "sd-2-c6", "sd-2-fast",
             "sora3-933", "sora3-fast"]
OMNI_MODELS = ["omni-flash-4s", "omni-flash-6s", "omni-flash-8s",
               "omni-flash-10s", "gemini-omni-flash-preview"]
SORA_MODELS = ["sora2-12s-16x9", "sora2-12s-9x16"]
VEO_FRAME_MODELS = [f"firefly-veo31-{s}-{r}-{q}"
                    for s in ("4s", "6s") for r in ("16x9", "9x16")
                    for q in ("1080p", "720p")]
VEO_REF_MODELS = ["firefly-veo31-ref-8s-16x9-1080p"]
CHAT_VIDEO_MODELS = (SORA_MODELS + VEO_FRAME_MODELS + VEO_REF_MODELS
                     + ["veo-3.1-fast-generate-preview"])
BANANA_PRO = [f"firefly-nano-banana-pro-{k}-{r}" for k in ("2k", "4k")
              for r in ("16x9", "9x16", "4x3", "1x1", "3x4")]
BANANA_MODELS = BANANA_PRO + ["nano-banana2", "nano-banana-pro-2k",
                              "nano-banana-pro-4k", "nano-banana-2-2k",
                              "nano-banana-2-4k"]
IMAGE_MODELS = ["gpt-image-2", "gpt-image2-2k", "gpt-image2-4k"]

VIDEO_MODELS = GROK_MODELS + H3_MODELS + OMNI_MODELS + CHAT_VIDEO_MODELS
ALL_IMAGE_MODELS = IMAGE_MODELS + BANANA_MODELS

GROK_SIZES = ["720x1280", "1280x720", "1024x1024"]
GROK_MAX_REFS = 7
H3_RESOLUTIONS = ["768p", "480p"]
H3_RATIOS = ["9:16", "16:9"]
H3_MAX_IMAGES, H3_MAX_AUDIOS = 8, 3
IMAGE_SIZES = ["1024x1024", "1792x1024", "1024x1792", "1536x1152"]

_BRANCHES = (("grok", GROK_MODELS), ("h3", H3_MODELS), ("omni", OMNI_MODELS),
             ("chat_video", CHAT_VIDEO_MODELS), ("banana", BANANA_MODELS),
             ("image", IMAGE_MODELS))


def branch_of(model: str) -> str:
    """模型名 → 分支。认不出的按 h3 走（`/v1/videos` JSON 是这家最通用的一套）。"""
    m = (model or "").strip()
    for name, models in _BRANCHES:
        if m in models:
            return name
    if m.startswith("firefly-nano-banana") or "banana" in m:
        return "banana"
    if m.startswith("firefly-veo31") or m.startswith("sora"):
        return "chat_video"
    if m.startswith("omni-flash"):
        return "omni"
    if m.startswith("grok-video"):
        return "grok"
    return "h3"


def _to_bytes(ref: str, idx: int) -> Optional[tuple]:
    """data URI / 本机路径 → (文件名, 字节, MIME)。GROK 的 input_reference[] 要真文件。"""
    if ref.startswith("data:"):
        head, _, b64 = ref.partition(",")
        mime = head[5:].split(";")[0] or "image/png"
        ext = "png" if "png" in mime else "jpg"
        try:
            return (f"ref_{idx}.{ext}", base64.b64decode(b64), mime)
        except Exception:                                   # noqa: BLE001
            return None
    if not ref.startswith("http") and os.path.isfile(ref):
        ext = os.path.splitext(ref)[1].lstrip(".").lower() or "png"
        with open(ref, "rb") as f:
            return (f"ref_{idx}.{ext}",
                    f.read(), "image/png" if ext == "png" else "image/jpeg")
    return None


class HaomanjuProvider(Provider):
    id = "haomanju"
    name = "好漫剧 75api.com"
    aliases = ("75api", "好漫剧", "hmj", "村长")
    default_base_url = "https://www.75api.com"
    supports = ("image", "video")
    # 各分支要求不同：GROK 要文件字节、h3/omni 要链接、香蕉两种都收。
    # 声明成 data_uri（两种都能拿到），由各分支自己转。
    ref_mode = "data_uri"

    def needs_url(self, model: str = "", media: str = "video") -> bool:
        # h3 的 images 和 omni 的 image 都写明「支持 http 链接」，给 data URI 会被丢掉
        return branch_of(model) in ("h3", "omni")

    def needs_bytes(self, model: str = "") -> bool:
        # GROK 是 multipart 文件上传，给链接它不下载
        return branch_of(model) == "grok"

    def accepts_url(self, model: str = "", media: str = "image") -> bool:
        return branch_of(model) != "grok"

    def capabilities(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "default_base_url": self.default_base_url,
            "supports": list(self.supports),
            "image": {
                "models": ALL_IMAGE_MODELS,
                "default_model": "gpt-image-2",
                "sizes": IMAGE_SIZES,
                "default_size": "1024x1024",
                "max_refs": 9,
                "ref_mode": "data_uri",
                "notes": "**两条协议**：gpt-image-2 走 /v1/images/generations（有图走 edits，"
                         "multipart 字段 `image[]`）；**香蕉走 Gemini 风格的 chat/completions**，"
                         "比例和档位**写在模型名里**（firefly-nano-banana-pro-2k-16x9），"
                         "只有 nano-banana2 用顶层 `size`（如 16x9-2k）。"
                         "`1536x1152` 是这家独有的尺寸。",
            },
            "video": {
                "models": VIDEO_MODELS,
                "default_model": "minimax_h3",
                "ratios": H3_RATIOS,
                "durations": list(range(5, 16)),
                "default_duration": 10,
                "resolutions": H3_RESOLUTIONS,
                "max_refs": H3_MAX_IMAGES,
                "ref_mode": "url",
                "notes": "⚠ **四种协议按模型分派**：GROK=/v1/videos **multipart 文件上传**；"
                         "minimax_h3 与 sd-*=/v1/videos **JSON 链接数组**（同端点不同格式！）；"
                         "Omni-flash=/v1/video/generations；Sora2/VEO=chat/completions **同步返回**。"
                         "秒数/比例/分辨率在多数分支里**写在模型名里**。"
                         "VEO 帧模式(firefly-veo31-*)最多 2 张图（1=首帧、2=首尾帧），"
                         "多图参考要用 firefly-veo31-ref-*。",
            },
            "notes": "模型名有两套（文档名 / pricing 实拉名），只有 gpt-image-2 和 minimax_h3 重合；"
                     "两套都列了，跑不通就换另一套（503 不计费）。",
        }

    # ---------------------------------------------------------------- video
    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 8, poll_timeout: int = 2400) -> dict:
        model = task.model or "minimax_h3"
        br = branch_of(model)
        refs = list(task.refs or [])
        if not (task.prompt or "").strip():
            raise ApiError("好漫剧 prompt 必填", status=0, kind="task_fatal")

        if br == "grok":
            return self._grok(task, dest, model, refs, log=log, cancel=cancel,
                              poll_interval=poll_interval, poll_timeout=poll_timeout)
        if br == "omni":
            return self._omni(task, dest, model, refs, log=log, cancel=cancel,
                              poll_interval=poll_interval, poll_timeout=poll_timeout)
        if br == "chat_video":
            return self._chat_video(task, dest, model, refs, log=log)
        return self._h3(task, dest, model, refs, log=log, cancel=cancel,
                        poll_interval=poll_interval, poll_timeout=poll_timeout)

    def _grok(self, task, dest, model, refs, *, log, cancel,
              poll_interval, poll_timeout) -> dict:
        """文档一：multipart + `input_reference[]` 文件上传。

        prompt 里用 `@图1`/`@图2` 引用，编号就是 refs 的顺序 —— 顺序错了人就配错。
        """
        m = re.search(r"-(\d+)s\b", model)
        seconds = m.group(1) if m else str(int(task.duration or 10))
        size = "1280x720" if (task.ratio or "9:16") == "16:9" else "720x1280"

        files = [("model", (None, model)), ("prompt", (None, task.prompt)),
                 ("size", (None, size)), ("seconds", (None, seconds)),
                 ("resolution_name", (None, "720p"))]
        used, dropped = 0, 0
        for i, r in enumerate(refs[:GROK_MAX_REFS], 1):
            got = _to_bytes(r, i)
            if got:
                files.append(("input_reference[]", got))
                used += 1
            else:
                dropped += 1
        if dropped:
            # 静默丢掉的话，@图N 的编号会整个错位 —— 出来的人和 prompt 说的对不上
            raise ApiError(
                f"GROK 的 input_reference[] 是**文件上传**，不收链接，"
                f"这一项有 {dropped} 张给的是链接。prompt 里的 @图1/@图2 是按顺序对应的，"
                f"少一张后面全错位，所以不出这条。"
                f"关掉对象存储让参考图走本机文件，或把这类活排给收链接的分支（minimax_h3）。",
                status=0, kind="task_fatal")

        log(f"好漫剧 GROK {model}: {seconds}秒 {size} 参考图{used}张（multipart）")
        data = self.session.request("POST", "/v1/videos", files=files,
                                    retries=2, timeout=600)
        return self._wait_videos(data, dest, model, log=log, cancel=cancel,
                                 poll_interval=poll_interval, poll_timeout=poll_timeout)

    def _h3(self, task, dest, model, refs, *, log, cancel,
            poll_interval, poll_timeout) -> dict:
        """文档七：同端点但是 JSON，`images` 是 http 链接数组。"""
        urls = [r for r in refs if str(r).startswith(("http://", "https://"))]
        dropped = len(refs) - len(urls)
        if dropped:
            raise ApiError(
                f"minimax_h3 的 images 只收 http 链接，这一项有 {dropped} 张是本机图。"
                f"本该有 {len(refs)} 张参考图 —— 少了出来的就不是同一个人，所以不出这条。"
                f"去「设置 → 参考图上传」配对象存储。",
                status=0, kind="task_fatal")
        sec = max(5, min(15, int(task.duration or 10)))
        body = {
            "model": model,
            "prompt": task.prompt,
            "seconds": str(sec),                     # 文档：字符串类型
            "aspect_ratio": task.ratio or "9:16",
            "resolution": (task.resolution or "768p") if (task.resolution or "768p") in H3_RESOLUTIONS else "768p",
        }
        if urls:
            body["images"] = urls[:H3_MAX_IMAGES]
        auds = [a for a in (task.extra.get("audio_refs") or task.extra.get("audios") or [])
                if str(a).startswith("http")][:H3_MAX_AUDIOS]
        if auds:
            body["audios"] = auds

        log(f"好漫剧 H3 {model}: {sec}秒 {body['resolution']} {body['aspect_ratio']} "
            f"图{len(urls)}/音频{len(auds)}（JSON）")
        data = self.session.request("POST", "/v1/videos", json_body=body,
                                    retries=2, timeout=300)
        return self._wait_videos(data, dest, model, log=log, cancel=cancel,
                                 poll_interval=poll_interval, poll_timeout=poll_timeout)

    def _wait_videos(self, data, dest, model, *, log, cancel,
                     poll_interval, poll_timeout) -> dict:
        url = extract_video_url(data)
        task_id = extract_task_id(data)
        if not url:
            if not task_id:
                raise ApiError(f"提交没返回任务 ID：{str(data)[:300]}")
            url = self.session.poll("/v1/videos/{id}", task_id, picker=extract_video_url,
                                    content_path_tpl="/v1/videos/{id}/content",
                                    interval=poll_interval, timeout=poll_timeout,
                                    log=log, cancel=cancel)
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id, "model": model}

    def _omni(self, task, dest, model, refs, *, log, cancel,
              poll_interval, poll_timeout) -> dict:
        """文档六：`/v1/video/generations`。返回**套两层**、状态大写、进度带百分号。"""
        ratio = "landscape" if (task.ratio or "9:16") == "16:9" else "portrait"
        body = {"model": model, "prompt": task.prompt, "aspect_ratio": ratio}
        url_refs = [r for r in refs if str(r).startswith(("http://", "https://"))]
        if url_refs:
            body["image"] = url_refs[0]              # 文档只给了单张 image
            if len(url_refs) > 1:
                log(f"Omni-flash 只收单张参考图，已用第 1 张（忽略 {len(url_refs) - 1} 张）")
        if task.duration:
            body["duration"] = int(task.duration)

        log(f"好漫剧 Omni {model}: {ratio} 参考图{1 if url_refs else 0}张")
        data = self.session.request("POST", "/v1/video/generations", json_body=body,
                                    retries=2, timeout=300)
        url = extract_video_url(data)
        task_id = extract_task_id(data)
        if not url:
            if not task_id:
                raise ApiError(f"提交没返回任务 ID：{str(data)[:300]}")
            url = self._poll_generations(task_id, poll_interval, poll_timeout,
                                         log=log, cancel=cancel)
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id, "model": model}

    def _poll_generations(self, task_id: str, interval: int, timeout: int, *,
                          log, cancel=None) -> str:
        """`/v1/video/generations/{id}`。

        通用轮询器认不出这条：状态在 `data.status`（**大写 IN_PROGRESS**）、
        进度是字符串 `"30%"`，而且外面还套了一层 `{"code":"success","data":{…}}`。
        """
        start, last = time.time(), ""
        while time.time() - start < timeout:
            if cancel and cancel():
                raise ApiError("用户已取消")
            data = self.session.request("GET", f"/v1/video/generations/{task_id}",
                                        retries=1, timeout=60)
            inner = (data or {}).get("data") or {}
            status = str(inner.get("status") or "").lower()
            if status != last:
                log(f"好漫剧 Omni {task_id}: {status} {inner.get('progress', '')}")
                last = status
            if status in ("failure", "failed", "error"):
                raise ApiError(f"任务失败：{inner.get('fail_reason') or str(data)[:300]}")
            url = extract_video_url(data)
            if status in ("success", "completed", "succeeded"):
                if url:
                    return url
                raise ApiError(f"任务完成但没取到视频地址：{str(data)[:300]}")
            time.sleep(interval)
        raise ApiError(f"好漫剧 Omni 轮询超时：{task_id}", status=0, kind="retryable")

    def _chat_video(self, task, dest, model, refs, *, log) -> dict:
        """文档四、五：chat/completions **同步**返回，视频在 `<video src=…>` 里。"""
        n = len(refs)
        # ⚠ 判据必须是 `-ref-`，不能写 `"ref" in model` ——
        # **"firefly" 里就含 "ref"**（fi-ref-ly），那样写帧模式的上限永远不生效。
        is_ref_mode = "-ref-" in model
        if is_ref_mode and n > 3:
            raise ApiError(f"VEO 参考图模式最多 3 张，收到 {n} 张",
                           status=0, kind="task_fatal")
        if "veo31" in model and not is_ref_mode and n > 2:
            raise ApiError(
                f"VEO **帧模式**最多 2 张（1张=首帧、2张=首尾帧），收到 {n} 张。"
                f"要多图参考请换 firefly-veo31-ref-* 模型。",
                status=0, kind="task_fatal")

        if refs:
            parts = [{"type": "text", "text": task.prompt}]
            for r in refs:
                parts.append({"type": "image_url", "image_url": {"url": r}})
            content = parts
        else:
            content = task.prompt        # 文档：无图时 content 是纯字符串

        body = {"model": model, "messages": [{"role": "user", "content": content}]}
        log(f"好漫剧 chat视频 {model}: 参考图{n}张（同步等待）")
        data = self.session.request("POST", "/v1/chat/completions", json_body=body,
                                    retries=1, timeout=900)
        url = extract_video_url(data)
        if not url:
            raise ApiError(f"没能从 content 里取到视频地址：{str(data)[:400]}")
        self.session.save_item(url, dest)
        return {"task_id": "", "source": url, "provider": self.id, "model": model}

    # ---------------------------------------------------------------- image
    def generate_image(self, task: ImageTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 900) -> dict:
        model = task.model or "gpt-image-2"
        if not (task.prompt or "").strip():
            raise ApiError("好漫剧 prompt 必填", status=0, kind="task_fatal")
        if branch_of(model) == "banana":
            return self._banana(task, dest, model, log=log)

        size = task.size if task.size in IMAGE_SIZES else "1024x1024"
        refs = list(task.refs or [])[:9]
        files = []
        for i, r in enumerate(refs, 1):
            got = _to_bytes(r, i)
            if got:
                files.append(("image[]", got))
        if refs and not files:
            raise ApiError(
                f"这家的 edits 是 multipart、只收文件字节，{len(refs)} 张参考图全是链接。"
                f"少了参考图出来的就不是同一个人，所以不出这张图。",
                status=0, kind="task_fatal")

        if files:
            form = [("model", (None, model)), ("prompt", (None, task.prompt)),
                    ("size", (None, size)), ("n", (None, "1")),
                    ("response_format", (None, "b64_json"))]
            log(f"好漫剧 图生图 {model}: {size} 参考图{len(files)}张（multipart image[]）")
            data = self.session.request("POST", "/v1/images/edits", files=form + files,
                                        retries=2, timeout=600)
        else:
            body = {"model": model, "prompt": task.prompt, "n": int(task.n or 1),
                    "size": size, "response_format": "b64_json"}
            log(f"好漫剧 文生图 {model}: {size}")
            data = self.session.request("POST", "/v1/images/generations",
                                        json_body=body, retries=2, timeout=600)

        items = extract_image_items(data)
        if not items:
            raise ApiError(f"没返回图片：{str(data)[:300]}")
        self.session.save_item(items[0], dest)
        return {"task_id": "", "source": items[0][:200], "provider": self.id, "model": model}

    def _banana(self, task, dest, model, *, log) -> dict:
        """文档二：chat/completions，结果是 content 里的 markdown `![](url)`。

        Pro 的比例和档位**写在模型名里**；只有 nano-banana2 用顶层 `size`。
        """
        refs = list(task.refs or [])[:9]
        if refs:
            parts = [{"type": "text", "text": task.prompt}]
            for r in refs:
                parts.append({"type": "image_url", "image_url": {"url": r}})
            content = parts
        else:
            content = task.prompt
        body = {"model": model, "messages": [{"role": "user", "content": content}]}
        size = str(task.extra.get("size") or "").strip()
        if size and ("nano-banana2" in model or "nano-banana-2" in model):
            body["size"] = size                  # 只有香蕉2 认这个字段

        log(f"好漫剧 香蕉 {model}: 参考图{len(refs)}张 size={body.get('size', '(不传)')}")
        data = self.session.request("POST", "/v1/chat/completions", json_body=body,
                                    retries=1, timeout=600)
        items = extract_image_items(data)
        if not items:
            raise ApiError(f"香蕉没返回图片：{str(data)[:400]}")
        self.session.save_item(items[0], dest)
        return {"task_id": "", "source": items[0][:200], "provider": self.id, "model": model}
