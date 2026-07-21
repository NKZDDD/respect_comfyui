"""Respect ComfyUI 扩展 - 分镜任务队列（文件系统作为生产者/消费者队列）。

一个「场景 scene」= 一张图 + 绑定的多个提示词（一对多）。用文件夹分阶段，"做完即移走" 天然防重复、可断点续跑：

    <root>/
      01_pending/<scene>/image.png
      01_pending/<scene>/prompts/001.txt 002.txt ...   # 按顺序编号
      02_done_prompts/<scene>/00X.txt                  # 提示词做完移到这
      03_videos/<scene>/00X.mp4                         # 删帧后的视频按 scene 成批
      04_done_scenes/<scene>/image.png                  # 该 scene 全做完，图片才移到这

三个节点：
- RespectStoryboardSave     写入一个 scene（图 + 有序提示词）
- RespectStoryboardNext     取下一个未做的 (图,提示词) 任务（每次 1 个）
- RespectStoryboardComplete 归档视频 + 提示词标记完成；scene 全做完才移动图片
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from typing import Any, Optional

import torch

from .utils import _comfy_output_base, pil_to_tensor, tensor_to_pil

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore

CATEGORY = "Respect/分镜"

PENDING = "01_pending"
DONE_PROMPTS = "02_done_prompts"
VIDEOS = "03_videos"
DONE_SCENES = "04_done_scenes"


def _resolve_root(root_dir: str) -> str:
    root_dir = (root_dir or "").strip().strip('"')
    if root_dir:
        root_dir = os.path.expanduser(os.path.expandvars(root_dir))
        if not os.path.isabs(root_dir):
            root_dir = os.path.join(_comfy_output_base(), root_dir)
    else:
        root_dir = os.path.join(_comfy_output_base(), "respect_storyboard")
    return root_dir


def _parse_prompts(prompts_json: str, prompts_text: str) -> list[str]:
    """优先解析 all_json（JSON 数组，保序）；否则按多行文本，每行一条。"""
    out: list[str] = []
    s = (prompts_json or "").strip()
    if s:
        try:
            data = json.loads(s)
            if isinstance(data, list):
                out = [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            out = []
    if not out and (prompts_text or "").strip():
        out = [ln.strip() for ln in prompts_text.splitlines() if ln.strip()]
    return out


# ---------------------------------------------------------------------------
# ① 分镜存储
# ---------------------------------------------------------------------------


class RespectStoryboardSave:
    """把「一张图 + 多个提示词（有序）」写入 01_pending/<scene>/。

    `prompts_json` 直接接 Respect 分段提取 的 all_json；或用 `prompts_text` 多行（每行一条）。
    scene_id 留空自动生成。返回 scene_id / pending_dir / count。
    """

    DESCRIPTION = "分镜存储：图 + 有序提示词 → <root>/01_pending/<scene>/（image.png + prompts/00X.txt）。防重复续跑用。"

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "root_dir": ("STRING", {"default": "respect_storyboard", "multiline": False, "tooltip": "队列根目录：相对=output 下，也可绝对路径"}),
                "image": ("IMAGE", {"tooltip": "该分镜的图（作为视频首帧）"}),
                "prompts_json": ("STRING", {"default": "", "multiline": False, "forceInput": True, "tooltip": "接分段提取的 all_json（JSON数组，保序）"}),
            },
            "optional": {
                "prompts_text": ("STRING", {"default": "", "multiline": True, "tooltip": "备用：多行提示词，每行一条（prompts_json 为空时用）"}),
                "scene_id": ("STRING", {"default": "", "multiline": False, "placeholder": "留空自动生成", "tooltip": "场景 ID，留空自动 scene_时间戳_hash"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("scene_id", "pending_dir", "count")
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = CATEGORY

    def save(self, root_dir: str, image: torch.Tensor, prompts_json: str = "",
             prompts_text: str = "", scene_id: str = "") -> tuple[str, str, int]:
        if Image is None:
            raise RuntimeError("缺少 PIL，无法保存图片")
        prompts = _parse_prompts(prompts_json, prompts_text)
        if not prompts:
            raise ValueError("没有提示词（prompts_json 需为 JSON 数组，或用 prompts_text 每行一条）")

        root = _resolve_root(root_dir)
        scene_id = (scene_id or "").strip() or f"scene_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        scene_dir = os.path.join(root, PENDING, scene_id)
        prompts_dir = os.path.join(scene_dir, "prompts")
        os.makedirs(prompts_dir, exist_ok=True)

        pil_list = tensor_to_pil(image[:1])
        if not pil_list:
            raise ValueError("image 为空")
        pil_list[0].save(os.path.join(scene_dir, "image.png"))

        for i, p in enumerate(prompts, start=1):
            with open(os.path.join(prompts_dir, f"{i:03d}.txt"), "w", encoding="utf-8") as f:
                f.write(p)

        print(f"[Respect] 分镜存储: scene={scene_id} 提示词={len(prompts)} -> {scene_dir}")
        return (scene_id, scene_dir, len(prompts))


# ---------------------------------------------------------------------------
# ② 取下一个任务
# ---------------------------------------------------------------------------


def _list_pending_jobs(root: str) -> list[tuple[str, str]]:
    """返回按 (scene, seq) 排序的待做任务 [(scene_id, seq), ...]。"""
    pending = os.path.join(root, PENDING)
    jobs: list[tuple[str, str]] = []
    if not os.path.isdir(pending):
        return jobs
    for scene in sorted(os.listdir(pending)):
        pdir = os.path.join(pending, scene, "prompts")
        img = os.path.join(pending, scene, "image.png")
        if not os.path.isdir(pdir) or not os.path.isfile(img):
            continue
        for fn in sorted(os.listdir(pdir)):
            if fn.lower().endswith(".txt"):
                jobs.append((scene, os.path.splitext(fn)[0]))
    return jobs


class RespectStoryboardNext:
    """取下一个未做的 (图, 提示词) 任务（每次运行 1 个）。

    输出 image + prompt + scene_id + seq（后两个传给 完成归档 节点）。队列空时 has_job=False。
    只读不移动；做完由 完成归档 节点移走，下次运行自然取到下一个。
    """

    DESCRIPTION = "取任务：扫 01_pending，按顺序给出下一个 (图,提示词)。has_job=false 表示队列已空。"

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "root_dir": ("STRING", {"default": "respect_storyboard", "multiline": False, "tooltip": "队列根目录（同存储节点）"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING", "BOOLEAN", "INT")
    RETURN_NAMES = ("image", "prompt", "scene_id", "seq", "has_job", "remaining")
    FUNCTION = "next_job"
    CATEGORY = CATEGORY

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")  # 每次都重新扫描目录

    def next_job(self, root_dir: str):
        root = _resolve_root(root_dir)
        jobs = _list_pending_jobs(root)
        if not jobs:
            print("[Respect] 分镜取任务: 队列已空")
            return (torch.zeros((1, 64, 64, 3), dtype=torch.float32), "", "", "", False, 0)

        scene_id, seq = jobs[0]
        img_path = os.path.join(root, PENDING, scene_id, "image.png")
        txt_path = os.path.join(root, PENDING, scene_id, "prompts", f"{seq}.txt")
        with open(txt_path, "r", encoding="utf-8") as f:
            prompt = f.read().strip()
        img_tensor = pil_to_tensor(Image.open(img_path)) if Image is not None else torch.zeros((1, 64, 64, 3))
        print(f"[Respect] 分镜取任务: scene={scene_id} seq={seq} 剩余={len(jobs)}")
        return (img_tensor, prompt, scene_id, seq, True, len(jobs))


# ---------------------------------------------------------------------------
# ③ 完成归档
# ---------------------------------------------------------------------------


class RespectStoryboardComplete:
    """归档一个任务：视频存进 03_videos/<scene>/<seq>.mp4，提示词移到 02_done_prompts；
    该 scene 提示词全做完后，把 image.png 移到 04_done_scenes。

    `video_path` 接删帧后的视频。scene_id / seq 接自 取任务 节点。
    """

    DESCRIPTION = "完成归档：视频→03_videos/<scene>；提示词→02_done_prompts；scene 全做完则图片→04_done_scenes。防重复。"

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "root_dir": ("STRING", {"default": "respect_storyboard", "multiline": False, "tooltip": "队列根目录（同前）"}),
                "scene_id": ("STRING", {"default": "", "multiline": False, "forceInput": True, "tooltip": "接取任务节点的 scene_id"}),
                "seq": ("STRING", {"default": "", "multiline": False, "forceInput": True, "tooltip": "接取任务节点的 seq"}),
                "video_path": ("STRING", {"default": "", "multiline": False, "forceInput": True, "tooltip": "删帧后的视频路径"}),
            },
        }

    RETURN_TYPES = ("STRING", "BOOLEAN", "INT")
    RETURN_NAMES = ("videos_dir", "scene_done", "remaining")
    FUNCTION = "complete"
    OUTPUT_NODE = True
    CATEGORY = CATEGORY

    def complete(self, root_dir: str, scene_id: str, seq: str, video_path: str):
        root = _resolve_root(root_dir)
        scene_id = (scene_id or "").strip()
        seq = (seq or "").strip()
        video_path = (video_path or "").strip().strip('"')
        if not scene_id or not seq:
            raise ValueError("scene_id / seq 为空（请接 取任务 节点的输出）")

        videos_dir = os.path.join(root, VIDEOS, scene_id)
        os.makedirs(videos_dir, exist_ok=True)

        # 1) 视频归档
        if video_path and os.path.isfile(video_path):
            ext = os.path.splitext(video_path)[1] or ".mp4"
            dst = os.path.join(videos_dir, f"{seq}{ext}")
            try:
                shutil.copy2(video_path, dst)
            except Exception as exc:
                print(f"[Respect] 视频归档失败: {exc}")
        else:
            print(f"[Respect] 完成归档警告: 视频不存在，仅标记提示词完成: {video_path}")

        # 2) 提示词标记完成（移到 02_done_prompts）
        src_txt = os.path.join(root, PENDING, scene_id, "prompts", f"{seq}.txt")
        done_dir = os.path.join(root, DONE_PROMPTS, scene_id)
        os.makedirs(done_dir, exist_ok=True)
        if os.path.isfile(src_txt):
            try:
                shutil.move(src_txt, os.path.join(done_dir, f"{seq}.txt"))
            except Exception as exc:
                print(f"[Respect] 提示词归档失败: {exc}")

        # 3) 该 scene 提示词是否全部完成
        prompts_dir = os.path.join(root, PENDING, scene_id, "prompts")
        remaining = 0
        if os.path.isdir(prompts_dir):
            remaining = len([f for f in os.listdir(prompts_dir) if f.lower().endswith(".txt")])

        scene_done = False
        if remaining == 0:
            # 图片移到 04_done_scenes，清理空的 pending/<scene>
            img = os.path.join(root, PENDING, scene_id, "image.png")
            dst_scene = os.path.join(root, DONE_SCENES, scene_id)
            os.makedirs(dst_scene, exist_ok=True)
            if os.path.isfile(img):
                try:
                    shutil.move(img, os.path.join(dst_scene, "image.png"))
                except Exception as exc:
                    print(f"[Respect] 图片归档失败: {exc}")
            try:
                # 清空的 prompts 目录与 scene 目录
                if os.path.isdir(prompts_dir) and not os.listdir(prompts_dir):
                    os.rmdir(prompts_dir)
                scene_pending = os.path.join(root, PENDING, scene_id)
                if os.path.isdir(scene_pending) and not os.listdir(scene_pending):
                    os.rmdir(scene_pending)
            except Exception:
                pass
            scene_done = True

        print(f"[Respect] 分镜完成: scene={scene_id} seq={seq} 该scene剩余={remaining} scene_done={scene_done}")
        return (videos_dir, scene_done, remaining)


NODE_CLASS_MAPPINGS = {
    "RespectStoryboardSave": RespectStoryboardSave,
    "RespectStoryboardNext": RespectStoryboardNext,
    "RespectStoryboardComplete": RespectStoryboardComplete,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RespectStoryboardSave": "Respect 分镜存储",
    "RespectStoryboardNext": "Respect 分镜取任务",
    "RespectStoryboardComplete": "Respect 分镜完成归档",
}
