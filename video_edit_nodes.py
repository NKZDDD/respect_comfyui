"""Respect ComfyUI 扩展 - 视频/帧裁剪节点。

按帧号灵活裁剪，支持多种写法（1 起，含端点）：
- `1-10`  连续区间
- `3-7`   区间
- `1-1`   单帧
- `3,7`   多个单帧
- `1-3,8-10`  多段组合
- `5-`    第 5 帧到末尾
- `-5`    开头到第 5 帧
- `7-3`   逆序（倒放该段）
- 留空 / `all`  全部
分隔符支持 `,` `，` `、` `;` 空格换行。

两个节点：
- RespectSelectFrames：对 IMAGE 批次（帧）选取子集 → IMAGE（可接 Load Video / Video Combine 生态）
- RespectTrimVideoFile：对 mp4 文件按帧裁成新 mp4（用 cv2 或 imageio，无音轨）
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid
from typing import Any, Optional

import torch

from .utils import _comfy_output_base

CATEGORY = "Respect"


# ---------------------------------------------------------------------------
# 帧号解析
# ---------------------------------------------------------------------------


def parse_frame_spec(spec: str, total: int, one_based: bool = True) -> list[int]:
    """把帧号写法解析成 0-based 索引列表（保持书写顺序，允许重复/逆序，越界丢弃）。"""
    s = (spec or "").strip().lower()
    if total <= 0:
        return []
    if s in ("", "all", "*"):
        return list(range(total))

    s = re.sub(r"[，、;；\s]+", ",", s)
    base = 1 if one_based else 0
    last = total if one_based else total - 1  # 用户语义里的“末帧”

    raw: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if part.startswith("-"):            # -b : 从头到 b
                a, b = base, int(part[1:])
            elif part.endswith("-"):            # a- : a 到末尾
                a, b = int(part[:-1]), last
            elif "-" in part:                   # a-b
                sa, sb = part.split("-", 1)
                a, b = int(sa), int(sb)
            else:                               # 单帧
                a = b = int(part)
        except ValueError:
            continue
        step = 1 if a <= b else -1
        raw.extend(range(a, b + step, step))

    out: list[int] = []
    for v in raw:
        idx = v - 1 if one_based else v
        if 0 <= idx < total:
            out.append(idx)
    return out


# ---------------------------------------------------------------------------
# IMAGE 批次帧选择
# ---------------------------------------------------------------------------


class RespectSelectFrames:
    """从 IMAGE 批次（帧序列）按帧号选取子集，输出 IMAGE 批次。

    `select` 支持 1-10 / 3-7 / 3,7 / 1-1 / 1-3,8-10 / 5- / -5 / 7-3（逆序）/ 留空=全部。
    """

    DESCRIPTION = (
        "对帧序列(IMAGE)按帧号选取。select 写法：1-10 连续 / 3,7 单帧 / 1-3,8-10 组合 / "
        "5- 到末尾 / -5 从头 / 7-3 逆序 / 留空=全部。删首帧填 2-。one_based=第1帧记作1。"
    )

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "frames": ("IMAGE", {"tooltip": "输入帧序列（IMAGE 批次）"}),
                "select": ("STRING", {"default": "", "multiline": False,
                                       "placeholder": "如 1-10 或 3,7 或 1-3,8-10 或 5- ；留空=全部",
                                       "tooltip": "帧号：1-10/3,7/5-(到末尾)/-5(从头)/7-3(逆序)/留空=全部。删首帧填 2-"}),
                "one_based": ("BOOLEAN", {"default": True, "tooltip": "开=第1帧记作1；关=从0起"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "STRING")
    RETURN_NAMES = ("frames", "count", "indices")
    FUNCTION = "select_frames"
    CATEGORY = CATEGORY

    def select_frames(self, frames: torch.Tensor, select: str = "", one_based: bool = True):
        if frames is None or frames.ndim < 3:
            raise ValueError("frames 不是有效的 IMAGE 批次")
        if frames.ndim == 3:
            frames = frames.unsqueeze(0)
        total = frames.shape[0]
        idxs = parse_frame_spec(select, total, one_based)
        if not idxs:
            raise ValueError(f"帧选择结果为空（共 {total} 帧，select={select!r}）")
        index_tensor = torch.tensor(idxs, dtype=torch.long, device=frames.device)
        out = frames.index_select(0, index_tensor)
        shown = ",".join(str(i + 1 if one_based else i) for i in idxs)
        print(f"[Respect] 帧选择: 共 {total} 帧 -> 取 {len(idxs)} 帧 [{shown}]")
        return (out, len(idxs), shown)


# ---------------------------------------------------------------------------
# 视频文件按帧裁剪（cv2 / imageio）
# ---------------------------------------------------------------------------


def _resolve_out_path(save_dir: str, filename: str, prefix: str = "trim", ext: str = ".mp4") -> str:
    save_dir = (save_dir or "").strip().strip('"')
    if save_dir:
        save_dir = os.path.expanduser(os.path.expandvars(save_dir))
        target_dir = save_dir if os.path.isabs(save_dir) else os.path.join(_comfy_output_base(), save_dir)
    else:
        target_dir = os.path.join(_comfy_output_base(), "respect")
    os.makedirs(target_dir, exist_ok=True)
    filename = (filename or "").strip()
    if filename:
        if not os.path.splitext(filename)[1]:
            filename += ext
    else:
        filename = f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}{ext}"
    return os.path.join(target_dir, filename)


def _trim_with_cv2(path: str, select: str, one_based: bool, out_fps: float, out_path: str) -> Optional[int]:
    try:
        import cv2
    except ImportError:
        return None
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError(f"无法打开视频: {path}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    fps0 = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    # total 不可靠时先粗读一遍算帧数
    if total <= 0:
        total = 0
        while True:
            ok, _ = cap.read()
            if not ok:
                break
            total += 1
        cap.release()
        cap = cv2.VideoCapture(path)

    idxs = parse_frame_spec(select, total, one_based)
    if not idxs:
        cap.release()
        raise ValueError(f"帧选择结果为空（共 {total} 帧，select={select!r}）")

    need = set(idxs)
    max_need = max(need)
    cache: dict[int, Any] = {}
    i = 0
    while i <= max_need:
        ok, frame = cap.read()
        if not ok:
            break
        if i in need:
            cache[i] = frame
        i += 1
    cap.release()

    fps = out_fps if out_fps and out_fps > 0 else fps0
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    written = 0
    for idx in idxs:  # 按书写顺序（可逆序/重复）
        f = cache.get(idx)
        if f is not None:
            writer.write(f)
            written += 1
    writer.release()
    return written


def _trim_with_imageio(path: str, select: str, one_based: bool, out_fps: float, out_path: str) -> Optional[int]:
    try:
        import imageio.v2 as imageio
    except ImportError:
        try:
            import imageio  # type: ignore
        except ImportError:
            return None
    reader = imageio.get_reader(path)
    meta = reader.get_meta_data()
    fps0 = float(meta.get("fps", 30.0) or 30.0)
    try:
        total = reader.count_frames()
    except Exception:
        total = len(list(reader))  # 兜底
        reader = imageio.get_reader(path)
    idxs = parse_frame_spec(select, total, one_based)
    if not idxs:
        reader.close()
        raise ValueError(f"帧选择结果为空（共 {total} 帧，select={select!r}）")

    need = set(idxs)
    max_need = max(need)
    cache: dict[int, Any] = {}
    for i, frame in enumerate(reader):
        if i in need:
            cache[i] = frame
        if i >= max_need:
            break
    reader.close()

    fps = out_fps if out_fps and out_fps > 0 else fps0
    writer = imageio.get_writer(out_path, fps=fps, macro_block_size=None)
    written = 0
    for idx in idxs:
        f = cache.get(idx)
        if f is not None:
            writer.append_data(f)
            written += 1
    writer.close()
    return written


def _transcode_to_h264(path: str) -> bool:
    """把视频转成 H.264 + yuv420p（浏览器/ComfyUI 预览兼容），无 ffmpeg 则跳过。

    cv2 写出的是 mpeg4(Simple Profile)，很多预览器会黑屏/0:00，转 H.264 后正常。
    """
    ff = _find_ffmpeg()
    if not ff:
        return False
    tmp = path + ".h264.mp4"
    ok, _err = _run_ffmpeg([ff, "-y", "-i", path, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", "-an", tmp])
    if ok and os.path.isfile(tmp):
        try:
            os.replace(tmp, path)
            return True
        except Exception:
            pass
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except Exception:
        pass
    return False


class RespectTrimVideoFile:
    """把 mp4 文件按帧号裁成新 mp4（无音轨）。用 cv2 或 imageio，任装其一。

    `video_path` 可接上游视频节点的 local_path。`select` 写法同帧选择节点。
    `out_fps=0` 表示沿用原视频帧率。有 ffmpeg 时会转 H.264 以便预览。
    """

    DESCRIPTION = (
        "把 mp4 按帧号裁成新 mp4（无音轨）。select 写法同帧选择：1-100/30-90/1-10,50-60/"
        "5-(到末尾)/2-(删首帧)/留空=全部。装了 ffmpeg 会自动转 H.264，避免预览黑屏。"
    )

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "video_path": ("STRING", {"default": "", "multiline": False, "forceInput": True, "tooltip": "输入 mp4 路径（接上游 local_path）"}),
                "select": ("STRING", {"default": "", "multiline": False,
                                       "placeholder": "如 1-100 或 30-90 或 1-10,50-60 ；留空=全部",
                                       "tooltip": "帧号：1-100/30-90/2-(删首帧)/留空=全部"}),
                "one_based": ("BOOLEAN", {"default": True, "tooltip": "开=第1帧记作1"}),
            },
            "optional": {
                "out_fps": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 240.0, "step": 1.0, "tooltip": "输出帧率；0=沿用原视频"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect", "tooltip": "输出目录"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳", "tooltip": "输出文件名"}),
            },
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("local_path", "count")
    FUNCTION = "trim"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def trim(self, video_path: str, select: str = "", one_based: bool = True,
             out_fps: float = 0.0, save_dir: str = "", filename: str = ""):
        path = (video_path or "").strip().strip('"')
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(f"找不到视频文件: {path}")
        out_path = _resolve_out_path(save_dir, filename)

        written = _trim_with_cv2(path, select, one_based, out_fps, out_path)
        if written is None:
            written = _trim_with_imageio(path, select, one_based, out_fps, out_path)
        if written is None:
            raise RuntimeError(
                "未安装视频处理库，请在 ComfyUI 的 Python 任装其一：\n"
                "  pip install opencv-python\n"
                "  pip install imageio imageio-ffmpeg"
            )
        # cv2 写出的是 mpeg4(SP)，预览常黑屏 → 转 H.264（有 ffmpeg 时）
        if _transcode_to_h264(out_path):
            print(f"[Respect] 视频裁剪: {written} 帧 -> {out_path}（已转 H.264）")
        else:
            print(f"[Respect] 视频裁剪: {written} 帧 -> {out_path}（未转码，若预览黑屏请装 imageio-ffmpeg）")
        return (out_path, written)


# ---------------------------------------------------------------------------
# 视频拼接（任意个 mp4 → 一个 mp4）
# ---------------------------------------------------------------------------


def _concat_with_cv2(paths: list[str], out_fps: float, out_path: str) -> Optional[int]:
    try:
        import cv2
    except ImportError:
        return None
    cap0 = cv2.VideoCapture(paths[0])
    if not cap0.isOpened():
        raise ValueError(f"无法打开视频: {paths[0]}")
    w = int(cap0.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap0.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps0 = cap0.get(cv2.CAP_PROP_FPS) or 30.0
    cap0.release()

    fps = out_fps if out_fps and out_fps > 0 else fps0
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    written = 0
    for p in paths:
        cap = cv2.VideoCapture(p)
        if not cap.isOpened():
            print(f"[Respect] 跳过无法打开的视频: {p}")
            continue
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame.shape[1] != w or frame.shape[0] != h:
                frame = cv2.resize(frame, (w, h))
            writer.write(frame)
            written += 1
        cap.release()
    writer.release()
    return written


def _concat_with_imageio(paths: list[str], out_fps: float, out_path: str) -> Optional[int]:
    try:
        import imageio.v2 as imageio
    except ImportError:
        try:
            import imageio  # type: ignore
        except ImportError:
            return None
    import numpy as np

    r0 = imageio.get_reader(paths[0])
    fps0 = float(r0.get_meta_data().get("fps", 30.0) or 30.0)
    first = None
    for fr in r0:
        first = fr
        break
    r0.close()
    if first is None:
        raise ValueError(f"首个视频无帧: {paths[0]}")
    th, tw = first.shape[0], first.shape[1]

    fps = out_fps if out_fps and out_fps > 0 else fps0
    writer = imageio.get_writer(out_path, fps=fps, macro_block_size=None)
    written = 0
    for p in paths:
        try:
            rd = imageio.get_reader(p)
        except Exception as exc:
            print(f"[Respect] 跳过无法打开的视频 {p}: {exc}")
            continue
        for fr in rd:
            if fr.shape[0] != th or fr.shape[1] != tw:
                from PIL import Image
                fr = np.asarray(Image.fromarray(fr).resize((tw, th)))
            writer.append_data(fr)
            written += 1
        rd.close()
    writer.close()
    return written


# --- ffmpeg 拼接（保留音轨 / 无损快速）--------------------------------------


def _find_ffmpeg() -> Optional[str]:
    """优先用 imageio-ffmpeg 自带的 ffmpeg，其次系统 PATH 里的 ffmpeg。"""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return shutil.which("ffmpeg")


def _probe_video(path: str) -> Optional[tuple[int, int, float]]:
    """用 cv2 / imageio 探测第一个视频的 (宽, 高, fps)，都没有则返回 None。"""
    try:
        import cv2
        cap = cv2.VideoCapture(path)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            cap.release()
            if w > 0 and h > 0:
                return (w, h, fps)
    except Exception:
        pass
    try:
        import imageio.v2 as imageio
    except ImportError:
        try:
            import imageio  # type: ignore
        except ImportError:
            return None
    try:
        r = imageio.get_reader(path)
        meta = r.get_meta_data()
        fps = float(meta.get("fps", 30.0) or 30.0)
        size = meta.get("size")
        if size:
            w, h = int(size[0]), int(size[1])
        else:
            fr = None
            for fr in r:
                break
            h, w = (fr.shape[0], fr.shape[1]) if fr is not None else (0, 0)
        r.close()
        if w > 0 and h > 0:
            return (w, h, fps)
    except Exception:
        pass
    return None


def _run_ffmpeg(cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as exc:
        return False, str(exc)
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", "ignore")[-600:]
        return False, tail
    return True, ""


def _ffmpeg_concat_copy(ff: str, paths: list[str], out_path: str) -> tuple[bool, str]:
    """concat 解复用器 + -c copy：无损、快、保音轨，但要求各片编码/参数一致。"""
    list_path = out_path + ".concat.txt"
    try:
        with open(list_path, "w", encoding="utf-8") as f:
            for p in paths:
                safe = os.path.abspath(p).replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{safe}'\n")
        cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", out_path]
        return _run_ffmpeg(cmd)
    finally:
        try:
            os.remove(list_path)
        except Exception:
            pass


def _ffmpeg_concat_reencode(ff: str, paths: list[str], out_path: str,
                            w: int, h: int, fps: float, with_audio: bool) -> tuple[bool, str]:
    """concat 滤镜：缩放/补边对齐到 WxH+fps，重编码 H.264(+AAC)，可保音轨。"""
    n = len(paths)
    vscale = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
              f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:g},format=yuv420p")
    parts: list[str] = []
    concat_inputs = ""
    for i in range(n):
        parts.append(f"[{i}:v]{vscale}[v{i}]")
        if with_audio:
            parts.append(f"[{i}:a]aresample=async=1[a{i}]")
        concat_inputs += f"[v{i}]" + (f"[a{i}]" if with_audio else "")
    if with_audio:
        parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[v][a]")
        maps = ["-map", "[v]", "-map", "[a]", "-c:a", "aac"]
    else:
        parts.append(f"{concat_inputs}concat=n={n}:v=1:a=0[v]")
        maps = ["-map", "[v]"]
    cmd = [ff, "-y"]
    for p in paths:
        cmd += ["-i", p]
    cmd += ["-filter_complex", ";".join(parts)] + maps + ["-c:v", "libx264", "-pix_fmt", "yuv420p", out_path]
    return _run_ffmpeg(cmd)


CONCAT_MODES = ["auto", "copy(无损保音轨)", "reencode(缩放保音轨)", "frames(逐帧无音轨)"]
CONCAT_BGM_STAGES = ["none", "after_merge(合并后加)", "per_video(每个视频各加)"]
_CONCAT_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi")


class RespectConcatVideos:
    """把任意个 mp4 按顺序拼接成一个 mp4。

    顺序 = `video_1..video_8`（非空的，接各视频节点的 local_path）+ `extra_paths`（每行一个路径，数量不限）。

    mode：
    - auto（默认）：有 ffmpeg → reencode 保音轨（缩放对齐，最稳）；否则逐帧无音轨
    - copy(无损保音轨)：ffmpeg 无损快速拼接，要求各片编码/尺寸/帧率一致
    - reencode(缩放保音轨)：ffmpeg 缩放对齐 + 重编码 + 保音轨（缺音轨的会自动回退无音轨）
    - frames(逐帧无音轨)：cv2/imageio 逐帧，无音轨（无需 ffmpeg）

    `out_fps` / `width` / `height` = 0 表示按第一个视频自动取。
    """

    DESCRIPTION = (
        "把多个 mp4 顺序拼接。顺序=video_1..8(接各视频节点 local_path)+extra_paths(每行一个)。"
        "mode：auto(有ffmpeg→保音轨重编码)/copy(无损快,需同参)/reencode(缩放保音轨)/frames(无音轨)。"
    )

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        optional = {f"video_{i + 1}": ("STRING", {"default": "", "forceInput": True, "tooltip": f"第{i+1}个视频路径（接 local_path）"}) for i in range(8)}
        optional.update({
            "folder": ("STRING", {"default": "", "multiline": False, "placeholder": "可选：读取该文件夹内所有视频(按名排序)", "tooltip": "填分镜的 03_videos/<scene> 即可整批拼接"}),
            "extra_paths": ("STRING", {"default": "", "multiline": True, "placeholder": "追加视频路径，每行一个（数量不限）", "tooltip": "超过8个时每行填一个路径"}),
            "mode": (CONCAT_MODES, {"default": "auto", "tooltip": "auto=保音轨重编码；copy=无损快(需同参)；frames=无音轨无需ffmpeg"}),
            "keep_audio": ("BOOLEAN", {"default": True, "tooltip": "reencode/auto 时是否保留音轨"}),
            "bgm_audio": ("STRING", {"default": "", "multiline": False, "placeholder": "可选：BGM 音频路径", "tooltip": "填了才加 BGM，配合 bgm_stage"}),
            "bgm_stage": (CONCAT_BGM_STAGES, {"default": "none", "tooltip": "none=不加；after_merge=合并后统一加；per_video=每个视频各加再合并"}),
            "bgm_mode": (["mix(叠加原声)", "replace(替换原声)"], {"default": "mix(叠加原声)", "tooltip": "叠加或替换原声"}),
            "bgm_volume": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 8.0, "step": 0.1, "tooltip": "BGM 音量倍数"}),
            "out_fps": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 240.0, "step": 1.0}),
            "width": ("INT", {"default": 0, "min": 0, "max": 8192}),
            "height": ("INT", {"default": 0, "min": 0, "max": 8192}),
            "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect"}),
            "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳"}),
        })
        return {"required": {}, "optional": optional}

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("local_path", "clip_count")
    FUNCTION = "concat"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def concat(self, folder: str = "", extra_paths: str = "", mode: str = "auto", keep_audio: bool = True,
               bgm_audio: str = "", bgm_stage: str = "none", bgm_mode: str = "mix(叠加原声)", bgm_volume: float = 1.0,
               out_fps: float = 0.0, width: int = 0, height: int = 0,
               save_dir: str = "", filename: str = "", **kwargs):
        paths: list[str] = []
        # 文件夹优先（按文件名排序）
        folder = (folder or "").strip().strip('"')
        if folder:
            fdir = os.path.expanduser(os.path.expandvars(folder))
            if not os.path.isabs(fdir):
                fdir = os.path.join(_comfy_output_base(), fdir)
            if os.path.isdir(fdir):
                for fn in sorted(os.listdir(fdir)):
                    if fn.lower().endswith(_CONCAT_VIDEO_EXTS):
                        paths.append(os.path.join(fdir, fn))
        for i in range(8):
            v = kwargs.get(f"video_{i + 1}")
            if v:
                paths.append(str(v).strip().strip('"'))
        for line in (extra_paths or "").splitlines():
            line = line.strip().strip('"')
            if line:
                paths.append(line)
        paths = [p for p in paths if p]

        missing = [p for p in paths if not os.path.isfile(p)]
        if missing:
            raise FileNotFoundError(f"以下视频不存在: {missing}")
        if not paths:
            raise ValueError("没有可拼接的视频（请连 video_1.. / 填 folder / extra_paths）")

        # per_video：先给每个视频各加 BGM
        bgm_audio = (bgm_audio or "").strip().strip('"')
        stage = bgm_stage.split("(")[0]
        bmode = bgm_mode.split("(")[0]
        ff_bgm = _find_ffmpeg()
        if stage == "per_video" and bgm_audio and os.path.isfile(bgm_audio) and ff_bgm:
            new_paths = []
            for p in paths:
                tmp = os.path.join(_comfy_output_base(), "respect", f"bgmtmp_{uuid.uuid4().hex[:8]}.mp4")
                os.makedirs(os.path.dirname(tmp), exist_ok=True)
                ok, _e = _add_bgm_ffmpeg(ff_bgm, p, bgm_audio, tmp, mode=bmode,
                                         bgm_volume=bgm_volume, original_volume=1.0, loop_bgm=True)
                new_paths.append(tmp if ok and os.path.isfile(tmp) else p)
            paths = new_paths

        out_path = _resolve_out_path(save_dir, filename, prefix="concat")
        key = mode.split("(")[0]
        ff = _find_ffmpeg() if key in ("auto", "copy", "reencode") else None

        def _run_concat():
            if key == "copy":
                if not ff:
                    raise RuntimeError("copy 模式需要 ffmpeg（可 pip install imageio-ffmpeg）")
                ok, err = _ffmpeg_concat_copy(ff, paths, out_path)
                if not ok:
                    raise RuntimeError(f"ffmpeg copy 拼接失败（各片参数可能不一致，试试 reencode）：{err}")
                print(f"[Respect] 视频拼接(copy 无损): {len(paths)} 个 -> {out_path}")
                return
            if key == "reencode" or (key == "auto" and ff):
                if not ff:
                    raise RuntimeError("reencode 模式需要 ffmpeg（可 pip install imageio-ffmpeg）")
                probe = _probe_video(paths[0]) or (1280, 720, 30.0)
                tw = width if width > 0 else probe[0]
                th = height if height > 0 else probe[1]
                tfps = out_fps if out_fps and out_fps > 0 else probe[2]
                ok, err = _ffmpeg_concat_reencode(ff, paths, out_path, tw, th, tfps, with_audio=keep_audio)
                if not ok and keep_audio:
                    print(f"[Respect] 带音轨拼接失败，回退无音轨重试：{err[:200]}")
                    ok, err = _ffmpeg_concat_reencode(ff, paths, out_path, tw, th, tfps, with_audio=False)
                if ok:
                    print(f"[Respect] 视频拼接(reencode {tw}x{th}@{tfps:g}, 音轨={keep_audio}): {len(paths)} 个 -> {out_path}")
                    return
                if key == "reencode":
                    raise RuntimeError(f"ffmpeg reencode 拼接失败：{err}")
                print(f"[Respect] ffmpeg 拼接失败，回退逐帧模式：{err[:200]}")
            written = _concat_with_cv2(paths, out_fps, out_path)
            if written is None:
                written = _concat_with_imageio(paths, out_fps, out_path)
            if written is None:
                raise RuntimeError(
                    "无可用后端：装 ffmpeg（pip install imageio-ffmpeg，可保音轨）"
                    "或 opencv-python / imageio（逐帧无音轨）任一即可"
                )
            print(f"[Respect] 视频拼接(逐帧无音轨): {len(paths)} 个 -> {written} 帧 -> {out_path}")

        _run_concat()

        # after_merge：合并后统一加 BGM
        if stage == "after_merge" and bgm_audio and os.path.isfile(bgm_audio) and ff_bgm:
            final = out_path + ".bgm.mp4"
            ok, err = _add_bgm_ffmpeg(ff_bgm, out_path, bgm_audio, final, mode=bmode,
                                      bgm_volume=bgm_volume, original_volume=1.0, loop_bgm=True)
            if ok and os.path.isfile(final):
                os.replace(final, out_path)
                print(f"[Respect] 合并后加 BGM 完成 -> {out_path}")
            else:
                print(f"[Respect] 合并后加 BGM 失败，输出无 BGM：{err[:200]}")

        return (out_path, len(paths))


# ---------------------------------------------------------------------------
# 给视频加 BGM（背景音乐）
# ---------------------------------------------------------------------------


BGM_MODES = ["mix(叠加原声)", "replace(替换原声)"]


def _add_bgm_ffmpeg(ff: str, video: str, audio: str, out_path: str, *,
                    mode: str, bgm_volume: float, original_volume: float, loop_bgm: bool) -> tuple[bool, str]:
    cmd = [ff, "-y", "-i", video]
    if loop_bgm:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-i", audio]

    if mode == "mix":
        fc = (f"[1:a]volume={bgm_volume:g}[bgm];"
              f"[0:a]volume={original_volume:g}[org];"
              f"[org][bgm]amix=inputs=2:duration=first:dropout_transition=0[a]")
    else:  # replace
        fc = f"[1:a]volume={bgm_volume:g}[a]"

    cmd += ["-filter_complex", fc, "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-shortest", out_path]
    return _run_ffmpeg(cmd)


class RespectAddBGM:
    """给视频加背景音乐（BGM）。用 ffmpeg，视频不重编码（-c:v copy），快且无损。

    - `mode=mix`：BGM 叠加在原声上（保留人声/原音效）；原视频无音轨时自动退化为纯 BGM
    - `mode=replace`：用 BGM 替换原声
    - `loop_bgm`：BGM 比视频短就循环铺满；输出长度对齐视频（-shortest）
    - `bgm_volume` / `original_volume`：音量倍数（1.0 原样）
    需要 ffmpeg（pip install imageio-ffmpeg 即可，无需系统装）。
    """

    DESCRIPTION = (
        "给视频加背景音乐。mix=叠加原声(原视频无声时自动纯BGM)；replace=替换原声。"
        "loop_bgm=BGM 短则循环铺满，输出对齐视频长度。视频不重编码(-c:v copy)，快。需要 ffmpeg。"
    )

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "video_path": ("STRING", {"default": "", "multiline": False, "forceInput": True, "tooltip": "输入视频路径（接 local_path）"}),
                "audio_path": ("STRING", {"default": "", "multiline": False, "placeholder": "BGM 音频文件路径 mp3/wav/m4a/aac", "tooltip": "本地 BGM 音频文件路径"}),
                "mode": (BGM_MODES, {"default": "mix(叠加原声)", "tooltip": "mix=叠加原声；replace=替换原声"}),
                "bgm_volume": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 8.0, "step": 0.1, "tooltip": "BGM 音量倍数"}),
            },
            "optional": {
                "original_volume": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 8.0, "step": 0.1, "tooltip": "mix 时原声音量倍数"}),
                "loop_bgm": ("BOOLEAN", {"default": True, "tooltip": "BGM 比视频短时循环铺满"}),
                "save_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "保存目录：留空=output/respect", "tooltip": "输出目录"}),
                "filename": ("STRING", {"default": "", "multiline": False, "placeholder": "文件名：留空=自动加时间戳", "tooltip": "输出文件名"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("local_path",)
    FUNCTION = "add_bgm"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def add_bgm(self, video_path: str, audio_path: str, mode: str = "mix(叠加原声)",
                bgm_volume: float = 1.0, original_volume: float = 1.0, loop_bgm: bool = True,
                save_dir: str = "", filename: str = ""):
        video = (video_path or "").strip().strip('"')
        audio = (audio_path or "").strip().strip('"')
        if not video or not os.path.isfile(video):
            raise FileNotFoundError(f"找不到视频文件: {video}")
        if not audio or not os.path.isfile(audio):
            raise FileNotFoundError(f"找不到 BGM 音频文件: {audio}")

        ff = _find_ffmpeg()
        if not ff:
            raise RuntimeError("加 BGM 需要 ffmpeg（pip install imageio-ffmpeg 即可，无需系统装）")

        out_path = _resolve_out_path(save_dir, filename, prefix="bgm")
        key = mode.split("(")[0]  # mix / replace

        ok, err = _add_bgm_ffmpeg(ff, video, audio, out_path, mode=key,
                                  bgm_volume=bgm_volume, original_volume=original_volume, loop_bgm=loop_bgm)
        if not ok and key == "mix":
            # 原视频可能没有音轨，mix 失败 → 退化为纯 BGM(replace)
            print(f"[Respect] mix 失败（原视频可能无音轨），改用纯 BGM：{err[:200]}")
            ok, err = _add_bgm_ffmpeg(ff, video, audio, out_path, mode="replace",
                                      bgm_volume=bgm_volume, original_volume=original_volume, loop_bgm=loop_bgm)
        if not ok:
            raise RuntimeError(f"加 BGM 失败：{err}")
        print(f"[Respect] 已加 BGM({key}): {out_path}")
        return (out_path,)


NODE_CLASS_MAPPINGS = {
    "RespectSelectFrames": RespectSelectFrames,
    "RespectTrimVideoFile": RespectTrimVideoFile,
    "RespectConcatVideos": RespectConcatVideos,
    "RespectAddBGM": RespectAddBGM,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectSelectFrames": "Respect 帧选择裁剪 (IMAGE)",
    "RespectTrimVideoFile": "Respect 视频文件裁剪 (mp4)",
    "RespectConcatVideos": "Respect 视频拼接 (mp4)",
    "RespectAddBGM": "Respect 视频加BGM (mp4)",
}
