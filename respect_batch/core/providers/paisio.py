# -*- coding: utf-8 -*-
"""鹤（api.paisio.online）。SD2 / SD3 / Seedance 全系。

「鹤」和「派系」是同一个网关的两个叫法 —— ComfyUI 侧 he_nodes.py 的 base_url
就是 api.paisio.online，文档是 y5dprsil1i.apifox.cn。之前这里显示成「派系」，
现在统一叫「鹤」。

视频：POST /v1/videos。**所有视频模型同一套请求体**（文档：「视频生成请求体。
所有视频模型使用相同的参数格式。」）——  prompt 原样 + image_url / extra_images，
用 @Image1 / @Img1 在正文里引用。旧模型那套 metadata+images 是我们自己造的，已删。
使用文档规定的 aspect_ratio/image_url/extra_* 标准格式。
图片：OpenAI 兼容 /v1/images/generations（同步或异步都兼容）。

这家还有两个能力本程序没实现，需要时再补：
  · POST /v1/images/edits —— 最多 16 张图 + mask，能做局部重绘（定向修订用得上）
  · POST /v1/virtual-assets —— 官方的参考**视频/音频**上传途径（→ va_xxx，
    再 /sync 轮询到 active）。目前 Seedance 2.5 的图片通过项目对象存储转公网 URL；
    虚拟资产上传仍未接入。
"""

from __future__ import annotations

from typing import Callable, Optional

from ..apiutil import ApiError, extract_image_items, extract_task_id, extract_video_url
from .base import ImageTask, Provider, VideoTask


# 2026-08-28 用真 Key 实拉 GET /v1/models 校正（83 个）。上一版是 08-19 的快照。
# **鹤这次换了一整轮清单**：新增 `paisio-seedance-2.5-480p` / `-720p` 这套带
# `paisio-` 前缀的 2.5 写法，而 `seedance2.5-00-720p` / `-480p`、`sd2.5-ultra-720p`
# 已经下线 —— 模型名不能靠文档或旧材料猜，也不能指望上一次实拉的结果还成立。
# 鹤文档写的提示词上限。**只提醒不硬校验** —— 见 _video_body 里的说明：
# 这套流程的视频提示词普遍 7800-8400 字，硬拦等于这家不能用。
PROMPT_SOFT_MAX = 2500

# 2026-09-01 实拉又下线两个：`seedance2.5-4-1-720p`、`sd2.5-720p-standard`。
# 这一族的名字换得比什么都快 —— 所以能力判定一律走 `is_seedance25()`
# 的家族标记，别拿名字来精确比对（见下面）。
SEEDANCE25_MODELS = (
    "seedance2.5-26-720p", "seedance2.5-26-480p",
    "paisiodance-2.5-720p", "paisiodance-2.5-480p",
    "paisio-seedance-2.5-720p", "paisio-seedance-2.5-480p",   # 08-28 新增的写法
    "doubao-seedance-2-5-720p",                  # 同一个 2.5，豆包品牌的透传名
)
SEEDANCE25_DURATIONS = list(range(4, 31))        # 广场标 4-30s（不是 4-29）

# 名单会过期，家族不会 —— 所以能力判定一律走这个函数，别再拿名字去
# SEEDANCE25_MODELS 里精确比对。
#
# 为什么非改不可：2.5 的能力以前挂在**六处精确名单成员判定**上（下拉候选、
# 时长档位、参考图形式、body 形状、档位校验、多镜头能力）。鹤 08-28 加了
# `paisio-seedance-2.5-*` 这套新写法，六处**一起**漏判，而其中三处是静默的：
#   · 时长回落到整家的 15 秒上限 —— 用户想选 30 秒选不到（页面上看不出原因）
#   · 参考图按 data URI 发，而 2.5 只收公网 URL —— 图被丢掉照样出片，脸不对，不报错
#   · body 一律走文档那套：prompt + image_url + extra_images
# 同一个毛病 08-19 已经犯过一次（那次是 _MULTISHOT 里的连字符）。名单继续
# 写死就还会有第三次，所以判定收敛到这里一处。
_SD25_MARKS = ("seedance2.5", "seedance-2.5", "seedance-2-5", "paisiodance-2.5", "sd2.5")


def is_seedance25(model: str) -> bool:
    """这个名字属于 Seedance 2.5 家族吗（4-30 秒 / 公网 URL / 新 body 形状）。

    片段匹配，覆盖 `seedance2.5-*`、`paisio-seedance-2.5-*`、`paisiodance-2.5-*`、
    `doubao-seedance-2-5-*`、`sd2.5-*` 一整族。
    刻意**不**匹配 `paisio-seedance-2-mini-*` / `seedance2-4-*`（那是 2.0 系
    和按次分组，body 形状不一样）。

    宽判的代价是可控的：万一鹤出一个名字带 2.5 但规格不同的模型，会被当成 2.5
    发出去、被网关 400 挡掉（不计费）。漏判的代价是参考图静默失效 —— 出片、计费、
    脸不对。两害相权取宽判。
    """
    m = (model or "").lower().replace("_", "-")
    return any(mark in m for mark in _SD25_MARKS)


# 广场上标出来的硬约束，只写有依据的那几个。08-28 实拉：`seedance2-4-8-720p`
# 已下线，规则一并撤掉；新上的 `seedance2-4-6/4-7-720p` 广场没截到档位，
# 不写 —— 宁可让网关去 400（不计费），也别拿猜的规则拦住能跑的活。
DURATION_RULES = {
    # seedance2.5-4-1-720p 已下线（2026-09-01 实拉）；这一条留着无害，
    # 但清单里不再列它，免得页面上还能选到。
    "seedance2-4-2-fast-720p": (10,),
    "seedance2-4-1-720p": tuple(range(4, 16)),
    "seedance2-4-4-720p": tuple(range(4, 16)),
}
# (图, 视频, 音频)。seedance2.5-4-1-720p 广场标 10/0/0 —— **不收参考视频和音频**。
# 这个模型 2026-09-01 已下线，这条留着是为了老项目里存着这个名字时还能判对。
REF_LIMITS = {"seedance2.5-4-1-720p": (10, 0, 0)}
REF_LIMITS_DEFAULT = (30, 10, 10)
SEEDANCE25_RATIOS = ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9", "3:2", "2:3"]


# 视频模型清单**提成模块常量**，因为 `model_options` 要按家族标记从它推 ——
# 内联在返回的字典里时同一个字面量引不到自己，于是那边只能另抄一份
# 静态元组，两份迟早对不上（2026-09-01 就对不上了，见 model_options）。
VIDEO_MODELS = [
                # 2026-08-28 用真 Key 实拉 GET /v1/models 校正（上一次是 08-19）。
                # 名字只能来自 /v1/models，不能照文档或上一次的快照抄 ——
                # 页面上留一个已下线的名字，是能选中、跑起来才 503，
                # 而失败记录里只看到"生成失败"。
                # 这轮下线的（已从清单里撤掉）：sd2-ultra-720p、
                # sd2-ultra-fast-720p、paisiodance2.0-fast-720p、
                # seedance2-4-8-720p、seedance2.5-00-720p/-480p、
                # sd2.5-ultra-720p、grok-imagine-video-1.5(-fast)。
                # **sd2-* 整族下线了**（2026-09-01 实拉 /v1/models 确认）：
                # sd2-720p / -480p / -1080p / sd2-fast-720p / -480p 全都不在了。
                # 而 `sd2-720p` 正是这一家的 default_model **和代码里的兜底**
                # （`task.model or "sd2-720p"`）—— 也就是说：没显式指定模型的
                # 视频任务，一条都发不出去，报「找不到模型」。
                # 现存的 sd2 只剩这两个 mini：
                "sd2-video20-mini-720p", "sd2-video20-mini-480p",
                "sd2-19-720p", "sd2-19-480p", "sd2-19-1080p", "sd2-19-4k",
                "sd2.5-19-720p", "sd2.5-19-pro-720p",
                "sd2.5-19-pro-1080p", "sd2.5-19-pro-480p",
                "sd3-720p", "sd3-480p", "sd3-1080p",
                "sd3-fast-720p", "sd3-fast-480p",
                # 2.0 系。08-28 新上的 paisio-seedance-2.0-* / -2-mini-* /
                # seedance2.0-standard-* / -26-* / doubao-seedance-2-0-*
                "paisio-seedance-2.0-480p", "paisio-seedance-2.0-720p",
                "paisio-seedance-2.0-1080p", "paisio-seedance-2.0-4k",
                "paisio-seedance-2.0-fast-480p", "paisio-seedance-2.0-fast-720p",
                "paisio-seedance-2-mini-480p", "paisio-seedance-2-mini-720p",
                "seedance2.0-standard-480p", "seedance2.0-standard-720p",
                "seedance2.0-26-3-480p", "seedance2.0-26-3-720p",
                "seedance2.0-26-4-720p", "seedance2.0-fast720p",
                "seedance2.0-selfsur-720p", "seedance2.0-selfsur-fast-720p",
                # paisiodance2.0-720p 这一轮也下线了（实拉确认）
                "doubao-seedance-2-0-720p", "doubao-seedance-2-0-fast-720p",
                # 按次分组
                # seedance2-4-1-720p 下线（实拉确认）
                "seedance2-4-2-fast-720p",
                "seedance2-4-4-720p", "seedance2-4-6-720p", "seedance2-4-7-720p",
                # Seedance 2.5 全家
                *SEEDANCE25_MODELS,
                "minimax-h3", "minimax-h3-2k", "minimax-h3-768p", "mx-h3",
]


class PaisioProvider(Provider):
    # id 保持 "paisio" 不动：它是 config.json 里 providers / chains /
    # limits.per_provider 的键，改了等于让已保存的 key 和优先级链全部失效。
    # 显示名叫「鹤」，内部键叫 paisio —— 这是两回事。
    id = "paisio"
    name = "鹤 api.paisio.online（SD2/SD3/Seedance）"
    aliases = ("he", "pis", "派系")      # 认这些别名，指到同一家
    default_base_url = "https://api.paisio.online"
    supports = ("image", "video")
    # 新文档明确要求 image_url / extra_images 是公网 http(s) URL。
    # 没配对象存储时宁可在发送前报清楚，也不能把 data URI 发出去后让参考图静默失效。
    url_only_models = SEEDANCE25_MODELS

    def needs_url(self, model: str = "", media: str = "image") -> bool:
        """视频**一律**只收公网 URL；图片沿用原来的按家族判。

        文档（提交视频生成任务）:「所有视频模型使用**完全相同**的请求参数格式」，
        字段是 `image_url` / `extra_images` / `start_image_url`，写明「字符串 URL
        或 {url:"..."}」—— 没有能塞 data URI 的字段。

        ⚠ 这里以前只对 2.5 家族返回 True，而 `_video_body` 合成一条之后
        **对所有模型**拒绝非 http 参考图 —— 两处声明打架：
          · 配了对象存储：参考图本来就是 URL，看不出问题
          · **没配对象存储**：produce.py 按 needs_url=False 交 data URI，
            请求体当场 task_fatal —— 旧模型带参考图的活全线失败
        而报错说的是「请配置对象存储」，位置也不对：该在 uploader 那里说，
        它才写得清去哪个设置页填什么。

        图片那条不动：出图用的是 `image` 字段，原来就能吃 data URI。
        """
        if media == "video":
            return True
        return is_seedance25(model) or super().needs_url(model, media)

    # -- 余额与实时价格（GET /v1/balance）--------------------------------
    def balance(self) -> dict:
        """余额 / VIP等级 / 今日次数 / **current_prices 实时价格表**。

        `current_prices` 就是这个 Key 真正能用的模型清单 —— 比写死的列表可靠，
        也不用去撞需要鉴权的 /v1/models。价格随 VIP 等级变，所以必须按 Key 查。
        """
        return self.session.request("GET", "/v1/balance", retries=1, timeout=60)

    def live_models(self) -> list:
        """从 /v1/balance 的价格表取模型名（按价格升序）。取不到就返回空。

        ⚠ 2026-08-28 实测：这条路在鹤这边**是死的** —— 同一个 Key，
        `/v1/models` 通，`/v1/balance` 报 401 INVALID_TOKEN（`/api/pricing`
        和 `/api/status` 都 403）。也就是说这个函数现在恒返回 []，
        而它目前没有任何调用方。要实拉清单请用基类的 `list_models()`
        （GET /v1/models，零费用，已验证可用）。留着它是因为余额接口
        将来可能开放；别在它上面搭新功能。
        """
        try:
            data = self.balance()
        except Exception:                                   # noqa: BLE001
            return []
        prices = (data or {}).get("current_prices") or {}
        return sorted(prices, key=lambda k: prices.get(k) or 0)


    def capabilities(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "default_base_url": self.default_base_url,
            "supports": list(self.supports),
            "image": {
                # 2026-08-28 实拉：上一版这 16 个名字**一个都不在线上了**
                # （gpt-image-2-1k/2k/4k、gpt-image2-low/medium/high、
                #  nano-banana-2-*、nano-banana-pro-*、image-2-1K/2K、
                #  gemini-*-image-preview 不带尾号的那两个）。
                # 鹤当图片服务商时整家都是假绿灯：页面上选得到、跑起来全 503。
                # 现在的写法是 gpt-image2-<分组>-<画质>、gemini-*-preview<分组号>。
                # 分组号（1/2/3）是网关的通道分组，不是画质；画质是 low/medium/high。
                "models": ["gpt-image2-1-low", "gpt-image2-1-medium", "gpt-image2-1-high",
                           "gpt-image2-2-low", "gpt-image2-2-medium", "gpt-image2-2-high",
                           "gemini-3-pro-image-preview1", "gemini-3-pro-image-preview2",
                           "gemini-3-pro-image-preview3",
                           "gemini-3.1-flash-image-preview1",
                           "gemini-3.1-flash-image-preview2",
                           "gemini-3.1-flash-image-preview3"],
                "default_model": "gpt-image2-1-high",
                "sizes": ["1024x1536", "1024x1024", "1536x1024"],
                "default_size": "1024x1536",
                "max_refs": 9,
                "ref_mode": "data_uri",
                "notes": "⚠ 2026-08-28 实拉：**旧的 gpt-image-2-1k / -2k / -4k 和 "
                         "nano-banana 全系都已下线**，现在是 gpt-image2-1-high 这种"
                         "「分组号 + 画质」写法（1/2 是网关通道分组，low/medium/high 是画质）。"
                         "Gemini 的三个尾号 1/2/3 同理，也是分组不是画质。"
                         "**没有**不带后缀的 gpt-image-2（那是灵感鸭的写法，"
                         "填错会报「找不到这个模型」）。low 最便宜，试跑用它。"
                         "名字以 /v1/models 为准 —— 这家半年内换过两轮。",
            },
            "video": {
                # 分辨率写在模型名里，所以不用也不能传 resolution。
                # 名字里带 fast 的便宜、带 480p 的更便宜 —— 调试和试跑用它们。
                "models": VIDEO_MODELS,
                # **默认换成一个实拉里真存在的。** 原来是 sd2-720p —— 那一族
                # 整个下线了，于是「没改过模型就点开始」必然失败。
                # 挑 720p 的 2.5：这套流程的主力档，实拉在，也是材料里用的那个。
                "default_model": "paisio-seedance-2.5-720p",
                "ratios": ["9:16", "16:9", "1:1"],
                "durations": [4, 5, 8, 10, 12, 15],
                "default_duration": 15,
                "resolutions": [""],
                "max_refs": 9,
                "ref_mode": "data_uri",
                # 不能把 2.5 的 30 秒/30 图能力写成整家通用值，否则切回旧模型时
                # 前端仍会允许选 30 秒，直到付费请求发出去才收到 400。
                #
                # 依据分两档，别混：**名字**是 08-28 实拉 /v1/models 确认的；
                # **4-30 秒**只对 seedance2.5-4-1-720p 有广场截图，其余 2.5 是
                # 按家族推断的（鹤没开放 /api/pricing —— 实测 403，/v1/balance
                # 也 401，拿不到按模型的档位）。推断错的代价是网关 400，不计费；
                # 真跑通了别的档位就写进「设置 → 服务商 → 时长档位」，那份覆盖
                # 优先级最高（web/index.html:effectiveBlock）。
                #
                # **按家族标记推，不按那个静态元组。** 这两处以前不是一回事：
                # `model_options` 从 `SEEDANCE25_MODELS` 生成，而能力判定走
                # `is_seedance25()` 的片段匹配 —— 于是任何一个「标记认得、
                # 元组里没有」的名字（2026-09-01 加进来的 `sd2.5-19-720p`
                # 就是）会拿到整家的 4-15 秒和 data_uri，而它其实是 2.5：
                # 时长选不到 30 秒，参考图按 data URI 发而 2.5 只收公网链接 ——
                # **图被丢掉照样出片，脸不对，不报错**。
                # 这个文件自己写过「名单会过期，家族不会」，这里补上那一步。
                "model_options": {
                    model: {
                        "durations": SEEDANCE25_DURATIONS,
                        "ratios": SEEDANCE25_RATIOS,
                        "max_refs": 30,
                        "max_video_refs": 10,
                        "max_audio_refs": 10,
                        "ref_mode": "url",
                    }
                    for model in VIDEO_MODELS if is_seedance25(model)
                },
                "notes": "分辨率写在模型名里，不用也不能单独传。名字带 fast 的便宜、"
                         "带 480p 的更便宜 —— 试跑和调提示词用 sd3-fast-480p / "
                         "sd3-fast-480p，定稿再换 720p/1080p。"
                         "**模型名以 /v1/models 为准**，"
                         "2026-08-28 实拉又下线了 9 个（sd2-ultra 系、seedance2.5-00 系、"
                         "sd2.5-ultra-720p、grok 视频），同时新增了 paisio-seedance-2.5-* 这套写法。"
                         "旧模型参考图可用压缩 data URI；Seedance 2.5 必须使用公网 URL，"
                         "支持 4-30 秒、30图/10视频/10音频 —— 要 30 秒就选 2.5 家族的名字，"
                         "选旧模型时上限是 15 秒。",
            },
            "notes": "视频首选。也提供 chat 模型（claude/gpt 系）可作 LLM 分析引擎。",
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
            # 文档 2026-08 新增：async=true 返回 task_id，再轮询任务。
            # 4K 同步出图很容易把连接拖到超时，异步才是该走的路。
            "async": True,
        }
        refs = list(task.refs or [])
        if len(refs) > 1:
            # 文档的统一出图接口只列了**单个** `image` 字段，没有多图入口。
            # 以前这里发的是 `images` 数组 —— 文档里没有这个字段，
            # 多半被网关整个忽略：图照出，但一张参考图都没生效，而且不报错。
            raise ApiError(
                f"鹤的出图接口只收 1 张参考图（文档字段是单数 image），这一项要 {len(refs)} 张。"
                f"少了参考图出来的就不是同一个人/同一个东西，所以不出这张图 —— "
                f"把多图参考的活排给支持多图的服务商。",
                status=0, kind="task_fatal")
        if refs:
            body["image"] = refs[0]

        data = self.session.request("POST", "/v1/images/generations", json_body=body,
                                    retries=2, timeout=600)
        items = extract_image_items(data)
        task_id = extract_task_id(data)
        if not items:
            if not task_id:
                raise ApiError("提交未返回 task_id 或图片")
            # 文档的异步查询端点是 /v1/images/generations/{task_id}，
            # **不是** /v1/images/{id}（那个路径查不到，只会白等到超时）。
            items = self.session.poll("/v1/images/generations/{id}", task_id,
                                      picker=extract_image_items,
                                      interval=poll_interval, timeout=poll_timeout,
                                      log=log, cancel=cancel)
        self.session.save_item(items[0], dest)
        return {"task_id": task_id, "source": items[0][:200], "provider": self.id,
                "model": body["model"]}

    # ---------------------------------------------------------------- video
    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 10, poll_timeout: int = 2400) -> dict:
        # 兜底也要跟着换 —— 这里和 default_model 是**两处**，
        # 只改一处的后果是页面显示新的、实际发旧的。
        model = task.model or "paisio-seedance-2.5-720p"
        # **所有视频模型用同一套请求体。** 文档原话（提交视频生成任务）：
        # 「视频生成请求体。所有视频模型使用相同的参数格式。」
        #
        # 原来这里按模型分两条路，旧模型那条自己造了一套字段 ——
        # `images` 数组（文档没有这个字段）、`metadata.ratio` / `modeType`
        # （文档没有 metadata），而且**往正文末尾追加 `@图1..N`**。
        # 文档里的引用语法是 `@Image1` / `@Img1`，压根没有 `@图N` 这个写法。
        #
        # 后果正是用户报的「提示词失效 / 参考图失效」：材料里的正文已经用
        # `@Image1..N` 写好了身份映射，末尾又被追加一串 `@图1..5` ——
        # 同一个请求里两套编号，而参考图塞在一个服务商不认的字段里。
        # 图能出、片能出，用的参考图和正文说的对不上，一处都不报错。
        body = self._video_body(task, model)
        note = body.pop("_note", "")
        if note:
            log("⚠️ " + note)
        data = self.session.request("POST", "/v1/videos", json_body=body, retries=2, timeout=300)
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

    @staticmethod
    def _video_body(task: VideoTask, model: str) -> dict:
        refs = list(task.refs or [])
        videos = list(task.extra.get("video_refs") or task.extra.get("videos") or [])
        audios = list(task.extra.get("audio_refs") or task.extra.get("audios") or [])
        duration = int(task.duration or 15)
        ratio = task.ratio or "9:16"

        problems = []
        prompt = task.prompt or ""
        # 空提示词一定不出片 —— 与其花一次调用换一句 400，不如现在停。
        if not prompt.strip():
            problems.append("提示词是空的")
        # **文档写的 2500 字上限只提醒、不拦。**
        #
        # origin/main（2026-08-31）按文档把它写成了硬校验。合并时没照搬 ——
        # 拿真材料量过：这套流程的视频提示词 7800-8400 字，**98 段全部超过**；
        # 图片提示词 331 条里 289 条超。照那条硬拦，鹤这家一条都发不出去。
        # 而这个数字来自文档、没有实测背书（这个项目里「文档和实拉对不上」
        # 已经出过好几次：模型清单一次就下线了 15 个）。
        #
        # 这里是 @staticmethod，**没有 log** —— 直接调会 NameError，而它只在
        # 真跑到这一行时才炸。所以把话挂在 body 上，让调用方打。
        note = ""
        if len(prompt) > PROMPT_SOFT_MAX:
            note = (f"提示词 {len(prompt)} 字，鹤的文档写的上限是 "
                    f"{PROMPT_SOFT_MAX} 字 —— **没有实测确认，所以没拦**。"
                    f"这一条要是回 400 说提示词过长，那就是它；去 "
                    f"core/providers/paisio.py 把 PROMPT_SOFT_MAX 那段改成 "
                    f"problems.append 就是硬校验。")
        allowed = DURATION_RULES.get(model)
        if allowed and duration not in allowed:
            problems.append(f"{model}的时长只能是{min(allowed)}-{max(allowed)}秒，收到{duration}秒"
                            if len(allowed) == max(allowed) - min(allowed) + 1
                            else f"{model}的时长只能是{'、'.join(map(str, allowed))}秒，收到{duration}秒")
        elif not allowed and not 4 <= duration <= 30:
            problems.append(f"时长按4-30秒处理，收到{duration}秒")
        if ratio not in SEEDANCE25_RATIOS:
            problems.append(f"比例只支持{'、'.join(SEEDANCE25_RATIOS)}，收到{ratio}")
        cap_i, cap_v, cap_a = REF_LIMITS.get(model, REF_LIMITS_DEFAULT)
        if len(refs) > cap_i:
            problems.append(f"{model}图片最多{cap_i}张，收到{len(refs)}张")
        if len(videos) > cap_v:
            # 标 10/0/0 的模型压根不收参考视频 —— 发过去被忽略，
            # 与其静默丢掉不如直接说，免得以为运镜参考生效了
            problems.append(f"{model}不支持参考视频，收到{len(videos)}条" if cap_v == 0
                            else f"视频素材最多{cap_v}条，收到{len(videos)}条")
        if len(audios) > cap_a:
            problems.append(f"{model}不支持参考音频，收到{len(audios)}条" if cap_a == 0
                            else f"音频素材最多{cap_a}条，收到{len(audios)}条")
        local_refs = [r for r in refs if not str(r).startswith(("http://", "https://"))]
        if local_refs:
            problems.append("参考图必须先转成公网 http/https URL（请配置对象存储）")
        if problems:
            # 前缀不能写死「Seedance 2.5」—— 这个函数现在管所有视频模型，
            # 旧模型看到那句会以为自己选错了模型，往完全错的方向查。
            raise ApiError(f"鹤 {model} 的视频参数不符合接口要求：" + "；".join(problems),
                           status=0, kind="task_fatal")

        body = {
            "model": model,
            "prompt": prompt,   # 上面校验过的那一份，原样发，不追加任何 @ 引用
            "duration": duration,
            "aspect_ratio": ratio,
        }
        if task.extra.get("first_last") and len(refs) >= 2:
            # 文档 2026-08 新增：start_image_url=首帧、end_image_url=末帧
            # （「部分模型支持首尾帧控制」）。文档没说它俩能不能和 image_url 同发，
            # 所以这条路径**不发 image_url / extra_images**，两组字段不混。
            body["start_image_url"], body["end_image_url"] = refs[0], refs[1]
        elif refs:
            # prompt 里可用 @Image1 / @Image2 引用，顺序就是编号
            body["image_url"] = refs[0]
            if len(refs) > 1:
                body["extra_images"] = refs[1:]
        if videos:
            body["extra_videos"] = videos
        if audios:
            body["extra_audios"] = audios
        if note:
            body["_note"] = note   # 调用方打完就 pop，不发给服务商
        return body
