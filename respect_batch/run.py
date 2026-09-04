# -*- coding: utf-8 -*-
"""Respect 批量并发 —— 入口。

    双击 / 直接跑        起界面，浏览器打开 http://127.0.0.1:8790
    run.py run ...       不开界面，命令行跑一批（给脚本和定时任务用）

为什么存在：ComfyUI 一次只推进一个节点，一条视频几分钟，排 20 条就串行等
20 次。这里 20 条同时发出去，总耗时约等于最慢那一条。
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    # line_buffering：输出被重定向到文件时（打包成 exe 后常见）Python 默认按块
    # 缓冲，进程被强杀就什么都没写进去，连启动横幅都看不到。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from core import paths                                      # noqa: E402


def _free_port(host: str, want: int) -> int:
    """端口被占就往后找。**不能直接失败** —— 上一个实例没退干净是常事，
    而报「端口被占用」之后人只会反复双击。"""
    import socket
    for p in range(want, want + 20):
        with socket.socket() as s:
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    return want


def serve(args) -> int:
    from core import server                                 # noqa: PLC0415
    port = _free_port(args.host, args.port)
    url = f"http://{args.host}:{port}/"
    httpd = server.serve(args.host, port)
    print("=" * 62)
    print("  Respect 批量并发")
    print(f"  界面：{url}")
    print(f"  配置：{paths.config_path()}")
    print(f"  记录：{paths.runs_dir()}")
    print("  关掉这个黑窗口就是退出。")
    print("=" * 62)
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n收到 Ctrl-C，退出。")
    return 0


def cli(args) -> int:
    """不开界面跑一批。清单从文件读，一行一条（格式同界面上那个框）。"""
    from core import batch, config                          # noqa: PLC0415
    cfg = config.load()
    if not os.path.isfile(args.file):
        print(f"✗ 找不到任务清单：{args.file}")
        return 2
    with open(args.file, encoding="utf-8-sig") as f:
        lines = f.read()

    d = cfg.get("defaults") or {}
    spec = {
        "kind": args.kind, "provider": args.provider, "model": args.model,
        "lines": lines, "size": args.size, "ratio": args.ratio,
        "duration": args.duration, "resolution": args.resolution,
        "concurrency": args.jobs or d.get("concurrency", 4),
        "repeat": args.repeat,
        "max_retry": d.get("max_retry", 2) if args.retry is None else args.retry,
        "out_dir": args.out or d.get("out_dir"),
        "skip_existing": not args.no_skip,
        "timeout": d.get("timeout", 900),
        "poll_timeout": (d.get("poll_timeout_image", 900) if args.kind == "image"
                         else d.get("poll_timeout_video", 2400)),
    }
    run = batch.start(spec, cfg)
    seen = 0
    while run.status in ("排队中", "跑批中"):
        time.sleep(1)
        with run._lock:                                     # noqa: SLF001
            rows, seen = run.logs[seen:], len(run.logs)
        for r in rows:
            print(f"{r['t']}  {r['text']}")
    with run._lock:                                         # noqa: SLF001
        for r in run.logs[seen:]:
            print(f"{r['t']}  {r['text']}")
    c = run.counts()
    print(f"\n{run.message}")
    print(f"记录：{run.manifest_path}")
    # 有失败就非 0 退出 —— 定时任务/CI 靠这个知道要不要看
    return 1 if c["失败"] else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Respect 批量并发")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--data-dir", default="", help="配置和记录放哪（默认 LOCALAPPDATA）")

    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="不开界面，命令行跑一批")
    r.add_argument("--file", required=True, help="任务清单，一行一条")
    r.add_argument("--provider", required=True)
    r.add_argument("--kind", default="image", choices=["image", "video"])
    r.add_argument("--model", default="")
    r.add_argument("--size", default="")
    r.add_argument("--ratio", default="")
    r.add_argument("--duration", type=int, default=0)
    r.add_argument("--resolution", default="")
    r.add_argument("-j", "--jobs", type=int, default=0, help="并发数")
    r.add_argument("--repeat", type=int, default=1, help="每条出几张")
    r.add_argument("--retry", type=int, default=None)
    r.add_argument("--out", default="", help="输出目录")
    r.add_argument("--no-skip", action="store_true", help="成品已存在也重跑")

    args = ap.parse_args()
    if args.data_dir:
        paths.set_data_dir(args.data_dir)
    os.makedirs(paths.data_dir(), exist_ok=True)
    return cli(args) if args.cmd == "run" else serve(args)


if __name__ == "__main__":
    sys.exit(main())
