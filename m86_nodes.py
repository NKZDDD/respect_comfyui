"""Respect ComfyUI 扩展 - M86 / New API（`https://yiyun.xiaoge.uk`）节点。

OpenAI 兼容中转，当前三条线：
- 对话  `POST /v1/chat/completions`（用现成的 `Respect Chat 对话`，base_url 填这家即可，无需新节点）
- 图片  `POST /v1/images/generations` —— `seed-image-1.0`，**同步**返回 `data[].url`
- 视频  `POST /v1/videos` —— `seed-2.0`，异步；`GET /v1/videos/{task_id}` 轮询，
        完成取 `url` / `video_url` / `urls[]`；也可 `GET /v1/videos/{task_id}/content`

和别家最容易搞混的三点（写错就静默出错）：
1. **图片的 `size` 是比例**（`1:1`/`2:3`/`9:16`…）不是像素
2. **视频的比例字段叫 `ratio`** —— 文档写明 `size` 只是客户端兼容字段，优先用 `ratio`；
   发 `aspect_ratio` 是别家的写法，这里没用
3. 参考图 JSON 里是 **URL 数组**；本地图要走 **multipart**（同一个 `images` 字段重复多次）

计费：`seed-2.0` 固定 $1.2/次，5～15 秒同价。
"""

from __future__ import annotations

import json

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
    tensors_concat,
)
from .video_nodes import _async_extract_url, _async_poll, _sd2_extract_task_id

CATEGORY = "Respect/M86"

M86_VIDEO_MODELS = ["seed-2.0"]
M86_IMAGE_MODELS = ["seed-image-1.0"]
# 文档列的两套比例（图片没有 21:9，视频没有 2:3）
M86_IMAGE_RATIOS = ["1:1", "2:3", "3:4", "4:3", "9:16", "16:9"]
M86_VIDEO_RATIOS = ["1:1", "3:4", "4:3", "9:16", "16:9", "21:9"]
M86_FORMATS = ["url", "b64_json"]


def _m86_lines(s: str, cap: int = 9) -> list:
    return [ln.strip() for ln in (s or "").splitlines() if ln.strip()][:cap]


def _m86_jpeg_bytes(frame) -> bytes:
    """单帧 IMAGE → JPEG bytes（multipart 用）。"""
    import base64

    b = tensor_to_b64(frame, fmt="JPEG", quality=90, max_side=1536)
    if not b:
        return b""
    return base64.b64decode(b[0].split(",", 1)[1])


# ---------------------------------------------------------------------------
# M86 视频（seed-2.0）
# ---------------------------------------------------------------------------


class RespectM86Video:
    """M86 视频 `seed-2.0`。`POST /v1/videos` 提交 + `GET /v1/videos/{task_id}` 轮询。

    - 比例字段是 **`ratio`**（不是 aspect_ratio / size）
    - 参考图：填了公网 URL 走 JSON `images[]`；接了 IMAGE 走 **multipart**（`images` 字段重复多次）
    - 计费固定 $1.2/次，5～15 秒同价，所以默认给满 15 秒
    """

    DESCRIPTION = ("M86 视频 seed-2.0（base_url=https://yiyun.xiaoge.uk）。比例字段是 ratio；"
                   "参考图给URL走JSON、接IMAGE自动走multipart。$1.2/次固定，5~15秒同价。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://yiyun.xiaoge.uk"}),
                "model": (M86_VIDEO_MODELS, {"default": "seed-2.0"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "seconds": ("INT", {"default": 15, "min": 1, "max": 15, "tooltip": "5~15 秒同价（$1.2/次），默认给满"}),
                "ratio": (M86_VIDEO_RATIOS, {"default": "9:16", "tooltip": "该接口的比例字段就叫 ratio"}),
                "poll_interval": ("INT", {"default": 15, "min": 2, "max": 60, "tooltip": "文档示例用 15 秒"}),
                "poll_timeout": ("INT", {"default": 2400, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "image_1": ("IMAGE", {"tooltip": "本地参考图 → multipart 上传（同一个 images 字段重复多次）"}),
                "image_2": ("IMAGE",),
                "image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考图公网URL，每行一个（填了就走 JSON images[]，优先于 IMAGE）"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 2, "min": 1, "max": 9, "step": 1, "tooltip": "参考图接口数量；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("在线视频 URL", "下载到本地的路径（预览/拼接用这个）", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, seconds, ratio, poll_interval, poll_timeout,
                 auto_download, image_urls="", custom_model="", save_dir="", filename="",
                 inputcount=2, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        fields = {"model": model, "prompt": prompt,
                  "seconds": str(int(seconds)), "ratio": ratio}
        urls = _m86_lines(image_urls)

        if urls:
            if dynamic_image_inputs(kwargs):
                print("[Respect] 同时给了 URL 和 IMAGE —— 走 JSON 用 URL，接入的 IMAGE 本次被忽略"
                      "（两种混用文档没定义；要用本地图就把 URL 框清空）")
            body = dict(fields)
            body["images"] = urls
            print(f"[Respect] M86 视频提交(JSON) ratio={ratio} seconds={seconds} 参考图={len(urls)}张URL"
                  f"（顺序即 images[0..N]，第1个可当首帧、最后一个可当尾帧）")
            print(f"[Respect] body={json.dumps(body, ensure_ascii=False)}")
            resp = api_request(cfg, "POST", "/v1/videos", json_body=body,
                               retries=2, timeout=max(cfg.timeout, 300))
        else:
            frames = expand_image_frames(dynamic_image_inputs(kwargs))[:9]
            files = [(k, (None, v)) for k, v in fields.items()]
            for i, frame in enumerate(frames, start=1):
                data = _m86_jpeg_bytes(frame)
                if data:
                    files.append(("images", (f"frame_{i:02d}.jpg", data, "image/jpeg")))
            mode = f"multipart {len(frames)}张本地图" if frames else "纯文生"
            print(f"[Respect] M86 视频提交({mode}) ratio={ratio} seconds={seconds}")
            resp = api_request(cfg, "POST", "/v1/videos", files=files,
                               retries=2, timeout=max(cfg.timeout, 300))

        data = resp.json() if resp.content else {}
        url = _async_extract_url(data)
        task_id = _sd2_extract_task_id(data)
        if not url:
            if not task_id:
                raise RespectAPIError(f"提交未返回 task_id 或视频URL: {json.dumps(data, ensure_ascii=False)[:400]}")
            url = _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))

        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="m86", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] M86 视频下载失败: {exc}")
        return (url, local, task_id or "")


# ---------------------------------------------------------------------------
# M86 图片（seed-image-1.0，同步）
# ---------------------------------------------------------------------------


class RespectM86Image:
    """M86 图片 `seed-image-1.0`。`POST /v1/images/generations`，**同步**返回。

    注意 **`size` 是比例**（`1:1`/`9:16`…）不是像素。`ref_images` 是参考图 URL 数组，
    文档写明只收链接（且模型支持时才生效）。
    """

    DESCRIPTION = ("M86 图片 seed-image-1.0（同步出图）。**size 是比例**不是像素；"
                   "ref_images 只收公网URL。response_format 可选 url / b64_json。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://yiyun.xiaoge.uk"}),
                "model": (M86_IMAGE_MODELS, {"default": "seed-image-1.0"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "size": (M86_IMAGE_RATIOS, {"default": "9:16", "tooltip": "这家的 size 就是比例，不是像素"}),
                "n": ("INT", {"default": 1, "min": 1, "max": 10}),
            },
            "optional": {
                "response_format": (M86_FORMATS, {"default": "url"}),
                "style": ("STRING", {"default": "", "multiline": False, "placeholder": "可选：风格描述"}),
                "ref_image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考图公网URL，每行一个（文档：只收链接）"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "image_urls")
    OUTPUT_TOOLTIPS = ("生成的图片", "图片URL（每行一个）")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, size, n,
                 response_format="url", style="", ref_image_urls="", custom_model=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        body = {
            "model": model,
            "prompt": prompt,
            "size": size,                 # 这家的 size = 比例
            "n": int(n),
            "response_format": response_format,
        }
        if (style or "").strip():
            body["style"] = style.strip()
        refs = _m86_lines(ref_image_urls)
        if refs:
            body["ref_images"] = refs

        print(f"[Respect] M86 出图 size(比例)={size} n={n} 参考图={len(refs)}张")
        resp = api_request(cfg, "POST", "/v1/images/generations", json_body=body,
                           retries=2, timeout=max(cfg.timeout, 300))
        data = resp.json() if resp.content else {}
        items = extract_image_payloads(data)
        if not items:
            raise RespectAPIError(f"未能从响应中提取图片: {json.dumps(data, ensure_ascii=False)[:400]}")
        tensors = [t for t in (resolve_image_to_tensor(i, cfg) for i in items) if t is not None]
        if not tensors:
            raise RespectAPIError(f"取到结果但无法解析为图片: {str(items)[:300]}")
        urls = "\n".join(i for i in items if isinstance(i, str) and i.startswith("http"))
        return (tensors_concat(tensors), urls)


NODE_CLASS_MAPPINGS = {
    "RespectM86Video": RespectM86Video,
    "RespectM86Image": RespectM86Image,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectM86Video": "Respect M86 视频（seed-2.0）",
    "RespectM86Image": "Respect M86 图片（seed-image-1.0）",
}
