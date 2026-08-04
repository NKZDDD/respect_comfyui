"""Respect ComfyUI 扩展 - 零视工坊(zeroapi.ai-ren.cn) 专用节点。

零视工坊全部走 `POST /v1/videos` 提交 + `GET /v1/videos/{id}` 轮询（完成时 `url` = 无水印视频）。
在 Respect API 设置里把 base_url 填 `https://zeroapi.ai-ren.cn`，再用这些节点。

各能力 body 字段不同：
- Sora2/VEO 创建视频：{prompt, model, size, input_reference(多图用|分隔), remix_id}
- 图生视频：{model, prompt, image / images[], duration, size, stream}
参考图优先用公网 URL（接对象存储上传），否则把接入的 IMAGE 转 base64 内联。
"""

from __future__ import annotations

import base64
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
from .video_nodes import _async_poll, _submit_async_video
from .llm_nodes import _img_status, _img_task_id, _poll_image_task

CATEGORY = "Respect/零视工坊"


def _ref_b64_or_url(tensor, url: str = "") -> str:
    """优先用填的公网 URL；否则把 tensor 转 base64 data URL。"""
    if (url or "").strip():
        return url.strip()
    if tensor is not None and (not hasattr(tensor, "numel") or tensor.numel() > 0):
        b = tensor_to_b64(tensor[:1], fmt="JPEG", quality=90, max_side=1536)
        return b[0] if b else ""
    return ""


def _zero_lines(s: str) -> list[str]:
    return [ln.strip() for ln in (s or "").splitlines() if ln.strip()]


def _clean_urls(items) -> list[str]:
    """保序去空的 URL 列表。"""
    return [u.strip() for u in (items or []) if isinstance(u, str) and u.strip()]


def _zero_preflight(urls: list[str], timeout: int = 12) -> list[str]:
    """**不带鉴权**地试拉每个素材 URL，返回有问题的说明。

    零视会自己去 fetch 这些地址，拉不到就回 `Failed to fetch media URL`——
    提前用匿名请求验一遍，能直接指出是哪条、什么原因（403 多半是 R2 桶没公开）。
    """
    import requests

    problems: list[str] = []
    for u in urls:
        # 关键：用「服务器视角」——默认 UA、不带 Range。浏览器能打开不代表服务端能拉：
        # Cloudflare / 图床可能拦非浏览器 UA，或只放行 GET 不放行 HEAD。
        head_note = ""
        try:
            h = requests.head(u, timeout=timeout, allow_redirects=True)
            if h.status_code not in (200, 206, 405):   # 405=不支持HEAD，正常
                head_note = f"（HEAD 返回 {h.status_code}，有些抓取器先发 HEAD 会直接失败）"
        except Exception as exc:
            head_note = f"（HEAD 失败: {type(exc).__name__}）"

        try:
            g = requests.get(u, timeout=timeout, stream=True)
            code, ctype = g.status_code, g.headers.get("Content-Type", "")
            server = g.headers.get("Server", "")
            g.close()
            if code not in (200, 206):
                hint = ""
                if code in (401, 403):
                    hint = "（非公开可读，或被 CDN 机器人防护拦了非浏览器请求）"
                elif code == 404:
                    hint = "（路径不对：检查 public_base_url 有没有多带桶名）"
                problems.append(f"HTTP {code}{hint}{head_note} server={server or '?'} -> {u}")
            elif not ctype.startswith(("image/", "video/", "audio/", "application/octet-stream")):
                problems.append(f"能拉到但 Content-Type={ctype!r}（不是媒体类型，服务端可能拒收）{head_note} -> {u}")
            elif head_note:
                problems.append(f"GET 正常但{head_note} -> {u}")
        except Exception as exc:
            problems.append(f"{type(exc).__name__}: {exc}{head_note} -> {u}")
    return problems


def _collect_refs(image_tensors, url_texts, cap: int = 9) -> list[str]:
    """图片 tensor(转base64) 在前、公网 URL 在后，保序去空，最多 cap 张。"""
    refs: list[str] = []
    for t in image_tensors:
        r = _ref_b64_or_url(t)
        if r:
            refs.append(r)
    for u in url_texts:
        if isinstance(u, str) and u.strip():
            refs.append(u.strip())
    return refs[:cap]


ZERO_SIZES = ["1280x720", "1920x1080", "720x1280", "1080x1920", "1024x1024", "1280x960", "960x1280", "832x480", "480x832"]
# 文档允许的六种比例；size 只在「没显式给 ratio」时才由服务端推断，推断失败会回落 16:9
ZERO_RATIOS = ["自动(按size推算)", "9:16", "16:9", "1:1", "4:3", "3:4", "21:9"]
_RATIO_VALUES = {"21:9": 21 / 9, "16:9": 16 / 9, "4:3": 4 / 3, "1:1": 1.0, "3:4": 3 / 4, "9:16": 9 / 16}


def _zero_ratio(size: str, override: str = "") -> str:
    """从 `宽x高` 算出最接近的官方比例；`override` 非「自动」时直接用它。"""
    if override and not override.startswith("自动"):
        return override
    try:
        w, h = (size or "").lower().replace("×", "x").split("x")[:2]
        val = float(int(w)) / float(int(h))
    except Exception:
        return ""
    return min(_RATIO_VALUES.items(), key=lambda kv: abs(kv[1] - val))[0]


# ---------------------------------------------------------------------------
# 零视工坊 Sora2 / VEO 创建视频
# ---------------------------------------------------------------------------

ZERO_SORA_MODELS = ["veo_3_1-fast", "veo_3_1-fast-fl", "sora-2", "sora-2-pro"]


class RespectZeroSoraVeo:
    """零视工坊 Sora2 / VEO 创建视频。`POST /v1/videos` 提交 + 轮询。

    body：{prompt, model, size, input_reference(多图用|分隔), remix_id}。
    参考图/首尾帧：图片槽转 base64、URL 槽直用，合并后用 | 分隔填 input_reference。
    """

    DESCRIPTION = ("零视工坊 Sora2/VEO(base_url=zeroapi.ai-ren.cn)。model=veo_3_1-fast/-fl/sora-2，size=WxH，"
                   "首尾帧/参考图→input_reference(|分隔)，remix_id 可把 veo 续到15秒。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://zeroapi.ai-ren.cn"}),
                "model": (ZERO_SORA_MODELS, {"default": "veo_3_1-fast"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "size": (ZERO_SIZES, {"default": "1280x720", "tooltip": "输出尺寸 宽x高"}),
                "poll_interval": ("INT", {"default": 8, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "first_frame": ("IMAGE", {"tooltip": "首帧 → input_reference 第1个"}),
                "last_frame": ("IMAGE", {"tooltip": "尾帧 → input_reference 第2个"}),
                "ref_image_3": ("IMAGE",),
                "ref_image_4": ("IMAGE",),
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "参考图公网URL(接对象存储上传)"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "remix_id": ("STRING", {"default": "", "multiline": False, "placeholder": "可选：已有 veo 任务ID，续到15秒"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了优先使用"}),
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，自定义 宽x高，覆盖上面"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                # 新控件一律加在最后：已保存的工作流不会错位
                "aspect_ratio": (ZERO_RATIOS, {"default": "自动(按size推算)", "tooltip": "显式发 aspect_ratio+ratio；不发的话服务端可能回落 16:9"}),
                "seconds": ("INT", {"default": 0, "min": 0, "max": 60, "tooltip": "时长；0=不传该字段(用服务端默认)。sd2 只支持 5/10/15；veo/sora 一般不需要填"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, size, poll_interval, poll_timeout, auto_download,
                 first_frame=None, last_frame=None, ref_image_3=None, ref_image_4=None,
                 ref_url_1="", ref_url_2="", ref_url_3="", ref_url_4="",
                 remix_id="", custom_model="", custom_size="", save_dir="", filename="",
                 aspect_ratio="自动(按size推算)", seconds=0):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        size = (custom_size or "").strip() or size

        refs = _collect_refs([first_frame, last_frame, ref_image_3, ref_image_4],
                             [ref_url_1, ref_url_2, ref_url_3, ref_url_4])
        body: dict = {"model": model, "prompt": prompt, "size": size}
        # 显式带上比例（两个别名都发），否则服务端推断失败会变成 16:9
        ratio = _zero_ratio(size, aspect_ratio)
        if ratio:
            body["aspect_ratio"] = ratio
            body["ratio"] = ratio
        if int(seconds) > 0:
            body["seconds"] = str(int(seconds))   # 该网关的 seconds 是字符串类型（发数字会 400 invalid_json）
        if refs:
            # sd2 系走 images 数组；sora/veo 用 input_reference（多图 | 分隔）
            if model.lower().startswith("sd"):
                body["images"] = refs[:9]
            else:
                body["input_reference"] = "|".join(refs)
        if (remix_id or "").strip():
            body["remix_id"] = remix_id.strip()

        direct, task_id = _submit_async_video(cfg, body, timeout=300)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="zero_soraveo", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] 零视工坊 Sora/VEO 下载失败: {exc}")
        return (url, local, task_id or "")


# ---------------------------------------------------------------------------
# 零视工坊 图生视频 (vad3 / seedance_2 / omni_flash / grok-1.5)
# ---------------------------------------------------------------------------

ZERO_I2V_MODELS = ["seedance_2_fast_480p", "vad3", "omni_flash", "grok-1.5", "sd2-fast", "sd2-pro"]


class RespectZeroImg2Video:
    """零视工坊 图生视频。`POST /v1/videos` 提交 + 轮询。

    body：{model, prompt, image / images[], duration, size, stream}。
    单张 → image；多张 → images[]。参考图优先公网 URL，否则 IMAGE 转 base64。
    """

    DESCRIPTION = ("零视工坊 图生视频(base_url=zeroapi.ai-ren.cn)。model=seedance_2_fast_480p/vad3/omni_flash/grok-1.5；"
                   "duration(seedance 4-15，其它多为10/20)，size=WxH，单图 image/多图 images[](≤9)。"
                   "⚠️ sd 系请改用『零视工坊 SD2 视频（新接口）』节点——它的字段不一样(duration/aspect_ratio 必填、只收URL)。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://zeroapi.ai-ren.cn"}),
                "model": (ZERO_I2V_MODELS, {"default": "seedance_2_fast_480p"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": ("INT", {"default": 10, "min": 4, "max": 20, "tooltip": "秒数；seedance 4-15，sd2 只支持 5/10/15，其它常见 10/20"}),
                "size": (ZERO_SIZES, {"default": "1280x720"}),
                "poll_interval": ("INT", {"default": 8, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "first_frame": ("IMAGE", {"tooltip": "首帧/参考图（单张→image，多张→images[]）"}),
                "ref_image_2": ("IMAGE",),
                "ref_image_3": ("IMAGE",),
                "ref_image_4": ("IMAGE",),
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "参考图公网URL(接对象存储上传)"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "ref_url_5": ("STRING", {"default": "", "multiline": False}),
                "ref_url_6": ("STRING", {"default": "", "multiline": False}),
                "ref_url_7": ("STRING", {"default": "", "multiline": False}),
                "ref_url_8": ("STRING", {"default": "", "multiline": False}),
                "ref_url_9": ("STRING", {"default": "", "multiline": False}),
                "extra_image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "追加参考图URL，每行一个（连同上面共≤9）"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了优先使用"}),
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，自定义 宽x高"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                # 新控件加在最后：已保存的工作流不会错位
                "aspect_ratio": (ZERO_RATIOS, {"default": "自动(按size推算)", "tooltip": "显式发 aspect_ratio+ratio；不发的话服务端可能回落 16:9"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, duration, size, poll_interval, poll_timeout, auto_download,
                 first_frame=None, ref_image_2=None, ref_image_3=None, ref_image_4=None,
                 ref_url_1="", ref_url_2="", ref_url_3="", ref_url_4="", ref_url_5="",
                 ref_url_6="", ref_url_7="", ref_url_8="", ref_url_9="", extra_image_urls="",
                 custom_model="", custom_size="", save_dir="", filename="",
                 aspect_ratio="自动(按size推算)"):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        size = (custom_size or "").strip() or size

        imgs = _collect_refs(
            [first_frame, ref_image_2, ref_image_3, ref_image_4],
            [ref_url_1, ref_url_2, ref_url_3, ref_url_4, ref_url_5,
             ref_url_6, ref_url_7, ref_url_8, ref_url_9] + _zero_lines(extra_image_urls),
            cap=9,
        )
        # duration 给数字、seconds 给字符串（该网关 seconds 是 string 类型），两个都发提高兼容
        body: dict = {"model": model, "prompt": prompt, "size": size,
                      "duration": int(duration), "seconds": str(int(duration)), "stream": False}
        # 显式带上比例（两个别名都发），否则服务端推断失败会变成 16:9
        ratio = _zero_ratio(size, aspect_ratio)
        if ratio:
            body["aspect_ratio"] = ratio
            body["ratio"] = ratio
        if len(imgs) == 1:
            body["image"] = imgs[0]
        elif len(imgs) > 1:
            body["images"] = imgs

        direct, task_id = _submit_async_video(cfg, body, timeout=300)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="zero_i2v", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] 零视工坊 图生视频 下载失败: {exc}")
        return (url, local, task_id or "")


# ---------------------------------------------------------------------------
# 零视工坊 SD2 视频（新接口，替代原 sd 系）
# ---------------------------------------------------------------------------

ZERO_SD2_MODELS = ["sd2-fast"]
ZERO_SD2_DURATIONS = [5, 10, 15]
ZERO_SD2_RATIOS = ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9"]


class RespectZeroSD2:
    """零视工坊 SD2 视频（新接口）。`POST /v1/videos` + `GET /v1/videos/{task_id}` 轮询。

    严格照该文档：`{model, prompt, duration(int 5/10/15), aspect_ratio(必填), images[≤9], videos[≤3], audios[≤3]}`。
    分辨率固定 720P（不用也不能传）。**参考素材只收 HTTPS URL** —— 接「对象存储上传」拿 R2 链接最稳。
    """

    DESCRIPTION = ("零视工坊 SD2 视频(新接口，替代原 sd 系)。model=sd2-fast，duration 只能 5/10/15，"
                   "aspect_ratio 必填，720P 固定；images≤9 / videos≤3 / audios≤3 且只收 HTTPS URL。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://zeroapi.ai-ren.cn"}),
                "model": (ZERO_SD2_MODELS, {"default": "sd2-fast", "tooltip": "上新模型用 custom_model 填"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": ("INT", {"default": 10, "min": 5, "max": 15, "tooltip": "只支持 5 / 10 / 15，填别的会自动吸附"}),
                "aspect_ratio": (ZERO_SD2_RATIOS, {"default": "9:16", "tooltip": "该接口必填"}),
                "poll_interval": ("INT", {"default": 8, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "参考图 HTTPS URL（接对象存储上传）"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "extra_image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "追加参考图URL，每行一个（共≤9）"}),
                "video_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考视频 HTTPS URL，每行一个（≤3）"}),
                "audio_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考音频 HTTPS URL，每行一个（≤3）"}),
                "image_1": ("IMAGE", {"tooltip": "可接；但填了 ref_url_* 时以 URL 为准（文档说 images 只收公网URL）"}),
                "image_2": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "verify_urls": ("BOOLEAN", {"default": True, "tooltip": "提交前匿名试拉一遍素材URL，提前指出哪条公网拉不到（避免白花一次生成费）"}),
                "inputcount": ("INT", {"default": 2, "min": 1, "max": 9, "step": 1, "tooltip": "IMAGE 接口数量；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("在线视频 URL", "下载到本地的路径", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, duration, aspect_ratio, poll_interval, poll_timeout,
                 auto_download, ref_url_1="", ref_url_2="", ref_url_3="", ref_url_4="",
                 extra_image_urls="", video_urls="", audio_urls="",
                 custom_model="", save_dir="", filename="", verify_urls=True, inputcount=2, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        dur = int(duration)
        if dur not in ZERO_SD2_DURATIONS:
            near = min(ZERO_SD2_DURATIONS, key=lambda d: abs(d - dur))
            print(f"[Respect] 零视 SD2 只支持 duration={ZERO_SD2_DURATIONS}，已把 {dur} 纠正为 {near}")
            dur = near

        body: dict = {
            "model": model,
            "prompt": prompt,
            "duration": dur,              # 文档：int
            "aspect_ratio": aspect_ratio,  # 文档：必填
        }

        urls = _clean_urls([ref_url_1, ref_url_2, ref_url_3, ref_url_4] + _zero_lines(extra_image_urls))
        # 文档：images 只收公网 HTTPS URL → 不发 base64。
        # 但不因为「顺手也接了 IMAGE」就报错：填了 URL 就以 URL 为准，只提示一句。
        tensors = dynamic_image_inputs(kwargs)
        if tensors and urls:
            print(f"[Respect] 零视 SD2 按文档只发公网URL，已忽略接入的 {len(tensors)} 张 IMAGE（用的是 ref_url_*）")
        elif tensors and not urls:
            raise RespectAPIError(
                "接了 IMAGE 但没填任何 ref_url_* —— 该接口文档写明 images 只收公网 HTTPS URL，base64 会被判 "
                "Failed to fetch media URL。\n正确接法：加载图像 → 『Respect 对象存储上传』→ url → 本节点 ref_url_1。\n"
                "（只想文生视频就把 IMAGE 线拔掉）"
            )
        imgs = urls[:9]
        if imgs:
            body["images"] = imgs
        vids = _zero_lines(video_urls)[:3]
        if vids:
            body["videos"] = vids
        auds = _zero_lines(audio_urls)[:3]
        if auds:
            body["audios"] = auds

        # 提交前匿名试拉一遍，直接指出哪条素材公网拉不到
        if verify_urls and (imgs or vids or auds):
            probs = _zero_preflight(imgs + vids + auds)
            if probs:
                raise RespectAPIError(
                    "以下参考素材**公网访问不到**，零视会报 Failed to fetch media URL：\n  "
                    + "\n  ".join(probs)
                    + "\n\n修法：用『Respect 对象存储上传』上传，并确保 public_base_url 填的是能公开访问的域名"
                      "（R2 要在桶设置里开 r2.dev 子域或绑自定义域名）。\n"
                      "确认过能公开访问就把 verify_urls 关掉跳过本检查。"
                )

        print(f"[Respect] 零视 SD2 提交: model={model} duration={dur} aspect_ratio={aspect_ratio} "
              f"images={len(imgs)} videos={len(vids)} audios={len(auds)}")
        print(f"[Respect] body={json.dumps(body, ensure_ascii=False)}")
        try:
            direct, task_id = _submit_async_video(cfg, body, timeout=300)
        except RespectAPIError as exc:
            msg = str(exc)
            # 网关侧临时故障：它和上游之间超时/被取消，跟入参无关。不自动重试——提交要扣费。
            if "context canceled" in msg or "read_response_body_failed" in msg or "fail_to_fetch_task" in msg:
                raise RespectAPIError(
                    f"{msg}\n\n"
                    "【判断】零视网关侧的临时故障（它读上游响应时连接被取消/超时），**不是参数问题** —— "
                    "参考素材这次已经能正常抓取了。\n"
                    "【建议】① 先去零视后台看这条任务是否其实已创建（避免重复扣费）；"
                    "② 等 1–2 分钟重跑；③ 反复复现就把下面这段发他们客服。\n"
                    f"【本次提交】{json.dumps(body, ensure_ascii=False)[:500]}"
                ) from exc
            raise
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        local = ""
        if auto_download and url:
            try:
                local = download_to_output(url, cfg, prefix="zero_sd2", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] 零视 SD2 下载失败: {exc}")
        return (url, local, task_id or "")


# ---------------------------------------------------------------------------
# 零视工坊 图片（gpt-image-2）—— 文档没列在索引里，参数见「模型」页
# ---------------------------------------------------------------------------

ZERO_IMAGE_MODELS = ["gpt-image-2", "gpt-image-2-2K", "gpt-image-2-4K", "nano_banana_pro"]
ZERO_IMAGE_SIZES = ["1024x1024", "1536x1024", "1024x1536", "1792x1024", "1024x1792"]
ZERO_IMAGE_QUALITY = ["standard", "hd", "high", "medium", "low", "auto"]
ZERO_IMAGE_STYLE = ["vivid", "natural"]
ZERO_IMAGE_FORMATS = ["url", "b64_json"]


class RespectZeroImage:
    """零视工坊 图片（`POST /v1/images/generations`）。返回 IMAGE。

    参数按该网关「模型」页：`prompt`(必填) / `size` / `quality` / `style` / `n`(1-10) / `response_format`。
    该网关的图片是**异步**的（只回 `task_id` + `status=queued`）→ 节点自动轮询，查询端点自动探测。

    接了参考图 → 改走 `POST /v1/images/edits`（multipart，重复 `image` 字段）。
    参考图数量可变：填 `inputcount` 后点节点上的「更新输入口」。
    """

    DESCRIPTION = ("零视工坊 图片(base_url=zeroapi.ai-ren.cn)。prompt/size/quality/style/n/response_format；"
                   "异步自动轮询。接参考图则走 /v1/images/edits，数量用 inputcount + 『更新输入口』。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://zeroapi.ai-ren.cn"}),
                "model": (ZERO_IMAGE_MODELS, {"default": "gpt-image-2", "tooltip": "上新模型用 custom_model 填"}),
                "prompt": ("STRING", {"default": "", "multiline": True, "tooltip": "想要生成图像的文字描述（必填）"}),
                "size": (ZERO_IMAGE_SIZES, {"default": "1024x1024", "tooltip": "输出图像尺寸"}),
                "n": ("INT", {"default": 1, "min": 1, "max": 10, "tooltip": "生成的图像数量 1-10"}),
                "poll_interval": ("INT", {"default": 5, "min": 2, "max": 60}),
                "poll_timeout": ("INT", {"default": 900, "min": 60, "max": 7200}),
            },
            "optional": {
                "quality": (ZERO_IMAGE_QUALITY, {"default": "standard", "tooltip": "生成质量预设"}),
                "style": (ZERO_IMAGE_STYLE, {"default": "vivid", "tooltip": "画风"}),
                "response_format": (ZERO_IMAGE_FORMATS, {"default": "url", "tooltip": "图像结果的返回方式"}),
                "image_1": ("IMAGE", {"tooltip": "参考图（接了就走 /v1/images/edits）"}),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖 size，如 2048x2048"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 64, "step": 1, "tooltip": "参考图接口数量；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_urls", "task_id")
    OUTPUT_TOOLTIPS = ("生成的图片", "图片URL（每行一个）", "任务 ID")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, size, n, poll_interval, poll_timeout,
                 quality="standard", style="vivid", response_format="url",
                 custom_model="", custom_size="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        size = (custom_size or "").strip() or size
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")

        refs = expand_image_frames(dynamic_image_inputs(kwargs))
        if refs:
            # 图生图：文档未列，按 OpenAI 兼容惯例走 edits（每张参考图一个重复的 image 字段）
            files: list = [
                ("model", (None, model)),
                ("prompt", (None, prompt)),
                ("size", (None, size)),
                ("n", (None, str(int(n)))),
                ("quality", (None, quality)),
                ("style", (None, style)),
                ("response_format", (None, response_format)),
            ]
            for i, frame in enumerate(refs):
                b64 = tensor_to_b64(frame, fmt="PNG", max_side=2048)
                if not b64:
                    continue
                raw = b64[0].split(",", 1)[1]
                files.append(("image", (f"ref_{i + 1}.png", base64.b64decode(raw), "image/png")))
            resp = api_request(cfg, "POST", "/v1/images/edits", files=files,
                               retries=2, timeout=max(cfg.timeout, 300))
        else:
            body = {
                "model": model, "prompt": prompt, "size": size, "n": int(n),
                "quality": quality, "style": style, "response_format": response_format,
            }
            resp = api_request(cfg, "POST", "/v1/images/generations", json_body=body,
                               retries=2, timeout=max(cfg.timeout, 300))

        data = resp.json() if resp.content else {}
        items = extract_image_payloads(data)
        task_id = _img_task_id(data)
        if not items:
            status = _img_status(data)
            if not task_id:
                raise RespectAPIError(f"未返回图片也没有 task_id: {json.dumps(data, ensure_ascii=False)[:400]}")
            print(f"[Respect] 零视工坊图片异步任务 {task_id}（status={status or 'n/a'}），开始轮询…")
            items = _poll_image_task(cfg, task_id, int(poll_interval), int(poll_timeout))

        tensors = [t for t in (resolve_image_to_tensor(i, cfg) for i in items) if t is not None]
        if not tensors:
            raise RespectAPIError(f"取到结果但无法解析为图片: {str(items)[:300]}")
        urls = "\n".join(i for i in items if isinstance(i, str) and i.startswith("http"))
        return (tensors_concat(tensors), urls, task_id or "")


NODE_CLASS_MAPPINGS = {
    "RespectZeroSoraVeo": RespectZeroSoraVeo,
    "RespectZeroImg2Video": RespectZeroImg2Video,
    "RespectZeroSD2": RespectZeroSD2,
    "RespectZeroImage": RespectZeroImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectZeroSoraVeo": "Respect 零视工坊 Sora2/VEO 视频",
    "RespectZeroImg2Video": "Respect 零视工坊 图生视频",
    "RespectZeroSD2": "Respect 零视工坊 SD2 视频（新接口）",
    "RespectZeroImage": "Respect 零视工坊 图片（gpt-image-2）",
}
