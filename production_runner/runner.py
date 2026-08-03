# -*- coding: utf-8 -*-
"""生产执行器（环节9-10）：读 tasks.json → 灵感鸭生成 → 落盘 + 注册表。

对应 script-to-video-prompts-v2 skill 的模块契约：
  进 = tasks.json + 提示词文件 + 固定故事板
  出 = 约定路径的文件 + 注册表登记

执行纪律（与 skill 一致）：
  按清单顺序串行；输出已存在则跳过（生成即固定，不覆盖）；
  技术失败同参重试 ≤2；内容质量不判断——落记录，留给人工（环节11）。

用法：
  python runner.py <项目目录> --tasks 06_生产提示词/tasks_EP01.json [--stage all|storyboard|video]
                              [--only EP01-SEG04] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

# Windows 控制台中文兜底
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lingganya import Client, LingganyaError, resolve_ref  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_TECH_RETRY = 2  # 技术失败重试上限（skill 固定参数）

DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://www.lingganyaapi.com",
    "proxy": "",
    "image_model": "gpt-image-2",
    "image_size": "1024x1536",
    "image_poll_interval": 5,
    "image_poll_timeout": 900,
    "video_model": "sd-2.0",
    "video_resolution": "720p",
    "video_poll_interval": 8,
    "video_poll_timeout": 1800,
    "ref_max_side": 1536,
    # 视频可走独立中转站/接口风格；留空 = 与图片同一家
    "video_api_style": "lingganya",   # lingganya | sd2
    "video_base_url": "",
    "video_api_key": "",
    "upload_base_url": "https://api.aione.help",  # sd2 风格参考图公网上传
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    path = os.path.join(HERE, "config.json")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            cfg.update(json.load(f))
    if not cfg.get("api_key"):
        cfg["api_key"] = (os.environ.get("LINGGANYA_API_KEY")
                          or os.environ.get("RESPECT_API_KEY")
                          or os.environ.get("AICOPY_API_KEY") or "")
    return cfg


# ---------------------------------------------------------------------------
# 项目文件工具
# ---------------------------------------------------------------------------


def p(root: str, rel: str) -> str:
    return rel if os.path.isabs(rel) else os.path.join(root, rel)


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read().strip()


def load_registry(path: str) -> list:
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, list) else data.get("items", [])
    return []


def save_registry(path: str, items: list) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def upsert(items: list, entry: dict, keys=("segment_id", "file_ref")) -> None:
    for i, it in enumerate(items):
        if all(it.get(k) == entry.get(k) for k in keys):
            items[i] = entry
            return
    items.append(entry)


def log_event(root: str, event: dict) -> None:
    path = os.path.join(root, "06_生产提示词", "execution_log.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    event["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 图片类任务（环节5 资产图 / 环节9 故事板，共用一套执行逻辑）
# ---------------------------------------------------------------------------

IMAGE_KINDS = {
    "asset": {"label": "资产图", "id_key": "asset_id",
              "registry": os.path.join("02_全剧资产", "asset_registry.json")},
    "storyboard": {"label": "故事板", "id_key": "segment_id",
                   "registry": os.path.join("03_段落故事板", "storyboard_registry.json")},
}


def run_image_task(client: Client, cfg: dict, root: str, task: dict, dry: bool, kind: str) -> str:
    meta = IMAGE_KINDS[kind]
    tid = task.get(meta["id_key"]) or task.get("segment_id") or task.get("asset_id")
    out = p(root, task["output"])
    if os.path.isfile(out):
        print(f"[跳过] {tid} {meta['label']}已存在（不覆盖）: {task['output']}")
        return "skipped"

    prompt = read_text(p(root, task["prompt_ref"]))
    refs = []
    for r in sorted(task.get("reference_images", []), key=lambda x: x.get("image_n", 0)):
        val = r.get("url") or r.get("file_ref") or ""
        refs.append(resolve_ref(val, root, max_side=cfg["ref_max_side"]))
    size = (task.get("params") or {}).get("size") or cfg["image_size"]

    print(f"[{meta['label']}] {tid}  参考图×{len(refs)}  size={size}")
    if dry:
        print(f"    (dry-run) prompt {len(prompt)} 字，输出 → {task['output']}")
        return "dry"

    last_exc = None
    for attempt in range(1 + MAX_TECH_RETRY):
        try:
            if attempt:
                print(f"    技术重试 {attempt}/{MAX_TECH_RETRY}（同参考图同提示词）")
            data, task_id = client.submit_image(prompt, model=cfg["image_model"], size=size, images=refs or None)
            items = client.poll("images", task_id, interval=cfg["image_poll_interval"],
                                timeout=cfg["image_poll_timeout"], want_images=True) if task_id else []
            if not items:
                raise LingganyaError("提交未返回 task_id 或图片")
            client.save_item(items[0], out)
            print(f"    完成 → {task['output']}")

            reg_path = os.path.join(root, meta["registry"])
            items_reg = load_registry(reg_path)
            entry = {
                meta["id_key"]: tid,
                "file_ref": task["output"],
                "model": cfg["image_model"],
                "task_id": task_id,
                "reference_count": len(refs),
                "status": "generated",  # 技术检查通过后由 Agent/人工改为 fixed
            }
            if kind == "storyboard":
                entry["storyboard_id"] = f"{tid}_SB"
            upsert(items_reg, entry, keys=(meta["id_key"], "file_ref"))
            save_registry(reg_path, items_reg)
            log_event(root, {"stage": kind, "id": tid, "result": "ok",
                             "task_id": task_id, "output": task["output"], "attempt": attempt})
            return "ok"
        except (LingganyaError, OSError) as exc:
            last_exc = exc
            print(f"    失败: {exc}")
    log_event(root, {"stage": kind, "id": tid, "result": "tech_failed", "error": str(last_exc)})
    return "failed"


# ---------------------------------------------------------------------------
# 视频任务（环节10 —— 纯执行）
# ---------------------------------------------------------------------------


def video_client(cfg: dict) -> Client:
    """视频可配置独立中转站；未配置则与图片共用主配置。"""
    return Client(cfg.get("video_api_key") or cfg["api_key"],
                  cfg.get("video_base_url") or cfg["base_url"],
                  proxy=cfg.get("proxy", ""))


def run_video_task(client: Client, cfg: dict, root: str, task: dict, dry: bool) -> str:
    seg = task["segment_id"]
    out = p(root, task["output"])
    if os.path.isfile(out):
        print(f"[跳过] {seg} 视频已存在（不覆盖）: {task['output']}")
        return "skipped"

    sb_rel = task["storyboard_ref"]
    sb_path = p(root, sb_rel)
    if not (sb_rel.startswith("http") or os.path.isfile(sb_path)):
        print(f"[阻塞] {seg} 固定故事板不存在，先跑 --stage storyboard: {sb_rel}")
        return "blocked"

    prompt = read_text(p(root, task["prompt_ref"]))
    params = task.get("params") or {}
    seconds = int(params.get("duration", 15))
    ratio = params.get("ratio", "9:16")
    model = params.get("model") or cfg["video_model"]
    resolution = params.get("resolution") or cfg["video_resolution"]
    style = (params.get("api_style") or cfg.get("video_api_style") or "lingganya").lower()

    ref_paths = [sb_rel]
    if task.get("aux_reference"):
        ref_paths.append(task["aux_reference"])

    print(f"[视频] {seg}  model={model} style={style} {seconds}s {ratio}  参考图×{len(ref_paths)}")
    if dry:
        print(f"    (dry-run) prompt {len(prompt)} 字，输出 → {task['output']}")
        return "dry"

    last_exc = None
    uploaded: list = []
    for attempt in range(1 + MAX_TECH_RETRY):
        try:
            if attempt:
                print(f"    技术重试 {attempt}/{MAX_TECH_RETRY}（同故事板同提示词）")
            from lingganya import extract_video_url, file_to_data_uri
            if style == "sd2":
                # 参考图：URL 直用；本地文件压缩转 data URI（1024px q80，实测 paisio 接受）
                if not uploaded:
                    for rp in ref_paths:
                        if rp.startswith("http"):
                            uploaded.append(rp)
                        else:
                            uploaded.append(file_to_data_uri(p(root, rp), max_side=1024, quality=80))
                data, task_id = client.submit_video_sd2(prompt, model=model, ratio=ratio,
                                                        duration=seconds, images=uploaded)
            else:
                refs = [resolve_ref(rp, root, max_side=cfg["ref_max_side"]) for rp in ref_paths]
                data, task_id = client.submit_video(prompt, model=model, size=ratio,
                                                    seconds=seconds, resolution=resolution,
                                                    images=refs)
            url = extract_video_url(data)
            if not url:
                if not task_id:
                    raise LingganyaError("提交未返回 task_id 或视频URL")
                url = client.poll("videos", task_id, interval=cfg["video_poll_interval"],
                                  timeout=cfg["video_poll_timeout"])
            client.save_item(url, out)
            print(f"    完成 → {task['output']}")

            reg_path = os.path.join(root, "04_段落视频", "video_registry.json")
            items_reg = load_registry(reg_path)
            upsert(items_reg, {
                "segment_id": seg,
                "segment_video_id": f"{seg}_VID",
                "video_file_ref": task["output"],
                "storyboard_ref": sb_rel,
                "model": model,
                "task_id": task_id,
                "source_url": url,
                "status": "generated",  # 内容质量判断在环节11（人工）
            }, keys=("segment_id", "video_file_ref"))
            save_registry(reg_path, items_reg)
            log_event(root, {"stage": "video", "segment_id": seg, "result": "ok",
                             "task_id": task_id, "output": task["output"], "attempt": attempt})
            return "ok"
        except (LingganyaError, OSError) as exc:
            last_exc = exc
            print(f"    失败: {exc}")
    log_event(root, {"stage": "video", "segment_id": seg, "result": "tech_failed",
                     "error": str(last_exc)})
    return "failed"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="灵感鸭生产执行器（v2 skill 环节9-10）")
    ap.add_argument("project", help="项目根目录")
    ap.add_argument("--tasks", default="", help="tasks.json 路径（默认自动找 06_生产提示词/tasks_*.json）")
    ap.add_argument("--stage", choices=["all", "asset", "storyboard", "video"], default="all")
    ap.add_argument("--only", default="", help="只跑指定段，如 EP01-SEG04（可逗号分隔多个）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将执行的任务，不调 API")
    args = ap.parse_args()

    root = os.path.abspath(args.project)
    if not os.path.isdir(root):
        print(f"项目目录不存在: {root}")
        return 2

    tasks_path = p(root, args.tasks) if args.tasks else ""
    if not tasks_path:
        cand_dir = os.path.join(root, "06_生产提示词")
        cands = sorted(f for f in os.listdir(cand_dir)) if os.path.isdir(cand_dir) else []
        cands = [f for f in cands if f.startswith("tasks_") and f.endswith(".json")]
        if not cands:
            print("找不到 tasks_*.json，请用 --tasks 指定")
            return 2
        tasks_path = os.path.join(cand_dir, cands[0])
    print(f"任务清单: {tasks_path}")
    with open(tasks_path, "r", encoding="utf-8-sig") as f:
        tasks = json.load(f)

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    cfg = load_config()
    client = None
    if not args.dry_run:
        client = Client(cfg["api_key"], cfg["base_url"], proxy=cfg.get("proxy", ""))

    stats: dict = {}

    def bump(k):
        stats[k] = stats.get(k, 0) + 1

    # 按清单顺序串行（剧情顺序 = 环节9/10 的默认纪律）
    if args.stage in ("all", "asset"):
        for t in tasks.get("asset_tasks", []):
            if only and t.get("asset_id") not in only:
                continue
            bump(run_image_task(client, cfg, root, t, args.dry_run, "asset"))
    if args.stage in ("all", "storyboard"):
        for t in tasks.get("storyboard_tasks", []):
            if only and t["segment_id"] not in only:
                continue
            bump(run_image_task(client, cfg, root, t, args.dry_run, "storyboard"))
    if args.stage in ("all", "video"):
        vclient = video_client(cfg) if not args.dry_run else None
        for t in tasks.get("video_tasks", []):
            if only and t["segment_id"] not in only:
                continue
            bump(run_video_task(vclient, cfg, root, t, args.dry_run))

    print(f"\n汇总: {json.dumps(stats, ensure_ascii=False)}")
    print("注意：status=generated 只代表技术生成成功；内容质量判断（固定/修订）在环节11由人工完成。")
    return 1 if stats.get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())
