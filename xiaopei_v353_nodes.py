"""Respect ComfyUI 扩展 - 小裴视频插件 **3.3.53** 新增/改形状的分支。

文档：`视频插件接口文档-3.3.53-完整详细版.md`（2026-08-15）

3.3.25 → 3.3.53 之间分支被重排过，**大部分模型名和请求体形状都变了**。原来的
`xiaopei_video_nodes.py` 只有 ad渠道(#8)、omni(#15)、veo(#16) 三个分支还对得上，
其余要么模型名没了、要么协议整个换掉。本文件放**新增和换了形状**的分支：

| 节点 | 文档分支 | 这家独有的坑 |
|---|---|---|
| GROK 1.0 | #1 | `duration` 和 `video_length` **同时发且相等**，还要再套一个 `video_config` |
| GROK 1.5 | #2 | `reference_images` 是**对象数组** `[{"url":"data:…"}]`；首帧也走它，不是 `image` |
| Horse 官方快乐马 | #3 | 参数塞在 `parameters{}` 里；**首帧模式禁止传 `parameters.ratio`** |
| Minimax-h3 | #4 | 走 `/v1/video/generations`；`fps` 固定 24；图片要带 `role` |
| 火山官方 sd稳定版 | #5 | 素材走 `content` 块数组；**首帧/首尾帧禁止传 `ratio`**，传了报 TaskTypeConstraint |
| sd-2.5-不卡脸 | #6 | 4–29 秒；`images/videos/audios` 是**裸 URL 数组**；不发 `resolution` |
| sd2.0全系列不卡脸 | #7 | 靠 `metadata.modeType` 区分模式；`enableSound` 是**字符串 `"on"`** |
| sd-720满血-900 | #11 | 只支持多参考图；`duration` 是**字符串 `"15"`** |

**素材形式不能混**（文档「字段速查」那节）：GROK 和 Horse 官方吃 **Data URL**，
其余分支吃**公网 URL**。本文件按分支自动选，接 IMAGE 就行。

图片进插件前等比压到**最长边 1024px**（文档「素材来源」），这里照做。
"""

from __future__ import annotations

from .utils import (RespectAPIError, ensure_config, tensor_to_b64)
from .video_nodes import _async_poll
from .xiaopei_video_nodes import (CATEGORY, _RET, _RET_NAMES, _RET_TIPS,
                                  _xp_finish, _xp_local_or_urls,
                                  _xp_media_urls, _xp_poll_generations,
                                  _xp_submit)

# --- 3.3.53 模型总表 ---------------------------------------------------------

GROK10_MODELS = ["grok-imagine-1.0-video", "grok-1.0-官转接口", "grok-1.0-备用接口"]
GROK10_DURATIONS = [6, 10]
GROK15_MODELS = ["grok-imagine-video-1.5-preview", "grok-1.5-官转接口",
                 "grok-1.5-备用接口", "grok-1.5-多参接口"]
GROK15_SECONDS = ["6", "10", "15"]
GROK_ASPECTS = ["16:9", "9:16", "3:2"]
GROK_SIZES = {"16:9": "1280x720", "9:16": "720x1280", "3:2": "1080x720"}

HORSE_MODELS = ["happyhorse-1.1-t2v-720p", "happyhorse-1.1-t2v-1080p",
                "happyhorse-1.1-i2v-720p", "happyhorse-1.1-i2v-1080p",
                "happyhorse-1.1-r2v-720p", "happyhorse-1.1-r2v-1080p"]
HORSE_ASPECTS = ["16:9", "9:16", "1:1", "4:3", "3:4", "4:5", "5:4", "9:21", "21:9"]

H3_MODELS = ["开源h3-480p", "开源h3-720p", "开源h3-1080p", "开源h3-2k"]
H3_ASPECTS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"]

VOLC_MODELS = ["火山官方2.5-480p", "火山官方2.5-720p",
               "火山官方2.0-480p-mini", "火山官方2.0-720p-mini"]
# 文档 #5：2.5 系 4-30 秒、图30/视频10/音频10；2.0 mini 4-15 秒、图9/视频3/音频3
VOLC_LIMITS = {"火山官方2.5-480p": (30, 30, 10, 10), "火山官方2.5-720p": (30, 30, 10, 10),
               "火山官方2.0-480p-mini": (15, 9, 3, 3), "火山官方2.0-720p-mini": (15, 9, 3, 3)}

SD25_MODELS = ["sd-2.5-480p不卡脸(按秒)", "sd-2.5-720p不卡脸(按秒)",
               "sd-2.5-480p不卡脸(按秒)-备用", "sd-2.5-720p不卡脸(按秒)-备用"]
SD25_ASPECTS = ["16:9", "9:16", "1:1"]

SD2FULL_MODELS = ["sd2.0-720mini-不卡脸（按秒）", "sd2.0-720fast-不卡脸（按秒）",
                  "sd2.0-720满血-不卡脸（按秒）", "sd2.0-720满血（按次）不卡脸",
                  "sd2.0-720fast（按次）不卡脸", "sd2.0-1080mini-不卡脸（按秒）",
                  "sd2.0-1080fast-不卡脸（按秒）", "sd2.0-1080满血-不卡脸（按秒）"]
SD2FULL_ASPECTS = ["16:9", "9:16", "1:1"]
# 文档 #7：modeType 由模式决定，写错上游会按别的模式跑
SD2FULL_MODETYPE = {
    "文生视频": "text2video",
    "首帧生成视频": "image2video",
    "首帧+参考图生成视频": "image2video",
    "首尾帧生成视频": "frames2video",
    "多参考图生成视频": "",          # 纯参考可省略
}

SD900_MODEL = "sd-720满血-900（不售后）"

MODES = ["文生视频", "首帧生成视频", "首尾帧生成视频", "多参考图生成视频", "首帧+参考图生成视频"]


def _data_urls(tensors: list, cap: int) -> list[str]:
    """IMAGE → Data URL 列表（GROK / Horse 官方这两支只吃 data:）。

    文档「素材来源」：图片进插件前等比压缩到**最长边 1024px**，这里照做，
    否则 base64 体积翻几倍，容易吃 413。
    """
    out: list[str] = []
    for t in tensors:
        if t is None or (hasattr(t, "numel") and t.numel() == 0):
            continue
        for b in tensor_to_b64(t, fmt="JPEG", quality=90, max_side=1024):
            out.append(b)
            if len(out) >= cap:
                return out
    return out


def _imgs_from(kwargs: dict, n: int) -> list:
    return [kwargs.get(f"image_{i + 1}") for i in range(n)]


def _base_required(models: list, default: str, aspects: list, *, duration=None,
                   with_mode=True, poll=5) -> dict:
    req: dict = {
        "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 默认 https://api.aicopy.top"}),
        "model": (models, {"default": default}),
        "prompt": ("STRING", {"default": "", "multiline": True}),
    }
    if with_mode:
        req["generation_mode"] = (MODES, {"default": "首帧生成视频"})
    if duration:
        d, lo, hi = duration
        req["duration"] = ("INT", {"default": d, "min": lo, "max": hi})
    req["aspect_ratio"] = (aspects, {"default": aspects[0]})
    req["poll_interval"] = ("INT", {"default": poll, "min": 2, "max": 60})
    req["poll_timeout"] = ("INT", {"default": 1800, "min": 60, "max": 7200})
    req["auto_download"] = ("BOOLEAN", {"default": True})
    return req


def _tail_optional(extra: dict = None, *, count_max: int = 9) -> dict:
    opt = dict(extra or {})
    opt.pop("inputcount", None)          # 统一在末尾加，别让调用方插到中间
    opt["custom_model"] = ("STRING", {"default": "", "multiline": False, "placeholder": "可选，填了覆盖上方模型"})
    opt["save_dir"] = ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"})
    opt["filename"] = ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"})
    # 放最后：widgets_values 是按顺序存的，插在中间会让已保存的工作流参数错位
    opt["inputcount"] = ("INT", {"default": 4, "min": 1, "max": count_max, "step": 1,
                                 "tooltip": "参考图接口数量；改完点节点上的『更新输入口』按钮增减"})
    return opt


# ---------------------------------------------------------------------------
# #1  GROK 1.0-video（可多参）
# ---------------------------------------------------------------------------


class RespectXPGrok10:
    """小裴 GROK 1.0-video（文档 #1）。`POST /v1/videos`，时长只有 6 / 10 秒。

    这支最容易写错的是**时长要发三遍**：顶层 `duration`、顶层 `video_length`、
    还有 `video_config` 里再来一次，三处必须一致。参考图是 **Data URL**：
    首帧走 `image`（单个字符串），多参考走 `reference_images`（字符串数组，≤7）——
    两者插件不会同时发。
    """

    DESCRIPTION = ("小裴 GROK1.0（文档#1）。duration+video_length+video_config 三处时长要一致；"
                   "首帧=image(data URL)、多参考=reference_images(data URL字符串数组,≤7)；6或10秒，固定720p。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": _base_required(GROK10_MODELS, GROK10_MODELS[0], GROK_ASPECTS,
                                       duration=(6, 6, 10)),
            "optional": _tail_optional({f"image_{i + 1}": ("IMAGE",) for i in range(4)}),
        }

    RETURN_TYPES, RETURN_NAMES, OUTPUT_TOOLTIPS = _RET, _RET_NAMES, _RET_TIPS
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, generation_mode, duration, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 custom_model="", save_dir="", filename="", **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        dur = int(duration)
        if dur not in GROK10_DURATIONS:
            near = min(GROK10_DURATIONS, key=lambda d: abs(d - dur))
            print(f"[Respect] GROK1.0 只支持 {GROK10_DURATIONS} 秒，已把 {dur} 纠正为 {near}")
            dur = near

        body: dict = {
            "model": model, "prompt": prompt,
            "duration": dur, "video_length": dur,       # 两个都要发，且相等
            "aspect_ratio": aspect_ratio, "resolution": "720p",
            "video_config": {"video_length": dur, "aspect_ratio": aspect_ratio,
                             "resolution": "720p", "preset": "normal"},
        }
        imgs = _data_urls(_imgs_from(kwargs, 4), 7)
        if generation_mode == "多参考图生成视频":
            if not imgs:
                raise RespectAPIError("多参考图至少接 1 张 IMAGE")
            body["reference_images"] = imgs             # 字符串数组，不是对象数组
        elif generation_mode != "文生视频":
            if not imgs:
                raise RespectAPIError(f"{generation_mode} 需要接 1 张 IMAGE 作首帧")
            body["image"] = imgs[0]                     # 单个字符串
            if len(imgs) > 1:
                print("[Respect] GROK1.0 首帧模式只发 1 张，其余已忽略（要多图请选『多参考图生成视频』）")

        direct, task_id, _ = _xp_submit(cfg, "/v1/videos", body)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        return _xp_finish(cfg, url, task_id, "xp_grok10", auto_download, save_dir, filename)


# ---------------------------------------------------------------------------
# #2  GROK1.5-Preview（可多参）
# ---------------------------------------------------------------------------


class RespectXPGrok15:
    """小裴 GROK1.5-Preview（文档 #2）。`POST /v1/videos`，时长 6 / 10 / 15 秒。

    和 1.0 完全不是一套：`seconds` 是**字符串**、比例换算成 `size`，
    参考图是 **对象数组** `[{"url":"data:image/...;base64,..."}]`。
    **首帧模式也用 `reference_images`**（只放 1 项），不是 `image_url`。
    """

    DESCRIPTION = ("小裴 GROK1.5-Preview（文档#2）。seconds是字符串(6/10/15)、size由比例换算；"
                   "reference_images 是对象数组[{url:data-url}]，首帧也用它（1项），≤7张。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        req = _base_required(GROK15_MODELS, GROK15_MODELS[0], GROK_ASPECTS, with_mode=False)
        req["seconds"] = (GROK15_SECONDS, {"default": "10", "tooltip": "只有 6/10/15；发出去是字符串"})
        return {
            "required": req,
            "optional": _tail_optional({
                **{f"image_{i + 1}": ("IMAGE",) for i in range(4)},
                "custom_size": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，直接指定 size 如 1280x720"}),
            }),
        }

    RETURN_TYPES, RETURN_NAMES, OUTPUT_TOOLTIPS = _RET, _RET_NAMES, _RET_TIPS
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, aspect_ratio, seconds,
                 poll_interval, poll_timeout, auto_download,
                 custom_model="", custom_size="", save_dir="", filename="", **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        size = (custom_size or "").strip() or GROK_SIZES.get(aspect_ratio, "720x1280")

        body: dict = {"model": model, "prompt": prompt,
                      "seconds": str(seconds), "size": size}
        imgs = _data_urls(_imgs_from(kwargs, 4), 7)
        if imgs:
            # 对象数组：给字符串数组会 422（文档「HTTP错误含义」那条）
            body["reference_images"] = [{"url": u} for u in imgs]

        direct, task_id, _ = _xp_submit(cfg, "/v1/videos", body)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        return _xp_finish(cfg, url, task_id, "xp_grok15", auto_download, save_dir, filename)


# ---------------------------------------------------------------------------
# #3  Horse 官方快乐马不卡脸（按秒）
# ---------------------------------------------------------------------------


class RespectXPHorseOfficial:
    """小裴 Horse官方快乐马不卡脸（文档 #3）。`POST /v1/videos`，4–15 秒。

    **模式由变体名锁定**：`-t2v-` 文生、`-i2v-` 首帧、`-r2v-` 多参考图，选错了发对字段也没用。
    参数塞在 `parameters{duration, resolution, watermark, ratio}` 里；
    **首帧模式不传 `parameters.ratio`**（画幅跟随首帧）。素材是 **Data URL**。
    """

    DESCRIPTION = ("小裴 Horse官方快乐马（文档#3）。模式由变体锁定(t2v/i2v/r2v)；参数在 parameters{} 里，"
                   "首帧模式不传 parameters.ratio；首帧=image_url、多参考=reference_images，都是 data URL(≤9)。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        req = _base_required(HORSE_MODELS, "happyhorse-1.1-i2v-720p", HORSE_ASPECTS,
                             duration=(8, 4, 15), with_mode=False)
        return {
            "required": req,
            "optional": _tail_optional({
                **{f"image_{i + 1}": ("IMAGE",) for i in range(4)},
                "watermark": ("BOOLEAN", {"default": False, "tooltip": "文档默认 false"}),
            }),
        }

    RETURN_TYPES, RETURN_NAMES, OUTPUT_TOOLTIPS = _RET, _RET_NAMES, _RET_TIPS
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, duration, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 watermark=False, custom_model="", save_dir="", filename="", **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        res = "1080P" if "1080p" in model else "720P"        # 文档里 parameters.resolution 是大写 P
        params: dict = {"duration": int(duration), "resolution": res, "watermark": bool(watermark)}

        body: dict = {"model": model, "prompt": prompt, "parameters": params}
        imgs = _data_urls(_imgs_from(kwargs, 4), 9)
        if "-i2v-" in model:
            if not imgs:
                raise RespectAPIError(f"{model} 是首帧变体，需要接 1 张 IMAGE")
            body["image_url"] = imgs[0]
            # 首帧模式禁传 ratio：画幅由首帧决定
        elif "-r2v-" in model:
            if not imgs:
                raise RespectAPIError(f"{model} 是多参考图变体，至少接 1 张 IMAGE")
            body["reference_images"] = imgs               # 字符串数组
            params["ratio"] = aspect_ratio
        else:                                             # -t2v- 文生
            if imgs:
                print(f"[Respect] {model} 是文生变体，已忽略参考图（要用图请换 -i2v- / -r2v- 变体）")
            params["ratio"] = aspect_ratio

        direct, task_id, _ = _xp_submit(cfg, "/v1/videos", body)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        return _xp_finish(cfg, url, task_id, "xp_horse", auto_download, save_dir, filename)


# ---------------------------------------------------------------------------
# #4  Minimax-h3
# ---------------------------------------------------------------------------


class RespectXPH3:
    """小裴 Minimax-h3（文档 #4）。**走 `/v1/video/generations`**，不是 `/v1/videos`。

    5–15 秒，`fps` 固定 24，分辨率由变体锁定（480p/720p/1080p/2k）。
    参考图是 `[{"url":…, "role":…}]`：首帧 `first_frame`、尾帧 `last_frame`、
    多参考全是 `reference_image`。视频/音频各 ≤3，形状是 `[{"url":…}]`。
    查询也用 `/v1/video/generations/{id}`，没链接才回退 `/v1/videos/{id}/content`。
    """

    DESCRIPTION = ("小裴 Minimax-h3（文档#4）。POST /v1/video/generations（**没有 videos 的复数**）；"
                   "fps固定24；reference_images=[{url,role}] first_frame/last_frame/reference_image；"
                   "reference_videos/reference_audios=[{url}]，各≤3。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": _base_required(H3_MODELS, "开源h3-720p", H3_ASPECTS, duration=(8, 5, 15)),
            "optional": _tail_optional({
                **{f"image_{i + 1}": ("IMAGE",) for i in range(4)},
                "image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考图公网URL，每行一个（填了优先，≤9）"}),
                "video_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考视频URL，每行一个（≤3，仅多参考模式）"}),
                "video_paths": ("STRING", {"default": "", "multiline": True, "placeholder": "本地视频路径，每行一个（自动上传换URL）"}),
                "audio_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考音频URL，每行一个（≤3，仅多参考模式）"}),
                "audio_paths": ("STRING", {"default": "", "multiline": True, "placeholder": "本地音频路径，每行一个（自动上传换URL）"}),
            }),
        }

    RETURN_TYPES, RETURN_NAMES, OUTPUT_TOOLTIPS = _RET, _RET_NAMES, _RET_TIPS
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, generation_mode, duration, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 image_urls="", video_urls="", video_paths="", audio_urls="", audio_paths="",
                 custom_model="", save_dir="", filename="", **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        imgs = _xp_media_urls(cfg, _imgs_from(kwargs, 4), image_urls, 9)

        body: dict = {"model": model, "prompt": prompt, "aspect_ratio": aspect_ratio,
                      "duration": int(duration), "fps": 24}
        if generation_mode == "首帧生成视频":
            if not imgs:
                raise RespectAPIError("首帧生成视频需要 1 张图")
            body["reference_images"] = [{"url": imgs[0], "role": "first_frame"}]
        elif generation_mode == "首尾帧生成视频":
            if len(imgs) < 2:
                raise RespectAPIError("首尾帧需要 2 张图（第1张首帧、第2张尾帧）")
            body["reference_images"] = [{"url": imgs[0], "role": "first_frame"},
                                        {"url": imgs[1], "role": "last_frame"}]
        elif generation_mode in ("多参考图生成视频", "首帧+参考图生成视频"):
            if not imgs:
                raise RespectAPIError("该模式至少需要 1 张参考图")
            # 文档：多参考里所有图都是 reference_image，别混 first_frame
            body["reference_images"] = [{"url": u, "role": "reference_image"} for u in imgs]
            vids = _xp_local_or_urls(cfg, video_urls, video_paths)
            auds = _xp_local_or_urls(cfg, audio_urls, audio_paths)
            if vids:
                body["reference_videos"] = [{"url": u} for u in vids]
            if auds:
                body["reference_audios"] = [{"url": u} for u in auds]

        direct, task_id, _ = _xp_submit(cfg, "/v1/video/generations", body)
        url = direct or _xp_poll_generations(cfg, task_id, int(poll_interval), int(poll_timeout))
        return _xp_finish(cfg, url, task_id, "xp_h3", auto_download, save_dir, filename)


# ---------------------------------------------------------------------------
# #5  【火山官方】sd稳定版
# ---------------------------------------------------------------------------


class RespectXPVolcano:
    """小裴【火山官方】sd稳定版（文档 #5）。素材走 **`content` 块数组**。

    **这支没有文生模式**，必须给图。两条硬规矩：
    - 首帧 / 首尾帧 **禁止传 `ratio`** —— 传了火山直接回 `InvalidParameter.TaskTypeConstraint`，
      画幅本来就跟随首帧
    - 多参考里所有图都是 `reference_image`，不能混 `first_frame` / `last_frame`

    2.5 系 4–30 秒、图30/视频10/音频10；2.0 mini 4–15 秒、图9/视频3/音频3。
    """

    DESCRIPTION = ("小裴 火山官方sd稳定版（文档#5）。content块数组+role；**没有文生模式**；"
                   "首帧/首尾帧禁传 ratio(否则 TaskTypeConstraint)；2.5系4-30秒图30，2.0mini 4-15秒图9。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        req = _base_required(VOLC_MODELS, "火山官方2.5-720p", ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"],
                             duration=(8, 4, 30))
        req["generation_mode"] = (["首帧生成视频", "首尾帧生成视频", "多参考图生成视频"],
                                  {"default": "首帧生成视频", "tooltip": "本分支没有文生视频模式"})
        return {
            "required": req,
            "optional": _tail_optional({
                **{f"image_{i + 1}": ("IMAGE",) for i in range(4)},
                "image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考图公网URL，每行一个（填了优先）"}),
                "video_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考视频URL，每行一个"}),
                "video_paths": ("STRING", {"default": "", "multiline": True, "placeholder": "本地视频路径，每行一个（自动上传换URL）"}),
                "audio_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考音频URL，每行一个"}),
                "audio_paths": ("STRING", {"default": "", "multiline": True, "placeholder": "本地音频路径，每行一个（自动上传换URL）"}),
                "generate_audio": ("BOOLEAN", {"default": True, "tooltip": "文档固定 true"}),
                "watermark": ("BOOLEAN", {"default": False, "tooltip": "文档固定 false"}),
            }),
        }

    RETURN_TYPES, RETURN_NAMES, OUTPUT_TOOLTIPS = _RET, _RET_NAMES, _RET_TIPS
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, generation_mode, duration, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 image_urls="", video_urls="", video_paths="", audio_urls="", audio_paths="",
                 generate_audio=True, watermark=False,
                 custom_model="", save_dir="", filename="", **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        max_sec, cap_img, cap_vid, cap_aud = VOLC_LIMITS.get(model, (15, 9, 3, 3))
        sec = int(duration)
        if not 4 <= sec <= max_sec:
            near = min(max_sec, max(4, sec))
            print(f"[Respect] {model} 只支持 4–{max_sec} 秒，已把 {sec} 纠正为 {near}")
            sec = near

        imgs = _xp_media_urls(cfg, _imgs_from(kwargs, 4), image_urls, cap_img)
        if not imgs:
            raise RespectAPIError(
                "火山官方分支**没有文生模式**（文档 #5），至少要 1 张参考图。\n"
                "想纯文生请换『SD2.5 不卡脸』或『SD2.0 全系列』节点。")

        content: list[dict] = [{"type": "text", "text": prompt or ""}]
        if generation_mode == "首帧生成视频":
            content.append({"type": "image_url", "image_url": {"url": imgs[0]}, "role": "first_frame"})
        elif generation_mode == "首尾帧生成视频":
            if len(imgs) < 2:
                raise RespectAPIError("首尾帧需要 2 张图（第1张首帧、第2张尾帧）")
            content.append({"type": "image_url", "image_url": {"url": imgs[0]}, "role": "first_frame"})
            content.append({"type": "image_url", "image_url": {"url": imgs[1]}, "role": "last_frame"})
        else:                                              # 多参考图
            for u in imgs:
                content.append({"type": "image_url", "image_url": {"url": u}, "role": "reference_image"})
            for u in _xp_local_or_urls(cfg, video_urls, video_paths, cap_vid):
                content.append({"type": "video_url", "video_url": {"url": u}, "role": "reference_video"})
            for u in _xp_local_or_urls(cfg, audio_urls, audio_paths, cap_aud):
                content.append({"type": "audio_url", "audio_url": {"url": u}, "role": "reference_audio"})

        res = "480p" if "480" in model else "720p"
        body: dict = {"model": model, "content": content,
                      "generate_audio": bool(generate_audio), "duration": sec,
                      "watermark": bool(watermark), "resolution": res}
        if generation_mode == "多参考图生成视频":
            # 只有多参考才发 ratio；首帧/首尾帧发了会 InvalidParameter.TaskTypeConstraint
            body["ratio"] = aspect_ratio

        direct, task_id, _ = _xp_submit(cfg, "/v1/videos", body)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        return _xp_finish(cfg, url, task_id, "xp_volc", auto_download, save_dir, filename)


# ---------------------------------------------------------------------------
# #6  sd-2.5-不卡脸（按秒）
# ---------------------------------------------------------------------------


class RespectXPSd25:
    """小裴 sd-2.5-不卡脸（按秒）（文档 #6）。`POST /v1/videos`，**4–29 秒**。

    素材是最朴素的裸 URL 数组：`images` / `videos` / `audios`（图≤30、视频音频各≤10）。
    模式全靠 `images` 的顺序表达 —— 首帧=1 项、首尾帧=2 项、多参考=任意项，
    **没有 `first_frame_url` 这种字段**。分辨率由模型锁定，插件不发 `resolution`。
    """

    DESCRIPTION = ("小裴 sd-2.5不卡脸(按秒)（文档#6）。4-29秒；images/videos/audios 是裸URL数组"
                   "(图≤30/视频≤10/音频≤10)；模式靠 images 顺序表达，不发 resolution。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": _base_required(SD25_MODELS, "sd-2.5-720p不卡脸(按秒)", SD25_ASPECTS,
                                       duration=(15, 4, 29)),
            "optional": _tail_optional({
                **{f"image_{i + 1}": ("IMAGE",) for i in range(4)},
                "image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考图公网URL，每行一个（填了优先，≤30）"}),
                "video_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考视频URL，每行一个（≤10）"}),
                "video_paths": ("STRING", {"default": "", "multiline": True, "placeholder": "本地视频路径，每行一个（自动上传换URL）"}),
                "audio_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考音频URL，每行一个（≤10）"}),
                "audio_paths": ("STRING", {"default": "", "multiline": True, "placeholder": "本地音频路径，每行一个（自动上传换URL）"}),
            }, count_max=30),
        }

    RETURN_TYPES, RETURN_NAMES, OUTPUT_TOOLTIPS = _RET, _RET_NAMES, _RET_TIPS
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, generation_mode, duration, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 image_urls="", video_urls="", video_paths="", audio_urls="", audio_paths="",
                 custom_model="", save_dir="", filename="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        imgs = _xp_media_urls(cfg, _imgs_from(kwargs, 30), image_urls, 30)

        need = {"首帧生成视频": 1, "首尾帧生成视频": 2, "多参考图生成视频": 1,
                "首帧+参考图生成视频": 1}.get(generation_mode, 0)
        if len(imgs) < need:
            raise RespectAPIError(f"{generation_mode} 至少需要 {need} 张图，现在只有 {len(imgs)} 张")

        body: dict = {"model": model, "prompt": prompt,
                      "duration": int(duration), "aspect_ratio": aspect_ratio}
        if generation_mode != "文生视频" and imgs:
            body["images"] = imgs[:2] if generation_mode == "首尾帧生成视频" else imgs
        vids = _xp_local_or_urls(cfg, video_urls, video_paths, 10)
        auds = _xp_local_or_urls(cfg, audio_urls, audio_paths, 10)
        if vids:
            body["videos"] = vids
        if auds:
            body["audios"] = auds

        direct, task_id, _ = _xp_submit(cfg, "/v1/videos", body)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        return _xp_finish(cfg, url, task_id, "xp_sd25", auto_download, save_dir, filename)


# ---------------------------------------------------------------------------
# #7  sd2.0全系列不卡脸（按秒+按次）
# ---------------------------------------------------------------------------


class RespectXPSd2Full:
    """小裴 sd2.0全系列不卡脸（文档 #7）。`POST /v1/videos`，4–15 秒。

    比例和模式都塞在 **`metadata`** 里，这是这支唯一的特点：

        "metadata": {"ratio": "9:16", "enableSound": "on", "modeType": "frames2video"}

    `modeType`：文生 `text2video`、首帧/首帧+参考 `image2video`、首尾帧 `frames2video`、
    纯视频参考可省略。**`enableSound` 是字符串 `"on"`**，不是布尔。
    素材同样是裸 URL 数组 `images`/`videos`/`audios`（图9、视频3、音频3）。
    """

    DESCRIPTION = ("小裴 sd2.0全系列不卡脸（文档#7）。比例/模式在 metadata 里："
                   "{ratio, enableSound:'on'(字符串), modeType: text2video/image2video/frames2video}；"
                   "images/videos/audios 裸URL数组(9/3/3)。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": _base_required(SD2FULL_MODELS, "sd2.0-720满血-不卡脸（按秒）",
                                       SD2FULL_ASPECTS, duration=(8, 4, 15)),
            "optional": _tail_optional({
                **{f"image_{i + 1}": ("IMAGE",) for i in range(4)},
                "image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考图公网URL，每行一个（填了优先，≤9）"}),
                "video_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考视频URL，每行一个（≤3）"}),
                "video_paths": ("STRING", {"default": "", "multiline": True, "placeholder": "本地视频路径，每行一个（自动上传换URL）"}),
                "audio_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考音频URL，每行一个（≤3）"}),
                "audio_paths": ("STRING", {"default": "", "multiline": True, "placeholder": "本地音频路径，每行一个（自动上传换URL）"}),
                "enable_sound": ("BOOLEAN", {"default": True, "tooltip": "发出去是字符串 'on'/'off'"}),
            }),
        }

    RETURN_TYPES, RETURN_NAMES, OUTPUT_TOOLTIPS = _RET, _RET_NAMES, _RET_TIPS
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, generation_mode, duration, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 image_urls="", video_urls="", video_paths="", audio_urls="", audio_paths="",
                 enable_sound=True, custom_model="", save_dir="", filename="", **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        imgs = _xp_media_urls(cfg, _imgs_from(kwargs, 4), image_urls, 9)

        need = {"首帧生成视频": 1, "首尾帧生成视频": 2, "多参考图生成视频": 1,
                "首帧+参考图生成视频": 1}.get(generation_mode, 0)
        if len(imgs) < need:
            raise RespectAPIError(f"{generation_mode} 至少需要 {need} 张图，现在只有 {len(imgs)} 张")

        meta: dict = {"ratio": aspect_ratio, "enableSound": "on" if enable_sound else "off"}
        mode_type = SD2FULL_MODETYPE.get(generation_mode, "")
        if mode_type:
            meta["modeType"] = mode_type      # 纯参考模式省略该键

        body: dict = {"model": model, "prompt": prompt,
                      "duration": int(duration), "metadata": meta}
        if imgs and generation_mode != "文生视频":
            body["images"] = imgs[:2] if generation_mode == "首尾帧生成视频" else imgs
        vids = _xp_local_or_urls(cfg, video_urls, video_paths, 3)
        auds = _xp_local_or_urls(cfg, audio_urls, audio_paths, 3)
        if vids:
            body["videos"] = vids
        if auds:
            body["audios"] = auds

        direct, task_id, _ = _xp_submit(cfg, "/v1/videos", body)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        return _xp_finish(cfg, url, task_id, "xp_sd2full", auto_download, save_dir, filename)


# ---------------------------------------------------------------------------
# #11  sd-720满血-900（不售后）
# ---------------------------------------------------------------------------


class RespectXPSd900:
    """小裴 sd-720满血-900（不售后）（文档 #11）。**只支持多参考图**，1–9 张。

    固定 15 秒 / 720p，比例只有 16:9 和 9:16。
    两个易错点：`duration` 是**字符串** `"15"`；`reference_images` 是**对象数组** `[{"url":…}]`。
    不支持文生、首帧、首尾帧、视频参考、音频参考 —— 名字里的「不售后」不是玩笑，参数错了没人管。
    """

    DESCRIPTION = ("小裴 sd-720满血-900（不售后）（文档#11）。只支持多参考图1-9张；"
                   "duration 是字符串'15'；reference_images 是对象数组[{url}]；固定720p，只有16:9/9:16。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        req = _base_required([SD900_MODEL], SD900_MODEL, ["16:9", "9:16"], with_mode=False)
        return {
            "required": req,
            "optional": _tail_optional({
                **{f"image_{i + 1}": ("IMAGE",) for i in range(4)},
                "image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考图公网URL，每行一个（填了优先，1-9张）"}),
            }),
        }

    RETURN_TYPES, RETURN_NAMES, OUTPUT_TOOLTIPS = _RET, _RET_NAMES, _RET_TIPS
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 image_urls="", custom_model="", save_dir="", filename="",
                 inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        imgs = _xp_media_urls(cfg, _imgs_from(kwargs, 9), image_urls, 9)
        if not imgs:
            raise RespectAPIError(
                "这支**只支持多参考图**（文档 #11），至少要 1 张。\n"
                "它不支持文生/首帧/首尾帧/视频参考/音频参考，要那些请换别的分支。")

        body: dict = {
            "model": model, "prompt": prompt,
            "duration": "15",                        # 字符串，不是整数
            "aspect_ratio": aspect_ratio, "resolution": "720p",
            "reference_images": [{"url": u} for u in imgs],   # 对象数组
        }
        direct, task_id, _ = _xp_submit(cfg, "/v1/videos", body)
        url = direct or _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))
        return _xp_finish(cfg, url, task_id, "xp_sd900", auto_download, save_dir, filename)


NODE_CLASS_MAPPINGS = {
    "RespectXPGrok10": RespectXPGrok10,
    "RespectXPGrok15": RespectXPGrok15,
    "RespectXPHorseOfficial": RespectXPHorseOfficial,
    "RespectXPH3": RespectXPH3,
    "RespectXPVolcano": RespectXPVolcano,
    "RespectXPSd25": RespectXPSd25,
    "RespectXPSd2Full": RespectXPSd2Full,
    "RespectXPSd900": RespectXPSd900,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectXPGrok10": "Respect 小裴 GROK1.0 视频（可多参）",
    "RespectXPGrok15": "Respect 小裴 GROK1.5-Preview（可多参）",
    "RespectXPHorseOfficial": "Respect 小裴 Horse官方快乐马（按秒）",
    "RespectXPH3": "Respect 小裴 Minimax-h3（/video/generations）",
    "RespectXPVolcano": "Respect 小裴 火山官方 sd稳定版（content块）",
    "RespectXPSd25": "Respect 小裴 SD2.5 不卡脸（按秒，4-29s）",
    "RespectXPSd2Full": "Respect 小裴 SD2.0 全系列不卡脸（metadata）",
    "RespectXPSd900": "Respect 小裴 sd-720满血-900（不售后，只多参考）",
}
