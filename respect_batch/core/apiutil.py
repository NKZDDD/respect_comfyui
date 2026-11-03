# -*- coding: utf-8 -*-
"""服务商共用的 HTTP / 解析 / 落盘工具。不依赖 ComfyUI、torch。"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import re
import tempfile
import time
from contextlib import contextmanager
from typing import Any, Optional

import requests

from . import submitted

# 完成词。**多收几个同义词是有价值的**，不只是靠下面那支兜底：
# 认出「完成」之后还有一步 —— 完成了但响应里没给地址时，会去打
# `content_path_tpl` 那个下载端点；而走兜底那支是拿不到这一步的。
DONE_STATES = ("completed", "succeeded", "success", "done", "finished", "complete",
               "generated", "succeed", "successful", "finish")
FAIL_STATES = ("failed", "cancelled", "canceled", "error", "fail")
# 「还在跑」的说法。**这张表存在的理由是第四种情况：状态词我们不认识。**
#
# 原来只有完成和失败两张表，认不出的词一律当成「还没好」—— 于是
# **结果地址已经拿在手里了，却接着睡到超时**：服务商平台上显示完成，
# studio 这边还在等。而等满之后报的是「任务超时」，人会去查线路、查服务商，
# 查不到任何东西，因为那条任务早就好了。
#
# 现在分三类：认识的「在跑」→ 接着等（哪怕响应里有地址，那多半是回显的
# 输入图或预览）；认识的完成/失败 → 照旧；**认不出的 → 当作没有状态**，
# 手上有结果就收下，并且在日志里点名那个词，好补进这张表。
RUNNING_STATES = (
    "queued", "pending", "processing", "in_progress", "in-progress", "inprogress",
    "running", "waiting", "created", "submitted", "start", "starting",
    "generating", "uploading", "preparing", "init", "initializing",
    "progress", "incomplete", "not_start", "notstart", "doing", "active",
    "accepted", "scheduled", "retrying",
)
MEDIA_VIDEO = (".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi")
MEDIA_IMAGE = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
URL_KEYS = ("url", "video_url", "download_url", "file_url", "result_url", "image_url")


# ---------------------------------------------------------------- 错误分级
#
# retryable   —— 网络抖动/限流/网关错误：值得同参重试
# task_fatal  —— 这一个任务本身的问题（提示词违规、参数不合法）：重试无意义，跳过它继续跑别的
# batch_fatal —— 账户级问题（余额不足、密钥失效、封禁）：重试和继续都无意义，立即熔断整批
RETRYABLE, TASK_FATAL, BATCH_FATAL = "retryable", "task_fatal", "batch_fatal"

# 余额/鉴权类关键词（各中转站措辞不一，做宽匹配）
_BATCH_FATAL_KW = (
    "insufficient", "quota", "balance", "billing", "payment", "credit",
    "exceeded your current", "no more credit", "out of credit",
    "invalid api key", "invalid_api_key", "incorrect api key", "unauthorized",
    "authentication", "token 不正确", "令牌", "余额", "额度", "欠费",
    "无可用渠道", "账户", "已封禁", "禁用", "过期",
)
# 「这段内容不让过」——**只认平台的判词，不认内容名词。**
#
# 这一条踩过两次，方向相反：
#
#   漏：表里只有「违规」没有「违反」，也没有「防护限制」，于是
#       「该提示可能违反了关于暴力内容的防护限制」被判成「没见过的错误」，
#       自动改写提示词那一层根本没被触发，只白重试了两次。
#
#   过：补完之后我一度把「暴力」「血腥」「色情」也当成触发词 ——
#       **而这些正是短剧剧本的常用词**。不少服务商会把提示词原样回显在
#       报错里，一旦回显，一个网络错误也会因为台词里有「他违反了约定」
#       而被判成内容审核：不再重试（内容问题按不可重试处理），
#       还白跑几轮改写。
#
# 分界线是：**平台说话的方式和剧本写人的方式不一样**。
# 「防护限制」「内容政策」「审核未通过」「修改提示语」不会出现在台词里；
# 「暴力」「违反了约定」天天出现。所以只收前者。
CONTENT_REJECT_RE = re.compile(
    # 英文：平台判词
    r"content polic|content guideline|usage polic|safety (system|filter|polic)"
    r"|content filter|moderation|policy violation|violat\w* (our|the|content|safety)"
    r"|prohibited (content|by)|not allowed by|disallowed by|blocked by"
    r"|flagged (as|by|for)|rejected by|restricted content|harmful content"
    # 中文：平台判词。「违反」必须带上它违反的是什么，光一个「违反」不算 ——
    # 台词里的「你违反了约定」会误伤
    r"|违反了?[^。；\n]{0,14}(限制|政策|策略|规范|准则|条款|规定|协议)"
    r"|防护限制|安全限制|内容政策|内容策略|安全策略|使用政策|社区(规范|准则)"
    r"|审核(未|不)通过|未通过审核|内容审核"
    # 「违规」也得带上判定的语气 —— 剧本里「他违规操作」不算平台判词
    r"|(涉嫌|涉及|存在|判定为?|属于)违规|违规内容|内容违规|违规，"
    r"|不当内容|不适当内容|敏感内容|命中敏感"
    r"|(拒绝|不予|无法)生成|已被拦截|被(拦截|屏蔽)"
    # unsafe 那一族。实遇（2026-08-26，超模出图）：
    #   "The generated images appear to be unsafe. Try modifying the prompt or seeds."
    #   服务商错误码 image_task_error —— 那是个通用码，**不能拿它判审核**
    #   （网络错、参数错也是这个码），只有文案能分。
    # 这条以前判成 UNKNOWN，于是**一轮改写都不走**：短剧里打人流血是常规戏，
    # 本该自动改写重发的活儿直接算失败，人得手动去改提示词。
    # 只收「明确说这东西不安全」的写法，不收裸的 safe/safety ——
    # 剧本里「安全屋」「他不安全」会误伤。
    r"|appear\w* to be unsafe|(is|was|are|were) unsafe"
    r"|unsafe (image|content|prompt|output)|\bnsfw\b"
    # 让你怎么办 —— 最强的信号，只有内容问题才会这么说
    r"|修改提示(语|词)|调整提示(语|词)|更换描述"
    # 同一句的英文写法。原来只有中文，于是英文网关的同一句话认不出来。
    r"|(modify|modifying|change|adjust|rephrase|revise)\w*"
    r"\s+(the\s+|your\s+)?prompt", re.I)

_TASK_FATAL_KW = (
    "invalid prompt", "prompt too long", "unsupported",
)


# 「这会儿排不上」和「账户没钱」是两件事，而两边都会出现 quota / 额度 这个词。
#
# 实跑撞到：`HTTP 429 No available image quota. Please try again later.`
# ——「quota」命中了上面那张余额表，于是被判成 batch_fatal，**整批立刻熔断**，
# 卡片写着「这家服务商的账户没钱了」。而账户是有钱的，那句话是「稍后再试」。
# 后果：一次临时排队，整批图停掉，人跑去充值。
#
# 429 本来就是限流码。带着「稍后再试」的 429 一律当临时状况处理 ——
# 真欠费的家不会让你 try again later。
_TRANSIENT = re.compile(
    r"try again later|retry later|稍后再?试|请稍[后候]|暂时(不可用|无法|没有)"
    r"|temporarily (unavailable|busy)|rate limit", re.I)


# 各家在 `error.code` / `error.type` 里给的机器可读错误码。
#
# **有码就认码，别去猜措辞。** 措辞随时会变、会翻译、会本地化，
# 而码是给程序看的。只有拿不到码（或者码是 upstream_error 这种通用值）时
# 才退回读 message —— 那是下策，不是首选。
_CODE_CONTENT = frozenset({
    "content_policy_violation", "content_policy", "content_filter",
    "content_filtered", "sensitive_content", "moderation_blocked",
    "safety_violation", "safety_error", "prohibited_content",
    "image_generation_user_error", "invalid_prompt",
})
_CODE_QUOTA = frozenset({
    "insufficient_quota", "insufficient_balance", "billing_hard_limit_reached",
    "account_deactivated", "quota_exceeded",
})
_CODE_AUTH = frozenset({
    "invalid_api_key", "invalid_authentication", "authentication_error",
})
_CODE_RETRY = frozenset({
    "rate_limit_exceeded", "server_error", "service_unavailable",
    "engine_overloaded", "timeout", "gateway_timeout",
})


def code_kind(err_code: str) -> str:
    """服务商给的机器码 → 三级分类。不认识返回空字符串。"""
    c = (err_code or "").strip().lower()
    # Polling failures arrive as HTTP 200; their ApiError status is 0.
    # Parameter errors must not fall through to the status-0 retry rule.
    if c in _CODE_CONTENT or c == "invalid_duration":
        return TASK_FATAL
    if c in _CODE_QUOTA or c in _CODE_AUTH:
        return BATCH_FATAL
    if c in _CODE_RETRY:
        return RETRYABLE
    return ""


# 「这个**模型**不行」和「这个**账户**不行」是两回事，而它们共用状态码。
#
# 实遇（2026-09-14，超模）：一个账号按能力分四把 Key，**每把能看见的模型完全
# 不重叠**（一把只有 gpt-image-1k-th，另一把只有 2.5 那六个＋Native 三个）。
# 拿错 Key 槽去发某个模型，回的是：
#     403 {"message": "model gpt-image-1k-th is not available for this API key"}
# 而 403 原来一律判 BATCH_FATAL —— **立即熔断整批**，几百条任务当场停，
# 报错还写着「账户问题」，人会跑去充值。而真相只是模型选错了/Key 槽用错了。
#
# 反向也有一条：`404 model not found` 原来落到 RETRYABLE（0/404 那一档），
# 于是模型名打错会同参重发，每次撞同一堵墙 —— 而巨轮那家的名字带空格和
# 全角括号，打错是常事。
#
# 两条都归 TASK_FATAL：这一条做不成，但别的任务和账户都是好的。
_MODEL_LEVEL = re.compile(
    r"model[^\n]{0,80}(is )?not (available|found|supported|exist)"
    r"|not (available|permitted) for this api key"
    r"|模型[^\n]{0,20}(不存在|不可用|无权|没有权限)"
    r"|无权使用[^\n]{0,20}模型", re.I)


def classify(status: int, text: str = "", err_code: str = "") -> str:
    """把 HTTP 状态 + 服务商错误码 + 响应体分成三级。

    优先级：**服务商给的机器码 > HTTP 状态 > 响应体措辞**。
    只靠措辞是最脆的一层 —— 但也去不掉：有的家只给 `upstream_error`
    这种通用码，真正的原因只写在 message 里（实跑撞到过）。
    """
    by_code = code_kind(err_code)
    if by_code:
        return by_code
    low = (text or "").lower()
    # **模型级的要排在账户级前面。** 两者共用 403（见 _MODEL_LEVEL 的说明）：
    # 「这把 Key 用不了这个模型」熔断整批是错的 —— 别的模型和账户都好好的。
    if _MODEL_LEVEL.search(text or ""):
        return TASK_FATAL
    if status in (401, 402, 403):
        return BATCH_FATAL
    if status == 429 and _TRANSIENT.search(text or ""):
        return RETRYABLE
    if any(k in low for k in _BATCH_FATAL_KW):
        return BATCH_FATAL
    # **内容问题要排在状态码前面。**
    #
    # 轮询式的服务商是「HTTP 200 + 任务状态 failed」，我们抛出来的 ApiError
    # status 是 0 —— 而 0 在下面那行属于「可重试」，于是内容被拒也被原样重发。
    # 实跑就是这样：章鱼哥回「该提示可能违反了关于暴力内容的防护限制」，
    # 程序照样重试两次，每次都要重新出一张图，拿回同一句话。
    #
    # 内容问题跟它是从哪个状态码回来的没有关系，所以先判它。
    if CONTENT_REJECT_RE.search(text or "") or any(k in low for k in _TASK_FATAL_KW):
        return TASK_FATAL
    if status == 429:
        return RETRYABLE
    if status in (408, 409, 425, 500, 502, 503, 504, 0):
        return RETRYABLE
    if status in (400, 422):
        return TASK_FATAL
    return RETRYABLE


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int = 0, kind: str = "",
                 retry_after: float = 0, err_code: str = ""):
        super().__init__(message)
        self.status = status
        # 服务商给的机器可读错误码。**要单独留着**，别只靠 message ——
        # 拍进字符串里之后，判断就只剩「在一堆文字里搜关键词」这一条腿。
        self.err_code = err_code
        self.kind = kind or classify(status, message, err_code)
        self.retry_after = retry_after
        # 服务商可以往这里塞「该查什么」的清单：有些家的 400 只回一句笼统话，
        # 通用错误码给不出具体指引，只有各家自己知道该逐条比对哪些约束。
        # diagnose.build() 会把它并进「怎么改」。
        self.extra_fix: list = []


# ---------------------------------------------------------------- 响应解析

def extract_task_id(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    scopes = [data]
    inner = data.get("data")
    if isinstance(inner, dict):
        scopes.append(inner)
    for scope in scopes:
        for k in ("id", "task_id", "video_id", "taskId", "taskid"):
            v = scope.get(k)
            if isinstance(v, (str, int)) and str(v):
                return str(v)
    return ""


def extract_status(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    scopes = [data]
    inner = data.get("data")
    if isinstance(inner, dict):
        scopes.append(inner)
    for scope in scopes:
        for k in ("status", "state", "task_status", "job_status"):
            v = scope.get(k)
            if isinstance(v, str) and v:
                return v.lower()
    return ""


# 文本里嵌的链接：<video src='…'> / <img src="…"> / ![alt](…) / 裸 URL
_EMBEDDED_URL_RE = re.compile(
    r"""<(?:video|source|img|audio)[^>]*?\ssrc=["'](https?://[^"']+)["']"""
    r"""|!\[[^\]]*\]\((https?://[^)\s]+)\)"""
    r"""|(https?://[^\s"'<>)\]]+)""",
    re.I | re.X)


# 接口**动作词**。出错时网关常把请求路径原样写进正文（OpenAI 风格的
# `Invalid URL (POST /v1/images/edits)` 最常见）。把它当成结果捞回来，
# 后果不是「多了一项」，是**网关真正说的那句话被顶掉了**：
# 报错变成「结果解析不出来」，而人会去查线路、查余额，查不到任何东西。
_API_TAIL = frozenset((
    "generations", "generation", "edits", "edit", "variations", "completions",
    "embeddings", "uploads", "upload", "files", "videos", "video", "images",
    "image", "models", "chat", "audio", "speech", "transcriptions",
    "tasks", "task", "status", "query",
))
# ⚠ **"content" 绝不能进这张表。** `/v1/videos/{id}/content` 是小裴、阿珂、
# 好漫剧、灵感鸭、巨轮**真正的下载地址**，挡掉它等于把成片本身当成噪音扔了。
# 这张表只放「后面必然还跟着东西才成立」的动作词。


def _is_api_endpoint(u: str) -> bool:
    """这个 URL 是不是「接口地址」而不是「结果文件」。"""
    tail = (u or "").split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1].lower()
    return tail in _API_TAIL


def _collect_urls(node: Any, found: list, key: str = "") -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            _collect_urls(v, found, str(k))
    elif isinstance(node, (list, tuple)):
        for v in node:
            _collect_urls(v, found, key)
    elif isinstance(node, str):
        if node.startswith("http"):
            # 整串就是 URL 也可能是**接口地址**：网关把请求路径塞进
            # `action` / `request_url` / `docs_url` 之类的字段是常事。
            if not _is_api_endpoint(node):
                found.append((key, node))
            return
        # 有的家把结果**嵌在一段文本里**，整串不是 URL：
        #   好漫剧 chat/completions → 一段 html 代码块，里面是 <video src='…mp4'>
        #   香蕉/若干图片接口       → markdown 图片 ![Generated Image](http://…png)
        # 只看 startswith("http") 的话这两种一个都取不到，
        # 而报错会是「没返回结果」—— 指向完全错的方向（会去查线路、查余额）。
        if "http" in node and len(node) < 20000:
            for m in _EMBEDDED_URL_RE.finditer(node):
                u = m.group(1) or m.group(2) or m.group(3)
                # 整串就是 URL 的（上面那条分支）当结果收；**夹在一段话里**的
                # 就要挑一下 —— 报错原文里回显的接口地址正是长这样。
                if not _is_api_endpoint(u):
                    found.append((key, u))


def _dig(node: Any, keys: tuple, depth: int = 4) -> str:
    """在响应里找某几个键的第一个非空字符串值。各家的嵌套层数不一样。"""
    if depth < 0 or not isinstance(node, (dict, list, tuple)):
        return ""
    if isinstance(node, dict):
        for k in keys:
            v = node.get(k)
            if isinstance(v, (str, int)) and str(v).strip():
                return str(v).strip()
        for v in node.values():
            got = _dig(v, keys, depth - 1)
            if got:
                return got
        return ""
    for v in node:
        got = _dig(v, keys, depth - 1)
        if got:
            return got
    return ""


def never_sent(exc: BaseException) -> bool:
    """这个网络错误能不能确定请求根本没到服务商（没连上、域名解析失败、握手失败）。

    读超时、连接中途断开、回了 200 但正文不是 JSON，都说明服务商已经收到了 ——
    对提交来说，这时它可能已经建好任务、开始计费。
    """
    if isinstance(exc, (requests.ConnectTimeout, requests.exceptions.SSLError,
                        requests.exceptions.ProxyError)):
        return True
    if isinstance(exc, requests.ConnectionError) and not isinstance(exc, requests.Timeout):
        text = repr(exc)
        return any(s in text for s in ("NewConnectionError", "NameResolutionError",
                                       "Failed to establish a new connection", "getaddrinfo"))
    return False


def submit_uncertain(why: str, status: int = 0) -> "ApiError":
    return ApiError(f"提交后没有收到服务商的明确回复（{why}）。服务商那边可能已经建好任务、开始计费；"
                    f"为避免重复扣费，这条不自动重发。请先到服务商后台核对：已经生成的取回放到输出位置，"
                    f"确认没有生成再重跑这一段。", status, TASK_FATAL, err_code="submit_uncertain")


def task_failed(data: Any) -> "ApiError":
    """轮询到「任务失败」→ 一个**保留了结构**的异常。

    以前是 `ApiError(f"任务失败: {json.dumps(data)[:500]}")` —— 整个响应
    压成一句话。两个后果：

      · `error.code` 变成字符串里的一段文本，判断就只剩「搜关键词」一条腿。
        实跑因此漏掉了内容审核（章鱼哥回「违反了关于暴力内容的防护限制」，
        表里只有「违规」没有「违反」），自动改写提示词那一层根本没被触发。
      · 日志里是一整坨 JSON，真正那句话被埋在 `"created_at"` 之类中间。

    现在把码单独取出来交给 classify，把服务商自己那句话放到最前面。
    """
    code = _dig(data, ("code", "error_code", "type"))
    msg = _dig(data, ("message", "msg", "error_message", "reason", "detail"))
    # 通用码（upstream_error / unknown 之类）当没有：它什么错都用，
    # 认了反而会把内容问题判成上游故障。这时候只能退回读 message。
    if code.lower() in ("upstream_error", "unknown", "error", "failed", "500"):
        code = ""
    head = msg or json.dumps(data, ensure_ascii=False)[:400]
    tail = f"（服务商错误码：{code}）" if code else ""
    exc = ApiError(f"任务失败：{head}{tail}", 0, err_code=code)
    exc.task_finished = True
    exc.provider_task_failed = True
    return exc


def extract_video_url(data: Any) -> str:
    """响应里哪一个是**成片**。挑不出来就返回空 —— 空的意思是「还没有」。

    ⚠ 这里**不是「随便挑一个 URL」**，那正是以前的写法，而它有一种很贵的
    错法：服务商在任务还没跑完时**把我们传进去的参数原样回显**
    （`inputs: [{"image_url": "…/ref_first_frame.png"}]` 是最常见的形状）。
    于是「响应里有 URL」在还没出片时就已经成立了，而后面一路没人拦得住：
    `save_item` 把那张 png 下载成 `out.mp4`，大小正常，
    `_incomplete_image` 的结尾标记表里只有 .png/.jpg、**.mp4 直接放行** ——
    一张参考图就这么被当成片收下、任务标 ok，到拼接那步才出事。

    所以现在**图片样的一律不算成片**：后缀是图片的、或者键名是 `image_url`
    这种明摆着是图的，直接排除。排除干净之后没剩下的就返回空，
    轮询那边会接着等 —— 这比挑一个错的强得多。
    """
    found: list = []
    _collect_urls(data, found)
    if not found:
        return ""
    # 图片键。**video 结果里出现它一定不是成片**，是回显的参考图。
    picture_keys = ("image_url", "image", "images", "reference_image",
                    "first_frame", "last_frame", "cover", "thumbnail",
                    "preview", "poster", "snapshot")
    ok = []
    for key, url in found:
        base = url.split("?", 1)[0].lower()
        if base.endswith(MEDIA_IMAGE):
            continue                       # 图片后缀：肯定不是成片
        if str(key).lower() in picture_keys:
            continue                       # 键名就写着是图 / 封面 / 预览
        ok.append((key, url))
    if not ok:
        return ""

    def rank(item):
        key, url = item
        base = url.split("?", 1)[0].lower()
        score = 0
        if base.endswith(MEDIA_VIDEO):
            score -= 100
        if key in URL_KEYS:
            score -= 10
        if base.rstrip("/").endswith("/content") and not base.endswith(MEDIA_VIDEO):
            score += 50
        return score

    ok.sort(key=rank)
    return ok[0][1]


def data_array_images(data: Any) -> list:
    """严格按 OpenAI 风格的 `data[]` 取图：**一个元素 = 一张图，链接优先**。

    这一段是从 ComfyUI 那边搬过来的（utils.extract_data_array_images），
    它把这个坑踩明白了：**网关会同时给 `url` 和 `b64_json`**（4K 模型常见）。

    下面那个递归扫描器对这种响应有两个毛病：
      · 同一张图数成两张（两个字符串不相等，去重去不掉）
      · **优先挑了 b64_json —— 而那个是坏的**

    实跑：超模一张 1254×1254 的图，`b64_json` 里只有 4096 个字符
    （解出来 3055 字节），而同一个元素里的 `url` 是好的。
    超模自己的文档也写着「异步任务固定返回 URL 结果」——
    几 MB 的图塞进 JSON 的 base64 字段本来就会被中间层截断。

    所以：响应是规范的 `{"data": [...]}` 就走这条，取不到再退回递归扫描。
    """
    if not isinstance(data, dict):
        return []
    arr = data.get("data")
    if not isinstance(arr, list) or not arr:
        return []
    out: list = []
    for item in arr:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("image_url")
        if isinstance(url, dict):
            url = url.get("url")
        if isinstance(url, str) and url.strip() and not _is_api_endpoint(url):
            out.append(url.strip())          # 链接优先：不会被截断
            continue
        b64 = item.get("b64_json") or item.get("image_b64")
        if isinstance(b64, str) and b64.strip():
            out.append(b64 if b64.startswith("data:")
                       else "data:image/png;base64," + b64)
    return out


def extract_image_items(data: Any) -> list:
    """http URL / data URI / b64_json。

    先走 `data[]` 严格解析（一个元素一张、链接优先），拿不到才递归乱扫。
    顺序反过来的话，同时给 url 和 b64 的响应会挑中那个会被截断的 b64 ——
    实跑因此存下了一批残图，而报错出现在下一步拿它当参考图的时候。
    """
    strict = data_array_images(data)
    if strict:
        return strict
    # **链接和内嵌数据分开收，最后链接排前面。**
    #
    # 以前是一个列表按遇到的顺序收，而 dict 分支先看 `b64_json`、再往下走 ——
    # 于是同一份响应里既有 url 又有 b64 时，取到的是 b64。
    # 上面那条严格路径是链接优先的，但它只在 `{"data":[...]}` 这种规范结构上生效；
    # 轮询 `/v1/images/{id}` 回来的结构一旦不是那个形状就落到这里。
    #
    # 代价是实打实的：超模那条线路把 b64 字段**截在 4096 字符**
    # （解出来 3055 字节的残 PNG），而同一份响应里的 url 是好的。
    # 取错一次 = 一张残图 + 两次重试 = 一张资产出三次图。
    urls: list = []
    embeds: list = []

    def walk(node: Any):
        if isinstance(node, dict):
            b64 = node.get("b64_json")
            if isinstance(b64, str) and b64:
                embeds.append("data:image/png;base64," + b64)
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            if node.startswith("data:image"):
                embeds.append(node)
            elif node.startswith("http"):
                base = node.split("?", 1)[0].lower()
                # `"image" in base` 这一条**顺手把接口地址也收了**：
                # https://host/v1/images/edits 里就有 image。收进来的后果不是
                # 多一项，是 _pick_images 看见非空 items 就**不去轮询了**，
                # 而报错变成「解析不出图」，网关原话再也没人看见。
                if (base.endswith(MEDIA_IMAGE) or "image" in base)                         and not _is_api_endpoint(node):
                    urls.append(node)

    walk(data)
    items = urls + embeds
    if items:
        seen, out = set(), []
        for it in items:
            if it not in seen:
                seen.add(it)
                out.append(it)
        return out
    found: list = []
    _collect_urls(data, found)
    return [u for _, u in found]


# ---------------------------------------------------------------- 参考图

# **默认不动原图。** 用户原话（2026-08-31）：「我就不需要你做这个压缩，
# PNG 改 JPG 除非是服务商要求，否则都不要对原图进行修改才对」。
#
# 原来是无条件缩到最长边 1024 再转 JPEG q80 —— 而那个 1024 全项目没有一处
# 设置过，是 produce 里的硬编码兜底。代价实测过：1024x1536 的故事板发出去
# 是 682x1024，只剩 44% 的像素；2048x2048 的资产只剩 25%。参考图是喂给模型
# 的身份和构图来源，缩掉一半而没人选过这件事。
#
# 2026-10-09：用户要求所有上传参考图兼容 10 MB 限制。默认预算 9.5 MB，
# 以下仍原样发送；超过只生成上传副本。声明的尺寸/格式限制继续生效，改动写日志。
REF_KEEP = 0                    # max_side 传这个 = 不缩


def _alpha(path: str) -> bool:
    """这张图有没有透明通道 —— 只读文件头，不解码。"""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
    except Exception:                                       # noqa: BLE001
        return False


def encode_ref(path: str, max_side: int = REF_KEEP, quality: int = 80,
               fmt: str = "", max_bytes: int = 9_500_000) -> tuple:
    """本地图片 → `(字节, mime, 扩展名, 说明)`。

    未指定尺寸/格式且低于 max_bytes 时原样发送；超限只重编码上传副本。
    原素材永远不覆盖。默认预算 9.5 MB，兼容常见的 10 MB 文件上限。

    **说明不是可选的。** 改过就要在日志里看得见 —— 出来的脸不像时，
    第一件要排除的就是「是不是我们把参考图改小了」，而那件事以前只有
    读代码才知道。
    """
    ext = (os.path.splitext(path)[1] or ".png").lower()
    fmt = (fmt or "").strip().upper()
    if fmt in ("JPG", "JPEG"):
        fmt = "JPEG"

    if max_side <= 0 and not fmt:
        with open(path, "rb") as f:
            raw = f.read()
        from .reference_images import limit_bytes
        bounded, bounded_mime, bounded_ext, bounded_note = limit_bytes(raw, max_bytes)
        if bounded_note:
            return bounded, bounded_mime, bounded_ext, bounded_note
        mime = mimetypes.guess_type(path)[0] or "image/png"
        note = "原样（未改）"
        if _alpha(path):
            # 以前一律 convert("RGB") 会把透明压平成黑或白。现在不动它 ——
            # 但各家对 alpha 的处理不一样，出图不对时要能想到这一条。
            note += "；带透明通道，各家处理不一样"
        return raw, mime, ext, note

    try:
        from PIL import Image
    except ImportError:
        # 这一家声明了要改，而我们改不了。**不能装作改过了** ——
        # 原样发过去撞上限时报的是别的错，方向完全跑偏。
        raise ApiError('缺少 Pillow，无法按服务商要求准备参考图；请使用完整安装包', kind=TASK_FATAL)

    img = Image.open(path)
    w, h = img.size
    bits = []
    if max_side > 0 and max(w, h) > max_side:
        scale = max_side / float(max(w, h))
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        img = img.resize((nw, nh), Image.LANCZOS)
        bits.append(f"{w}x{h}→{nw}x{nh}（这一家最长边限 {max_side}，"
                    f"剩 {nw * nh / float(w * h) * 100:.0f}% 像素）")
    out_fmt = fmt or ((img.format or "PNG").upper())
    if out_fmt == "JPEG" and img.mode != "RGB":
        img = img.convert("RGB")                # JPEG 没有 alpha
    if fmt and fmt != (Image.open(path).format or "").upper():
        bits.append(f"转成 {fmt}（这一家要求的）")
    buf = io.BytesIO()
    img.save(buf, format=out_fmt,
             **({"quality": quality} if out_fmt == "JPEG" else {}))
    ext2 = ".jpg" if out_fmt == "JPEG" else ("." + out_fmt.lower())
    mime2 = "image/jpeg" if out_fmt == "JPEG" else f"image/{out_fmt.lower()}"
    from .reference_images import limit_bytes
    bounded, bounded_mime, bounded_ext, bounded_note = limit_bytes(buf.getvalue(), max_bytes, required_format=fmt)
    return bounded, bounded_mime or mime2, bounded_ext or ext2, (bounded_note or "；".join(bits) or f"{w}x{h} 原尺寸")


def file_to_data_uri(path: str, max_side: int = REF_KEEP, quality: int = 80,
                     fmt: str = "") -> str:
    """本地图片 → base64 data URI。默认不改原图，见 `encode_ref`。"""
    raw, mime, _ext, _note = encode_ref(path, max_side, quality, fmt)
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def resolve_ref(ref: str, project_root: str, max_side: int = REF_KEEP,
                fmt: str = "") -> str:
    """参考图引用 → 可入 images[] 的值。http/data 原样；本地路径转 data URI。"""
    ref = (ref or "").strip()
    if not ref:
        return ""
    if ref.startswith("http") or ref.startswith("data:"):
        return ref
    path = ref if os.path.isabs(ref) else os.path.join(project_root, ref)
    if not os.path.isfile(path):
        raise ApiError(f"参考图文件不存在: {path}")
    return file_to_data_uri(path, max_side=max_side, fmt=fmt)


# ---------------------------------------------------------------- HTTP

# 小于这个字节数的图/片一定不是真结果。最小的合法 PNG 也有 67 字节，
# 而服务商出问题时给的是 0 字节，或者几十字节的一段 JSON/HTML 错误页。
MIN_BYTES = 512


_B64_ALPHABET = re.compile(r"[^A-Za-z0-9+/]")


def _b64_bytes(payload: str, whole: str) -> bytes:
    """base64 文本 → 字节。宽容地解，解不动就说清楚收到的是什么。

    `base64.b64decode` 只会抛一句 `Incorrect padding`，**不告诉你它在解什么**。
    实跑撞到过：超模一批资产全挂在这一句上，每张还自动重试两次
    （每次要重出一张图、两分半），八张图跑了半小时，
    最后既没有图，也没有一条能拿去问服务商的信息。

    宽容处理三种常见的不合规写法，都是真出现过的：
      · 前后有空白 / 换行（有些家会把 b64 折行）
      · URL-safe 字母表（`-_` 而不是 `+/`）
      · 少了结尾的 `=` 填充（不少网关会把它剥掉）

    嵌套的 `data:` 前缀单独说：有的家在 `b64_json` 里塞的是一整个 data URI，
    我们又给它拼了一次前缀，结果是 `data:…,data:…,iVBOR…`。
    """
    s = "".join((payload or "").split())            # 去掉所有空白和换行
    while s.startswith("data:"):                    # 嵌套前缀：再剥一层
        s = s.split(",", 1)[1] if "," in s else ""
    s = s.replace("-", "+").replace("_", "/")       # URL-safe → 标准字母表
    # **先把字母表外的字符全去掉，再补填充。** 顺序反了没用：
    # b64decode 自己会丢掉这些字符，于是我们按原长度补的 `=` 补错位置，
    # 还是 `Incorrect padding`。
    s = _B64_ALPHABET.sub("", s).rstrip("=")
    s += "=" * (-len(s) % 4)
    err = ""
    raw = b""
    try:
        raw = base64.b64decode(s)
    except Exception as exc:                        # noqa: BLE001
        err = str(exc)
    if err or not raw:
        # 解出空字节和解不动是同一件事：那串东西压根不是图片数据。
        # 不能让它落到后面的大小检查上 —— 那条会说「只有 0 字节」，
        # 把人引去找服务商要文件，而真正的问题是这个字段的格式不对。
        looks = ("像一个链接" if whole[:200].lstrip().startswith("http")
                 else "像 JSON" if whole.lstrip()[:1] in "{[" else "不像链接也不像 JSON")
        raise ApiError(
            f"服务商说做好了，但返回的内容解不成图片（{err or '解出来是空的'}）。"
            f"这不是网络问题，重试多少次都是同一个结果 —— "
            f"是这一家返回的格式和我们认的对不上。\n"
            f"收到 {len(whole)} 字符，{looks}。开头 120 字：{whole[:120]!r}\n"
            f"把上面这两行发给服务商，问「你们这个字段返回的到底是什么格式」。",
            status=0, kind=TASK_FATAL)
    return raw


# 图片格式的收尾标记。文件没有它 = 只下/解了一半。
#
# **大小检查拦不住这一类。** 一张 1254×1254 的 PNG 截掉后半段仍然有几百 KB，
# 512 字节那道线轻松通过，于是被当成做好了、注册成 generated、
# 后面的状态资产和故事板拿它当参考 —— 到那时候才炸：
#
#     UNKNOWN: Truncated File Read
#
# 而报错出现在**用它的那一步**，不是产生它的那一步。实跑里 19 个资产 +
# 40 张故事板都挂在这句话上，真正坏掉的却是上一轮存下来的那几张图。
_END_MARK = {".png": b"IEND" + bytes([0xAE, 0x42, 0x60, 0x82]),
             ".jpg": bytes([0xFF, 0xD9]),
             ".jpeg": bytes([0xFF, 0xD9])}


# 文件头认种类。**这是最后一道，也是唯一不依赖任何一方说法的那道** ——
# 前面每一道判断都建立在「服务商说的」之上（状态词、Content-Length、
# 它自己声明的宽高），只有这一道看的是**真的拿到了什么**。
#
# 要防的那件事很具体：一张图被当成片存成 `out.mp4`。大小正常、
# 结尾标记那道对 .mp4 不适用（表里只有 .png/.jpg），于是一路放行到拼接才炸。
_ISO_BOXES = (b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide")
_PNG_HEAD = bytes((0x89, 0x50, 0x4E, 0x47))
_JPG_HEAD = bytes((0xFF, 0xD8, 0xFF))
_EBML_HEAD = bytes((0x1A, 0x45, 0xDF, 0xA3))


def _looks_like(head: bytes, ext: str) -> bool:
    """文件头像不像这个扩展名该有的样子。认不出的扩展名一律放行。"""
    if ext in (".mp4", ".mov", ".m4v"):
        # ISO BMFF：第一个 box 的类型在 4..8。老文件也可能直接以 moov/mdat 开头，
        # 所以在前 16 字节里找，别只认偏移 4。
        return any(b in head[:16] for b in _ISO_BOXES)
    if ext in (".webm", ".mkv"):
        return head.startswith(_EBML_HEAD)
    if ext == ".avi":
        return head.startswith(b"RIFF") and b"AVI " in head[:16]
    if ext == ".png":
        return head.startswith(_PNG_HEAD)
    if ext in (".jpg", ".jpeg"):
        return head.startswith(_JPG_HEAD)
    if ext == ".webp":
        return head.startswith(b"RIFF") and b"WEBP" in head[:16]
    if ext == ".gif":
        return head.startswith(b"GIF8")
    return True


def _wrong_kind(dest: str, *, extension: Optional[str] = None) -> str:
    """存下来的东西和扩展名对不上 → 一句人话；对得上返回空。"""
    ext = extension if extension is not None else os.path.splitext(dest)[1].lower()
    try:
        with open(dest, "rb") as f:
            head = f.read(64)
    except OSError:
        return ""
    if _looks_like(head, ext):
        return ""
    # 认出常见的几种「这根本不是媒体文件」，直接说是什么，别让人去猜
    if head.startswith(_PNG_HEAD) or head.startswith(_JPG_HEAD):
        what = "一张图片"
    elif head[:1] in (b"{", b"["):
        what = "一段 JSON（多半是服务商的错误响应）"
    elif head[:1] == b"<":
        what = "一个 HTML 页面（多半是登录页或错误页）"
    else:
        what = f"认不出的内容（开头是 {head[:16]!r}）"
    return (f"存下来的东西不是 {ext} —— 实际是{what}。"
            f"大小和下载过程都正常，所以前面每一道都放行了；"
            f"**这一道看的是文件本身**。"
            f"收下的话它会被当成做好了：视频那一格照样标 ok，"
            f"到拼接成片那一步才炸，而那时已经隔了几十条任务。")


def _incomplete_image(dest: str, *, extension: Optional[str] = None) -> str:
    """这个图片文件是不是只有一半。是的话返回一句人话，否则空字符串。

    这里只快速查收尾标记；中段损坏由 _check_saved 随后的完整解码拦住。
    没有固定收尾标记的格式交给后续检查。
    """
    ext = extension if extension is not None else os.path.splitext(dest)[1].lower()
    mark = _END_MARK.get(ext)
    if not mark:
        return ""
    try:
        with open(dest, "rb") as f:
            f.seek(max(0, os.path.getsize(dest) - 64))
            tail = f.read()
    except OSError:
        return ""
    if mark in tail:
        return ""
    return (f"这张图没有结尾标记，是个残图（只解出/下载了一半）。"
            f"大小看着正常（{os.path.getsize(dest)} 字节），但打不开 —— "
            f"留着的话，后面拿它当参考图的那几步会报 "
            f"「Truncated File Read」，而那时候看不出是这一张的问题。")


def _field_cap(src: str) -> int:
    """内嵌数据的长度看着像个「字段上限」吗。是就返回那个长度，否则 0。

    判据是**整数**：1024 的整数倍，或者 2 的整数次方（4096、8192、65536…）。
    随机截断落在这种数上的概率极低，而字段上限恰恰都是这种数。

    分清这两件事的意义是钱：随机截断重试一次经常就好，字段上限重试三次
    是三次都拿同一张残图 —— 而出图是按次计费的。
    """
    m = re.search(r"（(\d+) 字符", src or "")
    if not m:
        return 0
    n = int(m.group(1))
    if n < 1024:
        return 0
    if n % 1024 == 0 or (n & (n - 1)) == 0:
        return n
    return 0


@contextmanager
def _atomic_output(dest: str):
    """每个写入独占临时文件；调用方校验通过后才原子发布到最终路径。"""
    folder = os.path.dirname(os.path.abspath(dest))
    os.makedirs(folder, exist_ok=True)
    # 不能共用 dest + '.part'：同名任务重叠时会互相截断、混写和删除。
    fd, part = tempfile.mkstemp(prefix=".result-", suffix=".part", dir=folder)
    os.close(fd)
    try:
        yield part
        os.replace(part, dest)
    finally:
        if os.path.exists(part):
            os.remove(part)


def _normalize_result_image(path: str, dest: str, log) -> None:
    """Convert a complete image to the contract's file format; never rename raw JPEG to PNG."""
    target = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.webp': 'WEBP'}.get(os.path.splitext(dest)[1].lower())
    if not target:
        return
    from PIL import Image, UnidentifiedImageError
    try:
        opened = Image.open(path)
    except (UnidentifiedImageError, OSError, ValueError):
        return  # 未能识别的文件交给原有类型/残图检查，保留已有错误诊断。
    try:
        with opened as source:
            actual = source.format
            if actual == target or actual not in ('PNG', 'JPEG', 'WEBP'):
                return
            source.verify()
        with Image.open(path) as source:
            source.load()
            if getattr(source, 'n_frames', 1) > 1:
                raise ValueError('不自动压平多帧图片')
            pixels = source.copy()
        if target in ('PNG', 'WEBP') and pixels.mode == 'CMYK':
            pixels = pixels.convert('RGB')
        if target == 'JPEG' and pixels.mode not in ('RGB', 'L'):
            if 'A' in pixels.getbands():
                bg = Image.new('RGB', pixels.size, 'white')
                bg.paste(pixels, mask=pixels.getchannel('A'))
                pixels = bg
            else:
                pixels = pixels.convert('RGB')
        pixels.save(path, format=target, **({'quality': 95} if target == 'JPEG' else {}))
        log(f'服务商返回 {actual}，已转为目标 {target}，像素尺寸保持 {pixels.width}×{pixels.height}')
    except UnidentifiedImageError:
        return  # 原有文件类型检查会报告 HTML/JSON/无效内容。
    except Exception as exc:
        raise ApiError(f'结果图片格式转换或完整性检查失败：{exc}', kind=RETRYABLE, err_code='result_invalid') from exc


def _check_saved(dest: str, src: str, *, extension: Optional[str] = None) -> None:
    """落盘之后验一遍。**0 字节的文件是最坏的一种失败。**

    它不报错：文件建出来了，注册表记成 generated，比例检查量不出尺寸
    所以也不吭声，而下一次跑 `os.path.isfile()` 是真 —— 于是这一条
    **永远被跳过**，成片里那一段永远缺着，而进度显示 100%。

    服务商侧真实发生过：任务查询说成功、给了下载链接，链接返回 200 但
    body 是空的。不验的话我们就把这个空文件当成交付物收下了。
    """
    try:
        n = os.path.getsize(dest)
    except OSError as exc:
        raise ApiError(f"结果文件没能落盘：{dest}（{exc}）") from exc
    if n >= MIN_BYTES:
        ext = extension if extension is not None else os.path.splitext(dest)[1].lower()
        wrong = _wrong_kind(dest, extension=ext)
        if wrong:
            os.remove(dest)     # 必须删：留着下次 isfile 为真，这一条永远被跳过
            raise ApiError(wrong + chr(10) + f"来源：{src}", 0, RETRYABLE)
        bad = _incomplete_image(dest, extension=ext)
        if not bad:
            if ext in MEDIA_IMAGE:
                from PIL import Image
                try:
                    # verify 检查 PNG 块校验和；load 检查压缩数据和全部像素。
                    # 头尾和总字节数都正常的混写图片也必须拒收。
                    with Image.open(dest) as im:
                        im.verify()
                    with Image.open(dest) as im:
                        for frame in range(getattr(im, "n_frames", 1)):
                            im.seek(frame)
                            im.load()
                except Exception as exc:
                    os.remove(dest)
                    raise ApiError(
                        f"结果图片完整性检查失败（{n} 字节）：{exc}。"
                        f"没有保存为完成结果。\n来源：{src}",
                        kind=RETRYABLE, err_code="result_invalid") from exc
            return
        os.remove(dest)     # 同样必须删：留着下次会被当成「已经做过了」跳过
        # **内嵌数据被截在一个整数长度上 = 这条线路的字段上限，重试没有意义。**
        #
        # 实遇超模：`响应内嵌数据（4096 字符…）` —— 4096 是 2 的 12 次方，
        # 不是巧合。减去 `data:image/png;base64,` 那 22 个前缀 = 4074 字符，
        # 4074×3/4 = 3055 字节，和量出来的残图一模一样。
        # 每次都截在同一处，所以那两次重试是**确定性地白花钱**：
        # 一张资产出了三次图，三次都是同一张残图。
        cap = _field_cap(src)
        if cap:
            raise ApiError(
                f"{bad}\n来源：{src}\n"
                f"**{cap} 是个整数上限，不是随机截断** —— 这条线路把内嵌图片"
                f"字段截在这里，每次都一样，所以重试不会有不同结果（已经不再重试）。\n"
                f"两条出路：让这家改成返回图片**链接**（我们本来就发了 "
                f"response_format=url 和 async=true，是它没给）；"
                f"或者把这类活排给别家 —— 图越大越容易撞这个上限。\n"
                f"上面那行日志里有这一次用的服务商 / 模型 / **Key 分组** ——"
                f"问服务商时把它一起发过去，有几家的上限是**按分组**不一样的。",
                status=0, kind=TASK_FATAL)
        raise ApiError(f"{bad}\n来源：{src}", 0, RETRYABLE)
    head = ""
    if n:
        try:
            with open(dest, "rb") as f:
                head = f.read(200).decode("utf-8", "replace").strip()
        except OSError:
            pass
    os.remove(dest)         # **必须删掉**，留着下次会被当成「已经做过了」跳过
    # 链接和内嵌数据要给不同的下一步：说「拿链接去问服务商」而实际上根本没有
    # 链接（内容是响应里内嵌的），人会去翻一个不存在的东西。
    tail = (f"这种情况要拿「来源」那个链接去问服务商：任务标成成功了，"
            f"但下载地址返回的是空的。" if src.startswith("http") else
            f"内容是响应里直接带的、不是下载来的 —— 把上面的「来源」发给服务商，"
            f"问「这个字段返回的到底是什么」。")
    raise ApiError(
        f"服务商说做好了，但取回来的文件只有 {n} 字节（正常的图至少几十 KB）—— "
        f"这不是一张图，已经删掉，不会被当成做好了。\n"
        f"来源：{src}\n"
        + (f"文件内容：{head!r}\n" if head else "文件是空的。\n")
        + tail)


def _retry_after(resp) -> float:
    """读 Retry-After 头（秒或 HTTP 日期，只处理秒）。"""
    v = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
    try:
        return max(0.0, float(v))
    except (TypeError, ValueError):
        return 0.0


def _body_error(data: Any) -> str:
    """HTTP 200 但 body 里藏错误的情况：提取错误文案，没有则返回空串。"""
    if not isinstance(data, dict):
        return ""
    err = data.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or "")
    if isinstance(err, str) and err:
        return err
    if data.get("code") not in (None, 0, "0", "success", "ok") and data.get("message"):
        return str(data.get("message"))
    return ""


class HttpSession:
    """带鉴权/分级重试的轻量会话。"""

    def __init__(self, api_key: str, base_url: str, timeout: int = 600, proxy: str = ""):
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "").strip().rstrip("/")
        self.timeout = timeout
        self.proxy = (proxy or "").strip()
        self.result_source_bytes = {}
        # 鉴权头的形状：绝大多数网关是 Bearer，但「智」（zhi168）用 X-API-Key。
        # 服务商在 __init__ 里改这个属性就行，默认不动。
        self.auth_style = "bearer"

    def _download_headers(self) -> dict:
        """**取成品用的头，和调 JSON 接口的头不是同一份。**

        `_headers()` 里有 `Accept: application/json` 和 `Content-Type: application/json`。
        拿它去 GET 一个视频/图片是自相矛盾的：一边说「我只收 JSON」，
        一边等着对方回二进制；而 GET 带 Content-Type 本身就不合常理，
        网关和 WAF 有拒的。

        实遇 2026-09-07（云会画 ai.yunhuiart.cn）：`/v1/videos/{id}/content`
        用 JSON 那份头去请求，回 502
        `{"code":"artifact_request_rejected","message":"Artifact redirect was rejected"}`。
        而它文档里的官方示例只带一个 Authorization —— 那份能用。

        鉴权照旧带（很多家的 /content 是要鉴权的代理，比如小霸龙）。
        """
        auth = ({"X-API-Key": self.api_key} if self.auth_style == "x-api-key"
                else {"Authorization": f"Bearer {self.api_key}"})
        return {**auth, "Accept": "*/*",
                "User-Agent": "ScriptToVideoRunner/2.0"}

    def _headers(self, multipart: bool = False) -> dict:
        auth = ({"X-API-Key": self.api_key} if self.auth_style == "x-api-key"
                else {"Authorization": f"Bearer {self.api_key}"})
        h = {
            **auth,
            "Accept": "application/json",
            "User-Agent": "ScriptToVideoRunner/2.0",
        }
        # 传文件时不能自己写 Content-Type：requests 要在里面填 multipart 的 boundary，
        # 手写死 application/json 会让服务端解不出 form 字段。
        if not multipart:
            h["Content-Type"] = "application/json"
        return h

    def _proxies(self) -> Optional[dict]:
        if self.proxy.lower() in ("direct", "none", "off", "关闭", "直连"):
            # requests 在 Windows 上即使 proxies=None 也会读取系统代理。给空字符串
            # 才是真正直连；有些国内网关经系统代理会在 TLS 握手时直接 EOF。
            return {"http": "", "https": ""}
        return {"http": self.proxy, "https": self.proxy} if self.proxy else None

    def request(self, method: str, path: str, *, json_body: Any = None, params: Any = None,
                files: Any = None, raw_body: Any = None, headers: Optional[dict] = None,
                retries: int = 3, timeout: Optional[int] = None,
                submit: Optional[bool] = None) -> Any:
        """`submit` 默认按上下文判断：生产一个输出、还没拿到任务号时的 POST 就是提交。
        提交之前的上传之类要显式传 `submit=False`，否则上传超时也会被当成提交不确定。
        """
        url = path if path.startswith("http") else self.base_url + path
        last: Optional[Exception] = None
        if submit is None:
            submit = (method.upper() == "POST" and submitted.submitting()
                      and 'upload' not in path.lower()
                      and path.rstrip('/') != '/api/multimodal/get_result')
        from . import managed_usage, distribution
        tracked = managed_usage.active() and submit
        if tracked:
            retries = 1
            managed_usage.begin_request()
        for attempt in range(max(1, retries)):
            try:
                request_headers = self._headers(multipart=bool(files))
                if headers:
                    request_headers.update(headers)
                resp = requests.request(
                    method, url, headers=request_headers,
                    json=json_body, data=raw_body, params=params, files=files,
                    timeout=timeout or self.timeout, proxies=self._proxies(),
                    allow_redirects=not (managed_usage.active() or
                        (distribution.ENABLED and getattr(distribution, 'MANAGED', False))),
                )
                if resp.status_code >= 400:
                    if tracked:
                        managed_usage.failed_request(resp.status_code)
                    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "latin-1"):
                        resp.encoding = "utf-8"
                    body = resp.text[:400]
                    kind = classify(resp.status_code, body)
                    # 账户级问题（余额/密钥）立刻抛，不浪费重试次数
                    if kind == BATCH_FATAL:
                        raise ApiError(f"HTTP {resp.status_code}: {body}", resp.status_code, kind)
                    if kind == RETRYABLE and submit and resp.status_code != 429:
                        raise submit_uncertain(f"HTTP {resp.status_code}：{body[:200]}", resp.status_code)
                    if kind == RETRYABLE and attempt < retries - 1:
                        wait = _retry_after(resp) or (2 ** attempt)
                        time.sleep(min(wait, 30))
                        continue
                    raise ApiError(f"HTTP {resp.status_code}: {body}", resp.status_code, kind,
                                   _retry_after(resp))
                data = resp.json() if resp.content else {}
                # 有的中转站 HTTP 200 但 body 里带业务错误（余额不足最常见）
                err = _body_error(data)
                if err:
                    kind = classify(200, err)
                    if tracked:
                        managed_usage.note('failed' if kind in (TASK_FATAL, BATCH_FATAL) else 'unknown')
                    if kind == BATCH_FATAL:
                        raise ApiError(f"接口返回错误: {err[:400]}", 200, kind)
                if not err:
                    managed_usage.response('POST' if tracked else 'GET', data)
                return data
            except ApiError:
                raise
            except requests.RequestException as exc:
                if tracked:
                    managed_usage.failed_request()
                last = exc
                if submit and not never_sent(exc):
                    raise submit_uncertain(f"{type(exc).__name__}：{exc}") from exc
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise ApiError(f"网络错误: {exc}", 0, RETRYABLE) from exc
            except ValueError:
                if tracked:
                    managed_usage.failed_request()
                raise
        raise ApiError(f"网络错误: {last}", 0, RETRYABLE)

    def poll(self, path_tpl: str, task_id: str, *, picker, interval: int = 8,
             timeout: int = 1800, content_path_tpl: str = "", log=print, cancel=None) -> Any:
        """轮询直到完成。picker(data) 提取结果；cancel() 返回 True 时中止。"""
        submitted.remember(task_id, path=path_tpl, content=content_path_tpl,
                           picker=getattr(picker, "__name__", ""))
        start, last_status = time.time(), ""
        # 连续同样失败的计数。**查询一直报错时别拖满超时** ——
        # 端点或参数不对是每次都一样的错，等 30 分钟不会等出不同结果，
        # 而这段时间里那条任务在服务商那边可能早就跑完了。
        # （Gate 那家单独写轮询时就踩过这一课，这里补给所有走通用器的家。）
        fails, last_fail = 0, ""
        while time.time() - start < timeout:
            if cancel and cancel():
                raise ApiError("用户已取消")
            try:
                data = self.request("GET", path_tpl.format(id=task_id), retries=1, timeout=60)
                fails, last_fail = 0, ""
            except ApiError as exc:
                fails += 1
                if str(exc) == last_fail and fails >= 5:
                    stop = ApiError(
                        f"查询任务连续 {fails} 次同样失败，不再等下去：{exc}"
                        f"（任务 {task_id} 可能在服务商那边已经跑完了 —— "
                        f"这类错每次都一样，多半是查询端点或参数不对，"
                        f"等满 {timeout} 秒也不会变）",
                        status=0, kind=TASK_FATAL)
                    # 连续 404 = 服务商那边没有这条任务，续查不会再有结果。
                    stop.task_finished = getattr(exc, "status", 0) == 404
                    raise stop from exc
                last_fail = str(exc)
                log(f"轮询错误(继续，第 {fails} 次): {exc}")
                time.sleep(interval)
                continue
            status = extract_status(data)
            got = picker(data)
            if status and status != last_status:
                log(f"状态: {status}")
                last_status = status
            if status in FAIL_STATES:
                raise task_failed(data)
            done = status in DONE_STATES
            # 认不出的状态词**不算「还在跑」**，见 RUNNING_STATES 的注释。
            unknown = bool(status) and not done and status not in RUNNING_STATES
            if got and unknown:
                log(f"⚠️ 状态词 `{status}` 我们不认识 —— 但结果已经拿到了，"
                    f"按完成收下。（认不出就接着等的话，会一直等到超时，"
                    f"而任务其实早就好了。把这个词补进 apiutil 的 "
                    f"DONE_STATES / RUNNING_STATES，下次就不用靠这一支兜底。）")
            if got and (not status or done or unknown):
                return got
            if done and content_path_tpl:
                got = picker(self.request("GET", content_path_tpl.format(id=task_id),
                                          retries=1, timeout=120))
                if got:
                    return got
                raise ApiError(f"任务完成但未取到结果: {task_id}")
            if done:
                raise ApiError(f"任务完成但未取到结果: {task_id}")
            time.sleep(interval)
        # **把最后看到的状态词写进报错。** 只说「超时」的话，
        # 「服务商那边明明显示完成了」这种情况完全没有线索可查 ——
        # 而状态词就是线索：它要么是个我们没收录的完成词，
        # 要么说明查的根本不是同一条任务。
        raise ApiError(
            f"任务超时({timeout}s): {task_id}"
            + (f"，最后一次查到的状态是 `{last_status}`" if last_status
               else "，整个过程中一个状态字段都没读到")
            + (f"（这个词不在已知的完成/失败/进行中里 —— "
               f"服务商那边如果显示已完成，多半就是它没被认出来）"
               if last_status and last_status not in DONE_STATES
               and last_status not in FAIL_STATES
               and last_status not in RUNNING_STATES else ""),
            status=0, kind=RETRYABLE)

    def save_item(self, item: str, dest: str, retries: int = 3, *, log=None) -> str:
        """结果（http / data URI / 裸base64）暂存、校验，再原子发布。

        **http 的取空了要重取。** 不少家的任务状态先翻成「成功」，
        文件才慢半拍写进他们的对象存储 —— 我们紧接着就去下载，
        于是拿到一个 200 + 空 body。等两秒再取一次基本就有了。
        取不到才报错，那时候才是真的要去问服务商。
        （data URI 和 base64 是响应里带的，重取没有意义，不重试。）
        """
        # completed 只结束生成，后面还有下载。下载断了只重取这个链接，
        # 不能抛给外层重新提交生成（任务已完成，也已经计费）。
        log = log or (lambda _: None)
        remote = item.startswith("http")
        attempts = max(1, retries) if remote else 1
        last = None
        for attempt in range(attempts):
            try:
                if remote:
                    log(f"已取得结果地址，开始下载（第 {attempt + 1}/{attempts} 次）")
                result = self._save_once(item, dest, log=log)
                log("结果已保存并通过文件检查")
                return result
            except ApiError as exc:
                if exc.kind == TASK_FATAL or ("字节" not in str(exc)
                                              and exc.err_code != "result_invalid"):
                    raise                       # 不是空文件，是别的错，别在这儿吞
                last = exc
            except requests.RequestException as exc:
                last = exc
                # 鉴权回退已经试过。永久 HTTP 错误不必再请求同一个地址。
                response = getattr(exc, "response", None)
                status = getattr(response, "status_code", 0)
                if 400 <= status < 500 and status not in (404, 408, 425, 429):
                    break
            if attempt < attempts - 1:
                log(f"下载未成功，将重新下载同一结果，不重新生成：{str(last)[:180]}")
                time.sleep(2 * (attempt + 1))
        if (isinstance(last, requests.RequestException)
                or isinstance(last, ApiError) and last.err_code == "result_invalid"):
            exc = ApiError(
                f"结果下载失败：已取得服务商结果，但取回或文件检查未能通过（尝试 {attempt + 1} 次）。"
                f"已停止自动重试生成，避免重复计费。最后的下载错误：{last}",
                kind=TASK_FATAL, err_code="result_download_failed")
            exc.extra_fix = ([f"已返回的结果地址：{item}"] if remote else
                             ["服务商返回的是内嵌图片，请从该任务取回完整原图。"]) + [f"应保存到：{dest}"]
            raise exc from last
        raise last                              # type: ignore[misc]

    def _save_once(self, item: str, dest: str, *, log=None) -> str:
        if not hasattr(self, 'result_source_bytes'):
            self.result_source_bytes = {}  # 兼容旧外挂创建/恢复的 session。
        log = log or (lambda _: None)
        os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
        # 内嵌数据也要能追溯：只写「内嵌数据」的话，大小检查报出来的那条
        # 完全看不出收到的是什么，跟服务商对不上话。
        src = f"响应内嵌数据（{len(item)} 字符，开头 {item[:80]!r}）"
        if item.startswith("data:"):
            # **先解码，解成功了再开文件。** 顺序反过来的话，`open(dest,"wb")`
            # 已经把文件建成 0 字节，b64decode 再抛异常 —— 于是磁盘上留下一个
            # 0KB 的「图」。实跑撞过：超模一批资产全是 0KB，报错只有
            # 一句 `Incorrect padding`，看不出是我们自己留下的空壳。
            raw = _b64_bytes(item.split(",", 1)[1], item)
            with _atomic_output(dest) as part:
                with open(part, "wb") as f:
                    f.write(raw)
                self.result_source_bytes[os.path.abspath(dest)] = os.path.getsize(part)
                _normalize_result_image(part, dest, log)
                _check_saved(part, src, extension=os.path.splitext(dest)[1].lower())
        elif item.startswith("http"):
            src = item
            # 下载用 `_download_headers()`，**不是** `_headers()` ——
            # 后者带 JSON 的 Accept/Content-Type，对二进制下载是自相矛盾的，
            # 有网关会直接拒（见 _download_headers 的注释）。
            headers = self._download_headers() if item.startswith(self.base_url) else None
            # 生成可以等很久，下载连接/停传不能沿用那 900 秒。
            # read timeout 是「多久收不到数据」，不是整个大文件必须 30 秒下完。
            timeout = (min(self.timeout, 15), min(self.timeout, 30))
            r = requests.get(item, headers=headers, timeout=timeout,
                             proxies=self._proxies(), stream=True)
            if r.status_code >= 400 and headers is None:
                r.close()
                r = requests.get(item, headers=self._download_headers(),
                                 timeout=timeout,
                                 proxies=self._proxies(), stream=True)
            elif r.status_code >= 400 and headers is not None:
                # 反方向也试一次：**带了鉴权反而被拒**。
                #
                # 预签名地址的 query 串里就是凭证，有些存储会拿 Authorization
                # 头去验然后拒掉；而跳转目标同主机时 requests 不替我们摘掉这个头
                # （只有跨主机才摘）。
                #
                # 云会画那次 502 的主因更可能是 JSON 头（它文档的官方示例
                # 带着 Authorization 跟随 302 是能用的），已经在上面修掉了。
                # 这一支留着是**便宜的保险**：只在已经 4xx/5xx 之后多发一次，
                # 而缺了它的代价是「片子已生成已计费却取不回来」。
                r.close()
                r = requests.get(item,
                                 headers={"User-Agent": "ScriptToVideoRunner/2.0"},
                                 timeout=timeout, proxies=self._proxies(),
                                 stream=True)
            try:
                r.raise_for_status()
            except requests.RequestException:
                r.close()
                raise
            # 先写 .part 再改名：下到一半断了（视频几十 MB，断过），
            # 直接写 dest 会留下一个**够大但不完整**的文件 ——
            # 大小检查放它过去，下次 isfile 为真于是永远跳过，
            # 成片里那一段是坏的。改名是原子的，要么完整要么没有。
            # 服务商自报的字节数。**拿来核对**，别只是收着 ——
            # `.part` + 原子改名防的是「断在中途」（那时会抛异常），
            # 防不住「干净地少给一半」：有些 CDN / 代理在长传输上会正常关闭连接，
            # iter_content 不抛异常就结束了，于是我们改名收下一个半截文件。
            #
            # 图片有末尾标记（IEND / FFD9）兜底，**视频没有** —— `_END_MARK`
            # 表里只有 .png/.jpg，.mp4 走到那里直接放行。而半截的 mp4 往往
            # 还能播，只是短了几秒：拼接出来的成片少一段，没有任何报错。
            want = 0
            try:
                want = int(r.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                want = 0
            got = 0
            try:
                log("下载连接已建立，正在接收结果")
                last_report = time.monotonic()
                with _atomic_output(dest) as part:
                    with open(part, "wb") as f:
                        for chunk in r.iter_content(chunk_size=64 << 10):
                            f.write(chunk)
                            got += len(chunk)
                            now = time.monotonic()
                            if now - last_report >= 5:
                                total = f" / {want / (1 << 20):.1f} MB" if want else " MB"
                                log(f"正在下载结果：{got / (1 << 20):.1f}{total}")
                                last_report = now
                    if want and got < want:
                        raise ApiError(
                            f"下载没下完：服务商说这个文件有 {want:,} 字节，"
                            f"实际只收到 {got:,} 字节（缺 {want - got:,}）。"
                            f"连接是正常关闭的，所以没有网络报错 —— "
                            f"这种半截文件往往还能打开、只是短了一截，"
                            f"收下的话成片会少一段而且不报错，所以这里判失败。\n"
                            f"来源：{item[:200]}",
                            status=0, kind=RETRYABLE)
                    self.result_source_bytes[os.path.abspath(dest)] = os.path.getsize(part)
                    _normalize_result_image(part, dest, log)
                    _check_saved(part, src, extension=os.path.splitext(dest)[1].lower())
            finally:
                r.close()
        else:
            raw = _b64_bytes(item, item)
            with _atomic_output(dest) as part:
                with open(part, "wb") as f:
                    f.write(raw)
                self.result_source_bytes[os.path.abspath(dest)] = os.path.getsize(part)
                _normalize_result_image(part, dest, log)
                _check_saved(part, src, extension=os.path.splitext(dest)[1].lower())
        return dest
