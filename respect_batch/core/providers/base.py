# -*- coding: utf-8 -*-
"""服务商抽象层。

新增一个服务商 = 写一个继承 Provider 的类 + 在 __init__.py 注册。
`capabilities()` 返回的结构直接驱动前端表单渲染，不需要改前端代码。
"""

from __future__ import annotations

from typing import Callable, Optional

from ..apiutil import ApiError, HttpSession


class ImageTask:
    """一次出图请求（资产图 / 故事板通用）。"""

    def __init__(self, prompt: str, refs: Optional[list] = None, size: str = "1024x1536",
                 model: str = "", n: int = 1, extra: Optional[dict] = None):
        self.prompt = prompt
        self.refs = refs or []          # 已解析为 URL 或 data URI，顺序即 Image 1..N
        self.size = size
        self.model = model
        self.n = n
        self.extra = extra or {}


class VideoTask:
    def __init__(self, prompt: str, refs: Optional[list] = None, duration: int = 15,
                 ratio: str = "9:16", model: str = "", resolution: str = "",
                 extra: Optional[dict] = None):
        self.prompt = prompt
        self.refs = refs or []
        self.duration = duration
        self.ratio = ratio
        self.model = model
        self.resolution = resolution
        self.extra = extra or {}


class Provider:
    """服务商基类。"""

    id: str = ""
    name: str = ""
    default_base_url: str = ""
    supports: tuple = ()   # ("image",) / ("video",) / ("image", "video")

    # 参考图怎么给：
    #   data_uri —— 能直接吃图片内容（省事，默认）
    #   url      —— 只收公网链接，本机文件必须先上传（core/uploader.py）
    # 同一家不同模型可能不一样（零视图生视频吃 base64、SD2 只收 URL），
    # 所以还有 url_only_models 这个逃生口，按模型名细分。
    #   bytes    —— 走 multipart，只收真的文件字节，**给链接会被丢掉**
    ref_mode: str = "data_uri"
    url_only_models: tuple = ()
    # 这一家是不是**按账号计费、而且一个账号同时只能生成一条**。
    #
    # 声明成 True 之后，出片那一层会按账号排队（见 core/accounts.py）：
    # api_key 里粘几个账号就有几路并发，每个账号内部严格串行。
    # 不声明的家照旧按服务商并发，一个 Key 打到底。
    #
    # 为什么做成服务商自己声明：这是这一家的**计费和限流形状**，
    # 只有它自己知道。写在调度那一层就得维护一张「哪几家要这样」的名单，
    # 而漏了一家的后果是那家被并发打爆 —— 而且报错只会说「生成失败」。
    per_account_serial: bool = False

    # 这一家的 Key 是不是**分几把各自填**。每项 `(字段名, 分组前缀, 标签, 说明)`。
    #
    # 坤鸡就是这样：4K 是按**令牌分组**的，不是模型的区别（文档原文「1K 分组
    # 最高支持 1K；4K 分组支持 1K/2K/4K」）—— 同一把 Key 拿不到两档。
    #
    # 底层一直支持（`kunji.parse_keys` 认 `1k=sk-a;4k=sk-b`），但页面上只有
    # 一个密码框，用户得**自己知道这个写法**。不知道就只填一把，然后要 4K 时
    # 拿 1K 分组的 Key 去要 —— 服务商**静默降级**：你以为出了 4K，
    # 实际拿到 1K，不报错，图也在。所以页面上要一把一个框（跟超模一样）。
    #
    # 存的时候按前缀拼回 `api_key`（`前缀=值;…`）—— 服务商那边本来就认它，
    # 也是用户直接粘客服那段文本时的形状，不用改服务商一行代码。
    key_fields: tuple = ()

    # 账号表单：这一家的凭据由哪几个框组成。
    # `shared` 是多账号共用的（填一次），`per` 是每个账号各自的。
    # 每项 `(键名, 标签, 是不是密钥, 说明)` —— 键名要和服务商解凭据时
    # 认的别名一致（比如 hvtald 的 `_ALIAS`），否则填了也读不到。
    #
    # 为什么做成服务商自己声明：**只有它知道自己要哪几项**。写在页面里
    # 就得维护第二份字段表，而两份对不上的表现是「填了没生效」——
    # 用户填完点保存、页面显示正常，跑起来报「凭据不全」。
    account_form: dict = {}

    def selftest(self) -> Optional[dict]:
        """这一家自己的连通性自检。返回 `{"ok": bool, "msg": str}`。

        返回 `None` = 没有专门的自检，调用方回落到「拉一次模型列表」。

        为什么要这个钩子：统一的「拉模型列表」对**凭据不止一把**的家是
        假绿灯。HVTALD 的模型是固定一个、不联网 —— WebDAV 地址填错、
        账号密码填错，自检照样显示「1 个模型」。
        **假绿灯比没有检查更糟**：人会信它，然后去查别的地方。
        """
        return None

    def needs_url(self, model: str = "", media: str = "image") -> bool:
        """这家**只**收公网链接，给 data URI 会被丢掉。

        带 media 是因为同一家的图片和视频接口经常不一样（M86 出图的 ref_images
        只收链接，出视频却能吃 multipart 字节）。声明错的后果不是报错，是参考图
        被悄悄丢掉照样出图 —— 状态资产没了父资产或依赖参考，脸就不是本人。
        """
        return self.ref_mode == "url" or (model or "") in self.url_only_models

    def needs_bytes(self, model: str = "") -> bool:
        """这家的参考图只收文件字节。

        为什么必须单独声明：配了对象存储之后，解析器默认把本机文件一律上传换成
        公网链接（体积小、通用）。可 multipart 的接口拿到链接只能丢掉 ——
        图照样出，但没有父资产参考，状态资产的脸就飘了，而且**不报错**。
        这种静默降级比直接失败危险得多，所以解析器要按这个声明给对形式。
        """
        return self.ref_mode == "bytes"

    def accepts_url(self, model: str = "", media: str = "image") -> bool:
        """给这家公网链接它也能用吗。

        默认能 —— 大多数网关的 `images` 数组既吃链接也吃 data URI，链接还更省
        体积。但有两类不行，必须各自声明清楚，否则解析器一上传就把参考图作废了：
          · multipart 接口（只收文件字节）
          · 把参考图内联进某个字段、只认裸 base64 的（给链接会被原样发出去）
        """
        return not self.needs_bytes(model)

    def __init__(self, api_key: str = "", base_url: str = "", proxy: str = "", timeout: int = 900):
        self.session = HttpSession(api_key, base_url or self.default_base_url, timeout, proxy)

    # -- 能力声明（驱动前端） --------------------------------------------
    def capabilities(self) -> dict:
        """返回 {id,name,default_base_url,supports,image:{...},video:{...},notes}"""
        raise NotImplementedError

    # -- 探活 -------------------------------------------------------------
    def list_models(self) -> list:
        try:
            data = self.session.request("GET", "/v1/models", retries=1, timeout=30)
            return sorted(m.get("id", "") for m in (data.get("data") or []) if m.get("id"))
        except ApiError:
            return []

    # -- 生成 -------------------------------------------------------------
    def generate_image(self, task: ImageTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 5, poll_timeout: int = 900) -> dict:
        """生成并落盘到 dest。返回 {task_id, source, ...} 元信息。"""
        raise NotImplementedError("该服务商不支持出图")

    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 10, poll_timeout: int = 2400) -> dict:
        raise NotImplementedError("该服务商不支持出视频")
