"""Respect ComfyUI 扩展 - 超模（`https://www.chaomoapi.com`）节点。

文档：`https://www.chaomoapi.com/custom/doc`

这家和章鱼哥/别家**不通用**，三处形状完全不同，照抄别家节点会静默丢参数：

1. **视频参考素材是 OpenAI chat 风格的 `content` 块**，不是 `images[]`：
   ```json
   "content": [{"type": "image_url", "role": "reference_image",
                "image_url": {"url": "https://…"}}]
   ```
   `type` 可为 `image_url` / `video_url` / `audio_url`。发 `images:[base64]` 过去
   **不会报错，但参考图被忽略** —— 图照出、人不对。
2. **视频的 `size` 是分辨率档位**（`480p`/`720p`/`1080p`/`4k`），不是像素也不是比例。
3. **`seconds` 是字符串**（`"4"`，4–15 秒）。

图片是另一套：`POST /v1/images/generations`，比例字段叫 **`ratio`**、要带 `async:true`，
然后 `GET /v1/images/{task_id}` 轮询。图生图走 `POST /v1/images/edits`（multipart，
字段名 **`image[]`**，1–9 张），文档明写「参考图 URL 不能直接当文件传入：请先下载到
本地，再通过 `image[]` 上传」—— 所以图生图节点收 IMAGE，视频节点收 URL。
"""

from __future__ import annotations

import base64
import json

from .llm_nodes import _img_task_id, _poll_image_task
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
    tensors_concat,
)
from .video_nodes import _async_extract_url, _async_poll, _sd2_extract_task_id

CATEGORY = "Respect/超模"

CM_VIDEO_MODELS = ["seedance2", "seedance2-fast", "seedance2-mini"]
CM_IMAGE_MODELS = [
    "gpt-image2-1K", "gpt-image2-2K-low", "gpt-image2-4K-low",
    "gpt-image2-2K-Direct", "gpt-image2-4K-Direct", "gpt-image2-4K",
    "gpt-image-1k-th",
    "gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview",
]
CM_RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "2:3", "3:2", "21:9"]
CM_SIZES = ["720p", "1080p", "480p", "4k"]      # 视频 size = 分辨率档位
CM_MAX_REFS = 9


def _cm_lines(s: str, cap: int) -> list:
    return [ln.strip() for ln in (s or "").splitlines() if ln.strip()][:cap]


def _cm_block(kind: str, url: str) -> dict:
    """拼一个 content 块。kind ∈ image / video / audio。"""
    return {"type": f"{kind}_url", "role": "reference_image" if kind == "image" else f"reference_{kind}",
            f"{kind}_url": {"url": url}}


# ---------------------------------------------------------------------------
# ① 超模 视频（content 块 + seconds 字符串 + size 分辨率档）
# ---------------------------------------------------------------------------


class RespectChaomoVideo:
    """超模 视频（`POST /v1/videos` → `GET /v1/videos/{task_id}` 轮询）。

    body：`{model, prompt, seconds:"8", size:"720p", content:[…]}`。
    参考素材用 `content` 块传，**只收公网 URL**（本地图请接『Respect 对象存储上传』换链接）。
    URL 口数量用 `inputcount` + 「更新输入口」调。
    """

    DESCRIPTION = ("超模 chaomoapi 视频。seconds是字符串(4-15)、size是分辨率档(480p/720p/1080p/4k)、"
                   "参考素材走 content 块[{type:image_url,role:reference_image,image_url:{url}}]，只收公网URL。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://www.chaomoapi.com"}),
                "model": (CM_VIDEO_MODELS, {"default": "seedance2", "tooltip": "上新模型用 custom_model 填"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "seconds": ("INT", {"default": 8, "min": 4, "max": 15, "tooltip": "4–15 秒；发出去是字符串"}),
                "size": (CM_SIZES, {"default": "720p", "tooltip": "这家的 size 是分辨率档位，不是像素/比例"}),
                "poll_interval": ("INT", {"default": 5, "min": 3, "max": 60, "tooltip": "文档建议 3~5 秒"}),
                "poll_timeout": ("INT", {"default": 2400, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "参考图公网URL（接『对象存储上传』）"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "extra_image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "追加参考图URL，每行一个（共≤9）"}),
                "video_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考视频URL，每行一个 → video_url 块"}),
                "audio_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考音频URL，每行一个 → audio_url 块"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "ratio": ("STRING", {"default": "", "multiline": False, "placeholder": "留空。文档视频段没有比例字段，填了才发 ratio"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 9, "step": 1, "tooltip": "参考图URL接口数量（≤9）；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("在线视频 URL", "下载到本地的路径（预览/拼接用这个）", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, seconds, size,
                 poll_interval, poll_timeout, auto_download,
                 extra_image_urls="", video_urls="", audio_urls="",
                 custom_model="", ratio="", save_dir="", filename="",
                 inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        imgs = dynamic_url_inputs(kwargs) + _cm_lines(extra_image_urls, CM_MAX_REFS)
        imgs = imgs[:CM_MAX_REFS]
        vids, auds = _cm_lines(video_urls, 3), _cm_lines(audio_urls, 3)

        bad = [u for u in imgs + vids + auds if not u.startswith(("http://", "https://"))]
        if bad:
            raise RespectAPIError(
                f"超模视频的 content 块只收公网 URL，这些不是：{bad[:2]}\n"
                f"本地图请接『Respect 对象存储上传』换成链接，或改用『Respect 超模 图生图』（那个走 multipart 收本地图）。")

        body: dict = {
            "model": model,
            "prompt": prompt,
            "seconds": str(int(seconds)),      # 字符串，不是整数
            "size": size,                      # 分辨率档位，不是像素
        }
        content = ([_cm_block("image", u) for u in imgs]
                   + [_cm_block("video", u) for u in vids]
                   + [_cm_block("audio", u) for u in auds])
        if content:
            body["content"] = content
        if (ratio or "").strip():
            # 文档视频段没列比例字段，不猜着发；用户明确填了才带上
            body["ratio"] = ratio.strip()

        print(f"[Respect] 超模 {model}: seconds='{seconds}' size={size} "
              f"content块 图{len(imgs)}/视频{len(vids)}/音频{len(auds)}")
        print(f"[Respect] body={json.dumps(body, ensure_ascii=False)[:400]}")
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
                local = download_to_output(url, cfg, prefix="chaomo", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] 超模 视频下载失败: {exc}")
        return (url, local, task_id or "")


# ---------------------------------------------------------------------------
# ② 超模 图片（ratio + async:true → /v1/images/{task_id} 轮询）
# ---------------------------------------------------------------------------


class RespectChaomoImage:
    """超模 文生图（`POST /v1/images/generations`，`async:true` 后轮询 `/v1/images/{task_id}`）。

    **比例字段叫 `ratio`**（`16:9` 这种），不是 `size`/`aspect_ratio`；`n` 文档写死 1。
    要用参考图请走『Respect 超模 图生图』（那边是 multipart）。
    """

    DESCRIPTION = ("超模 chaomoapi 文生图。POST /v1/images/generations，比例字段是 ratio、n固定1、"
                   "async:true 后轮询 GET /v1/images/{task_id}。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://www.chaomoapi.com"}),
                "model": (CM_IMAGE_MODELS, {"default": "gpt-image2-1K", "tooltip": "上新模型用 custom_model 填"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "ratio": (CM_RATIOS, {"default": "9:16", "tooltip": "这家的比例字段就叫 ratio"}),
                "poll_interval": ("INT", {"default": 5, "min": 3, "max": 60}),
                "poll_timeout": ("INT", {"default": 900, "min": 60, "max": 3600}),
            },
            "optional": {
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "response_format": ("STRING", {"default": "url", "multiline": False, "placeholder": "url 或 b64_json"}),
                "use_async": ("BOOLEAN", {"default": True, "tooltip": "文档示例带 async:true；关掉则按同步解析"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_url", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, ratio, poll_interval, poll_timeout,
                 custom_model="", response_format="url", use_async=True):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        body = {
            "model": model,
            "prompt": prompt,
            "ratio": ratio,                    # 不是 size / aspect_ratio
            "n": 1,                            # 文档：固定 1
            "response_format": (response_format or "url").strip() or "url",
        }
        if use_async:
            body["async"] = True

        print(f"[Respect] 超模 图片 {model}: ratio={ratio} async={bool(use_async)}")
        resp = api_request(cfg, "POST", "/v1/images/generations", json_body=body,
                           retries=2, timeout=max(cfg.timeout, 300))
        data = resp.json() if resp.content else {}
        items = extract_image_payloads(data)
        if not items:
            tid = _img_task_id(data)
            if not tid:
                raise RespectAPIError(f"未取到图片也没有任务 ID: {json.dumps(data, ensure_ascii=False)[:400]}")
            items = _poll_image_task(cfg, tid, interval=int(poll_interval), timeout=int(poll_timeout))

        tensors = [t for t in (resolve_image_to_tensor(i, cfg) for i in items) if t is not None]
        if not tensors:
            raise RespectAPIError(f"取到结果但无法解析为图片: {str(items)[:300]}")
        first = items[0] if isinstance(items[0], str) else ""
        return (tensors_concat(tensors), first if first.startswith("http") else "", model)


# ---------------------------------------------------------------------------
# ③ 超模 图生图（multipart image[]，1–9 张；文档明写不收 URL）
# ---------------------------------------------------------------------------


class RespectChaomoImageEdit:
    """超模 图生图 / 多图参考（`POST /v1/images/edits`，multipart，字段名 **`image[]`**）。

    文档原文：「参考图 URL 不能直接当文件传入：请先下载到本地，再通过 `image[]` 上传」——
    所以这个节点直接收 ComfyUI 的 IMAGE（本来就是本地数据），不需要对象存储。
    张数用 `inputcount` + 「更新输入口」调，**1–9 张**。
    """

    DESCRIPTION = ("超模 chaomoapi 图生图。POST /v1/images/edits，multipart 字段名是 image[]（1-9张）；"
                   "文档明写参考图URL不能直传，必须上传文件 —— 本节点直接吃 IMAGE。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://www.chaomoapi.com"}),
                "model": (CM_IMAGE_MODELS, {"default": "gpt-image2-1K"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "ratio": (CM_RATIOS, {"default": "9:16"}),
                "poll_interval": ("INT", {"default": 5, "min": 3, "max": 60}),
                "poll_timeout": ("INT", {"default": 900, "min": 60, "max": 3600}),
            },
            "optional": {
                "image_1": ("IMAGE", {"tooltip": "参考图（必接至少一张）"}),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "response_format": ("STRING", {"default": "url", "multiline": False, "placeholder": "url 或 b64_json"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 9, "step": 1, "tooltip": "参考图接口数量（≤9）；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_url", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, ratio, poll_interval, poll_timeout,
                 custom_model="", response_format="url", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        frames = expand_image_frames(dynamic_image_inputs(kwargs))[:CM_MAX_REFS]
        if not frames:
            raise RespectAPIError(
                "图生图至少要接 1 张 IMAGE。只想文生图请用『Respect 超模 图片』节点。")

        files: list = [
            ("model", (None, model)),
            ("prompt", (None, prompt)),
            ("ratio", (None, ratio)),
            ("n", (None, "1")),
            ("response_format", (None, (response_format or "url").strip() or "url")),
        ]
        for i, frame in enumerate(frames):
            b64 = tensor_to_b64(frame, fmt="PNG", max_side=2048)
            if not b64:
                continue
            raw = base64.b64decode(b64[0].split(",", 1)[1])
            files.append(("image[]", (f"ref_{i + 1}.png", raw, "image/png")))

        print(f"[Respect] 超模 图生图 {model}: ratio={ratio} 参考图{len(frames)}张（multipart image[]）")
        resp = api_request(cfg, "POST", "/v1/images/edits", files=files,
                           retries=2, timeout=max(cfg.timeout, 600))
        data = resp.json() if resp.content else {}
        items = extract_image_payloads(data)
        if not items:
            tid = _img_task_id(data)
            if not tid:
                raise RespectAPIError(f"未取到图片也没有任务 ID: {json.dumps(data, ensure_ascii=False)[:400]}")
            items = _poll_image_task(cfg, tid, interval=int(poll_interval), timeout=int(poll_timeout))

        tensors = [t for t in (resolve_image_to_tensor(i, cfg) for i in items) if t is not None]
        if not tensors:
            raise RespectAPIError(f"取到结果但无法解析为图片: {str(items)[:300]}")
        first = items[0] if isinstance(items[0], str) else ""
        return (tensors_concat(tensors), first if first.startswith("http") else "", model)


NODE_CLASS_MAPPINGS = {
    "RespectChaomoVideo": RespectChaomoVideo,
    "RespectChaomoImage": RespectChaomoImage,
    "RespectChaomoImageEdit": RespectChaomoImageEdit,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectChaomoVideo": "Respect 超模 视频（chaomoapi）",
    "RespectChaomoImage": "Respect 超模 图片（ratio+异步）",
    "RespectChaomoImageEdit": "Respect 超模 图生图（multipart≤9）",
}
