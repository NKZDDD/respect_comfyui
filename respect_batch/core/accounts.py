# -*- coding: utf-8 -*-
"""按账号排队 + 按账号计数。给 HVTALD 这类「一个账号只能同时跑一条」的家用。

和本程序接过的其它服务商都不是一类：

    别家     一个 Key，并发上限由服务商的限流决定 → 调大并发就更快
    这一家   **按账号计费**，而且一个账号同时只能生成一条 →
             想并发只能配多个账号，并发上限 = 账号数

所以这里做两件事，都是**账号维度**的：

  1. **排队**：一个账号一个槽位，占着就得等。多账号才有并发。
  2. **计数**：这个账号今天做了多少条 —— 用户要看的就是「一天能做多少」。

为什么排队不能复用 executor 里那道 GATE：那道闸门是「每家一个信号量」，
粒度是**服务商**。这一家的粒度是**账号** —— 同一家里 3 个账号应该能同时
跑 3 条，而每个账号内部严格串行。用服务商粒度表达不出来：
限成 1 就浪费另外两个账号，限成 3 就会有两条挤在同一个账号上。

**挤在同一个账号上的后果不是报错**，是那一家直接拒或者排队超时 ——
而失败记录只会说「生成失败」，看不出是自己把自己撞了。
"""

from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
from contextlib import contextmanager
from typing import Callable, Optional

from . import paths

# **不能用绝对时间当上限。** 原来写的是 3600 秒，而合法的等待远超它：
# 一个账号 × 50 条视频 × 每条 5 分钟 = 4 小时以上，第十几条之后就会报
# 「等了 3600 秒也没等到空账号」—— 而它其实在正常排队。
# 用户原话：「如果我只填一个账号也是可以一个做完做下一个的」。对。
#
# 换成**按进度**判断：只要还有账号在被归还，就说明队伍在往前走，接着等。
# 连这么久都没有任何账号被归还，才是真卡住了（比一次出片的轮询上限
# 还长一截 —— 出片本来就慢）。
STUCK_SECONDS = 3600

# 计数保留多少天。留着看趋势，但别让文件无限长。
KEEP_DAYS = 60

_LOCK = threading.RLock()
_POOLS: dict = {}          # provider_id → _Pool
_USAGE_LOCK = threading.RLock()


class Account:
    """一个账号。`api_key` 是**原样的那段凭据文本**，交给服务商自己去解。"""

    __slots__ = ("api_key", "label")

    def __init__(self, api_key: str, label: str):
        self.api_key = api_key
        self.label = label

    def __repr__(self) -> str:            # 只出现在日志里，不含密钥
        return f"<账号 {self.label}>"


# 「一条账号从这里开始」只认**身份**那一项，不认 token。
#
# 一开始把 token 也算进去了，结果一个写成多行的账号
# （deviceId 一行、token 一行）被判成「这一段里有两个开头」→ 拆成两个账号，
# 而拆出来的每半个都缺字段，跑起来是「凭据不全」。
_HEAD = re.compile(r"^\s*\"?(deviceId|device_id|设备|账号|account)\"?\s*[=:：]",
                   re.I)

# `deviceId=dev-1`、`deviceId: dev-1`、`"deviceId": "dev-1"` 三种都要认出来。
_DEVICE = re.compile(
    r"\"?(?:deviceId|device_id)\"?\s*[=:：]\s*\"?([A-Za-z0-9_\-]{4,})", re.I)


def _label(text: str, i: int) -> str:
    """给这个账号起一个能在页面上认出来、又不泄露密钥的名字。

    取 deviceId 的前 8 位。取不到就用序号 —— **绝不回退到 token 的片段**，
    那是密钥，进了日志和页面就等于泄露。
    """
    m = _DEVICE.search(text)
    return m.group(1)[:8] if m else f"账号{i}"


def parse_accounts(api_key: str) -> list:
    """把一段粘进来的文本拆成**多个账号**。

    用户手上是客服发来的几段文本，格式五花八门，所以认得宽一点：

      · JSON 数组   `[{...}, {...}]`            → 一个元素一个账号
      · JSON 对象   `{...}`                     → 一个账号
      · 空行分段    多行一段、段之间空一行      → 一段一个账号
      · 一行一个    `deviceId=…;token=…;…`      → 一行一个账号

    最后那条是最常见的粘法，也是**最容易被吃掉的**：`parse_creds` 里
    `[;\\n]+` 把换行和分号当成一回事，于是三行三个账号会被合成一个
    （后面的覆盖前面的），只剩最后一个账号在跑 —— 不报错，只是慢三倍。
    """
    raw = (api_key or "").strip()
    if not raw:
        return []

    if raw.startswith("["):
        try:
            rows = json.loads(raw)
            if isinstance(rows, list):
                return [Account(json.dumps(r, ensure_ascii=False),
                                _label(json.dumps(r, ensure_ascii=False), i))
                        for i, r in enumerate(rows, 1) if isinstance(r, dict)]
        except Exception:                                   # noqa: BLE001
            pass
    if raw.startswith("{"):
        return [Account(raw, _label(raw, 1))]

    # 先按空行分段
    blocks = [b.strip() for b in re.split(r"\n\s*\n", raw) if b.strip()]
    out: list = []
    shared: list = []          # 不属于任何一个账号的那几行 —— 见下
    for b in blocks:
        lines = [ln.strip() for ln in b.splitlines() if ln.strip()]
        # 这一段里有几个「开头字段」？多于一个说明是「一行一个账号」。
        heads = [ln for ln in lines if _HEAD.match(ln)]
        if len(heads) > 1:
            # **只写了一次的共用字段要留下来。**
            #
            # 客服给凭据的常见写法是：每个账号一行 deviceId+token，
            # 而 webdav / user / password 只写一次（那三项本来就是共用的）。
            # 按行拆完之后每个账号只剩 deviceId+token —— 服务商那边
            # `parse_creds` 是在**单个账号的文本**上跑的，webdav 那几项
            # 一个都没有，于是每一条都在凭据检查那儿抛「凭据不全」。
            #
            # 用户实遇（2026-08-21）：三条任务同一秒起、同一秒失败，
            # 而日志上只有「没见过的错误」—— 那句写清了缺哪几项的话
            # 被日志层吞了（见 diagnose.one_line）。
            out.extend(heads)
            shared.extend(ln for ln in lines if ln not in heads)
        else:
            out.append("\n".join(lines))
    if shared and len(out) > 1:
        # **共用的排在前面，账号自己那一行排后面。**
        #
        # 服务商那边解凭据是「一路扫过去，后面的覆盖前面的」
        # （`parse_creds` 里 `out[key] = v`）。所以顺序决定谁说话算数：
        # 共用在后 → 它会盖掉某个账号自己填的 webdav；共用在前 → 账号能覆盖。
        # 而「共用一份、单个账号可覆盖」是用户定的形状。
        head = "\n".join(dict.fromkeys(shared)) + "\n"
        out = [head + o for o in out]
    return [Account(t, _label(t, i)) for i, t in enumerate(out, 1) if t.strip()]


class _Pool:
    """一个服务商的账号池。一个账号一个槽位。"""

    def __init__(self, provider: str, accounts: list):
        self.provider = provider
        self.accounts = list(accounts)
        self._free: queue.Queue = queue.Queue()
        for a in self.accounts:
            self._free.put(a)
        # 最后一次有账号被归还的时刻。**判「卡住了」用它，不用绝对等待时长** ——
        # 一个账号排 50 条队是正常的，等 4 小时也正常。
        self._last_release = time.time()

    def __len__(self) -> int:
        return len(self.accounts)

    def busy(self) -> int:
        return max(0, len(self.accounts) - self._free.qsize())

    @contextmanager
    def slot(self, log: Optional[Callable] = None,
             cancel: Optional[Callable] = None):
        """占一个空账号。全忙就等 —— 这就是「一个账号只能跑一条」的实现。"""
        waited = 0.0
        told = False
        while True:
            if cancel and cancel():
                raise RuntimeError("等空账号的时候被取消了")
            try:
                acct = self._free.get(timeout=2)
                break
            except queue.Empty:
                waited += 2
                if log and not told and waited >= 4:
                    told = True
                    log(f"{len(self.accounts)} 个账号都在忙，排队等一个空的 —— "
                        f"这一家一个账号只能同时生成一条，"
                        f"{len(self.accounts)} 个账号就是 {len(self.accounts)} 路并发，"
                        f"剩下的按顺序一条一条来（想更快就多配账号）。")
                idle = time.time() - self._last_release
                if idle >= STUCK_SECONDS:
                    raise RuntimeError(
                        f"已经 {int(idle)} 秒没有任何账号被归还了 —— 队伍不动了。"
                        f"（自己等了 {int(waited)} 秒。这一家一个账号同时只能生成一条，"
                        f"当前配了 {len(self.accounts)} 个账号，排队本身是正常的，"
                        f"但这么久一条都没做完不正常。）"
                        f"去看在跑的那几条是不是卡在轮询上，或者把出片的"
                        f"「等出结果最多多久」调小一点。")
        if log:
            log(f"用账号 {acct.label}（这一家一个账号只能同时跑一条）")
        try:
            yield acct
        finally:
            self._free.put(acct)
            self._last_release = time.time()   # 队伍往前走了一格


def configure(provider: str, api_key: str) -> int:
    """按当前凭据文本重建这一家的账号池，返回账号数。

    账号没变就**不重建** —— 重建会把在途任务占着的槽位凭空变回空闲，
    于是同一个账号上会挤进两条，而那正是这套东西要防的事。
    """
    fresh = parse_accounts(api_key)
    with _LOCK:
        old = _POOLS.get(provider)
        if old is not None and [a.api_key for a in old.accounts] == \
                [a.api_key for a in fresh]:
            return len(old)
        _POOLS[provider] = _Pool(provider, fresh)
        return len(fresh)


def pool(provider: str) -> Optional[_Pool]:
    with _LOCK:
        return _POOLS.get(provider)


# ---------------------------------------------------------------- 计数

def _usage_path() -> str:
    return os.path.join(paths.data_dir(), "account_usage.json")


def _read() -> dict:
    try:
        with open(_usage_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:                                       # noqa: BLE001
        return {}


def bump(provider: str, label: str, n: int = 1, day: str = "") -> None:
    """这个账号今天又做了 n 条。

    **计数放在数据目录、不放项目里**：账号是跨项目共用的，
    而用户要看的是「这个账号一天能做多少」—— 记在项目里的话，
    同一天跑两部剧就得自己把两个数加起来。
    """
    if not provider or not label:
        return
    day = day or time.strftime("%Y-%m-%d")
    with _USAGE_LOCK:
        data = _read()
        per = data.setdefault(provider, {})
        rows = per.setdefault(label, {})
        rows[day] = int(rows.get(day) or 0) + int(n)
        # 只留最近 KEEP_DAYS 天
        for k in sorted(rows)[:-KEEP_DAYS]:
            rows.pop(k, None)
        tmp = _usage_path() + ".part"
        try:
            os.makedirs(os.path.dirname(tmp), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, _usage_path())
        except Exception:                                   # noqa: BLE001
            # 计数记不下来不该拖垮出片 —— 那是观测，不是生产。
            pass


def report(provider: str, days: int = 7) -> dict:
    """最近几天，每个账号每天做了多少。

    返回 `{"days": [...], "rows": [{"label":…, "today":N, "total":N,
    "by_day":{...}}], "accounts": N, "busy": N}`。
    """
    today = time.strftime("%Y-%m-%d")
    want = [time.strftime("%Y-%m-%d",
                          time.localtime(time.time() - 86400 * i))
            for i in range(max(1, days))]
    per = (_read().get(provider) or {})
    p = pool(provider)
    known = [a.label for a in (p.accounts if p else [])]
    # 配着的账号排前面，历史里出现过但现在没配的排后面（也要能看见 ——
    # 不然「我记得昨天那个账号跑了很多」会查不到）
    labels = known + [k for k in sorted(per) if k not in known]
    rows = []
    for lb in labels:
        by_day = {d: int((per.get(lb) or {}).get(d) or 0) for d in want}
        rows.append({"label": lb,
                     "configured": lb in known,
                     "today": by_day.get(today, 0),
                     "total": sum(by_day.values()),
                     "by_day": by_day})
    return {"days": want, "rows": rows,
            "accounts": len(known), "busy": p.busy() if p else 0,
            "today_total": sum(r["today"] for r in rows)}
