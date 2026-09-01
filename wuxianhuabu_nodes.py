"""Respect ComfyUI 扩展 - 无限画布（`https://videogogo.top/api`）节点。

协议与 `script-to-video-studio/core/providers/wuxianhuabu.py` 同源。**这不是阿珂。**

只做视频。**模型清单和逐模型约束 2026-09-01 从 `GET /v1/models` 实拉**——
这家每个模型自己回一份 `capability_schema`，比文档准。实拉出来是 5 个模型，
而且时长和比例逐模型不同（见 `WXHB_MODELS`）。

⚠ 五个要点：

1. **模型框是候选，不是白名单。** 平台随时上新（这次实拉就比上一版多出三个），
   写死白名单等于「平台上新，你就得改插件」。所以下拉旁边有 `custom_model`：
   表外的名字**照发**，只是没有它的约束、那一趟不校验。
2. **约束逐模型不同，按全局那份填会被拒**：`seedance-2.5gs 720p` 是 **15–30 秒**
   （下限 15，不是 4）、`seedance-2.0(-F)-r` 只到 **15 秒**、
   `seedance-2.5-hf-720p` **没有 3:4**。实拉还确认**一个模型都不支持 21:9**——
   上一版给了这个选项，选中要么被拒、要么网关自己挑一个，出来不是这个画幅。
3. **张数还有个「三类加起来」的总数**（`max_assets: 50`）。图 30 + 视频 10 +
   音频 10 各自都不超，加起来也可能正好撞上。
4. **本机图能直接用。** 这家有素材上传口 `POST /v1/assets`（裸字节 +
   `X-File-Name` 头）换 `asset_id`。所以 IMAGE 输入口在这里是真能用的 ——
   跟鹤不一样（鹤只收公网 URL）。提交带 `Idempotency-Key`，重投不重复计费。
5. 认不出的参考素材、以及超限/不合规的参数**一律当场停**，不裁不改 ——
   裁了参考素材画面就用错图，改了时长片子和提示词对不上，两种都不报错。
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

# 这张表是 **2026-09-01 从 `GET /v1/models` 实拉的**，不是照文档抄的。
# 这家每个模型自己回一份 `capability_schema`，比任何文档都准 ——
# 实拉出来和上一版差了好几处，每一处的失败都是静默的：
#
#   · 上一版只写了 2 个模型，实际有 5 个 —— 另外三个页面上根本选不到
#   · 上一版给了 `21:9`，而**一个模型都不支持** —— 选了要么被拒，
#     要么网关自己挑一个，出来的片子不是这个画幅
#   · 比例和时长上一版是**全局一份**，实际逐模型不同：
#       seedance-2.5-hf-720p   16:9/9:16/4:3/1:1（**没有 3:4**），4–30 秒
#       seedance-2.5gs 720p    多 3:4，**15–30 秒**（下限是 15，不是 4）
#       seedance-2.0(-F)-r     多 3:4，**4–15 秒**（上限是 15，不是 30）
#     按全局那份填，2.0 系选 20 秒、2.5gs 选 10 秒都会被拒。
#
# **每一条只写它自己声明过的。** 没声明的键就不放 —— 放一个「看起来合理」
# 的数进去，和照文档抄没有区别：它会显示在界面上、会拿去拦人，而没有任何
# 东西背书。只有 `seedance-2.5gs 720p` 声明了图/视频/音频各自的上限，
# 另外几个只声明 `max_assets`（三类**加起来**的总数），还有两个什么都没声明。
_R4 = ["16:9", "9:16", "4:3", "1:1"]                    # 2.5-hf-720p 只有这四个
_R5 = ["16:9", "9:16", "1:1", "4:3", "3:4"]             # 其余四个多一个 3:4

WXHB_MODELS = {
    "seedance-2.5-hf-720p": {
        "resolution": "720p", "ratios": _R4, "durations": list(range(4, 31)),
    },
    "seedance-2.5gs 720p": {                            # 名字里**有空格**，照它给的原样
        "resolution": "720p", "ratios": _R5, "durations": list(range(15, 31)),
        "max_images": 30, "max_videos": 10, "max_audios": 10,
        "max_assets": 50, "min_images": 1, "max_prompt": 8000,
    },
    "seedance-2.0-r-720P": {
        "resolution": "720p", "ratios": _R5, "durations": list(range(4, 16)),
        "max_assets": 50,
    },
    "seedance-2.0-F-r-720P": {
        "resolution": "720p", "ratios": _R5, "durations": list(range(4, 16)),
        "max_assets": 50,
    },
    # 它的 capability_schema 里**只有一个 notes 网址**，什么都没声明。
    # 480p 和比例是文档里写的，实拉没有背书 —— 标出来，别让「我们写的」
    # 看起来像「它说的」。
    "seedance-2.5-hf": {
        "resolution": "480p", "ratios": _R5, "durations": list(range(4, 31)),
    },
}
WXHB_MODEL_NAMES = list(WXHB_MODELS)
# 全局那份 = 各模型的**并集**，只用来填界面候选和「整家总体收什么」。
# 判合不合法要按模型来（见 _wxhb_limits）—— 拿并集去判等于全放行。
WXHB_RATIOS = _R5
WXHB_MAX_IMAGES, WXHB_MAX_VIDEOS, WXHB_MAX_AUDIOS = 30, 10, 10


def _wxhb_limits(model: str) -> dict:
    """这一个模型的已知约束。**认不出就返回空 —— 空的意思是「不知道」，
    不是「不允许」。**

    上面那张表是**候选和已知约束，不是白名单**。平台随时会上新模型
    （这次实拉就多出三个），写死白名单等于「平台上新，你就得改代码」。
    所以模型用「下拉候选 + custom_model 覆盖」：表里有的按它的约束校验，
    表外的**原样发出去**，只在控制台说一声「没有它的约束，这趟不校验」。
    真不合法的话平台会拒，而那句拒绝是响的。
    """
    return WXHB_MODELS.get(model) or {}


def _wxhb_guess_resolution(model: str) -> str:
    """名字里带 720/480/1080 就按它。**猜不出来就返回空、不填这个字段** ——
    随手填一个的后果是「片子出得来、分辨率不是你要的」，而且不报错。
    """
    m = re.search(r"(2160|1440|1080|720|540|480|360)\s*[pP]", model or "")
    return (m.group(1) + "p") if m else ""

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

    DESCRIPTION = ("无限画布 视频(base_url=https://videogogo.top/api)。模型清单和逐模型约束"
                   "**2026-09-01 从 /v1/models 实拉**：时长、比例、张数上限各模型不同"
                   "(2.5gs 是 15-30 秒、2.0 系只到 15 秒、2.5-hf-720p 没有 3:4)。"
                   "模型框是**候选不是白名单** —— custom_model 填表外的名字会照发、只是不校验。"
                   "本机图会自动传 /v1/assets 换 asset_id，不用先配对象存储。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_config": ("RESPECT_CONFIG", {"tooltip": BASE_HINT}),
                "model": (WXHB_MODEL_NAMES, {"default": "seedance-2.5-hf-720p",
                                             "tooltip": "2026-09-01 实拉的 5 个。**这是候选不是白名单** ——"
                                                        "平台上新时用下面的 custom_model 填新名字，照样发得出去"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "seconds": ("INT", {"default": 15, "min": 4, "max": 30,
                                    "tooltip": "**逐模型不同**：2.5gs 720p 是 15-30；2.0 系只到 15；"
                                               "2.5-hf 系 4-30。超了当场报，不白等排队"}),
                "ratio": (WXHB_RATIOS, {"default": "9:16",
                                        "tooltip": "seedance-2.5-hf-720p **没有 3:4**；实拉确认一个模型都不支持 21:9"}),
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
                # ⚠ 新加的 widget **必须追加在末尾** —— widgets_values 是按位置存的，
                # 插在中间会让已保存工作流的每个值都错位一格。
                "custom_model": ("STRING", {"default": "", "multiline": False,
                                            "placeholder": "平台上新的模型名，填了就覆盖上面的下拉",
                                            "tooltip": "表外的名字**照发**，只是没有它的约束、这趟不校验。"
                                                       "平台上新不用等插件更新"}),
                "resolution": ("STRING", {"default": "", "multiline": False,
                                          "placeholder": "留空=按模型/名字推；推不出就不发这个字段",
                                          "tooltip": "优先级：这里填的 > 表里记的 > 从模型名认的 > **不填**。"
                                                     "「不填」是有意义的一档：让平台用它自己的默认，比蒙一个强"}),
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
                 save_dir="", filename="", inputcount=4, custom_model="",
                 resolution="", **kwargs):
        cfg = ensure_config(api_config)
        model = (custom_model or "").strip() or model
        if not (prompt or "").strip():
            raise RespectAPIError("prompt 必填")
        sec = int(seconds)
        lim = _wxhb_limits(model)
        if not lim:
            # 表里没有 = 我们**不知道**它的约束，不是不允许。照发。
            print(f"[Respect] ⚠ 无限画布没有 {model!r} 的约束记录"
                  f"（这张表是 2026-09-01 实拉的，平台上新会比它快）——"
                  f"时长/比例/张数这一趟都不校验，照你填的发出去。"
                  f"不合法的话平台会拒，那句拒绝是响的。")

        frames = expand_image_frames(dynamic_image_inputs(kwargs))
        url_refs = dynamic_url_inputs(kwargs)
        videos = [ln.strip() for ln in (video_urls or "").splitlines() if ln.strip()]
        audios = [ln.strip() for ln in (audio_urls or "").splitlines() if ln.strip()]
        n_img = len(frames) + len(url_refs)

        # **逐模型判，而且一次把问题说全。** 一条一条报要跑好几趟，
        # 而这些在发请求之前就全知道 —— 现在停比撞一个 400 便宜，
        # 更比「平台不报错、自己挑个默认值」强。
        bad = []
        if lim and sec not in lim["durations"]:
            bad.append(f"{model} 的时长只能是 {min(lim['durations'])}–"
                       f"{max(lim['durations'])} 秒，这一项填的是 {sec} 秒")
        if lim and ratio not in lim["ratios"]:
            bad.append(f"{model} 不收 {ratio} 这个画幅，它只有 {' / '.join(lim['ratios'])}")
        # 张数上限**表外的模型也判** —— 这几个是整家的接口上限，不是某个模型的脾气；
        # 超了的后果是服务商截掉多的，而**截掉的正是排在后面那几张**，
        # 画面用错参考却标成功。报错要分清这个数是模型声明的还是整家的兜底。
        for label, n, key, fam in (("参考图", n_img, "max_images", WXHB_MAX_IMAGES),
                                   ("参考视频", len(videos), "max_videos", WXHB_MAX_VIDEOS),
                                   ("参考音频", len(audios), "max_audios", WXHB_MAX_AUDIOS)):
            cap = lim.get(key)
            src = f"{model} 声明的" if cap is not None else "整家的上限（这个模型没单独声明）"
            cap = cap if cap is not None else fam
            if n > cap:
                bad.append(f"{label} {n} 条，超了 {cap} 条 —— {src}")
        # **三类加起来还有一个总数。** 图 30 + 视频 10 + 音频 10 各自都不超，
        # 加起来 50 也可能正好撞上。
        total_cap, total = lim.get("max_assets"), n_img + len(videos) + len(audios)
        if total_cap and total > total_cap:
            bad.append(f"参考素材一共 {total} 条（图 {n_img} + 视频 {len(videos)} + "
                       f"音频 {len(audios)}），超了 {model} 的总数上限 {total_cap} —— "
                       f"**分类各自都没超，是加起来超的**")
        if lim.get("min_images") and n_img < lim["min_images"]:
            bad.append(f"{model} 要求至少 {lim['min_images']} 张参考图，这一条一张都没有")
        picked = (resolution or "").strip()
        if picked and lim.get("resolution") and picked != lim["resolution"]:
            bad.append(f"{model} 只有 {lim['resolution']}，填的是 {picked}")
        if lim.get("max_prompt") and len(prompt) > lim["max_prompt"]:
            bad.append(f"提示词 {len(prompt)} 字，超了 {model} 的 {lim['max_prompt']} 字上限")
        if bad:
            raise RespectAPIError(
                "无限画布这一条发不出去：\n  · " + "\n  · ".join(bad)
                + "\n**不会静默裁掉或改掉** —— 裁了参考素材画面就用错图，"
                  "改了时长片子和提示词对不上，两种都不报错。")

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
            "ratio": ratio,
            "generate_audio": bool(generate_audio),
            "watermark": bool(watermark),
        }
        # 优先级：**填的 > 表里记的 > 从模型名认的 > 不填**。
        # 「不填」是有意义的一档：让平台用它自己的默认，比我们蒙一个强 ——
        # 蒙错的后果是「片子出得来、分辨率不是你要的」，而且不报错。
        res = picked or lim.get("resolution") or _wxhb_guess_resolution(model)
        if res:
            body["resolution"] = res
        if images:
            body["reference_images"] = images
        if videos:
            body["reference_videos"] = videos
        if audios:
            body["reference_audios"] = audios

        # 同一次生成用同一个 key：重投不会重复计费
        headers = dict(cfg.headers(content_type="application/json"))
        headers["Idempotency-Key"] = str(uuid.uuid4())
        print(f"[Respect] 无限画布 {model}: {sec}s "
              f"{body.get('resolution') or '分辨率跟平台默认'} {ratio} "
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
