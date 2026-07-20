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
    extra_headers: dict = field(default_factory=dict)

    def normalized_base(self) -> str:
        base = (self.base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        if not base:
            base = DEFAULT_BASE_URL
        if not base.endswith("/v1"):
            base = base + "/v1"
        return base

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


def bytes_to_tensor(content: bytes) -> torch.Tensor:
    return pil_to_tensor(Image.open(io.BytesIO(content)))


def b64_to_tensor(data: str) -> torch.Tensor:
    if data.startswith("data:"):
        data = data.split(",", 1)[1]
    return bytes_to_tensor(base64.b64decode(data))


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
_DATA_IMG_RE = re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+")
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


def resolve_image_to_tensor(item: str, cfg: RespectConfig) -> Optional[torch.Tensor]:
    """图片资源字符串 -> tensor。"""
    try:
        if item.startswith("data:"):
            return b64_to_tensor(item)
        if item.startswith("/v1/"):
            item = cfg.normalized_base().rsplit("/v1", 1)[0] + item
        if item.startswith("http://") or item.startswith("https://"):
            return url_to_tensor(item, cfg)
        if len(item) > 200 and re.match(r"^[A-Za-z0-9+/=\s]+$", item):
            return b64_to_tensor(item)
    except Exception as exc:  # pragma: no cover - 仅记录失败
        print(f"[Respect] 图片解析失败: {item[:120]}... err={exc}")
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
            if resp.status_code in (429, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
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
