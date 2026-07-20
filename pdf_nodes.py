"""Respect ComfyUI 扩展 - PDF 转文字批量加载节点。

从一个文件夹按批次取 PDF 文件并抽取文字输出，取样模式与 ZIP 批量节点一致：
- increment 递增：每次运行往后取一批（跨执行累加，自动回绕）
- decrement 递减：每次运行往前取一批
- random 随机 / fixed 固定

`folder_path` 可填绝对路径或相对 input 的路径；也可以直接填单个 .pdf 文件路径（只处理这一个）。
PDF 文字抽取自动尝试 pymupdf(fitz) / pdfplumber / pypdf，任装其一即可。
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .loader_nodes import (
    SAMPLE_MODES,
    SORT_MODES,
    _input_dir,
    _natural_key,
    _pick_indices,
)

CATEGORY = "Respect"
PDF_EXTS = (".pdf",)


# ---------------------------------------------------------------------------
# 文件夹 / 排序 / 页码
# ---------------------------------------------------------------------------


def _list_input_subdirs() -> list[str]:
    base = _input_dir()
    out = ["(input 根目录)"]
    try:
        for f in sorted(os.listdir(base)):
            if os.path.isdir(os.path.join(base, f)):
                out.append(f)
    except Exception:
        pass
    return out


def _resolve_folder(folder: str, folder_path: str) -> str:
    fp = (folder_path or "").strip().strip('"')
    if fp:
        fp = os.path.expanduser(os.path.expandvars(fp))
        return fp if os.path.isabs(fp) else os.path.join(_input_dir(), fp)
    if folder and folder != "(input 根目录)":
        return os.path.join(_input_dir(), folder)
    return _input_dir()


def _sort_paths(paths: list[str], sort_mode: str) -> list[str]:
    if sort_mode == "none":
        return paths
    if sort_mode == "name":
        return sorted(paths, key=lambda p: os.path.basename(p).lower())
    if sort_mode == "name_desc":
        return sorted(paths, key=lambda p: os.path.basename(p).lower(), reverse=True)
    return sorted(paths, key=lambda p: _natural_key(os.path.basename(p)))


def _list_pdfs(folder: str, recursive: bool, sort_mode: str) -> list[str]:
    paths: list[str] = []
    if recursive:
        for root, _dirs, names in os.walk(folder):
            for n in names:
                if n.lower().endswith(PDF_EXTS) and not n.startswith("."):
                    paths.append(os.path.join(root, n))
    else:
        try:
            for n in os.listdir(folder):
                p = os.path.join(folder, n)
                if os.path.isfile(p) and n.lower().endswith(PDF_EXTS) and not n.startswith("."):
                    paths.append(p)
        except Exception:
            pass
    return _sort_paths(paths, sort_mode)


def _parse_pages(pages_str: str, total: int) -> list[int]:
    """把 "all" / "" / "1-5" / "2" / "1,3,5-7" 解析成 0-based 页索引。"""
    s = (pages_str or "").strip().lower().replace("，", ",")
    if not s or s == "all":
        return list(range(total))
    result: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                a, b = int(a), int(b)
            except ValueError:
                continue
            for i in range(min(a, b), max(a, b) + 1):
                if 1 <= i <= total:
                    result.append(i - 1)
        else:
            try:
                i = int(part)
            except ValueError:
                continue
            if 1 <= i <= total:
                result.append(i - 1)
    return result or list(range(total))


# ---------------------------------------------------------------------------
# PDF -> 文字（多后端）
# ---------------------------------------------------------------------------


_NO_LIB_MSG = (
    "未安装 PDF 解析库，请在 ComfyUI 的 Python 环境任装其一：\n"
    "  pip install pymupdf   （推荐，最快最稳）\n"
    "  pip install pdfplumber\n"
    "  pip install pypdf"
)


def _extract_with_fitz(path: str, pages_str: str) -> Optional[str]:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None
    doc = fitz.open(path)
    try:
        idxs = _parse_pages(pages_str, doc.page_count)
        return "\n".join(doc.load_page(i).get_text() for i in idxs).strip()
    finally:
        doc.close()


def _extract_with_pdfplumber(path: str, pages_str: str) -> Optional[str]:
    try:
        import pdfplumber
    except ImportError:
        return None
    with pdfplumber.open(path) as pdf:
        idxs = _parse_pages(pages_str, len(pdf.pages))
        return "\n".join((pdf.pages[i].extract_text() or "") for i in idxs).strip()


def _extract_with_pypdf(path: str, pages_str: str) -> Optional[str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except ImportError:
            return None
    reader = PdfReader(path)
    idxs = _parse_pages(pages_str, len(reader.pages))
    return "\n".join((reader.pages[i].extract_text() or "") for i in idxs).strip()


def _extract_pdf_text(path: str, pages_str: str = "all") -> str:
    for backend in (_extract_with_fitz, _extract_with_pdfplumber, _extract_with_pypdf):
        text = backend(path, pages_str)
        if text is not None:
            return text
    raise RuntimeError(_NO_LIB_MSG)


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------


class RespectLoadPdfText:
    """从文件夹按批次取 PDF，抽取文字输出。

    - `folder_path` 填文件夹（绝对/相对 input）→ 按 sort 排序后按 mode 取；也可填单个 .pdf 文件路径只处理它。
    - `mode=increment` + `batch_size=1`：每次运行按顺序取下一个 PDF（跨执行递增）。
    - `pages`：`all` 或 `1-5` / `2` / `1,3,5-7`。
    输出：合并文字、被取文件名列表、本次文件数。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "folder": (_list_input_subdirs(),),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 256}),
                "mode": (SAMPLE_MODES, {"default": "increment"}),
                "index": ("INT", {"default": 0, "min": 0, "max": 0xffffffff}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "sort": (SORT_MODES, {"default": "natural"}),
                "recursive": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "folder_path": ("STRING", {"default": "", "multiline": False, "placeholder": "文件夹绝对/相对路径，或单个 .pdf 文件路径；填了优先于上方下拉"}),
                "pages": ("STRING", {"default": "all", "multiline": False, "placeholder": "all 或 1-5 / 2 / 1,3,5-7"}),
                "include_filename_header": ("BOOLEAN", {"default": True}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "STRING")
    RETURN_NAMES = ("text", "filenames", "count", "stem")
    FUNCTION = "load"
    CATEGORY = CATEGORY

    @classmethod
    def IS_CHANGED(cls, mode="increment", **kwargs):
        if mode in ("increment", "decrement", "random"):
            return float("nan")
        return "|".join(
            str(kwargs.get(k)) for k in ("folder", "folder_path", "index", "batch_size", "sort", "recursive", "pages")
        )

    def load(
        self,
        folder: str,
        batch_size: int,
        mode: str,
        index: int,
        seed: int,
        sort: str = "natural",
        recursive: bool = False,
        folder_path: str = "",
        pages: str = "all",
        include_filename_header: bool = True,
        unique_id: Optional[str] = None,
    ) -> tuple[str, str, int]:
        resolved = _resolve_folder(folder, folder_path)

        if os.path.isfile(resolved) and resolved.lower().endswith(PDF_EXTS):
            pdfs = [resolved]
            state_key = resolved
        elif os.path.isdir(resolved):
            pdfs = _list_pdfs(resolved, recursive, sort)
            state_key = resolved
        else:
            raise FileNotFoundError(f"找不到文件夹或 PDF 文件: {resolved}")

        if not pdfs:
            raise ValueError(f"目录内没有 PDF 文件: {resolved}")

        idxs = _pick_indices(
            total=len(pdfs),
            batch_size=batch_size,
            mode=mode,
            index=index,
            seed=seed,
            state_key=state_key,
            unique_id=unique_id,
        )

        parts: list[str] = []
        picked_names: list[str] = []
        for i in idxs:
            path = pdfs[i]
            name = os.path.basename(path)
            try:
                text = _extract_pdf_text(path, pages)
            except RuntimeError:
                raise  # 缺库：直接抛出安装提示
            except Exception as exc:
                print(f"[Respect] PDF 解析失败 {name}: {exc}")
                text = ""
            picked_names.append(name)
            if include_filename_header and len(idxs) > 1:
                parts.append(f"===== {name} =====\n{text}")
            else:
                parts.append(text)

        combined = "\n\n".join(parts).strip()
        stem = os.path.splitext(picked_names[0])[0] if picked_names else ""
        print(f"[Respect] 从文件夹取出 {len(picked_names)} 个 PDF (mode={mode}): {picked_names}")
        return (combined, "\n".join(picked_names), len(picked_names), stem)


NODE_CLASS_MAPPINGS = {
    "RespectLoadPdfText": RespectLoadPdfText,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectLoadPdfText": "Respect PDF批量转文字",
}
