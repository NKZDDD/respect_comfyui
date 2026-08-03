# -*- coding: utf-8 -*-
"""灵感鸭 API 独立客户端（www.lingganyaapi.com）。

不依赖 ComfyUI / torch，只需要 requests；Pillow 可选（用于压缩参考图）。
行为与仓库 lingganya_nodes.py 保持一致——三步式异步：

- 图片：POST /v1/images/generations?async=true → GET /v1/images/{id} → GET /v1/images/{id}/content
- 视频：POST /v1/videos?async=true            → GET /v1/videos/{id} → GET /v1/videos/{id}/content

字段要点：
- 视频 `size` 是宽高比（如 9:16），`seconds` 才是时长（sora 传字符串、sd 传整数）
- 图片 `size` 是像素（如 1024x1536）
- `images[]` 是参考图数组：公网 URL 优先（官方要求），base64 data URI 兜底
- SD 系列（sd-2.0 / sd-fast）`resolution` 必须放顶层
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import time
from typing import Any, Optional

import requests

DONE_STATES = ("completed", "succeeded", "success", "done", "finished", "complete", "generated")
FAIL_STATES = ("failed", "cancelled", "canceled", "error", "fail")
MEDIA_VIDEO = (".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi")
MEDIA_IMAGE = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
URL_KEYS = ("url", "video_url", "download_url", "file_url", "result_url", "image_url")


class LingganyaError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# 响应解析（镜像 video_nodes/utils 的容错逻辑）
# ---------------------------------------------------------------------------


def extract_task_id(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for scope in (data, data.get("data") if isinstance(data.get("data"), dict) else {}):
        for k in ("id", "task_id", "video_id"):
            v = scope.get(k) if isinstance(scope, dict) else None
            if isinstance(v, (str, int)) and str(v):
                return str(v)
    return ""


def extract_status(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for scope in (data, data.get("data") if isinstance(data.get("data"), dict) else {}):
        for k in ("status", "state", "task_status", "job_status"):
            v = scope.get(k) if isinstance(scope, dict) else None
            if isinstance(v, str) and v:
                return v.lower()
    return ""


def _collect_urls(node: Any, found: list, key: str = "") -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            _collect_urls(v, found, str(k))
    elif isinstance(node, (list, tuple)):
        for v in node:
            _collect_urls(v, found, key)
    elif isinstance(node, str) and node.startswith("http"):
        found.append((key, node))


def extract_video_url(data: Any) -> str:
    """取真正的视频直链：媒体后缀优先，API /content 端点垫底。"""
    found: list = []
    _collect_urls(data, found)
    if not found:
        return ""

    def rank(item):
        key, url = item
        base = url.split("?", 1)[0].lower()
        score = 0
        if base.endswith(MEDIA_VIDEO):
            score -= 100
        if key in URL_KEYS:
            score -= 10
        if base.rstrip("/").endswith("/content") and not base.endswith(MEDIA_VIDEO):
            score += 50
        return score

    found.sort(key=rank)
    return found[0][1]


def extract_image_items(data: Any) -> list[str]:
    """取图片资源列表：http URL / data URI / 裸 base64（b64_json 字段）。"""
    items: list[str] = []

    def walk(node: Any):
        if isinstance(node, dict):
            b64 = node.get("b64_json")
            if isinstance(b64, str) and b64:
                items.append("data:image/png;base64," + b64)
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            if node.startswith("data:image"):
                items.append(node)
            elif node.startswith("http"):
                base = node.split("?", 1)[0].lower()
                if base.endswith(MEDIA_IMAGE) or "image" in base:
                    items.append(node)

    walk(data)
    if items:
        # 去重保序
        seen, out = set(), []
        for it in items:
            if it not in seen:
                seen.add(it)
                out.append(it)
        return out
    # 兜底：任意 http URL（排除 /content API 端点优先级同视频）
    found: list = []
    _collect_urls(data, found)
    return [u for _, u in found]


# ---------------------------------------------------------------------------
# 本地文件 → 参考图 data URI
# ---------------------------------------------------------------------------


def file_to_data_uri(path: str, max_side: int = 1536, quality: int = 90) -> str:
    """本地图片 → base64 data URI。装了 Pillow 会先压到 max_side 再编码。"""
    try:
        from PIL import Image  # 可选依赖

        img = Image.open(path)
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if max_side > 0 and max(w, h) > max_side:
            scale = max_side / float(max(w, h))
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        raw, mime = buf.getvalue(), "image/jpeg"
    except ImportError:
        with open(path, "rb") as f:
            raw = f.read()
        mime = mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def resolve_ref(ref: str, project_root: str, max_side: int = 1536) -> str:
    """参考图引用 → 可入 images[] 的值：http(s) URL 原样；本地路径转 data URI。"""
    ref = (ref or "").strip()
    if not ref:
        return ""
    if ref.startswith("http") or ref.startswith("data:"):
        return ref
    path = ref if os.path.isabs(ref) else os.path.join(project_root, ref)
    if not os.path.isfile(path):
        raise LingganyaError(f"参考图文件不存在: {path}")
    return file_to_data_uri(path, max_side=max_side)


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------


class Client:
    def __init__(self, api_key: str, base_url: str = "https://www.lingganyaapi.com",
                 timeout: int = 600, proxy: str = ""):
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "https://www.lingganyaapi.com").strip().rstrip("/")
        self.timeout = timeout
        self.proxy = (proxy or "").strip()
        if not self.api_key:
            raise LingganyaError("缺少 API key：填 config.json 的 api_key，或设环境变量 "
                                 "LINGGANYA_API_KEY / RESPECT_API_KEY / AICOPY_API_KEY")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "RespectProductionRunner/1.0",
        }

    def _proxies(self) -> Optional[dict]:
        return {"http": self.proxy, "https": self.proxy} if self.proxy else None

    def request(self, method: str, path: str, *, json_body: Any = None, params: Any = None,
                retries: int = 3, timeout: Optional[int] = None) -> Any:
        url = path if path.startswith("http") else self.base_url + path
        last: Optional[Exception] = None
        for attempt in range(max(1, retries)):
            try:
                resp = requests.request(
                    method, url, headers=self._headers(), json=json_body, params=params,
                    timeout=timeout or self.timeout, proxies=self._proxies(),
                )
                if resp.status_code in (429, 502, 503, 504) and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                if resp.status_code >= 400:
                    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "latin-1"):
                        resp.encoding = "utf-8"
                    raise LingganyaError(f"HTTP {resp.status_code}: {resp.text[:500]}", resp.status_code)
                return resp.json() if resp.content else {}
            except LingganyaError:
                raise
            except requests.RequestException as exc:
                last = exc
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise LingganyaError(f"网络错误: {exc}") from exc
        raise LingganyaError(f"网络错误: {last}")

    # -- 参考图上传（换公网 URL，SD2 系接口要求） -----------------------------

    def upload_file(self, path: str, upload_base: str) -> str:
        """把本地文件传到图床（{upload_base}/v1/uploads，字段 image）→ 公网 URL。"""
        base = (upload_base or "").strip().rstrip("/")
        if not base:
            raise LingganyaError("缺少 upload_base_url（参考图公网上传地址）")
        last: Optional[Exception] = None
        for endpoint in ("/v1/uploads", "/v1/upload"):
            try:
                with open(path, "rb") as f:
                    resp = requests.post(
                        base + endpoint,
                        headers={"Authorization": f"Bearer {self.api_key}",
                                 "Accept": "application/json",
                                 "User-Agent": "RespectProductionRunner/1.0"},
                        files={"image": (os.path.basename(path), f,
                                         mimetypes.guess_type(path)[0] or "image/png")},
                        timeout=180, proxies=self._proxies(),
                    )
                if resp.status_code >= 400:
                    raise LingganyaError(f"上传 HTTP {resp.status_code}: {resp.text[:300]}")
                data = resp.json() if resp.content else {}
                for scope in (data, data.get("data") if isinstance(data.get("data"), dict) else {}):
                    if isinstance(scope, dict):
                        for k in ("image_url", "url", "file_url", "download_url"):
                            v = scope.get(k)
                            if isinstance(v, str) and v.startswith("http"):
                                return v
                        for k in ("image_urls", "urls"):
                            v = scope.get(k)
                            if isinstance(v, list) and v and str(v[0]).startswith("http"):
                                return str(v[0])
                if isinstance(data, str) and data.startswith("http"):
                    return data
                raise LingganyaError(f"上传响应中未找到 URL: {str(data)[:300]}")
            except (LingganyaError, requests.RequestException, OSError) as exc:
                last = exc
                continue
        raise LingganyaError(f"参考图上传失败: {last}")

    # -- 提交 ---------------------------------------------------------------

    def submit_image(self, prompt: str, *, model: str = "gpt-image-2",
                     size: str = "1024x1024", n: int = 1,
                     images: Optional[list[str]] = None) -> tuple[Any, str]:
        body: dict = {"model": model, "prompt": prompt, "size": size, "n": int(n)}
        if images:
            body["images"] = images[:9]
        data = self.request("POST", "/v1/images/generations", json_body=body,
                            params={"async": "true"}, retries=2, timeout=300)
        return data, extract_task_id(data)

    def submit_video(self, prompt: str, *, model: str = "sd-2.0", size: str = "9:16",
                     seconds: int = 15, resolution: str = "",
                     images: Optional[list[str]] = None) -> tuple[Any, str]:
        """灵感鸭统一视频接口风格（sora/sd 共用 /v1/videos?async=true）。"""
        is_sd = model.lower().startswith("sd")
        body: dict = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "seconds": int(seconds) if is_sd else str(int(seconds)),
        }
        if images:
            body["images"] = images[:9]
        res = (resolution or "").strip()
        if not res and is_sd:
            res = "720p"  # SD 必填
        if res:
            body["resolution"] = res
        data = self.request("POST", "/v1/videos", json_body=body,
                            params={"async": "true"}, retries=2, timeout=300)
        return data, extract_task_id(data)

    def submit_video_sd2(self, prompt: str, *, model: str = "sd2-pro-720p", ratio: str = "9:16",
                         duration: int = 12, images: Optional[list[str]] = None,
                         enable_sound: bool = True) -> tuple[Any, str]:
        """SD2/seedance 中转风格（如 paisio）：POST /v1/videos，metadata{modeType,ratio,enableSound}。

        images 必须是公网 URL（先用 upload_file 换 URL）；提示词自动补 @图N 标记。
        """
        imgs = (images or [])[:9]
        p = prompt or ""
        if imgs and "@图" not in p:
            p = p.strip() + " " + " ".join(f"@图{i + 1}" for i in range(len(imgs)))
        body: dict = {
            "model": model,
            "prompt": p,
            "duration": int(duration),
            "metadata": {
                "modeType": "image2video" if imgs else "text2video",
                "ratio": ratio or "9:16",
                "enableSound": "on" if enable_sound else "off",
            },
        }
        if imgs:
            body["images"] = imgs
        data = self.request("POST", "/v1/videos", json_body=body, retries=2, timeout=300)
        return data, extract_task_id(data)

    # -- 轮询与取件 ----------------------------------------------------------

    def poll(self, kind: str, task_id: str, *, interval: int = 8, timeout: int = 1800,
             want_images: bool = False, log=print) -> Any:
        """轮询直到完成。返回：want_images=True → 图片项列表；否则视频 URL。"""
        pick = extract_image_items if want_images else extract_video_url
        start, last_status = time.time(), ""
        while time.time() - start < timeout:
            try:
                data = self.request("GET", f"/v1/{kind}/{task_id}", retries=1, timeout=60)
            except LingganyaError as exc:
                log(f"    轮询错误(继续): {exc}")
                time.sleep(interval)
                continue
            status = extract_status(data)
            got = pick(data)
            if status and status != last_status:
                log(f"    状态: {status}")
                last_status = status
            if status in FAIL_STATES:
                raise LingganyaError(f"任务失败: {json.dumps(data, ensure_ascii=False)[:600]}")
            done = status in DONE_STATES
            if got and (not status or done):
                return got
            if done:
                content = self.request("GET", f"/v1/{kind}/{task_id}/content", retries=1, timeout=120)
                got = pick(content)
                if got:
                    return got
                raise LingganyaError(f"任务已完成但未取到结果: {task_id}")
            time.sleep(interval)
        raise LingganyaError(f"任务超时({timeout}s): {task_id}")

    # -- 下载 ---------------------------------------------------------------

    def save_item(self, item: str, dest: str) -> str:
        """把生成结果（http URL / data URI / 裸 base64）落盘到 dest。"""
        os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
        if item.startswith("data:"):
            raw = base64.b64decode(item.split(",", 1)[1])
            with open(dest, "wb") as f:
                f.write(raw)
            return dest
        if item.startswith("http"):
            headers = self._headers() if item.startswith(self.base_url) else None
            with requests.get(item, headers=headers, timeout=self.timeout,
                              proxies=self._proxies(), stream=True) as r:
                if r.status_code >= 400 and headers is None:
                    r2 = requests.get(item, headers=self._headers(), timeout=self.timeout,
                                      proxies=self._proxies(), stream=True)
                    r2.raise_for_status()
                    r = r2
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
            return dest
        # 裸 base64
        with open(dest, "wb") as f:
            f.write(base64.b64decode(item))
        return dest
