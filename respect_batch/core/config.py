# -*- coding: utf-8 -*-
"""配置读写。一份 config.json，放数据目录。

密钥**只出不进**这条规则写在 `masked()` 里：页面拿到的永远是打码的，
保存时如果某一项还是打码串就当"没改"，保留原值。不这么做的话，
用户在页面上改了个并发数点保存，密钥就被那串星号覆盖了 —— 而且不报错，
下次跑批才发现全家 401。
"""

from __future__ import annotations

import copy
import os
from typing import Any

from . import distribution, paths
from .store import read_json, write_json

MASK = "********"
SECRET_KEYS = ("api_key", "secret_key", "access_key")

DEFAULTS: dict = {
    "providers": {},          # id → {api_key, base_url, proxy, ref_max_side, ref_format}
    "upload": {               # 对象存储：只收公网 URL 的那几家靠它
        "endpoint": "", "region": "auto", "bucket": "",
        "access_key": "", "secret_key": "",
        "public_base_url": "", "prefix": "respect", "public_acl": False,
        "mode": "always",     # always = 一律换链接（请求体也小）；when_required = 只在必须时
    },
    "limits": {
        "global": 8,          # 所有在途 API 调用的总上限
        "per_provider": {},   # id → 这一家的上限
    },
    "defaults": {
        "concurrency": 4,
        "max_retry": 2,
        "timeout": 900,       # 单条 HTTP 超时
        "poll_timeout_image": 900,
        "poll_timeout_video": 2400,
        "out_dir": "",
        "skip_existing": True,
    },
}


def _merge(base: Any, over: Any) -> Any:
    """深合并，而且**保证不和 DEFAULTS 共用任何一个内层对象**。

    原来这里是 `dict(base)`（浅拷贝）。后果：磁盘上没有 `providers` 这一节时，
    `load()["providers"]` **就是 DEFAULTS["providers"] 本身**，往里塞一把密钥
    等于改了模块级默认值。表现是「在页面上删掉某家的 Key、保存、刷新，它又回来了」
    —— 不报错，而且下一次 load 还会把它合进去，看起来像配置文件没保存成功。
    """
    if isinstance(base, dict) and isinstance(over, dict):
        out = {k: copy.deepcopy(v) for k, v in base.items()}
        for k, v in over.items():
            out[k] = _merge(base[k], v) if k in base else copy.deepcopy(v)
        return out
    return copy.deepcopy(over if over is not None else base)


def load() -> dict:
    source = (distribution.profile()["config"] if distribution.ENABLED
              else read_json(paths.config_path(), {}) or {})
    cfg = _merge(DEFAULTS, source)
    if not (cfg["defaults"].get("out_dir") or "").strip():
        cfg["defaults"]["out_dir"] = paths.default_out_dir()
    return cfg


def save(cfg: dict) -> None:
    if distribution.ENABLED:
        raise ValueError("发行版配置由管理员提供，不能在用户端修改")
    write_json(paths.config_path(), cfg)


def masked(cfg: dict) -> dict:
    """给页面看的那一份：所有密钥换成星号，长度信息也不给。"""
    out = _merge(DEFAULTS, cfg)
    for pid, blk in (out.get("providers") or {}).items():
        if (blk or {}).get("api_key"):
            blk["api_key"] = MASK
    for k in SECRET_KEYS:
        if (out.get("upload") or {}).get(k):
            out["upload"][k] = MASK
    return out


def apply_from_page(cfg: dict, incoming: dict) -> dict:
    """把页面提交的那份合进来，**打码串一律当没改**。"""
    merged = _merge(cfg, incoming)
    for pid, blk in (incoming.get("providers") or {}).items():
        if (blk or {}).get("api_key") == MASK:
            merged["providers"][pid]["api_key"] = \
                ((cfg.get("providers") or {}).get(pid) or {}).get("api_key", "")
    for k in SECRET_KEYS:
        if (incoming.get("upload") or {}).get(k) == MASK:
            merged["upload"][k] = (cfg.get("upload") or {}).get(k, "")
    return merged


def provider_cfg(cfg: dict, pid: str) -> dict:
    """某一家的凭据。api_key 留空时回落环境变量 —— CI/命令行跑批用得上。"""
    blk = dict(((cfg.get("providers") or {}).get(pid) or {}))
    if distribution.ENABLED:
        return blk
    if not (blk.get("api_key") or "").strip():
        for env in (f"RESPECT_{pid.upper()}_API_KEY", f"{pid.upper()}_API_KEY"):
            v = os.environ.get(env, "").strip()
            if v:
                blk["api_key"] = v
                break
    return blk


def import_from_studio() -> dict:
    """一次性从 script-to-video-studio 拷密钥过来。

    只拷 providers / upload / limits 三块 —— 那是"填过一遍不想再填"的部分。
    拷完两边各改各的，**不做同步**：同步的话一边调并发另一边跟着变，
    而人只记得自己动过一处。
    """
    src = os.path.join(paths.studio_data_dir(), "config.json")
    data = read_json(src, None)
    if data is None:
        return {"ok": False, "msg": f"没找到 Studio 的配置：{src}"}
    cfg = load()
    n = 0
    for pid, blk in (data.get("providers") or {}).items():
        if (blk or {}).get("api_key"):
            cfg.setdefault("providers", {})[pid] = dict(blk)
            n += 1
    if data.get("upload"):
        cfg["upload"] = _merge(cfg["upload"], data["upload"])
    if data.get("limits"):
        cfg["limits"] = _merge(cfg["limits"], data["limits"])
    save(cfg)
    return {"ok": True, "msg": f"导入了 {n} 家的密钥，外加对象存储和并发上限。"
                               f"从现在起两边各改各的，不会互相影响。",
            "count": n, "source": src}
