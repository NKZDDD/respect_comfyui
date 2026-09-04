# -*- coding: utf-8 -*-
"""HVTALD 空间（z988.top）。底层是**即梦 AI 国际版**，一手工作室转售。

和本程序接过的所有服务商都不是一类，但对外**做成普通 Provider**，
在前端就是下拉里多一家、照常排进优先级链 —— 它的怪癖全在这个文件里消化掉：

| 它的怪癖 | 这里怎么消化 |
|---|---|
| 没有比例字段，**比例要写在 prompt 最前面** | 自动把 `task.ratio` 拼到提示词开头 |
| 固定 15 秒 / 1080P，不可调 | capabilities 只报 15 秒；给别的值就纠正并说明 |
| 结果靠 **回调** `feedbackurl`，不是查任务 | 没有公网回调时改为轮询 WebDAV 的 `outs/` |
| 成片在 WebDAV 里、要 basic auth | 自己下载，不走 save_item 的匿名取 |
| 认证是 `deviceId`+`token` 写在 body 里 | 从 api_key 里解出来，见下面 `_creds()` |

**凭据怎么传**：`build()` 只给 api_key / base_url / proxy / timeout，
而这家要 5 个值（deviceId、token、webdav 地址、用户名、密码）。
所以 api_key 字段接受三种写法，用户把客服给的东西**原样粘进去**就行：

  1. JSON：`{"deviceId":"…","token":"…","webDavUrl":"…","user":"…","password":"…"}`
  2. 分号键值：`deviceId=…;token=…;webdav=…;user=…;password=…`
  3. 留空 → 读环境变量 `HVTALD_DEVICE_ID` / `HVTALD_TOKEN` /
     `HVTALD_WEBDAV_URL` / `HVTALD_WEBDAV_USER` / `HVTALD_WEBDAV_PASSWORD`

⚠ 成片**只保存 48 小时**，且 API 与 WebDAV 都是明文 HTTP。
"""

from __future__ import annotations

import json
import os
import random
import re
import string
import time
import xml.etree.ElementTree as ET
from typing import Callable, Optional
from urllib.parse import unquote, urlparse

import requests

from ..apiutil import ApiError
from .base import Provider, VideoTask

API_PATH = "/dy/brush/fromApi"
MAX_REFS = 9
FIXED_DURATION = 15                       # 固定 15 秒，文档写死
RATIOS = ["9:16", "16:9", "1:1", "4:3", "3:4"]
_RATIO_HEAD = re.compile(r"^\s*\d{1,2}\s*[:：]\s*\d{1,2}")

_ENV = {
    "device_id": "HVTALD_DEVICE_ID", "token": "HVTALD_TOKEN",
    "webdav_url": "HVTALD_WEBDAV_URL", "user": "HVTALD_WEBDAV_USER",
    "password": "HVTALD_WEBDAV_PASSWORD",
}
_ALIAS = {
    "deviceid": "device_id", "device_id": "device_id",
    "token": "token",
    "webdavurl": "webdav_url", "webdav_url": "webdav_url", "webdav": "webdav_url",
    # 别名要宽。认不出来的后果是**静默变成空密码** —— 然后 WebDAV 401，
    # 而人明明填了。`dav_user` / `dav_pass` 这几个是很自然会写的写法。
    "user": "user", "username": "user", "webdav_user": "user",
    "dav_user": "user", "davuser": "user", "webdavuser": "user",
    "password": "password", "pass": "password", "webdav_password": "password",
    "dav_pass": "password", "dav_password": "password", "davpass": "password",
    "webdav_pass": "password", "passwd": "password",
}


def _action_id() -> str:
    """24 位小写字母。

    文档请求参数表写「32 位」、回调参数表写「24 位」，自相矛盾；
    示例 `jdbamfupzohjmbsnxsombhip` 是 24 位纯小写 —— 以示例为准，
    示例是真跑出来的，表格是人写的。
    """
    return "".join(random.choice(string.ascii_lowercase) for _ in range(24))


def parse_creds(api_key: str) -> dict:
    """把 api_key 里的凭据解出来。JSON / 分号键值 / 环境变量，三种都认。

    宽容解析是刻意的：用户手上是客服发来的一段文本，格式五花八门。
    与其让他学一种格式，不如这里多认几种 —— 认不出来的项再退回环境变量。
    """
    out = {k: "" for k in _ENV}
    raw = (api_key or "").strip()

    if raw.startswith("{"):
        try:
            for k, v in (json.loads(raw) or {}).items():
                key = _ALIAS.get(str(k).strip().lower())
                if key and isinstance(v, (str, int)):
                    out[key] = str(v).strip()
        except Exception:                                   # noqa: BLE001
            pass
    elif "=" in raw:
        for part in re.split(r"[;\n]+", raw):
            if "=" not in part:
                continue
            k, _, v = part.partition("=")
            key = _ALIAS.get(k.strip().lower())
            # **空值不覆盖已有值。** 账号表单里共用那几项排在前面、
            # 账号自己那几项排在后面（后者本该赢，见 core/accounts）。
            # 而「账号用不一样的存储」那几个框留空时也会写成 `password=`
            # 这种空值 —— 照旧覆盖的话，**共用的密码被清成空**，
            # 然后 WebDAV 401，而报错说的是「找不到 outs」。
            # 留空的意思是「用共用的」，不是「清掉」。
            if key and (v.strip() or not out.get(key)):
                out[key] = v.strip()

    for key, env in _ENV.items():                # 没填的退回环境变量
        if not out[key]:
            out[key] = os.environ.get(env, "").strip()
    return out


class HvtaldProvider(Provider):
    id = "hvtald"
    name = "HVTALD 空间（即梦国际版·15秒）"
    aliases = ("z988", "即梦国际", "hv")
    default_base_url = "http://ha.z988.top"
    supports = ("video",)
    # imgs 要「绝对地址」，本机图必须先传对象存储换链接
    ref_mode = "url"
    # **按账号计费，而且一个账号同时只能生成一条。** 想并发只能配多个账号 ——
    # 并发上限就是账号数。挤在同一个账号上不会报「并发超限」这种明白话，
    # 只会排队超时或者直接拒，而失败记录里只看得到「生成失败」。
    per_account_serial = True

    # **这一家的判定就是「outs/ 里有没有出现成片」，别的什么都不看。**
    # 用户原话（2026-08-26）：「长时间没有出现作物就是出现了任务异常，
    # 我不去判断是什么异常只要他超过多少时间我就算他失败了」。
    #
    # 所以墙可以短。能短的前提是**排队在墙外**：账号池的槽位是在调
    # generate_video 之前拿的，全局闸门上限也被压到账号数（见
    # produce.make_video_worker），所以这个墙只覆盖「投递 + 远端生成」，
    # 不含本地等空账号那一段。固定 15 秒 / 1080p 的活，正常几分钟内落盘。
    #
    # 别把它写进全局默认：出图 900、别家出片 2400，各家的合理值差一个
    # 数量级，一个数管所有家的结果就是「有的家白等半小时，有的家没等够」。
    poll_defaults = {"interval": 10, "timeout": 1200}

    # 账号表单。键名和上面 `_ALIAS` 认的一致 —— 不一致就是「填了读不到」。
    #
    # 共用/各自的分法按客服实际给凭据的形状来：deviceId + token 一个账号一份，
    # webdav 那三项通常整批共用（写一次）。单个账号要用别的存储时可以覆盖。
    account_form = {
        "shared_label": "共用存储（WebDAV，填一次给所有账号用）",
        "shared": (
            ("webdav", "WebDAV 地址", False,
             "客服给的那个 https 地址，成片会传到这里（**只保存 48 小时**）"),
            ("user", "WebDAV 用户名", False, ""),
            ("password", "WebDAV 密码", True, ""),
        ),
        "per_label": "账号（一个账号同时只能跑一条，配几个就是几路并发）",
        "per": (
            ("deviceId", "deviceId / 设备号", False, "客服给的那一串"),
            ("token", "token", True, ""),
            ("webdav", "这个账号单独用的 WebDAV 地址", False,
             "留空 = 用上面共用的那个"),
            ("user", "单独的用户名", False, "留空 = 用共用的"),
            ("password", "单独的密码", True, "留空 = 用共用的"),
        ),
    }

    def __init__(self, api_key: str = "", base_url: str = "", proxy: str = "",
                 timeout: int = 900):
        super().__init__(api_key=api_key, base_url=base_url, proxy=proxy, timeout=timeout)
        self.creds = parse_creds(api_key)
        self._timeout = timeout
        self._outs = None        # 找到的成片目录（相对 webdav 地址），见 _find_outs
        self._is_dir: dict = {}  # 上一次列目录时哪些名字是目录
        self._tried: list = []   # 找 outs 时试过哪些路径 —— 报错要说出来

    # ------------------------------------------------------------ 能力
    def capabilities(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "default_base_url": self.default_base_url,
            "supports": list(self.supports),
            "video": {
                "models": ["即梦国际版"],
                "default_model": "即梦国际版",
                "ratios": RATIOS,
                "durations": [FIXED_DURATION],       # 只有 15 秒，别给前端选别的
                "default_duration": FIXED_DURATION,
                "resolutions": ["1080p"],
                "max_refs": MAX_REFS,
                "ref_mode": "url",
                "poll_interval": self.poll_defaults["interval"],
                "poll_timeout": self.poll_defaults["timeout"],
                "notes": "固定 **15 秒 / 1080P**，不卡人脸，参考图 ≤9 张、必须是公网绝对地址。"
                         "这家**没有比例字段** —— 比例是从提示词最前面提取的，"
                         "本类会自动把所选比例拼到 prompt 开头，调用方照常设 ratio 即可。"
                         "并发 = 开通的线路数；成片在 WebDAV 里**只保存 48 小时**。",
            },
            "notes": "凭据填在 API Key 里（JSON 或 deviceId=…;token=…;webdav=…;user=…;password=… ），"
                     "也可用 HVTALD_* 环境变量。API 与 WebDAV 均为明文 HTTP。",
        }

    def selftest(self) -> Optional[dict]:
        """凭据齐不齐 → WebDAV 连不连得上 → `outs/` 在哪一层。

        这三件按顺序查，因为**后一件依赖前一件**，而混在一起报的话
        「401」和「地址填成网页版了」看起来一样。
        """
        ok, missing = self.ready()
        if not ok:
            return {"ok": False,
                    "msg": f"凭据不全，缺：{'、'.join(missing)}"}
        base = self.creds["webdav_url"]
        try:
            self._list_url(self._up(0), missing_ok=False)
        except ApiError as exc:
            m = str(exc)
            hint = ""
            if "404" in m:
                hint = ("　这个地址本身就不存在。**最常见的是填了网页版的地址** ——"
                        "网页版是给人看的页面，WebDAV 是另一个入口（客服给的那个），"
                        "两者经常不是同一个地址。")
            elif "401" in m or "403" in m:
                hint = "　地址是对的，用户名或密码不对。"
            return {"ok": False, "msg": f"WebDAV 连不上：{m[:160]}{hint}"}
        outs = self._find_outs(lambda _m: None)
        if not outs:
            kids = self._child_dirs()
            # **只探这一层。** 不再「把整个空间找一遍」——
            # 位置是固定的（见 _find_outs 的说明）。所以这里的任务是把
            # 「该往哪层填」摆出来，让人一次填对。
            return {"ok": False,
                    "msg": (f"WebDAV 通了（{base}），但这个地址下面没有 `outs/`"
                            f" —— 成片是从那里取的。" + chr(10)
                            + f"探的是：{self._tried[0]}" + chr(10)
                            + "这一层现有的目录："
                            + (("、".join(kids[:12])
                                + ("…" if len(kids) > 12 else ""))
                               if kids else "（一个都没有 —— 多半是地址或账号密码不对）")
                            + chr(10)
                            + "把地址改成 `outs` 的上一层"
                            + ("（多半是上面某个目录里面）" if kids else "")
                            + "，再点一次自检。")}
        return {"ok": True, "msg": f"WebDAV 通了，成片目录：{outs}"}

    def ready(self) -> tuple:
        """凭据齐不齐。缺哪项直接说，别等发出去才 401。"""
        missing = [k for k, v in self.creds.items() if not v]
        return (not missing, missing)

    # ------------------------------------------------------------ WebDAV
    def _auth(self):
        return (self.creds["user"], self.creds["password"])

    def _dav(self, sub: str = "") -> str:
        base = self.creds["webdav_url"].rstrip("/")
        return f"{base}/{sub.strip('/')}" if sub.strip("/") else base

    def _up(self, levels: int, sub: str = "") -> str:
        """把 webdav 地址往上剪 `levels` 层，再接上 `sub`。返回绝对地址。

        **不用 URL 里的 `..`**：那要服务端自己规范化，而不少 WebDAV
        （尤其自建的）不做 —— 结果是 404，而我们会当成「这一层没有」，
        把一个本来找得到的目录判成找不到。自己裁是确定的。
        """
        u = urlparse(self.creds["webdav_url"].rstrip("/"))
        parts = [p for p in u.path.split("/") if p]
        if levels:
            parts = parts[:-levels] if levels < len(parts) else []
        path = "/".join(parts + ([sub.strip("/")] if sub.strip("/") else []))
        return f"{u.scheme}://{u.netloc}/{path}" if path else f"{u.scheme}://{u.netloc}/"

    def _list(self, sub: str = "outs", missing_ok: bool = True) -> list:
        """PROPFIND 列目录 → [(文件名, 完整URL)]。相对 webdav 地址的那一版。"""
        return self._list_url(self._dav(sub), missing_ok, sub)

    def _list_url(self, url: str, missing_ok: bool = True, sub: str = "",
                  depth: str = "1", kinds: bool = False) -> list:
        """按**绝对地址**列目录。WebDAV 就是 HTTP 扩展方法，不用额外依赖。

        `missing_ok=False` 时，目录不存在会抛错而不是返回空列表 ——
        **「目录不存在」和「目录是空的」不是一回事**，见 `_wait`。

        `depth="infinity"` 会连子目录里的东西一起列出来。取片要用它 ——
        这一家的成片在 `outs/<日期>/` 里，只列一层拿回来的全是目录名。
        `kinds=True` 时返回 `[(名字, 地址, 是不是目录)]` —— 取片要按**这一条**
        判，不能查 `self._is_dir`（那是按名字存的，多层列举时会串）。
        """
        try:
            r = requests.request("PROPFIND", url, auth=self._auth(),
                                 headers={"Depth": depth,
                                          "Content-Type": "application/xml"},
                                 timeout=60)
        except requests.RequestException as exc:
            raise ApiError(f"连不上 WebDAV（{url}）：{exc}")
        if r.status_code == 404:
            if missing_ok:
                return []
            raise ApiError(
                f"WebDAV 上没有 `{sub or url}/` 这个目录（{url} 返回 404）。"
                f"成片是从这里取的 —— 目录不在，就永远取不到。\n"
                f"多半是 webdav 地址填到了**错的层级**：它应该指到\n"
                f"`outs/` 的**上一层**，而不是某个线路目录（比如 `.../5051`）"
                f"或者 `conf/` 下面。\n"
                f"去「设置 → HVTALD → 共用存储」核对那个地址，"
                f"或者用 WebDAV 网页版翻一下 `outs` 在哪一层。",
                status=404, kind="task_fatal")
        if r.status_code >= 400:
            # **状态码要带上**（原来只写在文案里，程序读不到）——
            # 上层要靠它分开「路径不存在」和「账号密码不对」，
            # 两者的修法完全不同，指错了人会去改一个没错的地方。
            raise ApiError(f"WebDAV 列目录失败 HTTP {r.status_code}（{url}）"
                           f"—— 401/403 多半是空间账号密码不对",
                           status=r.status_code)
        out = []
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError as exc:
            raise ApiError(f"WebDAV 返回的不是合法 XML：{exc}")
        self_path = urlparse(url).path.rstrip("/")
        # **按 response 逐条读，目录看 `resourcetype/collection`。**
        #
        # 原来只看「href 以 / 收尾」—— 那是个约定，不是规范。实测这台
        # 服务器（fo.z988.top:901）给目录的 href **不带结尾斜杠**：
        #   /…/5051/outs   collection=True
        # 于是 `_is_dir` 全是 False，`_child_dirs()` **永远返回空** ——
        # 报错里那句「这一层现有的目录：（一个都没有 —— 多半是地址或
        # 账号密码不对）」在这台服务器上是**永远成立的假话**，
        # 哪怕路径和密码都对。用户对着它去改地址，而地址本来是对的
        # （实遇 2026-08-28）。
        for resp in root.iter("{DAV:}response"):
            href = resp.find("{DAV:}href")
            raw = ((href.text if href is not None else "") or "").strip()
            if not raw or raw.rstrip("/").endswith(self_path):
                continue
            name = unquote(raw.rstrip("/").rsplit("/", 1)[-1])
            if not name:
                continue
            full = raw if raw.startswith("http") else (
                f"{urlparse(url).scheme}://{urlparse(url).netloc}{raw}")
            rt = resp.find(".//{DAV:}resourcetype")
            is_col = (rt is not None
                      and rt.find("{DAV:}collection") is not None)
            # 结尾斜杠仍然认 —— 有的服务端不给 resourcetype
            is_dir = is_col or raw.endswith("/")
            self._is_dir[name] = is_dir
            out.append((name, full, is_dir) if kinds else (name, full))
        return out

    def _outs_files(self, outs: str) -> tuple:
        """`outs/` 里所有**文件**（含日期子目录里的）→ `([(名字, 地址)], 说明)`。

        这一家的实际布局（实拉，2026-08-31）：
            outs/20260821/kionrlxozknnblmxjroyjldrzvvmobao_MMTVTCALD000004-….mp4
            outs/20260828/…  outs/20260830/…  outs/20260831/…

        也就是**按日期分子目录**。原来这里只 `Depth: 1` 列 `outs/`，
        拿回来的四条全是目录名（`20260821` 这种），而匹配条件是
        「以 actionId 开头且 .mp4 结尾」—— 一条都对不上。
        后果不是报错：每一条视频白等满 1200 秒，然后报「那个目录在，
        只是里面没有这一条」，听起来像服务商没出片，而片子早就躺在里面了。
        日志里那句「outs/ 现有 N 个文件」也永远是 0。

        先试 `Depth: infinity`（这台服务器认，一次拿全）；服务端不认的
        （有些 WebDAV 默认禁 infinity）退回「列一层 + 逐个子目录再列一层」。
        **不做无限递归** —— 位置是固定的，只是多了一层日期桶。
        """
        try:
            rows = self._list_url(outs, depth="infinity", kinds=True)
            files = [(n, u) for n, u, d in rows if not d]
            if files or not [1 for _n, _u, d in rows if d]:
                return files, "Depth:infinity"
        except ApiError:
            pass            # 不认 infinity，走下面那条
        rows = self._list_url(outs, kinds=True)
        files = [(n, u) for n, u, d in rows if not d]
        subs = [(n, u) for n, u, d in rows if d]
        for _n, u in subs:
            try:
                files += [(n2, u2) for n2, u2, d2
                          in self._list_url(u, kinds=True) if not d2]
            except ApiError:
                continue    # 某个日期目录读不了，不该毒掉整次取片
        return files, f"逐层：outs + {len(subs)} 个子目录"

    # ------------------------------------------------------------ 找 outs
    # 往上最多剪几层。**一路剪到空间根**（路径有几段就剪几层，再封一个上界）——
    # 实遇的地址是 `/project/pro_test/conf/sd2_HVTALD_0818/5051`，五段；
    # 写死 4 层就正好差一层到不了根，而那恰好可能是 `outs` 所在的地方。
    #
    # 上界还是要有：PROPFIND 不便宜，无界搜索在大空间上能跑几分钟 ——
    # 而那看起来就是「卡住了」。8 层足够覆盖任何合理的目录深度。
    _UP_LEVELS = 8

    def _find_outs(self, log: Callable = print) -> str:
        """成片目录：就是 `<你填的 webdav 地址>/outs`。不在那儿就返回空串。

        **不翻目录了。** 原来会往上剪 8 层、往下看一层地找 `outs` ——
        用户原话（2026-08-28）：「理论上他的生产位置是固定的一个 outs，
        而不是要去找多层…为什么有这种八、九层的查找」。对。位置是固定的，
        翻找只有两种结果：要么白探十几次（每一次都是一个 WebDAV 请求），
        要么**探到一个同名但不属于这条线路的 outs**，然后一直等一个永远不会
        出现在那儿的成片 —— 后者比直接报错难查得多。

        所以只认这一层。不在这一层就说清该改哪儿，让人把地址填对 ——
        那是一次性的事，不该每次投递都靠猜。
        """
        if self._outs is not None:
            return self._outs
        url = self._up(0, "outs")
        self._tried = [url]
        if self._probe_url(url):
            self._outs = url
            return url
        return ""

    def _probe_url(self, url: str) -> bool:
        """这个绝对地址是不是一个能列的目录。"""
        try:
            self._list_url(url, missing_ok=False)
            return True
        except ApiError:
            return False

    def _child_dirs(self) -> list:
        """填的这一层下面有哪些子目录。列不出来就返回空。"""
        self._is_dir.clear()
        try:
            self._list_url(self._up(0), missing_ok=True)
        except ApiError:
            return []
        return [n for n, d in self._is_dir.items() if d][:12]

    def _level_exists(self) -> str:
        """填的这一层怎么样：ok / auth（账号密码不对）/ missing（不存在）。

        `_child_dirs` 用的是 `missing_ok=True` —— **404 也返回空列表**。
        于是「这一层在、但底下没有子目录」和「这一层压根不存在」长得一模一样，
        都报「一个都没有 —— 多半是地址或账号密码不对」。而两者改法完全不同：
        前者是层级填浅/填深了，后者是路径整段写错了。
        用户实遇（2026-08-28）：地址里多了一段 `/webdav/`，整条路径都 404，
        而报错让他去数层级。
        """
        try:
            self._list_url(self._up(0), missing_ok=False, sub="你填的这一层")
            return "ok"
        except ApiError as exc:
            # 401/403 **不是**「路径不存在」—— 是账号密码不对。
            # 报成前者的话，人会去改一个没错的地址（用户问的正是
            # 「所以是我的路径填错了对吗」，而这一点当时答不了）。
            if getattr(exc, "status", 0) in (401, 403):
                return "auth"
            return "missing"

    def _ancestors(self) -> list:
        """[(地址, 这一层在不在, 它下面有没有 outs)]，从填的这一层往上。

        **只用来报错，不用来取片。** 用户否掉的是「翻着找 outs 然后就用它」
        （会静默用上另一条线路的 outs，然后一直等一个不会出现的成片）；
        而「告诉他 outs 其实在哪一层」是纯诊断 —— 路径写错时他要的正是这个，
        否则只能一层一层猜。
        """
        depth = len([x for x in urlparse(self.creds["webdav_url"]).path.split("/")
                     if x])
        rows = []
        for lv in range(0, min(depth, 8) + 1):
            base = self._up(lv)
            try:
                self._list_url(base, missing_ok=False)
            except ApiError:
                rows.append((base, False, False))
                continue
            rows.append((base, True, self._probe_url(self._up(lv, "outs"))))
        return rows

    def _download(self, url: str, dest: str) -> str:
        """带 basic auth 下载。**先写 .part 再改名** —— 下到一半断了不能留个够大的坏文件，
        那种文件能过大小检查、下次 isfile 为真被跳过，成片里就永远缺一段。"""
        os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
        r = requests.get(url, auth=self._auth(), stream=True, timeout=self._timeout)
        if r.status_code >= 400:
            raise ApiError(f"成片下载失败 HTTP {r.status_code}: {url}")
        part = dest + ".part"
        try:
            with open(part, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
            if os.path.getsize(part) < 1024:
                raise ApiError(f"成片只有 {os.path.getsize(part)} 字节，不是有效视频：{url}")
            os.replace(part, dest)
        finally:
            if os.path.exists(part):
                os.remove(part)
        return dest

    # ------------------------------------------------------------ 出片
    def build_body(self, task: VideoTask, action_id: str = "") -> dict:
        """拼投递 body。**比例自动拼进 prompt** 是这家的关键适配点。"""
        prompt = (task.prompt or "").strip()
        ratio = (task.ratio or "9:16").strip()
        if not _RATIO_HEAD.match(prompt):
            # 这家没有比例字段，系统从提示词最前面提取 —— 调用方照常设 ratio，
            # 这里替他拼上，免得每个上层都得记住这条怪癖。
            prompt = f"{ratio} {prompt}".strip()
        refs = [r for r in (task.refs or []) if str(r).startswith(("http://", "https://"))]
        dropped = len(task.refs or []) - len(refs)
        if dropped:
            raise ApiError(
                f"HVTALD 的 imgs 要「绝对地址」，这一项给的 {dropped} 张不是。"
                f"本该有 {len(task.refs)} 张参考图 —— 少了出来的就不是同一个人，"
                f"所以不出这条。去「设置 → 参考图上传」配对象存储。",
                status=0, kind="task_fatal")
        if not refs:
            raise ApiError("HVTALD 的 imgs 是必填项，至少要 1 张参考图（绝对地址）",
                           status=0, kind="task_fatal")
        return {
            "deviceId": self.creds["device_id"],
            "token": self.creds["token"],
            "actionId": action_id or _action_id(),
            "imgs": refs[:MAX_REFS],
            "prompt": prompt,
            "webDavUrl": self.creds["webdav_url"],
            "user": self.creds["user"],
            "password": self.creds["password"],
        }

    def generate_video(self, task: VideoTask, dest: str, *, log: Callable = print,
                       cancel: Optional[Callable] = None,
                       poll_interval: int = 30, poll_timeout: int = 1800) -> dict:
        ok, missing = self.ready()
        if not ok:
            raise ApiError(
                f"HVTALD 凭据不全，缺：{missing}。"
                f"把客服给的信息粘到 API Key 里（JSON 或 deviceId=…;token=…;webdav=…;"
                f"user=…;password=… ），或设 HVTALD_* 环境变量。",
                status=0, kind="task_fatal")

        if int(task.duration or FIXED_DURATION) != FIXED_DURATION:
            log(f"HVTALD 固定出 {FIXED_DURATION} 秒（不可调），已忽略 duration={task.duration}")

        body = self.build_body(task)
        aid = body["actionId"]
        feedback = task.extra.get("feedbackurl")
        if feedback:
            body["feedbackurl"] = feedback

        log(f"HVTALD 投递 actionId={aid} 参考图{len(body['imgs'])}张 prompt={body['prompt'][:40]}…")
        url = self.session.base_url.rstrip("/") + API_PATH
        try:
            r = requests.post(url, json=body, timeout=self._timeout)
        except Exception as exc:                            # noqa: BLE001
            raise ApiError(f"HVTALD 投递发不出去（{url}）：{exc}")
        # **别直接 r.json()。** 网关这一刻没起来、被前置拦了、或者返回
        # 一个 HTML 页面时，抛出来的是
        #   Expecting value: line 1 column 1 (char 0)
        # 那句话不含状态码、也不含它到底回了什么 —— 看不出是网关 502
        # 还是地址填错回了个登录页。用户实遇（2026-08-28）就是这一句，
        # 而它对着一屏日志什么都说明不了。
        raw = (r.text or "").strip()
        try:
            data = r.json()
        except Exception:                                    # noqa: BLE001
            head = raw[:300].replace(chr(10), " ")
            raise ApiError(
                f"HVTALD 投递回了非 JSON（{url}）：HTTP {r.status_code}，"
                f"正文前 300 字：{head or '（空的）'}" + chr(10)
                + ("（200 + 空正文：多半是网关这一刻没起来，稍后重来）"
                   if r.status_code == 200 and not raw
                   else "（看状态码：502/504 是网关挂了；回 HTML 多半是"
                        "base_url 填错了，填的不是接口地址）"),
                status=r.status_code, kind="retryable")
        if int(data.get("code", 0)) != 200:
            raise ApiError(f"HVTALD 投递被拒：{str(data)[:300]}"
                           f"（检查 deviceId/token，以及线路是否还有余量）")
        aid = str(data.get("actionId") or aid)
        log(f"HVTALD 已插入任务：{data.get('msg', '')} actionId={aid}")

        got = self._wait(aid, poll_interval, poll_timeout, log=log, cancel=cancel)
        self._download(got, dest)
        return {"task_id": aid, "source": got, "provider": self.id, "model": "即梦国际版"}

    def _wait(self, aid: str, interval: int, timeout: int, *, log, cancel=None) -> str:
        """回调用不上时的取片方式：轮询 outs/ 找以 actionId 开头的 mp4。

        文档的回调示例里 videopath 就是 `{actionId}_xxx.mp4` 这个形状。
        """
        # **先把成片目录找出来。** 不让用户去数目录层级 ——
        # 客服给的地址可能指到线路目录、conf 上面或者空间根，
        # 而哪一层有 `outs` 是查得出来的事。
        outs = self._find_outs(log)
        if not outs:
            here = self._tried[0]
            rows = self._ancestors()
            hit = [b for b, ok, o in rows if ok and o]
            where = ((f"**`outs/` 在这一层下面：{hit[0]}** —— "
                      f"把 WebDAV 地址改成它。")
                     if hit else
                     "往上几层也都没有 `outs/` —— 用 WebDAV 网页版翻一下它在哪儿。")
            tail = ("（不再自己翻目录取片：翻到另一条线路的同名 outs，"
                    "会一直等一个永远不会出现在那儿的成片。这里只是告诉你它在哪。）")
            state = self._level_exists()
            if state == "auth":
                raise ApiError(
                    "WebDAV 拒绝了（401/403）—— **这不是路径问题，是空间的账号密码不对**。" + chr(10)
                    + f"  {self._up(0)}" + chr(10)
                    + "（任务投递成功不代表这一步也能过：deviceId/token 是接口的凭据，"
                    + "WebDAV 用户名密码是另一套。）" + chr(10)
                    + "去「设置 → HVTALD → 共用存储」核对用户名和密码；密码留空是「不改」，要换得重新填一遍。",
                    status=401, kind="task_fatal",
                    err_code="HVTALD_OUTS_MISSING")
            if state == "missing":
                # **路径整段不存在**和「路径在、只是没有 outs」是两回事，
                # 改法完全不同（见 _level_exists）。
                alive = [b for b, ok, _o in rows if ok]
                raise ApiError(
                    "WebDAV 地址填的这个路径**本身就不存在**（404）：" + chr(10)
                    + f"  {self._up(0)}" + chr(10)
                    + (("往上找，这几层是在的：" + chr(10)
                        + "".join(f"  {b}" + chr(10) for b in alive[:6]))
                       if alive else
                       ("往上一层都不在 —— 多半是主机/端口/账号密码不对，"
                        "或者地址里多了一段（比如 `/webdav/`）。" + chr(10)))
                    + where + chr(10) + tail,
                    status=404, kind="task_fatal",
                    err_code="HVTALD_OUTS_MISSING")
            kids = self._child_dirs()
            raise ApiError(
                f"这个地址在，但它下面没有 `outs/`：{here}" + chr(10)
                + "成片是从 `outs/` 取的，路径不对就永远取不到。" + chr(10)
                + "这一层现有的目录："
                + (("、".join(kids[:12]) + ("…" if len(kids) > 12 else ""))
                   if kids else "（一个子目录都没有）") + chr(10)
                + where + chr(10) + tail,
                status=404, kind="task_fatal", err_code="HVTALD_OUTS_MISSING")
        start, seen = time.time(), -1
        while time.time() - start < timeout:
            if cancel and cancel():
                raise ApiError("用户已取消")
            # 目录已经确认存在了，所以这里用宽松模式：
            # 临时挪走或网络抖一下不该判死这一条。
            # **要连日期子目录一起看。** 成片在 `outs/<日期>/` 里，
            # 只列 outs 一层拿回来的全是目录名，一条都匹配不上（见 _outs_files）。
            files, how = self._outs_files(outs)
            if len(files) != seen:
                log(f"HVTALD outs/ 现有 {len(files)} 个成片文件（{how}），等 {aid} …")
                seen = len(files)
            for name, full in files:
                if name.startswith(aid) and name.lower().endswith((".mp4", ".mov")):
                    log(f"HVTALD 成片就绪：{name}")
                    return full
            time.sleep(interval)
        # **不重投。** 用户原话（2026-08-26）：「有调整提示词这个操作才要
        # 重试，如果没有就不需要重试」。对 —— 超时这条路上提示词一个字都
        # 没变，同参重投只是换一个 actionId 再撞一次同样的墙，而**每次都
        # 算一次钱**；更难看的是取片按 actionId 前缀找，重投之后前一次的
        # 成片如果晚到，没人认领（WebDAV 只存 48 小时）。
        # 提示词被审核拒绝那条路不受影响：那条走 soften 改写后重发，
        # 发出去的东西真的变了，才值得再花一次。
        files, how = self._outs_files(outs)
        raise ApiError(
            f"等了 {timeout} 秒没在 `{outs}/` 看到 {aid} 开头的成片"
            f"（那个目录在，连日期子目录一起扫的，{how}，"
            f"现有 {len(files)} 个成片文件）。\n"
            f"**这条不再重投** —— 提示词没有变，同参再发一次只会撞"
            f"同一个墙，而每次都算一次钱。任务没丢，"
            f"actionId={aid} 记下来可以稍后取；"
            f"成片晚到的话它就在 `{outs}/` 里。\n"
            f"这家按线路排队，满负荷时要等。一个账号同时只跑一条 —— "
            f"经常撞墙就加账号（加并发），调大这个墙只是等更久。\n"
            f"顺便说一句：`conf/.../used/` 不是成片目录 —— 那是「投文件式」"
            f"用法里服务端取走配置后挪过去的地方，我们走的是 HTTP 接口，"
            f"那个目录永远是空的，别拿它判断任务有没有发出去。",
            status=0, kind="task_fatal", err_code="VIDEO_POLL_TIMEOUT")
