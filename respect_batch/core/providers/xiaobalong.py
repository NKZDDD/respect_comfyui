# -*- coding: utf-8 -*-
"""小霸龙（api.keik.cc）。文档：小霸龙 API 统一图片与视频接口文档 r21（2026-07-30）

  · 图片 **同步** POST /v1/images/generations —— 直接返回 data[]，没有任务 ID、不轮询
  · 视频 **异步** POST /v1/videos → GET /v1/videos/{id} → GET /v1/videos/{id}/content
  · 素材上传 POST /v1/assets/uploads（渠道无关）→ asset://xiaobalong/...，**24 小时有效**

这家最要命的一条是计费安全规则（文档原文）：

    图片和视频的创建 POST 都只能提交一次，**客户端不得自动重试**。

所以本类所有创建请求都是 retries=1（只发一次）。网络中断/超时/没拿到任务 ID 一律
不重投 —— 那可能已经越过计费边界，重投等于再扣一次钱。

其余几个必须记住的差异：
  1. 图片比例字段是 **ratio**（`size` 仅在含 ':' 时当别名），数量字段推荐 **count**（1–4，按张计费）
  2. 图片 HTTP 200 **不等于成功**：`error` 非空或 `data: []` 都按失败处理（且不结算）
  3. 视频统一用 **duration 整数**；素材是**纯字符串数组** images/videos/audios（≤9/≤3/≤3），
     **不能用对象数组**
  4. 状态多一个 **unknown** —— 不是失败、也不是可重投信号，只能继续低频查
     （DONE_STATES / FAIL_STATES 都不含它，poll 会自然继续，别自作聪明加进去）
  5. 创建阶段叫 processing、查询阶段叫 in_progress，两个都要认
  6. 结果 metadata.url 指向 /v1/videos/{id}/content，是**要鉴权的代理**，不是公开直链
     （save_item 对本站地址会自动带 Bearer）
  7. asset:// URI 文档**只承诺用于视频素材**；图片参考图必须是执行服务能读取的公网 URL
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from ..apiutil import (ApiError, extract_image_items, extract_task_id,
                       extract_video_url)
from .base import ImageTask, Provider, VideoTask

IMAGE_MODELS = ["gemini-3-pro-image", "gemini-3.1-flash-image",
                "image2", "image2-2k4k", "image2-4k", "image2-high"]
# 2026-08-16 从 GET /api/pricing（公开可读）实拉，**不是文档 r21 里那批**。
# r21（2026-07-30）列的 bh2.0-* / gz-sd480p / sdvip* / doubaofast / quanneng2.0 /
# fd-Seedance 2.0 933 / video-standard-720p / B-quannengship2.0 现在全查不到，
# 20 个只活下来 sd2-fast福利 和 sd2-福利。这家换模型很勤，文档自己也写了别硬编码 ——
# list_models() 拿到的实时清单优先于这里。
VIDEO_MODELS = [
    "sd2-mini-480p", "sd2-mini-720p", "sd2-720p-933", "sd2.5-480p-301010",
    "sd2.0-720p-903", "sd2-720p-high", "sd2.5-720p-301010", "sd2-标准720p",
    "sd2-900", "sd2-fast福利", "sd2-fast-933", "sd2-福利",
    "sd2-720p-福利", "sd2-720p-quan", "gz-sd2-720p",
]
# 2026-08-16 实时单价（USD），仅供排优先级链时估成本；结算以实时 /api/pricing 为准
VIDEO_PRICES = {
    "sd2-mini-480p": 0.028767123287, "sd2-mini-720p": 0.038356164383,
    "sd2-720p-933": 0.04200913242, "sd2.5-480p-301010": 0.049315068493,
    "sd2.0-720p-903": 0.050684931506, "sd2-720p-high": 0.053424657534,
    "sd2.5-720p-301010": 0.061643835616, "sd2-标准720p": 0.095890410958,
    "sd2-900": 0.246575342465, "sd2-fast福利": 0.390410958904,
    "sd2-fast-933": 0.472602739726, "sd2-福利": 0.479452054794,
    "sd2-720p-福利": 0.520547945205, "sd2-720p-quan": 0.753424657534,
    "gz-sd2-720p": 0.890410958904,
}
RATIOS = ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9"]
# 文档 12.1：只有这两个模型限制了 resolution 白名单
IMAGE_RESOLUTIONS = {"image2-2k4k": ("2K", "4K"), "image2-4k": ("4K",)}
# 文档 12.2 的两条时长白名单（quanneng2.0 / -9tu）对应的模型已下线，先清空。
# 现存这批的档位官方没给，**不猜** —— 猜错时长会按错的长度出片并计费，
# 而参数越界只是 400（不结算），后者安全得多。
DURATION_RULES: dict = {}
# 前端下拉的可选秒数。
#
# **这里原来报的是 4-30，是故意报宽的** —— 理由是「报宽只会吃 400（不计费），
# 报窄会把能力埋掉」。那个权衡有它的道理，但它有个说不出口的前提：
# 下拉里出现 30 秒，人会当成「这家支持 30 秒」，而我们**根本不知道**。
#
# 现在的立场：**只报有依据的**。文档 r21 给的是 4-15（那批模型已下线，
# 但那是这家唯一给过的数字），所以基线就是 4-15。
# 某个模型实测能出更长的，写进「服务商 → 时长档位」那个框里
# （`sd2.5-720p-301010=4,8,15,30`），页面就会给那个模型放开到 30。
#
# 这样两边都不吃亏：没依据的不假装支持，验过的也不会被埋掉。
DEFAULT_DURATIONS = tuple(range(4, 16))

MAX_IMAGES, MAX_VIDEOS, MAX_AUDIOS = 9, 3, 3
# 文档 11.2 单文件上限（MiB）
UPLOAD_LIMITS = {".jpg": 10, ".jpeg": 10, ".png": 10, ".webp": 10,
                 ".mp3": 50, ".wav": 50, ".mp4": 60}
_CTYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
           ".webp": "image/webp", ".mp3": "audio/mpeg", ".wav": "audio/wav",
           ".mp4": "video/mp4"}


def _fit_duration(model: str, want: int, *, log=None) -> int:
    """收敛时长。**只在有明确依据时才改**，没依据就原样发出去。

    以前这里对未知模型一律 `min(15, ...)` —— 你要 29 秒，它悄悄发 15 秒出去，
    片子短了一半、任务还标成功，**没有任何提示**。而那个 15 是文档 r21 里
    「大多数模型 4-15」的说法，那批模型 2026-08-16 实拉已经全部下线了，
    等于拿一条过期规则去砍现役模型。

    现在的立场：拿不准就发用户填的值。参数越界网关会 400，**400 不计费**，
    比默默出一条时长不对的片子安全得多 —— 后者要到成片看完才发现。
    """
    sec = int(want or 5)
    allowed = DURATION_RULES.get(model)
    if allowed and sec not in allowed:
        near = min(allowed, key=lambda a: abs(a - sec))
        if log:
            log(f"{model} 的时长档位是 {allowed}，已把 {sec} 秒纠正为 {near} 秒")
        return near
    if sec < 1:
        return 1
    return sec


def _is_remote(ref: str) -> bool:
    """公网直链或 asset:// URI —— 这两种网关才读得到。"""
    return str(ref).startswith(("http://", "https://", "asset://"))


class XiaobalongProvider(Provider):
    id = "xiaobalong"
    name = "小霸龙 api.keik.cc"
    aliases = ("keik", "小霸龙", "xbl", "binghuo")
    default_base_url = "https://api.keik.cc"
    supports = ("image", "video")
    # 图片参考图只收公网 URL；视频素材收 HTTPS 或 asset:// —— 两边都不吃 data URI
    ref_mode = "url"

    def capabilities(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "default_base_url": self.default_base_url,
            "supports": list(self.supports),
            "image": {
                "models": IMAGE_MODELS,
                "default_model": "gemini-3-pro-image",
                "sizes": RATIOS,                  # 这家图片的"尺寸"就是比例(ratio)
                "default_size": "9:16",
                "max_refs": MAX_IMAGES,
                "ref_mode": "url",
                "notes": "**同步**出图，没有任务 ID 也不轮询。比例字段是 ratio、数量字段是 count(1–4，"
                         "按张计费)。image2-2k4k 只认 resolution=2K/4K，image2-4k 只认 4K。"
                         "参考图 reference_images 只收公网 URL —— **asset:// 只用于视频**。"
                         "HTTP 200 不代表成功：error 非空或 data:[] 都算失败。",
            },
            "video": {
                "models": VIDEO_MODELS,
                "default_model": "sd2-720p-933",
                "prices_usd": VIDEO_PRICES,
                "ratios": RATIOS,
                "durations": list(DEFAULT_DURATIONS),
                "default_duration": 5,
                "resolutions": [""],
                "max_refs": MAX_IMAGES,
                "ref_mode": "url",
                "notes": "统一用 **duration 整数**；素材是纯字符串数组 images≤9 / videos≤3 / audios≤3"
                         "（不能用对象数组），可填 HTTPS 直链或上传接口给的 asset://xiaobalong/... "
                         "(24 小时有效)。带参考视频的按秒模型价格 ×1.8。"
                         "⚠ **模型清单换得很勤**：2026-08-16 实拉发现文档 r21 里 20 个视频模型只剩 2 个还在，"
                         "现在是 sd2-* / sd2.5-* 一套。上线新模型时用 list_models() 或 /api/pricing 复核，"
                         "别照旧文档抄。各模型的时长档位官方没给，越界会 400（不结算）。",
            },
            "notes": "⚠ 创建 POST 只能提交一次、**不得自动重试**（本类已设 retries=1）。"
                     "status=unknown 不是失败也不是可重投信号，只能继续查。"
                     "模型名区分大小写、空格和中文，别照抄别家。",
        }

    # -- 素材上传（渠道无关）---------------------------------------------
    def upload_asset(self, path: str, *, log: Callable = print) -> str:
        """本地文件 → asset://xiaobalong/... URI（**只承诺用于视频素材**，24 小时有效）。"""
        if not os.path.isfile(path):
            raise ApiError(f"找不到文件: {path}")
        ext = os.path.splitext(path)[1].lower()
        limit = UPLOAD_LIMITS.get(ext)
        if limit is None:
            raise ApiError(f"小霸龙只收 {'/'.join(sorted(UPLOAD_LIMITS))}，不收 {ext or '(无扩展名)'}；"
                           f"且扩展名必须与文件真实内容一致")
        size = os.path.getsize(path)
        if size > limit * 1024 * 1024:
            raise ApiError(f"{os.path.basename(path)} 有 {size / 1048576:.1f}MiB，超过 {ext} 的 {limit}MiB 上限")
        with open(path, "rb") as fh:
            blob = fh.read()
        # 请求体只能有一个名为 file 的文件字段，不能附带其他表单字段
        data = self.session.request("POST", "/v1/assets/uploads",
                                    files=[("file", (os.path.basename(path), blob, _CTYPES[ext]))],
                                    retries=1, timeout=900)
        uri = data.get("url", "") if isinstance(data, dict) else ""
        if not uri:
            raise ApiError(f"上传没返回 url: {str(data)[:300]}")
        log(f"小霸龙 素材已上传: {uri}（24 小时有效）")
        return uri

    # ---------------------------------------------------------------- image
    def generate_image(self, task: ImageTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 900) -> dict:
        model = task.model or "gemini-3-pro-image"
        if not (task.prompt or "").strip():
            raise ApiError("小霸龙 prompt 必填且不可为空")

        body: dict = {"model": model, "prompt": task.prompt, "count": int(task.n or 1)}
        ratio = (task.size or "").strip()
        if ":" in ratio:
            body["ratio"] = ratio            # 只有比例才发；像素值这家不认
        allowed = IMAGE_RESOLUTIONS.get(model)
        if allowed:
            # 这两个模型有 resolution 白名单，不给会被上游拒
            want = str(task.extra.get("resolution") or "").strip().upper()
            body["resolution"] = want if want in allowed else allowed[0]

        refs = [r for r in (task.refs or []) if _is_remote(r)][:MAX_IMAGES]
        dropped = len(task.refs or []) - len(refs)
        if dropped:
            # 丢了不能只 log 一句照样出图：状态资产要靠父资产定身份，少一张出来就不是同一个人
            raise ApiError(
                f"小霸龙**图片**的 reference_images 只收执行服务能读取的公网 URL，"
                f"这一项给的 {dropped} 张不是（注意 asset:// 文档只承诺用于视频素材）。"
                f"本该有 {len(task.refs)} 张参考图，能用的只有 {len(refs)} 张 —— "
                f"少了参考图出来的就不是同一个人，所以不出这张图。"
                f"去「设置 → 参考图上传」配对象存储，或把这类活排给收本地图的服务商。",
                status=0, kind="task_fatal")
        if refs:
            # 参考图字段只能选一组，不能和 image/image_url/images/image_urls 混用
            body["reference_images"] = refs

        log(f"小霸龙 图片 {model}: count={body['count']} ratio={body.get('ratio', '省略')} "
            f"resolution={body.get('resolution', '省略')} 参考图{len(refs)}张")
        # retries=1：文档规定创建 POST 不得自动重试
        data = self.session.request("POST", "/v1/images/generations", json_body=body,
                                    retries=1, timeout=600)

        if isinstance(data, dict) and data.get("error"):
            raise ApiError(f"小霸龙图片失败（应用级错误，不结算）: {str(data['error'])[:300]}")
        items = extract_image_items(data)
        if not items:
            # data:[] 按失败处理，但**禁止自动重提**
            raise ApiError(f"小霸龙返回 data 为空 → 按失败处理（不结算，但不要自动重提）: {str(data)[:300]}")
        self.session.save_item(items[0], dest)
        return {"task_id": extract_task_id(data), "source": items[0][:200],
                "provider": self.id, "model": model}

    # ---------------------------------------------------------------- video
    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 8, poll_timeout: int = 2400) -> dict:
        model = task.model or "bh2.0-720p"
        if not (task.prompt or "").strip():
            raise ApiError("小霸龙 prompt 必填且不可为空")
        sec = _fit_duration(model, task.duration, log=log)

        refs = [r for r in (task.refs or []) if _is_remote(r)][:MAX_IMAGES]
        dropped = len(task.refs or []) - len(refs)
        if dropped:
            raise ApiError(
                f"小霸龙视频素材只收 HTTPS 直链或 asset://xiaobalong/... URI，"
                f"这一项给的 {dropped} 张两样都不是。本该有 {len(task.refs)} 张参考图 —— "
                f"少了出来的就不是同一个人/同一个东西，所以不出这条。"
                f"去「设置 → 参考图上传」配对象存储，或先用 upload_asset() 换成 asset:// URI。",
                status=0, kind="task_fatal")

        body: dict = {"model": model, "prompt": task.prompt, "duration": sec}
        if (task.ratio or "").strip():
            body["aspect_ratio"] = task.ratio.strip()
        if refs:
            body["images"] = refs                     # 纯字符串数组，不能用对象数组
        vids = [v for v in (task.extra.get("video_refs") or task.extra.get("videos") or [])
                if _is_remote(v)][:MAX_VIDEOS]
        auds = [a for a in (task.extra.get("audio_refs") or task.extra.get("audios") or [])
                if _is_remote(a)][:MAX_AUDIOS]
        if vids:
            body["videos"] = vids                     # videos 优先，别同时发不一致的 reference_videos
        if auds:
            body["audios"] = auds

        log(f"小霸龙 视频 {model}: duration={sec} aspect_ratio={body.get('aspect_ratio', '省略')} "
            f"图{len(refs)}/视频{len(vids)}/音频{len(auds)}")
        # retries=1：创建 POST 只发一次
        data = self.session.request("POST", "/v1/videos", json_body=body,
                                    retries=1, timeout=300)

        task_id = extract_task_id(data)
        status = (data.get("status") or "").lower() if isinstance(data, dict) else ""
        if status == "unknown":
            # 202 + unknown：越过了安全提交边界，网关也不确定上游收没收。
            # 这**不是失败**，任务可能已经在生成并计费 —— 只能继续查，绝不能重投。
            log(f"⚠ 小霸龙返回 status=unknown（任务 {task_id or '无 ID'}）：不是失败，"
                f"任务可能已计费生成，继续查询，禁止重新提交")
        if not task_id:
            raise ApiError(
                "提交没返回任务 ID —— 文档规定此时禁止自动重提，请记下时间人工核对是否已建单扣费。",
                status=0, kind="task_fatal")

        url = extract_video_url(data)
        if not url:
            # unknown / queued / processing / in_progress 都继续；只有 failed 才停
            url = self.session.poll("/v1/videos/{id}", task_id, picker=extract_video_url,
                                    content_path_tpl="/v1/videos/{id}/content",
                                    interval=poll_interval, timeout=poll_timeout,
                                    log=log, cancel=cancel)
        # 结果地址是要鉴权的本站代理，save_item 对本站地址会自动带 Bearer
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id, "model": model}
