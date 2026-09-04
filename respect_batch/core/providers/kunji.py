# -*- coding: utf-8 -*-
"""坤鸡（img.yunfei.best）。对齐 respect_comfyui/kunji_nodes.py。

**三条互不相同的协议**，选模型就等于选协议：

  1. `gpt-image-2` —— OpenAI 兼容。无参考图 `POST /v1/images/generations`(JSON)、
     有参考图 `POST /v1/images/edits`(**multipart，要真文件字节，不收链接**)
  2. **香蕉**(`gemini-3-*-image-preview`) —— **Gemini 原生格式**：
     `POST /v1beta/models/{model}:generateContent`，模型名在**路径**里不在 body，
     参考图是 `inline_data`/`file_data` 部件，尺寸走 `imageConfig.imageSize`
  3. **veo 视频**(`veo-3.1-*`) —— `POST /v1/videos` + 轮询，720p、4/6/8 秒

⚠ **4K 是按令牌分组的，不是模型的区别**（文档原文：「1K 分组最高支持 1K；
4K 分组支持 1K/2K/4K」「high 分组支持 high」）。所以同一把 Key 拿不到两档 ——
要用 4K 就得有 4K 分组的 Key。本类允许在 api_key 里**一次填多把**，见 `parse_keys`。

香蕉那条线不看分组，`imageSize` 直接给 4K。

⚠ 出图返回的 URL **只保存 15 分钟**，尽快下载（本程序落盘是即时的，不受影响）。
"""

from __future__ import annotations

import base64
import os
import re
from typing import Callable, Optional

from ..apiutil import ApiError, extract_image_items, extract_task_id, extract_video_url
from .base import ImageTask, Provider, VideoTask

IMAGE_MODELS = [
    # 2026-08-19 实拉：/v1/models 只返回 gpt-image-2（按令牌分组过滤后），
    # /api/pricing 另列两个 gemini。旧清单里的 gpt-image-1 / nano-banana 查不到。
    "gpt-image-2",
    "gemini-3-pro-image-preview",       # 香蕉 Pro：画质档
    "gemini-3.1-flash-image-preview",   # 香蕉2：速度档，额外支持超宽比例
]
BANANA_MODELS = ("gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview")
VIDEO_MODELS = ["veo-3.1-fast-generate-preview", "veo-3.1-generate-preview",
                "veo-3.1-generate-preview-ref"]
# 档位写法和像素写法都收（文档正文用档位、curl 示例用像素）
SIZES = ["1K", "2K", "4K", "1024x1536", "1024x1024", "1536x1024",
         "2048x2048", "1792x1024", "1024x1792"]
BANANA_SIZES = ["1K", "2K", "4K"]          # **K 必须大写**
BANANA_RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3",
                 "5:4", "4:5", "21:9"]
# 这 4 个超宽只有香蕉2支持
BANANA_WIDE_ONLY = ("8:1", "4:1", "1:4", "1:8")
VIDEO_RATIOS = ["16:9", "9:16"]
VIDEO_DURATIONS = [4, 6, 8]

# api_key 里可以按分组填多把
_KEY_ALIAS = {"1k": "1k", "2k": "2k", "4k": "4k", "high": "high", "default": "default"}


def parse_keys(api_key: str) -> dict:
    """把 api_key 解成 {分组: key}。

    **4K 要单独的 Key**（文档：4K 分组才支持 1K/2K/4K），所以一个字段得能装多把。
    两种写法都认，用户手上是客服发的一段文本，别逼他学格式：

      · 单把：`sk-xxx`                      → 所有档位都用它
      · 多把：`1k=sk-aaa;4k=sk-bbb;high=sk-ccc`

    没配到的档位回落到 `default`（多把写法里没写 default 就用第一把）。
    """
    raw = (api_key or "").strip()
    if not raw:
        return {}
    if "=" not in raw:
        return {"default": raw}
    out = {}
    for part in re.split(r"[;\n]+", raw):
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        key = _KEY_ALIAS.get(k.strip().lower())
        if key and v.strip():
            out[key] = v.strip()
    if out and "default" not in out:
        out["default"] = next(iter(out.values()))
    return out


def _to_bytes(ref: str, idx: int) -> Optional[tuple]:
    """data URI / 本机路径 → (文件名, 字节, MIME)。公网 URL 这家的 edits 吃不了。"""
    if ref.startswith("data:"):
        head, _, b64 = ref.partition(",")
        mime = head[5:].split(";")[0] or "image/png"
        ext = "png" if "png" in mime else "jpg"
        try:
            return (f"ref_{idx}.{ext}", base64.b64decode(b64), mime)
        except Exception:                       # noqa: BLE001
            return None
    if not ref.startswith("http") and os.path.isfile(ref):
        ext = os.path.splitext(ref)[1].lstrip(".").lower() or "png"
        mime = "image/png" if ext == "png" else "image/jpeg"
        with open(ref, "rb") as f:
            return (f"ref_{idx}.{ext}", f.read(), mime)
    return None


class KunjiProvider(Provider):
    id = "kunji"
    name = "坤鸡 img.yunfei.best（图片 + veo视频）"
    aliases = ("yunfei", "坤鸡", "banana")
    default_base_url = "https://img.yunfei.best"
    supports = ("image", "video")
    # **Key 分四把各自填**（页面上跟超模一样，一把一个框）。
    # 存回 api_key 时拼成 `1k=…;4k=…;high=…;default=…`，`parse_keys` 认这个。
    # 只填一把也行 —— 那把当所有档位的默认。
    key_fields = (
        ("image_1k_api_key", "1k", "图片 1K Key",
         "最高只出 1K。只填这一把的话，选 2K/4K 会被静默降级"),
        ("image_4k_api_key", "4k", "图片 4K Key",
         "1K/2K/4K 都能出。要 4K 就必须有这一把"),
        ("image_high_api_key", "high", "图片 high Key",
         "只有 quality=high 那条线用；没有就留空"),
        ("video_api_key", "default", "视频 Key",
         "veo 出片用。没配分组的档位也回落到它"),
    )
    # gpt-image-2 的 edits 是 multipart，只收文件字节；香蕉和 veo 收链接/base64。
    # 默认按最严的 bytes 声明，香蕉那条在 accepts_url 里放开。
    ref_mode = "bytes"

    def __init__(self, api_key: str = "", base_url: str = "", proxy: str = "",
                 timeout: int = 900):
        super().__init__(api_key=api_key, base_url=base_url, proxy=proxy, timeout=timeout)
        self.keys = parse_keys(api_key)

    # -- 分组 Key -------------------------------------------------------
    def key_for(self, size: str = "", quality: str = "") -> str:
        """按要出的档位挑 Key。

        **4K 要 4K 分组的 Key**，拿 1K 分组的 Key 去要 4K 只会被降级或拒 ——
        而降级是静默的：你以为出了 4K，实际拿到 1K。所以这里按档位切。
        """
        if not self.keys:
            return ""
        want = (size or "").strip().upper()
        if (quality or "").strip().lower() == "high" and "high" in self.keys:
            return self.keys["high"]
        for tier in ("4K", "2K", "1K"):
            if want.startswith(tier) and tier.lower() in self.keys:
                return self.keys[tier.lower()]
        return self.keys.get("default", "")

    def _with_key(self, key: str):
        """临时把会话切到指定 Key。没配分组就用原来的，不折腾。"""
        if key and key != self.session.api_key:
            self.session.api_key = key

    def accepts_url(self, model: str = "", media: str = "image") -> bool:
        # 香蕉的 file_data 收公网 URL；gpt-image-2 的 edits 只收字节；视频收 URL
        return media == "video" or (model or "") in BANANA_MODELS

    def needs_bytes(self, model: str = "") -> bool:
        return (model or "gpt-image-2") not in BANANA_MODELS

    def capabilities(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "default_base_url": self.default_base_url,
            "supports": list(self.supports),
            "image": {
                "models": IMAGE_MODELS,
                "default_model": "gpt-image-2",
                "sizes": SIZES,
                "default_size": "1K",
                "ratios": BANANA_RATIOS + list(BANANA_WIDE_ONLY),
                "max_refs": 9,
                "ref_mode": "data_uri",
                "notes": "**两条协议**：gpt-image-2 走 OpenAI 兼容（有参考图=multipart 的 edits，"
                         "要真文件字节不收链接）；**香蕉**(gemini-3-*) 走 Gemini 原生 "
                         "generateContent，模型名在路径里、尺寸走 imageSize(1K/2K/4K，K大写)。"
                         "⚠ **4K 按令牌分组**：gpt-image-2 要 4K 分组的 Key 才出得了 4K，"
                         "香蕉那条不看分组。多把 Key 可以一起填：`1k=sk-a;4k=sk-b;high=sk-c`。"
                         "8:1/4:1/1:4/1:8 超宽只有香蕉2支持。出图 URL 只存 15 分钟。",
            },
            "video": {
                "models": VIDEO_MODELS,
                "default_model": "veo-3.1-fast-generate-preview",
                "ratios": VIDEO_RATIOS,
                "durations": VIDEO_DURATIONS,
                "default_duration": 4,
                "resolutions": ["720p"],
                "max_refs": 9,
                "ref_mode": "url",
                "notes": "veo-3.1，固定 720p、只有 4/6/8 秒。单图用 image_url、"
                         "首尾帧和多参考用 image_urls。**多参考图必须用 -ref 模型，"
                         "且固定 8 秒 + 16:9** —— 传 4/6 秒或 9:16 会生成失败（不扣费）。"
                         "图片不支持 {data,mime_type} 对象格式。failed 不扣费。",
            },
            "notes": "同一家三条协议：gpt-image-2 / 香蕉(Gemini原生) / veo视频。选模型即选协议。",
        }

    # ---------------------------------------------------------------- image
    def generate_image(self, task: ImageTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 900) -> dict:
        model = task.model or "gpt-image-2"
        size = task.size or "1K"
        if not (task.prompt or "").strip():
            raise ApiError("提示词是空的")
        self._with_key(self.key_for(size, str(task.extra.get("quality") or "")))

        if model in BANANA_MODELS:
            return self._banana(task, dest, model, size, log=log)

        files, dropped = [], []
        for i, r in enumerate(task.refs[:9], 1):
            got = _to_bytes(r, i)
            if got:
                files.append(("image[]", got))      # 文档：image / image[] 都行，多张用 image[]
            else:
                dropped.append(i)
        if dropped:
            raise ApiError(
                f"这家的 edits 只收文件字节，不收链接，第 {dropped} 张参考图给的是链接。"
                f"本该有 {len(task.refs)} 张参考图，能用的只有 {len(files)} 张 —— "
                f"少了参考图出来的就不是同一个人/同一个东西，所以不出这张图。"
                f"要么把这一类活排给收链接的服务商，要么关掉对象存储让参考图走本机文件。",
                status=0, kind="task_fatal")

        common = [("model", (None, model)), ("prompt", (None, task.prompt)),
                  ("size", (None, size)), ("response_format", (None, "b64_json")),
                  ("n", (None, "1"))]                # 文档：n 请固定传 1
        if task.extra.get("quality"):
            common.append(("quality", (None, str(task.extra["quality"]))))
        if files:
            data = self.session.request("POST", "/v1/images/edits", files=common + files,
                                        retries=2, timeout=600)
        else:
            body = {"model": model, "prompt": task.prompt, "size": size,
                    "response_format": "b64_json", "n": 1}
            if task.extra.get("quality"):
                body["quality"] = str(task.extra["quality"])
            data = self.session.request("POST", "/v1/images/generations", json_body=body,
                                        retries=2, timeout=600)

        items = extract_image_items(data)
        if not items:
            raise ApiError(f"没返回图片：{str(data)[:300]}")
        self.session.save_item(items[0], dest)
        return {"task_id": "", "source": items[0][:200], "provider": self.id, "model": model}

    def _banana(self, task: ImageTask, dest: str, model: str, size: str, *, log) -> dict:
        """香蕉：Gemini 原生 generateContent。模型名在**路径**里，不在 body。"""
        ratio = str(task.extra.get("ratio") or "").strip()
        if ratio in BANANA_WIDE_ONLY and "3.1-flash" not in model:
            raise ApiError(
                f"{ratio} 这种超宽比例只有香蕉2（gemini-3.1-flash-image-preview）支持，"
                f"当前是 {model}。", status=0, kind="task_fatal")
        tier = size if size in BANANA_SIZES else "1K"

        parts = [{"text": task.prompt}]
        for r in (task.refs or [])[:9]:
            if r.startswith("data:"):
                head, _, b64 = r.partition(",")
                parts.append({"inline_data": {
                    "mime_type": head[5:].split(";")[0] or "image/png", "data": b64}})
            elif r.startswith(("http://", "https://")):
                parts.append({"file_data": {"mime_type": "image/png", "file_uri": r}})
        img_cfg = {"imageSize": tier}
        if ratio:
            # 文档：需要自动比例时**省略**，不要传 auto
            img_cfg["aspectRatio"] = ratio
        body = {"contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"responseModalities": ["IMAGE"],
                                     "imageConfig": img_cfg}}

        path = f"/v1beta/models/{model}:generateContent"
        log(f"坤鸡 香蕉 {model}: imageSize={tier} aspectRatio={ratio or '(自动)'} "
            f"参考图{len(parts) - 1}项")
        data = self.session.request("POST", path, json_body=body, retries=2, timeout=600)

        items = []
        try:
            for part in data["candidates"][0]["content"]["parts"]:
                inline = part.get("inline_data") or part.get("inlineData") or {}
                if inline.get("data"):
                    mime = inline.get("mime_type") or inline.get("mimeType") or "image/png"
                    items.append(f"data:{mime};base64,{inline['data']}")
                fd = part.get("file_data") or part.get("fileData") or {}
                uri = fd.get("file_uri") or fd.get("fileUri")
                if uri:
                    items.append(uri)
        except (KeyError, IndexError, TypeError):
            pass
        items = items or extract_image_items(data)
        if not items:
            raise ApiError(f"香蕉没返回图片：{str(data)[:300]}")
        self.session.save_item(items[0], dest)
        return {"task_id": "", "source": items[0][:200], "provider": self.id, "model": model}

    # ---------------------------------------------------------------- video
    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 8, poll_timeout: int = 1800) -> dict:
        model = task.model or "veo-3.1-fast-generate-preview"
        self._with_key(self.keys.get("default", ""))
        refs = [r for r in (task.refs or []) if str(r).startswith(("http", "data:"))]
        dur = int(task.duration or 4)
        ratio = task.ratio or "16:9"

        multi = len(refs) > 2 or bool(task.extra.get("multi_ref"))
        if multi:
            # 文档：多参考图必须 -ref 模型，且**固定 8 秒 + 16:9**；
            # 传 4/6 秒或 9:16 会生成失败 —— 失败虽不扣费，但白等一整轮轮询。
            if "-ref" not in model:
                raise ApiError(
                    f"多参考图必须用 veo-3.1-generate-preview-ref，当前是 {model}。",
                    status=0, kind="task_fatal")
            if dur != 8 or ratio != "16:9":
                log(f"坤鸡 veo 多参考图固定 8 秒 + 16:9，已把 {dur}秒/{ratio} 纠正")
                dur, ratio = 8, "16:9"
        if dur not in VIDEO_DURATIONS:
            near = min(VIDEO_DURATIONS, key=lambda d: abs(d - dur))
            log(f"坤鸡 veo 只有 {VIDEO_DURATIONS} 秒，已把 {dur} 纠正为 {near}")
            dur = near

        body = {"model": model, "prompt": task.prompt, "duration": dur,
                "aspect_ratio": ratio,
                "generate_audio": bool(task.extra.get("generate_audio", True))}
        if task.extra.get("negative_prompt"):
            body["negative_prompt"] = str(task.extra["negative_prompt"])
        if multi:
            body["image_urls"] = refs
        elif len(refs) == 2:
            body["image_urls"] = refs               # [首帧, 尾帧]
        elif refs:
            body["image_url"] = refs[0]             # 单个字符串，不是数组

        log(f"坤鸡 veo {model}: {dur}秒 {ratio} 参考图{len(refs)}张")
        data = self.session.request("POST", "/v1/videos", json_body=body,
                                    retries=2, timeout=300)
        url = extract_video_url(data)
        task_id = extract_task_id(data)
        if not url:
            if not task_id:
                raise ApiError(f"提交没返回任务 ID：{str(data)[:300]}")
            url = self.session.poll("/v1/videos/{id}", task_id, picker=extract_video_url,
                                    interval=poll_interval, timeout=poll_timeout,
                                    log=log, cancel=cancel)
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id, "model": model}
