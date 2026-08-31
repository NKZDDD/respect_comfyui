"""Respect ComfyUI 扩展 - Gate（`https://api-gate.astralmindai.com`）节点。

协议与 `script-to-video-studio/core/providers/gate.py` 同源（依据《Gate接入文档》
和公开 Schema `GET /public/model_group/info`），两边规格表由脚本比对保持一致。

- 图片 `POST /v1/images/generations`（**同步**）
- 视频 `POST /api/multimodal/create_task` 提交 → `GET /v1/videos/{id}` 轮询
  → `GET /v1/videos/{id}/content` 下载

⚠ 三个只有对着 Schema 才知道的坑：

1. **图片不是一套字段硬套所有模型**：
   · Kling 用 `resolution` + `aspect_ratio`（没有 `size`），数量字段叫 `num_images`
   · Qwen 的尺寸分隔符是 `*` 不是 `x`
   · `seedream-4-5` 自定义尺寸下限比本插件默认的 1024x1536 高，只能给 `2K`/`4K`
   · Seedream / Kling 一族**不收 `n`**
   照发服务端会拒绝，或者**静默忽略**——后者更麻烦，你以为设了尺寸其实没设。
2. **GPT 两个图片模型（gpt-image-1 / gpt-image-2）在当前 Schema 里只做文生图**，
   接了参考图不是少几张的问题，是这条路根本没有参考图。
3. **视频参考素材只收公网 URL**，而且提交端点**不在 `/v1` 下**
   （是 `/api/multimodal/create_task`），跟查询/下载不是同一个前缀。
"""

from __future__ import annotations

import json

from .utils import (RespectAPIError, api_request, download_to_output,
                    dynamic_image_inputs, dynamic_url_inputs, ensure_config,
                    expand_image_frames, extract_data_array_images,
                    extract_image_payloads, resolve_image_to_tensor,
                    tensor_to_b64, tensors_concat)

CATEGORY = "Respect/Gate"
BASE_HINT = "base_url 填 https://api-gate.astralmindai.com"

GATE_IMAGE_MODELS = [
    "nano-banana", "nano-banana-pro", "seedream-5-0-lite", "nano-banana-2",
    "seedream-5-0-pro", "gpt-image-2", "nano-banana-2-lite", "seedream-4-0",
    "kling-image-o3", "qwen-image-2.0-pro", "qwen-image-2.0", "seedream-4-5",
    "kling-image-v3", "gpt-image-1",
]
GATE_VIDEO_MODELS = [
    "seedance-2.5-official", "seedance-2.0-standard-official",
    "seedance-2.0-fast-official", "seedance-2.0-mini", "seedance-2.0-standard",
    "seedance-2.5", "seedance-2.0-fast",
]
GATE_IMAGE_SIZES = ["1024x1536", "1536x1024", "1024x1024"]
GATE_RATIOS = ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9", "adaptive"]
GATE_RESOLUTIONS = ["720p", "480p"]

# 每个图片模型能收几张参考图。0 = 这条路只做文生图。
GATE_IMAGE_REF_LIMITS = {
    "nano-banana": 14, "nano-banana-pro": 14, "seedream-5-0-lite": 14,
    "nano-banana-2": 14, "seedream-5-0-pro": 10,
    "nano-banana-2-lite": 14, "gpt-image-2": 0, "gpt-image-1": 0,
    "kling-image-v3": 1,
}
GATE_NO_N = {"seedream-5-0-lite", "seedream-5-0-pro", "seedream-4-0",
             "seedream-4-5", "kling-image-o3", "kling-image-v3"}
GATE_KLING = {"kling-image-o3", "kling-image-v3"}


def _gate_root(cfg) -> str:
    """去掉 `/v1` 的根地址。

    `normalized_base()` 会**给 base_url 补上 `/v1`**，而 Gate 的提交端点是
    `/api/multimodal/create_task` —— 不在 `/v1` 下。直接交给 api_request 拼会拼成
    `…/v1/api/multimodal/create_task`（404），所以这里自己拼绝对地址。
    """
    return cfg.normalized_base().rsplit("/v1", 1)[0]


def _is_25(model: str) -> bool:
    return str(model).startswith("seedance-2.5")


def _ratio_for_size(size: str) -> str:
    """`宽x高` → Kling 要的宽高比字段。"""
    try:
        w, h = (int(x) for x in str(size).lower().split("x", 1))
    except (TypeError, ValueError):
        return "1:1"
    pairs = {(9, 16): "9:16", (16, 9): "16:9", (1, 1): "1:1",
             (4, 3): "4:3", (3, 4): "3:4", (3, 2): "3:2", (2, 3): "2:3"}
    return min(pairs.items(), key=lambda kv: abs(w / h - kv[0][0] / kv[0][1]))[1]


def _image_shape(model: str, size: str) -> dict:
    """按模型给出**它自己认的**尺寸字段。

    发错的后果分两种，第二种更麻烦：
      · 服务端直接拒绝 —— 至少你知道出事了
      · 服务端**静默忽略** —— 你以为设了尺寸，其实出的是它的默认值
    """
    wanted = str(size or "1024x1536")
    if model in GATE_KLING:
        return {"resolution": "1K", "aspect_ratio": _ratio_for_size(wanted)}
    if model.startswith("qwen-image-2.0"):
        return {"size": wanted.replace("x", "*").replace("X", "*")}
    if model == "seedream-4-5":
        return {"size": wanted if wanted in ("2K", "4K") else "2K"}
    return {"size": wanted}


class RespectGateImage:
    """Gate 图片。`POST /v1/images/generations`，同步返回。"""

    DESCRIPTION = ("Gate 图片(base_url=https://api-gate.astralmindai.com)。14 个模型，"
                   "**尺寸字段按模型不同**(Kling 用 resolution+aspect_ratio、Qwen 用 * 分隔、"
                   "seedream-4-5 只收 2K/4K)；gpt-image-1/2 只做文生图。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": BASE_HINT}),
                "model": (GATE_IMAGE_MODELS, {"default": "seedream-5-0-pro"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "size": (GATE_IMAGE_SIZES, {"default": "1024x1536",
                                            "tooltip": "会按模型转成它认的字段；seedream-4-5 只收 2K/4K，会自动改成 2K"}),
                "n": ("INT", {"default": 1, "min": 1, "max": 4,
                              "tooltip": "Kling 走 num_images；Seedream 一族不收这个字段，会自动不发"}),
            },
            "optional": {
                "image_1": ("IMAGE", {"tooltip": "参考图；接批次会展开。gpt-image-1/2 不收参考图，接了会报错而不是悄悄丢"}),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 14, "step": 1,
                                       "tooltip": "参考图接口数量；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("image", "image_url", "model_used", "image_urls", "count")
    OUTPUT_TOOLTIPS = ("所有返回的图拼成的批次", "第一张的链接", "实际用的模型",
                       "全部链接，每行一个", "这次拿到几张")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, size, n,
                 custom_model="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        frames = expand_image_frames(dynamic_image_inputs(kwargs))
        limit = GATE_IMAGE_REF_LIMITS.get(model, 14)
        if frames and not limit:
            raise RespectAPIError(
                f"Gate 的 {model} 在当前 Schema 里**只做文生图**，接了 {len(frames)} 张参考图。\n"
                f"少了参考图出来的就不是同一个人，所以这一条不出，不会悄悄丢掉。\n"
                f"要用参考图请换 Seedream / Nano Banana / Qwen / Kling 系模型。")
        if len(frames) > limit:
            raise RespectAPIError(
                f"Gate 的 {model} 最多 {limit} 张参考图，这一项接了 {len(frames)} 张。\n"
                f"**不会自动裁掉多的** —— 裁掉哪张都会让画面里少一个人，而且不报错。")

        body: dict = {"model": model, "prompt": prompt}
        body.update(_image_shape(model, size))
        if model in GATE_KLING:
            body["num_images"] = int(n)
        elif model not in GATE_NO_N:
            body["n"] = int(n)
        if frames:
            refs = [b for f in frames for b in tensor_to_b64(f, fmt="PNG", max_side=2048)]
            body["image"] = refs[0] if len(refs) == 1 else refs

        shape = body.get("size") or f"{body.get('resolution')} {body.get('aspect_ratio')}"
        print(f"[Respect] Gate 图片 {model}: 尺寸字段={shape} 参考图{len(frames)}张")
        resp = api_request(cfg, "POST", "/v1/images/generations",
                           json_body=body, retries=1, timeout=max(cfg.timeout, 600))
        data = resp.json() if resp.content else {}
        items = extract_data_array_images(data) or extract_image_payloads(data)
        if not items:
            raise RespectAPIError(
                f"Gate 没返回可用图片：{json.dumps(data, ensure_ascii=False)[:400]}")

        tensors = [t for t in (resolve_image_to_tensor(i, cfg) for i in items) if t is not None]
        if not tensors:
            raise RespectAPIError(
                f"Gate 返回了 {len(items)} 项，但一项都解析不成图片。\n"
                f"上面那行 `[Respect] 图片解析失败：…` 写了具体原因。\n"
                f"首项开头：{str(items[0])[:120]}…")
        urls = [i for i in items if isinstance(i, str) and i.startswith("http")]
        return (tensors_concat(tensors), urls[0] if urls else "", model,
                "\n".join(urls), len(tensors))


class RespectGateVideo:
    """Gate 视频。`POST /api/multimodal/create_task` → 轮询 `GET /v1/videos/{id}`。"""

    DESCRIPTION = ("Gate 视频(base_url=https://api-gate.astralmindai.com)。"
                   "2.5 系 4-30 秒 / 30图 10视频 10音频；2.0 系 4-15 秒 / 9图 3视频 3音频。"
                   "⚠ 参考素材**只收公网 URL**，本机图先过『对象存储上传』。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": BASE_HINT}),
                "model": (GATE_VIDEO_MODELS, {"default": "seedance-2.5"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "seconds": ("INT", {"default": 15, "min": 4, "max": 30,
                                    "tooltip": "2.5 系 4-30 秒；2.0 系只到 15 秒（超了当场报，不会白等排队）"}),
                "ratio": (GATE_RATIOS, {"default": "9:16"}),
                "resolution": (GATE_RESOLUTIONS, {"default": "720p"}),
                "poll_interval": ("INT", {"default": 8, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 2400, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "ref_url_1": ("STRING", {"default": "", "multiline": False,
                                         "placeholder": "参考图公网 URL（只收 http/https）"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "video_urls": ("STRING", {"default": "", "multiline": True,
                                          "placeholder": "参考视频 URL，每行一个"}),
                "audio_urls": ("STRING", {"default": "", "multiline": True,
                                          "placeholder": "参考音频 URL，每行一个"}),
                "generate_audio": ("BOOLEAN", {"default": True}),
                "watermark": ("BOOLEAN", {"default": False}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 30, "step": 1,
                                       "tooltip": "参考图 URL 接口数量；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("在线视频 URL", "下载到本地的路径", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, seconds, ratio, resolution,
                 poll_interval, poll_timeout, auto_download,
                 video_urls="", audio_urls="", generate_audio=True, watermark=False,
                 custom_model="", save_dir="", filename="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        is25 = _is_25(model)
        upper = 30 if is25 else 15
        sec = int(seconds)
        if not 4 <= sec <= upper:
            raise RespectAPIError(
                f"Gate 的 {model} 只支持 4–{upper} 秒，这一项填的是 {sec} 秒。\n"
                f"（2.5 系到 30 秒，2.0 系只到 15 秒）现在就停，别让排队时间白花。")

        images = dynamic_url_inputs(kwargs)
        videos = [ln.strip() for ln in (video_urls or "").splitlines() if ln.strip()]
        audios = [ln.strip() for ln in (audio_urls or "").splitlines() if ln.strip()]
        max_i, max_va = (30, 10) if is25 else (9, 3)
        if len(images) > max_i or len(videos) > max_va or len(audios) > max_va:
            raise RespectAPIError(
                f"Gate 的 {model} 素材超限：图 {len(images)}/{max_i}、"
                f"视频 {len(videos)}/{max_va}、音频 {len(audios)}/{max_va}。\n"
                f"**不会自动裁掉多的** —— 裁掉哪一项都不报错，而片子里就少一个人。")
        bad = [r for r in images + videos + audios
               if not str(r).startswith(("http://", "https://"))]
        if bad:
            raise RespectAPIError(
                f"Gate 的视频参考素材**只收公网 http/https URL**，这一项有 {len(bad)} 条不是。\n"
                f"少一张参考图出来的就不是同一个人，所以这一条不出。\n"
                f"把图接『Respect 对象存储上传』，把返回的 url 填进 ref_url_N。")

        body: dict = {
            "model": model,
            "prompt": prompt,
            "duration": sec,
            "ratio": ratio,
            "resolution": (resolution or "720p").lower(),
            "generate_audio": bool(generate_audio),
            "watermark": bool(watermark),
        }
        if images:
            body["image_url"] = images
        if videos:
            body["video_url"] = videos
        if audios:
            body["audio_url"] = audios

        print(f"[Respect] Gate 视频 {model}: {sec}s {body['resolution']} {ratio} "
              f"图{len(images)}/视频{len(videos)}/音频{len(audios)}")
        # 提交端点**不在 /v1 下**，自己拼绝对地址（见 _gate_root）
        resp = api_request(cfg, "POST", f"{_gate_root(cfg)}/api/multimodal/create_task",
                           json_body=body, retries=1, timeout=300)
        data = resp.json() if resp.content else {}
        task_id = str(data.get("task_id") or data.get("id") or "") if isinstance(data, dict) else ""
        video_url = _gate_pick_url(data)
        if not video_url:
            if not task_id:
                raise RespectAPIError(
                    f"Gate 创建任务没返回 ID：{json.dumps(data, ensure_ascii=False)[:400]}")
            video_url = _gate_poll(cfg, task_id, int(poll_interval), int(poll_timeout))

        local = ""
        if auto_download and video_url:
            try:
                local = download_to_output(video_url, cfg, prefix="gate_video",
                                           save_dir=save_dir, filename=filename)
            except Exception as exc:                        # noqa: BLE001
                print(f"[Respect] Gate 视频下载失败（链接仍可用）：{exc}")
        return (video_url, local, task_id)


def _gate_pick_url(payload) -> str:
    """从响应里取成片地址。只认明确的字段，不做模糊猜测。"""
    if not isinstance(payload, dict):
        return ""
    for key in ("video_url", "url", "result_url", "download_url"):
        val = payload.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    inner = payload.get("data")
    return _gate_pick_url(inner) if isinstance(inner, dict) else ""


def _gate_poll(cfg, task_id: str, interval: int, timeout: int) -> str:
    import time
    start, last = time.time(), ""
    while time.time() - start < timeout:
        resp = api_request(cfg, "GET", f"/v1/videos/{task_id}", retries=1, timeout=60)
        data = resp.json() if resp.content else {}
        inner = data.get("data") if isinstance(data.get("data"), dict) else data
        status = str((inner or {}).get("status") or "").lower()
        if status != last:
            print(f"[Respect] Gate {task_id}: {status or '(无状态字段)'}")
            last = status
        if status in ("failed", "failure", "error"):
            raise RespectAPIError(
                f"Gate 任务失败：{json.dumps(data, ensure_ascii=False)[:300]}")
        url = _gate_pick_url(data)
        if url:
            return url
        if status in ("succeeded", "success", "completed"):
            # 状态说成了但没给链接 —— 退回下载端点
            return f"{_gate_root(cfg)}/v1/videos/{task_id}/content"
        time.sleep(interval)
    raise RespectAPIError(f"Gate 任务超时：{task_id}（可调大 poll_timeout）")


NODE_CLASS_MAPPINGS = {
    "RespectGateImage": RespectGateImage,
    "RespectGateVideo": RespectGateVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectGateImage": "Respect Gate 图片",
    "RespectGateVideo": "Respect Gate 视频",
}
