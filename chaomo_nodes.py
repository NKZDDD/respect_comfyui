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
    b64_decode_loose,
    download_to_output,
    dynamic_image_inputs,
    dynamic_url_inputs,
    ensure_config,
    expand_image_frames,
    extract_data_array_images,
    extract_image_payloads,
    resolve_image_to_tensor,
    tensor_to_b64,
    tensors_concat,
)
from .video_nodes import _async_extract_url, _async_poll, _sd2_extract_task_id

CATEGORY = "Respect/超模"

CM_VIDEO_MODELS = ["seedance2", "seedance2-fast", "seedance2-mini"]
CM_IMAGE_MODELS = [
    # Native 三档：官方原生接口，2026-08 确认在售
    "gpt-image2-1K-Native", "gpt-image2-2K-Native", "gpt-image2-4K-Native",
    "gpt-image2-1K", "gpt-image2-2K-low", "gpt-image2-4K-low",
    "gpt-image2-2K-Direct", "gpt-image2-4K-Direct", "gpt-image2-4K",
    "gpt-image-1k-th",
    "gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview",
]
CM_RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "2:3", "3:2", "21:9"]
# quality：文档示例用 "high"，其余取值没列全，所以默认「(不传)」——
# 不猜着发，发了不认识的值可能整单 400。
CM_QUALITY = ["(不传)", "high", "medium", "low", "auto"]
CM_SIZES = ["720p", "1080p", "480p", "4k"]      # 视频 size = 分辨率档位
CM_MAX_REFS = 9


def _cm_lines(s: str, cap: int) -> list:
    return [ln.strip() for ln in (s or "").splitlines() if ln.strip()][:cap]


def _cm_meta(data) -> dict:
    """取 include_metadata 回来的核验信息（实际宽高 / 格式 / 字节数 / 耗时）。"""
    if not isinstance(data, dict):
        return {}
    for key in ("metadata", "meta", "info"):
        v = data.get(key)
        if isinstance(v, dict):
            return v
    arr = data.get("data")
    if isinstance(arr, list) and arr and isinstance(arr[0], dict):
        v = arr[0].get("metadata")
        if isinstance(v, dict):
            return v
    return {}


def _cm_check_meta(meta: dict, items: list, what: str) -> None:
    """拿网关自报的字节数核对手里的数据 —— 这是判断「有没有被截断」的硬证据。

    文档说 include_metadata 会给「**可核验的**实际图片宽高、格式和字节数」，
    那就真的拿来核验：base64 解出来的长度对不上，说明传输途中丢了数据，
    当场说清楚，而不是等 PIL 报一句看不懂的 "cannot identify image file"。
    """
    if not meta:
        return
    size = next((meta.get(k) for k in ("bytes", "size_bytes", "byte_size", "file_size")
                 if isinstance(meta.get(k), (int, float))), None)
    desc = "  ".join(f"{k}={meta[k]}" for k in
                     ("width", "height", "format", "bytes", "size_bytes", "elapsed", "duration")
                     if k in meta)
    if desc:
        print(f"[Respect] 超模 {what} 核验信息: {desc}")
    if not size:
        return
    for item in items:
        if not (isinstance(item, str) and item.startswith("data:")):
            continue
        try:
            got = len(b64_decode_loose(item.split(",", 1)[1]))
        except Exception:                                   # noqa: BLE001
            continue
        if got < int(size) * 0.98:                          # 留 2% 容差（元数据可能不含容器开销）
            raise RespectAPIError(
                f"超模说这张图有 {int(size)} 字节，实际只收到 {got} 字节"
                f"（缺 {int(size) - got}，{100 - got * 100 // int(size)}%）。\n"
                f"**数据在传输途中丢了**，不是解析问题。建议在节点上把 use_async 打开 —— "
                f"文档写明「异步任务固定返回 URL 结果」，走链接下载就不用把几 MB 的图"
                f"塞进 JSON 的 base64 字段，从根上避开这个问题。")


def _cm_check_thumbnail(meta: dict, tensors: list, what: str) -> None:
    """比对**解出来的真实像素**和网关自报的宽高 —— 专治「拿回来的是网页缩略图」。

    缩略图和残图是两种完全不同的失败：残图打不开、会报错；**缩略图打得开、
    看着正常，只是糊**。所以任何「文件坏没坏」式的检查都抓不到它，
    只有拿 include_metadata 给的原图规格一比才露馅。

    典型成因：响应里同时给了预览图和原图，兜底解析器挑中了预览那条。
    """
    if not meta or not tensors:
        return
    want_w = meta.get("width") if isinstance(meta.get("width"), int) else 0
    want_h = meta.get("height") if isinstance(meta.get("height"), int) else 0
    if not (want_w and want_h):
        return
    t = tensors[0]
    shape = getattr(t, "shape", None)
    if not shape or len(shape) < 3:
        return
    h, w = int(shape[-3]), int(shape[-2])       # IMAGE 是 [B, H, W, C]
    if w < want_w * 0.9 or h < want_h * 0.9:
        raise RespectAPIError(
            f"超模说这张图是 {want_w}x{want_h}，实际解出来只有 {w}x{h} —— "
            f"**拿到的是缩略图，不是原图**。\n"
            f"缩略图是一张完整合法的小图，能正常打开、也有正确的结尾标记，"
            f"所以「文件坏没坏」那类检查发现不了它。\n"
            f"多半是响应里同时给了预览图和原图、挑错了链接："
            f"把控制台那行 `← HTTP 200 {{…}}` 贴出来我看下 data[] 的结构。")
    print(f"[Respect] 超模 {what} 尺寸核验通过：{w}x{h}（网关自报 {want_w}x{want_h}）")


def _cm_finish(items: list, cfg, model: str, what: str, meta: dict = None) -> tuple:
    """把响应里的图片资源统一转成节点输出。

    这家**可能一次返回多张**（4K 系尤其要留意），所以：
    - IMAGE 输出把所有张拼成一个批次（后面接保存节点会全部存下来）
    - `image_url` 只给第一张（兼容老连线），全部链接走 `image_urls`（每行一个）
    只导出第一张的话，多出来的那些等于花了钱没拿到手。
    """
    tensors = [t for t in (resolve_image_to_tensor(i, cfg) for i in items) if t is not None]
    if not tensors:
        raise RespectAPIError(
            f"超模返回了 {len(items)} 项结果，但一项都解析不成图片。\n"
            f"**上面那行 `[Respect] 图片解析失败：…` 写了具体原因**，按它说的判断：\n"
            f"  · 「解码就失败了」/「数据不完整」→ 网关把图截断了，重跑一次；一直这样就是它那边的问题\n"
            f"  · 「开头不是任何已知图片格式」→ 返回的压根不是图（可能是错误信息），把响应贴出来看\n"
            f"首项开头：{str(items[0])[:120]}…")
    # 解出像素之后才量得到真实尺寸 —— 缩略图就是在这一步露馅的
    _cm_check_thumbnail(meta or {}, tensors, what)
    urls = [i for i in items if isinstance(i, str) and i.startswith("http")]
    if len(items) > 1:
        print(f"[Respect] 超模 {what} 返回 {len(items)} 张（其中 {len(urls)} 个链接）；"
              f"IMAGE 输出已拼成 {len(tensors)} 张的批次，全部链接见 image_urls")
    return (tensors_concat(tensors), urls[0] if urls else "", model,
            "\n".join(urls), len(tensors))


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
                "quality": (CM_QUALITY, {"default": "(不传)", "tooltip": "文档示例用 high；选(不传)就不带该字段"}),
            },
        }

    # image_urls / count 是后加的，**必须追加在末尾**，否则已保存工作流的连线会错位
    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("image", "image_url", "model_used", "image_urls", "count")
    OUTPUT_TOOLTIPS = ("所有返回的图拼成的批次", "第一张的链接", "实际用的模型",
                       "全部链接，每行一个（一次返回多张时用这个）", "这次拿到几张")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, ratio, poll_interval, poll_timeout,
                 custom_model="", response_format="url", use_async=True, quality="(不传)"):
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
            # 文档：返回可核验的实际图片宽高、格式和字节数 —— 用来核对有没有传丢
            "include_metadata": True,
        }
        if not quality.startswith("("):
            body["quality"] = quality
        if use_async:
            # 文档：**异步任务固定返回 URL 结果**，避开 base64 传大图
            body["async"] = True

        print(f"[Respect] 超模 图片 {model}: ratio={ratio} async={bool(use_async)}")
        resp = api_request(cfg, "POST", "/v1/images/generations", json_body=body,
                           retries=2, timeout=max(cfg.timeout, 300))
        data = resp.json() if resp.content else {}
        # 先按规范的 data[] 严格取（一个元素=一张），取不到再退回兜底的递归解析
        items = extract_data_array_images(data) or extract_image_payloads(data)
        if not items:
            tid = _img_task_id(data)
            if not tid:
                raise RespectAPIError(f"未取到图片也没有任务 ID: {json.dumps(data, ensure_ascii=False)[:400]}")
            items = _poll_image_task(cfg, tid, interval=int(poll_interval), timeout=int(poll_timeout))
        meta = _cm_meta(data)
        _cm_check_meta(meta, items, "图片")

        return _cm_finish(items, cfg, model, "图片", meta)


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
                "use_async": ("BOOLEAN", {"default": True, "tooltip": "强烈建议开：文档写明异步任务固定返回 URL，走链接下载可避开 base64 传输把大图弄坏"}),
                "quality": (CM_QUALITY, {"default": "(不传)", "tooltip": "文档示例用 high；选(不传)就不带该字段"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 9, "step": 1, "tooltip": "参考图接口数量（≤9）；改完点『更新输入口』按钮"}),
            },
        }

    # image_urls / count 是后加的，**必须追加在末尾**，否则已保存工作流的连线会错位
    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("image", "image_url", "model_used", "image_urls", "count")
    OUTPUT_TOOLTIPS = ("所有返回的图拼成的批次", "第一张的链接", "实际用的模型",
                       "全部链接，每行一个（一次返回多张时用这个）", "这次拿到几张")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, ratio, poll_interval, poll_timeout,
                 custom_model="", response_format="url", use_async=True,
                 quality="(不传)", inputcount=4, **kwargs):
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
            # 文档：**异步任务固定返回 URL 结果**。走异步就不用把几 MB 的图塞进
            # JSON 的 base64 字段 —— 那条路上任何一处丢字节都会让整张图报废。
            ("async", (None, "true" if use_async else "false")),
            # 文档：返回可核验的实际图片宽高、格式和**字节数**，用来核对有没有传丢
            ("include_metadata", (None, "true")),
        ]
        if not quality.startswith("("):
            files.append(("quality", (None, quality)))
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
        # 先按规范的 data[] 严格取（一个元素=一张），取不到再退回兜底的递归解析
        items = extract_data_array_images(data) or extract_image_payloads(data)
        if not items:
            tid = _img_task_id(data)
            if not tid:
                raise RespectAPIError(f"未取到图片也没有任务 ID: {json.dumps(data, ensure_ascii=False)[:400]}")
            items = _poll_image_task(cfg, tid, interval=int(poll_interval), timeout=int(poll_timeout))
        meta = _cm_meta(data)
        _cm_check_meta(meta, items, "图生图")

        return _cm_finish(items, cfg, model, "图生图", meta)


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
