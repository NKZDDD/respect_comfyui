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
from typing import Any

import torch

from .utils import (
    dynamic_url_inputs,
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

CATEGORY = "Respect/灵感鸭"

# 视频模型：以 `GET /v1/models`（用「Respect 加载模型列表」节点）的实际返回为准 —— 文档的模型表不全，
# 真实还有 -T / -vip 这些变体。注意 veo 是下划线 veo_3_1_fast，和别家的 veo_3_1-fast 写法不同。
LG_VIDEO_MODELS = [
    # SD 吊炸天：文档明确支持的四个（分辨率走顶层 resolution，别用带分辨率后缀的名字）
    "sd-fast", "sd-2.0", "sd-fast-special", "sd-2.0-special",
    # -T / -vip：/v1/models 里有（计费通道），但 SD 视频接口文档未列 —— 实测会让上游报
    # 404 Invalid URL (POST /api/v3/contents/generations/tasks)，谨慎使用
    "sd-fast-T", "sd-fast-vip", "sd-2.0-T", "sd-2.0-vip",
    # grok
    "grok-imagine-video-1.5-preview", "grok-video-1.5-special", "grok-image-video-special",
    # gemini omni
    "gemini_omni_flash", "gemini-omni-flash-special", "Gemini-Omni-vip",
    # veo
    "veo_3_1_fast", "veo_3_1_fast_hd", "veo_3_1_fast_fl_hd",
    # sora
    "sora-2", "sora-2-pro", "sora-2-vip",
]
# 每个模型的硬约束：seconds 是固定档位（不是任意值）、参考图上限、需不需要参考图、resolution 档
LG_VIDEO_SPECS: dict[str, dict] = {
    "sora-2": {"seconds": [4, 8, 12], "max_images": 1},
    "sora-2-pro": {"seconds": [12], "max_images": 1},
    "sora-2-vip": {"seconds": [12], "max_images": 1},
    "gemini_omni_flash": {"seconds": [10], "max_images": 7},
    "gemini-omni-flash-special": {"seconds": [10], "max_images": 7},
    "Gemini-Omni-vip": {"seconds": [10], "max_images": 7},
    "veo_3_1_fast": {"seconds": [8], "max_images": 3},
    "veo_3_1_fast_hd": {"seconds": [8], "max_images": 3},
    "veo_3_1_fast_fl_hd": {"seconds": [8], "max_images": 2},
    "grok-imagine-video-1.5-preview": {"seconds": [10, 15], "max_images": 1, "need_image": True},
    "grok-video-1.5-special": {"seconds": [10, 15], "max_images": 1, "need_image": True},
    "grok-image-video-special": {"seconds": [10, 15], "max_images": 7},
    # SD 吊炸天：resolution 顶层必填。extra 可放 reference_videos/reference_audios/generate_audio。
    # 只有 -special 那份文档写了「有 images 时 extra.reference_mode 必填」(media≤9张 / frame=2张)，
    # 普通 sd-2.0/sd-fast 的官方示例带图也没有 reference_mode → 不自动补，填了才发。
    "sd-2.0": {"seconds": list(range(4, 16)), "max_images": 9, "resolution": ["1080p", "720p"]},
    "sd-fast": {"seconds": list(range(4, 16)), "max_images": 9, "resolution": ["720p", "480p"]},
    "sd-2.0-special": {"seconds": list(range(5, 16)), "max_images": 9, "resolution": ["1080p", "720p"], "ref_mode": True},
    "sd-fast-special": {"seconds": list(range(5, 16)), "max_images": 9, "resolution": ["720p", "480p"], "ref_mode": True},
    # -T / -vip 是同系列的不同通道（价格/优先级不同），约束按各自基础型号处理
    "sd-2.0-T": {"seconds": list(range(4, 16)), "max_images": 9, "resolution": ["1080p", "720p"]},
    "sd-2.0-vip": {"seconds": list(range(4, 16)), "max_images": 9, "resolution": ["1080p", "720p"]},
    "sd-fast-T": {"seconds": list(range(4, 16)), "max_images": 9, "resolution": ["720p", "480p"]},
    "sd-fast-vip": {"seconds": list(range(4, 16)), "max_images": 9, "resolution": ["720p", "480p"]},
}
LG_SIZES = ["16:9", "9:16", "1:1", "720x1280", "1280x720", "1080x1920", "1920x1080",
            "1024x1024", "1024x1792", "1792x1024"]
LG_RESOLUTIONS = ["auto(按模型)", "1080p", "720p", "480p"]
LG_TRISTATE = ["auto(不传)", "true", "false"]
LG_IMAGE_MODELS = [
    "gpt-image-2", "gpt-image-2-special", "gpt-image-2-4k",
    "nano_banana_2", "nano_banana_2-special", "nano_banana_pro", "nano_banana_pro-special",
]
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


def _lg_brief(body: dict) -> str:
    """把请求体压成一行日志：base64/长串截断，方便对着 400 报错排查参数。"""
    def shrink(v):
        if isinstance(v, str):
            if v.startswith("data:"):
                head = v.split(",", 1)[0]
                return f"<{head} {len(v)}字符>"
            return v if len(v) <= 80 else v[:77] + "…"
        if isinstance(v, list):
            return [shrink(x) for x in v]
        if isinstance(v, dict):
            return {k: shrink(x) for k, x in v.items()}
        return v
    return json.dumps({k: shrink(v) for k, v in body.items()}, ensure_ascii=False)


def _lg_fit_video(body: dict) -> dict:
    """按模型规格纠正请求体：seconds 吸附到合法档位、参考图裁到上限、缺图报错。"""
    model = str(body.get("model") or "")
    spec = LG_VIDEO_SPECS.get(model)
    if not spec:
        return body                      # 自定义模型名不动，交给服务端判断

    allowed = spec["seconds"]
    try:
        sec = int(str(body.get("seconds")))
    except Exception:
        sec = allowed[-1]
    if sec not in allowed:
        near = min(allowed, key=lambda a: abs(a - sec))
        print(f"[Respect] 灵感鸭 {model} 只支持 seconds={allowed}，已把 {sec} 纠正为 {near}")
        sec = near
    # sd 系文档要整数，其余按官方示例给字符串（两者都被接受，保持与示例一致）
    body["seconds"] = sec if model.startswith("sd") else str(sec)

    imgs = body.get("images") or []
    cap = spec["max_images"]
    # SD 系：有参考图时 extra.reference_mode 必填（media=素材参考 / frame=首尾帧）
    if spec.get("ref_mode") and imgs:
        extra = body.setdefault("extra", {})
        mode = str(extra.get("reference_mode") or "").strip().lower()
        if mode not in ("media", "frame"):
            # 不靠张数猜：2 张图既可能是首尾帧(frame)、也可能是多图参考(media)，
            # 猜错等于悄悄改变了生成语义。所以留空一律按 media，要首尾帧必须自己填 frame。
            mode = "media"
            extra["reference_mode"] = mode
            print(f"[Respect] 灵感鸭 {model} 有参考图必须带 extra.reference_mode，未指定 → 按 media(素材参考) 提交。"
                  f"要做首尾帧请把 reference_mode 填 frame（正好 2 张：第1张首帧、第2张尾帧）")
        else:
            extra["reference_mode"] = mode
        if mode == "frame":
            cap = 2                       # frame 模式只能首帧+尾帧
    if len(imgs) > cap:
        print(f"[Respect] 灵感鸭 {model} 最多 {cap} 张参考图，已裁掉多余 {len(imgs) - cap} 张")
        body["images"] = imgs[:cap]
    if spec.get("need_image") and not body.get("images"):
        raise RespectAPIError(f"{model} 必须提供 1 张参考图（接 first_frame 或填 ref_url_1）")

    # resolution 只有 sd 系需要且必填；其余模型不该带
    res_allowed = spec.get("resolution")
    if res_allowed:
        if str(body.get("resolution") or "") not in res_allowed:
            print(f"[Respect] 灵感鸭 {model} 的 resolution 只能 {res_allowed}，已设为 {res_allowed[0]}")
            body["resolution"] = res_allowed[0]
    else:
        body.pop("resolution", None)
    return body


def _lg_hints(body: dict) -> list[str]:
    """按真实模型表逐条自检，生成「该查什么」清单（灵感鸭 400 只回一句笼统话）。"""
    model = str(body.get("model") or "")
    tips: list[str] = []
    spec = LG_VIDEO_SPECS.get(model)
    if model and spec is None:
        # 别武断说「不存在」：该站实际模型比文档多（-T/-vip 等），权威清单看『Respect 加载模型列表』
        tips.append(f"model={model} 不在插件内置清单里（可能是新通道，不代表无效）。"
                    f"用『Respect 加载模型列表』(GET /v1/models) 确认你的 key 能用哪些；"
                    f"内置已知：{', '.join(LG_VIDEO_SPECS)}")
    else:
        if str(body.get("seconds")) not in [str(s) for s in spec["seconds"]]:
            tips.append(f"seconds={body.get('seconds')} 不是 {model} 的合法档位，只能 {spec['seconds']}")
        imgs = body.get("images") or []
        if len(imgs) > spec["max_images"]:
            tips.append(f"参考图 {len(imgs)} 张超上限：{model} 最多 {spec['max_images']} 张")
        if spec.get("need_image") and not imgs:
            tips.append(f"{model} 必须带 1 张参考图")
        if not spec.get("resolution") and body.get("resolution"):
            tips.append(f"{model} 不该带 resolution 字段（只有 sd-* 需要）")
        if spec.get("ref_mode") and imgs:
            mode = str((body.get("extra") or {}).get("reference_mode") or "")
            if mode not in ("media", "frame"):
                tips.append(f"{model} 有参考图时 extra.reference_mode 必填：media(素材参考) 或 frame(首尾帧)")
            elif mode == "frame" and len(imgs) != 2:
                tips.append(f"reference_mode=frame 要正好 2 张图（首帧+尾帧），当前 {len(imgs)} 张")
    if model.endswith(("-T", "-vip")):
        tips.append(f"{model} 带 -T/-vip 后缀：这类通道在 /v1/models 里有，但 SD 视频接口文档只写了 "
                    "sd-2.0 / sd-fast(+-special)。实测会让上游报 404 Invalid URL "
                    "(POST /api/v3/contents/generations/tasks)，被包装成 503『请优化提示词』——"
                    "换成 sd-fast / sd-2.0 再试")
    tips.append("若报 503/笼统失败，去网关后台看『管理员原始错误』：那里才是上游真实报错（用户可见那句常是误导）")
    tips.append("提示词/参考图可能被内容审核拦下（报错里『生成内容』在最前）——换中性描述或换张图再试")
    tips.append("模型名区分写法：灵感鸭是 veo_3_1_fast（下划线）、gemini_omni_flash，别用别家网关的写法")
    return tips


def _lg_submit(cfg, path: str, body: dict, timeout: int = 300, use_async: bool = True) -> tuple[Any, str]:
    """提交任务。返回 (原始响应, task_id)。

    统一文档写明「所有任务默认异步、async 参数非必需」，所以视频不带 `?async=true`；
    图片那页文档标了必填，图片仍带。
    灵感鸭的 400 只回一句「生成内容或参数不符合要求」，所以这里把**实际发出的 body**
    和**自检清单**一起塞进异常，ComfyUI 弹窗里就能直接看到。
    """
    brief = _lg_brief(body)
    params = {"async": "true"} if use_async else None
    print(f"[Respect] 灵感鸭提交 {path}{'?async=true' if use_async else ''}  body={brief}")
    try:
        resp = api_request(cfg, "POST", path, json_body=body, params=params,
                           retries=2, timeout=max(cfg.timeout, timeout))
    except RespectAPIError as exc:
        lines = "\n".join(f"  {i + 1}. {t}" for i, t in enumerate(_lg_hints(body)))
        raise RespectAPIError(
            f"{exc}\n\n【实际发出的参数】{brief}\n\n【逐条自检】\n{lines}"
        ) from exc
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
                "model": (LG_VIDEO_MODELS, {"default": "sd-fast", "tooltip": "SD系用 sd-fast/sd-2.0(或 -special)——文档明确支持；-T/-vip 只在 /v1/models 里有、该接口未文档化，会让上游报 404。上新模型用 custom_model 填"}),
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
                "reference_mode": ("STRING", {"default": "", "multiline": False, "placeholder": "media=素材参考(默认) / frame=首尾帧", "tooltip": "SD系有参考图时必填。media=多图素材参考(≤9张)；frame=首尾帧(正好2张，第1张首帧、第2张尾帧)。留空一律按 media——张数无法区分这两种意图，不会替你猜"}),
                "reference_videos": ("STRING", {"default": "", "multiline": True, "placeholder": "SD extra.reference_videos，参考视频URL每行一个"}),
                "reference_audios": ("STRING", {"default": "", "multiline": True, "placeholder": "SD extra.reference_audios，参考音频URL每行一个"}),
                "generate_audio": (LG_TRISTATE, {"default": "auto(不传)", "tooltip": "SD extra.generate_audio；auto=不传该字段"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了覆盖上面模型"}),
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖 size"}),
                "custom_resolution": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖 resolution"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 30, "step": 1, "tooltip": "参考图接口数量；改完点节点上的『更新输入口』按钮增减"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("在线视频 URL", "下载到本地的路径（预览/拼接用这个）", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, size, seconds, resolution,
                 poll_interval, poll_timeout, auto_download, extra_image_urls="",
                 first_frame=None, ref_image_2=None, ref_image_3=None, ref_image_4=None,
                 reference_mode="", reference_videos="", reference_audios="", generate_audio="auto(不传)",
                 custom_model="", custom_size="", custom_resolution="", save_dir="", filename="", inputcount=4, **kwargs):
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

        # images[] 官方支持 公网URL / data:image;base64 / 纯 base64 三种，base64 是合法的
        refs = _lg_refs([first_frame, ref_image_2, ref_image_3, ref_image_4],
                        dynamic_url_inputs(kwargs) + _lg_lines(extra_image_urls))
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

        # 按该模型的硬约束纠正 seconds/参考图数/resolution（避免笼统 400）
        body = _lg_fit_video(body)
        data, task_id = _lg_submit(cfg, "/v1/videos", body, use_async=False)
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
