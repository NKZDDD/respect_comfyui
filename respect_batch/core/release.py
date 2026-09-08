"""发行版模型目录和请求边界；凭据只由编译后的 distribution 模块提供。"""
from __future__ import annotations

import copy
import json
import re
from urllib.parse import quote, urlsplit

from . import distribution

OPTION_KEYS = ("sizes", "default_size", "ratios", "default_ratio", "durations",
               "default_duration", "resolutions", "min_refs", "max_refs", "ref_mode")
TASK_KEYS = {"model", "kind", "provider", "tasks", "refs", "ref_slots", "ref_pick_mode",
             "size", "ratio", "duration", "resolution", "repeat", "concurrency",
             "max_retry", "skip_existing", "out_dir"}


def catalog() -> list:
    return distribution.profile()["models"]


def public_boot() -> dict:
    from . import config, paths, refs, uploader
    cfg = config.load()
    caps = {"id": "preset", "name": "Respect", "supports": []}
    for kind in ("image", "video"):
        rows = [r for r in catalog() if r["kind"] == kind]
        if not rows:
            continue
        caps["supports"].append(kind)
        caps[kind] = {"models": [r["id"] for r in rows], "default_model": rows[0]["id"],
                      "model_labels": {r["id"]: r["label"] for r in rows},
                      "model_options": {r["id"]: {**{k: v for k, v in r["options"].items()
                                                if k in OPTION_KEYS},
                          "upload_ready": uploader.configured(refs.upload_config(cfg, r["provider"]))}
                          for r in rows}}
    return {"ok": True, "distribution": True, "preview": bool(distribution.profile().get("preview")),
            "providers": [caps], "templates": [],
            "config": {"providers": {"preset": {"api_key": "configured"}},
                       "defaults": cfg["defaults"], "limits": {"global": cfg["limits"]["global"]}},
            "default_out_dir": paths.default_out_dir(), "data_dir": "",
            "upload_ready": uploader.configured(cfg.get("upload"))}


def prepare(raw: dict) -> tuple[dict, dict]:
    """在任何凭据解析或网络调用前，把公开模型选项转换成唯一批准的路由。"""
    from . import assets, config, refs
    if distribution.profile().get("preview"):
        raise ValueError("这是待配置的预览版，请联系管理员提供正式发行包")
    if set(raw) - TASK_KEYS:
        raise ValueError("发行版不接受自定义服务商、接口地址或高级调用字段")
    if raw.get("provider") not in (None, "", "preset"):
        raise ValueError("发行版只能使用预设模型")
    item = next((r for r in catalog() if r["id"] == raw.get("model")), None)
    if item is None or raw.get("kind", item["kind"]) != item["kind"]:
        raise ValueError("这个模型不在发行版开放清单中")
    cfg = config.load()
    pc = cfg["providers"][item["provider"]]
    if not pc.get("api_key"):
        raise ValueError("这是待配置的预览版，请联系管理员提供正式发行包")
    out = copy.deepcopy(raw)
    rows = out.get("tasks")
    if not isinstance(rows, list) or not rows:
        raise ValueError("至少填写一条任务")

    def check_refs(refs):
        if not isinstance(refs, list) or any(not isinstance(r, str) or not assets.readable(r) for r in refs):
            raise ValueError("参考图须通过本程序的图片或文件夹入口导入")

    shared = out.get("refs", [])
    check_refs(shared)
    pools = out.get("ref_slots", [])
    if not isinstance(pools, list):
        raise ValueError("素材库格式不正确")
    for pool in pools:
        check_refs(pool)
    for row in rows:
        if not isinstance(row, dict) or set(row) - {"prompt", "refs"}:
            raise ValueError("任务格式不正确")
        if not isinstance(row.get("prompt"), str):
            raise ValueError("提示词必须是文字")
        check_refs(row.get("refs", []))
    opts = item["options"]
    for key, choices in (("size", "sizes"), ("ratio", "ratios"),
                         ("duration", "durations"), ("resolution", "resolutions")):
        value = out.get(key)
        if value not in (None, "", 0) and (key not in ("duration",) and not isinstance(value, str)):
            raise ValueError("模型参数格式不正确")
        if value not in (None, "", 0) and str(value) not in [str(v) for v in opts.get(choices, [])]:
            raise ValueError(f"当前模型不支持这个{dict(size='尺寸', ratio='比例', duration='时长', resolution='分辨率')[key]}")
    max_refs = opts.get("max_refs")
    pool_count = sum(bool(pool) for pool in pools)
    if any(len(set(shared + row.get("refs", []))) + pool_count < opts.get("min_refs", 0)
           for row in rows):
        raise ValueError("当前模型每条任务需要一张首帧参考图")
    if max_refs is not None and any(len(set(shared + row.get("refs", []))) + pool_count > max_refs
                                    for row in rows):
        raise ValueError(f"当前模型每条最多 {max_refs} 张参考图，请减少参考图或素材库")
    if (shared or pool_count or any(r.get("refs") for r in rows)) and opts.get("ref_mode") == "url":
        from .uploader import configured
        if not configured(refs.upload_config(cfg, item["provider"])):
            raise ValueError("发行包尚未配置图片上传服务，请联系管理员更新发行包")
    defaults = cfg["defaults"]
    out.update(provider=item["provider"], model=item["model"], kind=item["kind"])
    out["concurrency"] = max(1, min(int(raw.get("concurrency") or defaults["concurrency"]),
                                    defaults["concurrency"]))
    out["max_retry"] = max(0, min(int(raw.get("max_retry", defaults["max_retry"])), defaults["max_retry"]))
    out["repeat"] = max(1, min(int(raw.get("repeat") or 1), 500))
    for key in ("timeout", "skip_existing", "out_dir"):
        out.setdefault(key, defaults[key])
    out["poll_timeout"] = defaults["poll_timeout_image" if item["kind"] == "image" else "poll_timeout_video"]
    return out, cfg


def redact(value):
    """输出到页面和记录前，隐藏凭据、上游标识和原始响应。"""
    if not distribution.ENABLED:
        return value
    profile = distribution.profile()
    secrets = [p.get("api_key", "") for p in profile["config"]["providers"].values()]
    upload = profile["config"].get("upload", {})
    secrets += [upload.get(k, "") for k in ("access_key", "secret_key")]
    private_names = set(profile.get("private_names", []))
    private_names.update(profile["config"]["providers"])
    for pc in [upload, *profile["config"]["providers"].values()]:
        for key in ("endpoint", "public_base_url", "base_url"):
            host = urlsplit(pc.get(key, "")).hostname
            if host:
                private_names.add(host)
    model_labels = {row["model"]: row["label"] for row in profile["models"]}
    hidden_fields = {"api_key", "access_key", "secret_key", "proxy", "base_url",
                     "endpoint", "public_base_url", "bucket", "region", "meta",
                     "source", "raw", "response", "headers", "authorization",
                     "per_provider_limit", "per_provider_inflight"}

    user_fields = {"prompt", "path", "dest", "manifest", "out_dir", "refs", "ref_slots", "name"}

    def clean(v, hide_source=True):
        if isinstance(v, dict):
            return {k: ("Respect" if k == "provider" else
                        model_labels.get(x, clean(x)) if k == "model" and isinstance(x, str)
                        else clean(x, hide_source and k not in user_fields))
                    for k, x in v.items() if str(k).lower() not in hidden_fields}
        if isinstance(v, (list, tuple)):
            return [clean(x, hide_source) for x in v]
        if isinstance(v, str):
            for secret in secrets:
                if secret:
                    for form in (secret, quote(secret, safe=""), json.dumps(secret)[1:-1]):
                        v = v.replace(form, "[凭据已隐藏]")
            v = re.sub(r"(?i)(Bearer\s+)\S+", r"\1[凭据已隐藏]", v)
            if hide_source:
                v = re.sub(r'https?://[^\s<>"\']+', '[服务链接]', v, flags=re.I)
                for name in sorted(private_names, key=len, reverse=True):
                    if name:
                        pattern = (r"(?<![a-zA-Z0-9])" + re.escape(name) + r"(?![a-zA-Z0-9])"
                                   if name.isascii() else re.escape(name))
                        v = re.sub(pattern, "Respect", v, flags=re.I)
                v = v.replace("服务商", "服务").replace("联系管理员", "联系 Respect 支持")
        return v
    return clean(value)
