"""Respect ComfyUI 扩展 - 无限画布（`https://videogogo.top/api`）节点。

协议与 `script-to-video-studio/core/providers/wuxianhuabu.py` 同源。**这不是阿珂。**

只做视频，两个模型：
  · `seedance-2.5-hf-720p` —— 720p，4–30 秒
  · `seedance-2.5-hf`     —— 480p，4–30 秒
分辨率**由模型名决定**（不是单独的参数），所以这里不给分辨率选项 —— 给了也是
两个必然对不上的字段，选错还不报错。

混合参考：最多 30 图 / 10 视频 / 10 音频，默认开音频、关水印。

⚠ 三个要点：

1. **本机图能直接用。** 这家有素材上传口：`POST /v1/assets`（裸字节 + `X-File-Name`
   头），换回 `asset_id` 再放进 `reference_images` 字符串数组。所以 IMAGE 输入口
   在这里是真能用的 —— 跟鹤不一样（鹤只收公网 URL）。
2. **提交带 `Idempotency-Key`。** 重投同一个 key 不会重复计费，所以这里每次生成
   都生成一个新 key、而重试沿用同一个。
3. 认不出的参考素材**当场停**，不当成 asset_id 发出去 —— 服务商认不出就当没有
   这张参考图，片子照出、照计费，脸不对而且一处都不报错。
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import time
import uuid

from .utils import (RespectAPIError, api_request, download_to_output,
                    dynamic_image_inputs, dynamic_url_inputs, ensure_config,
                    expand_image_frames, tensor_to_b64)

CATEGORY = "Respect/无限画布"
BASE_HINT = "base_url 填 https://videogogo.top/api"

WXHB_MODELS = ["seedance-2.5-hf-720p", "seedance-2.5-hf"]
WXHB_RESOLUTION = {"seedance-2.5-hf-720p": "720p", "seedance-2.5-hf": "480p"}
WXHB_RATIOS = ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9"]
WXHB_MAX_IMAGES, WXHB_MAX_VIDEOS, WXHB_MAX_AUDIOS = 30, 10, 10

# 形状像 asset_id 才放行。**不能什么都放行** —— 一个写错的路径原样发出去
# 就是一个假 asset_id，服务商认不出就当没有这张参考图。
_ASSET_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{8,128}$")


def _wxhb_upload(cfg, blob: bytes, mime: str, name: str, kind: str) -> str:
    """裸字节 → asset_id。`POST /v1/assets`，Content-Type 是文件本身的类型。"""
    headers = dict(cfg.headers(content_type=mime))
    headers["X-File-Name"] = name
    resp = api_request(cfg, "POST", "/v1/assets", data=blob,
                       headers=headers, retries=2, timeout=max(cfg.timeout, 600))
    data = resp.json() if resp.content else {}
    asset_id = data.get("asset_id", "") if isinstance(data, dict) else ""
    if not asset_id:
        raise RespectAPIError(
            f"无限画布上传{kind}素材没返回 asset_id："
            f"{json.dumps(data, ensure_ascii=False)[:300]}")
    print(f"[Respect] 无限画布 {kind}参考素材已上传：{asset_id}")
    return str(asset_id)


def _wxhb_asset(cfg, ref: str, kind: str) -> str:
    """一条参考素材 → 服务商认的形式（URL 原样 / data URI 上传 / asset_id 原样）。"""
    value = str(ref or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("data:"):
        head, _, payload = value.partition(",")
        mime = (head[5:].split(";", 1)[0] or "application/octet-stream")
        try:
            blob = base64.b64decode(payload, validate=False)
        except (TypeError, ValueError) as exc:
            raise RespectAPIError(f"无限画布{kind}参考素材的 data URI 解不开") from exc
        if not blob:
            raise RespectAPIError(f"无限画布{kind}参考素材是空的")
        ext = mimetypes.guess_extension(mime) or ".bin"
        return _wxhb_upload(cfg, blob, mime, f"reference-{uuid.uuid4().hex[:12]}{ext}", kind)
    if _ASSET_ID_RE.match(value):
        return value
    raise RespectAPIError(
        f"无限画布{kind}参考素材认不出：{value[:120]!r}。\n"
        f"既不是 http 链接、不是 data URI，形状也不像 asset_id。\n"
        f"**不会当成 asset_id 发出去** —— 服务商认不出就当没有这张参考图，"
        f"片子照出、照计费，脸不对而且一处都不报错。")


class RespectWuxianhuabuVideo:
    """无限画布 视频。`POST /v1/videos` 提交 → `GET /v1/videos/{id}` 轮询。"""

    DESCRIPTION = ("无限画布 视频(base_url=https://videogogo.top/api)。Seedance 2.5，4-30 秒，"
                   "最多 30图/10视频/10音频。**分辨率由模型名决定**(-720p 是 720p，另一个 480p)。"
                   "本机图会自动传 /v1/assets 换 asset_id，不用先配对象存储。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": BASE_HINT}),
                "model": (WXHB_MODELS, {"default": "seedance-2.5-hf-720p",
                                        "tooltip": "分辨率跟着模型走：-720p → 720p，seedance-2.5-hf → 480p"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "seconds": ("INT", {"default": 15, "min": 4, "max": 30}),
                "ratio": (WXHB_RATIOS, {"default": "9:16"}),
                "poll_interval": ("INT", {"default": 6, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 2400, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "image_1": ("IMAGE", {"tooltip": "参考图；会自动上传换 asset_id。接批次会展开"}),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "ref_url_1": ("STRING", {"default": "", "multiline": False,
                                         "placeholder": "参考图公网 URL 或 asset_id（和 IMAGE 口可以混用）"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "video_urls": ("STRING", {"default": "", "multiline": True,
                                          "placeholder": "参考视频 URL / asset_id，每行一个"}),
                "audio_urls": ("STRING", {"default": "", "multiline": True,
                                          "placeholder": "参考音频 URL / asset_id，每行一个"}),
                "generate_audio": ("BOOLEAN", {"default": True}),
                "watermark": ("BOOLEAN", {"default": False}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 30, "step": 1,
                                       "tooltip": "参考图接口数量；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("在线视频 URL", "下载到本地的路径", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, seconds, ratio,
                 poll_interval, poll_timeout, auto_download,
                 video_urls="", audio_urls="", generate_audio=True, watermark=False,
                 save_dir="", filename="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        if model not in WXHB_RESOLUTION:
            raise RespectAPIError(
                f"无限画布不认识模型 {model!r}，只能选 {' / '.join(WXHB_MODELS)}")
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")
        sec = int(seconds)
        if not 4 <= sec <= 30:
            raise RespectAPIError(f"无限画布只支持 4–30 秒，这一项填的是 {sec} 秒")

        frames = expand_image_frames(dynamic_image_inputs(kwargs))
        url_refs = dynamic_url_inputs(kwargs)
        videos = [ln.strip() for ln in (video_urls or "").splitlines() if ln.strip()]
        audios = [ln.strip() for ln in (audio_urls or "").splitlines() if ln.strip()]

        total_i = len(frames) + len(url_refs)
        if (total_i > WXHB_MAX_IMAGES or len(videos) > WXHB_MAX_VIDEOS
                or len(audios) > WXHB_MAX_AUDIOS):
            raise RespectAPIError(
                f"无限画布素材超限：图片 {total_i}/{WXHB_MAX_IMAGES}、"
                f"视频 {len(videos)}/{WXHB_MAX_VIDEOS}、音频 {len(audios)}/{WXHB_MAX_AUDIOS}。\n"
                f"**不会自动裁掉多的** —— 裁掉哪张都会让画面里少一个人，而且不报错。")

        images: list = []
        for frame in frames:
            for b64 in tensor_to_b64(frame, fmt="PNG", max_side=2048):
                images.append(_wxhb_asset(cfg, b64, "图片"))
        images += [_wxhb_asset(cfg, u, "图片") for u in url_refs]
        videos = [_wxhb_asset(cfg, v, "视频") for v in videos]
        audios = [_wxhb_asset(cfg, a, "音频") for a in audios]

        body: dict = {
            "model": model,
            "prompt": prompt,
            "seconds": sec,
            "resolution": WXHB_RESOLUTION[model],
            "ratio": ratio,
            "generate_audio": bool(generate_audio),
            "watermark": bool(watermark),
        }
        if images:
            body["reference_images"] = images
        if videos:
            body["reference_videos"] = videos
        if audios:
            body["reference_audios"] = audios

        # 同一次生成用同一个 key：重投不会重复计费
        headers = dict(cfg.headers(content_type="application/json"))
        headers["Idempotency-Key"] = str(uuid.uuid4())
        print(f"[Respect] 无限画布 {model}: {sec}s {body['resolution']} {ratio} "
              f"图{len(images)}/视频{len(videos)}/音频{len(audios)}")
        resp = api_request(cfg, "POST", "/v1/videos", json_body=body,
                           headers=headers, retries=2, timeout=300)
        data = resp.json() if resp.content else {}
        task_id = str(data.get("task_id") or data.get("id") or "") if isinstance(data, dict) else ""
        video_url = _wxhb_pick_url(data)
        if not video_url:
            if not task_id:
                raise RespectAPIError(
                    f"无限画布提交没返回任务 ID：{json.dumps(data, ensure_ascii=False)[:400]}")
            video_url = _wxhb_poll(cfg, task_id, int(poll_interval), int(poll_timeout))

        local = ""
        if auto_download and video_url:
            try:
                local = download_to_output(video_url, cfg, prefix="wxhb_video",
                                           save_dir=save_dir, filename=filename)
            except Exception as exc:                        # noqa: BLE001
                print(f"[Respect] 无限画布 视频下载失败（链接仍可用）：{exc}")
        return (video_url, local, task_id)


def _wxhb_pick_url(payload) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("video_url", "url", "result_url", "download_url"):
        val = payload.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    inner = payload.get("data")
    return _wxhb_pick_url(inner) if isinstance(inner, dict) else ""


def _wxhb_poll(cfg, task_id: str, interval: int, timeout: int) -> str:
    start, last = time.time(), ""
    while time.time() - start < timeout:
        resp = api_request(cfg, "GET", f"/v1/videos/{task_id}", retries=1, timeout=60)
        data = resp.json() if resp.content else {}
        inner = data.get("data") if isinstance(data.get("data"), dict) else data
        status = str((inner or {}).get("status") or "").lower()
        if status != last:
            print(f"[Respect] 无限画布 {task_id}: {status or '(无状态字段)'}")
            last = status
        if status in ("failed", "failure", "error"):
            raise RespectAPIError(
                f"无限画布任务失败：{json.dumps(data, ensure_ascii=False)[:300]}")
        url = _wxhb_pick_url(data)
        if url:
            return url
        time.sleep(interval)
    raise RespectAPIError(f"无限画布任务超时：{task_id}（可调大 poll_timeout）")


NODE_CLASS_MAPPINGS = {
    "RespectWuxianhuabuVideo": RespectWuxianhuabuVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectWuxianhuabuVideo": "Respect 无限画布 视频",
}
