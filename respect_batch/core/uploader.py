# -*- coding: utf-8 -*-
"""本地文件 → 公网 URL（走你自己的对象存储，R2 / OSS / COS / S3 / MinIO 都是这一套）。

只有这一条通道，故意不做别的兜底：
  · 服务商自带的上传端点跨站不通（各家只认自己签发的 key），而且要靠 404/401
    才能发现某家没有这个端点 —— 几百段视频光探测就白发上千次请求。
  · data URI 只有部分家接受，而且请求体会膨胀到几 MB。

配好对象存储之后，参考图统一传上去换链接：URL-only 的接口能用了，
能吃 data URI 的那些家请求体也从几 MB 缩成一行链接。

按内容哈希缓存并持久化 —— 这不是优化是必需：40 集 466 段视频接近 900 次上传，
但参考的是反复出现的那几十张资产图，缓存后同一张全剧只传一次。
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import threading
import time
from typing import Callable, Optional

from . import distribution, paths
from .apiutil import ApiError, TASK_FATAL, encode_ref
from .store import LOCK, read_json, write_json

CACHE_NAME = "upload_cache.json"
_MEM: dict = {}
_MEM_LOCK = threading.RLock()
_PROVIDER_UPLOADS: dict = {}

# 配置写错了重试多少次都一样，别浪费时间。
# endpoint 打错的典型表现是 SSL 握手失败 / 域名解析不了，也算配置问题。
_FATAL_WORDS = ("NoSuchBucket", "InvalidAccessKeyId", "SignatureDoesNotMatch",
                "AccessDenied", "AllAccessDisabled", "InvalidBucketName",
                "Could not connect to the endpoint", "EndpointConnectionError",
                "InvalidArgument", "NoSuchKey",
                "SSL validation failed", "SSLError", "Name or service not known",
                "getaddrinfo failed", "nodename nor servname")


def configured(cfg: Optional[dict]) -> bool:
    cfg = cfg or {}
    if cfg.get("backend") == "aicopy":
        return bool(cfg.get("api_key"))
    return bool((cfg.get("bucket") or "").strip()
                and (cfg.get("access_key") or "").strip()
                and (cfg.get("secret_key") or "").strip())


# ---------------------------------------------------------------- 缓存
def _sha(path: str, max_side: int, fmt: str = "") -> str:
    """按文件内容 + 处理参数算 key。参数变了就要重新上传。

    `fmt` 必须进 key。不进的话，改成「默认原样发」之后，同一张图会命中
    上一次那条 JPEG 的缓存 URL —— 于是设置改了、日志说「原样」、
    服务商拿到的还是那张压过的旧图。一处都不报错。
    """
    h = hashlib.sha256()
    h.update(f"{max_side}|{fmt}|".encode())
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:32]


def _cache_path(project_root: str = "") -> str:
    """缓存放**数据目录**，不跟着输出目录走。

    原来是 `<项目>/07_检查与记录/upload_cache.json` —— 那是 studio 的目录结构。
    这个程序没有"项目"，每次跑批的输出目录还可能不一样；跟着输出目录走的话，
    同一张参考图换个输出目录就重传一次，40 集那种量级白发几百次请求。
    """
    return os.path.join(project_root or paths.data_dir(), CACHE_NAME)


def _cache_get(project_root: str, key: str) -> str:
    with _MEM_LOCK:
        if key in _MEM:
            return _MEM[key]
    if distribution.ENABLED:
        return ""
    url = (read_json(_cache_path(project_root), {}) or {}).get(key, "")
    if url:
        with _MEM_LOCK:
            _MEM[key] = url
    return url


def _cache_put(project_root: str, key: str, url: str) -> None:
    with _MEM_LOCK:
        _MEM[key] = url
    if distribution.ENABLED:
        return
    with LOCK:                      # 读-改-写整段加锁，多线程同时上传时不互相覆盖
        p = _cache_path(project_root)
        d = read_json(p, {}) or {}
        d[key] = url
        write_json(p, d)


# ---------------------------------------------------------------- 上传
def _client(cfg: dict):
    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except ImportError:
        raise ApiError("要用对象存储得先装 boto3：pip install boto3，装完重启程序",
                       kind=TASK_FATAL)
    return boto3.client(
        "s3",
        endpoint_url=(cfg.get("endpoint") or "").strip() or None,
        region_name=(cfg.get("region") or "auto").strip(),
        aws_access_key_id=(cfg.get("access_key") or "").strip(),
        aws_secret_access_key=(cfg.get("secret_key") or "").strip(),
        config=BotoConfig(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def public_url(cfg: dict, key: str) -> str:
    """拼公网访问地址。

    强烈建议填 public_base_url：R2 的 *.r2.cloudflarestorage.com 是 S3 API 域名，
    **不对外公开**，拿它拼出来的链接服务商取不到图。要填 R2 的公开域名
    （自定义域，或 pub-xxx.r2.dev）。
    """
    base = (cfg.get("public_base_url") or "").strip().rstrip("/")
    if base:
        return f"{base}/{key}"
    ep = (cfg.get("endpoint") or "").strip().rstrip("/")
    bucket = (cfg.get("bucket") or "").strip()
    if ep:
        return f"{ep}/{bucket}/{key}"
    return f"https://{bucket}.s3.amazonaws.com/{key}"


def put(cfg: dict, data: bytes, key: str) -> str:
    """上传一份字节，返回公网 URL。"""
    bucket = (cfg.get("bucket") or "").strip()
    if not bucket:
        raise ApiError("对象存储没填 bucket（设置 → 参考图上传）", kind=TASK_FATAL)
    extra = {"ContentType": mimetypes.guess_type(key)[0] or "application/octet-stream"}
    if cfg.get("public_acl"):            # R2 不支持 ACL，默认关；靠公开桶+公开域名
        extra["ACL"] = "public-read"
    try:
        _client(cfg).put_object(Bucket=bucket, Key=key, Body=data, **extra)
    except ApiError:
        raise
    except Exception as exc:             # noqa: BLE001
        msg = str(exc)
        raise ApiError(f"上传到对象存储失败：{msg}",
                       kind=TASK_FATAL if any(w in msg for w in _FATAL_WORDS) else "") from exc
    return public_url(cfg, key)


def _aicopy_url(path: str, cfg: dict, max_side: int, fmt: str, log: Callable) -> str:
    """小裴专用图床；固定地址，且只使用小裴自己的凭据。"""
    import requests
    from .apiutil import classify
    token = cfg.get("api_key", "")
    if not token:
        raise ApiError("小裴图片上传尚未配置，请联系管理员", kind=TASK_FATAL)
    data, mime, ext, _ = encode_ref(path, max_side=max_side, fmt=fmt)
    if len(data) > 15 * 1024 * 1024:
        raise ApiError("小裴图床单张图片上限为 15MB，请缩小图片后导入", kind=TASK_FATAL)
    cache_key = hashlib.sha256(token.encode() + data).hexdigest()
    with _MEM_LOCK:
        old = _PROVIDER_UPLOADS.get(cache_key)
        if old and time.monotonic() - old[0] < 900:
            return old[1]
    session = requests.Session()
    session.trust_env = False
    try:
        for endpoint in ("/v1/uploads", "/v1/upload"):
            response = session.post("https://api.aione.help" + endpoint,
                headers={"Authorization": "Bearer " + token},
                files={"image": ("reference" + ext, data, mime)}, timeout=120,
                allow_redirects=False)
            if response.status_code in (404, 405) and endpoint == "/v1/uploads":
                continue
            if not 200 <= response.status_code < 300:
                raise ApiError(f"小裴图片上传失败（HTTP {response.status_code}）",
                    response.status_code, classify(response.status_code, response.text[:400]))
            payload = response.json()
            if not isinstance(payload, dict):
                break
            for item in (payload, payload.get("data", {})):
                if not isinstance(item, dict):
                    continue
                values = [item.get(k) for k in ("image_url", "url", "file_url", "download_url")]
                for key in ("image_urls", "urls"):
                    if isinstance(item.get(key), list):
                        values.extend(item[key])
                url = next((v for v in values if isinstance(v, str) and v.startswith("https://")), "")
                if url:
                    with _MEM_LOCK:
                        _PROVIDER_UPLOADS[cache_key] = (time.monotonic(), url)
                    log(f"参考图上传完成：{os.path.basename(path)}")
                    return url
            break
    except requests.RequestException as exc:
        raise ApiError("小裴图片上传网络失败，请稍后重试") from exc
    finally:
        session.close()
    raise ApiError("小裴图片上传未返回可用的 HTTPS 链接", kind=TASK_FATAL)


def to_url(path: str, cfg: dict, *, project_root: str = "", max_side: int = 0,
           fmt: str = "", log: Callable = print) -> str:
    """本地图片 → 公网 URL。命中缓存就不重复上传。

    `max_side=0` 且 `fmt` 为空（默认）= **原样上传，一个字节都不改**。
    只有这一家自己声明了要求才会重编码，见 `produce._ref_rules`。
    """
    if not os.path.isfile(path):
        raise ApiError(f"参考图文件不存在: {path}")
    if cfg.get("backend") == "aicopy":
        return _aicopy_url(path, cfg, max_side, fmt, log)
    if not configured(cfg):
        raise ApiError(
            "这个模型的参考图**只收公网链接**，但还没配对象存储，本机的图传不上去。"
            "去「设置 → 参考图上传」填 R2（或 OSS/COS/MinIO）的 endpoint、bucket、"
            "密钥和公开访问域名；或者换一家能直接吃图片内容的服务商。\n"
            "（这一条宁可现在停下：把 data URI 发给只收链接的接口不会报错，"
            "参考图会被悄悄丢掉照样出图 —— 图在、人不对，几百张里靠肉眼发现。）",
            kind=TASK_FATAL)

    h = _sha(path, max_side, fmt)
    hit = _cache_get(project_root, h)
    if hit:
        return hit

    # **默认原样传。** 原来这里无条件压成 JPEG，理由写的是「省流量、
    # 避开各家对 png 透明通道的处理差异」—— 但那是拿画质换的，而且
    # 没人选过：参考图是喂给模型的身份和构图来源。
    data, _mime, ext, how = encode_ref(path, max_side=max_side, fmt=fmt)
    prefix = (cfg.get("prefix") or "respect").strip().strip("/")
    # 扩展名跟着**实际发出去的那份**走，不再写死 .jpg。
    # 写死的话对象是 PNG 内容却叫 .jpg —— 多数服务商按 Content-Type 走
    # 不受影响，但按扩展名判断的那几家会读不了，而那时报的是「图片无效」。
    name = f"{os.path.splitext(os.path.basename(path))[0]}_{h[:12]}{ext}"
    key = f"{prefix}/{name}" if prefix else name

    # put() 按 key 的扩展名猜 ContentType —— 上面扩展名跟着实际内容走了，
    # 所以这里不用另传一份，两处不会再对不上。
    url = put(cfg, data, key)
    # **改没改要说出来。** 原来只写「已上传（57KB）」，而那时它其实被缩到了
    # 682x1024。出来的脸不像时，日志里得有这一行，否则谁都不会想到问题在这儿。
    message = f"已上传 {os.path.basename(path)}　{how}　{len(data)//1024}KB"
    log(message if distribution.ENABLED else f"{message} → {url}")
    _cache_put(project_root, h, url)
    return url


# ---------------------------------------------------------------- 自检
def selftest(cfg: dict, log: Callable = print) -> dict:
    """传一个小文件再用普通 HTTP 取回来，确认**服务商真的能读到**。

    只测「上传成功」是不够的：最常见的坑是桶不公开、或 public_base_url 填了
    R2 的 S3 API 域名（那个域名不对外）。上传都会成功，但服务商取图 403，
    到时候是一批任务失败，不如现在花两秒测出来。
    """
    if not configured(cfg):
        return {"ok": False, "step": "配置", "msg": "bucket / access_key / secret_key 没填全"}
    payload = b"respect-studio-uploader-selftest"
    prefix = (cfg.get("prefix") or "respect").strip().strip("/")
    key = f"{prefix}/_selftest.txt" if prefix else "_selftest.txt"
    try:
        url = put(cfg, payload, key)
    except ApiError as exc:
        return {"ok": False, "step": "上传", "msg": str(exc)}

    try:
        import requests
        r = requests.get(url, timeout=20)
    except Exception as exc:            # noqa: BLE001
        return {"ok": False, "step": "读回", "url": url,
                "msg": f"上传成功但链接打不开：{exc}。"
                       f"检查「公开访问域名」填得对不对。"}
    if r.status_code != 200:
        return {"ok": False, "step": "读回", "url": url,
                "msg": f"上传成功，但公开访问返回 {r.status_code}。"
                       f"要么桶没开公开读，要么「公开访问域名」填错了 —— "
                       f"R2 别填 *.r2.cloudflarestorage.com（那是 S3 API 域名，不对外），"
                       f"要填自定义域或 pub-xxx.r2.dev。"}
    if r.content.strip() != payload:
        return {"ok": False, "step": "读回", "url": url,
                "msg": "链接能打开但内容不对，可能是域名指到了别的桶"}
    return {"ok": True, "step": "完成", "url": url,
            "msg": "上传和公开读取都正常，可以开工"}


def cache_stats(project_root: str) -> dict:
    return {"cached": len(read_json(_cache_path(project_root), {}) or {})}
