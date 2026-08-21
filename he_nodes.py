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
    dynamic_url_inputs,
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
# 照当前文档的模型清单（2026-08 抓取）。**列表会变**，不确定时先跑「Respect 加载模型列表」。
HE_VIDEO_MODELS = [
    # 2026-08-19 实拉 GET /v1/models 的结果。**别照文档或旧材料抄** ——
    # 上一版这里有 9 个已下线的名字（sd2-pro-720p、paisiodance2.0、
    # seedance2.0-official2-720p 之类），跑起来只会 503 no available channel。
    "sd2-720p", "sd2-480p", "sd2-1080p",
    "sd2-fast-720p", "sd2-fast-480p",
    "sd2-ultra-720p", "sd2-ultra-fast-720p",
    "sd2-video20-mini-720p", "sd2-video20-mini-480p",
    "sd3-720p", "sd3-480p", "sd3-1080p", "sd3-fast-720p", "sd3-fast-480p",
    "seedance2.0-selfsur-720p", "seedance2.0-selfsur-fast-720p",
    "paisiodance2.0-720p", "paisiodance2.0-fast-720p",
    # 按次分组（模型广场「sd2,sd2.5-按次分组」）
    "seedance2-4-1-720p", "seedance2-4-2-fast-720p",
    "seedance2-4-4-720p", "seedance2-4-8-720p",
    "grok-imagine-video-1.5", "grok-imagine-video-1.5-fast",
    "minimax-h3", "mx-h3",
]
HE_RATIOS = ["(不传)", "9:16", "16:9", "1:1", "4:3", "3:4", "21:9", "3:2", "2:3"]
HE_TRISTATE = ["on", "off", "(不传)"]

# --- 图片 ---------------------------------------------------------------
HE_IMAGE_MODELS = [
    "gpt-image2-high", "gpt-image2-medium", "gpt-image2-low",
    "gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview",
]
HE_EDIT_MODELS = ["gpt-image2-high", "gpt-image2-medium", "gpt-image2-low"]
HE_IMAGE_SIZES = ["1K", "2K", "4K"]
HE_IMAGE_RATIOS = ["1:1", "16:9", "9:16", "3:2", "2:3", "4:3", "3:4", "4:5", "5:4", "21:9", "9:21"]
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
                "model": (HE_VIDEO_MODELS, {"default": "sd2-720p", "tooltip": "2026-08-19 实拉的清单；上新用 custom_model 填"}),
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
                "image_url": ("STRING", {"default": "", "multiline": True, "placeholder": "公网参考图URL，每行一个：第1行→image_url(首帧)，其余→extra_images", "tooltip": "文档路径：只收 http/https（jpg/png/webp）。接『对象存储上传』的 url 最稳"}),
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
        # 文档字段：duration 是**整数**(4-15)，比例是**顶层 aspect_ratio**（该接口没有 size 字段）
        if int(seconds) > 0:
            body["duration"] = int(seconds)
        if not aspect_ratio.startswith("("):
            body["aspect_ratio"] = aspect_ratio

        # 参考图文档路径：image_url（单张首帧，公网 http/https）+ extra_images（URL 数组）
        ref_urls = [ln.strip() for ln in (image_url or "").splitlines() if ln.strip()]
        if ref_urls:
            body["image_url"] = ref_urls[0]
            if ref_urls[1:]:
                body["extra_images"] = ref_urls[1:9]

        refs = _he_data_uris(dynamic_image_inputs(kwargs))
        if compat_metadata:
            # 即梦/豆包兼容附加字段（文档未列，但 production_runner 实测跑通过 17 段）
            if refs:
                body["images"] = refs
            if int(seconds) > 0:
                body["seconds"] = str(int(seconds))
            meta: dict = {"modeType": "image2video" if (refs or ref_urls) else "text2video"}
            if not aspect_ratio.startswith("("):
                meta["ratio"] = aspect_ratio
            if not enable_sound.startswith("("):
                meta["enableSound"] = enable_sound
            body["metadata"] = meta
        elif refs and not ref_urls:
            print("[Respect] compat_metadata 已关且没填公网URL —— 文档的 image_url 要求 http/https，"
                  "base64 会被拒。请把图先过『对象存储上传』，把 url 填进 image_url。")

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



# --- 图片异步模式（文档 2026-08 新增）------------------------------------
# POST /v1/images/generations 带 async:true → task_id
# GET  /v1/images/generations/{task_id} → in_progress(progress%) / completed / failed
# 注意 failed 是**退款**的，所以失败不要盲目重投，先看错误原因。
_HE_IMG_PATH = "/v1/images/generations/{tid}"


def _he_task_id(data) -> str:
    if not isinstance(data, dict):
        return ""
    for k in ("task_id", "id", "request_id"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _he_poll_image(cfg, task_id: str, interval: int = 4, timeout: int = 900) -> list:
    """轮询异步图片任务，返回图片资源列表。文档建议 3–5 秒一次。"""
    start, last = time.time(), ""
    while time.time() - start < timeout:
        resp = api_request(cfg, "GET", _HE_IMG_PATH.format(tid=task_id), retries=1, timeout=60)
        data = resp.json() if resp.content else {}
        status = str(data.get("status") or "").lower()
        if status != last:
            prog = data.get("progress")
            print(f"[Respect] 鹤 图片任务 {task_id}: {status}"
                  + (f" {prog}%" if isinstance(prog, (int, float)) else ""))
            last = status
        if status == "failed":
            msg = ""
            err = data.get("error")
            if isinstance(err, dict):
                msg = str(err.get("message") or "")
            raise RespectAPIError(
                f"鹤 图片任务失败：{msg or json.dumps(data, ensure_ascii=False)[:300]}\n"
                f"（文档写明 failed 会退款，所以别急着重投，先看这条原因）")
        items = extract_image_payloads(data)
        if items and status in ("completed", ""):
            return items
        if status == "completed":
            raise RespectAPIError(f"任务已完成但没取到图片: {json.dumps(data, ensure_ascii=False)[:300]}")
        time.sleep(interval)
    raise RespectAPIError(f"鹤 图片任务超时: {task_id}（可调大 poll_timeout）")


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
                "use_async": ("BOOLEAN", {"default": False, "tooltip": "文档新增：async=true 返回 task_id 后轮询 /v1/images/generations/{id}。4K 出图建议开，同步容易超时"}),
                "poll_interval": ("INT", {"default": 4, "min": 3, "max": 60, "tooltip": "文档建议 3–5 秒"}),
                "poll_timeout": ("INT", {"default": 900, "min": 60, "max": 3600}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "revised_prompt")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, imageSize, aspectRatio, n,
                 quality="auto", output_format="png", output_compression=0, background="auto",
                 ref_image=None, ref_url="", custom_model="", custom_size="",
                 use_async=False, poll_interval=4, poll_timeout=900):
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

        if use_async:
            body["async"] = True

        resp = api_request(cfg, "POST", "/v1/images/generations", json_body=body,
                           retries=2, timeout=max(cfg.timeout, 300))
        data = resp.json() if resp.content else {}
        items = extract_image_payloads(data)
        if not items:
            # 异步模式：拿 task_id 去 /v1/images/generations/{id} 轮询
            tid = _he_task_id(data)
            if not tid:
                raise RespectAPIError(f"未能从响应中提取图片: {json.dumps(data, ensure_ascii=False)[:400]}")
            items = _he_poll_image(cfg, tid, int(poll_interval), int(poll_timeout))
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
                "model_id": ("STRING", {"default": "seedance2.5-00-720p", "multiline": False, "tooltip": "目标模型（query 参数）。2026-08-19 实拉确认 seedance2.0-official 已下线；填的值要在 /v1/models 里存在"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("asset_id", "asset_type", "status")
    OUTPUT_TOOLTIPS = ("资产 ID（va_xxx），视频生成时引用", "image / video / audio", "最终状态（active 才可用）")
    FUNCTION = "upload"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def upload(self, api_config, poll_interval, poll_timeout, image=None, file_path="",
               name="", model_id="seedance2.5-00-720p"):
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


# ---------------------------------------------------------------------------
# 鹤 Seedance 2.5（新规格，和上面的旧模型完全不同）
# ---------------------------------------------------------------------------

HE_SD25_MODELS = [
    # 2026-08-19 实拉。**上一版写的 `seedance-2.5-720p` / `-480p` 根本不存在**
    # （多了连字符、少了档位号），跑起来必然 503。真名长这样：
    "seedance2.5-4-1-720p",                      # 按次 3.5/次，4-30s，图10/视频0/音频0
    "seedance2.5-00-720p", "seedance2.5-00-480p",
    "seedance2.5-26-720p", "seedance2.5-26-480p",
    "sd2.5-ultra-720p",
    "paisiodance-2.5-720p", "paisiodance-2.5-480p",
]
HE_SD25_RATIOS = ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9", "3:2", "2:3"]
# 文档 2026-08 新增 start_image_url / end_image_url（「部分模型支持首尾帧控制」）。
# 文档没说这两个能不能和 image_url 同时发，所以按模式分流、两组不混发 ——
# 混着发万一被当成别的任务类型，错了是要计费的。

# 模型广场上标出来的硬约束。**只写有依据的那几个** —— 没截到的分组留空，
# 走下面的宽松默认；宁可让网关去 400（不计费），也别拿猜的规则拦住能跑的活。
HE_DURATION_RULES = {
    "seedance2-4-2-fast-720p": (10,),            # 仅有 10s
    "seedance2-4-8-720p": (10, 15),              # 10/15s
    "seedance2-4-1-720p": tuple(range(4, 16)),   # 4-15s
    "seedance2-4-4-720p": tuple(range(4, 16)),   # 4-15s
    "seedance2.5-4-1-720p": tuple(range(4, 31)),  # 4-30s
}
# (图, 视频, 音频) 上限。seedance2.5-4-1-720p 广场上标的是 10/0/0 ——
# **它不支持参考视频和音频**，上一版按 30/10/10 做的，等于给了不存在的能力。
HE_REF_LIMITS = {
    "seedance2.5-4-1-720p": (10, 0, 0),
}
HE_REF_LIMITS_DEFAULT = (30, 10, 10)

HE_SD25_MODES = ["多参考图", "首尾帧"]


class RespectHeSeedance25:
    """鹤 Seedance 2.5（`seedance2.5-4-1-720p` 等 8 个，见 HE_SD25_MODELS）。

    和鹤的旧模型**不是一套字段**（旧的是 `metadata{modeType,ratio}` + `images[data URI]`），
    2.5 用文档规定的标准格式：

    ```json
    {"model":"seedance2.5-4-1-720p","prompt":"…","duration":30,"aspect_ratio":"21:9",
     "image_url":"https://…","extra_images":["https://…"],
     "extra_videos":["https://….mp4"],"extra_audios":["https://….wav"]}
    ```
    硬约束（提交前就校验，不浪费付费请求）：
    时长和素材上限**按模型定**（见 HE_DURATION_RULES / HE_REF_LIMITS）：
    如 seedance2.5-4-1-720p 是 4–30 秒、图 ≤10 且**不收参考视频/音频**；
    没列到的型号走宽松默认（4–30 秒、图30/视频10/音频10），
    且**参考素材必须是公网 http(s) URL**（接「对象存储上传」拿链接）。
    """

    DESCRIPTION = ("鹤 Seedance 2.5：duration按模型定(4-30) + aspect_ratio + image_url/extra_images"
                   "(≤30) + extra_videos(≤10)/extra_audios(≤10)。**只收公网URL**，"
                   "参考图请接『对象存储上传』。与鹤的旧模型字段完全不同。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://api.paisio.online"}),
                "model": (HE_SD25_MODELS, {"default": "seedance2.5-4-1-720p", "tooltip": "广场「按次分组」那个：3.5/次、4-30秒、图10且不收视频音频"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": ("INT", {"default": 15, "min": 4, "max": 30, "tooltip": "按模型定：seedance2.5-4-1-720p 是 4–30 秒"}),
                "aspect_ratio": (HE_SD25_RATIOS, {"default": "9:16"}),
                "generation_mode": (HE_SD25_MODES, {"default": "多参考图", "tooltip": "选『首尾帧』就只发 start_image_url+end_image_url，不发 image_url —— 两组字段不混发，避免被当成别的任务类型"}),
                "poll_interval": ("INT", {"default": 10, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 2400, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "首帧/主参考图 URL（接对象存储上传）→ image_url"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "extra_image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "追加参考图URL，每行一个（连同上面共 ≤30）"}),
                "video_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考视频URL，每行一个（≤10）"}),
                "audio_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考音频URL，每行一个（≤10）"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 30, "step": 1, "tooltip": "参考图URL接口数量；改完点节点上的『更新输入口』按钮增减 ref_url_N（接对象存储上传的 url）"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("在线视频 URL", "下载到本地的路径（预览/拼接用这个）", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, duration, aspect_ratio,
                 generation_mode, poll_interval, poll_timeout, auto_download,
                 extra_image_urls="", video_urls="", audio_urls="",
                 custom_model="", save_dir="", filename="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model

        def lines(s, cap):
            return [ln.strip() for ln in (s or "").splitlines() if ln.strip()][:cap]

        # ref_url_N 数量由 inputcount + 「更新输入口」决定，按数字顺序取
        imgs = dynamic_url_inputs(kwargs)
        imgs += lines(extra_image_urls, 30)
        vids, auds = lines(video_urls, 10), lines(audio_urls, 10)

        # 提交前把不合规的全说清楚，别发出去等 400（付费请求）
        problems = []
        dur = int(duration)
        allowed = HE_DURATION_RULES.get(model)
        if allowed and dur not in allowed:
            rng = (f"{min(allowed)}–{max(allowed)} 秒"
                   if len(allowed) == max(allowed) - min(allowed) + 1
                   else "、".join(str(a) for a in allowed) + " 秒")
            problems.append(f"{model} 的时长只能是 {rng}，收到 {dur} 秒")
        elif not allowed and not 4 <= dur <= 30:
            problems.append(f"时长按 4-30 秒处理，收到 {dur} 秒")
        if aspect_ratio not in HE_SD25_RATIOS:
            problems.append(f"比例只支持 {'、'.join(HE_SD25_RATIOS)}，收到 {aspect_ratio}")
        cap_i, cap_v, cap_a = HE_REF_LIMITS.get(model, HE_REF_LIMITS_DEFAULT)
        if len(imgs) > cap_i:
            problems.append(f"{model} 图片最多 {cap_i} 张，收到 {len(imgs)} 张")
        if len(vids) > cap_v:
            # 广场标 10/0/0 的模型压根不收视频音频 —— 发过去也是被忽略，
            # 与其静默丢掉不如直接说，免得以为参考视频生效了
            problems.append(f"{model} 不支持参考视频（上限 {cap_v}），收到 {len(vids)} 条"
                            if cap_v == 0 else
                            f"视频素材最多 {cap_v} 条，收到 {len(vids)} 条")
        if len(auds) > cap_a:
            problems.append(f"{model} 不支持参考音频（上限 {cap_a}），收到 {len(auds)} 条"
                            if cap_a == 0 else
                            f"音频素材最多 {cap_a} 条，收到 {len(auds)} 条")
        bad = [u for u in imgs + vids + auds if not u.startswith(("http://", "https://"))]
        if bad:
            problems.append(f"参考素材必须是公网 http(s) URL（接『对象存储上传』），"
                            f"这些不是：{bad[:2]}")
        if generation_mode == "首尾帧" and len(imgs) < 2:
            problems.append(f"首尾帧要 2 张图（第1张首帧、第2张尾帧），现在只有 {len(imgs)} 张")
        if problems:
            raise RespectAPIError("Seedance 2.5 参数不符合鹤的接口要求：" + "；".join(problems))

        body: dict = {"model": model, "prompt": prompt or "",
                      "duration": dur, "aspect_ratio": aspect_ratio}
        if generation_mode == "首尾帧":
            # 文档：start_image_url=首帧、end_image_url=末帧（部分模型支持）。
            # 这条路径**不发 image_url / extra_images**，免得两组字段撞车。
            body["start_image_url"], body["end_image_url"] = imgs[0], imgs[1]
            if imgs[2:]:
                print(f"[Respect] 首尾帧模式只用前 2 张，已忽略多余 {len(imgs) - 2} 张"
                      f"（要多图参考请把模式切回『多参考图』）")
        elif imgs:
            # prompt 里可用 @Image1 / @Image2 引用，**顺序就是编号**
            body["image_url"] = imgs[0]
            if imgs[1:]:
                body["extra_images"] = imgs[1:]
        if vids:
            body["extra_videos"] = vids
        if auds:
            body["extra_audios"] = auds

        print(f"[Respect] 鹤 Seedance2.5 提交 body={_he_brief(body)}")
        direct, task_id = _submit_async_video(cfg, body, timeout=300)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="he_sd25", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] 鹤 Seedance2.5 下载失败: {exc}")
        return (url, local, task_id or "")



# ---------------------------------------------------------------------------
# ⑥ 鹤 账户余额与价格（GET /v1/balance）
# ---------------------------------------------------------------------------


class RespectHeBalance:
    """鹤 账户余额与实时价格（`GET /v1/balance`）。

    返回余额、VIP 等级、今日生成次数，以及 **`current_prices`：当前 Key 实际适用的
    模型价格表**。这张表就是最可靠的模型清单 —— 比文档里那两个示例模型名靠谱，
    也不用去撞需要鉴权的 `/v1/models`。价格随 VIP 等级变，所以要按 Key 查。
    """

    DESCRIPTION = ("鹤 GET /v1/balance：余额 / VIP等级 / 今日次数 / current_prices 实时价格表。"
                   "价格表同时就是该 Key 可用的模型清单，选模型前先跑这个。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://api.paisio.online"}),
            },
            "optional": {
                "filter": ("STRING", {"default": "", "multiline": False, "placeholder": "按关键字过滤模型名，如 sd2 / seedance / image"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "FLOAT", "INT")
    RETURN_NAMES = ("report", "model_ids", "balance", "today_count")
    OUTPUT_TOOLTIPS = ("可读报告（接『显示文字』看）", "模型名列表，每行一个", "余额", "今日已生成次数")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, api_config, filter=""):
        cfg = ensure_config(api_config)
        # /v1/balance 实测在普通令牌上返回 **401**（2026-08-19 用真 Key 验过），
        # 所以模型清单以 /v1/models 为准，价格表拿得到就顺带显示。
        data = {}
        try:
            resp = api_request(cfg, "GET", "/v1/balance", retries=1, timeout=60)
            data = resp.json() if resp.content else {}
        except Exception as exc:                                # noqa: BLE001
            print(f"[Respect] 鹤 /v1/balance 取不到（{exc}）—— 只列模型，不显示余额价格")

        prices = data.get("current_prices") or {}
        if not prices:
            mr = api_request(cfg, "GET", "/v1/models", retries=1, timeout=60)
            md = mr.json() if mr.content else {}
            prices = {m.get("id"): "" for m in (md.get("data") or []) if m.get("id")}
        kw = (filter or "").strip().lower()
        rows, ids = [], []
        def _order(k):
            v = prices.get(k)
            return (0, v) if isinstance(v, (int, float)) else (1, 0)

        for name in sorted(prices, key=_order):
            if kw and kw not in name.lower():
                continue
            ids.append(name)
            rows.append(f"  {name:<34} {prices[name] if prices[name] != "" else "(价格未给)"}")

        bal = float(data.get("balance") or 0)
        used = data.get("used")
        report = (
            f"鹤 账户\n"
            f"  余额={bal} {data.get('currency', '')}"
            + (f"（已用 {used}）" if used is not None else "")
            + f"\n  等级={data.get('tier_name') or data.get('tier') or '未给'}"
            f"  今日已生成={data.get('today_count', '未给')} 次\n\n"
            f"当前适用价格表（{len(rows)} 个模型，按价格升序）：\n" + "\n".join(rows)
        )
        if not rows:
            report += "  （没返回 current_prices —— 换个过滤词，或该 Key 暂无可用模型）"
        report += "\n\n注：价格随 VIP 等级变，这张表就是该 Key 的真实可用清单，别照文档抄模型名。"
        print(f"[Respect] 鹤 余额={bal} 等级={data.get('tier', '?')} 可用模型 {len(ids)} 个")
        return (report, "\n".join(ids), bal, int(data.get("today_count") or 0))


# ---------------------------------------------------------------------------
# ⑦ 鹤 虚拟资产管理（列表 / 资产组状态 / 能力配置 / 删除）
# ---------------------------------------------------------------------------


HE_ASSET_ACTIONS = ["查询资产组状态", "查询资产列表", "查询上传能力配置", "删除资产"]


class RespectHeAssetManage:
    """鹤 虚拟资产管理。上传之外的 4 个接口合成一个节点，用 `action` 选。

    **「查询资产组状态」是最该先跑的那个**：文档写明 `group_status` 和 `status`
    **都为 active** 时资产组才可用于视频生成。单个资产 active 不代表能用 ——
    组没好就提交，视频那边照样失败，而且看不出原因。
    """

    DESCRIPTION = ("鹤 虚拟资产管理：查资产组状态(group_status+status 都 active 才能用于生成)、"
                   "列资产、查上传能力(configured:true 才支持)、删资产。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://api.paisio.online"}),
                "action": (HE_ASSET_ACTIONS, {"default": "查询资产组状态"}),
            },
            "optional": {
                "asset_id": ("STRING", {"default": "", "multiline": False, "placeholder": "删除资产时必填（va_xxx）"}),
                "model": ("STRING", {"default": "", "multiline": False, "placeholder": "查上传能力时填模型名"}),
                "page": ("INT", {"default": 1, "min": 1, "max": 999, "tooltip": "查列表用"}),
                "page_size": ("INT", {"default": 20, "min": 1, "max": 100}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "BOOLEAN")
    RETURN_NAMES = ("report", "asset_ids", "ready")
    OUTPUT_TOOLTIPS = ("可读结果", "资产 ID 列表，每行一个", "资产组是否已就绪（可用于视频生成）")
    FUNCTION = "run"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def run(self, api_config, action, asset_id="", model="", page=1, page_size=20):
        cfg = ensure_config(api_config)
        aid = (asset_id or "").strip()

        if action == "删除资产":
            if not aid:
                raise RespectAPIError("删除资产必须填 asset_id（va_xxx）")
            resp = api_request(cfg, "DELETE", f"/v1/virtual-assets/{aid}", retries=1, timeout=60)
            data = resp.json() if resp.content else {}
            return (f"已删除 {aid}\n{json.dumps(data, ensure_ascii=False)[:300]}", "", False)

        if action == "查询上传能力配置":
            params = {"model": model.strip()} if (model or "").strip() else None
            resp = api_request(cfg, "GET", "/v1/virtual-assets/config", params=params,
                               retries=1, timeout=60)
            data = resp.json() if resp.content else {}
            ok = bool(data.get("configured"))
            return (f"configured={ok}（true 才支持虚拟资产上传）\n"
                    f"{json.dumps(data, ensure_ascii=False)[:600]}", "", ok)

        if action == "查询资产列表":
            resp = api_request(cfg, "GET", "/v1/virtual-assets",
                               params={"page": int(page), "page_size": int(page_size)},
                               retries=1, timeout=60)
            data = resp.json() if resp.content else {}
            arr = data.get("data") or data.get("assets") or []
            ids, rows = [], []
            for a in arr if isinstance(arr, list) else []:
                if not isinstance(a, dict):
                    continue
                i = str(a.get("id") or a.get("asset_id") or "")
                if i:
                    ids.append(i)
                rows.append(f"  {i:<40} {a.get('status', '?'):<10} {a.get('type', '')}")
            return (f"第 {page} 页，共 {len(rows)} 项：\n" + "\n".join(rows), "\n".join(ids), False)

        # 查询资产组状态
        resp = api_request(cfg, "GET", "/v1/virtual-assets/group", retries=1, timeout=60)
        data = resp.json() if resp.content else {}
        gs = str(data.get("group_status") or "")
        st = str(data.get("status") or "")
        ready = gs == "active" and st == "active"
        note = ("✅ 资产组已就绪，可以用于视频生成" if ready else
                "⏳ **还不能用于视频生成** —— 文档要求 group_status 和 status 都为 active。"
                "单个资产 active 不代表组好了，这时候提交视频会失败且看不出原因，"
                "每 2–3 秒再查一次。")
        return (f"group_status={gs or '未给'}  status={st or '未给'}\n{note}\n\n"
                f"{json.dumps(data, ensure_ascii=False)[:600]}", "", ready)


NODE_CLASS_MAPPINGS = {
    "RespectHeVideo": RespectHeVideo,
    "RespectHeSeedance25": RespectHeSeedance25,
    "RespectHeImage": RespectHeImage,
    "RespectHeImageEdit": RespectHeImageEdit,
    "RespectHeAssetUpload": RespectHeAssetUpload,
    "RespectHeBalance": RespectHeBalance,
    "RespectHeAssetManage": RespectHeAssetManage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectHeVideo": "Respect 鹤 视频（sd2/sd3/seedance 旧规格）",
    "RespectHeSeedance25": "Respect 鹤 Seedance 2.5（含首尾帧）",
    "RespectHeImage": "Respect 鹤 图片生成（统一接口）",
    "RespectHeImageEdit": "Respect 鹤 图生图/多图融合（≤16张）",
    "RespectHeAssetUpload": "Respect 鹤 虚拟资产上传（图/视频/音频）",
    "RespectHeBalance": "Respect 鹤 余额与价格表（先查再选模型）",
    "RespectHeAssetManage": "Respect 鹤 虚拟资产管理（组状态/列表/删除）",
}
