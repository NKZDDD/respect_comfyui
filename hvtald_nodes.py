"""Respect ComfyUI 扩展 - HVTALD 空间（`z988.top`）节点。底层是**即梦 AI 国际版**。

文档：《视频端口介绍》（一手工作室）

和本插件接过的所有网关都不是一类，接之前先弄清它的形态：

- **不是同步 API，也不是「提交→轮询任务」**，而是「投递任务 → 回调通知」
- 固定产出 **15 秒 / 1080P**，不卡人脸，参考图最多 **9 张**
- **画面比例从 prompt 里提取，而且必须放在提示词最前面**（如 `9:16 女团舞…`）；
  没有 aspect_ratio 之类的字段
- 并发 = 开通的线路数；按次 2.5 元/条，包月 3600 元/线路

它给了三条路，本文件接的是后两条：

| 方式 | 怎么用 | 对应节点 |
|---|---|---|
| ② WebDAV 投料 | 素材传到空间根目录，系统**约 10 分钟扫一次**，成片落到 `outs/` | 「HVTALD 上传素材」 |
| ③ 回调接口 | `POST /dy/brush/fromApi` 投任务，成片通过 `feedbackurl` 回调 | 「HVTALD 视频」 |

**回调这条在 ComfyUI 里用不了** —— 节点是同步执行的，本机也没有公网地址去接
`feedbackurl`。所以「HVTALD 视频」节点改成：投完任务拿 `actionId`，然后
**去 WebDAV 的 `outs/` 目录轮询找文件名以该 actionId 开头的 mp4**
（文档的回调示例里 `videopath` 就是 `{actionId}_xxx.mp4` 这个形状）。
你要是有公网回调服务，把 `feedbackurl` 填上，它照样会回调，两边不冲突。

⚠ 两个坑：
1. **成片只保存 48 小时**，超时可能被删，节点默认自动下载到本地
2. `actionId` 文档自相矛盾（请求参数表写 32 位、回调参数表写 24 位），
   实际示例是 **24 位小写字母**，这里按示例来
"""

from __future__ import annotations

import json
import os
import random
import re
import string
import time
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse

import requests

from .utils import (RespectAPIError, download_to_output, dynamic_url_inputs,
                    tensor_to_b64)

CATEGORY = "Respect/HVTALD"

HV_MAX_IMAGES = 9
HV_RATIOS = ["9:16", "16:9", "1:1", "4:3", "3:4"]
# 文档：比例必须放提示词最前面，系统从 prompt 里提取
_RATIO_HEAD = re.compile(r"^\s*\d{1,2}\s*[:：]\s*\d{1,2}")


def _hv_action_id() -> str:
    """24 位小写字母 —— 按文档示例 `jdbamfupzohjmbsnxsombhip` 的形状来。

    文档请求参数表写「32 位字符串」、回调参数表写「24 位」，自相矛盾；
    示例是 24 位纯小写字母，以示例为准（示例是真跑出来的，表格是人写的）。
    """
    return "".join(random.choice(string.ascii_lowercase) for _ in range(24))


def _hv_cfg(cfg) -> dict:
    if not isinstance(cfg, dict) or "device_id" not in cfg:
        raise RespectAPIError("请先连接『Respect HVTALD 设置』节点")
    return cfg


def _hv_auth(cfg: dict):
    return (cfg["webdav_user"], cfg["webdav_password"])


def _hv_dav(cfg: dict, sub: str = "") -> str:
    base = cfg["webdav_url"].rstrip("/")
    return f"{base}/{sub.strip('/')}" if sub.strip("/") else base


def _hv_list(cfg: dict, sub: str = "outs") -> list:
    """PROPFIND 列目录，返回 [(文件名, 完整URL)]。

    WebDAV 就是 HTTP 扩展方法，用 requests 直接发 PROPFIND 即可，不用额外依赖。
    """
    url = _hv_dav(cfg, sub)
    try:
        resp = requests.request(
            "PROPFIND", url, auth=_hv_auth(cfg),
            headers={"Depth": "1", "Content-Type": "application/xml"},
            timeout=cfg.get("timeout", 60))
    except requests.RequestException as exc:
        raise RespectAPIError(f"连不上 WebDAV（{url}）：{exc}")
    if resp.status_code == 404:
        return []
    if resp.status_code >= 400:
        raise RespectAPIError(
            f"WebDAV 列目录失败 HTTP {resp.status_code}（{url}）\n"
            f"401/403 多半是账号密码不对；确认用的是客服给的空间账号。")

    out = []
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        raise RespectAPIError(f"WebDAV 返回的不是合法 XML：{exc}")
    for href in root.iter("{DAV:}href"):
        raw = (href.text or "").strip()
        if not raw or raw.rstrip("/").endswith(urlparse(url).path.rstrip("/")):
            continue                                  # 跳过目录自身
        name = unquote(raw.rstrip("/").rsplit("/", 1)[-1])
        if not name:
            continue
        full = raw if raw.startswith("http") else (
            f"{urlparse(url).scheme}://{urlparse(url).netloc}{raw}")
        out.append((name, full))
    return out


def _hv_put(cfg: dict, name: str, blob: bytes, ctype: str) -> str:
    """上传一个文件到空间**根目录**（文档：素材都必须上传到根目录）。"""
    url = f"{_hv_dav(cfg)}/{name}"
    resp = requests.put(url, data=blob, auth=_hv_auth(cfg),
                        headers={"Content-Type": ctype},
                        timeout=cfg.get("timeout", 300))
    if resp.status_code >= 400:
        raise RespectAPIError(f"WebDAV 上传失败 HTTP {resp.status_code}: {name}")
    return url


# ---------------------------------------------------------------------------
# ① HVTALD 设置（凭据集中在这里，别散落到各节点）
# ---------------------------------------------------------------------------


class RespectHvtaldSettings:
    """HVTALD 空间的接入凭据。输出 `HVTALD_CONFIG` 给其余节点用。

    ⚠ 这里有 4 个密级字段（token / webdav 密码等）。**保存工作流会把它们一起存进
    JSON**，分享出去就是泄露。建议留空、改用环境变量：
    `HVTALD_DEVICE_ID` / `HVTALD_TOKEN` / `HVTALD_WEBDAV_USER` / `HVTALD_WEBDAV_PASSWORD`。
    """

    DESCRIPTION = ("HVTALD 空间凭据（deviceId/token/WebDAV账号）。留空则读环境变量 "
                   "HVTALD_DEVICE_ID / HVTALD_TOKEN / HVTALD_WEBDAV_USER / HVTALD_WEBDAV_PASSWORD。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "api_url": ("STRING", {"default": "http://ha.z988.top/dy/brush/fromApi", "multiline": False}),
                "webdav_url": ("STRING", {"default": "", "multiline": False, "placeholder": "http://fo.z988.top:901/webdav/project/…/5051"}),
            },
            "optional": {
                "device_id": ("STRING", {"default": "", "multiline": False, "placeholder": "留空=读环境变量 HVTALD_DEVICE_ID"}),
                "token": ("STRING", {"default": "", "multiline": False, "placeholder": "留空=读环境变量 HVTALD_TOKEN"}),
                "webdav_user": ("STRING", {"default": "", "multiline": False, "placeholder": "留空=读环境变量 HVTALD_WEBDAV_USER"}),
                "webdav_password": ("STRING", {"default": "", "multiline": False, "placeholder": "留空=读环境变量 HVTALD_WEBDAV_PASSWORD"}),
                "timeout": ("INT", {"default": 120, "min": 10, "max": 3600}),
            },
        }

    RETURN_TYPES = ("HVTALD_CONFIG",)
    RETURN_NAMES = ("hvtald_config",)
    FUNCTION = "build"
    CATEGORY = CATEGORY

    def build(self, api_url, webdav_url, device_id="", token="",
              webdav_user="", webdav_password="", timeout=120):
        cfg = {
            "api_url": (api_url or "").strip(),
            "webdav_url": (webdav_url or "").strip(),
            "device_id": (device_id or "").strip() or os.environ.get("HVTALD_DEVICE_ID", ""),
            "token": (token or "").strip() or os.environ.get("HVTALD_TOKEN", ""),
            "webdav_user": (webdav_user or "").strip() or os.environ.get("HVTALD_WEBDAV_USER", ""),
            "webdav_password": (webdav_password or "").strip() or os.environ.get("HVTALD_WEBDAV_PASSWORD", ""),
            "timeout": int(timeout),
        }
        missing = [k for k in ("webdav_url", "device_id", "token", "webdav_user", "webdav_password")
                   if not cfg[k]]
        if missing:
            print(f"[Respect] ⚠ HVTALD 这些字段还是空的：{missing}（填进去或设对应环境变量）")
        return (cfg,)


# ---------------------------------------------------------------------------
# ② HVTALD 视频（POST /dy/brush/fromApi → 去 WebDAV outs/ 等成片）
# ---------------------------------------------------------------------------


class RespectHvtaldVideo:
    """HVTALD 视频（即梦国际版，固定 15 秒 / 1080P）。

    投递 `POST /dy/brush/fromApi`，参数**全部在 JSON body 里**（不是 header）：
    `deviceId` / `token` / `imgs` / `prompt` / `webDavUrl` / `user` / `password`。

    **比例写在 prompt 最前面**（如 `9:16 跳女团舞…`）—— 这家没有比例字段，
    系统是从提示词里提取的，忘了写就按默认出。

    成片不是查任务查出来的：投完拿 `actionId`，节点去 WebDAV `outs/` 轮询
    找文件名以该 actionId 开头的 mp4（回调示例里就是这个形状）。
    """

    DESCRIPTION = ("HVTALD/即梦国际版视频，固定15秒1080P、参考图≤9张。比例要写在 prompt 最前面。"
                   "投递后去 WebDAV outs/ 轮询取片（成片只留48小时）。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "hvtald_config": ("HVTALD_CONFIG",),
                "prompt": ("STRING", {"default": "9:16 ", "multiline": True, "tooltip": "**比例必须放最前面**，如『9:16 跳韩系热辣女团舞』"}),
                "wait_for_video": ("BOOLEAN", {"default": True, "tooltip": "关掉=只投递拿 actionId，不等成片"}),
                "poll_interval": ("INT", {"default": 30, "min": 10, "max": 300, "tooltip": "系统约10分钟扫一次，查太勤没意义"}),
                "poll_timeout": ("INT", {"default": 1800, "min": 60, "max": 7200}),
                "auto_download": ("BOOLEAN", {"default": True, "tooltip": "成片只保存48小时，建议开"}),
            },
            "optional": {
                "ref_url_1": ("STRING", {"default": "", "multiline": False, "placeholder": "参考图**绝对地址**（接『对象存储上传』）"}),
                "ref_url_2": ("STRING", {"default": "", "multiline": False}),
                "ref_url_3": ("STRING", {"default": "", "multiline": False}),
                "ref_url_4": ("STRING", {"default": "", "multiline": False}),
                "extra_image_urls": ("STRING", {"default": "", "multiline": True, "placeholder": "追加参考图URL，每行一个（共≤9）"}),
                "feedbackurl": ("STRING", {"default": "", "multiline": False, "placeholder": "可选：你自己的公网回调地址；本机 ComfyUI 一般填不了"}),
                "action_id": ("STRING", {"default": "", "multiline": False, "placeholder": "可选：自定义 actionId，留空自动生成 24 位"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 9, "step": 1, "tooltip": "参考图URL接口数量（≤9）；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "local_path", "action_id")
    OUTPUT_TOOLTIPS = ("成片地址（WebDAV outs/ 里的）", "下载到本地的路径", "actionId —— 出问题拿这个对账")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, hvtald_config, prompt, wait_for_video, poll_interval,
                 poll_timeout, auto_download, extra_image_urls="", feedbackurl="",
                 action_id="", save_dir="", filename="", inputcount=4, **kwargs):
        cfg = _hv_cfg(hvtald_config)
        prompt = (prompt or "").strip()
        if not prompt:
            raise RespectAPIError("prompt 必填")
        if not _RATIO_HEAD.match(prompt):
            print("[Respect] ⚠ HVTALD：prompt 开头没看到比例（如 `9:16 `）。"
                  "这家没有比例字段，是**从提示词最前面提取**的，不写就按默认出片。")

        imgs = dynamic_url_inputs(kwargs)
        imgs += [ln.strip() for ln in (extra_image_urls or "").splitlines() if ln.strip()]
        if not imgs:
            raise RespectAPIError("imgs 必填：至少给 1 张参考图的**绝对地址**"
                                  "（本地图请接『Respect 对象存储上传』换公网链接）")
        bad = [u for u in imgs if not u.startswith(("http://", "https://"))]
        if bad:
            raise RespectAPIError(f"参考图必须是绝对地址（http/https），这些不是：{bad[:2]}")
        if len(imgs) > HV_MAX_IMAGES:
            print(f"[Respect] HVTALD 最多 {HV_MAX_IMAGES} 张参考图，已裁掉多余 {len(imgs) - HV_MAX_IMAGES} 张")
            imgs = imgs[:HV_MAX_IMAGES]

        aid = (action_id or "").strip() or _hv_action_id()
        body = {
            "deviceId": cfg["device_id"],
            "token": cfg["token"],
            "actionId": aid,
            "imgs": imgs,
            "prompt": prompt,
            "webDavUrl": cfg["webdav_url"],
            "user": cfg["webdav_user"],
            "password": cfg["webdav_password"],
        }
        if (feedbackurl or "").strip():
            body["feedbackurl"] = feedbackurl.strip()

        # 打日志时把密级字段挡掉 —— 这几个是明文传的，别再落进日志
        safe = dict(body, token="***", password="***", deviceId="***")
        print(f"[Respect] HVTALD 投递 actionId={aid} 参考图{len(imgs)}张")
        print(f"[Respect]   body={json.dumps(safe, ensure_ascii=False)[:400]}")

        try:
            resp = requests.post(cfg["api_url"], json=body, timeout=cfg.get("timeout", 120))
        except requests.RequestException as exc:
            raise RespectAPIError(f"投递失败（连不上 {cfg['api_url']}）：{exc}")
        try:
            data = resp.json()
        except Exception:                                   # noqa: BLE001
            raise RespectAPIError(f"投递返回的不是 JSON：HTTP {resp.status_code} {resp.text[:300]}")
        if int(data.get("code", 0)) != 200:
            raise RespectAPIError(f"投递被拒：{json.dumps(data, ensure_ascii=False)[:300]}\n"
                                  f"（检查 deviceId / token，以及线路是否还有余量）")
        aid = str(data.get("actionId") or aid)
        print(f"[Respect] HVTALD 已插入任务：{data.get('msg', '')} actionId={aid}")

        if not wait_for_video:
            return ("", "", aid)

        url = self._wait(cfg, aid, int(poll_interval), int(poll_timeout))
        local = ""
        if auto_download and url:
            try:
                local = _hv_download(cfg, url, save_dir, filename)
            except Exception as exc:                        # noqa: BLE001
                print(f"[Respect] HVTALD 成片下载失败: {exc}（成片只留 48 小时，尽快手动取）")
        return (url, local, aid)

    @staticmethod
    def _wait(cfg: dict, aid: str, interval: int, timeout: int) -> str:
        """去 outs/ 找文件名以 actionId 开头的 mp4。"""
        start, seen = time.time(), -1
        while time.time() - start < timeout:
            files = _hv_list(cfg, "outs")
            if len(files) != seen:
                print(f"[Respect] HVTALD outs/ 现有 {len(files)} 个文件，等 {aid} …")
                seen = len(files)
            for name, full in files:
                if name.startswith(aid) and name.lower().endswith((".mp4", ".mov")):
                    print(f"[Respect] HVTALD 成片就绪: {name}")
                    return full
            time.sleep(interval)
        raise RespectAPIError(
            f"等了 {timeout} 秒没在 outs/ 看到 {aid} 开头的成片。\n"
            f"任务可能还在队列里（这家是按线路排队的，满负荷时要等）。\n"
            f"把 wait_for_video 关掉先拿 actionId，稍后用『HVTALD 取成片』节点按 actionId 取。")


def _hv_download(cfg: dict, url: str, save_dir: str, filename: str) -> str:
    """带 WebDAV 认证下载成片。utils 的下载器不带 basic auth，所以这里自己来。"""
    resp = requests.get(url, auth=_hv_auth(cfg), stream=True, timeout=cfg.get("timeout", 300))
    if resp.status_code >= 400:
        raise RespectAPIError(f"下载失败 HTTP {resp.status_code}: {url}")
    tmp = os.path.join(os.environ.get("TEMP", "."), f"hvtald_{int(time.time())}.mp4")
    with open(tmp, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            fh.write(chunk)
    try:
        return download_to_output(tmp, None, prefix="hvtald", save_dir=save_dir, filename=filename)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# ③ HVTALD 上传素材（走方式②：投料到根目录，系统约10分钟自动扫）
# ---------------------------------------------------------------------------


class RespectHvtaldUpload:
    """HVTALD 素材投递（WebDAV 方式）。按文档的命名规则自动组装。

    - **单图模式**：`名字.png` + `名字.txt`（提示词）
    - **多图模式**：`名字=index1.png` … `名字=indexN.png` + `名字.txt`
      （系统扫到 `=index` 就认为是多图，按后面的数字排序，从 1 开始）

    素材**必须放根目录**；系统约每 10 分钟扫一次，成片落到 `outs/`。
    一组物料出一个视频，要多个就换不同的名字投多组。
    """

    DESCRIPTION = ("HVTALD 走 WebDAV 投料：单图=名字.png+名字.txt；多图=名字=index1..N.png+名字.txt。"
                   "必须传到根目录，系统约10分钟扫一次，成片进 outs/。")

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "hvtald_config": ("HVTALD_CONFIG",),
                "group_name": ("STRING", {"default": "", "multiline": False, "placeholder": "这组素材的名字（英文/数字，别带空格）"}),
                "prompt": ("STRING", {"default": "9:16 ", "multiline": True, "tooltip": "**比例放最前面**；会写成 <名字>.txt"}),
            },
            "optional": {
                "image_1": ("IMAGE",),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "inputcount": ("INT", {"default": 4, "min": 1, "max": 9, "step": 1, "tooltip": "参考图接口数量（≤9）；改完点『更新输入口』按钮"}),
            },
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("report", "uploaded")
    FUNCTION = "upload"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def upload(self, hvtald_config, group_name, prompt, inputcount=4, **kwargs):
        import base64

        from .utils import dynamic_image_inputs, expand_image_frames

        cfg = _hv_cfg(hvtald_config)
        name = (group_name or "").strip()
        if not name or re.search(r"[\\/\s]", name):
            raise RespectAPIError("group_name 必填，且不能带空格或斜杠（它要当文件名用）")
        prompt = (prompt or "").strip()
        if not prompt:
            raise RespectAPIError("prompt 必填（会写成 <名字>.txt，系统靠它出片）")
        if not _RATIO_HEAD.match(prompt):
            print("[Respect] ⚠ HVTALD：prompt 开头没看到比例（如 `9:16 `），"
                  "系统是从提示词最前面提取比例的。")

        frames = expand_image_frames(dynamic_image_inputs(kwargs))[:HV_MAX_IMAGES]
        if not frames:
            raise RespectAPIError("至少接 1 张 IMAGE")

        done = []
        multi = len(frames) > 1
        for i, frame in enumerate(frames, start=1):
            b64 = tensor_to_b64(frame, fmt="PNG", max_side=2048)
            if not b64:
                continue
            blob = base64.b64decode(b64[0].split(",", 1)[1])
            # 多图必须是 `名字=indexN.png`；单图就是 `名字.png`
            fname = f"{name}=index{i}.png" if multi else f"{name}.png"
            _hv_put(cfg, fname, blob, "image/png")
            done.append(fname)

        # 提示词文件**最后传** —— 先有图再有 txt，避免扫描器撞上只有 txt 的半成品
        _hv_put(cfg, f"{name}.txt", prompt.encode("utf-8"), "text/plain; charset=utf-8")
        done.append(f"{name}.txt")

        report = (f"已投递到空间根目录（{'多图' if multi else '单图'}模式）：\n  "
                  + "\n  ".join(done)
                  + "\n\n系统约 10 分钟扫一次，成片会落到 outs/。"
                    "用『HVTALD 取成片』节点按名字取，成片只保存 48 小时。")
        print(f"[Respect] HVTALD 已投料 {len(done)} 个文件（组名 {name}）")
        return (report, len(done))


# ---------------------------------------------------------------------------
# ④ HVTALD 取成片（列 outs/ 或按 actionId/组名取）
# ---------------------------------------------------------------------------


class RespectHvtaldOuts:
    """列 WebDAV `outs/` 目录，或按前缀（actionId / 组名）取一条成片下载。

    投递和取片分开的场景用这个：`HVTALD 视频` 关掉 `wait_for_video` 先拿 actionId，
    过一阵再用本节点取。**成片只保存 48 小时**，及时下载备份。
    """

    DESCRIPTION = "列 HVTALD 的 outs/ 目录，或按 actionId/组名前缀取成片并下载（成片只留48小时）。"

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "hvtald_config": ("HVTALD_CONFIG",),
            },
            "optional": {
                "match_prefix": ("STRING", {"default": "", "multiline": False, "placeholder": "按 actionId 或组名开头匹配；留空=只列目录"}),
                "auto_download": ("BOOLEAN", {"default": True}),
                "subdir": ("STRING", {"default": "outs", "multiline": False, "placeholder": "默认 outs"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("report", "video_url", "local_path", "count")
    FUNCTION = "run"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def run(self, hvtald_config, match_prefix="", auto_download=True, subdir="outs",
            save_dir="", filename=""):
        cfg = _hv_cfg(hvtald_config)
        files = _hv_list(cfg, (subdir or "outs").strip())
        rows = [f"  {n}" for n, _ in files]
        report = f"{subdir or 'outs'}/ 共 {len(files)} 个文件：\n" + ("\n".join(rows) or "  （空）")

        pre = (match_prefix or "").strip()
        if not pre:
            return (report + "\n\n注：成片只保存 48 小时，及时下载备份。", "", "", len(files))

        hit = next(((n, u) for n, u in files
                    if n.startswith(pre) and n.lower().endswith((".mp4", ".mov"))), None)
        if not hit:
            return (report + f"\n\n没找到以 `{pre}` 开头的成片 —— 可能还在队列里，过会儿再试。",
                    "", "", len(files))

        name, url = hit
        local = ""
        if auto_download:
            try:
                local = _hv_download(cfg, url, save_dir, filename)
            except Exception as exc:                        # noqa: BLE001
                print(f"[Respect] HVTALD 下载失败: {exc}")
        return (report + f"\n\n命中：{name}", url, local, len(files))


NODE_CLASS_MAPPINGS = {
    "RespectHvtaldSettings": RespectHvtaldSettings,
    "RespectHvtaldVideo": RespectHvtaldVideo,
    "RespectHvtaldUpload": RespectHvtaldUpload,
    "RespectHvtaldOuts": RespectHvtaldOuts,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectHvtaldSettings": "Respect HVTALD 设置（空间/WebDAV）",
    "RespectHvtaldVideo": "Respect HVTALD 视频（即梦国际版15秒）",
    "RespectHvtaldUpload": "Respect HVTALD 上传素材（WebDAV投料）",
    "RespectHvtaldOuts": "Respect HVTALD 取成片（outs/）",
}
