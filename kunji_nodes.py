"""Respect ComfyUI 扩展 - 坤鸡 图片（`https://img.yunfei.best`）专用节点。

按坤鸡「图生图接口」文档：

- 图生图：`POST /v1/images/edits`，`multipart/form-data`
  必填 `image`(file) / `model`(如 gpt-image-2) / `prompt` / `response_format`(示例 b64_json)，可选 `size`
  返回 `data[0].b64_json`
- 文生图：无参考图时走 `POST /v1/images/generations`（JSON，同一套字段）

坤鸡的**视频**用 `Respect Grok-Video 视频（坤鸡分支）`，注意两者 base_url 可能不同：
图片是 `https://img.yunfei.best`，视频是你的坤鸡视频网关地址。
"""

from __future__ import annotations

import base64
import json


from .video_nodes import _async_extract_url, _async_poll, _sd2_extract_task_id
from .utils import (
    RespectAPIError,
    download_to_output,
    dynamic_url_inputs,
    api_request,
    dynamic_image_inputs,
    ensure_config,
    expand_image_frames,
    extract_image_payloads,
    resolve_image_to_tensor,
    tensor_to_b64,
    tensors_concat,
)

CATEGORY = "Respect/坤鸡"

KUNJI_IMAGE_MODELS = [
    # 2026-08-19 实拉：/v1/models 只返回 gpt-image-2（按令牌分组过滤后），
    # /api/pricing 另外列出两个 gemini。
    # **上一版写的 gpt-image-1 和 nano-banana 都查不到** —— 照着旧材料抄的。
    # 这家**没有 4K 型号**：整个目录里连 2k/4k 字样都没有。
    "gpt-image-2",
    "gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview",
]
# 文档：size **1K 分组最高 1K；4K 分组支持 1K/2K/4K；默认 auto**。
# 所以 4K 是有的 —— 但**取决于你的令牌在哪个分组**，不是模型名的区别。
# 档位写法和像素写法都收（文档正文用档位、curl 示例用 1024x1536）。
KUNJI_SIZES = ["auto", "1K", "2K", "4K",
               "1024x1024", "1536x1024", "1024x1536", "2048x2048", "1792x1024", "1024x1792"]
KUNJI_FORMATS = ["b64_json", "url"]
# 文档：high 分组支持 high，其他分组默认 medium
KUNJI_QUALITY = ["(不传)", "high", "medium", "low"]


class RespectKunjiImage:
    """坤鸡 图片（`img.yunfei.best`）。接了参考图走 `/v1/images/edits`（multipart），否则 `/v1/images/generations`。

    `response_format` 文档要求必填，示例用 `b64_json`（返回 `data[0].b64_json`）。
    参考图数量可变：填 `inputcount` 后点节点上的「更新输入口」；每个槽接 IMAGE 批次会展开成多张。
    """

    DESCRIPTION = ("坤鸡图片(base_url=https://img.yunfei.best)。有参考图→/v1/images/edits(multipart，重复 image 字段)，"
                   "无参考图→/v1/images/generations。size 可填 1K/2K/4K 档位或像素（**4K 要令牌在 4K 分组**）；quality=high 需 high 分组。⚠ 返回的 url **只保存 15 分钟**，尽快下载。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://img.yunfei.best"}),
                "model": (KUNJI_IMAGE_MODELS, {"default": "gpt-image-2", "tooltip": "上新模型用 custom_model 填"}),
                "prompt": ("STRING", {"default": "", "multiline": True, "tooltip": "图片编辑/生成提示词（必填）"}),
                "size": (KUNJI_SIZES, {"default": "1024x1024", "tooltip": "图片尺寸；可用 custom_size 覆盖"}),
                "response_format": (KUNJI_FORMATS, {"default": "b64_json", "tooltip": "文档必填，示例 b64_json"}),
            },
            "optional": {
                "image_1": ("IMAGE", {"tooltip": "参考图（接了就走 /v1/images/edits）"}),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "n": ("INT", {"default": 1, "min": 1, "max": 10, "tooltip": "生成数量（文档未列，按 OpenAI 惯例）"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，如 2048x2048"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 32, "step": 1, "tooltip": "参考图接口数量；改完点『更新输入口』按钮"}),
                "quality": (KUNJI_QUALITY, {"default": "(不传)", "tooltip": "文档：high 分组才支持 high，其他分组默认 medium。选(不传)就不带该字段"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, size, response_format,
                 n=1, custom_model="", custom_size="", inputcount=4, quality="(不传)", **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        size = (custom_size or "").strip() or size
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        frames = expand_image_frames(dynamic_image_inputs(kwargs))
        if frames:
            files: list = [
                ("model", (None, model)),
                ("prompt", (None, prompt)),
                ("size", (None, size)),
                ("response_format", (None, response_format)),
                ("n", (None, str(int(n)))),
            ]
            if not quality.startswith("("):
                files.append(("quality", (None, quality)))
            for i, frame in enumerate(frames):
                b64 = tensor_to_b64(frame, fmt="PNG", max_side=2048)
                if not b64:
                    continue
                raw = base64.b64decode(b64[0].split(",", 1)[1])
                # 文档是单个 image 字段；多张按 OpenAI 惯例重复该字段
                files.append(("image", (f"ref_{i + 1}.png", raw, "image/png")))
            resp = api_request(cfg, "POST", "/v1/images/edits", files=files,
                               retries=2, timeout=max(cfg.timeout, 300))
        else:
            body = {
                "model": model, "prompt": prompt, "size": size,
                "response_format": response_format, "n": int(n),
            }
            if not quality.startswith("("):
                body["quality"] = quality
            resp = api_request(cfg, "POST", "/v1/images/generations", json_body=body,
                               retries=2, timeout=max(cfg.timeout, 300))

        data = resp.json() if resp.content else {}
        items = extract_image_payloads(data)
        if not items:
            raise RespectAPIError(f"未能从响应中提取图片: {json.dumps(data, ensure_ascii=False)[:400]}")
        tensors = [t for t in (resolve_image_to_tensor(i, cfg) for i in items) if t is not None]
        if not tensors:
            raise RespectAPIError(f"取到结果但无法解析为图片: {str(items)[:300]}")
        return (tensors_concat(tensors), model)


# ---------------------------------------------------------------------------
# ② 坤鸡 香蕉（Gemini 原生 generateContent）
# ---------------------------------------------------------------------------

# 文档「比例与像素」那张表。**这是 4K 真正落地的地方** ——
# gpt-image-2 那条线的 4K 要看令牌分组，而香蕉这条线直接由 imageSize 决定。
KUNJI_BANANA_MODELS = ["gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview"]
KUNJI_BANANA_SIZES = ["1K", "2K", "4K"]        # 文档：**K 必须大写**
KUNJI_BANANA_RATIOS = ["(自动)", "1:1", "16:9", "9:16", "4:3", "3:4",
                       "3:2", "2:3", "5:4", "4:5", "21:9",
                       # 下面 4 个**只有香蕉2**（gemini-3.1-flash）支持
                       "8:1", "4:1", "1:4", "1:8"]
_BANANA_WIDE_ONLY = ("8:1", "4:1", "1:4", "1:8")
KUNJI_MODALITIES = ["IMAGE", "TEXT", "IMAGE,TEXT"]


class RespectKunjiBanana:
    """坤鸡 香蕉图片（`POST /v1beta/models/{model}:generateContent`）。

    **和 gpt-image-2 完全不是一套**：走 Gemini 原生格式，模型名在 **URL 里**、
    不在 body 里；鉴权头是 `x-goog-api-key`（也兼容 Bearer）。

    - `imageSize`：`1K` / `2K` / `4K` —— **K 必须大写**，这里就是 4K 的入口
    - `aspectRatio`：省略=自动跟参考图；**不要传 `auto`**（文档明说）
    - `8:1 / 4:1 / 1:4 / 1:8` 超宽长条**只有香蕉2**（gemini-3.1-flash）支持
    - `responseModalities`：`IMAGE` 回 base64、`TEXT` 回网址、两个都要就都回
    - 参考图：`inline_data`(base64) 或 `file_data`(公网URL)，可混用，按顺序处理
    """

    DESCRIPTION = ("坤鸡 香蕉（Gemini 原生格式，模型名在URL里）。imageSize=1K/2K/4K(**K大写**)，"
                   "aspectRatio 省略即自动、别传 auto；8:1/4:1/1:4/1:8 仅香蕉2支持。"
                   "参考图 inline_data(base64) 或 file_data(URL) 可混用。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://img.yunfei.best"}),
                "model": (KUNJI_BANANA_MODELS, {"default": "gemini-3-pro-image-preview", "tooltip": "香蕉Pro=画质档；香蕉2=速度档且支持超宽比例"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "imageSize": (KUNJI_BANANA_SIZES, {"default": "1K", "tooltip": "1K/2K/4K —— 这条线的 4K 不看令牌分组"}),
                "aspectRatio": (KUNJI_BANANA_RATIOS, {"default": "(自动)", "tooltip": "选(自动)就不发该字段（跟参考图）。文档明说别传 auto"}),
            },
            "optional": {
                "image_1": ("IMAGE", {"tooltip": "参考图 → inline_data(base64)"}),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "ref_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考图公网URL，每行一个 → file_data；可和上面的 IMAGE 混用"}),
                "responseModalities": (KUNJI_MODALITIES, {"default": "IMAGE", "tooltip": "IMAGE=回base64；TEXT=回网址；IMAGE,TEXT=都回"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 16, "step": 1, "tooltip": "参考图接口数量；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_url", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, imageSize, aspectRatio,
                 ref_urls="", responseModalities="IMAGE", custom_model="",
                 inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")
        if aspectRatio in _BANANA_WIDE_ONLY and "3.1-flash" not in model:
            raise RespectAPIError(
                f"{aspectRatio} 这种超宽比例**只有香蕉2**（gemini-3.1-flash-image-preview）支持，"
                f"当前选的是 {model}。换模型，或改用常规比例。")

        parts: list = [{"text": prompt}]
        for frame in expand_image_frames(dynamic_image_inputs(kwargs)):
            b = tensor_to_b64(frame, fmt="PNG", max_side=2048)
            if b:
                parts.append({"inline_data": {"mime_type": "image/png",
                                              "data": b[0].split(",", 1)[1]}})
        for u in [ln.strip() for ln in (ref_urls or "").splitlines() if ln.strip()]:
            if not u.startswith(("http://", "https://")):
                raise RespectAPIError(f"file_data 要公网 URL，这个不是：{u[:60]}")
            parts.append({"file_data": {"mime_type": "image/png", "file_uri": u}})

        img_cfg: dict = {"imageSize": imageSize}
        if not aspectRatio.startswith("("):
            # 文档：需要自动比例时**省略**，不要传 auto
            img_cfg["aspectRatio"] = aspectRatio
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseModalities": responseModalities.split(","),
                "imageConfig": img_cfg,
            },
        }

        # 模型名在**路径**里，不在 body 里；鉴权头文档给的是 x-goog-api-key
        base = cfg.normalized_base().rsplit("/v1", 1)[0]
        path = f"{base}/v1beta/models/{model}:generateContent"
        headers = {"x-goog-api-key": cfg.resolve_api_key(),
                   "Authorization": f"Bearer {cfg.resolve_api_key()}",
                   "Content-Type": "application/json",
                   "Accept": "application/json"}
        print(f"[Respect] 坤鸡 香蕉 {model}: imageSize={imageSize} "
              f"aspectRatio={img_cfg.get('aspectRatio', '(自动)')} 参考图{len(parts) - 1}项")
        resp = api_request(cfg, "POST", path, json_body=body, headers=headers,
                           retries=2, timeout=max(cfg.timeout, 600))
        data = resp.json() if resp.content else {}

        # IMAGE → parts[].inline_data.data；TEXT → parts[].file_data.file_uri
        items, url = [], ""
        try:
            for part in data["candidates"][0]["content"]["parts"]:
                inline = part.get("inline_data") or part.get("inlineData") or {}
                if inline.get("data"):
                    mime = inline.get("mime_type") or inline.get("mimeType") or "image/png"
                    items.append(f"data:{mime};base64,{inline['data']}")
                fd = part.get("file_data") or part.get("fileData") or {}
                if fd.get("file_uri") or fd.get("fileUri"):
                    url = fd.get("file_uri") or fd.get("fileUri")
                    items.append(url)
        except (KeyError, IndexError, TypeError):
            pass
        if not items:
            items = extract_image_payloads(data)
        if not items:
            raise RespectAPIError(f"香蕉没返回图片: {json.dumps(data, ensure_ascii=False)[:400]}")

        tensors = [t for t in (resolve_image_to_tensor(i, cfg) for i in items) if t is not None]
        if not tensors:
            raise RespectAPIError(f"取到结果但无法解析为图片: {str(items)[:200]}")
        return (tensors_concat(tensors), url, model)


# ---------------------------------------------------------------------------
# ③ 坤鸡 veo 视频（异步：提交 → 轮询 → 取片）
# ---------------------------------------------------------------------------

KUNJI_VEO_MODELS = ["veo-3.1-fast-generate-preview", "veo-3.1-generate-preview",
                    "veo-3.1-generate-preview-ref"]
KUNJI_VEO_MODES = ["文生视频", "单图生视频", "首尾帧视频", "多参考图视频"]
KUNJI_VEO_RATIOS = ["16:9", "9:16"]
KUNJI_VEO_DURATIONS = [4, 6, 8]


class RespectKunjiVeo:
    """坤鸡 veo 视频（`POST /v1/videos` → `GET /v1/videos/{id}` 轮询）。固定 720p。

    四种模式的字段不一样，选错模型会直接失败：

    | 模式 | 模型 | 图片字段 |
    |---|---|---|
    | 文生 | 任意 | 无 |
    | 单图 | fast / 标准 | `image_url`（单个字符串）|
    | 首尾帧 | fast / 标准 | `image_urls`（第1张首帧、第2张尾帧）|
    | 多参考图 | **必须 `-ref`** | `image_urls` 数组 |

    ⚠ **多参考图模式下 duration 固定 8、比例固定 16:9** —— 传 4/6 秒或 9:16
    会生成失败（文档原话）。失败不扣费，但白等一轮。
    图片**不支持** `{"data":…,"mime_type":…}` 对象格式，只收 URL / dataURL / 裸 base64。
    """

    DESCRIPTION = ("坤鸡 veo 视频（720p，4/6/8秒）。单图=image_url、首尾帧/多参考=image_urls；"
                   "多参考图必须用 -ref 模型且**固定 8 秒 + 16:9**，否则失败(不扣费)。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://img.yunfei.best"}),
                "model": (KUNJI_VEO_MODELS, {"default": "veo-3.1-fast-generate-preview"}),
                "prompt": ("STRING", {"default": "", "multiline": True, "tooltip": "只写运动和镜头要求，**别写比例和时长**（文档明说）"}),
                "generation_mode": (KUNJI_VEO_MODES, {"default": "单图生视频"}),
                "duration": ("INT", {"default": 4, "min": 4, "max": 8, "tooltip": "只有 4/6/8；多参考图模式固定 8"}),
                "aspect_ratio": (KUNJI_VEO_RATIOS, {"default": "16:9", "tooltip": "多参考图模式固定 16:9"}),
                "poll_interval": ("INT", {"default": 8, "min": 5, "max": 60, "tooltip": "文档建议 5~10 秒"}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "首帧/参考图：公网直链、dataURL 或裸 base64"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False, "placeholder": "尾帧（首尾帧模式）/ 第2张参考图"}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "extra_image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "追加参考图，每行一个"}),
                "generate_audio": ("BOOLEAN", {"default": True, "tooltip": "文档默认 true"}),
                "negative_prompt": ("STRING", {"default": "", "multiline": True, "placeholder": "负向提示词（可选）"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 16, "step": 1, "tooltip": "参考图URL接口数量；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("在线视频 URL", "下载到本地的路径", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, generation_mode, duration, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 extra_image_urls="", generate_audio=True, negative_prompt="",
                 custom_model="", save_dir="", filename="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        imgs = dynamic_url_inputs(kwargs)
        imgs += [ln.strip() for ln in (extra_image_urls or "").splitlines() if ln.strip()]
        dur, ratio = int(duration), aspect_ratio

        if generation_mode == "多参考图视频":
            # 文档：这个模式必须用 -ref 模型，且 duration 固定 8、比例固定 16:9。
            # 传 4/6 秒或 9:16 会**生成失败**（失败不扣费，但白等一轮轮询）。
            if "-ref" not in model:
                raise RespectAPIError(
                    f"多参考图模式必须用 veo-3.1-generate-preview-ref，当前是 {model}。")
            if not imgs:
                raise RespectAPIError("多参考图模式至少要 1 张参考图")
            if dur != 8 or ratio != "16:9":
                print(f"[Respect] 坤鸡 veo 多参考图模式固定 8 秒 + 16:9，"
                      f"已把 {dur}秒/{ratio} 纠正（否则会生成失败）")
                dur, ratio = 8, "16:9"
        elif generation_mode == "首尾帧视频" and len(imgs) < 2:
            raise RespectAPIError("首尾帧需要 2 张图（第1张首帧、第2张尾帧）")
        elif generation_mode == "单图生视频" and not imgs:
            raise RespectAPIError("单图生视频需要 1 张首帧图")
        if dur not in KUNJI_VEO_DURATIONS:
            near = min(KUNJI_VEO_DURATIONS, key=lambda d: abs(d - dur))
            print(f"[Respect] 坤鸡 veo 只支持 {KUNJI_VEO_DURATIONS} 秒，已把 {dur} 纠正为 {near}")
            dur = near

        body: dict = {"model": model, "prompt": prompt,
                      "duration": dur, "aspect_ratio": ratio,
                      "generate_audio": bool(generate_audio)}
        if (negative_prompt or "").strip():
            body["negative_prompt"] = negative_prompt.strip()
        if generation_mode == "单图生视频":
            body["image_url"] = imgs[0]          # 单个字符串，不是数组
        elif generation_mode == "首尾帧视频":
            body["image_urls"] = imgs[:2]        # [首帧, 尾帧]
        elif generation_mode == "多参考图视频":
            body["image_urls"] = imgs

        print(f"[Respect] 坤鸡 veo {model} {generation_mode}: {dur}秒 {ratio} 图{len(imgs)}张")
        resp = api_request(cfg, "POST", "/v1/videos", json_body=body,
                           retries=2, timeout=max(cfg.timeout, 300))
        data = resp.json() if resp.content else {}
        url = _async_extract_url(data)
        task_id = _sd2_extract_task_id(data)
        if not url:
            if not task_id:
                raise RespectAPIError(f"提交没返回任务 ID: {json.dumps(data, ensure_ascii=False)[:400]}")
            url = _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))

        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="kunji_veo",
                                           save_dir=save_dir, filename=filename)
            except Exception as exc:                        # noqa: BLE001
                print(f"[Respect] 坤鸡 veo 下载失败: {exc}")
        return (url, local, task_id or "")


NODE_CLASS_MAPPINGS = {
    "RespectKunjiImage": RespectKunjiImage,
    "RespectKunjiBanana": RespectKunjiBanana,
    "RespectKunjiVeo": RespectKunjiVeo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectKunjiImage": "Respect 坤鸡 图片（gpt-image-2）",
    "RespectKunjiBanana": "Respect 坤鸡 香蕉（Gemini原生·4K）",
    "RespectKunjiVeo": "Respect 坤鸡 veo 视频（720p）",
}
