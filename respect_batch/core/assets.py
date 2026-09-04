# -*- coding: utf-8 -*-
"""界面上拖进来的参考图落在哪，以及原生的「选文件夹」对话框。

**为什么要有这个文件**：浏览器里选的文件只有内容、拿不到真实路径（安全限制），
而服务商那一层要的是一个能读的东西。让用户手打绝对路径是最省事的做法 ——
也正是用户明确否掉的那种（原话：「不要训练用户去用什么换行啊本地地址什么的」）。
所以拖进来的文件在这里落盘，之后一切照旧走路径。

按内容哈希去重：同一张参考图拖十次也只有一份，而且第二次开程序还认得它。
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import threading

from . import paths

# 只收图片。收别的没有意义 —— 参考图接口只认图，而一个 .docx 被当成参考图
# 发出去，多半是"生成失败"或者更糟：服务商忽略它照样出图。
OK_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
MAX_BYTES = 40 * 1024 * 1024

_SAFE = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_PICK_LOCK = threading.Lock()


def uploads_dir() -> str:
    d = os.path.join(paths.data_dir(), "uploads")
    os.makedirs(d, exist_ok=True)
    return d


def save(data: bytes, filename: str) -> dict:
    """存一份拖进来的图，返回 `{path, name, size}`。同内容不重复存。"""
    name = _SAFE.sub("_", os.path.basename(filename or "")).strip(" .") or "ref"
    ext = os.path.splitext(name)[1].lower()
    if ext not in OK_EXT:
        raise ValueError(f"只收图片（{'、'.join(sorted(OK_EXT))}），这个是 {ext or '没有扩展名'}")
    if not data:
        raise ValueError(f"{name} 是个空文件 —— 空的参考图发出去不报错，"
                         f"服务商收到的是「有参考图」，实际什么都没有")
    if len(data) > MAX_BYTES:
        raise ValueError(f"{name} 有 {len(data) // 1024 // 1024}MB，超过 "
                         f"{MAX_BYTES // 1024 // 1024}MB")

    h = hashlib.sha256(data).hexdigest()[:16]
    stem = os.path.splitext(name)[0][:40]
    path = os.path.join(uploads_dir(), f"{stem}_{h}{ext}")
    if not os.path.isfile(path) or os.path.getsize(path) != len(data):
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    return {"path": path, "name": name, "size": len(data)}


def readable(path: str) -> bool:
    """这个路径能不能作为缩略图发回浏览器。

    **只放行 uploads 目录里的**。不限制的话，页面上随便传个
    `C:\\Users\\...\\.ssh\\id_rsa` 过来，这个进程就成了本机文件读取器 ——
    服务只绑 127.0.0.1，但浏览器里任何一个页面都能往它发请求。
    """
    try:
        p = os.path.realpath(path)
        base = os.path.realpath(uploads_dir())
        return os.path.isfile(p) and os.path.commonpath([p, base]) == base
    except (ValueError, OSError):
        return False


def content_type(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def pick_dir(start: str = "") -> dict:
    """弹一个**系统原生**的选文件夹对话框，返回选中的路径。

    为什么值得为它引入 tkinter：输出目录是这个程序里唯一还需要"打字"的地方，
    而打错的表现是成品跑到了一个谁也想不起来的目录里（还不报错）。

    两个实现上的坑：
      · Tk 必须在自己的线程里从头建到尾，而且**建完就销毁** —— 留着的话
        第二次弹会拿到一个已经死掉的根窗口，表现是点了没反应。
      · 打包成 exe 时 tkinter 必须显式带上（spec 里不能 exclude 它），
        漏了的话按钮点下去只报一句 ImportError，而人只会觉得"这按钮坏了"。
    """
    out = {"ok": False, "path": "", "msg": ""}

    def go():
        try:
            import tkinter as tk                            # noqa: PLC0415
            from tkinter import filedialog                  # noqa: PLC0415
        except Exception as exc:                            # noqa: BLE001
            out["msg"] = (f"这台机器上没有 tkinter（{exc}），弹不出选择框。"
                          f"把目录粘进输入框也一样能用。")
            return
        root = None
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)   # 否则会开在浏览器后面，像没反应
            p = filedialog.askdirectory(
                title="选一个输出目录",
                initialdir=(start if start and os.path.isdir(start)
                            else os.path.expanduser("~")))
            if p:
                out["ok"], out["path"] = True, os.path.normpath(p)
            else:
                out["msg"] = "取消了"
        except Exception as exc:                            # noqa: BLE001
            out["msg"] = f"选择框打不开：{exc}。把目录粘进输入框也一样能用。"
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:                           # noqa: BLE001
                    pass

    with _PICK_LOCK:                    # 同时弹两个会互相抢主循环
        t = threading.Thread(target=go, daemon=True)
        t.start()
        t.join(timeout=300)
    if t.is_alive():
        return {"ok": False, "path": "",
                "msg": "选择框开着还没选完（等了 5 分钟）。选好之后再点一次。"}
    return out
