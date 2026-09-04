# -*- coding: utf-8 -*-
"""服务商注册表：内置的自动发现，外挂的从数据目录扫。

新增一家有两条路：

  A. 外挂（推荐，不用动程序）
     把 myprovider.py 丢进 <数据目录>/providers/，重启或在设置页点「重新扫描」。
     打包成 exe 之后也能这么加 —— 程序里的代码是只读的，但这个目录不是。

  B. 内置
     在本目录写 myprovider.py 即可，**不用再去改这个文件**（以前要手动往
     _CLASSES 里加一行，加漏了就白写）。

两种都只要求：继承 Provider、给 id / name / supports、实现 capabilities 和
generate_image / generate_video。前端会自动出现这一家及其模型和参数选项。

加载失败不会拖垮程序：坏掉的那个文件被记进 ERRORS，设置页会红字列出来，
其余的照常用 —— 一个写错的插件不该让整个生产台起不来。
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import pkgutil
import sys
import traceback

from .. import paths
from .base import ImageTask, Provider, VideoTask   # noqa: F401  对外导出

# 内置的显示顺序：实测稳的排前面。没列到的按文件名排在后面。
#
# 这张表还有第二个用途，比排序重要得多：exe 里扫不到目录时按它逐个 import
# （见 _load_builtin）。所以**新加一家内置服务商必须写进来**，
# 否则它在 exe 里可能整家缺席 —— 页面上只是少一个选项，不报错。
# 这里漏过 ake 和 yishou，一直没被发现，是因为 exe 里目录恰好扫得到；
# 哪天扫不到就会一次性少四家。加一家就往这里加一行。
_BUILTIN_ORDER = ["paisio", "lingganya", "zeroapi", "m86", "aicopy", "kunji",
                  "octopus", "ake", "wuxianhuabu", "gate", "yishou",
                  "chaomo", "xiaobalong", "hvtald", "zhi",
                  "haomanju", "julun"]

REGISTRY: dict = {}          # id → 类
ALIASES: dict = {}           # 别名 → id
SOURCES: dict = {}           # id → 它从哪儿来（"内置" / 插件文件路径）
ERRORS: list = []            # 加载失败的文件 + 原因，给设置页显示
WARNINGS: list = []          # 加载成功但声明有问题的，照样能用但要提醒


def _classes_in(module) -> list:
    """模块里定义的 Provider 子类（不含 import 进来的）。"""
    out = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (issubclass(obj, Provider) and obj is not Provider
                and obj.__module__ == module.__name__ and getattr(obj, "id", "")):
            out.append(obj)
    return out


def _check(cls) -> list:
    """上架前的自检。返回问题清单（空 = 没问题）。

    查的都是「不查就会静默出错图」的那几项 —— 参考图形式声明错了不会报错，
    只会让参考图被悄悄丢掉，出来的脸不是本人。
    """
    bad = []
    inst = cls()
    if not getattr(cls, "name", ""):
        bad.append("没有 name（前端下拉会显示成空白）")
    sup = tuple(getattr(cls, "supports", ()) or ())
    if not sup:
        bad.append("没声明 supports，前端不知道它能出图还是出片")
    for media in sup:
        if media not in ("image", "video"):
            bad.append(f"supports 里的 {media!r} 不认识（只能是 image / video）")
            continue
        # 基类给了默认实现（直接抛 NotImplementedError），所以不能只看 callable，
        # 要看子类到底覆盖了没有 —— 没覆盖就是「声明支持但跑起来必炸」
        fn = f"generate_{media}"
        if getattr(cls, fn, None) is getattr(Provider, fn, None):
            bad.append(f"声明支持 {media} 却没实现 {fn}（跑到这一步会直接抛 NotImplementedError）")
        u, b, a = inst.needs_url("", media), inst.needs_bytes(""), inst.accepts_url("", media)
        if u and b:
            bad.append(f"{media}：既声明只收链接又声明只收字节，二选一")
        if u and not a:
            bad.append(f"{media}：声明只收链接，却又说不吃链接")
    try:
        cap = inst.capabilities()
        for k in ("id", "name", "supports"):
            if k not in cap:
                bad.append(f"capabilities() 缺 {k}")
    except Exception as exc:                        # noqa: BLE001
        bad.append(f"capabilities() 抛异常：{exc}")
    return bad


def _register(cls, source: str) -> None:
    pid = cls.id
    problems = _check(cls)
    if problems:
        WARNINGS.append({"id": pid, "source": source, "problems": problems})
    if pid in REGISTRY and SOURCES.get(pid) != source:
        # 外挂覆盖内置是允许的（不改程序就能替换一家的实现），但必须说出来
        WARNINGS.append({"id": pid, "source": source,
                         "problems": [f"覆盖了已有的同名服务商（原来来自 {SOURCES[pid]}）"]})
    REGISTRY[pid] = cls
    SOURCES[pid] = source
    for a in getattr(cls, "aliases", ()) or ():
        ALIASES[a] = pid


def _builtin_names() -> list:
    """本目录里有哪几个内置服务商模块。

    正常情况扫目录就行。但**打包成 exe 之后本目录在磁盘上根本不存在** ——
    .py 都在 exe 内部的归档里，扫出来是空的，结果是「一家服务商都没有」，
    而且不报错，页面就是干干净净的空下拉框。这个坑源码方式跑永远遇不到。

    所以冻结环境下扫不到时，退回按 _BUILTIN_ORDER 挨个 import，并留下警告 ——
    退回意味着「新加的内置文件如果没写进 _BUILTIN_ORDER 就会被漏掉」，
    这件事必须说出来，不能悄悄少一家。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    names = sorted(m.name for m in pkgutil.iter_modules([here])
                   if not m.name.startswith("_") and m.name != "base")
    if not names and getattr(sys, "frozen", False):
        names = list(_BUILTIN_ORDER)
        WARNINGS.append({"id": "(内置)", "source": "exe",
                         "problems": ["exe 里扫不到内置服务商目录，已按内置清单逐个加载。"
                                      "如果新加了内置服务商但没写进 _BUILTIN_ORDER，"
                                      "它在 exe 里会缺席 —— 打包时的自检会报出来"]})
    return names


def _load_builtin() -> None:
    names = _builtin_names()
    names.sort(key=lambda n: (_BUILTIN_ORDER.index(n) if n in _BUILTIN_ORDER
                              else len(_BUILTIN_ORDER), n))
    for name in names:
        try:
            mod = importlib.import_module(f".{name}", __name__)
        except Exception:                            # noqa: BLE001
            ERRORS.append({"file": f"{name}.py", "source": "内置",
                           "error": traceback.format_exc(limit=3)})
            continue
        for cls in _classes_in(mod):
            _register(cls, "内置")


def _load_plugins() -> None:
    d = paths.plugins_dir()
    if not os.path.isdir(d):
        return
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        full = os.path.join(d, fn)
        modname = f"stv_plugin_{os.path.splitext(fn)[0]}"
        try:
            spec = importlib.util.spec_from_file_location(modname, full)
            mod = importlib.util.module_from_spec(spec)
            # 先塞进 sys.modules 再执行：插件里如果有 dataclass、相对导入之类
            # 需要按名字找回自己的写法，不塞进去会报 KeyError
            sys.modules[modname] = mod
            spec.loader.exec_module(mod)
        except Exception:                            # noqa: BLE001
            sys.modules.pop(modname, None)
            ERRORS.append({"file": full, "source": "插件",
                           "error": traceback.format_exc(limit=4)})
            continue
        found = _classes_in(mod)
        if not found:
            ERRORS.append({"file": full, "source": "插件",
                           "error": "这个文件里没找到 Provider 的子类。"
                                    "插件要 `from core.providers.base import Provider` "
                                    "然后写一个继承它的类，并给 id / name / supports。"})
            continue
        for cls in found:
            _register(cls, full)


def reload_all() -> dict:
    """重新扫描内置 + 插件。设置页点「重新扫描」时调这个，不用重启。"""
    REGISTRY.clear()
    ALIASES.clear()
    SOURCES.clear()
    ERRORS.clear()
    WARNINGS.clear()
    _load_builtin()
    _load_plugins()
    return status()


def status() -> dict:
    """给设置页看的加载报告。"""
    return {
        "plugins_dir": paths.plugins_dir(),
        "plugins_dir_exists": os.path.isdir(paths.plugins_dir()),
        "providers": [{"id": pid, "name": getattr(cls, "name", pid),
                       "supports": list(getattr(cls, "supports", ())),
                       "source": SOURCES.get(pid, ""),
                       "builtin": SOURCES.get(pid) == "内置",
                       "aliases": [a for a, t in ALIASES.items() if t == pid]}
                      for pid, cls in REGISTRY.items()],
        "errors": list(ERRORS),
        "warnings": list(WARNINGS),
    }


def resolve_id(provider_id: str) -> str:
    pid = (provider_id or "").strip()
    return pid if pid in REGISTRY else ALIASES.get(pid, pid)


def list_capabilities() -> list:
    """所有服务商的能力声明（前端渲染用）。某一家的声明抛异常不该连累别家。"""
    out = []
    for pid, cls in REGISTRY.items():
        try:
            cap = cls().capabilities()
            # 从类属性补上来，**不指望每家的 capabilities() 自己写一遍** ——
            # 漏写一家的后果是页面上那家还按单账号渲染（一个密码框），
            # 用户没地方粘第二个账号，而且看不出为什么并发上不去。
            cap.setdefault("per_account_serial",
                           bool(getattr(cls, "per_account_serial", False)))
            # 同理：漏了的后果是那家还按单个密码框渲染，用户没地方填 4K 分组
            # 那一把，然后 4K 被静默降级成 1K —— 图在、不报错、只是不对。
            cap.setdefault("key_fields",
                           [list(g) for g in getattr(cls, "key_fields", ())])
            # 账号表单同理：不下发页面就画不出来，改了后端等于没改。
            af = dict(getattr(cls, "account_form", {}) or {})
            for k in ("shared", "per"):
                if k in af:
                    af[k] = [list(x) for x in af[k]]
            cap.setdefault("account_form", af)
            out.append(cap)
        except Exception as exc:                     # noqa: BLE001
            out.append({"id": pid, "name": getattr(cls, "name", pid),
                        "supports": [], "broken": str(exc)})
    return out


def build(provider_id: str, api_key: str, base_url: str = "",
          proxy: str = "", timeout: int = 900) -> Provider:
    cls = REGISTRY.get(resolve_id(provider_id))
    if not cls:
        raise ValueError(f"未知服务商: {provider_id}"
                         f"（可用: {'、'.join(REGISTRY)}；"
                         f"别名: {'、'.join(ALIASES) or '无'}）")
    return cls(api_key=api_key, base_url=base_url, proxy=proxy, timeout=timeout)


_load_builtin()
_load_plugins()
