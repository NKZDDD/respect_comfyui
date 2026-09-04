# -*- coding: utf-8 -*-
"""无限画布（videogogo.top）统一视频 API。只做视频。

这不是阿珂。**模型清单和逐模型约束从 `GET /v1/models` 实拉**（2026-09-01）——
这家每个模型自己回一份 `capability_schema`，比文档准。上一版是照文档抄的
两个模型，实拉出来是五个，而且比例和时长逐模型不同（见 MODELS 那张表）。

混合参考：图 / 视频 / 音频三类，默认音频开、水印关。
本地图片/data URI 先 POST /v1/assets 上传，随后把 asset_id 放进字符串数组。
"""

from __future__ import annotations

import base64
import mimetypes
import os
import re
import uuid
from typing import Callable, Optional
from urllib.parse import unquote_to_bytes

from ..apiutil import ApiError, extract_task_id, extract_video_url
from .base import Provider, VideoTask

# 这张表是 **2026-09-01 从 `GET /v1/models` 实拉的**，不是照文档抄的。
# 这家每个模型自己回一份 `capability_schema`，比任何文档都准 ——
# 而实拉出来和我们原来写的差了好几处，每一处的失败都是静默的：
#
#   · 只声明了 2 个模型，实际有 5 个 —— 另外三个页面上根本选不到
#   · 声明了 `21:9`，而**一个模型都不支持** —— 选了它请求会被拒，
#     或者网关自己挑一个，出来的片子不是这个画幅
#   · 比例和时长原来是**全局一份**，实际逐模型不同：
#       seedance-2.5-hf-720p   16:9/9:16/4:3/1:1（**没有 3:4**），4–30 秒
#       seedance-2.5gs 720p    多 3:4，**15–30 秒**（下限是 15，不是 4）
#       seedance-2.0(-F)-r     多 3:4，**4–15 秒**（上限是 15，不是 30）
#     按全局那份填，2.0 系列选 20 秒、2.5gs 选 10 秒都会被拒 ——
#     而页面上那两个值是我们自己给的候选。
#
# `seedance-2.5-hf` 的 `capability_schema` 里**只有一个 notes 网址**，
# 什么都没声明。它的 480p 是原来文档里写的，实拉没有背书 —— 标出来，
# 别让「我们写的」看起来像「它说的」。
_R4 = ["16:9", "9:16", "4:3", "1:1"]                    # 2.5-hf-720p 只有这四个
_R5 = ["16:9", "9:16", "1:1", "4:3", "3:4"]             # 其余四个多一个 3:4

# **每一条只写它自己声明过的。** 没声明的键就不放进来 ——
# 放一个「看起来合理」的数进去，和照文档抄没有区别：它会显示在页面上、
# 会拿去拦人，而没有任何东西背书。
#
# 第一版我就犯了这个：给全部五个模型都填了 30/10/10，
# 而实际只有 `seedance-2.5gs 720p` 声明了这三个数，另外四个只声明了
# `max_reference_assets: 50`（三类**加起来**的总数），
# 还有两个连这个都没有。判张数时退回整家的上限（MAX_IMAGES 那几个），
# 报错里会说清那是「整家的，这个模型没单独声明」。
MODELS = {
    "seedance-2.5-hf-720p": {
        "resolution": "720p", "ratios": _R4, "durations": list(range(4, 31)),
    },
    "seedance-2.5gs 720p": {                            # 名字里**有空格**，照它给的原样
        "resolution": "720p", "ratios": _R5, "durations": list(range(15, 31)),
        "max_images": 30, "max_videos": 10, "max_audios": 10,
        "max_assets": 50, "min_images": 1, "max_prompt": 8000,
    },
    "seedance-2.0-r-720P": {
        "resolution": "720p", "ratios": _R5, "durations": list(range(4, 16)),
        "max_assets": 50,
    },
    "seedance-2.0-F-r-720P": {
        "resolution": "720p", "ratios": _R5, "durations": list(range(4, 16)),
        "max_assets": 50,
    },
    # 它的 capability_schema 里**只有一个 notes 网址**。480p 和比例是文档里
    # 写的，实拉没有背书 —— 标出来，别让「我们写的」看起来像「它说的」。
    "seedance-2.5-hf": {
        "resolution": "480p", "ratios": _R5, "durations": list(range(4, 31)),
    },
}
VIDEO_MODELS = list(MODELS)
MODEL_RESOLUTION = {k: v["resolution"] for k, v in MODELS.items()}
# 全局那份 = 各模型的**并集**，只用来填「这家总体收什么」。
# 真正判合不合法要按模型来（见 _limits）—— 拿并集去判等于全放行。
RATIOS = _R5
MAX_IMAGES, MAX_VIDEOS, MAX_AUDIOS = 30, 10, 10


def _limits(model: str) -> dict:
    """这一个模型的已知约束。**不认识就返回空 —— 空的意思是「不知道」，
    不是「不允许」。**

    上面那张表是**候选和已知约束**，不是白名单。平台随时会上新模型
    （这次实拉就多出三个），而写死白名单等于「平台上新，你就得改代码」——
    用户原话（2026-09-01）：「声明两个的时候会不会导致我填写其他模型名
    无法使用，这不是我想要的，因为会导致我新增模型的时候一定需要修改代码」。

    所以页面上模型框是自由输入 + 候选（datalist），这里也照办：表里有的
    按它的约束校验，表外的**原样发出去**，只在日志里说一声「没有它的约束，
    不校验」。真不合法的话平台会拒，而那句拒绝是响的。

    最新清单随时可以实拉：基类的 `list_models()` 打的就是这家的 `/v1/models`，
    「生产」页模型框的候选和开跑前的 `preflight_models` 用的都是实拉那一份。
    """
    return MODELS.get(model) or {}


def _guess_resolution(model: str) -> str:
    """名字里带 720/480/1080 就按它。**猜不出来就返回空，不填这个字段** ——
    随手填一个的后果是「片子出得来、分辨率不是你要的」，而且不报错。
    """
    m = re.search(r"(2160|1440|1080|720|540|480|360)\s*[pP]", model or "")
    return (m.group(1) + "p") if m else ""


def _data_uri(value: str) -> tuple[bytes, str] | None:
    match = re.match(r"^data:([^;,]+)?(;base64)?,(.*)$", str(value), re.I | re.S)
    if not match:
        return None
    mime = match.group(1) or "application/octet-stream"
    try:
        blob = (base64.b64decode(match.group(3), validate=False)
                if match.group(2) else unquote_to_bytes(match.group(3)))
    except (TypeError, ValueError) as exc:
        raise ApiError("无限画布参考素材的 data URI 无法解码") from exc
    return blob, mime


class WuxianhuabuProvider(Provider):
    id = "wuxianhuabu"
    name = "无限画布 videogogo.top（Seedance 2.5）"
    aliases = ("videogogo", "无限画布", "wxhb")
    default_base_url = "https://videogogo.top/api"
    supports = ("video",)
    ref_mode = "data_uri"

    def capabilities(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "default_base_url": self.default_base_url,
            "supports": list(self.supports),
            "video": {
                "models": VIDEO_MODELS,
                "default_model": "seedance-2.5-hf-720p",
                "ratios": RATIOS,
                "durations": list(range(4, 31)),
                "default_duration": 15,
                "resolutions": ["480p", "720p"],
                "max_refs": MAX_IMAGES,
                "max_video_refs": MAX_VIDEOS,
                "max_audio_refs": MAX_AUDIOS,
                "ref_mode": "data_uri",
                # **逐模型给。** 页面按选中的模型换候选 —— 全局那份是并集，
                # 拿并集当候选就会让人选到一个这个模型不收的值，
                # 而那种拒绝要等跑到那一步才看得见。
                "model_options": {
                    m: {"resolutions": [v["resolution"]],
                        "ratios": v["ratios"],
                        "durations": v["durations"],
                        # 没单独声明的退回整家的上限 —— 页面要有个数可显示，
                        # 但**判的时候**会说清它是整家的（见 generate_video）。
                        "max_refs": v.get("max_images", MAX_IMAGES),
                        "max_video_refs": v.get("max_videos", MAX_VIDEOS),
                        "max_audio_refs": v.get("max_audios", MAX_AUDIOS)}
                    for m, v in MODELS.items()
                },
                "notes": "模型清单和逐模型约束是 2026-09-01 从 /v1/models 实拉的。"
                         "时长按模型不同：2.5-hf / 2.5-hf-720p 是 4–30 秒，"
                         "**2.5gs 是 15–30 秒**，**2.0 系列是 4–15 秒**。"
                         "比例也不同：2.5-hf-720p 没有 3:4；**没有任何模型收 21:9**。"
                         "2.5gs 还要求至少 1 张参考图、提示词 ≤8000 字。"
                         "seedance-2.5-hf 那一条它自己什么都没声明，480p 是文档里写的、"
                         "实拉没有背书。"
                         "图片、视频、音频数组都是 URL 或 /v1/assets 返回的 asset_id 字符串。",
            },
            "notes": "独立于阿珂。素材与结果最多保留 24 小时；创建请求带幂等键，"
                     "同一次网络重试不会重复建单。",
        }

    def _asset(self, ref: str, kind: str, *, log: Callable) -> str:
        value = str(ref or "").strip()
        if not value:
            return ""
        if value.startswith(("http://", "https://")):
            return value
        parsed = _data_uri(value)
        if parsed:
            blob, mime = parsed
            name = f"reference-{uuid.uuid4().hex[:12]}{mimetypes.guess_extension(mime) or '.bin'}"
        elif os.path.isfile(value):
            name = os.path.basename(value)
            mime = mimetypes.guess_type(value)[0] or "application/octet-stream"
            with open(value, "rb") as fh:
                blob = fh.read()
        elif re.fullmatch(r"[A-Za-z0-9_\-]{8,128}", value):
            # 已有 asset_id 是普通字符串，原样使用。
            return value
        else:
            # 到这儿说明:不是链接、不是 data URI、本机也没这个文件、
            # 形状还不像 asset_id。以前这里原样返回 —— 一个写错的路径
            # 就变成一个假 asset_id 发出去,服务商认不出就当没有这张参考图,
            # **片子照出、照计费,脸不对而且一处都不报错**。
            raise ApiError(
                f"无限画布{kind}参考素材认不出:{value[:120]!r}。"
                f"既不是 http 链接、不是 data URI,本机也没有这个文件,"
                f"形状也不像 asset_id。少一张参考素材出来的就不是同一个人,"
                f"所以这一条不出。",
                status=0, kind="task_fatal")
        if not blob:
            raise ApiError(f"无限画布{kind}参考素材为空")
        data = self.session.request(
            "POST", "/v1/assets", raw_body=blob,
            headers={"Content-Type": mime, "X-File-Name": name},
            retries=2, timeout=600)
        asset_id = data.get("asset_id", "") if isinstance(data, dict) else ""
        if not asset_id:
            raise ApiError(f"无限画布上传{kind}素材没返回 asset_id: {str(data)[:300]}")
        log(f"无限画布 {kind}参考素材已上传")
        return str(asset_id)

    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 2400) -> dict:
        model = (task.model or "seedance-2.5-hf-720p").strip()
        lim = _limits(model)
        image_src = list(task.refs or [])
        video_src = list(task.extra.get("video_refs") or task.extra.get("videos") or [])
        audio_src = list(task.extra.get("audio_refs") or task.extra.get("audios") or [])

        # **逐模型判，而且一次把问题说全。** 各条约束按模型不同（时长、比例、
        # 最少几张图），一条一条报要跑好几趟；而这些都在发请求之前就知道，
        # 现在停比撞一个 400 便宜 —— 撞 400 的那些家里，有几家是**不报错、
        # 自己挑一个默认值**，那才是最坏的。
        sec = int(task.duration or 15)
        ratio = task.ratio or "9:16"
        if not lim:
            # 表里没有 = 我们不知道它的约束，**不是不允许**。照发。
            log(f"⚠️ 无限画布没有 {model} 的约束记录（这张表是 2026-09-01 实拉的，"
                f"平台上新会比它快）—— 时长/比例/参考图张数这一趟都不校验，"
                f"照你填的发出去。不合法的话平台会拒，那句拒绝是响的。"
                f"要把它变成有校验的：跑一次 list_models() 看它声明的 "
                f"capability_schema，补进 core/providers/wuxianhuabu.py 的 MODELS。")
        bad = []
        if lim and sec not in lim["durations"]:
            bad.append(f"{model} 的时长只能是 {min(lim['durations'])}–"
                       f"{max(lim['durations'])} 秒，本任务是 {sec} 秒")
        if lim and ratio not in lim["ratios"]:
            bad.append(f"{model} 不收 {ratio} 这个画幅，它只有 "
                       f"{' / '.join(lim['ratios'])}")
        # 张数上限**表外的模型也判** —— 这几个是整家的接口上限，不是某个
        # 模型的脾气；而超了的后果是服务商截掉多的，**截掉的正是排在后面的
        # 那几张**，画面用错参考却标成功。
        #
        # 报错里要分清这个数是**这个模型声明的**还是**整家的兜底** ——
        # 前者改不了（换模型），后者可能只是我们没拿到它的声明。
        for label, n, key, fam in (("参考图", len(image_src), "max_images", MAX_IMAGES),
                                   ("参考视频", len(video_src), "max_videos", MAX_VIDEOS),
                                   ("参考音频", len(audio_src), "max_audios", MAX_AUDIOS)):
            cap = lim.get(key)
            src = f"{model} 声明的" if cap is not None else "整家的上限（这个模型没单独声明）"
            cap = cap if cap is not None else fam
            if n > cap:
                bad.append(f"{label} {n} 条，超了 {cap} 条 —— {src}")
        # **三类加起来还有一个总数。** 这一条它声明了而我们一直没判：
        # 图 30 + 视频 10 + 音频 10 各自都不超，加起来 50 也可能正好撞上。
        total_cap = lim.get("max_assets")
        total = len(image_src) + len(video_src) + len(audio_src)
        if total_cap and total > total_cap:
            bad.append(f"参考素材一共 {total} 条（图 {len(image_src)} + "
                       f"视频 {len(video_src)} + 音频 {len(audio_src)}），"
                       f"超了 {model} 的总数上限 {total_cap} ——"
                       f"**分类各自都没超，是加起来超的**")
        if lim.get("min_images") and len(image_src) < lim["min_images"]:
            bad.append(f"{model} 要求至少 {lim['min_images']} 张参考图，"
                       f"这一条一张都没有")
        # 页面上选的清晰度（`task.resolution`）**盖过表里的** —— 那是人明确挑的。
        # 但如果这个模型声明了它只有哪几档，选了它没有的就当场停：
        # 发出去多半是「片子出得来、清晰度不是你要的」，而且不报错。
        picked = (task.resolution or "").strip()
        if picked and lim.get("resolution") and picked != lim["resolution"]:
            bad.append(f"{model} 只有 {lim['resolution']}，选的是 {picked}")
        if lim.get("max_prompt") and len(task.prompt or "") > lim["max_prompt"]:
            bad.append(f"提示词 {len(task.prompt or '')} 字，"
                       f"超了 {model} 的 {lim['max_prompt']} 字上限")
        if bad:
            raise ApiError("无限画布这一条发不出去：" + "；".join(bad)
                           + "。**不能静默裁掉或改掉** —— 裁了参考素材画面就用错图，"
                             "改了时长片子和提示词对不上，两种都不报错。",
                           status=0, kind="task_fatal")

        images = [self._asset(r, "图片", log=log) for r in image_src]
        videos = [self._asset(r, "视频", log=log) for r in video_src]
        audios = [self._asset(r, "音频", log=log) for r in audio_src]
        body: dict = {
            "model": model,
            "prompt": task.prompt or "",
            "seconds": sec,
            "ratio": ratio,
            "generate_audio": bool(task.extra.get("generate_audio", True)),
            "watermark": bool(task.extra.get("watermark", False)),
        }
        # 表外的模型按名字里的 720p/480p 认；认不出来**就不填这个字段**，
        # 让平台用它自己的默认 —— 随手填一个的后果是「片子出得来、
        # 分辨率不是你要的」，而且不报错。
        # 优先级：**页面上选的 > 表里记的 > 从名字认的 > 不填**。
        # 「不填」是有意义的一档：让平台用它自己的默认，比我们蒙一个强。
        res = picked or lim.get("resolution") or _guess_resolution(model)
        if res:
            body["resolution"] = res
        if images:
            body["reference_images"] = images
        if videos:
            body["reference_videos"] = videos
        if audios:
            body["reference_audios"] = audios

        idem = str(task.extra.get("idempotency_key") or uuid.uuid4())
        log(f"无限画布 {model}: {sec}s {body.get('resolution') or '分辨率跟平台默认'} "
            f"{body['ratio']} 图{len(images)}/视频{len(videos)}/音频{len(audios)}")
        data = self.session.request(
            "POST", "/v1/videos", json_body=body,
            headers={"Idempotency-Key": idem}, retries=2, timeout=300)
        task_id = extract_task_id(data)
        url = extract_video_url(data)
        if not url:
            if not task_id:
                raise ApiError(f"提交没返回任务 ID: {str(data)[:300]}")
            url = self.session.poll("/v1/videos/{id}", task_id, picker=extract_video_url,
                                    interval=poll_interval, timeout=poll_timeout,
                                    log=log, cancel=cancel)
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id, "model": model}
