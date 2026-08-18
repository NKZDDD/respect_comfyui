"""Respect ComfyUI 扩展 - 小霸龙（`https://api.keik.cc`）节点。

文档：小霸龙 API 统一图片与视频接口文档 r21（2026-07-30）

- 图片 **同步**：`POST /v1/images/generations` 直接返回 `data[]`，没有任务 ID、没有轮询
- 视频 **异步**：`POST /v1/videos` → `GET /v1/videos/{task_id}` → `GET /v1/videos/{task_id}/content`
- 素材上传：`POST /v1/assets/uploads`（渠道无关）→ `asset://xiaobalong/...`，**24 小时有效**

这家最要命的一条是**计费安全规则**（文档原文）：

> 图片和视频的创建 POST 都只能提交一次，**客户端不得自动重试**。

所以本文件所有创建请求一律 `retries=1`（= 只发一次）。网络中断/超时/没拿到任务 ID
都不重投，节点会把「已经可能计费」这句话打在报错里让你人工核对。

其余几个和别家不一样的点：
1. 图片的比例字段是 **`ratio`**（`size` 只在含 `:` 时才当别名），数量字段推荐 **`count`**（1–4）
2. 图片 HTTP 200 **不等于成功**：`error` 非空或 `data: []` 都算失败（且不结算）
3. 视频统一用 **`duration` 整数**；素材是**纯字符串数组** `images` / `videos` / `audios`
   （**不能用对象数组**），分别 ≤9 / ≤3 / ≤3
4. 状态多一个 **`unknown`** —— 它**不是失败**，也不是可以重投的信号，只能继续低频查
5. 创建阶段叫 `processing`、查询阶段叫 `in_progress`，两个都要认
6. 结果地址 `metadata.url` 指向 `/v1/videos/{id}/content`，那是**要鉴权的代理**，不是公开直链
"""

from __future__ import annotations

import json
import os

from .utils import (RespectAPIError, api_request, download_to_output,
                    dynamic_url_inputs, ensure_config, extract_data_array_images,
                    extract_image_payloads,
                    resolve_image_to_tensor, tensors_concat)
from .video_nodes import _async_extract_url, _async_poll, _sd2_extract_task_id

CATEGORY = "Respect/小霸龙"

XBL_IMAGE_MODELS = ["gemini-3-pro-image", "gemini-3.1-flash-image",
                    "image2", "image2-2k4k", "image2-4k", "image2-high"]
# 2026-08-16 从 GET /api/pricing（公开可读）实拉的清单，**不是文档 r21 里那批**。
# r21（2026-07-30）写的 bh2.0-* / gz-sd480p / sdvip* / doubaofast / quanneng2.0 /
# fd-Seedance 2.0 933 / video-standard-720p / B-quannengship2.0 现在**全部查不到**，
# 20 个里只活下来 sd2-fast福利 和 sd2-福利 两个。所以别照文档抄模型名。
# 文档自己也写了：不要把 /v1/models 或 /api/pricing 永久硬编码 —— 拿不准就跑
# 『Respect 小霸龙 模型与价格』节点看当下的。
XBL_VIDEO_MODELS = [
    # 便宜 → 贵（USD 单价，2026-08-16）
    "sd2-mini-480p", "sd2-mini-720p", "sd2-720p-933", "sd2.5-480p-301010",
    "sd2.0-720p-903", "sd2-720p-high", "sd2.5-720p-301010", "sd2-标准720p",
    "sd2-900", "sd2-fast福利", "sd2-fast-933", "sd2-福利",
    "sd2-720p-福利", "sd2-720p-quan", "gz-sd2-720p",
]
XBL_RATIOS = ["", "9:16", "16:9", "1:1", "4:3", "3:4", "21:9"]
XBL_RESOLUTIONS = ["", "2K", "4K"]

# 文档 12.2 那两条时长白名单（quanneng2.0 / -9tu）对应的模型已经下线，先清空。
# 现存这批的档位官方没给，不猜 —— 参数越界会 400，400 不结算，比猜错时长安全。
XBL_DURATION_RULES: dict = {}
# 单文件上限（文档 11.2）
XBL_UPLOAD_LIMITS = {".jpg": 10, ".jpeg": 10, ".png": 10, ".webp": 10,
                     ".mp3": 50, ".wav": 50, ".mp4": 60}

MAX_IMAGES, MAX_VIDEOS, MAX_AUDIOS = 9, 3, 3


def _xbl_lines(s: str, cap: int) -> list:
    return [ln.strip() for ln in (s or "").splitlines() if ln.strip()][:cap]


def _xbl_check_assets(items: list, kind: str) -> None:
    """素材只能是公网 HTTPS 直链或 asset://xiaobalong/... URI。"""
    bad = [u for u in items if not u.startswith(("http://", "https://", "asset://"))]
    if bad:
        raise RespectAPIError(
            f"小霸龙的 {kind} 只收「无需登录即可下载的 HTTPS 直链」或上传接口返回的 "
            f"asset://xiaobalong/... URI，这些都不是：{bad[:2]}\n"
            f"本地文件请接『Respect 小霸龙 上传素材』节点换 asset:// URI（24 小时有效）。")


def _xbl_no_retry_hint(exc: Exception, what: str) -> RespectAPIError:
    """创建 POST 失败时的统一提示：**不要**重跑节点。"""
    return RespectAPIError(
        f"小霸龙{what}创建请求失败：{exc}\n\n"
        f"⚠ 文档规定创建 POST 只能提交一次、不得自动重试。这次可能已经越过计费边界，\n"
        f"  请**先不要重跑本节点**，记下提交时间去后台/找管理员核对是否已建单扣费。")


# ---------------------------------------------------------------------------
# ① 小霸龙 模型与价格（先查再填：模型名区分大小写，还有中文名）
# ---------------------------------------------------------------------------


class RespectXiaobalongModels:
    """小霸龙 模型 + 实时价格（`GET /v1/models` + `GET /api/pricing`）。

    文档要求：创建请求必须用 `/v1/models` 返回的**精确 id**（区分大小写、空格和中文），
    且不要把模型/价格永久硬编码。这个节点把两边合起来列出来。
    """

    DESCRIPTION = "小霸龙 GET /v1/models + /api/pricing：列出当前 Key 可用模型、能力类型与实时USD单价。"

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://api.keik.cc"}),
            },
            "optional": {
                "kind": (["全部", "只看视频", "只看图片"], {"default": "全部"}),
                "filter": ("STRING", {"default": "", "multiline": False, "placeholder": "按关键字过滤模型 id"}),
                "with_pricing": ("BOOLEAN", {"default": True, "tooltip": "同时拉 /api/pricing 实时单价"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("report", "model_ids", "count")
    OUTPUT_TOOLTIPS = ("可读清单（接『显示文字』看）", "模型 id 列表，每行一个", "数量")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, api_config, kind="全部", filter="", with_pricing=True):
        cfg = ensure_config(api_config)
        resp = api_request(cfg, "GET", "/v1/models", retries=1, timeout=60)
        data = resp.json() if resp.content else {}

        prices: dict = {}
        if with_pricing:
            try:
                pr = api_request(cfg, "GET", "/api/pricing", retries=1, timeout=60)
                for row in ((pr.json() if pr.content else {}).get("data") or []):
                    name = row.get("model_name")
                    if name:
                        prices[name] = row.get("model_price")
            except Exception as exc:
                print(f"[Respect] 小霸龙 价格接口没取到（不影响出图/出片）: {exc}")

        kw = (filter or "").strip().lower()
        rows, ids = [], []
        for m in (data.get("data") or []):
            mid = m.get("id") or ""
            if not mid:
                continue
            types = m.get("supported_endpoint_types") or []
            is_video = "openai-video" in types
            if kind == "只看视频" and not is_video:
                continue
            if kind == "只看图片" and is_video:
                continue
            if kw and kw not in mid.lower():
                continue
            ids.append(mid)
            usd = prices.get(mid)
            price = f"  单价=${usd:.6f}（¥{usd * 7.3:.3f} 展示价）" if isinstance(usd, (int, float)) else ""
            rows.append(f"{mid}\n    能力={','.join(types) or '未给'}  owner={m.get('owned_by', '?')}{price}")

        if not rows:
            report = "没拿到模型（检查 base_url=https://api.keik.cc / api_key，或该 Key 无可用模型）"
        else:
            report = (f"小霸龙可用模型 {len(rows)} 个：\n\n" + "\n\n".join(rows)
                      + "\n\n注：模型名区分大小写/空格/中文；价格以实时 /api/pricing 和所属分组为准，别硬编码。")
        print(f"[Respect] 小霸龙 模型 {len(ids)} 个: {', '.join(ids[:8])}{'…' if len(ids) > 8 else ''}")
        return (report, "\n".join(ids), len(ids))


# ---------------------------------------------------------------------------
# ② 小霸龙 图片（同步，无轮询；200 也可能是失败）
# ---------------------------------------------------------------------------


class RespectXiaobalongImage:
    """小霸龙 图片（`POST /v1/images/generations`，**同步**返回，无任务 ID / 无轮询）。

    比例字段是 `ratio`、数量字段是 `count`（1–4，按张计费）。
    参考图用 `reference_images`（**字符串 URL 数组**，≤9）——
    文档明说 `asset://` URI **只承诺用于视频**，图片参考图必须是执行服务能读到的 URL。
    """

    DESCRIPTION = ("小霸龙 同步图片。POST /v1/images/generations：比例字段是 ratio、数量是 count(1-4)、"
                   "参考图 reference_images 只收URL(≤9，asset://不适用于图片)。HTTP200 且 data 非空才算成功；"
                   "创建POST不重试。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://api.keik.cc"}),
                "model": (XBL_IMAGE_MODELS, {"default": "gemini-3-pro-image", "tooltip": "上新模型用 custom_model 填；名字区分大小写"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "count": ("INT", {"default": 1, "min": 1, "max": 4, "tooltip": "1–4 张，**按张计费**"}),
                "ratio": (XBL_RATIOS, {"default": "9:16", "tooltip": "留空=不发该字段（文档：拿不准就省略可选字段）"}),
                "resolution": (XBL_RESOLUTIONS, {"default": "", "tooltip": "image2-2k4k 只认 2K/4K，image2-4k 只认 4K；其余留空"}),
            },
            "optional": {
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "参考图URL（接『对象存储上传』）"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "extra_image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "追加参考图URL，每行一个（共≤9）"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "quality_level": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，模型支持才填"}),
                "response_format": ("STRING", {"default": "", "multiline": False, "placeholder": "可选：url 或 b64_json；留空=不发"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 9, "step": 1, "tooltip": "参考图URL接口数量（≤9）；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_url", "model_used")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, count, ratio, resolution,
                 extra_image_urls="", custom_model="", quality_level="",
                 response_format="", inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填，且不可为空")

        refs = (dynamic_url_inputs(kwargs) + _xbl_lines(extra_image_urls, MAX_IMAGES))[:MAX_IMAGES]
        bad = [u for u in refs if not u.startswith(("http://", "https://"))]
        if bad:
            raise RespectAPIError(
                f"小霸龙**图片**的参考图必须是执行服务能读取的 URL，这些不是：{bad[:2]}\n"
                f"注意：`asset://xiaobalong/...` 文档只承诺用于**视频**素材，别用在图片上。\n"
                f"本地图请接『Respect 对象存储上传』换公网链接。")

        body: dict = {"model": model, "prompt": prompt, "count": int(count)}
        if (ratio or "").strip():
            body["ratio"] = ratio.strip()
        if (resolution or "").strip():
            body["resolution"] = resolution.strip()
        if (quality_level or "").strip():
            body["quality_level"] = quality_level.strip()
        if (response_format or "").strip():
            body["response_format"] = response_format.strip()
        if refs:
            # 参考图字段只能选一组，不能和 image/image_url/images/image_urls 混用
            body["reference_images"] = refs

        print(f"[Respect] 小霸龙 图片 {model}: count={count} ratio={body.get('ratio', '省略')} "
              f"resolution={body.get('resolution', '省略')} 参考图{len(refs)}张")
        try:
            # retries=1 = 只发一次：文档规定创建 POST 不得自动重试
            resp = api_request(cfg, "POST", "/v1/images/generations", json_body=body,
                               retries=1, timeout=max(cfg.timeout, 600))
        except Exception as exc:
            raise _xbl_no_retry_hint(exc, "图片") from exc

        data = resp.json() if resp.content else {}
        # HTTP 200 不等于成功：error 非空 或 data 为空数组 都按失败处理
        err = data.get("error") if isinstance(data, dict) else None
        if err:
            raise RespectAPIError(f"小霸龙图片失败（应用级错误，不结算）: {json.dumps(err, ensure_ascii=False)[:300]}")
        # 文档明写按 data 结果项数计费，所以这里必须严格数：一个元素=一张。
        # 递归解析在 url+b64_json 同时给出时会数成两张，那会把账对错。
        items = extract_data_array_images(data) or extract_image_payloads(data)
        if not items:
            raise RespectAPIError(
                f"小霸龙返回 data 为空 → 按失败处理（文档：data:[] 不正式结算，但**不要自动重提**）。\n"
                f"原始响应: {json.dumps(data, ensure_ascii=False)[:400]}")

        tensors = [t for t in (resolve_image_to_tensor(i, cfg) for i in items) if t is not None]
        if not tensors:
            raise RespectAPIError(f"取到结果但无法解析为图片: {str(items)[:300]}")
        first = items[0] if isinstance(items[0], str) else ""
        print(f"[Respect] 小霸龙 出图 {len(items)} 张（按张计费）")
        return (tensors_concat(tensors), first if first.startswith("http") else "", model)


# ---------------------------------------------------------------------------
# ③ 小霸龙 视频（异步；duration 整数；素材是纯字符串数组）
# ---------------------------------------------------------------------------


class RespectXiaobalongVideo:
    """小霸龙 视频（`POST /v1/videos` → `GET /v1/videos/{task_id}` → `/content`）。

    body：`{model, prompt, duration:int, aspect_ratio, resolution, images[], videos[], audios[]}`。
    素材全是**字符串数组**（图≤9 / 视频≤3 / 音频≤3），可用公网 HTTPS 或
    『Respect 小霸龙 上传素材』给的 `asset://xiaobalong/...`。

    `status: unknown` **不是失败**，节点会继续查；创建 POST 只发一次，失败也不自动重投。
    """

    DESCRIPTION = ("小霸龙 异步视频。duration是整数(4-15)、素材是纯字符串数组 images≤9/videos≤3/audios≤3"
                   "(可用 asset:// URI)；unknown不是失败继续查；创建POST不重试。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://api.keik.cc"}),
                "model": (XBL_VIDEO_MODELS, {"default": "sd2-720p-933", "tooltip": "2026-08-16 实拉的清单；这家换模型很勤，拿不准先跑『模型与价格』节点。上新用 custom_model 填"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": ("INT", {"default": 5, "min": 1, "max": 60, "tooltip": "整数秒。多数模型 4–15；quanneng2.0 只有5/10/15，quanneng2.0-9tu 只有15"}),
                "aspect_ratio": (XBL_RATIOS, {"default": "9:16", "tooltip": "留空=不发（模型不认该字段时省略更安全）"}),
                "poll_interval": ("INT", {"default": 8, "min": 5, "max": 60, "tooltip": "文档建议 5–10 秒起步"}),
                "poll_timeout": ("INT", {"default": 2400, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "图片素材：HTTPS 或 asset://xiaobalong/..."}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "extra_image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "追加图片素材，每行一个（共≤9）"}),
                "video_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考视频，每行一个（≤3，部分模型加价×1.8）"}),
                "audio_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "参考音频，每行一个（≤3）"}),
                "resolution": ("STRING", {"default": "", "multiline": False, "placeholder": "留空。仅模型契约要求时才填"}),
                "generate_audio": (["不发", "true", "false"], {"default": "不发", "tooltip": "文档：仅模型明确支持时发送"}),
                "custom_model": ("STRING", {"default": "", "multiline": False, "placeholder": "可选，覆盖模型"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 9, "step": 1, "tooltip": "图片素材接口数量（≤9）；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "task_id")
    OUTPUT_TOOLTIPS = ("结果地址（/v1/videos/{id}/content，需鉴权，不是公开直链）",
                       "下载到本地的路径（预览/拼接用这个）", "任务 ID —— 出问题拿这个去核对")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, api_config, model, prompt, duration, aspect_ratio,
                 poll_interval, poll_timeout, auto_download,
                 extra_image_urls="", video_urls="", audio_urls="", resolution="",
                 generate_audio="不发", custom_model="", save_dir="", filename="",
                 inputcount=4, **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填，且不可为空")

        allowed = XBL_DURATION_RULES.get(model)
        if allowed and int(duration) not in allowed:
            raise RespectAPIError(
                f"{model} 的时长只能是 {allowed} 秒（文档 12.2），你填的是 {duration}。\n"
                f"先改对再跑 —— 这家按次计费，参数错了 400 也不结算，但别反复试。")

        imgs = (dynamic_url_inputs(kwargs) + _xbl_lines(extra_image_urls, MAX_IMAGES))[:MAX_IMAGES]
        vids, auds = _xbl_lines(video_urls, MAX_VIDEOS), _xbl_lines(audio_urls, MAX_AUDIOS)
        _xbl_check_assets(imgs, "images")
        _xbl_check_assets(vids, "videos")
        _xbl_check_assets(auds, "audios")

        body: dict = {"model": model, "prompt": prompt, "duration": int(duration)}
        if (aspect_ratio or "").strip():
            body["aspect_ratio"] = aspect_ratio.strip()
        if (resolution or "").strip():
            body["resolution"] = resolution.strip()
        if imgs:
            body["images"] = imgs                 # 纯字符串数组，不能用对象数组
        if vids:
            body["videos"] = vids                 # videos 优先；别同时发不一致的 reference_videos
        if auds:
            body["audios"] = auds
        if generate_audio in ("true", "false"):
            body["generate_audio"] = (generate_audio == "true")

        print(f"[Respect] 小霸龙 视频 {model}: duration={duration} "
              f"aspect_ratio={body.get('aspect_ratio', '省略')} 图{len(imgs)}/视频{len(vids)}/音频{len(auds)}")
        try:
            resp = api_request(cfg, "POST", "/v1/videos", json_body=body,
                               retries=1, timeout=max(cfg.timeout, 300))
        except Exception as exc:
            raise _xbl_no_retry_hint(exc, "视频") from exc

        data = resp.json() if resp.content else {}
        task_id = _sd2_extract_task_id(data)
        status = (data.get("status") or "").lower() if isinstance(data, dict) else ""
        if resp.status_code == 202 or status == "unknown":
            # 202 + unknown：已越过安全提交边界，网关也不确定上游收没收
            print(f"[Respect] ⚠ 小霸龙返回 {resp.status_code} status=unknown，任务 ID={task_id or '无'}\n"
                  f"          这**不是失败**：任务可能已在上游生成并计费。节点会继续查，"
                  f"千万不要重跑创建。")
        if not task_id:
            raise RespectAPIError(
                f"提交没返回任务 ID —— 文档规定此时**禁止自动重提**，请记下时间人工核对。\n"
                f"原始响应: {json.dumps(data, ensure_ascii=False)[:400]}")

        url = _async_extract_url(data)
        if not url:
            # unknown / queued / processing / in_progress 都继续查；只有 failed 才停
            url = _async_poll(cfg, task_id, interval=int(poll_interval), timeout=int(poll_timeout))

        local = ""
        if auto_download and url:
            try:
                # 结果地址是要鉴权的本地代理，download_to_output 会带上 Bearer
                local = download_to_output(url, cfg, prefix="xbl", save_dir=save_dir, filename=filename)
            except Exception as exc:
                print(f"[Respect] 小霸龙 视频下载失败: {exc}（任务 ID={task_id}，可用 /content 手动取）")
        return (url, local, task_id or "")


# ---------------------------------------------------------------------------
# ④ 小霸龙 上传素材（渠道无关 → asset://xiaobalong/...，24 小时有效）
# ---------------------------------------------------------------------------


class RespectXiaobalongUpload:
    """小霸龙 统一素材上传（`POST /v1/assets/uploads`）→ `asset://xiaobalong/...`。

    请求体**只能有一个名为 `file` 的文件字段**，不能附带别的表单字段。
    单文件上限：图片 10MiB / 音频 50MiB / 视频 60MiB；同一 IP 60 秒内 10 次。
    返回的 URI **只属于当前 Key、24 小时有效**，且**只承诺用于视频素材**（图片参考图请用公网 URL）。
    """

    DESCRIPTION = ("小霸龙 POST /v1/assets/uploads：本地图/音/视频 → asset://xiaobalong/... URI（24小时有效，"
                   "只用于视频素材）。图10MiB/音50MiB/视频60MiB，请求体只能有 file 一个字段。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": "base_url 填 https://api.keik.cc"}),
                "file_path": ("STRING", {"default": "", "multiline": False, "placeholder": "本地文件路径（.jpg/.png/.webp/.mp3/.wav/.mp4）"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("asset_uri",)
    OUTPUT_TOOLTIPS = ("asset://xiaobalong/... —— 直接填进视频节点的素材框（24 小时内有效）",)
    FUNCTION = "upload"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def upload(self, api_config, file_path):
        cfg = ensure_config(api_config)
        path = (file_path or "").strip().strip('"')
        if not os.path.isfile(path):
            raise RespectAPIError(f"找不到文件: {path}")

        ext = os.path.splitext(path)[1].lower()
        limit_mb = XBL_UPLOAD_LIMITS.get(ext)
        if limit_mb is None:
            raise RespectAPIError(
                f"小霸龙只收 {'/'.join(sorted(XBL_UPLOAD_LIMITS))}，不收 {ext or '（无扩展名）'}。\n"
                f"另外扩展名必须和文件真实内容一致，改后缀会被拒。")
        size = os.path.getsize(path)
        if size > limit_mb * 1024 * 1024:
            raise RespectAPIError(f"{os.path.basename(path)} 有 {size / 1048576:.1f}MiB，"
                                  f"超过 {ext} 的 {limit_mb}MiB 上限")

        ctype = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                 ".webp": "image/webp", ".mp3": "audio/mpeg", ".wav": "audio/wav",
                 ".mp4": "video/mp4"}[ext]
        with open(path, "rb") as fh:
            blob = fh.read()
        # 只能带 file 一个字段
        resp = api_request(cfg, "POST", "/v1/assets/uploads",
                           files=[("file", (os.path.basename(path), blob, ctype))],
                           retries=1, timeout=max(cfg.timeout, 900))
        data = resp.json() if resp.content else {}
        uri = data.get("url", "") if isinstance(data, dict) else ""
        if not uri:
            raise RespectAPIError(f"上传没返回 url: {json.dumps(data, ensure_ascii=False)[:300]}")
        print(f"[Respect] 小霸龙 素材已上传: {uri}（24 小时有效）")
        return (uri,)


NODE_CLASS_MAPPINGS = {
    "RespectXiaobalongVideo": RespectXiaobalongVideo,
    "RespectXiaobalongImage": RespectXiaobalongImage,
    "RespectXiaobalongModels": RespectXiaobalongModels,
    "RespectXiaobalongUpload": RespectXiaobalongUpload,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectXiaobalongVideo": "Respect 小霸龙 视频（keik.cc）",
    "RespectXiaobalongImage": "Respect 小霸龙 图片（同步）",
    "RespectXiaobalongModels": "Respect 小霸龙 模型与价格（先查再填）",
    "RespectXiaobalongUpload": "Respect 小霸龙 上传素材（→asset://）",
}
