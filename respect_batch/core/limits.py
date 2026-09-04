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


class Gate:
    """全局 + 按服务商的并发闸门。可热更新上限。"""

    def __init__(self, global_limit: int = 8, per_provider: Optional[dict] = None):
        self._lock = threading.RLock()
        self._global_limit = max(1, global_limit)
        self._global = threading.BoundedSemaphore(self._global_limit)
        self._per_conf = dict(per_provider or {})
        self._sems: dict = {}
        self._inflight: dict = {}
        self._inflight_total = 0

    def configure(self, global_limit: int, per_provider: dict) -> None:
        """上限变化时重建信号量；在途任务不受影响，新任务按新上限。"""
        with self._lock:
            gl = max(1, int(global_limit or 1))
            if gl != self._global_limit:
                self._global_limit = gl
                self._global = threading.BoundedSemaphore(gl)
            new_conf = {k: int(v) for k, v in (per_provider or {}).items() if v}
            for k, v in list(self._sems.items()):
                if new_conf.get(k) != getattr(v, "limit", None):
                    self._sems.pop(k, None)
            self._per_conf = new_conf

    def set_provider_limit(self, provider: str, limit: int) -> None:
        """单独改某一家的上限，不动别家。给「按账号串行」的家用 ——
        它的上限**就是账号数**，而账号数是从密钥文本里解出来的，
        配置里那份表不知道这个数。

        为什么必须卡在这道闸而不是在 worker 里等：worker 是在
        `with GATE.slot(provider)` **里面**跑的。1 个账号 + 并发 10 的话，
        9 条会占着全局槽位干等，把别家的任务堵死。卡在闸上就不进来占槽。
        """
        n = max(1, int(limit or 1))
        with self._lock:
            if self._per_conf.get(provider) == n:
                return
            self._per_conf[provider] = n
            self._sems.pop(provider, None)     # 下一个任务按新上限重建

    def _sem_for(self, provider: str):
        limit = self._per_conf.get(provider)
        if not limit:
            return None
        with self._lock:
            sem = self._sems.get(provider)
            if sem is None:
                sem = threading.BoundedSemaphore(max(1, int(limit)))
                sem.limit = int(limit)               # type: ignore[attr-defined]
                self._sems[provider] = sem
            return sem

    @contextmanager
    def slot(self, provider: str):
        sem = self._sem_for(provider)
        if sem:
            sem.acquire()
        self._global.acquire()
        with self._lock:
            self._inflight[provider] = self._inflight.get(provider, 0) + 1
            self._inflight_total += 1
        try:
            yield
        finally:
            with self._lock:
                self._inflight[provider] = max(0, self._inflight.get(provider, 1) - 1)
                self._inflight_total = max(0, self._inflight_total - 1)
            self._global.release()
            if sem:
                sem.release()

    def snapshot(self) -> dict:
        with self._lock:
            return {"global_limit": self._global_limit,
                    "global_inflight": self._inflight_total,
                    "per_provider_limit": dict(self._per_conf),
                    "per_provider_inflight": {k: v for k, v in self._inflight.items() if v}}


GATE = Gate()
