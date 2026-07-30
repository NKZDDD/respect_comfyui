"""Respect ComfyUI 扩展 - 灵感鸭AI(www.lingganyaapi.com) 统一接口节点。

灵感鸭是「三步式」异步：
- 视频：`POST /v1/videos?async=true` → `GET /v1/videos/{id}` → `GET /v1/videos/{id}/content`
- 图片：`POST /v1/images/generations?async=true` → `GET /v1/images/{id}` → `GET /v1/images/{id}/content`

在 Respect API 设置里把 base_url 填 `https://www.lingganyaapi.com`。

字段与别家不同（别拿 sora/通用节点硬连）：
- `size` 是**宽高比**（16:9），不是像素；`seconds` 才是时长（sora 传字符串、sd 传整数）
- `images[]` 是参考图**URL 数组**（≤9）——建议接「对象存储上传」拿 R2 URL
- SD 专属：`resolution` 必须放**顶层**（sd-2.0=1080p/720p，sd-fast=720p/480p）；
  参考视频/音频/参考模式/是否生成音频只能放 `extra{}` 里

模型名/尺寸/分辨率都是「下拉 + custom_* 可填覆盖」——灵感鸭上新模型时自己填即可，不用改代码。
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import torch

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
)
from .video_nodes import _ASYNC_DONE, _ASYNC_FAIL, _async_extract_url, _async_status, _sd2_extract_task_id

CATEGORY = "Respect"

LG_VIDEO_MODELS = ["sora-2", "sora-2-pro", "sd-2.0", "sd-fast"]
LG_SIZES = ["16:9", "9:16", "1:1", "4:3", "3:4"]
LG_RESOLUTIONS = ["auto(按模型)", "1080p", "720p", "480p"]
LG_TRISTATE = ["auto(不传)", "true", "false"]
LG_IMAGE_MODELS = ["gpt-image-2"]
LG_IMAGE_SIZES = ["1024x1024", "1536x1024", "1024x1536"]


def _lg_refs(tensors, urls, cap: int = 9) -> list[str]:
    """参考图：公网 URL 优先（官方 images[] 要 URL），IMAGE 兜底转 base64（批次会展开成多张）。"""
    refs: list[str] = []
    for u in urls:
        if isinstance(u, str) and u.strip():
            refs.append(u.strip())
    for frame in expand_image_frames(tensors):
        b = tensor_to_b64(frame, fmt="JPEG", quality=90, max_side=1536)
        if b:
            refs.append(b[0])
    return refs[:cap]


def _lg_lines(s: str, cap: int = 9) -> list[str]:
    return [ln.strip() for ln in (s or "").splitlines() if ln.strip()][:cap]


def _lg_submit(cfg, path: str, body: dict, timeout: int = 300) -> tuple[Any, str]:
    """提交任务（带 ?async=true）。返回 (原始响应, task_id)。"""
    resp = api_request(cfg, "POST", path, json_body=body, params={"async": "true"},
                       retries=2, timeout=max(cfg.timeout, timeout))
    data = resp.json() if resp.content else {}
    return data, _sd2_extract_task_id(data)


def _lg_content(cfg, kind: str, task_id: str, index: str = "") -> Any:
    """取成品：GET /v1/{kind}/{id}/content。"""
    params = {"index": index} if index else None
    resp = api_request(cfg, "GET", f"/v1/{kind}/{task_id}/content", params=params, retries=1, timeout=120)
    return resp.json() if resp.content else {}


def _lg_poll(cfg, kind: str, task_id: str, interval: int, timeout: int, images: bool = False):
    """轮询 GET /v1/{kind}/{id}；完成后若没直链就再取 /content。

    返回：images=False → 视频 URL 字符串；images=True → 图片资源列表。
    """
    def _pick(data):
        return extract_image_payloads(data) if images else _async_extract_url(data)

    start, last = time.time(), ""
    while time.time() - start < timeout:
        try:
            resp = api_request(cfg, "GET", f"/v1/{kind}/{task_id}", retries=1, timeout=60)
        except RespectAPIError as exc:
            print(f"[Respect] 灵感鸭轮询错误，继续重试: {exc}")
            time.sleep(interval)
            continue
        data = resp.json() if resp.content else {}
        status = _async_status(data)
        got = _pick(data)
        if status and status != last:
            print(f"[Respect] 灵感鸭任务 {task_id} 状态: {status}")
            last = status
        if status in _ASYNC_FAIL:
            raise RespectAPIError(f"任务失败: {json.dumps(data, ensure_ascii=False)[:600]}")
        done = status in _ASYNC_DONE
        if got and (not status or done):
            return got
        if done:
            # 完成但查询接口没给资源 → 取成品接口
            got = _pick(_lg_content(cfg, kind, task_id))
            if got:
                return got
            raise RespectAPIError(f"任务已完成但未取到结果: {task_id}")
        time.sleep(interval)
    raise RespectAPIError(f"任务超时: {task_id}")


# ---------------------------------------------------------------------------
# 灵感鸭 统一视频（sora-2 / SD吊炸天 共用）
# ---------------------------------------------------------------------------


class RespectLingganyaVideo:
    """灵感鸭 统一视频。`POST /v1/videos?async=true` + 查询 + 取成品。

    body：`{model, prompt, size(比例), seconds, images[]}`；
    SD 额外带顶层 `resolution` 与 `extra{reference_mode, reference_videos, reference_audios, generate_audio}`。
    """

    DESCRIPTION = ("灵感鸭统一视频(base_url=www.lingganyaapi.com)。size=宽高比、seconds=时长；"
                   "SD(sd-2.0/sd-fast)自动带顶层 resolution 和 extra{参考视频/音频/模式/生成音频}；"
                   "参考图 images[] 建议接对象存储上传的公网URL(≤9)。模型/尺寸/分辨率都可用 custom_* 覆盖。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://www.lingganyaapi.com"}),
                "model": (LG_VIDEO_MODELS, {"default": "sora-2", "tooltip": "上新模型时用 custom_model 填即可"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "size": (LG_SIZES, {"default": "16:9", "tooltip": "宽高比（不是像素）"}),
                "seconds": ("INT", {"default": 12, "min": 1, "max": 60, "tooltip": "时长；SD 限 4-15，sora 常见 12"}),
                "resolution": (LG_RESOLUTIONS, {"default": "auto(按模型)", "tooltip": "SD 必填且在顶层：sd-2.0=1080p/720p，sd-fast=720p/480p；auto→SD自动720p、sora不传"}),
                "poll_interval": ("INT", {"default": 8, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "参考图公网URL(接对象存储上传)"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "extra_image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "追加参考图URL，每行一个（连同上面共≤9）"}),
                "first_frame": ("IMAGE", {"tooltip": "没有公网URL时兜底：转base64塞 images[]（官方要URL，可能不被接受）"}),
                "ref_image_2": ("IMAGE",),
                "ref_image_3": ("IMAGE",),
                "ref_image_4": ("IMAGE",),
                "reference_mode": ("STRING", {"default": "", "multiline": False, "placeholder": "SD extra.reference_mode，按灵感鸭文档填", "tooltip": "透传到 extra；留空不传"}),
                "reference_videos": ("STRING", {"default": "", "multiline": True, "placeholder": "SD extra.reference_videos，参考视频URL每行一个"}),
                "reference_audios": ("STRING", {"default": "", "multiline": True, "placeholder": "SD extra.reference_audios，参考音频URL每行一个"}),
                "generate_audio": (LG_TRISTATE, {"default": "auto(不传)", "tooltip": "SD extra.generate_audio；auto=不传该字段"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了覆盖上面模型"}),
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖 size"}),
                "custom_resolution": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖 resolution"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("在线视频 URL", "下载到本地的路径（预览/拼接用这个）", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, size, seconds, resolution,
                 poll_interval, poll_timeout, auto_download,
                 ref_url_1="", ref_url_2="", ref_url_3="", ref_url_4="", extra_image_urls="",
                 first_frame=None, ref_image_2=None, ref_image_3=None, ref_image_4=None,
                 reference_mode="", reference_videos="", reference_audios="", generate_audio="auto(不传)",
                 custom_model="", custom_size="", custom_resolution="", save_dir="", filename=""):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        size = (custom_size or "").strip() or size
        is_sd = model.lower().startswith("sd")

        body: dict = {
            "model": model,
            "prompt": prompt,
            "size": size,
            # sora 文档示例为字符串，SD 文档为整数
            "seconds": int(seconds) if is_sd else str(int(seconds)),
        }

        refs = _lg_refs([first_frame, ref_image_2, ref_image_3, ref_image_4],
                        [ref_url_1, ref_url_2, ref_url_3, ref_url_4] + _lg_lines(extra_image_urls))
        if refs:
            body["images"] = refs

        res = (custom_resolution or "").strip()
        if not res and not resolution.startswith("auto"):
            res = resolution
        if not res and is_sd:
            res = "720p"  # SD 必填，给个两档都支持的默认
        if res:
            body["resolution"] = res  # 必须顶层

        extra: dict = {}
        if (reference_mode or "").strip():
            extra["reference_mode"] = reference_mode.strip()
        vids = _lg_lines(reference_videos, 3)
        if vids:
            extra["reference_videos"] = vids
        auds = _lg_lines(reference_audios, 3)
        if auds:
            extra["reference_audios"] = auds
        if not generate_audio.startswith("auto"):
            extra["generate_audio"] = (generate_audio == "true")
        if extra:
            body["extra"] = extra

        data, task_id = _lg_submit(cfg, "/v1/videos", body)
        url = _async_extract_url(data)
        if not url:
            if not task_id:
                raise RespectAPIError(f"提交未返回 task_id 或视频URL: {json.dumps(data, ensure_ascii=False)[:400]}")
            url = _lg_poll(cfg, "videos", task_id, int(poll_interval), int(poll_timeout))

        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="lingganya", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] 灵感鸭视频下载失败: {exc}")
        return (url, local, task_id or "")


# ---------------------------------------------------------------------------
# 灵感鸭 统一图片（gpt-image-2）
# ---------------------------------------------------------------------------


class RespectLingganyaImage:
    """灵感鸭 统一图片。`POST /v1/images/generations?async=true` + 查询 + 取成品。

    body：`{model, prompt, size(像素), n, images[]}`。参考图建议给公网 URL。
    """

    DESCRIPTION = ("灵感鸭统一图片(base_url=www.lingganyaapi.com)。gpt-image-2，size 用像素"
                   "(1024x1024/1536x1024/1024x1536)，参考图 images[] 建议接对象存储上传的URL。"
                   "模型/尺寸可用 custom_* 覆盖。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://www.lingganyaapi.com"}),
                "model": (LG_IMAGE_MODELS, {"default": "gpt-image-2", "tooltip": "上新模型用 custom_model 填"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "size": (LG_IMAGE_SIZES, {"default": "1024x1024", "tooltip": "像素尺寸（不是比例）"}),
                "n": ("INT", {"default": 1, "min": 1, "max": 10}),
                "poll_interval": ("INT", {"default": 5, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 900, "min": 60, "max": 7200}),
            },
            "optional": {
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "参考图公网URL(接对象存储上传)"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "extra_image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "追加参考图URL，每行一个"}),
                "image_1": ("IMAGE", {"tooltip": "没有公网URL时兜底：转base64塞 images[]"}),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖 size，如 2048x2048"}),
                # 新控件加在最后：已保存的工作流不会错位
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 64, "step": 1, "tooltip": "参考图接口数量；改完点节点上的『更新输入口』按钮增减 image_N 槽"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_urls", "task_id")
    OUTPUT_TOOLTIPS = ("生成的图片", "图片URL（每行一个）", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, size, n, poll_interval, poll_timeout,
                 ref_url_1="", ref_url_2="", ref_url_3="", ref_url_4="", extra_image_urls="",
                 custom_model="", custom_size="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        size = (custom_size or "").strip() or size

        body: dict = {"model": model, "prompt": prompt, "size": size, "n": int(n)}
        refs = _lg_refs(dynamic_image_inputs(kwargs),
                        [ref_url_1, ref_url_2, ref_url_3, ref_url_4] + _lg_lines(extra_image_urls))
        if refs:
            body["images"] = refs

        data, task_id = _lg_submit(cfg, "/v1/images/generations", body)
        items = extract_image_payloads(data)
        if not items:
            if not task_id:
                raise RespectAPIError(f"提交未返回 task_id 或图片: {json.dumps(data, ensure_ascii=False)[:400]}")
            items = _lg_poll(cfg, "images", task_id, int(poll_interval), int(poll_timeout), images=True)

        tensors = []
        for it in items:
            t = resolve_image_to_tensor(it, cfg)
            if t is not None:
                tensors.append(t)
        if not tensors:
            raise RespectAPIError(f"未能解析出图片: {str(items)[:300]}")
        image = torch.cat(tensors, dim=0) if len(tensors) > 1 else tensors[0]
        urls = "\n".join(i for i in items if isinstance(i, str) and i.startswith("http"))
        return (image, urls, task_id or "")


NODE_CLASS_MAPPINGS = {
    "RespectLingganyaVideo": RespectLingganyaVideo,
    "RespectLingganyaImage": RespectLingganyaImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectLingganyaVideo": "Respect 灵感鸭 统一视频（sora/SD）",
    "RespectLingganyaImage": "Respect 灵感鸭 统一图片（gpt-image-2）",
}
