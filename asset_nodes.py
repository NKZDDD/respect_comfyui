"""Respect ComfyUI 扩展 - 关键词取素材（角色库/素材库）。

从一段文字里按关键词取出逗号分隔的名字，再去指定目录按名字调出对应文件（图片/视频/文本）。

例：提示词里有 `出场人物：小白，小黑，小红` →
  keyword=出场人物 → 解析出 [小白, 小黑, 小红] →
  去 library_dir 找名为 小白 / 小黑 / 小红 的文件（按 file_type 的后缀）→ 输出。

输出：images(匹配到的图片，IMAGE 批次) + text(文本文件内容) + paths(所有匹配文件路径) + names + count。
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional

import torch

from .utils import _comfy_output_base, pil_to_tensor, tensors_concat

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore

CATEGORY = "Respect"

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
VIDEO_EXTS = (".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi")
TEXT_EXTS = (".txt", ".md", ".json", ".csv")

FILE_TYPES = ["图片", "视频", "文本", "任意"]
MATCH_MODES = ["精确(名字=文件名)", "前缀(文件名以名字开头)", "包含(文件名含名字)"]

_SEP_RE = re.compile(r"[,，、;；/|]+")


def _exts_for(file_type: str) -> tuple[str, ...]:
    if file_type == "图片":
        return IMAGE_EXTS
    if file_type == "视频":
        return VIDEO_EXTS
    if file_type == "文本":
        return TEXT_EXTS
    return IMAGE_EXTS + VIDEO_EXTS + TEXT_EXTS


def _clean_name(n: str) -> str:
    n = (n or "").strip().strip('"').strip("'").strip("“”‘’")
    return n.strip("。.!！?？:：;；、,， \t")


def _extract_names(text: str, keyword: str) -> list[str]:
    s = text or ""
    if (keyword or "").strip():
        m = re.search(re.escape(keyword.strip()) + r"\s*[:：]?\s*([^\n\r]+)", s)
        if not m:
            return []
        seg = m.group(1)
    else:
        seg = s
    # 名字列表遇到句末标点就截断（句号/问号/感叹号），逗号/顿号才是名字分隔
    seg = re.split(r"[。！!？?]", seg, maxsplit=1)[0]
    names = [_clean_name(p) for p in _SEP_RE.split(seg)]
    # 去空、去重（保序）
    out: list[str] = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return out


def _resolve_dir(library_dir: str) -> str:
    d = (library_dir or "").strip().strip('"')
    if not d:
        return ""
    d = os.path.expanduser(os.path.expandvars(d))
    if not os.path.isabs(d):
        d = os.path.join(_comfy_output_base(), d)
    return d


def _list_files(library_dir: str, exts: tuple, recursive: bool) -> list[str]:
    files: list[str] = []
    if not os.path.isdir(library_dir):
        return files
    if recursive:
        for root, _dirs, names in os.walk(library_dir):
            for n in names:
                if n.lower().endswith(exts):
                    files.append(os.path.join(root, n))
    else:
        for n in os.listdir(library_dir):
            p = os.path.join(library_dir, n)
            if os.path.isfile(p) and n.lower().endswith(exts):
                files.append(p)
    return files


def _match(stem: str, name: str, mode: str) -> bool:
    a, b = stem.lower(), name.lower()
    if mode.startswith("前缀"):
        return a.startswith(b)
    if mode.startswith("包含"):
        return b in a
    return a == b  # 精确


def _load_images(paths: list[str]) -> Optional[torch.Tensor]:
    if Image is None or not paths:
        return None
    tensors: list[torch.Tensor] = []
    target = None
    for p in paths:
        try:
            img = Image.open(p).convert("RGB")
        except Exception as exc:
            print(f"[Respect] 角色库图片打开失败 {p}: {exc}")
            continue
        if target is None:
            target = img.size  # (W, H) 以第一张为准
        elif img.size != target:
            img = img.resize(target)
        t = pil_to_tensor(img)
        if t is not None:
            tensors.append(t)
    if not tensors:
        return None
    return tensors_concat(tensors)


class RespectAssetLibrary:
    """关键词取素材：从 text 里按 keyword 取逗号分隔的名字，去 library_dir 调出同名文件。

    - keyword 留空 → 把整段 text 当名字列表
    - file_type：图片→加载成 IMAGE；文本→读出内容到 text；视频/任意→输出路径
    - match_mode：精确 / 前缀 / 包含（默认精确，文件名=名字）
    """

    DESCRIPTION = "按关键词从文本抠出逗号分隔的名字（如 出场人物：小白，小黑），去 library_dir 调出同名图片/视频/文本文件。"

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "text": ("STRING", {"default": "", "multiline": True, "tooltip": "含名字列表的文本（如 出场人物：小白，小黑，小红）"}),
                "keyword": ("STRING", {"default": "出场人物", "multiline": False, "tooltip": "定位名字列表的关键词；留空=整段当名字列表"}),
                "library_dir": ("STRING", {"default": "", "multiline": False, "placeholder": "角色库目录（绝对或相对 output）", "tooltip": "存角色素材的文件夹"}),
                "file_type": (FILE_TYPES, {"default": "图片", "tooltip": "调出哪类文件"}),
                "match_mode": (MATCH_MODES, {"default": "精确(名字=文件名)"}),
                "recursive": ("BOOLEAN", {"default": True, "tooltip": "是否搜子文件夹"}),
            },
            "optional": {
                "ext_override": ("STRING", {"default": "", "multiline": False, "placeholder": "自定义后缀，如 .png,.webp（覆盖 file_type）"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("images", "text", "paths", "names", "count")
    FUNCTION = "fetch"
    CATEGORY = CATEGORY

    def fetch(self, text, keyword, library_dir, file_type, match_mode, recursive, ext_override=""):
        names = _extract_names(text, keyword)
        lib = _resolve_dir(library_dir)
        if not lib or not os.path.isdir(lib):
            raise FileNotFoundError(f"角色库目录不存在: {library_dir}")

        if (ext_override or "").strip():
            exts = tuple(
                (e if e.startswith(".") else "." + e).strip().lower()
                for e in _SEP_RE.split(ext_override) if e.strip()
            )
        else:
            exts = _exts_for(file_type)

        all_files = _list_files(lib, exts, recursive)

        matched: list[str] = []
        for name in names:
            hits = []
            for fp in all_files:
                stem = os.path.splitext(os.path.basename(fp))[0]
                if _match(stem, name, match_mode):
                    hits.append(fp)
            for fp in sorted(hits):
                if fp not in matched:
                    matched.append(fp)

        # 分类输出
        img_paths = [p for p in matched if p.lower().endswith(IMAGE_EXTS)]
        txt_paths = [p for p in matched if p.lower().endswith(TEXT_EXTS)]

        images = _load_images(img_paths)
        if images is None:
            images = torch.zeros((1, 64, 64, 3), dtype=torch.float32)

        text_parts = []
        for p in txt_paths:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    text_parts.append(f"===== {os.path.splitext(os.path.basename(p))[0]} =====\n{f.read().strip()}")
            except Exception as exc:
                print(f"[Respect] 角色库文本读取失败 {p}: {exc}")

        print(f"[Respect] 角色库: 名字{names} -> 命中 {len(matched)} 个文件（图{len(img_paths)}/文本{len(txt_paths)}）")
        return (
            images,
            "\n\n".join(text_parts),
            "\n".join(matched),
            "，".join(names),
            len(matched),
        )


NODE_CLASS_MAPPINGS = {
    "RespectAssetLibrary": RespectAssetLibrary,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectAssetLibrary": "Respect 关键词取素材（角色库）",
}
