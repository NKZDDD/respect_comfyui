"""Respect ComfyUI 扩展 - 鹤 / paisio(`https://api.paisio.online`) 专用节点。

文档：y5dprsil1i.apifox.cn（就是之前做「Seedance 通用异步视频」用的那份，但模型名/字段已更新）。

- 视频：`POST /v1/videos` → `GET /v1/videos/{task_id}` 轮询 → 完成取直链
  文档只写 `{model, prompt, image_url}`，但**实测**（production_runner 跑通 17 段）该网关还接受
  即梦/豆包兼容风格的 `metadata{modeType,ratio,enableSound}`、`images[]`（data URI）、`duration/seconds`。
  参考图**必须 data URI 内联**（1024px JPEG q80）——它拒绝外部 key 走 aione 图床。
- 图片：`POST /v1/images/generations`（**同步**，统一 `imageSize` + `aspectRatio`），返回 `data[].b64_json`
- 图生图/多图融合：`POST /v1/images/edits`（multipart，`image[]` **最多 16 张**，可带 mask 做局部重绘）
- 虚拟资产：`POST /v1/virtual-assets` 上传图片/视频/音频 → `va_xxx`，
  再 `POST /v1/virtual-assets/{id}/sync` 轮询到 `active`；`GET /v1/virtual-assets/group` 看资产组是否可用。
  **这是给视频传「参考视频/音频」的官方途径**，不用自己搭图床。

LLM 不需要新节点：该网关兼容 OpenAI `/v1/chat/completions` 和 Anthropic `/v1/messages`，
直接用 `Respect Chat 对话` / `Respect Claude 对话`，base_url 填 `https://api.paisio.online` 即可。
"""

from __future__ import annotations

import base64
import io
import json
import time

import torch
from PIL import Image

from .utils import (
    RespectAPIError,
    api_request,
    download_to_output,
    dynamic_image_inputs,
    ensure_config,
    expand_image_frames,
    extract_image_payloads,
    resolve_image_to_tensor,
    tensor_to_b64,
    tensor_to_pil,
    tensors_concat,
)
from .video_nodes import _async_poll, _submit_async_video

CATEGORY = "Respect/鹤"

# --- 视频 ---------------------------------------------------------------
HE_VIDEO_MODELS = [
    "sd2-pro-720p",
    "sd2-1080p", "sd2-720p", "sd2-480p", "sd2-fast-720p", "sd2-fast-480p",
    "sd3-1080p", "sd3-720p", "sd3-480p", "sd3-fast-720p", "sd3-fast-480p",
    "seedance2.0-official2-1080p", "seedance2.0-official2-720p", "seedance2.0-official2-480p",
    "seedance2.0-fast2-720p", "seedance2.0-fast2-480p",
]
HE_RATIOS = ["(不传)", "9:16", "16:9", "1:1", "4:3", "3:4", "21:9"]
HE_TRISTATE = ["on", "off", "(不传)"]

# --- 图片 ---------------------------------------------------------------
HE_IMAGE_MODELS = [
    "gpt-image2-high", "gpt-image2-medium", "gpt-image2-low",
    "gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview",
]
HE_EDIT_MODELS = ["gpt-image2-high", "gpt-image2-medium", "gpt-image2-low"]
HE_IMAGE_SIZES = ["1K", "2K", "4K"]
HE_IMAGE_RATIOS = ["1:1", "16:9", "9:16", "3:2", "2:3", "4:3", "3:4", "4:5", "5:4", "21:9"]
HE_QUALITY = ["auto", "low", "medium", "high"]
HE_FORMATS = ["png", "jpeg", "webp"]
HE_BACKGROUNDS = ["auto", "opaque"]

# 该网关实测可用的参考图规格（见 production_runner 实践）
_REF_MAX_SIDE = 1024
_REF_QUALITY = 80


def _he_data_uris(tensors: list, max_side: int = _REF_MAX_SIDE, quality: int = _REF_QUALITY) -> list[str]:
    """IMAGE（含批次）→ data URI 列表。鹤只吃内联，不吃外部图床。"""
    out: list[str] = []
    for frame in expand_image_frames(tensors):
        b = tensor_to_b64(frame, fmt="JPEG", quality=quality, max_side=max_side)
        if b:
            out.append(b[0])
    return out


def _he_png_bytes(tensor, max_side: int = 2048) -> bytes:
    """单帧 IMAGE → PNG bytes（multipart 上传用）。"""
    b = tensor_to_b64(tensor, fmt="PNG", max_side=max_side)
    if not b:
        return b""
    return base64.b64decode(b[0].split(",", 1)[1])


def _he_brief(body: dict) -> str:
    """请求体压成一行日志：base64/长串截断，方便核对到底发了什么字段。"""
    def shrink(v):
        if isinstance(v, str):
            if v.startswith("data:"):
                return f"<{v.split(',', 1)[0]} {len(v)}字符>"
            return v if len(v) <= 80 else v[:77] + "…"
        if isinstance(v, list):
            return [shrink(x) for x in v]
        if isinstance(v, dict):
            return {k: shrink(x) for k, x in v.items()}
        return v
    return json.dumps({k: shrink(v) for k, v in body.items()}, ensure_ascii=False)


def _he_items_to_tensor(items: list, cfg) -> torch.Tensor:
    tensors = [t for t in (resolve_image_to_tensor(i, cfg) for i in items) if t is not None]
    if not tensors:
        raise RespectAPIError(f"未能把结果解析成图片: {str(items)[:300]}")
    return tensors_concat(tensors)


# ---------------------------------------------------------------------------
# ① 鹤 视频
# ---------------------------------------------------------------------------


class RespectHeVideo:
    """鹤/paisio 视频。`POST /v1/videos` 提交 + `GET /v1/videos/{task_id}` 轮询。

    body：文档字段 `{model, prompt, image_url}`，另按**实测**附带即梦/豆包兼容字段
    （`metadata{modeType,ratio,enableSound}` + `images[]` data URI + `seconds/duration`）。
    `compat_metadata` 关掉就只发文档里那三个字段。
    """

    DESCRIPTION = ("鹤/paisio 视频(base_url=https://api.paisio.online)。sd2/sd3/seedance2.0 全系按秒计费；"
                   "参考图自动转 data URI 内联(该网关不吃外部图床)；compat_metadata 默认开(实测可用)。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://api.paisio.online"}),
                "model": (HE_VIDEO_MODELS, {"default": "sd2-pro-720p", "tooltip": "上新模型用 custom_model 填"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "seconds": ("INT", {"default": 12, "min": 0, "max": 60, "tooltip": "时长；0=不传。sd2 支持 4-15 秒"}),
                "aspect_ratio": (HE_RATIOS, {"default": "9:16", "tooltip": "写进 metadata.ratio；选(不传)则不带"}),
                "poll_interval": ("INT", {"default": 8, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "image_1": ("IMAGE", {"tooltip": "参考图/首帧 → images[] data URI；接批次会展开"}),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "image_url": ("STRING", {"default": "", "multiline": False, "placeholder": "公网参考图URL（文档字段，作首帧）"}),
                "enable_sound": (HE_TRISTATE, {"default": "on", "tooltip": "metadata.enableSound"}),
                "compat_metadata": ("BOOLEAN", {"default": True, "tooltip": "带即梦/豆包兼容字段(metadata/images/seconds)；关掉=只发文档三字段"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 32, "step": 1, "tooltip": "参考图接口数量；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("在线视频 URL", "下载到本地的路径（预览/拼接用这个）", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, seconds, aspect_ratio, poll_interval, poll_timeout,
                 auto_download, image_url="", enable_sound="on", compat_metadata=True,
                 custom_model="", save_dir="", filename="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        body: dict = {"model": model, "prompt": prompt}
        url = (image_url or "").strip()
        if url:
            body["image_url"] = url

        refs = _he_data_uris(dynamic_image_inputs(kwargs))
        if compat_metadata:
            if refs:
                body["images"] = refs
            if int(seconds) > 0:
                body["seconds"] = str(int(seconds))
                body["duration"] = int(seconds)
            meta: dict = {"modeType": "image2video" if (refs or url) else "text2video"}
            if not aspect_ratio.startswith("("):
                meta["ratio"] = aspect_ratio
            if not enable_sound.startswith("("):
                meta["enableSound"] = enable_sound
            body["metadata"] = meta
        elif refs:
            # 只发文档字段时，参考图只能塞 image_url
            body.setdefault("image_url", refs[0])
            if body.get("image_url", "").startswith("data:"):
                print("[Respect] 提醒：compat_metadata 已关，把 data URI 放进了 image_url —— "
                      "文档这个字段是公网 URL，服务端若去 fetch 会失败。建议改填公网URL（接对象存储上传）。")

        print(f"[Respect] 鹤 视频提交 POST /v1/videos  body={_he_brief(body)}")
        if refs and "images" in body:
            print("[Respect] 注意：images[]+metadata 是即梦/豆包兼容写法（实测于 sd2-pro-720p）。"
                  "文档只列了 image_url；sd3/其它系列若出片不参考图，把 compat_metadata 关掉、"
                  "改成把公网URL填进 image_url 再试。")
        direct, task_id = _submit_async_video(cfg, body, timeout=300)
        video_url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        local = ""
        if auto_download and video_url:
            try:
                local = download_to_output(video_url, cfg, prefix="he_video", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] 鹤 视频下载失败: {exc}")
        return (video_url, local, task_id or "")


# ---------------------------------------------------------------------------
# ② 鹤 图片生成（统一接口，同步）
# ---------------------------------------------------------------------------


class RespectHeImage:
    """鹤/paisio 图片生成。`POST /v1/images/generations`（同步，返回 `data[].b64_json`）。

    统一参数体系：`imageSize`(1K/2K/4K) + `aspectRatio`，系统自动换算像素。
    单张参考图可走 `image`（URL / base64 / data URI）做图生图。
    """

    DESCRIPTION = ("鹤/paisio 图片生成(同步)。gpt-image2-low/medium/high、gemini-3(.1)-image；"
                   "imageSize=1K/2K/4K + aspectRatio 自动换算像素；可选单张参考图。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://api.paisio.online"}),
                "model": (HE_IMAGE_MODELS, {"default": "gpt-image2-high"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "imageSize": (HE_IMAGE_SIZES, {"default": "2K", "tooltip": "分辨率档，自动换算像素"}),
                "aspectRatio": (HE_IMAGE_RATIOS, {"default": "1:1"}),
                "n": ("INT", {"default": 1, "min": 1, "max": 10}),
            },
            "optional": {
                "quality": (HE_QUALITY, {"default": "auto"}),
                "output_format": (HE_FORMATS, {"default": "png"}),
                "output_compression": ("INT", {"default": 0, "min": 0, "max": 100, "tooltip": "0=不传；仅 jpeg/webp 有效"}),
                "background": (HE_BACKGROUNDS, {"default": "auto", "tooltip": "GPT-Image-2 不支持透明"}),
                "ref_image": ("IMAGE", {"tooltip": "单张参考图 → image 字段（转 data URI）"}),
                "ref_url": ("STRING", {"default": "", "multiline": False, "placeholder": "参考图公网URL，填了优先于 ref_image"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选：直接指定像素 size，如 1024x1536"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "revised_prompt")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, imageSize, aspectRatio, n,
                 quality="auto", output_format="png", output_compression=0, background="auto",
                 ref_image=None, ref_url="", custom_model="", custom_size=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        body: dict = {
            "model": model,
            "prompt": prompt,
            "n": int(n),
            "quality": quality,
            "output_format": output_format,
            "background": background,
        }
        size = (custom_size or "").strip()
        if size:
            body["size"] = size          # legacy 像素模式
        else:
            body["imageSize"] = imageSize
            body["aspectRatio"] = aspectRatio
        if int(output_compression) > 0 and output_format in ("jpeg", "webp"):
            body["output_compression"] = int(output_compression)

        ref = (ref_url or "").strip()
        if not ref and ref_image is not None:
            uris = _he_data_uris([ref_image])
            ref = uris[0] if uris else ""
        if ref:
            body["image"] = ref

        resp = api_request(cfg, "POST", "/v1/images/generations", json_body=body,
                           retries=2, timeout=max(cfg.timeout, 300))
        data = resp.json() if resp.content else {}
        items = extract_image_payloads(data)
        if not items:
            raise RespectAPIError(f"未能从响应中提取图片: {json.dumps(data, ensure_ascii=False)[:400]}")
        revised = ""
        arr = data.get("data")
        if isinstance(arr, list) and arr and isinstance(arr[0], dict):
            revised = str(arr[0].get("revised_prompt") or "")
        return (_he_items_to_tensor(items, cfg), revised)


# ---------------------------------------------------------------------------
# ③ 鹤 图生图 / 多图融合（最多 16 张）
# ---------------------------------------------------------------------------


class RespectHeImageEdit:
    """鹤/paisio 图生图 / 多图融合。`POST /v1/images/edits`（multipart，`image[]` 最多 16 张）。

    - 参考图数量可变：填 `inputcount` 后点节点上的「更新输入口」；每个槽接批次会展开
    - `mask` 可选：**透明区域=要重绘的区域**（节点会用第一张图 + mask 合成带 alpha 的 PNG）
    """

    DESCRIPTION = ("鹤/paisio 图生图/多图融合 /v1/images/edits，image[] 最多16张（inputcount+『更新输入口』）；"
                   "可接 mask 做局部重绘（mask 为白的地方会被重绘）。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://api.paisio.online"}),
                "model": (HE_EDIT_MODELS, {"default": "gpt-image2-high"}),
                "prompt": ("STRING", {"default": "", "multiline": True, "tooltip": "编辑/重绘指令"}),
                "image_1": ("IMAGE", {"tooltip": "第1张参考图（必须至少一张）"}),
                "n": ("INT", {"default": 1, "min": 1, "max": 10}),
            },
            "optional": {
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "mask": ("MASK", {"tooltip": "可选：白色区域=要重绘的区域（会转成透明 alpha 传给接口）"}),
                "size": ("STRING", {"default": "", "multiline": False, "placeholder": "如 1024x1024，留空=不传"}),
                "quality": (HE_QUALITY, {"default": "auto"}),
                "output_format": (HE_FORMATS, {"default": "png"}),
                "output_compression": ("INT", {"default": 0, "min": 0, "max": 100, "tooltip": "0=不传；仅 jpeg/webp"}),
                "background": (HE_BACKGROUNDS, {"default": "auto"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 16, "step": 1, "tooltip": "参考图接口数量(≤16)；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "revised_prompt")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, image_1, n,
                 mask=None, size="", quality="auto", output_format="png", output_compression=0,
                 background="auto", custom_model="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        kwargs["image_1"] = image_1
        frames = expand_image_frames(dynamic_image_inputs(kwargs))[:16]
        if not frames:
            raise RespectAPIError("至少需要一张参考图")

        files: list = [("model", (None, model)), ("prompt", (None, prompt)), ("n", (None, str(int(n)))),
                       ("quality", (None, quality)), ("output_format", (None, output_format)),
                       ("background", (None, background))]
        if (size or "").strip():
            files.append(("size", (None, size.strip())))
        if int(output_compression) > 0 and output_format in ("jpeg", "webp"):
            files.append(("output_compression", (None, str(int(output_compression)))))
        for i, frame in enumerate(frames):
            data = _he_png_bytes(frame)
            if data:
                files.append(("image[]", (f"ref_{i + 1}.png", data, "image/png")))

        if mask is not None and (not hasattr(mask, "numel") or mask.numel() > 0):
            data = _he_mask_png(frames[0], mask)
            if data:
                files.append(("mask", ("mask.png", data, "image/png")))

        resp = api_request(cfg, "POST", "/v1/images/edits", files=files,
                           retries=2, timeout=max(cfg.timeout, 300))
        payload = resp.json() if resp.content else {}
        items = extract_image_payloads(payload)
        if not items:
            raise RespectAPIError(f"未能从响应中提取图片: {json.dumps(payload, ensure_ascii=False)[:400]}")
        revised = ""
        arr = payload.get("data")
        if isinstance(arr, list) and arr and isinstance(arr[0], dict):
            revised = str(arr[0].get("revised_prompt") or "")
        return (_he_items_to_tensor(items, cfg), revised)


def _he_mask_png(base_frame, mask) -> bytes:
    """第一张图 + MASK → 带 alpha 的 PNG（mask 为白=透明=要重绘），尺寸与第一张图一致。"""
    pils = tensor_to_pil(base_frame)
    if not pils:
        return b""
    base = pils[0].convert("RGB")
    m = mask
    if getattr(m, "ndim", 2) == 3:
        m = m[0]
    arr = (m.detach().cpu().numpy() * 255).clip(0, 255).astype("uint8")
    alpha = Image.fromarray(255 - arr, mode="L").resize(base.size, Image.LANCZOS)
    rgba = base.convert("RGBA")
    rgba.putalpha(alpha)
    buf = io.BytesIO()
    rgba.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# ④ 鹤 虚拟资产上传（图片 / 视频 / 音频 → va_xxx）
# ---------------------------------------------------------------------------


_VA_DONE = ("active",)
_VA_FAIL = ("failed",)


class RespectHeAssetUpload:
    """鹤/paisio 虚拟资产上传。`POST /v1/virtual-assets` + `POST /v1/virtual-assets/{id}/sync` 轮询到 `active`。

    **给视频传参考视频/音频的官方途径**（不用自己搭图床）：支持 图片 jpg/png/webp、视频 mp4、音频 mp3/wav/m4a。
    `file_path` 填了就上传该文件（视频/音频用这个），否则上传接入的 `image`。
    上传后资产组需为 active 才能用于视频生成（节点会顺带查一次 `GET /v1/virtual-assets/group`）。
    """

    DESCRIPTION = ("鹤/paisio 虚拟资产上传：图片/视频/音频 → va_xxx，轮询到 active。"
                   "视频/音频用 file_path（可接『选择/上传本地视频』或视频节点的 local_path）。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://api.paisio.online"}),
                "poll_interval": ("INT", {"default": 3, "min": 2, "max": 30, "tooltip": "文档建议每 2-3 秒查一次"}),
                "poll_timeout": ("INT", {"default": 300, "min": 30, "max": 3600}),
            },
            "optional": {
                "image": ("IMAGE", {"tooltip": "上传图片（未填 file_path 时用）"}),
                "file_path": ("STRING", {"default": "", "multiline": False, "placeholder": "本地文件路径（视频mp4/音频mp3等），优先于 image"}),
                "name": ("STRING", {"default": "", "multiline": False, "placeholder": "资产名，留空=文件名"}),
                "model_id": ("STRING", {"default": "seedance2.0-official", "multiline": False, "tooltip": "目标模型（query 参数），默认 seedance2.0-official"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("asset_id", "asset_type", "status")
    OUTPUT_TOOLTIPS = ("资产 ID（va_xxx），视频生成时引用", "image / video / audio", "最终状态（active 才可用）")
    FUNCTION = "upload"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def upload(self, api_config, poll_interval, poll_timeout, image=None, file_path="",
               name="", model_id="seedance2.0-official"):
        import mimetypes
        import os

        cfg = ensure_config(api_config)
        file_path = (file_path or "").strip().strip('"')
        if file_path:
            if not os.path.isfile(file_path):
                raise FileNotFoundError(f"找不到本地文件: {file_path}")
            with open(file_path, "rb") as f:
                blob = f.read()
            fname = os.path.basename(file_path)
            ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        else:
            if image is None or (hasattr(image, "numel") and image.numel() == 0):
                raise RespectAPIError("请接入 image 或填 file_path")
            blob = _he_png_bytes(image[:1])
            fname = "upload.png"
            ctype = "image/png"
        if not blob:
            raise RespectAPIError("待上传内容为空")

        files: list = [("file", (fname, blob, ctype))]
        if (name or "").strip():
            files.append(("name", (None, name.strip())))
        params = {"model_id": model_id.strip()} if (model_id or "").strip() else None
        resp = api_request(cfg, "POST", "/v1/virtual-assets", files=files, params=params,
                           retries=2, timeout=max(cfg.timeout, 600))
        data = (resp.json() if resp.content else {}) or {}
        info = data.get("data") if isinstance(data.get("data"), dict) else data
        asset_id = str(info.get("id") or "")
        asset_type = str(info.get("asset_type") or "")
        status = str(info.get("status") or "").lower()
        if not asset_id:
            raise RespectAPIError(f"上传未返回资产 id: {json.dumps(data, ensure_ascii=False)[:400]}")
        print(f"[Respect] 鹤 资产已上传 {asset_id}（{asset_type}，status={status}）")

        # 轮询到 active / failed
        start = time.time()
        while status not in _VA_DONE and status not in _VA_FAIL and time.time() - start < poll_timeout:
            time.sleep(poll_interval)
            try:
                r = api_request(cfg, "POST", f"/v1/virtual-assets/{asset_id}/sync", retries=1, timeout=60)
            except RespectAPIError as exc:
                print(f"[Respect] 资产状态查询出错，继续重试: {exc}")
                continue
            d = (r.json() if r.content else {}) or {}
            inner = d.get("data") if isinstance(d.get("data"), dict) else d
            new_status = str(inner.get("status") or "").lower()
            if new_status and new_status != status:
                print(f"[Respect] 资产 {asset_id} 状态: {new_status}")
                status = new_status
            asset_type = asset_type or str(inner.get("asset_type") or "")
            if status in _VA_FAIL:
                raise RespectAPIError(f"资产处理失败: {inner.get('error_message') or d}")

        if status not in _VA_DONE:
            raise RespectAPIError(f"资产 {asset_id} 超时未 active（当前 {status or 'n/a'}），可调大 poll_timeout")

        # 顺带确认资产组可用（失败不阻塞）
        try:
            g = api_request(cfg, "GET", "/v1/virtual-assets/group",
                            params={"model_id": model_id.strip()} if (model_id or "").strip() else None,
                            retries=1, timeout=30)
            gd = (g.json() if g.content else {}) or {}
            gi = gd.get("data") if isinstance(gd.get("data"), dict) else gd
            print(f"[Respect] 资产组: group_status={gi.get('group_status')} status={gi.get('status')}")
        except Exception as exc:
            print(f"[Respect] 资产组状态查询跳过: {exc}")

        return (asset_id, asset_type, status)


NODE_CLASS_MAPPINGS = {
    "RespectHeVideo": RespectHeVideo,
    "RespectHeImage": RespectHeImage,
    "RespectHeImageEdit": RespectHeImageEdit,
    "RespectHeAssetUpload": RespectHeAssetUpload,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectHeVideo": "Respect 鹤 视频（sd2/sd3/seedance）",
    "RespectHeImage": "Respect 鹤 图片生成（统一接口）",
    "RespectHeImageEdit": "Respect 鹤 图生图/多图融合（≤16张）",
    "RespectHeAssetUpload": "Respect 鹤 虚拟资产上传（图/视频/音频）",
}
