# -*- coding: utf-8 -*-
"""数据目录 = 配置、外挂服务商、账号计数、上传缓存都放这儿。

**故意和 script-to-video-studio 分开**（它用 Respect-Studio）：这是独立程序，
装不装 studio 都能跑，两边的配置也不该互相覆盖 —— 一边改了并发上限
另一边跟着变，是那种"我没动过它"的事故。

想共用 studio 已经填好的密钥，用「设置 → 从 Studio 导入」，一次性拷过来，
之后两边各改各的。
"""

from __future__ import annotations

import os
import sys

APP_NAME = "Respect-Batch"

FROZEN = bool(getattr(sys, "frozen", False))
# 打包成 exe 之后 __file__ 在临时解压目录里，程序目录要看 sys.executable
PROGRAM_DIR = (os.path.dirname(os.path.abspath(sys.executable)) if FROZEN
               else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_forced = {"data": ""}


def res(*parts: str) -> str:
    """随程序发布的只读资源（web/ 下的页面）。打包后在 _MEIPASS 里。"""
    base = getattr(sys, "_MEIPASS", "") or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def set_data_dir(path: str) -> None:
    _forced["data"] = os.path.abspath(os.path.expanduser(path)) if path else ""


def default_data_dir() -> str:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, APP_NAME)


def data_dir() -> str:
    if _forced["data"]:
        return _forced["data"]
    env = os.environ.get("RESPECT_BATCH_DATA_DIR", "").strip()
    if env:
        return os.path.abspath(os.path.expanduser(env))
    # 绿色版：config.json 就摆在 exe 旁边时继续用那儿，别悄悄换位置 ——
    # 换了的表现是"我的密钥全没了"，而它们其实还在原地。
    if os.path.isfile(os.path.join(PROGRAM_DIR, "config.json")):
        return PROGRAM_DIR
    return default_data_dir()


def config_path() -> str:
    return os.path.join(data_dir(), "config.json")


def plugins_dir() -> str:
    """外挂服务商目录。丢一个 .py 进去就多一家，不用改程序、不用重新打包。

    放数据目录而不是程序目录：打包成 exe 之后程序里的代码是只读的。
    """
    return os.path.join(data_dir(), "providers")


def runs_dir() -> str:
    """跑批记录（每次一个 manifest）。成品不放这儿，成品去用户选的输出目录。"""
    return os.path.join(data_dir(), "runs")


def default_out_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Desktop", "Respect批量输出")


def studio_data_dir() -> str:
    """studio 的数据目录 —— 只用来做一次性导入密钥，平时不碰。"""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "Respect-Studio")
