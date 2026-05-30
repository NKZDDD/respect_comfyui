"""Respect ComfyUI 扩展 - 基础加载模块。

从一个 ZIP 包里按批次取图片 / 视频，支持四种取样模式：
- increment 递增：每次运行往后取一批（跨执行累加，自动回绕）
- decrement 递减：每次运行往前取一批（跨执行递减，自动回绕）
- random 随机：每次随机取一批
- fixed 固定：始终从 index 开始取同一批

把 .zip 放到 ComfyUI/input 目录后在下拉里选；也可以用 zip_path 直接填绝对路径。
"""

from __future__ import annotations

import os
import random
import re
import time
import zipfile
from typing import Any, Optional

import torch

from .utils import bytes_to_tensor, tensors_concat, _comfy_output_base

try:
    import folder_paths  # type: ignore
except Exception:  # pragma: no cover
    folder_paths = None

# 新版 ComfyUI 提供 VIDEO 类型；不可用时视频节点只输出路径字符串。
try:
    from comfy_api.input_impl import VideoFromFile  # type: ignore

    _HAS_VIDEO_TYPE = True
except Exception:  # pragma: no cover
    try:
        from comfy_api.input_impl.video_types import VideoFromFile  # type: ignore

        _HAS_VIDEO_TYPE = True
    except Exception:
        VideoFromFile = None  # type: ignore
        _HAS_VIDEO_TYPE = False


CATEGORY = "Respect"

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff")
VIDEO_EXTS = (".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi", ".flv", ".wmv")
SAMPLE_MODES = ["increment", "decrement", "random", "fixed"]
SORT_MODES = ["natural", "name", "name_desc", "none"]

# 跨执行的取样指针，按节点 unique_id + 配置 key 保存
_ITER_STATE: dict[str, dict] = {}


def _input_dir() -> str:
    if folder_paths is not None:
        return folder_paths.get_input_directory()
    return os.path.join(os.getcwd(), "input")


def _list_input_zips() -> list[str]:
    base = _input_dir()
    try:
        names = [f for f in os.listdir(base) if f.lower().endswith(".zip")]
    except Exception:
        names = []
    return sorted(names)


def _resolve_zip_path(zip_file: str, zip_path: str) -> str:
    zip_path = (zip_path or "").strip().strip('"')
    if zip_path:
        zip_path = os.path.expanduser(os.path.expandvars(zip_path))
        if os.path.isabs(zip_path):
            return zip_path
        return os.path.join(_input_dir(), zip_path)
    return os.path.join(_input_dir(), zip_file or "")


_NUM_RE = re.compile(r"(\d+)")


def _natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in _NUM_RE.split(s)]


def _sort_entries(names: list[str], sort_mode: str) -> list[str]:
    if sort_mode == "none":
        return names
    if sort_mode == "name":
        return sorted(names)
    if sort_mode == "name_desc":
        return sorted(names, reverse=True)
    # natural
    return sorted(names, key=_natural_key)


def _list_zip_entries(zf: zipfile.ZipFile, exts: tuple, recursive: bool, sort_mode: str) -> list[str]:
    out = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename
        base = os.path.basename(name)
        # 跳过 mac 资源叉与隐藏文件
        if base.startswith(".") or "__MACOSX" in name:
            continue
        # 非递归时只取根目录文件
        if not recursive and ("/" in name.strip("/")):
            continue
        if name.lower().endswith(exts):
            out.append(name)
    return _sort_entries(out, sort_mode)


def _pick_indices(
    total: int,
    batch_size: int,
    mode: str,
    index: int,
    seed: int,
    state_key: str,
    unique_id: Optional[str],
) -> list[int]:
    if total <= 0:
        return []
    batch_size = max(1, int(batch_size))

    if mode == "random":
        rng = random.Random()
        if seed:
            rng.seed(seed)
        if batch_size >= total:
            picks = list(range(total))
            rng.shuffle(picks)
            return picks
        return rng.sample(range(total), batch_size)

    if mode == "fixed":
        start = int(index) % total
        return [(start + i) % total for i in range(batch_size)]

    # increment / decrement：跨执行累加 / 递减
    skey = f"{unique_id}"
    base_key = f"{state_key}|mode={mode}|idx={index}|bs={batch_size}"
    st = _ITER_STATE.get(skey)
    if st is None or st.get("key") != base_key:
        st = {"key": base_key, "pos": int(index) % total}
        _ITER_STATE[skey] = st
    start = st["pos"]

    if mode == "decrement":
        picks = [(start - i) % total for i in range(batch_size)]
        st["pos"] = (start - batch_size) % total
    else:  # increment
        picks = [(start + i) % total for i in range(batch_size)]
        st["pos"] = (start + batch_size) % total
    return picks


def _changed_token(mode: str, kwargs: dict) -> Any:
    if mode in ("increment", "decrement", "random"):
        return float("nan")
    return "|".join(
        str(kwargs.get(k)) for k in ("zip_file", "zip_path", "index", "batch_size", "sort", "recursive")
    )


class RespectLoadImagesFromZip:
    """从 ZIP 包按批次取图片，输出 IMAGE 批次。"""

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        zips = _list_input_zips()
        zip_widget = zips if zips else ["(把 .zip 放到 ComfyUI/input 再刷新)"]
        return {
            "required": {
                "zip_file": (zip_widget,),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 256}),
                "mode": (SAMPLE_MODES, {"default": "increment"}),
                "index": ("INT", {"default": 0, "min": 0, "max": 0xffffffff}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "sort": (SORT_MODES, {"default": "natural"}),
                "recursive": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "zip_path": ("STRING", {"default": "", "multiline": False, "placeholder": "可选：绝对路径或相对 input 的路径，填了优先于上方下拉"}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("IMAGE", "STRING", "INT")
    RETURN_NAMES = ("images", "filenames", "count")
    FUNCTION = "load"
    CATEGORY = CATEGORY

    @classmethod
    def IS_CHANGED(cls, mode="increment", **kwargs):
        return _changed_token(mode, kwargs)

    def load(
        self,
        zip_file: str,
        batch_size: int,
        mode: str,
        index: int,
        seed: int,
        sort: str = "natural",
        recursive: bool = True,
        zip_path: str = "",
        unique_id: Optional[str] = None,
    ) -> tuple[torch.Tensor, str, int]:
        path = _resolve_zip_path(zip_file, zip_path)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"找不到 ZIP 文件: {path}")

        with zipfile.ZipFile(path, "r") as zf:
            entries = _list_zip_entries(zf, IMAGE_EXTS, recursive, sort)
            if not entries:
                raise ValueError(f"ZIP 内没有图片文件: {path}")

            idxs = _pick_indices(
                total=len(entries),
                batch_size=batch_size,
                mode=mode,
                index=index,
                seed=seed,
                state_key=path,
                unique_id=unique_id,
            )

            tensors: list[torch.Tensor] = []
            picked_names: list[str] = []
            for i in idxs:
                name = entries[i]
                try:
                    data = zf.read(name)
                    tensors.append(bytes_to_tensor(data))
                    picked_names.append(name)
                except Exception as exc:
                    print(f"[Respect] 读取图片失败 {name}: {exc}")

        if not tensors:
            raise ValueError("没有成功读取任何图片")

        batch = tensors_concat(tensors)
        print(f"[Respect] 从 ZIP 取出 {len(picked_names)} 张图片 (mode={mode}): {picked_names}")
        return (batch, "\n".join(picked_names), len(picked_names))


class RespectLoadVideosFromZip:
    """从 ZIP 包按批次取视频，解压到 output 目录并输出本地路径。

    新版 ComfyUI 可用时额外输出 VIDEO 类型，可直接接 SaveVideo / 预览。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        zips = _list_input_zips()
        zip_widget = zips if zips else ["(把 .zip 放到 ComfyUI/input 再刷新)"]
        return {
            "required": {
                "zip_file": (zip_widget,),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 256}),
                "mode": (SAMPLE_MODES, {"default": "increment"}),
                "index": ("INT", {"default": 0, "min": 0, "max": 0xffffffff}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "sort": (SORT_MODES, {"default": "natural"}),
                "recursive": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "zip_path": ("STRING", {"default": "", "multiline": False, "placeholder": "可选：绝对路径或相对 input 的路径，填了优先于上方下拉"}),
                "extract_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "解压目录：留空=output/respect_zip，支持绝对路径"}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    if _HAS_VIDEO_TYPE:
        RETURN_TYPES = ("VIDEO", "STRING", "STRING", "INT")
        RETURN_NAMES = ("video", "video_paths", "first_video", "count")
    else:
        RETURN_TYPES = ("STRING", "STRING", "INT")
        RETURN_NAMES = ("video_paths", "first_video", "count")
    FUNCTION = "load"
    CATEGORY = CATEGORY

    @classmethod
    def IS_CHANGED(cls, mode="increment", **kwargs):
        return _changed_token(mode, kwargs)

    def _extract_target(self, extract_dir: str) -> str:
        extract_dir = (extract_dir or "").strip().strip('"')
        if extract_dir:
            extract_dir = os.path.expanduser(os.path.expandvars(extract_dir))
            target = extract_dir if os.path.isabs(extract_dir) else os.path.join(_comfy_output_base(), extract_dir)
        else:
            target = os.path.join(_comfy_output_base(), "respect_zip")
        os.makedirs(target, exist_ok=True)
        return target

    def load(
        self,
        zip_file: str,
        batch_size: int,
        mode: str,
        index: int,
        seed: int,
        sort: str = "natural",
        recursive: bool = True,
        zip_path: str = "",
        extract_dir: str = "",
        unique_id: Optional[str] = None,
    ):
        path = _resolve_zip_path(zip_file, zip_path)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"找不到 ZIP 文件: {path}")

        target_dir = self._extract_target(extract_dir)

        with zipfile.ZipFile(path, "r") as zf:
            entries = _list_zip_entries(zf, VIDEO_EXTS, recursive, sort)
            if not entries:
                raise ValueError(f"ZIP 内没有视频文件: {path}")

            idxs = _pick_indices(
                total=len(entries),
                batch_size=batch_size,
                mode=mode,
                index=index,
                seed=seed,
                state_key=path,
                unique_id=unique_id,
            )

            out_paths: list[str] = []
            for i in idxs:
                name = entries[i]
                try:
                    data = zf.read(name)
                    safe_name = os.path.basename(name)
                    if not safe_name:
                        continue
                    out_path = os.path.join(target_dir, safe_name)
                    if os.path.exists(out_path):
                        stem, ext = os.path.splitext(safe_name)
                        out_path = os.path.join(target_dir, f"{stem}_{time.strftime('%H%M%S')}{ext}")
                    with open(out_path, "wb") as f:
                        f.write(data)
                    out_paths.append(out_path)
                except Exception as exc:
                    print(f"[Respect] 解压视频失败 {name}: {exc}")

        if not out_paths:
            raise ValueError("没有成功解压任何视频")

        print(f"[Respect] 从 ZIP 取出 {len(out_paths)} 个视频 (mode={mode})")
        paths_str = "\n".join(out_paths)

        if _HAS_VIDEO_TYPE:
            try:
                video_obj = VideoFromFile(out_paths[0])  # type: ignore
            except Exception as exc:
                print(f"[Respect] 构造 VIDEO 对象失败，仅返回路径: {exc}")
                video_obj = None
            return (video_obj, paths_str, out_paths[0], len(out_paths))
        return (paths_str, out_paths[0], len(out_paths))


NODE_CLASS_MAPPINGS = {
    "RespectLoadImagesFromZip": RespectLoadImagesFromZip,
    "RespectLoadVideosFromZip": RespectLoadVideosFromZip,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectLoadImagesFromZip": "Respect ZIP批量加载图片",
    "RespectLoadVideosFromZip": "Respect ZIP批量加载视频",
}
