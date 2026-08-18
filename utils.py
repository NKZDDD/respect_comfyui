"""Respect ComfyUI 扩展 - 通用工具模块

封装中转 API (api.aicopy.top) 的 HTTP 调用、图片与视频的读写、
以及 ComfyUI IMAGE tensor 的相互转换。
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

import numpy as np
import requests
import torch
from PIL import Image

try:
    import folder_paths  # type: ignore
except Exception:  # pragma: no cover - ComfyUI 运行环境之外
    folder_paths = None


DEFAULT_BASE_URL = "https://api.aicopy.top"
DEFAULT_TIMEOUT = 600
DEFAULT_USER_AGENT = "RespectComfyUI/1.0"
# Seedance / grok-video 等的参考图公网上传地址（源码写死为 api.aione.help，可在设置节点覆盖）
DEFAULT_UPLOAD_BASE = "https://api.aione.help"


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass
class RespectConfig:
    """中转 API 配置。"""

    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    timeout: int = DEFAULT_TIMEOUT
    proxy: str = ""
    upload_base_url: str = ""
    extra_headers: dict = field(default_factory=dict)

    def normalized_base(self) -> str:
        base = (self.base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        if not base:
            base = DEFAULT_BASE_URL
        if not base.endswith("/v1"):
            base = base + "/v1"
        return base

    def resolve_upload_base(self) -> str:
        """参考图公网上传的基址（默认 api.aione.help）。"""
        return (self.upload_base_url or "").strip().rstrip("/") or DEFAULT_UPLOAD_BASE

    def headers(self, content_type: str = "application/json") -> dict:
        hdrs = {
            "Authorization": f"Bearer {self.resolve_api_key()}",
            "Accept": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        }
        if content_type:
            hdrs["Content-Type"] = content_type
        hdrs.update(self.extra_headers or {})
        return hdrs

    def resolve_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        env = os.environ.get("RESPECT_API_KEY") or os.environ.get("AICOPY_API_KEY")
        return env or ""

    def proxies(self) -> Optional[dict]:
        if not self.proxy:
            return None
        return {"http": self.proxy, "https": self.proxy}


def ensure_config(cfg: Any) -> RespectConfig:
    """允许 API_CONFIG 输入是 dict 或 RespectConfig。"""
    if isinstance(cfg, RespectConfig):
        return cfg
    if isinstance(cfg, dict):
        return RespectConfig(
            api_key=str(cfg.get("api_key", "")),
            base_url=str(cfg.get("base_url", DEFAULT_BASE_URL)),
            timeout=int(cfg.get("timeout", DEFAULT_TIMEOUT)),
            proxy=str(cfg.get("proxy", "")),
            upload_base_url=str(cfg.get("upload_base_url", "")),
            extra_headers=dict(cfg.get("extra_headers", {}) or {}),
        )
    raise ValueError("无效的 API 配置，请连接 Respect API Settings 节点")


# ---------------------------------------------------------------------------
# 图片 <-> ComfyUI tensor 互转
# ---------------------------------------------------------------------------


def pil_to_tensor(img: Image.Image) -> torch.Tensor:
    """PIL Image -> ComfyUI IMAGE tensor [1, H, W, C] float32 0-1."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    arr = np.asarray(img, dtype=np.float32) / 255.0
    return torch.from_numpy(arr).unsqueeze(0)


def tensor_to_pil(tensor: torch.Tensor) -> list[Image.Image]:
    """ComfyUI IMAGE tensor -> 列表 PIL Image。"""
    if tensor is None:
        return []
    if tensor.ndim == 3:
        tensor = tensor.unsqueeze(0)
    images: list[Image.Image] = []
    for i in range(tensor.shape[0]):
        arr = (tensor[i].detach().cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
        images.append(Image.fromarray(arr))
    return images


def tensor_to_b64(tensor: torch.Tensor, fmt: str = "JPEG", quality: int = 90, max_side: int = 1536) -> list[str]:
    """ComfyUI IMAGE -> base64 data URL 列表，自动压缩。"""
    results: list[str] = []
    for pil in tensor_to_pil(tensor):
        if max_side > 0:
            w, h = pil.size
            long_side = max(w, h)
            if long_side > max_side:
                scale = max_side / float(long_side)
                pil = pil.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        save_fmt = fmt.upper()
        if save_fmt == "JPEG" and pil.mode != "RGB":
            pil = pil.convert("RGB")
        pil.save(buf, format=save_fmt, quality=quality)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        mime = "image/jpeg" if save_fmt == "JPEG" else f"image/{save_fmt.lower()}"
        results.append(f"data:{mime};base64,{b64}")
    return results


def dynamic_image_inputs(kwargs: dict, prefix: str = "image_") -> list:
    """取出动态输入口接进来的 IMAGE，按 `image_1, image_2, … image_10` 的**数字顺序**排列。

    配合前端 `web/respect_dynamic_ports.js` 的「更新输入口」按钮使用：
    节点只声明少量 `image_N`，多出来的槽由前端加，后端从 **kwargs 里动态取。
    """
    n = len(prefix)
    keys = sorted(
        (k for k in kwargs if k.startswith(prefix) and k[n:].isdigit()),
        key=lambda k: int(k[n:]),
    )
    out = []
    for k in keys:
        t = kwargs.get(k)
        if t is None or (hasattr(t, "numel") and t.numel() == 0):
            continue
        out.append(t)
    return out


def dynamic_url_inputs(kwargs: dict, prefix: str = "ref_url_") -> list:
    """取出动态输入口填/接进来的 URL，按 `ref_url_1, ref_url_2 … ref_url_10` 的数字顺序。

    和 `dynamic_image_inputs` 是一对：那个给吃图片内容的接口用，这个给**只收公网 URL**
    的接口用（接「对象存储上传」的 url 输出）。数量由 `inputcount` + 前端
    `web/respect_dynamic_ports.js` 的「更新输入口」按钮决定。
    """
    n = len(prefix)
    keys = sorted(
        (k for k in kwargs if k.startswith(prefix) and k[n:].isdigit()),
        key=lambda k: int(k[n:]),
    )
    out = []
    for k in keys:
        v = kwargs.get(k)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    return out


def expand_image_frames(tensors: list) -> list:
    """把每个 IMAGE 批次拆成单帧列表（角色库/ZIP 一次给多张时，每张都要当参考图）。"""
    frames = []
    for t in tensors:
        if t is None or (hasattr(t, "numel") and t.numel() == 0):
            continue
        count = t.shape[0] if getattr(t, "ndim", 3) == 4 else 1
        for i in range(count):
            frames.append(t[i:i + 1])
    return frames


def bytes_to_tensor(content: bytes) -> torch.Tensor:
    """字节 → tensor。**不做「截断图救回」** —— 缺角的图等于废图，宁可报错。"""
    return pil_to_tensor(Image.open(io.BytesIO(content)))


def b64_decode_loose(data: str) -> bytes:
    """宽松解 base64。

    中转网关返回的 b64 经常不规矩，`base64.b64decode` 严格模式会直接抛：
      · **尾部 `=` 被剥掉** —— 最常见，报 "Incorrect padding" 或
        "number of data characters cannot be 1 more than a multiple of 4"
      · 塞了换行/空格（有的网关按 76 字符折行）
      · 用了 base64url 的 `-_` 而不是 `+/`
    这三种数据其实都是完好的图，没理由让它们失败。
    """
    s = re.sub(r"\s+", "", data or "")
    if "-" in s or "_" in s:
        s = s.replace("-", "+").replace("_", "/")
    pad = (-len(s)) % 4
    if pad:
        s += "=" * pad
    return base64.b64decode(s)


def b64_to_tensor(data: str) -> torch.Tensor:
    if data.startswith("data:"):
        data = data.split(",", 1)[1]
    return bytes_to_tensor(b64_decode_loose(data))


def url_to_tensor(url: str, cfg: RespectConfig) -> torch.Tensor:
    # 只对中转 API 自己的域名带 Bearer token；S3 / CloudFront 预签名 URL 不能
    # 同时带 Authorization 头, 否则 AWS 会返回 400 Bad Request。
    low = url.lower()
    is_api = ("aicopy" in low) or ("/v1/" in low)
    headers = {"Authorization": f"Bearer {cfg.resolve_api_key()}"} if is_api else {}
    resp = requests.get(
        url,
        headers=headers,
        timeout=cfg.timeout,
        proxies=cfg.proxies(),
        stream=True,
    )
    resp.raise_for_status()
    return bytes_to_tensor(resp.content)


def tensors_concat(tensors: Sequence[torch.Tensor]) -> torch.Tensor:
    """把多个尺寸不同的 IMAGE tensor 统一到第一张尺寸后再 batch 拼接。"""
    valid = [t for t in tensors if t is not None and t.numel() > 0]
    if not valid:
        return torch.zeros((1, 64, 64, 3), dtype=torch.float32)
    target_h, target_w = valid[0].shape[1], valid[0].shape[2]
    out: list[torch.Tensor] = []
    for t in valid:
        if t.ndim == 3:
            t = t.unsqueeze(0)
        if t.shape[1] != target_h or t.shape[2] != target_w:
            pil_list = tensor_to_pil(t)
            resized = [pil.resize((target_w, target_h), Image.LANCZOS) for pil in pil_list]
            t = torch.cat([pil_to_tensor(p) for p in resized], dim=0)
        out.append(t)
    return torch.cat(out, dim=0)


# ---------------------------------------------------------------------------
# 提取响应中的图片 / 视频地址
# ---------------------------------------------------------------------------


_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_MD_IMG_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")
_REL_PATH_RE = re.compile(r"/v1/[A-Za-z0-9_./\-]+")
# ⚠ 字符类要覆盖全：base64url 用 `-_`，有的网关还按 76 字符折行。
# 少写一个字符，正则就会在那里**停下**，把后面的图数据全丢掉 ——
# 结果是一串看着很正常、其实缺了尾巴的 base64，PIL 报 "image file is truncated"，
# 而真正的元凶是这行正则，不是网关。
_DATA_IMG_RE = re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=_\-\s]+")
_HTML_MEDIA_RE = re.compile(
    r"<(?:video|source|audio)[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_HTML_IMG_RE = re.compile(
    r"<img[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".m4v", ".mkv", ".gif")


def extract_image_payloads(payload: Any) -> list[str]:
    """从任意响应结构中递归提取图片资源 (URL 或 data:image base64)。"""
    found: list[str] = []

    def walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, str):
            for m in _MD_IMG_RE.finditer(node):
                found.append(m.group(1))
            for m in _DATA_IMG_RE.finditer(node):
                found.append(m.group(0))
            for m in _URL_RE.finditer(node):
                url = m.group(0).rstrip(").,，。；;\"'>")
                if any(url.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
                    found.append(url)
                elif "image" in url.lower() or "/v1/files" in url.lower():
                    found.append(url)
            for m in _REL_PATH_RE.finditer(node):
                found.append(m.group(0))
            return
        if isinstance(node, dict):
            for key in ("url", "image_url", "b64_json", "image_b64", "result", "image"):
                val = node.get(key)
                if isinstance(val, str) and val:
                    if key in ("b64_json", "image_b64"):
                        if not val.startswith("data:"):
                            val = f"data:image/png;base64,{val}"
                        found.append(val)
                    elif key == "image_url" and isinstance(node.get(key), dict):
                        pass
                    else:
                        found.append(val)
                elif isinstance(val, dict):
                    walk(val)
                elif isinstance(val, list):
                    walk(val)
            for key in ("text", "content", "output_text"):
                val = node.get(key)
                if isinstance(val, str):
                    walk(val)
                elif isinstance(val, list):
                    walk(val)
            for k, v in node.items():
                if k in ("url", "image_url", "b64_json", "image_b64", "result", "image", "text", "content", "output_text"):
                    continue
                walk(v)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return _dedup_preserve(found)


def extract_data_array_images(payload: Any) -> list[str]:
    """严格按 OpenAI 风格的 `data[]` 取图：**一个元素 = 一张图**。

    为什么不能只用 `extract_image_payloads`：那个是递归乱扫的兜底解析器，
    专门对付各家五花八门的响应结构。代价是**同一张图会被数成多张** ——
    最典型的是网关同时给了 `url` 和 `b64_json`（4K 模型常见），
    两个字符串不相等，去重也去不掉，于是 1 张图变 2 张：
    IMAGE 批次里出现重复画面，数量统计也是错的。

    所以响应是规范的 `{"data": [{...}, ...]}` 时优先用这个；
    取不到再退回 `extract_image_payloads`。
    """
    if not isinstance(payload, dict):
        return []
    arr = payload.get("data")
    if not isinstance(arr, list) or not arr:
        return []
    out: list[str] = []
    for item in arr:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        # 一个元素只取一张：url 优先（省流量），没有再用 base64
        url = item.get("url") or item.get("image_url")
        if isinstance(url, dict):
            url = url.get("url")
        if isinstance(url, str) and url.strip():
            out.append(url.strip())
            continue
        b64 = item.get("b64_json") or item.get("image_b64")
        if isinstance(b64, str) and b64.strip():
            out.append(b64 if b64.startswith("data:") else f"data:image/png;base64,{b64}")
    return _dedup_preserve(out)


def extract_video_urls(payload: Any) -> list[str]:
    """从响应中提取视频地址。

    优先级：
    1. HTML <video src='...'> / <source src='...'>
    2. URL 路径或查询去掉后以 .mp4/.mov/.webm/.m4v/.mkv 结尾
    3. URL 里含 video / videos / firefly / pre-signed 等关键字
    4. Markdown 视频链接 `![text](url.mp4)`
    """
    text_blob = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    urls: list[str] = []

    for m in _HTML_MEDIA_RE.finditer(text_blob):
        urls.append(m.group(1))

    img_hits = {m.group(1) for m in _HTML_IMG_RE.finditer(text_blob)}

    for m in _URL_RE.finditer(text_blob):
        url = m.group(0).rstrip(").,，。；;\"'>]")
        low = url.lower()
        path = low.split("?", 1)[0]
        is_video_ext = any(path.endswith(ext) for ext in _VIDEO_EXTS)
        looks_like_video = (
            "/video" in low
            or "/v1/videos/" in low
            or "firefly" in low
            or "pre-signed" in low
            or "x-resource-length" in low
        )
        if is_video_ext:
            urls.append(url)
        elif looks_like_video and url not in img_hits:
            urls.append(url)

    return _dedup_preserve(urls)


def _dedup_preserve(items: Iterable[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _dump_bad_image(raw: bytes, why: str) -> str:
    """把解不开的原始字节落盘，方便直接拿去验尸。返回路径。"""
    try:
        base = _output_dir("respect/_bad_image")
        path = os.path.join(base, f"{why}_{int(time.time())}_{uuid.uuid4().hex[:6]}.bin")
        with open(path, "wb") as fh:
            fh.write(raw)
        return path
    except Exception:                                       # noqa: BLE001
        return ""


def _b64_diag(item: str, exc: Exception) -> str:
    """解不出图时给**确定性**结论，而不是"多半是…"。

    判据是文件格式自己的结束标记：PNG 必须以 IEND 块收尾、JPEG 必须以 FFD9 收尾。
    结束标记在 = 数据完整（那 PIL 打不开就另有原因）；不在 = 真的被截断了，
    而且能算出缺了多少。
    """
    payload = item.split(",", 1)[1] if item.startswith("data:") else item
    clean = re.sub(r"\s+", "", payload)
    try:
        raw = b64_decode_loose(payload)
    except Exception as dec:                                # noqa: BLE001
        return (f"base64 长度={len(clean)}（%4={len(clean) % 4}），**解码阶段就失败**（{dec}）。"
                f"→ 拿到的 base64 本身就是残的")

    head, tail = raw[:8], raw[-16:]
    kb = f"{len(raw) / 1024:.0f}KB"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        if b"IEND" in tail:
            return (f"PNG {kb}，**IEND 结束块在，数据是完整的** —— 那 PIL 打不开就不是截断问题："
                    f"{exc}。原始字节已存：{_dump_bad_image(raw, 'png_complete') or '存盘失败'}")
        return (f"PNG {kb}，**结尾没有 IEND 块 → 确认被截断**（尾部字节 {tail[-8:]!r}）。"
                f"图在网关那边就没传完，不是本插件的解析问题。"
                f"原始字节已存：{_dump_bad_image(raw, 'png_truncated') or '存盘失败'}")
    if head.startswith(b"\xff\xd8\xff"):
        if raw.endswith(b"\xff\xd9"):
            return f"JPEG {kb}，结束标记 FFD9 在，数据完整 —— PIL 报：{exc}"
        return (f"JPEG {kb}，**结尾没有 FFD9 → 确认被截断**。"
                f"原始字节已存：{_dump_bad_image(raw, 'jpeg_truncated') or '存盘失败'}")
    known = {b"RIFF": "WEBP", b"GIF8": "GIF"}
    fmt = next((v for k, v in known.items() if head.startswith(k)), "")
    if fmt:
        return f"{fmt} {kb}，PIL 报：{exc}"
    txt = raw[:200].decode("utf-8", "replace")
    return (f"{kb}，**开头不是任何图片格式**（{head!r}）→ 这根本不是图片，"
            f"网关很可能把错误信息塞进了 b64 字段。内容开头：{txt[:150]}")


def resolve_image_to_tensor(item: str, cfg: RespectConfig) -> Optional[torch.Tensor]:
    """图片资源字符串 -> tensor。"""
    try:
        if item.startswith("data:"):
            return b64_to_tensor(item)
        if item.startswith("/v1/"):
            item = cfg.normalized_base().rsplit("/v1", 1)[0] + item
        if item.startswith("http://") or item.startswith("https://"):
            return url_to_tensor(item, cfg)
        if len(item) > 200 and re.match(r"^[A-Za-z0-9+/=\s_-]+$", item):
            return b64_to_tensor(item)
    except Exception as exc:  # pragma: no cover - 仅记录失败
        if item.startswith("data:") or not item.startswith("http"):
            print(f"[Respect] 图片解析失败：{_b64_diag(item, exc)}")
        else:
            print(f"[Respect] 图片下载失败: {item[:120]}… err={exc}")
    return None


# ---------------------------------------------------------------------------
# HTTP 调用
# ---------------------------------------------------------------------------


class RespectAPIError(RuntimeError):
    def __init__(self, message: str, status: int = 0, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def _force_utf8(resp: requests.Response) -> None:
    """中转 API 默认返回 UTF-8, 但 Content-Type 经常没带 charset,
    requests 会按 ISO-8859-1 解码导致中文消息乱码。这里强制 utf-8。"""
    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "latin-1"):
        resp.encoding = "utf-8"


def _format_error(resp: requests.Response) -> str:
    _force_utf8(resp)
    try:
        data = resp.json()
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict) and err.get("message"):
            return f"HTTP {resp.status_code}: {err['message']}"
        if isinstance(err, str):
            return f"HTTP {resp.status_code}: {err}"
        return f"HTTP {resp.status_code}: {json.dumps(data, ensure_ascii=False)[:500]}"
    except Exception:
        return f"HTTP {resp.status_code}: {resp.text[:500]}"


# ---------------------------------------------------------------------------
# 请求日志：把真正发出去的 body 打到控制台
#
# 各家网关的字段形状差别极大（seconds 是字符串还是整数、参考图是 images[] 还是
# content 块、size 是像素还是档位…），发错**多数不会报错**，只会静默丢参数 ——
# 图照出、人不对。所以默认把创建请求的 body 原样打出来，好对着文档核。
#
# 关掉：设环境变量 RESPECT_LOG_BODY=0
# ---------------------------------------------------------------------------

_LOG_BODY = os.environ.get("RESPECT_LOG_BODY", "1").strip().lower() not in ("0", "false", "off", "no")
_LOG_MAX_STR = 200          # 单个字符串超这个长度就截断（base64 参考图动辄几 MB）
_LOG_MAX_RESP = 1500


def _sanitize_for_log(obj: Any, depth: int = 0) -> Any:
    """把 body 里的 base64 / 超长字符串换成占位符，其余原样保留。

    不这么做的话，一张参考图就能刷几千行，真正要看的字段全被顶没了。
    """
    if depth > 8:
        return "…"
    if isinstance(obj, dict):
        return {k: _sanitize_for_log(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_log(v, depth + 1) for v in obj]
    if isinstance(obj, str) and len(obj) > _LOG_MAX_STR:
        if obj.startswith("data:"):
            head = obj.split(",", 1)[0]
            return f"<{head},… {len(obj) / 1024:.0f}KB base64 已省略>"
        return obj[:_LOG_MAX_STR] + f"…<共{len(obj)}字符>"
    return obj


def _log_request(method: str, url: str, json_body: Any, files: Any, data: Any) -> None:
    """打印一次请求。只打创建类（POST/PUT/PATCH）—— GET 多半是轮询，几百次没意义。"""
    if not _LOG_BODY or method.upper() not in ("POST", "PUT", "PATCH"):
        return
    short = "/" + url.split("/", 3)[-1] if url.count("/") >= 3 else url
    print(f"[Respect] → {method.upper()} {short}")
    if json_body is not None:
        text = json.dumps(_sanitize_for_log(json_body), ensure_ascii=False, indent=2)
        print(f"[Respect]   body = {text}")
    for item in (files or []):
        # files 里两种形状：普通字段 (name, (None, 值))、文件项 (name, (文件名, 字节, 类型))
        try:
            name, payload = item
            if isinstance(payload, tuple) and payload[0] is None:
                print(f"[Respect]   {name} = {_sanitize_for_log(payload[1])}")
            elif isinstance(payload, tuple):
                blob = payload[1]
                size = f"{len(blob) / 1024:.0f} KB" if isinstance(blob, (bytes, bytearray)) else "?"
                print(f"[Respect]   {name} <- {payload[0]} ({size}, {payload[2] if len(payload) > 2 else '?'})")
        except Exception:                                   # noqa: BLE001
            print(f"[Respect]   {item}")
    if data is not None and not files:
        print(f"[Respect]   form = {_sanitize_for_log(data)}")


def _log_response(resp: requests.Response, stream: bool) -> None:
    """打印响应。stream=True 时**绝不能碰 body** —— 会把 SSE 流提前读掉。"""
    if not _LOG_BODY or stream:
        return
    try:
        _force_utf8(resp)
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "json" in ctype or resp.text.lstrip()[:1] in ("{", "["):
            body = json.dumps(_sanitize_for_log(resp.json()), ensure_ascii=False)[:_LOG_MAX_RESP]
        else:
            body = f"<{ctype or '未知类型'} {len(resp.content)} 字节>"
    except Exception:                                       # noqa: BLE001
        body = resp.text[:_LOG_MAX_RESP] if resp.content else ""
    print(f"[Respect] ← HTTP {resp.status_code} {body}")


def _assert_full_body(resp: requests.Response, stream: bool) -> None:
    """响应体没收完就当场报错，别把残缺的 JSON 往下传。

    连接中途断掉时，requests **不一定抛异常** —— `resp.content` 会是截断的，
    `resp.json()` 有时还能勉强解出来（尤其 base64 字段本来就是长字符串）。
    那样错误会一路飘到「图片解析失败」，看起来像是网关给了坏图，
    实际是本机这段网络没收完。这里拿 Content-Length 对一下，把问题钉在发生的地方。
    """
    if stream:
        return
    declared = resp.headers.get("Content-Length")
    if not declared or resp.headers.get("Transfer-Encoding", "").lower() == "chunked":
        return                                   # 分块传输没有可信长度，跳过
    try:
        want = int(declared)
    except ValueError:
        return
    got = len(resp.content)
    if got < want:
        raise RespectAPIError(
            f"响应体没收完：声明 {want} 字节，实际只收到 {got} 字节（少了 {want - got}）。\n"
            f"这是**本机到网关的连接中断**，不是网关给了坏数据 —— "
            f"查代理 / 网络稳定性，或把 timeout 调大后重试。",
            status=resp.status_code)


def api_request(
    cfg: RespectConfig,
    method: str,
    path: str,
    *,
    json_body: Any = None,
    files: Any = None,
    data: Any = None,
    params: Any = None,
    stream: bool = False,
    retries: int = 3,
    timeout: Optional[int] = None,
    headers: Optional[dict] = None,
) -> requests.Response:
    """带重试的通用请求。path 可以是 /v1/xxx 或 xxx (会自动拼接)。

    传入 `headers` 时直接使用该请求头（用于 Anthropic 的 x-api-key 等非 Bearer 场景），
    否则按 OpenAI 兼容方式自动生成 Bearer 请求头。
    """
    base = cfg.normalized_base()
    if path.startswith("/v1/"):
        url = base.rsplit("/v1", 1)[0] + path
    elif path.startswith("http"):
        url = path
    else:
        url = base + "/" + path.lstrip("/")

    if headers is None:
        headers = cfg.headers(content_type=None if files else "application/json")
        if files:
            headers.pop("Content-Type", None)

    last_exc: Optional[Exception] = None
    for attempt in range(max(1, retries)):
        # 每次重投都打，这样"到底发了几次"在日志里是明摆着的
        _log_request(method, url, json_body, files, data)
        try:
            resp = requests.request(
                method,
                url,
                headers=headers,
                json=json_body if (json_body is not None and not files) else None,
                files=files,
                data=data,
                params=params,
                timeout=timeout or cfg.timeout,
                proxies=cfg.proxies(),
                stream=stream,
            )
            _assert_full_body(resp, stream)
            if resp.status_code in (429, 502, 503, 504) and attempt < retries - 1:
                print(f"[Respect] ← HTTP {resp.status_code}，{2 ** attempt}秒后重试"
                      f"（第 {attempt + 2}/{retries} 次）")
                time.sleep(2 ** attempt)
                continue
            if method.upper() in ("POST", "PUT", "PATCH"):
                _log_response(resp, stream)
            if resp.status_code >= 400:
                raise RespectAPIError(_format_error(resp), status=resp.status_code)
            return resp
        except RespectAPIError:
            raise
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise RespectAPIError(f"网络错误: {exc}") from exc
    if last_exc:
        raise RespectAPIError(f"网络错误: {last_exc}")
    raise RespectAPIError("未知错误")


# ---------------------------------------------------------------------------
# 流式 SSE 解析 (用于 chat completions 流式视频)
# ---------------------------------------------------------------------------


def iter_sse_lines(resp: requests.Response) -> Iterable[str]:
    """逐行读取 SSE，返回 data: 后的 JSON 字符串。"""
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            yield payload


def collect_stream_text(resp: requests.Response) -> str:
    """把 SSE 流里的 delta.content 拼成完整文本。"""
    parts: list[str] = []
    for chunk in iter_sse_lines(resp):
        try:
            obj = json.loads(chunk)
        except Exception:
            continue
        try:
            delta = obj["choices"][0].get("delta") or obj["choices"][0].get("message") or {}
            content = delta.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        parts.append(item["text"])
        except Exception:
            continue
    return "".join(parts)


# ---------------------------------------------------------------------------
# 视频文件下载与保存
# ---------------------------------------------------------------------------


def _comfy_output_base() -> str:
    if folder_paths is not None:
        return folder_paths.get_output_directory()
    return os.path.join(os.getcwd(), "output")


def _output_dir(subdir: str = "respect") -> str:
    target = os.path.join(_comfy_output_base(), subdir)
    os.makedirs(target, exist_ok=True)
    return target


def _resolve_save_target(
    save_dir: str,
    filename: str,
    default_subdir: str,
    default_prefix: str,
    default_ext: str,
) -> str:
    """根据 save_dir / filename 解析最终绝对路径。

    save_dir:
        - 空：使用 ComfyUI output/<default_subdir>/
        - 绝对路径：直接使用
        - 相对路径：相对 ComfyUI output 目录
    filename:
        - 空：自动生成 `<prefix>_<timestamp>_<6hex>.<ext>`
        - 非空：直接使用；没扩展名则补 default_ext；允许包含子目录分隔符
    """
    save_dir = (save_dir or "").strip()
    filename = (filename or "").strip()

    if save_dir:
        save_dir = os.path.expanduser(os.path.expandvars(save_dir))
        if os.path.isabs(save_dir):
            target_dir = save_dir
        else:
            target_dir = os.path.join(_comfy_output_base(), save_dir)
    else:
        target_dir = _output_dir(default_subdir)

    if filename:
        filename = filename.replace("\\", "/").lstrip("/")
        if not os.path.splitext(filename)[1]:
            filename = filename + default_ext
        final_path = os.path.join(target_dir, filename)
    else:
        ts = time.strftime("%Y%m%d_%H%M%S")
        final_name = f"{default_prefix}_{ts}_{uuid.uuid4().hex[:6]}{default_ext}"
        final_path = os.path.join(target_dir, final_name)

    os.makedirs(os.path.dirname(final_path), exist_ok=True)
    return final_path


def download_to_output(
    url: str,
    cfg: RespectConfig,
    prefix: str = "respect",
    ext: str = ".mp4",
    subdir: str = "respect",
    save_dir: str = "",
    filename: str = "",
) -> str:
    """下载视频/文件到 ComfyUI output 目录，返回本地绝对路径。

    `save_dir` / `filename` 不空时优先按用户指定的目录与文件名保存；
    扩展名优先级：filename 自带 > url 推测 > 传入的 ext。
    传入的是本地已存在文件时，直接复制到目标（供保存/改名本地视频用）。
    """
    # 本地文件：复制而非下载（filename 无扩展名时补 .mp4）
    if os.path.isfile(url):
        import shutil
        src_ext = os.path.splitext(url)[1] or ext
        if not src_ext.startswith("."):
            src_ext = "." + src_ext
        out_path = _resolve_save_target(
            save_dir=save_dir, filename=filename,
            default_subdir=subdir, default_prefix=prefix, default_ext=src_ext,
        )
        if os.path.abspath(out_path) != os.path.abspath(url):
            shutil.copy2(url, out_path)
        return out_path

    if url.startswith("/v1/"):
        url = cfg.normalized_base().rsplit("/v1", 1)[0] + url

    headers = {"Authorization": f"Bearer {cfg.resolve_api_key()}"} if "aicopy" in url or "/v1/" in url else {}
    resp = requests.get(url, headers=headers, timeout=cfg.timeout, proxies=cfg.proxies(), stream=True)
    resp.raise_for_status()

    if not ext.startswith("."):
        ext = "." + ext
    last_seg = url.split("?")[0].split("/")[-1]
    if "." in last_seg:
        guessed = "." + last_seg.split(".")[-1].lower()
        if len(guessed) <= 6 and guessed.replace(".", "").isalnum():
            ext = guessed

    out_path = _resolve_save_target(
        save_dir=save_dir,
        filename=filename,
        default_subdir=subdir,
        default_prefix=prefix,
        default_ext=ext,
    )

    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if chunk:
                f.write(chunk)
    return out_path


# ---------------------------------------------------------------------------
# 内置尺寸表 (来自 文档 §8)
# ---------------------------------------------------------------------------


RESOLUTION_TABLE: dict[str, dict[str, str]] = {
    "1k": {
        "1:1": "1024x1024", "16:9": "1536x864", "9:16": "864x1536", "4:3": "1365x1024",
        "3:4": "1024x1365", "3:2": "1536x1024", "2:3": "1024x1536", "4:5": "1024x1280",
        "5:4": "1280x1024", "21:9": "1792x768",
    },
    "2k": {
        "1:1": "2048x2048", "16:9": "3072x1728", "9:16": "1728x3072", "4:3": "2730x2048",
        "3:4": "2048x2730", "3:2": "3072x2048", "2:3": "2048x3072", "4:5": "2048x2560",
        "5:4": "2560x2048", "21:9": "3584x1536",
    },
    "4k": {
        "1:1": "3840x3840", "16:9": "3840x2160", "9:16": "2160x3840", "4:3": "3840x2880",
        "3:4": "2880x3840", "3:2": "3840x2560", "2:3": "2560x3840", "4:5": "3072x3840",
        "5:4": "3840x3072", "21:9": "3840x1646",
    },
}

# nano-banana2 额外支持的超宽/超长比例（firefly model_id 已自带尺寸，这里仅为下拉可选 + lookup_size 兜底）
for _res, _long in (("1k", 1024), ("2k", 2048), ("4k", 4096)):
    RESOLUTION_TABLE[_res].update({
        "8:1": f"{_long}x{max(16, _long // 8)}",
        "1:4": f"{max(16, _long // 4)}x{_long}",
        "1:8": f"{max(16, _long // 8)}x{_long}",
    })

ASPECT_RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5", "5:4", "21:9", "8:1", "1:4", "1:8"]
RESOLUTIONS = ["1k", "2k", "4k"]


def lookup_size(resolution: str, aspect: str) -> str:
    return RESOLUTION_TABLE.get(resolution, {}).get(aspect, "1024x1024")


def model_has_size(model: str) -> bool:
    low = (model or "").lower()
    if re.search(r"\b\d+x\d+\b", low):
        return True
    if re.search(r"-(1k|2k|4k)(-|$)", low):
        return True
    return False


def aspect_to_x(aspect: str) -> str:
    """1:1 -> 1x1，用于拼接模型 ID。"""
    return aspect.replace(":", "x")
