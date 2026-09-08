# -*- coding: utf-8 -*-
"""JSON 读写。所有写入原子替换 + 全局锁。

必须连读也锁住：Windows 上 os.replace 的目标文件若被别的线程打开着读，
会 WinError 5 —— 而这个程序天生是多线程的，不锁必踩。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

LOCK = threading.RLock()


def read_json(path: str, default: Any = None) -> Any:
    with LOCK:
        if not os.path.isfile(path):
            return default
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return default


def write_json(path: str, data: Any) -> None:
    from .release import redact
    data = redact(data)
    with LOCK:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        for i in range(5):          # 杀软/索引器偶发占用，重试几次
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if i == 4:
                    raise
                time.sleep(0.05 * (i + 1))


def append_jsonl(path: str, row: dict) -> None:
    """逐条追加。跑批中途被强杀也留得下已完成的那些。"""
    with LOCK:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
