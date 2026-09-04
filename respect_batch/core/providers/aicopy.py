# -*- coding: utf-8 -*-
"""小裴 aicopy（api.aicopy.top）。对齐 respect_comfyui 的 image_nodes / video_nodes。

值钱的地方是**它有一堆 gpt-image-2 的备用通道**：`gpt-image-2应急通道01..06` 和
`GPT本地版*` 系列。别家 image-2 出问题时，这里能换通道继续 —— 同一个模型、
不同线路，比换模型对画风的影响小得多。

- 图片：`POST /v1/images/generations`（JSON）。参考图放 `image` 字段，
  **要裸 base64，不带 `data:` 前缀**（这点和别家都不一样）。
  返回 b64_json 或 url。
- 视频：统一接口（2026-08-19）—— `POST /v1/videos` 提交 +
  `GET /v1/videos/{id}` 轮询，所有模型同一套字段，网关按模型自动转换。
"""

from __future__ import annotations

from typing import Callable, Optional

from ..apiutil import (ApiError, extract_image_items, extract_task_id,
                       extract_video_url)
from .base import ImageTask, Provider, VideoTask

# gpt-image-2 的多条线路 —— 这家的核心价值
IMAGE_MODELS = [
    "gpt-image-2应急通道",
    "gpt-image-2应急通道01", "gpt-image-2应急通道02", "gpt-image-2应急通道03",
    "gpt-image-2应急通道04", "gpt-image-2应急通道05", "gpt-image-2应急通道06",
    "GPT本地版", "GPT本地版1k", "GPT本地版2k", "GPT本地版4k",
    "GPT本地版-通道1", "GPT本地版1k-通道1", "GPT本地版2k-通道1", "GPT本地版4k-通道1",
    "GPT本地版-通道2", "GPT本地版1k-通道2", "GPT本地版2k-通道2", "GPT本地版4k-通道2",
    "GPT本地版-通道3", "GPT本地版1k-通道3", "GPT本地版2k-通道3", "GPT本地版4k-通道3",
]
# ---------------------------------------------------------------------------
# 视频分支（对齐「用户侧统一视频接口」文档，2026-08-19）
#
# 网关升级成了统一入口：**所有模型同一套协议** —— POST /v1/videos 提交 +
# GET /v1/videos/{id} 轮询，参考素材、时长、画幅由网关按模型自动转换。
# 3.3.53 那套 16 个分支的请求体形状（metadata{} / content 块 / input.media /
# 双端点 / first_frame_url…）全部退役 —— 那些形状发错**多半不报错**，
# 只是参考图被静默忽略，现在由网关统一兜住，客户端只管一套字段：
#
#   单首帧 → 顶层 input_reference
#   首尾帧 → extra.reference_images 带 first_frame / last_frame 角色
#   多参考 → extra.reference_images 带 reference_image 角色
#   参考视频/音频 → extra.reference_videos / reference_audios
#   画幅 → extra.aspect_ratio
#
# 仍按模型族保留的知识只剩两类（网关换协议也带不走的上游限制）：
#   · 时长上限/固定值 —— 客户端先夹住，免得白跑一趟 400
#   · 模式限制 —— 火山官方没有文生、900 只吃多参考、快乐马只要单图
#
# 参考素材统一要公网 HTTP(S) 链接（GROK / Horse 旧分支吃 Data URL 的例外
# 取消了 —— 统一入口不再收 data URI，本机图得先传对象存储）。
# 模型族表（branch_of）保留：认不出新模型时按最通用的族夹时长。
# ---------------------------------------------------------------------------

# 模型族 —— 名字还是控制台那些公开模型名，族只用来夹时长/限模式
GROK10_MODELS = ["grok-imagine-1.0-video", "grok-1.0-官转接口", "grok-1.0-备用接口"]
GROK15_MODELS = ["grok-imagine-video-1.5-preview", "grok-1.5-官转接口",
                 "grok-1.5-备用接口", "grok-1.5-多参接口"]
HORSE_MODELS = ["happyhorse-1.1-t2v-720p", "happyhorse-1.1-t2v-1080p",
                "happyhorse-1.1-i2v-720p", "happyhorse-1.1-i2v-1080p",
                "happyhorse-1.1-r2v-720p", "happyhorse-1.1-r2v-1080p"]
H3_MODELS = ["开源h3-480p", "开源h3-720p", "开源h3-1080p", "开源h3-2k"]
VOLC_MODELS = ["火山官方2.5-480p", "火山官方2.5-720p",
               "火山官方2.0-480p-mini", "火山官方2.0-720p-mini"]
SD25_MODELS = ["sd-2.5-480p不卡脸(按秒)", "sd-2.5-720p不卡脸(按秒)",
               "sd-2.5-480p不卡脸(按秒)-备用", "sd-2.5-720p不卡脸(按秒)-备用"]
SD2FULL_MODELS = ["sd2.0-720mini-不卡脸（按秒）", "sd2.0-720fast-不卡脸（按秒）",
                  "sd2.0-720满血-不卡脸（按秒）", "sd2.0-720满血（按次）不卡脸",
                  "sd2.0-720fast（按次）不卡脸", "sd2.0-1080mini-不卡脸（按秒）",
                  "sd2.0-1080fast-不卡脸（按秒）", "sd2.0-1080满血-不卡脸（按秒）"]
AD_MODELS = ["sd2.0-480fast-ad渠道16x9", "sd2.0-480fast-ad渠道9x16",
             "sd2.0-480满血-ad渠道16x9", "sd2.0-480满血-ad渠道9x16",
             "sd2.0-720fast-ad渠道16x9", "sd2.0-720fast-ad渠道9x16",
             "sd2.0-720满血-ad渠道16x9", "sd2.0-720满血-ad渠道9x16",
             "sd2.0-1080满血-ad渠道16x9", "sd2.0-1080满血-ad渠道9x16"]
DUAL_MODELS = ["sd-480满血-933（按次）", "sd-720满血-933（按次）",
               "sd-480满血-933（按秒）", "sd-720满血-933（按秒）",
               "sd-2.0-480满血（卡脸）惊喜渠道", "sd-2.0-480fast（卡脸）惊喜渠道",
               "sd-2.0-720满血（卡脸）惊喜渠道", "sd-2.0-720fast（卡脸）惊喜渠道",
               "sd-2.0-1080满血（卡脸）惊喜渠道",
               "sd-2.0-720满血（不卡脸）惊喜渠道", "sd-2.0-480满血（不卡脸）惊喜渠道",
               "快乐马1.1（不卡脸）惊喜渠道", "可灵-3.0-omni（不卡脸）惊喜渠道"]
DUAL_SINGLE_ONLY = ("快乐马1.1（不卡脸）惊喜渠道",)         # 上游只支持文生/单首帧
ROTATE_MODELS = ["sd-720fast-不卡脸（按次）", "sd-720满血-较慢（按次）",
                 "sd-720满血-不卡脸（按次）", "sd-2.5-轮换渠道（按次）",
                 "sd-720fast（按秒）", "sd-720满血（按秒）", "sd-2.5-轮换渠道（按秒）"]
ROTATE_FIXED15 = ("sd-720fast-不卡脸（按次）", "sd-720满血-较慢（按次）", "sd-720满血-不卡脸（按次）")
SD900_MODELS = ["sd-720满血-900（不售后）"]                 # 上游只支持多参考
OMNI_MODELS = ["omni-fast-视频生成（无水印）", "omni-fast-视频生成（带水印）",
               "omni-fast-视频编辑（无水印）", "omni-fast-视频编辑（带水印）"]
VEO_MODELS = ["veo视频生成"]

VIDEO_MODELS = (GROK10_MODELS + GROK15_MODELS + HORSE_MODELS + H3_MODELS + VOLC_MODELS
                + SD25_MODELS + SD2FULL_MODELS + AD_MODELS + DUAL_MODELS + ROTATE_MODELS
                + SD900_MODELS + OMNI_MODELS + VEO_MODELS)

_BRANCH_TABLE = [
    ("grok10", GROK10_MODELS), ("grok15", GROK15_MODELS), ("horse", HORSE_MODELS),
    ("h3", H3_MODELS), ("volc", VOLC_MODELS), ("sd25", SD25_MODELS),
    ("sd2full", SD2FULL_MODELS), ("ad", AD_MODELS), ("dual", DUAL_MODELS),
    ("rotate", ROTATE_MODELS), ("sd900", SD900_MODELS), ("omni", OMNI_MODELS),
    ("veo", VEO_MODELS),
]


def branch_of(model: str) -> str:
    """模型名 → 族 id。认不出来的按 sd2full（最通用的时长规则）走。"""
    m = (model or "").strip()
    for name, models in _BRANCH_TABLE:
        if m in models:
            return name
    return "sd2full"


def _seconds_for(model: str, sec: int) -> int:
    """按族把时长夹进上游认的范围 —— 上游的限制换网关也带不走。

    固定值的（ad 15 / omni 10 / 按次轮换 15）直接给死值；离散档的
    （grok 6/10、grok1.5 6/10/15、veo 4/6/8）就近吸附，别让上游替我们挑。
    """
    br = branch_of(model)
    if br == "grok10":
        return min((6, 10), key=lambda d: abs(d - sec))
    if br == "grok15":
        return min((6, 10, 15), key=lambda d: abs(d - sec))
    if br == "veo":
        return min((4, 6, 8), key=lambda d: abs(d - sec))
    if br == "omni":
        return 10
    if br == "ad":
        return 15
    if model in ROTATE_FIXED15:
        return 15
    if br == "h3":
        return max(5, min(15, sec))
    if br == "sd25":
        return max(4, min(29, sec))
    if br == "volc":
        return max(4, min(30 if "2.5" in model else 15, sec))
    if br == "rotate":
        return max(4, min(29 if ("按秒" in model and "2.5" in model) else 15, sec))
    return max(4, min(15, sec))                     # sd2full / dual / sd900 / 没见过的新模型


def _ref_caps(model: str) -> tuple:
    """各族参考素材上限 (图, 视频, 音频)。超上限的部分**不发**，别让上游拒整个任务。"""
    br = branch_of(model)
    if br == "sd25":
        return 30, 10, 10
    if br == "volc":
        return (30, 10, 10) if "2.5" in model else (9, 3, 3)
    if br == "rotate":
        return (30, 10, 10) if "2.5" in model else (9, 3, 3)
    if br == "grok10" or br == "grok15":
        return 7, 0, 0
    if br == "veo":
        return 2, 0, 0
    if br == "omni":
        return 5, 2, 0
    if br == "sd900":
        return 9, 0, 0
    return 9, 3, 3                                   # horse / h3 / sd2full / ad / dual / 新模型


def _bare_b64(ref: str) -> str:
    """这家的 image 字段要裸 base64，不带 data: 前缀。"""
    return ref.split(",", 1)[1] if ref.startswith("data:") else ref


class AicopyProvider(Provider):
    id = "aicopy"
    name = "小裴 api.aicopy.top"
    default_base_url = "https://api.aicopy.top"
    supports = ("image", "video")

    def accepts_url(self, model: str = "", media: str = "image") -> bool:
        # 图片接口把参考图内联进 image 字段、只认裸 base64，给链接它读不了。
        # 视频统一接口的参考素材全是公网 HTTP(S) —— data URI 也不收了
        #（GROK/Horse 旧分支的例外随 3.3.53 一起退役）。
        if media == "image":
            return False
        return True

    def needs_url(self, model: str = "", media: str = "video") -> bool:
        # 统一接口所有视频模型都要公网 URL（本机图得先传对象存储）
        return media == "video"

    def capabilities(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "default_base_url": self.default_base_url,
            "supports": list(self.supports),
            "image": {
                "models": IMAGE_MODELS,
                "default_model": "gpt-image-2应急通道",
                "sizes": ["1024x1536", "1024x1024", "1536x1024"],
                "default_size": "1024x1536",
                "max_refs": 1,
                "ref_mode": "data_uri",
                "notes": "★ 这家有 6 条 gpt-image-2 应急通道 + 12 个 GPT本地版通道，"
                         "别家 image-2 挂了可以在这里换线路继续（同一个模型不同线路，"
                         "比换模型对画风影响小）。"
                         "⚠ 参考图只收 1 张，且要裸 base64（本程序已自动处理）。"
                         "模型名带中文，是这家自己的叫法，别改。",
            },
            "video": {
                "models": VIDEO_MODELS,
                "default_model": "sd2.0-720满血-不卡脸（按秒）",
                "ratios": ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9"],
                "durations": [4, 5, 6, 8, 10, 12, 15, 20, 29],
                "default_duration": 10,
                "resolutions": [""],
                "max_refs": 30,
                "ref_mode": "url",
                "notes": "统一视频接口（2026-08-19）：所有模型同一套 /v1/videos，"
                         "参考素材、画幅由网关按模型自动转换 —— 选模型不再选协议。"
                         "时长上限按模型族自动夹（sd-2.5 系到 29 秒，ad 渠道固定 15，"
                         "omni 固定 10，grok 只有 6/10 档）。"
                         "⚠ 参考素材全部要**公网链接**（GROK/Horse 旧例外已取消），"
                         "本机图得先配对象存储。"
                         "分辨率和模式常由模型名锁定（happyhorse 的 t2v/i2v/r2v、"
                         "ad渠道的 16x9/9x16），别指望用参数覆盖。",
            },
            "notes": "接了很多线路，主要当 image-2 的备份来用。",
        }

    # ---------------------------------------------------------------- image
    def generate_image(self, task: ImageTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 900) -> dict:
        model = task.model or "gpt-image-2应急通道"
        body = {"model": model, "prompt": task.prompt, "n": int(task.n or 1),
                "size": task.size or "1024x1536", "response_format": "b64_json"}
        if task.refs:
            # 以前是 log 一句「只用第 1 张」然后照样出图 —— 静默降级。
            # 状态资产要靠父资产与依赖资产定身份和空间，少一张出来就不是同一个
            # 人/同一个地方，而且任务标 ok 没人知道。报错让优先级链换支持多张的家。
            if len(task.refs) > 1:
                raise ApiError(
                    f"这家的图片接口只收 1 张参考图，这一项要 {len(task.refs)} 张。"
                    f"少了参考图出来的就不是同一个人/同一个东西，所以不出这张图。"
                    f"把需要多张参考图的活（复杂状态资产、故事板）排给别家，"
                    f"这家留着当 image-2 的应急线路（单图或无参考图的活）。",
                    status=0, kind="task_fatal")
            if task.refs[0].startswith("http"):
                raise ApiError(
                    "这家的图片接口把参考图内联进 image 字段、只认裸 base64，"
                    "拿到的却是公网链接 —— 发出去它读不了。"
                    "关掉这家的对象存储（参考图改走 data URI），或者把这类活排给别家。",
                    status=0, kind="task_fatal")
            body["image"] = _bare_b64(task.refs[0])
        data = self.session.request("POST", "/v1/images/generations", json_body=body,
                                    retries=2, timeout=600)
        items = extract_image_items(data)
        task_id = extract_task_id(data)
        if not items:
            if not task_id:
                raise ApiError(f"没返回图片也没返回 task_id：{str(data)[:300]}")
            items = self.session.poll("/v1/images/{id}", task_id, picker=extract_image_items,
                                      interval=poll_interval, timeout=poll_timeout,
                                      content_path_tpl="/v1/images/{id}/content",
                                      log=log, cancel=cancel)
        self.session.save_item(items[0], dest)
        return {"task_id": task_id, "source": items[0][:200], "provider": self.id,
                "model": model}

    # ---------------------------------------------------------------- video
    def build_video_body(self, task: VideoTask) -> tuple:
        """统一接口的 body（文档 2026-08-19）。返回 (创建路径, body, 轮询路径)。

        所有模型一套形状；模型族的差别只剩时长夹取、参考上限和模式限制
        （见 _seconds_for / _ref_caps）—— 那些是上游的限制，网关替不了。
        """
        model = task.model or "sd2.0-720满血-不卡脸（按秒）"
        br = branch_of(model)
        prompt = task.prompt or ""
        ratio = task.ratio or "9:16"
        refs = list(task.refs or [])
        vids = [v for v in (task.extra.get("video_refs") or task.extra.get("videos") or []) if v]
        auds = [a for a in (task.extra.get("audio_refs") or task.extra.get("audios") or []) if a]
        # 模式：靠图片张数推断（studio 没有独立的"模式"概念）
        first_last = len(refs) == 2 and bool(task.extra.get("first_last"))

        # 上游的模式限制 —— 换协议也带不走，提前说清，让优先级链换别家
        if br == "volc" and not refs:
            raise ApiError(
                "火山官方没有文生视频模式，至少要 1 张参考图。"
                "纯文生请把这活排给 sd-2.5 / sd2.0 全系列的单位。",
                status=0, kind="task_fatal")
        if br == "sd900" and not refs:
            raise ApiError("sd-720满血-900（不售后）只支持多参考图，至少要 1 张。",
                           status=0, kind="task_fatal")
        if len(refs) > 1 and model in DUAL_SINGLE_ONLY:
            raise ApiError(
                f"{model} 只支持文生和单首帧，给了 {len(refs)} 张图。"
                f"多参考请排给 933 或 sd-2.0 惊喜渠道的单位。",
                status=0, kind="task_fatal")

        icap, vcap, acap = _ref_caps(model)
        body = {"model": model, "prompt": prompt,
                "seconds": _seconds_for(model, int(task.duration or 10))}
        extra = {}
        # ad 渠道的画幅锁在模型名里（…16x9 / …9x16），再传 aspect_ratio 是给上游递矛盾
        if "16x9" not in model and "9x16" not in model:
            extra["aspect_ratio"] = ratio
        if first_last:
            extra["reference_images"] = [{"url": refs[0], "role": "first_frame"},
                                         {"url": refs[1], "role": "last_frame"}]
        elif len(refs) == 1:
            body["input_reference"] = {"url": refs[0]}     # 单首帧走顶层字段
        elif refs:
            extra["reference_images"] = [{"url": r, "role": "reference_image"}
                                         for r in refs[:icap]]
        if vids:
            extra["reference_videos"] = [{"url": v} for v in vids[:vcap]]
        if auds:
            extra["reference_audios"] = [{"url": a} for a in auds[:acap]]
        if extra:
            body["extra"] = extra
        return "/v1/videos", body, "/v1/videos/{id}"

    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 10, poll_timeout: int = 2400) -> dict:
        model = task.model or "sd2.0-720满血-不卡脸（按秒）"
        vpath, body, qpath = self.build_video_body(task)
        log(f"小裴 {model}（{branch_of(model)} 族）→ POST {vpath}")
        data = self.session.request("POST", vpath, json_body=body,
                                    retries=2, timeout=300)
        url = extract_video_url(data)
        task_id = extract_task_id(data)
        if not url:
            if not task_id:
                raise ApiError("提交没返回视频地址也没返回 task_id")
            url = self.session.poll(qpath, task_id, picker=extract_video_url,
                                    interval=poll_interval, timeout=poll_timeout,
                                    content_path_tpl="/v1/videos/{id}/content",
                                    log=log, cancel=cancel)
        self.session.save_item(url, dest)
        return {"task_id": task_id, "source": url, "provider": self.id, "model": model}
