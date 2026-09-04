# -*- coding: utf-8 -*-
"""超模（www.chaomoapi.com）。文档：https://www.chaomoapi.com/custom/doc

  · 图片   POST /v1/images/generations（`async:true` → GET /v1/images/{id} 轮询）
  · 图生图 POST /v1/images/edits（**multipart**，字段名 `image[]`，1–9 张）
  · 视频   POST /v1/videos → GET /v1/videos/{id}；结果在 data[].url

三个和别家形状完全不同、照抄就静默丢参数的点：

  1. **视频参考素材是 OpenAI chat 风格的 `content` 块**，不是 `images[]`：
         "content": [{"type": "image_url", "role": "reference_image",
                      "image_url": {"url": "https://…"}}]
     type 可为 image_url / video_url / audio_url。发 images:[base64] 过去不报错，
     但参考图被忽略 —— 图照出、人不对，这种静默降级最坑。
  2. **视频的 `size` 是分辨率档位**（480p/720p/1080p/4k），不是像素也不是比例。
  3. **`seconds` 是字符串**（"4"，4–15 秒）；图片那边比例字段又叫 **`ratio`**。

参考图形式：视频只收公网 URL（走 content 块）；图生图反过来**只收文件字节**
（文档原文：「参考图 URL 不能直接当文件传入：请先下载到本地，再通过 image[] 上传」）。
两边要求相反，所以 ref_mode 声明成 data_uri（两种都收），由本类内部各转各的：
拿到 data URI 就解码成字节，拿到链接就先下载 —— 配不配对象存储都能用。
"""

from __future__ import annotations

import base64
import os
from typing import Callable, Optional

import requests

from ..apiutil import (ApiError, _b64_bytes, extract_image_items,
                       extract_task_id, extract_video_url)
from .base import ImageTask, Provider, VideoTask

VIDEO_MODELS = ["seedance2", "seedance2-fast", "seedance2-mini"]
IMAGE_MODELS = [
    # Native 三档：官方原生接口，2026-08 确认在售
    "gpt-image2-1K-Native", "gpt-image2-2K-Native", "gpt-image2-4K-Native",
    "gpt-image2-1K", "gpt-image2-2K-low", "gpt-image2-4K-low",
    "gpt-image2-2K-Direct", "gpt-image2-4K-Direct", "gpt-image2-4K",
    "gpt-image-1k-th",
    "gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview",
]
RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "2:3", "3:2", "21:9"]
SIZES = ["480p", "720p", "1080p", "4k"]          # 视频 size = 分辨率档位
MAX_REFS = 9

_RATIO_VALUES = {"21:9": 21 / 9, "16:9": 16 / 9, "3:2": 1.5, "4:3": 4 / 3,
                 "1:1": 1.0, "3:4": 3 / 4, "2:3": 2 / 3, "9:16": 9 / 16}


def _to_ratio(want: str, default: str = "9:16") -> str:
    """'9:16' 直接用；'1024x1536' 这种像素换算成最接近的比例（这家只认 ratio）。"""
    s = (want or "").strip().lower().replace("×", "x").replace("：", ":")
    if s in RATIOS:
        return s
    val = _RATIO_VALUES.get(s, 0.0)
    if not val:
        try:
            w, h = s.split("x")[:2]
            val = int(w) / int(h)
        except Exception:                                   # noqa: BLE001
            return default
    return min(RATIOS, key=lambda r: abs(_RATIO_VALUES[r] - val))


def _to_size(resolution: str, default: str = "720p") -> str:
    """视频的 size 是档位：'1080p' / '1920x1080' / '4K' 都归到 480p/720p/1080p/4k。"""
    s = (resolution or "").strip().lower().replace("×", "x")
    if s in SIZES:
        return s
    if s in ("2k", "1440p"):
        return "1080p"          # 没有 2K 档，就近取高的那档
    try:                        # 给了像素就按短边归档
        w, h = (int(x) for x in s.split("x")[:2])
        short = min(w, h)
    except Exception:                                       # noqa: BLE001
        return default
    for edge, name in ((2160, "4k"), (1080, "1080p"), (720, "720p")):
        if short >= edge:
            return name
    return "480p"


# 文件头魔数：写成字节数组，避免任何转义在多层工具间被吃掉
PNG_MAGIC = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
JPEG_MAGIC = bytes([0xFF, 0xD8])


def _header_size(path: str) -> tuple:
    """只读文件头拿宽高，不用 Pillow（一批几百张，逐张解码太慢）。

    返回 (宽, 高)，认不出返回 (0, 0)。够用了：缩略图和原图差的是数量级，
    不需要精确到像素级的校验。
    """
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if head.startswith(PNG_MAGIC):
                # IHDR 紧跟在 8 字节签名 + 4 字节长度 + 4 字节类型之后
                return (int.from_bytes(head[16:20], "big"),
                        int.from_bytes(head[20:24], "big"))
            if head.startswith(JPEG_MAGIC):
                f.seek(2)
                while True:
                    b = f.read(2)
                    if len(b) < 2 or b[0] != 0xFF:
                        return (0, 0)
                    if 0xC0 <= b[1] <= 0xCF and b[1] not in (0xC4, 0xC8, 0xCC):
                        f.read(3)                       # 段长(2) + 精度(1)
                        h = int.from_bytes(f.read(2), "big")
                        w = int.from_bytes(f.read(2), "big")
                        return (w, h)
                    seg = int.from_bytes(f.read(2), "big")
                    f.seek(seg - 2, 1)
    except Exception:                                   # noqa: BLE001
        pass
    return (0, 0)


def _block(kind: str, url: str) -> dict:
    """一个 content 块。kind ∈ image / video / audio。"""
    return {"type": f"{kind}_url",
            "role": "reference_image" if kind == "image" else f"reference_{kind}",
            f"{kind}_url": {"url": url}}


class ChaomoProvider(Provider):
    id = "chaomo"
    name = "超模 chaomoapi.com"
    aliases = ("chaomoapi", "超模", "cm")
    default_base_url = "https://www.chaomoapi.com"
    supports = ("image", "video")
    # 图生图能吃字节（本类会把 data URI 解码、把链接下载），视频只收链接 → 见 needs_url
    ref_mode = "data_uri"

    def needs_url(self, model: str = "", media: str = "image") -> bool:
        # 视频的 content 块只放 url，本地图必须先换成链接；
        # 图片反过来只能上传文件，所以这里只对视频声明。
        return media == "video"

    def capabilities(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "default_base_url": self.default_base_url,
            "supports": list(self.supports),
            "image": {
                "models": IMAGE_MODELS,
                "default_model": "gpt-image2-1K",
                "sizes": RATIOS,                 # 这家图片的"尺寸"就是比例
                "default_size": "9:16",
                "max_refs": MAX_REFS,
                "ref_mode": "bytes",
                "notes": "比例字段是 **ratio**（不是 size/aspect_ratio），n 固定 1，异步"
                         "（async:true → 轮询 /v1/images/{id}）。有参考图时走 /v1/images/edits，"
                         "**multipart 字段名是 image[]**：文档明写参考图 URL 不能直传，"
                         "本类会自动把链接下载成文件再上传。",
            },
            "video": {
                "models": VIDEO_MODELS,
                "default_model": "seedance2",
                "ratios": RATIOS,
                "durations": list(range(4, 16)),
                "default_duration": 8,
                "resolutions": SIZES,
                "max_refs": MAX_REFS,
                "ref_mode": "url",
                "notes": "参考素材走 **content 块**（[{type:image_url,role:reference_image,"
                         "image_url:{url}}]），不是 images[] —— 发错不报错，参考图直接被忽略。"
                         "`seconds` 是字符串 4–15；`size` 是分辨率档位（480p/720p/1080p/4k），"
                         "文档没有独立比例字段。",
            },
            "notes": "图片和视频端点、字段名完全两套，别混用解析逻辑。",
        }

    # ---------------------------------------------------------------- 内部
    def _ref_bytes(self, ref: str, idx: int) -> tuple:
        """参考图 → (bytes, filename, content_type)。data URI 解码；http 链接先下载。"""
        if ref.startswith("data:"):
            head, _, payload = ref.partition(",")
            ctype = head[5:].split(";")[0] or "image/png"
            ext = {"image/jpeg": "jpg", "image/webp": "webp"}.get(ctype, "png")
            try:
                return (base64.b64decode(payload), f"ref_{idx}.{ext}", ctype)
            except Exception:                               # noqa: BLE001
                return ()
        if ref.startswith(("http://", "https://")):
            # 文档：URL 不能直传，必须先下载到本地再上传
            try:
                r = requests.get(ref, timeout=self.session.timeout,
                                 proxies=self.session._proxies())
                r.raise_for_status()
            except Exception as exc:                        # noqa: BLE001
                raise ApiError(f"超模图生图要求上传文件，下载参考图失败: {ref[:80]} ({exc})")
            ctype = (r.headers.get("Content-Type") or "image/png").split(";")[0]
            ext = {"image/jpeg": "jpg", "image/webp": "webp"}.get(ctype, "png")
            return (r.content, f"ref_{idx}.{ext}", ctype)
        return ()

    @staticmethod
    def meta_of(data) -> dict:
        """取 include_metadata 回来的核验信息（实际宽高 / 格式 / 字节数 / 耗时）。"""
        if not isinstance(data, dict):
            return {}
        for key in ("metadata", "meta", "info"):
            v = data.get(key)
            if isinstance(v, dict):
                return v
        arr = data.get("data")
        if isinstance(arr, list) and arr and isinstance(arr[0], dict):
            v = arr[0].get("metadata")
            if isinstance(v, dict):
                return v
        return {}

    @staticmethod
    def check_meta(meta: dict, items: list, *, dest: str = "", log=print) -> None:
        """拿网关自报的字节数核对手里的数据 —— 判断「有没有被截断」的硬证据。

        文档说 include_metadata 给的是「**可核验的**实际图片宽高、格式和字节数」，
        那就真拿来核验。对不上就当场报错：出来的图缺一块，比没有更糟 ——
        任务会标 ok，没人知道那张资产是残的。
        """
        if not meta:
            return
        size = next((meta.get(k) for k in ("bytes", "size_bytes", "byte_size", "file_size")
                     if isinstance(meta.get(k), (int, float))), None)
        desc = "  ".join(f"{k}={meta[k]}" for k in
                         ("width", "height", "format", "bytes", "size_bytes", "elapsed")
                         if k in meta)
        if desc:
            log(f"超模 核验信息: {desc}")
        if not size:
            return
        # 落盘文件核验：**这条专治「拿回来的是网页缩略图」**。
        # 缩略图是一张完整合法的小图 —— 有正确的结尾标记、体积也远超 MIN_BYTES，
        # save_item 那两道检查全都放行，于是任务标 ok、资产却是模糊的。
        # include_metadata 给的宽高和字节数是网关自报的原图规格，拿来一比就露馅。
        if dest and os.path.isfile(dest):
            got = os.path.getsize(dest)
            w, h = _header_size(dest)
            want_w = meta.get("width") if isinstance(meta.get("width"), int) else 0
            want_h = meta.get("height") if isinstance(meta.get("height"), int) else 0
            if want_w and want_h and w and h and (w < want_w * 0.9 or h < want_h * 0.9):
                os.remove(dest)                # 留着下次 isfile 为真会被当成"已做过"跳过
                raise ApiError(
                    f"超模说这张图是 {want_w}x{want_h}，实际存下来只有 {w}x{h} —— "
                    f"**拿到的是缩略图，不是原图**。缩略图是完整合法的小图，"
                    f"体积和结尾标记都正常，光靠大小检查发现不了。"
                    f"多半是结果里同时给了预览图和原图、挑错了链接。不收这张。",
                    status=0, kind="task_fatal")
            if size and got < int(size) * 0.6:
                os.remove(dest)
                raise ApiError(
                    f"超模说这张图有 {int(size)} 字节，落盘只有 {got} 字节"
                    f"（{got * 100 // int(size)}%）—— 多半是缩略图或半截图，不收。",
                    status=0, kind="task_fatal")

        for item in items:
            if not (isinstance(item, str) and item.startswith("data:")):
                continue                       # URL 结果已在上面按落盘文件核验过
            try:
                got = len(_b64_bytes(item.split(",", 1)[1], item))
            except Exception:                                   # noqa: BLE001
                continue
            if got < int(size) * 0.98:         # 留 2% 容差（元数据可能不含容器开销）
                raise ApiError(
                    f"超模说这张图有 {int(size)} 字节，实际只收到 {got} 字节"
                    f"（缺 {int(size) - got}）。数据在传输途中丢了，不出这张图 —— "
                    f"残图比没有更糟，任务会标 ok 但资产是坏的。"
                    f"本类已对图生图开启 async（异步固定返回 URL），"
                    f"还出现说明这条线路本身不稳，把这类活排给别家。",
                    status=0, kind="task_fatal")

    def _pick_images(self, data, task_id_hint: str, *, log, poll_interval,
                     poll_timeout) -> tuple:
        """返回 (图片清单, 最终那份响应)。

        **第二个返回值是必须的。** 我们开了 async，图在轮询结果里，
        而核验用的 metadata（宽高/格式/字节数）也在那一份里 ——
        拿提交时的响应去 check_meta，永远是空的，那道核对等于没接。
        """
        items = extract_image_items(data)
        if items:
            return items, data
        tid = extract_task_id(data) or task_id_hint
        if not tid:
            raise ApiError(f"未取到图片也没有任务 ID: {str(data)[:300]}")
        log(f"超模 图片任务 {tid} 已提交，开始轮询")
        last = {}

        def pick(payload):
            last["data"] = payload          # 留住最终那份，metadata 在里面
            return extract_image_items(payload)

        got = self.session.poll("/v1/images/{id}", tid, picker=pick,
                                interval=poll_interval, timeout=poll_timeout, log=log)
        return (got if isinstance(got, list) else [got]), last.get("data") or data

    # ---------------------------------------------------------------- image
    def generate_image(self, task: ImageTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 900) -> dict:
        model = task.model or "gpt-image2-1K"
        ratio = _to_ratio(task.size)
        refs = list(task.refs or [])[:MAX_REFS]

        if refs:
            # 图生图：multipart，字段名是 image[]（复数带方括号，别写成 image / images）
            #
            # ⚠ async 必须发。文档原文：「response_format：url 或 b64_json；
            # **异步任务固定返回 URL 结果**」。不发 async 就是同步，网关会把几 MB 的
            # PNG 塞进 JSON 的 base64 字段回来 —— 那条路上任何一处丢字节，整张图报废。
            # 实跑撞过：超模一批资产全是 0KB，报错只有一句 Incorrect padding。
            # 走异步拿 URL 直接下载，整条 base64 传输链就不存在了。
            files = [("model", (None, model)), ("prompt", (None, task.prompt or "")),
                     ("ratio", (None, ratio)), ("n", (None, "1")),
                     ("response_format", (None, "url")),
                     ("async", (None, "true")),
                     # quality：文档示例用 high。只有调用方明确指定才发，不猜。
                     *([("quality", (None, str(task.extra["quality"])))]
                       if task.extra.get("quality") else []),
                     # 返回可核验的实际宽高/格式/**字节数**，用来核对有没有传丢
                     ("include_metadata", (None, "true"))]
            attached = 0
            for i, ref in enumerate(refs, start=1):
                got = self._ref_bytes(ref, i)
                if got:
                    files.append(("image[]", (got[1], got[0], got[2])))
                    attached += 1
            # **数 image[] 的条数，别数 files 的长度。**
            # 原来写的是 `if len(files) == 5`（当时基数正好 5）。后来加了
            # async / include_metadata / quality，基数变成 7 甚至 8 ——
            # 这个判断就永远不成立了，于是「一张参考图都没转成文件」时
            # 照样把请求发出去：出来的图不是同一个人，而任务标 ok。
            # 拿魔法数字当哨兵，加一个字段就会把它悄悄废掉。
            if not attached:
                raise ApiError(f"超模图生图：{len(refs)} 张参考图一张都没转成文件，不出这张图 —— "
                               f"少了参考图出来的就不是同一个人。")
            log(f"超模 图生图 {model}: ratio={ratio} 参考图{attached}张（multipart image[]）")
            data = self.session.request("POST", "/v1/images/edits", files=files,
                                        retries=2, timeout=600)
        else:
            body = {"model": model, "prompt": task.prompt, "ratio": ratio,
                    "n": 1, "response_format": "url", "async": True,
                    # 文档：返回可核验的实际图片宽高、格式和字节数
                    "include_metadata": True}
            if task.extra.get("quality"):
                body["quality"] = str(task.extra["quality"])
            log(f"超模 文生图 {model}: ratio={ratio}")
            data = self.session.request("POST", "/v1/images/generations", json_body=body,
                                        retries=2, timeout=600)

        items, final = self._pick_images(
            data, "", log=log, poll_interval=poll_interval, poll_timeout=poll_timeout)
        if not items:
            raise ApiError(f"出图没返回可用结果: {str(data)[:300]}")
        self.session.save_item(items[0], dest)
        # 核验放在落盘之后：URL 结果只有存下来才量得到真实宽高
        self.check_meta(self.meta_of(final), items, dest=dest, log=log)
        return {"task_id": extract_task_id(data), "source": items[0][:200],
                "provider": self.id, "model": model}

    # ---------------------------------------------------------------- video
    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 2400) -> dict:
        model = task.model or "seedance2"
        sec = int(task.duration or 8)
        if not 4 <= sec <= 15:
            near = min(15, max(4, sec))
            log(f"超模 {model} 只支持 4–15 秒，已把 {sec} 纠正为 {near}")
            sec = near
        size = _to_size(task.resolution)

        refs = list(task.refs or [])[:MAX_REFS]
        local = [r for r in refs if not str(r).startswith(("http://", "https://"))]
        if local:
            # content 块只放 url，本地图丢了不会报错、只会静默不参考 —— 那更糟
            raise ApiError(
                f"超模视频的参考素材走 content 块，只收公网 URL，这一项给的 {len(local)} 张是本地图。"
                f"本该有 {len(refs)} 张参考图 —— 少了出来的就不是同一个人/同一个东西，所以不出这条。"
                f"去「设置 → 参考图上传」配对象存储（配好后本机图会自动传成链接），"
                f"或者把这类活排给收本地图的服务商。",
                status=0, kind="task_fatal")

        body: dict = {"model": model, "prompt": task.prompt or "",
                      "seconds": str(sec), "size": size}          # seconds 是字符串
        if refs:
            body["content"] = [_block("image", r) for r in refs]
        log(f"超模 {model}: seconds='{sec}' size={size} content块{len(refs)}项")

        data = self.session.request("POST", "/v1/videos", json_body=body,
                                    retries=2, timeout=300)
        url = extract_video_url(data)
        task_id = extract_task_id(data)
        if not url:
            if not task_id:
                raise ApiError(f"提交没返回任务 ID: {str(data)[:300]}")
            url = self.session.poll("/v1/videos/{id}", task_id, picker=extract_video_url,
                                    interval=poll_interval, timeout=poll_timeout,
                                    log=log, cancel=cancel)
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id, "model": model}
