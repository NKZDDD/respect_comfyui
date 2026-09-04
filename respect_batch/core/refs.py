# -*- coding: utf-8 -*-
"""参考图 → 能发出去的形式。

这一层不能省，也不能一刀切。各家要的形式**互相矛盾**，而给错形式的后果
不是报错，是**参考图被静默丢掉照样出图** —— 图出来了、任务标 ok、
只有脸不是本人。几百张里靠肉眼发现。

三种形式，按服务商自己的声明分派（base.py 里的 ref_mode / url_only_models）：

  needs_bytes   走 multipart，只收真文件字节 —— 给链接会被丢掉（超模图生图、坤鸡 edits）
  needs_url     只收公网链接 —— 给 data URI 会被丢掉（鹤 SD2、一手、智）
  其余          data URI 或链接都行

配了对象存储就一律换成链接：不只是为了 URL-only 那几家，能吃 data URI 的家
请求体也从几 MB 的 base64 缩成一行，快且稳。
"""

from __future__ import annotations

import os
from typing import Callable

from . import uploader
from .apiutil import ApiError, TASK_FATAL, resolve_ref


def rules_for(prov, media: str, override_side: int = 0, override_fmt: str = "") -> tuple:
    """这一家对参考图有什么要求 → `(最长边, 要什么格式)`。

    **没声明就是没要求：不缩、不转、原样发。** 参考图是喂给模型的身份和
    构图来源，压过之后脸就飘，而且日志里看不出来。只有服务商自己在
    capabilities 里声明了 ref_max_side / ref_format 才动它。
    """
    side, fmt = 0, ""
    try:
        cap = prov.capabilities() or {}
        for blk in ((cap.get(media) or {}), cap):
            side = side or int(blk.get("ref_max_side") or 0)
            fmt = fmt or str(blk.get("ref_format") or "")
    except Exception:                                       # noqa: BLE001
        pass
    if override_side:
        side = int(override_side)
    if override_fmt:
        fmt = str(override_fmt)
    return side, fmt


def make_resolver(prov, model: str, media: str, upload_cfg: dict,
                  ref_side: int = 0, ref_fmt: str = "") -> Callable:
    """返回 `resolve(src, log) -> str`。src 可以是本机路径 / http 链接 / data URI。"""
    up = upload_cfg or {}
    have_store = uploader.configured(up) and up.get("mode", "always") != "when_required"
    need_url = prov.needs_url(model, media)
    need_bytes = prov.needs_bytes(model)
    can_url = prov.accepts_url(model, media)
    use_url = need_url or (have_store and can_url)

    def resolve(src: str, log: Callable = print) -> str:
        src = (src or "").strip()
        if not src:
            return ""
        if src.startswith("data:"):
            # 只收链接的家拿到 data URI 会当没给 —— 这里直接拦，别让它静默降级
            if need_url:
                raise ApiError(
                    f"{prov.name} 的这个模型只收公网链接，你给的是 data URI。"
                    f"改成本机文件路径并配好对象存储（设置 → 参考图上传），"
                    f"或者换一家能直接吃图片内容的。", kind=TASK_FATAL)
            return src
        if src.startswith("http"):
            if need_bytes:
                raise ApiError(
                    f"{prov.name} 的这个模型走 multipart，只收真的文件字节，"
                    f"给链接会被丢掉（图照出、人不对）。请给本机文件路径。",
                    kind=TASK_FATAL)
            return src

        path = os.path.abspath(os.path.expanduser(src))
        # **先验这张图是不是真的图。** 0 字节的文件在三条分支上都过得去：
        # 传上去是个空对象、转 data URI 是段空数据 —— 服务商收到的是
        # "有参考图"，实际什么都没有。
        if not os.path.isfile(path):
            raise ApiError(f"参考图不存在：{path}", kind=TASK_FATAL)
        if os.path.getsize(path) < 512:
            raise ApiError(
                f"参考图是个空文件或者太小，不是一张真的图：{path}"
                f"（{os.path.getsize(path)} 字节）。少一张参考图出来的就不是同一个人，"
                f"所以这一条不出。", kind=TASK_FATAL)

        if need_bytes:
            return path                       # provider 自己读字节塞 multipart
        if not use_url:
            return resolve_ref(path, "", max_side=ref_side, fmt=ref_fmt)
        return uploader.to_url(path, up, max_side=ref_side, fmt=ref_fmt, log=log)

    return resolve
