"""Respect ComfyUI 扩展 - 文本分段提取工具。

把一段文字（通常是 GPT/LLM 返回）切成多份，方便任意段落接到不同下游节点。

三种分段方式（区别只在怎么切）：
- delimiter    ：按字面分隔符切（如 \\n\\n、---）
- regex_split  ：按正则切（re.split）
- regex_findall：正则逐个匹配，每个匹配（或第一个捕获组）= 一段
- json         ：把文字当 JSON 解析（自动去 ```json 代码围栏），按 json_path 定位到数组，每个元素 = 一段

输出：seg_1..seg_8 八个段插槽 + count + all_json（完整 JSON 数组）。
超过 8 段或想动态选段，用配套的「取第N段」节点（吃 all_json + index）。
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

CATEGORY = "Respect"

SPLIT_METHODS = ["delimiter", "regex_split", "regex_findall", "json"]
_MAX_SEG_OUTPUTS = 8


# ---------------------------------------------------------------------------
# JSON 容错解析 + 定位
# ---------------------------------------------------------------------------


def _loads_tolerant(text: str) -> Any:
    s = (text or "").strip()
    if not s:
        raise ValueError("输入文本为空")
    # 去掉 markdown 代码围栏 ```json ... ```
    fence = re.search(r"```(?:json)?\s*(.+?)```", s, re.DOTALL | re.IGNORECASE)
    if fence:
        s = fence.group(1).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    # 兜底：截取第一个 [..] 或 {..}
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        i, j = s.find(open_ch), s.rfind(close_ch)
        if 0 <= i < j:
            try:
                return json.loads(s[i:j + 1])
            except Exception:
                continue
    raise ValueError("无法解析为 JSON（请确认 GPT 按 json_schema 返回了合法 JSON）")


def _json_navigate(data: Any, path: str) -> Any:
    path = (path or "").strip()
    if not path:
        return data
    cur = data
    for key in path.split("."):
        key = key.strip()
        if key == "":
            continue
        if isinstance(cur, list) and key.lstrip("-").isdigit():
            idx = int(key)
            cur = cur[idx] if -len(cur) <= idx < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
    return cur


def _as_item_list(node: Any) -> list:
    if isinstance(node, list):
        return node
    if isinstance(node, dict):
        return list(node.values())
    if node is None:
        return []
    return [node]


def _stringify(item: Any, json_field: str) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict) and json_field:
        v = item.get(json_field, "")
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return json.dumps(item, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 分段核心
# ---------------------------------------------------------------------------


def _split_segments(
    text: str,
    method: str,
    pattern: str,
    json_path: str,
    json_field: str,
    ignorecase: bool,
    dotall: bool,
) -> list[str]:
    text = text or ""
    if method == "json":
        node = _json_navigate(_loads_tolerant(text), json_path)
        return [_stringify(it, json_field) for it in _as_item_list(node)]

    if method == "delimiter":
        sep = pattern if pattern != "" else "\n\n"
        # 允许用户填 \n \t 之类的转义
        sep = sep.encode("utf-8").decode("unicode_escape") if "\\" in sep else sep
        return text.split(sep)

    flags = re.MULTILINE
    if ignorecase:
        flags |= re.IGNORECASE
    if dotall:
        flags |= re.DOTALL
    if not pattern:
        raise ValueError("regex 模式需要填写 pattern")

    if method == "regex_split":
        return re.split(pattern, text, flags=flags)

    # regex_findall
    segs: list[str] = []
    for m in re.findall(pattern, text, flags=flags):
        if isinstance(m, tuple):
            segs.append(next((g for g in m if g), ""))
        else:
            segs.append(m)
    return segs


class RespectSplitSegments:
    """把文字切成多份，输出 seg_1..seg_8 + count + all_json。

    - method=json：GPT 用 json_schema 返回后，`json_path` 定位到数组（如 `segments`、`data.items`，
      留空=根就是数组）；元素是对象时用 `json_field` 取字段。
    - method=regex_split / regex_findall：填 `pattern`；regex_findall 每个匹配（或第一个捕获组）= 一段。
    - method=delimiter：`pattern` 填分隔符（默认空行 \\n\\n，支持 \\n \\t 转义）。
    超过 8 段时用 all_json 接「取第N段」节点。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "text": ("STRING", {"default": "", "multiline": True, "forceInput": False}),
                "method": (SPLIT_METHODS, {"default": "json"}),
            },
            "optional": {
                "pattern": ("STRING", {"default": "", "multiline": False, "placeholder": "regex 或分隔符；json 模式忽略"}),
                "json_path": ("STRING", {"default": "", "multiline": False, "placeholder": "json 模式：如 segments / data.items，留空=根"}),
                "json_field": ("STRING", {"default": "", "multiline": False, "placeholder": "json 元素是对象时取的字段名，可留空"}),
                "ignorecase": ("BOOLEAN", {"default": False}),
                "dotall": ("BOOLEAN", {"default": False}),
                "strip_each": ("BOOLEAN", {"default": True}),
                "drop_empty": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("STRING",) * _MAX_SEG_OUTPUTS + ("INT", "STRING")
    RETURN_NAMES = tuple(f"seg_{i + 1}" for i in range(_MAX_SEG_OUTPUTS)) + ("count", "all_json")
    FUNCTION = "split"
    CATEGORY = CATEGORY

    def split(
        self,
        text: str,
        method: str,
        pattern: str = "",
        json_path: str = "",
        json_field: str = "",
        ignorecase: bool = False,
        dotall: bool = False,
        strip_each: bool = True,
        drop_empty: bool = True,
    ):
        segs = _split_segments(text, method, pattern, json_path, json_field, ignorecase, dotall)
        if strip_each:
            segs = [s.strip() for s in segs]
        if drop_empty:
            segs = [s for s in segs if s != ""]

        all_json = json.dumps(segs, ensure_ascii=False)
        padded = (segs + [""] * _MAX_SEG_OUTPUTS)[:_MAX_SEG_OUTPUTS]
        print(f"[Respect] 分段提取 method={method} -> {len(segs)} 段")
        return tuple(padded) + (len(segs), all_json)


class RespectPickSegment:
    """从「分段提取」的 all_json 里取第 N 段（1 起）。用于超过 8 段或动态选段。

    index 超出范围 → 返回 default_text（默认空）。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "all_json": ("STRING", {"default": "", "multiline": False, "forceInput": True}),
                "index": ("INT", {"default": 1, "min": 1, "max": 100000}),
            },
            "optional": {
                "default_text": ("STRING", {"default": "", "multiline": True}),
            },
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("text", "count")
    FUNCTION = "pick"
    CATEGORY = CATEGORY

    def pick(self, all_json: str, index: int, default_text: str = "") -> tuple[str, int]:
        try:
            segs = json.loads(all_json or "[]")
        except Exception:
            segs = []
        if not isinstance(segs, list):
            segs = []
        i = int(index) - 1  # 1 起
        text = segs[i] if 0 <= i < len(segs) else default_text
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)
        return (text, len(segs))


def _unescape(s: str) -> str:
    """把 \\n \\t 之类的字面转义还原成真字符（单行输入框里输入换行用）。"""
    s = s or ""
    if "\\" not in s:
        return s
    try:
        return s.encode("utf-8").decode("unicode_escape")
    except Exception:
        return s


class RespectTextInput:
    """纯文字输入节点：多行文本框 → STRING 输出。可当常量文本源、拼进合并节点。"""

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "text": ("STRING", {"default": "", "multiline": True}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, text: str) -> tuple[str]:
        return (text or "",)


_MAX_MERGE_INPUTS = 8


class RespectMergeText:
    """文字合并：把最多 8 路文字按分隔符拼成一个 STRING（按 text_1..text_8 顺序）。

    `separator` 支持 \\n \\t 转义（单行框里输入换行）；`skip_empty` 跳过空/未连接的输入。
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        optional = {
            f"text_{i + 1}": ("STRING", {"default": "", "forceInput": True})
            for i in range(_MAX_MERGE_INPUTS)
        }
        return {
            "required": {
                "separator": ("STRING", {"default": "\\n", "multiline": False, "placeholder": "分隔符，支持 \\n \\t，默认换行"}),
                "skip_empty": ("BOOLEAN", {"default": True}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("text", "count")
    FUNCTION = "merge"
    CATEGORY = CATEGORY

    def merge(self, separator: str = "\\n", skip_empty: bool = True, **kwargs) -> tuple[str, int]:
        sep = _unescape(separator)
        parts: list[str] = []
        for i in range(_MAX_MERGE_INPUTS):
            v = kwargs.get(f"text_{i + 1}")
            if v is None:
                continue
            if not isinstance(v, str):
                v = str(v)
            if skip_empty and v.strip() == "":
                continue
            parts.append(v)
        return (sep.join(parts), len(parts))


NODE_CLASS_MAPPINGS = {
    "RespectSplitSegments": RespectSplitSegments,
    "RespectPickSegment": RespectPickSegment,
    "RespectTextInput": RespectTextInput,
    "RespectMergeText": RespectMergeText,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectSplitSegments": "Respect 分段提取",
    "RespectPickSegment": "Respect 取第N段",
    "RespectTextInput": "Respect 文字输入",
    "RespectMergeText": "Respect 文字合并",
}
