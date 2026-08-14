"""Respect ComfyUI 扩展 - 阿珂（`https://snumom.com`）节点。Grok Imagine 视频专线，**只做视频**。

- 创建 `POST /v1/videos`
- 查询 `GET /v1/videos/{id}`（文档建议 5 秒一次）：
  `queued` / `in_progress` 生成中；`completed` 取 `url`；`failed` 看 `error` / `message`

四个和别家不一样、写错就白花钱的点：
1. **`seconds` 是字符串**（`"8"`），不是整数
2. **`size` 同时决定分辨率和比例** —— 没有单独的 `aspect_ratio` / `resolution` 字段。
   只有四种组合：720p 16:9=`1280x720` / 9:16=`720x1280`；480p 16:9=`854x480` / 9:16=`480x854`
3. 参考图**两个字段、二选一，形状还不同**：
   - `reference_images` = **对象**数组 `[{"url":"…"}]`（文档推荐，只能公网 URL）
   - `input_reference` = **字符串**数组（URL 或 base64，可带 `data:image/...;base64,` 前缀）
   节点自动选：全是链接 → `reference_images`；含本地图 → 整批走 `input_reference`
4. 最多 **7 张**参考图

`model` / `prompt` / `seconds` / `size` 都必填。
"""

from __future__ import annotations

import json

from .utils import (
    RespectAPIError,
    api_request,
    download_to_output,
    dynamic_image_inputs,
    dynamic_url_inputs,
    ensure_config,
    expand_image_frames,
    tensor_to_b64,
)
from .video_nodes import _async_extract_url, _async_poll, _sd2_extract_task_id

CATEGORY = "Respect/阿珂"

AKE_MODELS = ["grok-imagine-video-1.5-preview"]
AKE_RATIOS = ["9:16", "16:9"]
AKE_RESOLUTIONS = ["720p", "480p"]
AKE_MAX_REFS = 7

# size 是唯一的画面控制字段：(分辨率, 比例) → 取值
AKE_SIZE_TABLE = {
    ("720p", "16:9"): "1280x720", ("720p", "9:16"): "720x1280",
    ("480p", "16:9"): "854x480", ("480p", "9:16"): "480x854",
}


class RespectAkeVideo:
    """阿珂 Grok Imagine 视频（`POST /v1/videos` + 5 秒轮询）。

    参考图两条路，节点按你给的内容自动选：
    - 只填了 URL（`ref_url_N` / 多行框）→ `reference_images:[{"url":…}]`（文档推荐）
    - 接了 IMAGE → 转 base64，整批走 `input_reference`（该字段吃 base64）
    数量用 `inputcount` + 「更新输入口」调，**最多 7 张**。
    """

    DESCRIPTION = ("阿珂 snumom.com Grok视频。seconds是字符串(1-15)、size 同时定分辨率和比例"
                   "(只有480p/720p × 16:9/9:16)；参考图≤7：给URL走 reference_images、"
                   "接IMAGE转base64走 input_reference。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://snumom.com"}),
                "model": (AKE_MODELS, {"default": AKE_MODELS[0], "tooltip": "上新模型用 custom_model 填"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "seconds": ("INT", {"default": 8, "min": 1, "max": 15, "tooltip": "1–15 秒；发出去是字符串"}),
                "resolution": (AKE_RESOLUTIONS, {"default": "720p", "tooltip": "和比例合成 size 发出去"}),
                "aspect_ratio": (AKE_RATIOS, {"default": "9:16", "tooltip": "这家只有 16:9 / 9:16 两种"}),
                "poll_interval": ("INT", {"default": 5, "min": 2, "max": 60, "tooltip": "文档建议 5 秒"}),
                "poll_timeout": ("INT", {"default": 2400, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "参考图公网URL（接对象存储上传）→ reference_images"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "extra_image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "追加参考图URL，每行一个（共≤7）"}),
                "image_1": ("IMAGE", {"tooltip": "本地参考图 → 转 base64 走 input_reference（该字段吃 base64）"}),
                "image_2": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选：直接指定 size 如 1280x720，覆盖上面两项"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 7, "step": 1, "tooltip": "参考图URL接口数量（≤7）；改完点『更新输入口』按钮增减 ref_url_N"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("在线视频 URL", "下载到本地的路径（预览/拼接用这个）", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, seconds, resolution, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 extra_image_urls="", custom_model="", custom_size="",
                 save_dir="", filename="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        size = (custom_size or "").strip() or AKE_SIZE_TABLE[(resolution, aspect_ratio)]

        # URL 优先用 reference_images；接了 IMAGE 就整批改走 input_reference（它吃 base64）
        urls = dynamic_url_inputs(kwargs)
        urls += [ln.strip() for ln in (extra_image_urls or "").splitlines() if ln.strip()]
        inline = []
        for frame in expand_image_frames(dynamic_image_inputs(kwargs)):
            b = tensor_to_b64(frame, fmt="JPEG", quality=90, max_side=1536)
            if b:
                inline.append(b[0])

        refs = (urls + inline)[:AKE_MAX_REFS]
        if len(urls) + len(inline) > AKE_MAX_REFS:
            print(f"[Respect] 阿珂最多 {AKE_MAX_REFS} 张参考图，已裁掉多余 "
                  f"{len(urls) + len(inline) - AKE_MAX_REFS} 张")

        body: dict = {"model": model, "prompt": prompt,
                      "seconds": str(int(seconds)), "size": size}
        field = "无"
        if refs:
            if inline:
                body["input_reference"] = refs      # 字符串数组，URL/base64 都收
                field = "input_reference(含base64)"
            else:
                body["reference_images"] = [{"url": u} for u in refs]   # 对象数组
                field = "reference_images"

        print(f"[Respect] 阿珂 {model}: seconds='{seconds}' size={size} 参考图{len(refs)}张 → {field}")
        print(f"[Respect] body={json.dumps(body, ensure_ascii=False)[:300]}")
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
                local = download_to_output(url, cfg, prefix="ake", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] 阿珂 视频下载失败: {exc}")
        return (url, local, task_id or "")


NODE_CLASS_MAPPINGS = {
    "RespectAkeVideo": RespectAkeVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectAkeVideo": "Respect 阿珂 Grok视频（snumom）",
}
