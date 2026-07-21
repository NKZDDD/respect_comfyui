"""Respect ComfyUI 扩展 - 预览节点。

- RespectPreviewImage：查看图像，直接在节点里显示 IMAGE。
- RespectPreviewVideo：查看视频，配合 web/respect_preview.js 在节点里渲染 <video> 播放。
"""

from __future__ import annotations

import os
import random
import shutil
from typing import Any, Optional

import numpy as np
from PIL import Image

try:
    import folder_paths  # type: ignore
except Exception:  # pragma: no cover
    folder_paths = None


CATEGORY = "Respect"

VIDEO_EXTS = (".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi", ".flv", ".wmv", ".gif")


def _rand_suffix(n: int = 5) -> str:
    return "".join(random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(n))


class RespectPreviewImage:
    """查看图像：把 IMAGE 保存到 temp 目录并在节点内预览（行为同核心 PreviewImage）。"""

    def __init__(self):
        self.output_dir = folder_paths.get_temp_directory() if folder_paths else os.path.join(os.getcwd(), "temp")
        self.type = "temp"
        self.prefix_append = "_respect_" + _rand_suffix()

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "images": ("IMAGE",),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ()
    FUNCTION = "preview"
    OUTPUT_NODE = True
    CATEGORY = CATEGORY

    def preview(self, images, prompt=None, extra_pnginfo=None):
        if folder_paths is None:
            return {"ui": {"images": []}}

        filename_prefix = "respect" + self.prefix_append
        full_output_folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
            filename_prefix, self.output_dir, images[0].shape[1], images[0].shape[0]
        )
        results = []
        for batch_number, image in enumerate(images):
            arr = (255.0 * image.cpu().numpy()).clip(0, 255).astype(np.uint8)
            img = Image.fromarray(arr)
            file = f"{filename}_{counter:05}_.png"
            img.save(os.path.join(full_output_folder, file), compress_level=4)
            results.append({"filename": file, "subfolder": subfolder, "type": self.type})
            counter += 1
        return {"ui": {"images": results}}


def _to_view_ref(path: str) -> Optional[dict]:
    """把本地视频绝对路径转换成 ComfyUI /view 可访问的引用。

    若文件已在 output/input/temp 目录下，直接引用；否则复制到 output/respect_preview。
    """
    if folder_paths is None:
        return None
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return None

    candidates = [
        ("output", folder_paths.get_output_directory()),
        ("input", folder_paths.get_input_directory()),
        ("temp", folder_paths.get_temp_directory()),
    ]
    for type_name, base in candidates:
        base = os.path.abspath(base)
        if path == base or path.startswith(base + os.sep):
            rel = os.path.relpath(path, base)
            subfolder = os.path.dirname(rel).replace("\\", "/")
            return {"filename": os.path.basename(rel), "subfolder": subfolder, "type": type_name}

    # 不在标准目录里，复制一份到 output/respect_preview
    dst_dir = os.path.join(folder_paths.get_output_directory(), "respect_preview")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(path))
    try:
        if os.path.abspath(dst) != path:
            shutil.copy2(path, dst)
    except Exception as exc:
        print(f"[Respect] 复制视频到预览目录失败: {exc}")
        return None
    return {"filename": os.path.basename(path), "subfolder": "respect_preview", "type": "output"}


class RespectPreviewVideo:
    """查看视频：输入本地视频路径（或 video_paths 多行），在节点内渲染播放器。"""

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "video_path": ("STRING", {"default": "", "multiline": False, "forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_path",)
    FUNCTION = "preview"
    OUTPUT_NODE = True
    CATEGORY = CATEGORY

    def preview(self, video_path: str):
        raw = (video_path or "").strip()
        if not raw:
            return {"ui": {"videos": []}, "result": ("",)}

        # 支持多行（取第一行非空）
        first = ""
        for line in raw.splitlines():
            line = line.strip().strip('"')
            if line:
                first = line
                break
        if not first:
            return {"ui": {"videos": []}, "result": (raw,)}

        # 传进来的是 http(s) URL：先下载到 output/respect_preview 再预览
        if first.lower().startswith(("http://", "https://")) and folder_paths is not None:
            try:
                import requests
                dst_dir = os.path.join(folder_paths.get_output_directory(), "respect_preview")
                os.makedirs(dst_dir, exist_ok=True)
                name = first.split("?")[0].split("/")[-1] or "video.mp4"
                if not os.path.splitext(name)[1]:
                    name += ".mp4"
                dst = os.path.join(dst_dir, f"{_rand_suffix()}_{name}")
                r = requests.get(first, timeout=600, stream=True)
                r.raise_for_status()
                with open(dst, "wb") as f:
                    for chunk in r.iter_content(64 * 1024):
                        if chunk:
                            f.write(chunk)
                first = dst
            except Exception as exc:
                print(f"[Respect] 下载视频 URL 失败，无法预览: {exc}")
                return {"ui": {"videos": []}, "result": (first,)}

        ref = _to_view_ref(first)
        if ref is None:
            print(f"[Respect] 无法预览视频（文件不存在或不可访问）: {first}")
            return {"ui": {"videos": []}, "result": (first,)}

        return {"ui": {"videos": [ref]}, "result": (first,)}


NODE_CLASS_MAPPINGS = {
    "RespectPreviewImage": RespectPreviewImage,
    "RespectPreviewVideo": RespectPreviewVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectPreviewImage": "Respect 查看图像",
    "RespectPreviewVideo": "Respect 查看视频",
}
