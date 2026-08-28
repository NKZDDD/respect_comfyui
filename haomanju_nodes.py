"""Respect ComfyUI 扩展 - 好漫剧（`https://www.75api.com`）节点。

文档：《好漫剧API对接文档》（村长服务中心，2026-08-24 修改）

这家是 **New API 网关**，但**七个分支用了四种不同的协议**，选模型就等于选协议：

| 分支 | 端点 | 格式 | 结果在哪 |
|---|---|---|---|
| GROK 视频 | `/v1/videos` | **multipart** | 轮询 `/v1/videos/{id}` |
| minimax_h3 视频 | `/v1/videos` | **JSON** | 同上，完成时带 `video_url` |
| Omni-flash 视频 | `/v1/video/generations` | JSON | 轮询同路径，**状态嵌在 data.data 里** |
| Sora2 / VEO 视频 | `/v1/chat/completions` | JSON | `choices[0].message.content` 里的 `<video src=…>` |
| 香蕉图片 | `/v1/chat/completions` | JSON | 同上，是 markdown `![](url)` |
| GPT-image-2 | `/v1/images/generations` `/edits` | JSON / multipart | `data[0].b64_json` |

**最容易搞错的一处**：GROK 和 minimax_h3 **同一个端点 `/v1/videos`**，
但 GROK 是 multipart + `input_reference[]` 文件上传，H3 是 JSON + `images` 链接数组。
发错格式不会得到"格式错误"这种明白话，多半是参考图整个丢掉。

⚠ **模型名有两套**。文档里写的（`grok-video-6s`、`sora2-12s-16x9`…）和
`/api/pricing` 实拉出来的（`grok-1.5-fast-10s`、`sora3-933`…）**只有
`gpt-image-2` 和 `minimax_h3` 两个重合**。文档自己的示例也印证网关会改名：
请求 `sora2-12s-16x9`、响应回 `firefly-sora2-12s-16x9`。
所以两套都放进下拉了，**文档名在前**；跑不通就换另一套（503 不计费）。
"""

from __future__ import annotations

import json
import re
import time

from .utils import (RespectAPIError, api_request, download_to_output,
                    dynamic_image_inputs, dynamic_url_inputs, ensure_config,
                    expand_image_frames, extract_image_payloads,
                    resolve_image_to_tensor, tensor_to_b64, tensors_concat)
from .video_nodes import (_async_extract_url, _async_poll, _ASYNC_DONE,
                          _ASYNC_FAIL, _sd2_extract_task_id)

CATEGORY = "Respect/好漫剧"
BASE_HINT = "base_url 填 https://www.75api.com"

# --- 一、GROK 视频（multipart）-------------------------------------------
HMJ_GROK_MODELS = [
    "grok-video-10s", "grok-video-6s", "grok-video-12s",     # 文档名（12s 目前只跑 10 秒）
    "grok-1.5-fast-10s", "grok-imagine-video-1.5-preview",   # pricing 实拉名
]
HMJ_GROK_SIZES = ["720x1280", "1280x720", "1024x1024"]
HMJ_GROK_SECONDS = ["10", "6", "12"]
HMJ_GROK_MAX_REFS = 7

# --- 七、minimax_h3（JSON，同端点）----------------------------------------
# sd-* 四个是 pricing 里有、**文档没写**的。它们和 h3 同属这个端点的 JSON 协议
# （同一家 New API 网关、同一个 /v1/videos），所以放在一起；字段不对会 400，
# 而 400 不计费 —— 比猜一套形状发出去安全。
HMJ_H3_MODELS = [
    "minimax_h3",
    "sd-2.5-c1", "sd-2-c1", "sd-2-c6", "sd-2-fast",
    "sora3-933", "sora3-fast", "veo-3.1-fast-generate-preview",
]
HMJ_H3_RESOLUTIONS = ["768p", "480p"]
HMJ_H3_RATIOS = ["9:16", "16:9"]
HMJ_H3_MAX_IMAGES, HMJ_H3_MAX_AUDIOS = 8, 3

# --- 六、Omni-flash（/v1/video/generations）--------------------------------
HMJ_OMNI_MODELS = ["omni-flash-4s", "omni-flash-6s", "omni-flash-8s",
                   "omni-flash-10s", "gemini-omni-flash-preview"]
HMJ_OMNI_RATIOS = ["landscape", "portrait", "square"]

# --- 四、Sora2 / 五、VEO（chat/completions）--------------------------------
HMJ_SORA_MODELS = ["sora2-12s-16x9", "sora2-12s-9x16", "sora3-933", "sora3-fast"]
# VEO：firefly-veo31-* 是**帧模式**（1图=首帧、2图=首尾帧）；
#      firefly-veo31-ref-* 是**参考图模式**（1~3 张参考图）。两者不能混用。
HMJ_VEO_FRAME_MODELS = [
    f"firefly-veo31-{sec}-{ratio}-{res}"
    for sec in ("4s", "6s") for ratio in ("16x9", "9x16") for res in ("1080p", "720p")
]
HMJ_VEO_REF_MODELS = ["firefly-veo31-ref-8s-16x9-1080p"]
HMJ_CHAT_VIDEO_MODELS = (HMJ_SORA_MODELS + HMJ_VEO_FRAME_MODELS
                         + HMJ_VEO_REF_MODELS + ["veo-3.1-fast-generate-preview"])

# --- 二、香蕉（chat/completions）-------------------------------------------
HMJ_BANANA_PRO = [f"firefly-nano-banana-pro-{k}-{r}"
                  for k in ("2k", "4k")
                  for r in ("16x9", "9x16", "4x3", "1x1", "3x4")]
HMJ_BANANA_MODELS = (HMJ_BANANA_PRO + ["nano-banana2"]
                     + ["nano-banana-pro-2k", "nano-banana-pro-4k",
                        "nano-banana-2-2k", "nano-banana-2-4k"])
# 香蕉2 独有：顶层 size 字段，形如 16x9-2k
HMJ_BANANA2_SIZES = ["(不传)", "16x9-2k", "9x16-2k", "1x1-2k",
                     "16x9-4k", "9x16-4k", "1x1-4k"]

# --- 三、GPT-image-2 --------------------------------------------------------
HMJ_IMAGE_MODELS = ["gpt-image-2", "gpt-image2-2k", "gpt-image2-4k"]
HMJ_IMAGE_SIZES = ["1792x1024", "1024x1792", "1024x1024", "1536x1152"]
HMJ_FORMATS = ["b64_json", "url"]


def _lines(s: str, cap: int) -> list:
    return [ln.strip() for ln in (s or "").splitlines() if ln.strip()][:cap]


def _http_only(urls: list, what: str) -> list:
    bad = [u for u in urls if not u.startswith(("http://", "https://"))]
    if bad:
        raise RespectAPIError(
            f"{what}只收公网 http(s) 链接，这些不是：{bad[:2]}\n"
            f"本地图请接『Respect 对象存储上传』换链接。")
    return urls


def _finish(cfg, url: str, task_id: str, prefix: str, auto_download: bool,
            save_dir: str, filename: str) -> tuple:
    local = ""
    if auto_download and url:
        try:
            local = download_to_output(url, cfg, prefix=prefix,
                                       save_dir=save_dir, filename=filename)
        except Exception as exc:                            # noqa: BLE001
            print(f"[Respect] 好漫剧 {prefix} 下载失败: {exc}")
    return (url, local, task_id or "")


# ---------------------------------------------------------------------------
# ① GROK 视频（multipart + input_reference[] 文件上传）
# ---------------------------------------------------------------------------


class RespectHmjGrokVideo:
    """好漫剧 GROK 视频（文档一）。`POST /v1/videos`，**multipart/form-data**。

    和本插件里所有别的 `/v1/videos` 都不一样：这条是**上传文件**，不是发链接。
    参考图走 `input_reference[]`（可重复，最多 7 个），**本节点直接吃 IMAGE**，
    不需要对象存储。

    prompt 里用 **`@图1` / `@图2`** 引用参考图 —— 编号就是接入口的顺序，
    所以 image_1 是 @图1、image_2 是 @图2，接错顺序画面就配错人。
    """

    DESCRIPTION = ("好漫剧 GROK 视频（文档一）。**multipart** + input_reference[] 文件上传（≤7），"
                   "直接吃 IMAGE 不用图床；prompt 里用 @图1/@图2 引用，编号=接入口顺序。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": BASE_HINT}),
                "model": (HMJ_GROK_MODELS, {"default": "grok-video-10s", "tooltip": "文档说 12s 目前只跑 10 秒"}),
                "prompt": ("STRING", {"default": "", "multiline": True, "tooltip": "引用参考图用 @图1 @图2，编号对应下面的接入口顺序"}),
                "seconds": (HMJ_GROK_SECONDS, {"default": "10", "tooltip": "**必须和模型名里的秒数一致**"}),
                "size": (HMJ_GROK_SIZES, {"default": "720x1280"}),
                "poll_interval": ("INT", {"default": 8, "min": 3, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "image_1": ("IMAGE", {"tooltip": "→ @图1"}),
                "image_2": ("IMAGE", {"tooltip": "→ @图2"}),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "resolution_name": ("STRING", {"default": "720p", "multiline": False, "placeholder": "文档：建议写死 720p"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 7, "step": 1, "tooltip": "参考图接口数量（≤7）；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, seconds, size, poll_interval,
                 poll_timeout, auto_download, resolution_name="720p",
                 custom_model="", save_dir="", filename="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")
        # 模型名里带秒数，和 seconds 对不上文档说会失败
        m = re.search(r"-(\d+)s\b", model)
        if m and m.group(1) != seconds:
            print(f"[Respect] ⚠ 好漫剧 GROK：模型 {model} 是 {m.group(1)} 秒，"
                  f"但 seconds 填的是 {seconds} —— 文档要求两者一致，已按模型名改成 {m.group(1)}")
            seconds = m.group(1)

        files: list = [
            ("model", (None, model)),
            ("prompt", (None, prompt)),
            ("size", (None, size)),
            ("seconds", (None, str(seconds))),
            ("resolution_name", (None, (resolution_name or "720p").strip() or "720p")),
        ]
        import base64
        frames = expand_image_frames(dynamic_image_inputs(kwargs))[:HMJ_GROK_MAX_REFS]
        for i, frame in enumerate(frames, start=1):
            b64 = tensor_to_b64(frame, fmt="PNG", max_side=2048)
            if not b64:
                continue
            raw = base64.b64decode(b64[0].split(",", 1)[1])
            files.append(("input_reference[]", (f"ref_{i}.png", raw, "image/png")))

        print(f"[Respect] 好漫剧 GROK {model}: {seconds}秒 {size} 参考图{len(frames)}张（multipart）")
        resp = api_request(cfg, "POST", "/v1/videos", files=files,
                           retries=2, timeout=max(cfg.timeout, 600))
        data = resp.json() if resp.content else {}
        url = _async_extract_url(data)
        task_id = _sd2_extract_task_id(data)
        if not url:
            if not task_id:
                raise RespectAPIError(f"提交没返回任务 ID: {json.dumps(data, ensure_ascii=False)[:400]}")
            url = _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        return _finish(cfg, url, task_id, "hmj_grok", auto_download, save_dir, filename)


# ---------------------------------------------------------------------------
# ② minimax_h3 视频（同端点但是 JSON）
# ---------------------------------------------------------------------------


class RespectHmjH3Video:
    """好漫剧 minimax_h3 视频（文档七）。`POST /v1/videos`，**JSON**。

    和上面的 GROK **同一个端点、不同格式** —— 这条是 JSON + `images` 链接数组，
    不是文件上传。参考图 ≤8 张、音频 ≤3 条，都只收 **http 链接**。

    完成时返回里带 `video_url`（指向 `/v1/videos/{id}/content`，要鉴权）。

    ⚠ 下拉里的 `sd-*` / `sora3-*` / `veo-3.1-*` 是 `/api/pricing` 实拉出来、
    **文档没写**的模型。它们和 h3 同属这个端点，按同一套 JSON 字段发；
    字段不对会 400，而 **400 不计费** —— 比猜一套形状安全。
    """

    DESCRIPTION = ("好漫剧 minimax_h3 视频（文档七）。/v1/videos 但用 **JSON**（GROK 那条是 multipart）；"
                   "images≤8 / audios≤3，**只收 http 链接**；seconds 5-15 字符串。"
                   "sd-*/sora3-* 是 pricing 实拉、文档没写的，同端点同形状试。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": BASE_HINT}),
                "model": (HMJ_H3_MODELS, {"default": "minimax_h3", "tooltip": "minimax_h3 是文档写明的；其余是 pricing 实拉的同端点模型"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "seconds": ("INT", {"default": 10, "min": 5, "max": 15, "tooltip": "5–15；**发出去是字符串**"}),
                "resolution": (HMJ_H3_RESOLUTIONS, {"default": "768p", "tooltip": "只有 480p / 768p"}),
                "aspect_ratio": (HMJ_H3_RATIOS, {"default": "9:16"}),
                "poll_interval": ("INT", {"default": 8, "min": 3, "max": 60}),
                "poll_timeout": ("INT", {"default": 2400, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "参考图 http 链接（接『对象存储上传』）"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "extra_image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "追加参考图链接，每行一个（共≤8）"}),
                "audio_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考音频链接，每行一个（≤3）"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 8, "step": 1, "tooltip": "参考图URL接口数量（≤8）；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, seconds, resolution, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 extra_image_urls="", audio_urls="", custom_model="",
                 save_dir="", filename="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        imgs = dynamic_url_inputs(kwargs) + _lines(extra_image_urls, HMJ_H3_MAX_IMAGES)
        imgs = _http_only(imgs, "minimax_h3 的 images")[:HMJ_H3_MAX_IMAGES]
        auds = _http_only(_lines(audio_urls, HMJ_H3_MAX_AUDIOS), "audios")

        body: dict = {
            "model": model,
            "prompt": prompt,
            "seconds": str(int(seconds)),        # 文档：字符串类型
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        }
        if imgs:
            body["images"] = imgs
        if auds:
            body["audios"] = auds

        print(f"[Respect] 好漫剧 H3 {model}: {seconds}秒 {resolution} {aspect_ratio} "
              f"图{len(imgs)}/音频{len(auds)}（JSON）")
        resp = api_request(cfg, "POST", "/v1/videos", json_body=body,
                           retries=2, timeout=max(cfg.timeout, 300))
        data = resp.json() if resp.content else {}
        url = _async_extract_url(data)
        task_id = _sd2_extract_task_id(data)
        if not url:
            if not task_id:
                raise RespectAPIError(f"提交没返回任务 ID: {json.dumps(data, ensure_ascii=False)[:400]}")
            url = _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        return _finish(cfg, url, task_id, "hmj_h3", auto_download, save_dir, filename)


# ---------------------------------------------------------------------------
# ③ Omni-flash 视频（/v1/video/generations，状态嵌在 data.data 里）
# ---------------------------------------------------------------------------


def _hmj_poll_generations(cfg, task_id: str, interval: int, timeout: int) -> str:
    """轮询 `/v1/video/generations/{task_id}`。

    这条的返回**套了两层**：`{"code":"success","data":{…,"status":"IN_PROGRESS",
    "progress":"30%","data":{"status":"in_progress"}}}`。
    状态是**大写**、进度是**带百分号的字符串**，通用的解析器认不出来，所以单独写。
    """
    start, last = time.time(), ""
    while time.time() - start < timeout:
        resp = api_request(cfg, "GET", f"/v1/video/generations/{task_id}",
                           retries=1, timeout=60)
        data = resp.json() if resp.content else {}
        inner = (data.get("data") or {}) if isinstance(data, dict) else {}
        status = str(inner.get("status") or "").lower()
        if status != last:
            print(f"[Respect] 好漫剧 Omni {task_id}: {status} {inner.get('progress', '')}")
            last = status
        if status in _ASYNC_FAIL or status == "failure":
            raise RespectAPIError(
                f"任务失败：{inner.get('fail_reason') or json.dumps(data, ensure_ascii=False)[:300]}")
        url = _async_extract_url(data)
        if url and (status in _ASYNC_DONE or status == "success"):
            return url
        if status in _ASYNC_DONE or status == "success":
            raise RespectAPIError(f"任务完成但没取到视频地址: {json.dumps(data, ensure_ascii=False)[:300]}")
        time.sleep(interval)
    raise RespectAPIError(f"好漫剧 Omni 轮询超时: {task_id}")


class RespectHmjOmniVideo:
    """好漫剧 Omni-flash 视频（文档六）。`POST /v1/video/generations`。

    **端点又换了一个**（既不是 `/v1/videos` 也不是 chat）。查询是同路径，
    但返回**套了两层**、状态是大写 `IN_PROGRESS`、进度是字符串 `"30%"`。

    参考图只有**单张** `image`（http 链接），文档没给多图字段。
    """

    DESCRIPTION = ("好漫剧 Omni-flash（文档六）。POST /v1/video/generations，查询同路径；"
                   "单张参考图字段是 image（http链接）；aspect_ratio 用 landscape/portrait。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": BASE_HINT}),
                "model": (HMJ_OMNI_MODELS, {"default": "omni-flash-4s", "tooltip": "秒数写在模型名里"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "aspect_ratio": (HMJ_OMNI_RATIOS, {"default": "landscape", "tooltip": "文档示例用的是 landscape，不是 16:9"}),
                "poll_interval": ("INT", {"default": 8, "min": 3, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "image_url": ("STRING", {"default": "", "multiline": False, "placeholder": "单张首帧参考图 http 链接"}),
                "duration": ("INT", {"default": 0, "min": 0, "max": 30, "tooltip": "0=不传（秒数由模型名决定）；文档图生视频示例里带了 duration"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, aspect_ratio, poll_interval,
                 poll_timeout, auto_download, image_url="", duration=0,
                 custom_model="", save_dir="", filename=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        body: dict = {"model": model, "prompt": prompt, "aspect_ratio": aspect_ratio}
        ref = (image_url or "").strip()
        if ref:
            _http_only([ref], "Omni 的 image")
            body["image"] = ref
        if int(duration) > 0:
            body["duration"] = int(duration)

        print(f"[Respect] 好漫剧 Omni {model}: {aspect_ratio} 参考图{'1' if ref else '0'}张")
        resp = api_request(cfg, "POST", "/v1/video/generations", json_body=body,
                           retries=2, timeout=max(cfg.timeout, 300))
        data = resp.json() if resp.content else {}
        url = _async_extract_url(data)
        task_id = _sd2_extract_task_id(data)
        if not url:
            if not task_id:
                raise RespectAPIError(f"提交没返回任务 ID: {json.dumps(data, ensure_ascii=False)[:400]}")
            url = _hmj_poll_generations(cfg, task_id, int(poll_interval), int(poll_timeout))
        return _finish(cfg, url, task_id, "hmj_omni", auto_download, save_dir, filename)


# ---------------------------------------------------------------------------
# ④ Sora2 / VEO 视频（chat/completions，结果是 <video src=…>）
# ---------------------------------------------------------------------------


class RespectHmjChatVideo:
    """好漫剧 Sora2 / VEO 视频（文档四、五）。`POST /v1/chat/completions`。

    **同步返回**，不用轮询：视频链接以 ```html `<video src='…'>` 的形式
    包在 `choices[0].message.content` 里。

    VEO 有两种模式，**模型名决定**、不能混：
    - `firefly-veo31-*`：帧模式，1 张图=首帧、2 张图=首尾帧
    - `firefly-veo31-ref-*`：参考图模式，1~3 张参考图

    参考图放在 messages 的 `image_url` 部件里，收公网链接或 data URI。
    """

    DESCRIPTION = ("好漫剧 Sora2/VEO（文档四、五）。chat/completions **同步**返回，"
                   "视频在 content 的 <video src> 里；VEO 帧模式(firefly-veo31-*) 1图=首帧/2图=首尾帧，"
                   "参考图模式要用 firefly-veo31-ref-*。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": BASE_HINT}),
                "model": (HMJ_CHAT_VIDEO_MODELS, {"default": "sora2-12s-16x9", "tooltip": "秒数/比例/分辨率全写在模型名里"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "image_1": ("IMAGE", {"tooltip": "帧模式=首帧；参考图模式=参考图1"}),
                "image_2": ("IMAGE", {"tooltip": "帧模式=尾帧；参考图模式=参考图2"}),
                "image_3": ("IMAGE",),
                "ref_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考图公网URL，每行一个（填了优先于上面的 IMAGE）"}),
                "timeout": ("INT", {"default": 900, "min": 60, "max": 3600, "tooltip": "同步等待，出片慢时调大"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 3, "min": 1, "max": 3, "step": 1, "tooltip": "参考图接口数量（≤3）；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, auto_download, ref_urls="",
                 timeout=900, custom_model="", save_dir="", filename="",
                 inputcount=3, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        parts: list = [{"type": "text", "text": prompt}]
        urls = _lines(ref_urls, 3)
        if urls:
            _http_only(urls, "参考图")
            for u in urls:
                parts.append({"type": "image_url", "image_url": {"url": u}})
        else:
            for frame in expand_image_frames(dynamic_image_inputs(kwargs))[:3]:
                b = tensor_to_b64(frame, fmt="JPEG", quality=90, max_side=1536)
                if b:
                    parts.append({"type": "image_url", "image_url": {"url": b[0]}})

        n_ref = len(parts) - 1
        # ⚠ 判据必须是 `-ref-`：**"firefly" 里就含 "ref"**（fi-ref-ly），
        # 写成 `"ref" not in model` 的话帧模式的 2 张上限永远不生效。
        is_ref_mode = "-ref-" in model
        if is_ref_mode and n_ref > 3:
            raise RespectAPIError(f"VEO 参考图模式最多 3 张，收到 {n_ref} 张")
        if "veo31" in model and not is_ref_mode and n_ref > 2:
            raise RespectAPIError(
                f"VEO **帧模式**最多 2 张（1张=首帧、2张=首尾帧），收到 {n_ref} 张。\n"
                f"要多图参考请换 firefly-veo31-ref-* 模型。")

        # 无参考图时文档用的是纯字符串 content，有图才用部件数组
        content = prompt if n_ref == 0 else parts
        body = {"model": model, "messages": [{"role": "user", "content": content}]}

        print(f"[Respect] 好漫剧 chat视频 {model}: 参考图{n_ref}张（同步等待，最长 {timeout} 秒）")
        resp = api_request(cfg, "POST", "/v1/chat/completions", json_body=body,
                           retries=1, timeout=max(int(timeout), 120))
        data = resp.json() if resp.content else {}
        url = _async_extract_url(data)
        if not url:
            raise RespectAPIError(
                f"没能从 content 里取到视频地址。原始响应：{json.dumps(data, ensure_ascii=False)[:500]}")
        local = ""
        if auto_download:
            try:
                local = download_to_output(url, cfg, prefix="hmj_chat",
                                           save_dir=save_dir, filename=filename)
            except Exception as exc:                        # noqa: BLE001
                print(f"[Respect] 好漫剧 chat视频 下载失败: {exc}")
        return (url, local, model)


# ---------------------------------------------------------------------------
# ⑤ 香蕉图片（chat/completions，结果是 markdown ![](url)）
# ---------------------------------------------------------------------------


class RespectHmjBanana:
    """好漫剧 香蕉图片（文档二）。`POST /v1/chat/completions`。

    - **香蕉 Pro**：比例和档位**写在模型名里**（`firefly-nano-banana-pro-2k-16x9`），
      不用也不能传 size
    - **香蕉 2**（`nano-banana2`）：模型名不带档位，改用**顶层 `size`** 字段
      （形如 `16x9-2k`），参考图支持 base64

    结果是 markdown 图片链接，包在 `choices[0].message.content` 里。
    """

    DESCRIPTION = ("好漫剧 香蕉图片（文档二）。Pro 的比例/档位在模型名里；"
                   "香蕉2 用顶层 size（如 16x9-2k）。结果是 content 里的 markdown ![](url)。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": BASE_HINT}),
                "model": (HMJ_BANANA_MODELS, {"default": "firefly-nano-banana-pro-2k-16x9"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
            },
            "optional": {
                "image_1": ("IMAGE", {"tooltip": "参考图 → base64 data URI"}),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "ref_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考图公网URL，每行一个（填了优先）"}),
                "size": (HMJ_BANANA2_SIZES, {"default": "(不传)", "tooltip": "**只有香蕉2需要**；Pro 的档位在模型名里，传了反而多余"}),
                "timeout": ("INT", {"default": 600, "min": 60, "max": 3600}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 9, "step": 1, "tooltip": "参考图接口数量；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_url", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, ref_urls="", size="(不传)",
                 timeout=600, custom_model="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        parts: list = [{"type": "text", "text": prompt}]
        urls = _lines(ref_urls, 9)
        if urls:
            _http_only(urls, "参考图")
            for u in urls:
                parts.append({"type": "image_url", "image_url": {"url": u}})
        else:
            for frame in expand_image_frames(dynamic_image_inputs(kwargs))[:9]:
                b = tensor_to_b64(frame, fmt="PNG", max_side=2048)
                if b:
                    parts.append({"type": "image_url", "image_url": {"url": b[0]}})

        n_ref = len(parts) - 1
        content = prompt if n_ref == 0 else parts
        body: dict = {"model": model, "messages": [{"role": "user", "content": content}]}
        if not size.startswith("("):
            if "nano-banana2" not in model and "nano-banana-2" not in model:
                print(f"[Respect] ⚠ size 是香蕉2 的字段，{model} 的档位写在模型名里 —— 仍按你选的发出去")
            body["size"] = size

        print(f"[Respect] 好漫剧 香蕉 {model}: 参考图{n_ref}张 size={body.get('size', '(不传)')}")
        resp = api_request(cfg, "POST", "/v1/chat/completions", json_body=body,
                           retries=1, timeout=max(int(timeout), 120))
        data = resp.json() if resp.content else {}
        items = extract_image_payloads(data)
        if not items:
            raise RespectAPIError(
                f"没能从 content 里取到图片。原始响应：{json.dumps(data, ensure_ascii=False)[:500]}")
        tensors = [t for t in (resolve_image_to_tensor(i, cfg) for i in items) if t is not None]
        if not tensors:
            raise RespectAPIError(f"取到结果但无法解析为图片: {str(items)[:300]}")
        first = next((i for i in items if isinstance(i, str) and i.startswith("http")), "")
        return (tensors_concat(tensors), first, model)


# ---------------------------------------------------------------------------
# ⑥ GPT-image-2 图片（generations / edits）
# ---------------------------------------------------------------------------


class RespectHmjImage:
    """好漫剧 GPT-image-2 图片（文档三）。

    - 无参考图 → `POST /v1/images/generations`（JSON）
    - 有参考图 → `POST /v1/images/edits`（**multipart**，字段名 `image[]`，可重复）

    返回 `data[0].b64_json`。文档给的四个尺寸里 **`1536x1152` 是这家独有的**，
    别家没有这个比例。
    """

    DESCRIPTION = ("好漫剧 GPT-image-2（文档三）。无图→/v1/images/generations，"
                   "有图→/v1/images/edits(multipart，字段 image[])；返回 b64_json。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": BASE_HINT}),
                "model": (HMJ_IMAGE_MODELS, {"default": "gpt-image-2"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "size": (HMJ_IMAGE_SIZES, {"default": "1024x1024"}),
                "response_format": (HMJ_FORMATS, {"default": "b64_json"}),
            },
            "optional": {
                "image_1": ("IMAGE", {"tooltip": "接了就走 /v1/images/edits"}),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "n": ("INT", {"default": 1, "min": 1, "max": 4}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖尺寸"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 9, "step": 1, "tooltip": "参考图接口数量；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, size, response_format,
                 n=1, custom_model="", custom_size="", inputcount=4, **kwargs):
        import base64

        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        size = (custom_size or "").strip() or size
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        frames = expand_image_frames(dynamic_image_inputs(kwargs))[:9]
        if frames:
            files: list = [
                ("model", (None, model)), ("prompt", (None, prompt)),
                ("size", (None, size)), ("n", (None, str(int(n)))),
                ("response_format", (None, response_format)),
            ]
            for i, frame in enumerate(frames, start=1):
                b64 = tensor_to_b64(frame, fmt="PNG", max_side=2048)
                if not b64:
                    continue
                raw = base64.b64decode(b64[0].split(",", 1)[1])
                files.append(("image[]", (f"ref_{i}.png", raw, "image/png")))
            print(f"[Respect] 好漫剧 图生图 {model}: {size} 参考图{len(frames)}张（multipart image[]）")
            resp = api_request(cfg, "POST", "/v1/images/edits", files=files,
                               retries=2, timeout=max(cfg.timeout, 600))
        else:
            body = {"model": model, "prompt": prompt, "n": int(n),
                    "size": size, "response_format": response_format}
            print(f"[Respect] 好漫剧 文生图 {model}: {size}")
            resp = api_request(cfg, "POST", "/v1/images/generations", json_body=body,
                               retries=2, timeout=max(cfg.timeout, 600))

        data = resp.json() if resp.content else {}
        items = extract_image_payloads(data)
        if not items:
            raise RespectAPIError(f"未能从响应中提取图片: {json.dumps(data, ensure_ascii=False)[:400]}")
        tensors = [t for t in (resolve_image_to_tensor(i, cfg) for i in items) if t is not None]
        if not tensors:
            raise RespectAPIError(f"取到结果但无法解析为图片: {str(items)[:300]}")
        return (tensors_concat(tensors), model)


NODE_CLASS_MAPPINGS = {
    "RespectHmjGrokVideo": RespectHmjGrokVideo,
    "RespectHmjH3Video": RespectHmjH3Video,
    "RespectHmjOmniVideo": RespectHmjOmniVideo,
    "RespectHmjChatVideo": RespectHmjChatVideo,
    "RespectHmjBanana": RespectHmjBanana,
    "RespectHmjImage": RespectHmjImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectHmjGrokVideo": "Respect 好漫剧 GROK视频（multipart传图）",
    "RespectHmjH3Video": "Respect 好漫剧 minimax_h3 / SD 视频",
    "RespectHmjOmniVideo": "Respect 好漫剧 Omni-flash 视频",
    "RespectHmjChatVideo": "Respect 好漫剧 Sora2/VEO 视频（同步）",
    "RespectHmjBanana": "Respect 好漫剧 香蕉图片（Pro/香蕉2）",
    "RespectHmjImage": "Respect 好漫剧 GPT-image-2 图片",
}
