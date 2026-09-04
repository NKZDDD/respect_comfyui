# -*- coding: utf-8 -*-
"""模板：一整套「怎么跑」存起来，下次一选就套上。

**只存设置，不存提示词。** 提示词每次都不一样，存进去只会让人套完模板还得
先清空一遍；而"怎么跑"（哪家、什么模型、多大、多长、几路并发）是稳定的，
那才是每次都要重填一遍的东西。

也**不存参考图**：参考图跟着这一批的内容走，跟"怎么跑"是两回事。
"""

from __future__ import annotations

import time

from . import paths
from .store import read_json, write_json

# 能进模板的字段。**白名单而不是黑名单** —— 将来 spec 里加了新字段
# （比如某次跑批临时塞进去的凭据），黑名单会把它一起存进模板文件里。
FIELDS = ("provider", "kind", "model", "size", "ratio", "duration", "resolution",
          "concurrency", "repeat", "max_retry", "out_dir", "skip_existing")


def _path() -> str:
    import os
    return os.path.join(paths.data_dir(), "templates.json")


def load() -> list:
    data = read_json(_path(), []) or []
    return data if isinstance(data, list) else []


def save_one(name: str, spec: dict) -> dict:
    name = (name or "").strip()[:40]
    if not name:
        return {"ok": False, "msg": "模板得有个名字"}
    item = {"name": name, "saved": time.strftime("%Y-%m-%d %H:%M"),
            "spec": {k: spec.get(k) for k in FIELDS if spec.get(k) not in (None, "")}}
    items = [t for t in load() if t.get("name") != name]     # 同名覆盖
    items.append(item)
    write_json(_path(), items)
    return {"ok": True, "msg": f"已存成模板「{name}」", "templates": items}


def delete(name: str) -> dict:
    items = [t for t in load() if t.get("name") != name]
    write_json(_path(), items)
    return {"ok": True, "templates": items}
