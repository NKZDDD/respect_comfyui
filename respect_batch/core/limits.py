# -*- coding: utf-8 -*-
"""并发闸门。三层，从外到内依次获取。

  1. 批内线程池   ThreadPoolExecutor(max_workers=用户填的并发数)
  2. 每家配额     一个服务商一个信号量（跨批共享）
  3. 全局总闸     所有在途 API 调用的总上限

为什么不是一个 `-j N` 了事：多家混跑时，按最保守的那家设 N 就浪费，
按最宽的设就会把某一家打爆 —— 而打爆的表现不是"429 太快了"这种明白话，
多半是"生成失败"，看不出是自己撞的自己。

第三层之外还有一层不在这儿：**按账号排队**（accounts.py）。
HVTALD 那种一个账号同时只能跑一条的家，粒度是账号不是服务商 ——
同一家 3 个账号该能同时跑 3 条，而每个账号内部严格串行。
服务商粒度表达不出来：限成 1 浪费另外两个账号，限成 3 会有两条挤在同一个账号上。

（这个文件叫 limits 不叫 gate，是因为 providers/gate.py 是**服务商 Gate**
  api-gate.astralmindai.com。撞名的后果是 import 到错的那个，还不报错。）
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Optional


class CancelledWhileWaiting(InterruptedError):
    pass


class Gate:
    """全局 + 按服务商的并发闸门。可热更新上限。"""

    def __init__(self, global_limit: int = 8, per_provider: Optional[dict] = None):
        self._lock = threading.Condition()
        self._global_limit = max(1, global_limit)
        self._batch_limits: dict = {}
        self._per_conf = dict(per_provider or {})
        self._inflight: dict = {}
        self._inflight_total = 0

    def configure(self, global_limit: int, per_provider: dict) -> None:
        with self._lock:
            self._global_limit = max(1, int(global_limit or 1))
            self._per_conf = {k: max(1, int(v)) for k, v in (per_provider or {}).items() if v}
            self._lock.notify_all()

    def _limit(self):
        return sum(self._batch_limits.values()) or self._global_limit

    @contextmanager
    def batch_limit(self, run_id: str, parallelism: int):
        """发行版的并发由每批选择，服务商配额仍跨批共享。"""
        with self._lock:
            self._batch_limits[run_id] = parallelism
            self._lock.notify_all()
        try:
            yield
        finally:
            with self._lock:
                del self._batch_limits[run_id]
                self._lock.notify_all()

    @contextmanager
    def slot(self, provider: str, cancel=None):
        with self._lock:
            while (self._inflight_total >= self._limit() or
                   self._inflight.get(provider, 0) >= self._per_conf.get(provider, float('inf'))):
                if cancel and cancel():
                    raise CancelledWhileWaiting("此批次已停止，任务尚未提交")
                self._lock.wait(0.5 if cancel else None)
            self._inflight[provider] = self._inflight.get(provider, 0) + 1
            self._inflight_total += 1
        try:
            yield
        finally:
            with self._lock:
                self._inflight[provider] -= 1
                self._inflight_total -= 1
                self._lock.notify_all()

    def snapshot(self) -> dict:
        with self._lock:
            return {"global_limit": self._limit(),
                    "global_inflight": self._inflight_total,
                    "per_provider_limit": dict(self._per_conf),
                    "per_provider_inflight": {k: v for k, v in self._inflight.items() if v}}


GATE = Gate()
