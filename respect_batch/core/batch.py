# -*- coding: utf-8 -*-
"""批量并发跑批。一份任务清单进去，成品 + manifest 出来。

**这是整个程序存在的理由。** ComfyUI 一次只推进一个节点，一条视频几分钟，
排 20 条就串行等 20 次；这里 20 条同时发出去，总耗时约等于最慢那一条。

四条纪律，都是「少了会花冤枉钱」的那种：

  1. **成品已存在就跳过**。跑批中断重来是常态，重跑一遍等于再付一次钱。
  2. **只重试技术失败**。内容被拒（提示词违规）、余额不足、密钥错 —— 重试
     多少次都一样，还各扣一次。按 apiutil 的 kind 分：只有 retryable 才重投。
  3. **有的家一次都不能重投**。小霸龙文档原文：创建 POST 只能提交一次、
     客户端不得自动重试 —— 网络超时也可能已经越过计费边界。见 NO_RETRY。
  4. **整批致命就整批停**。余额耗尽 / 密钥失效时，剩下 200 条挨个去撞没有意义，
     只会把日志刷满，真正的原因反而被埋掉。
"""

from __future__ import annotations

import os
import hashlib
import random
import re
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from typing import Callable, Optional

from . import accounts, config, distribution, paths, providers, refs, release, task_history
from .apiutil import BATCH_FATAL, RETRYABLE, TASK_FATAL, ApiError
from .limits import GATE, CancelledWhileWaiting
from .providers.base import ImageTask, VideoTask
from .store import append_jsonl, write_json

# 这几家的创建请求**一次都不能重投**（文档明写按次计费、不得自动重试）。
# 重投的代价不是报错，是**再扣一次钱**，而且你不会知道。
NO_RETRY = {"xiaobalong"}

_SAFE = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _safe_name(text: str, fallback: str) -> str:
    s = _SAFE.sub("_", (text or "").strip())[:60].strip(" .")
    return s or fallback


class Task:
    """一条任务。`dest` 一开始就定死 —— 「已存在就跳过」靠的就是它稳定。"""

    __slots__ = ("idx", "kind", "provider", "model", "prompt", "refs", "dest",
                 "size", "ratio", "duration", "resolution", "extra",
                 "status", "error", "error_kind", "meta", "started", "ended",
                 "attempts", "usage", "download_retry", "history_sequence")

    def __init__(self, idx: int, kind: str, provider: str, model: str, prompt: str,
                 refs_: list, dest: str, *, size: str = "", ratio: str = "",
                 duration: int = 0, resolution: str = "",
                 extra: Optional[dict] = None):
        self.idx, self.kind, self.provider, self.model = idx, kind, provider, model
        self.prompt, self.refs, self.dest = prompt, list(refs_ or []), dest
        self.size, self.ratio = size, ratio
        self.duration, self.resolution = duration, resolution
        self.extra = dict(extra or {})
        self.status = "待跑"
        self.error = ""
        self.error_kind = ""
        self.meta: dict = {}
        self.started = self.ended = 0.0
        self.attempts = 0
        self.usage = None
        self.download_retry = None
        self.history_sequence = 0

    def row(self) -> dict:
        return {"idx": self.idx, "kind": self.kind, "provider": self.provider,
                "model": self.model, "prompt": self.prompt[:200],
                "refs": self.refs, "dest": self.dest, "status": self.status,
                "error": self.error, "error_kind": self.error_kind,
                "attempts": self.attempts, "meta": self.meta,
                "can_retry_download": bool(self.download_retry) and self.status == '失败',
                "usage": self.usage,
                "seconds": round((self.ended or time.time()) - self.started, 1)
                if self.started else 0}


# ------------------------------------------------------------------ 清单展开

def parse_lines(text: str) -> list:
    """一行一条。可选用 `|` 分段：`提示词 | 参考图1;参考图2 | 输出文件名`

    空行和 `#` 开头的行跳过 —— 方便把不要的那几条注释掉重跑，而不是删掉
    （删掉之后就再也想不起来当时写的是什么）。

    ⚠ **这套语法只服务命令行**（`run.py run --file`），那条路的用户是写脚本的。
    界面走的是 `spec["tasks"]` 结构化清单，不要求任何人知道 `|` `;` `#`。
    用户原话：「不要训练用户去用什么换行啊本地地址什么的」。
    """
    rows = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        prompt = parts[0]
        if not prompt:
            continue
        refs_ = [r.strip() for r in (parts[1] if len(parts) > 1 else "").split(";")
                 if r.strip()]
        name = parts[2] if len(parts) > 2 else ""
        rows.append({"prompt": prompt, "refs": refs_, "name": name})
    return rows


def _rows_of(spec: dict) -> list:
    """清单：界面给的结构化优先，没有才回落命令行那套文本语法。"""
    raw = spec.get("tasks")
    if isinstance(raw, list) and raw:
        rows = []
        for r in raw:
            prompt = str((r or {}).get("prompt") or "").strip()
            if not prompt:
                continue          # 空卡片当没填，不当成一条任务发出去
            rows.append({
                "prompt": prompt,
                "refs": [str(x).strip() for x in ((r or {}).get("refs") or [])
                         if str(x).strip()],
                "name": str((r or {}).get("name") or "").strip(),
                "output_folder": r.get("output_folder", ""),
            })
        return rows
    return parse_lines(spec.get("lines") or "")


def _output_root(spec: dict) -> str:
    return os.path.abspath(os.path.expanduser(spec.get("out_dir") or paths.default_out_dir()))


def _valid_folder_name(name: str) -> bool:
    return bool(name and not name.endswith((" ", "."))
                and not re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
                and not re.fullmatch(r'(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[1-9¹²³])',
                                     name.partition(".")[0].rstrip(), re.I)
                and len(name.encode("utf-16-le", errors="surrogatepass")) <= 510)


def _output_directory(root: str, folder: str) -> str:
    if folder == "":
        return root
    if not isinstance(folder, str) or "\x00" in folder:
        raise ValueError("请填写有效的成品子文件夹名或完整目录路径")
    path = Path(folder)
    if path.is_absolute():
        if os.name == "nt":
            # Accept drive paths and network shares. Device namespaces are not folders.
            drive = path.drive
            if drive.startswith("\\\\?\\UNC\\"):
                drive = "\\\\" + drive[8:]
            elif drive.startswith("\\\\?\\"):
                drive = drive[4:]
            share = drive.removeprefix("\\\\").split("\\")
            if not (re.fullmatch(r"[a-zA-Z]:", drive) or
                    (drive.startswith("\\\\") and len(share) == 2 and all(_valid_folder_name(s) for s in share))):
                raise ValueError("请选择有效的磁盘文件夹或网络共享文件夹")
            if any(not _valid_folder_name(part) for part in path.parts[1:]):
                raise ValueError("成品文件夹路径中包含无效的文件夹名")
        return os.path.normpath(folder)
    if not _valid_folder_name(folder):
        raise ValueError("请填写单个成品子文件夹名，或选择完整的目标文件夹路径")
    directory = os.path.join(root, folder)
    if os.path.normcase(os.path.dirname(os.path.realpath(directory))) != os.path.normcase(os.path.realpath(root)):
        raise ValueError("成品子文件夹必须位于所选成品目录内")
    return directory


def build_tasks(spec: dict) -> list:
    """把界面上填的东西展开成任务清单。

    「每条出几张」展开成**几条独立任务**，而不是给服务商传 n=N：
    一条失败不牵连另一条，重跑也只重跑失败的那一张。多花的只是几次请求，
    换来的是失败粒度 —— n=4 里坏一张，整条都得重来，等于白付三张的钱。

    清单有两个来源，**结构化的优先**：
      · `spec["tasks"]`  界面给的 `[{prompt, refs, name}]` —— 没有任何语法
      · `spec["lines"]`  命令行给的一行一条文本，见 `parse_lines`
    另外 `spec["refs"]` 是**这一批共用的参考图**，会拼在每条自己的参考图前面
    （同一个角色出 20 个动作，图只拖一次）。
    """
    kind = spec.get("kind") or "image"
    provider = spec.get("provider") or ""
    model = spec.get("model") or ""
    out_dir = _output_root(spec)
    ext = ".png" if kind == "image" else ".mp4"
    repeat = max(1, int(spec.get("repeat") or 1))
    shared = [str(r).strip() for r in (spec.get("refs") or []) if str(r).strip()]
    # 每库每条只取一张，顺序循环或每条独立随机。
    slots = [[str(r).strip() for r in pool if str(r).strip()]
             for pool in (spec.get("ref_slots") or [])]
    pick_mode = spec.get("ref_pick_mode") or "sequence"
    if pick_mode not in ("sequence", "random"):
        raise ValueError("素材库配图方式只能是顺序循环或随机抽取")

    rows = _rows_of(spec)
    tasks, idx = [], 0
    for i, row in enumerate(rows, 1):
        destination_dir = _output_directory(out_dir, row.get("output_folder", ""))
        # 共用的在前、这条自己的在后 —— 顺序就是各家的「图1、图2」，
        # 反过来会让「@Image1 指谁」变掉，而那不会报错，只是出来的不对。
        row_refs = shared + [r for r in row["refs"] if r not in shared]
        for k in range(repeat):
            idx += 1
            picked = [(random.choice(pool) if pick_mode == "random"
                       else pool[(idx - 1) % len(pool)]) for pool in slots if pool]
            stem = row["name"] or _safe_name(row["prompt"], f"{idx:04d}")
            if repeat > 1:
                stem = f"{stem}_{k + 1}"
            # 前面无条件带序号：重名会互相覆盖，而覆盖之后你以为跑了 20 条、
            # 硬盘上只有 12 个文件，状态还全是「完成」。
            dest = os.path.join(destination_dir, f"{i:03d}_{stem}{ext}")
            tasks.append(Task(
                idx, kind, provider, model, row["prompt"], row_refs + picked, dest,
                size=spec.get("size") or "", ratio=spec.get("ratio") or "",
                duration=int(spec.get("duration") or 0),
                resolution=spec.get("resolution") or "",
                extra={**(spec.get("extra") or {}),
                       **({"resolution": spec["resolution"]} if kind == "image" and spec.get("resolution") else {}),
                       **({"video_refs": list(spec["video_refs"])} if kind == "video" and spec.get("video_refs") else {})}))
    return tasks


# ------------------------------------------------------------------ 一次跑批

class Run:
    """一次跑批的全部状态。页面每秒拉一次 `snapshot()`。"""

    def __init__(self, tasks: list, spec: dict, cfg: dict):
        self.id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:12]
        self.submission_id = None
        self.tasks = tasks
        self.spec = spec
        self.out_dir = _output_root(spec)
        self.output_dirs = list(dict.fromkeys(os.path.dirname(t.dest) for t in tasks))
        self.label = spec.get("model") or spec.get("provider") or ""
        self.account_pool = None
        self.output_route = (spec.get("kind"), spec.get("provider"), spec.get("model"),
                             cfg.get("_usage", {}).get("key_id"))
        self.cfg = cfg
        self._private_profile = distribution.profile() if distribution.ENABLED else None
        self.status = "排队中"
        self.message = ""
        # 整批致命是否已触发。**它不能直接把 status 改成终态** ——
        # 线程池这时还在收尾，剩下的任务还没标完。谁按 status 判断"跑完了"
        # （命令行那个循环、任何轮询脚本），读到的就是一份半截的统计，
        # 并据此定退出码。终态只由 go() 在池子排干之后定这一处。
        self.stopped = False
        self.started = time.time()
        self.ended = 0.0
        self._cancel = threading.Event()
        self._lock = threading.RLock()
        self.logs: list = []
        self.log_path = os.path.join(paths.runs_dir(), self.id, "log.jsonl")
        self.manifest_path = os.path.join(paths.runs_dir(), self.id, "manifest.json")

    # -- 日志 ---------------------------------------------------------
    def log(self, text: str, idx: int = 0) -> None:
        text = release.redact(text, self._private_profile)
        row = {"t": time.strftime("%H:%M:%S"), "idx": idx, "text": str(text)}
        with self._lock:
            self.logs.append(row)
            # 页面也看不过来更多，别把内存吃光；落盘那份是全的，不丢东西
            if len(self.logs) > 4000:
                del self.logs[:1000]
        try:
            append_jsonl(self.log_path, row)
        except Exception:                                   # noqa: BLE001
            pass

    def cancel(self) -> None:
        self._cancel.set()
        self.log("已请求停止 —— 在跑的那几条会跑完（钱已经花了，扔掉最亏），不再发新的。")

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # -- 快照 ---------------------------------------------------------
    def counts(self) -> dict:
        # 「未发」和「失败」**必须分开数**：整批致命（余额不足/密钥失效）时
        # 只有第一条真的发出去了，剩下的一条都没发。混在一起报「失败 20」，
        # 人看到的是"我被扣了 20 次"，然后去查账单查半天 —— 而实际只扣了 1 次。
        c = {"总数": len(self.tasks), "完成": 0, "失败": 0, "未发": 0, "跳过": 0,
             "进行中": 0, "待跑": 0}
        for t in self.tasks:
            c[t.status if t.status in c else "待跑"] += 1
        return c

    def snapshot(self, log_from: int = 0) -> dict:
        with self._lock:
            logs = self.logs[max(0, log_from):]
            total_logs = len(self.logs)
        return release.redact({"id": self.id, "status": self.status, "message": self.message,
                "counts": self.counts(), "tasks": [t.row() for t in self.tasks],
                "logs": logs, "log_total": total_logs,
                "gate": GATE.snapshot(),
                "seconds": round((self.ended or time.time()) - self.started, 1),
                "manifest": self.manifest_path,
                "output_dirs": self.output_dirs,
                "out_dir": self.out_dir if self.tasks else ""}, self._private_profile)

    def write_manifest(self) -> None:
        write_json(self.manifest_path, release.redact({
            "id": self.id, "status": self.status, "message": self.message,
            "account_id": self.cfg.get('_usage', {}).get('owner', ''),
            # spec 里不落 lines（可能几百行）和任何凭据
            # tasks/lines 不落：每条的提示词和参考图在下面 tasks 里已经有了，
            # 重复一份只会让 manifest 大一倍。凭据更是一个字都不能落。
            "spec": {k: v for k, v in self.spec.items()
                     if k not in ("lines", "tasks", "api_key", "proxy")},
            "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started)),
            "seconds": round((self.ended or time.time()) - self.started, 1),
            "counts": self.counts(),
            "tasks": [t.row() for t in self.tasks],
        }, self._private_profile))

    def retry_download(self, idx: int) -> None:
        """Retrieve the current batch's known result; never dispatch generation."""
        with self._lock:
            if self.status not in ('已完成', '已停止'):
                raise ValueError('请等待当前批次完成后再取回结果')
            task = next((t for t in self.tasks if t.idx == idx), None)
            if task is None or not task.download_retry or task.status != '失败':
                raise ValueError('该任务没有可重新下载的结果；请核对原任务记录')
            previous_status = self.status
            self.status, self.message = '下载中', '正在重新下载已有结果，不重新生成'
            task.status, task.error = '进行中', ''
            task.ended = 0

        def retrieve():
            from . import managed_usage, production_diagnostics
            session, source = task.download_retry
            try:
                with production_diagnostics.attempt(self, task, reuse_usage=True):
                    session.save_item(source, task.dest, log=lambda text: self.log(text, task.idx))
                    if task.usage:
                        task.usage = managed_usage.complete_download(
                            self.cfg.get('_usage', {}).get('owner', ''), task.usage)
                task.status, task.error, task.error_kind = '完成', '', ''
                task.download_retry = None
                self.log(f'[{idx}] 原结果已取回，未重新生成', idx)
            except Exception as exc:
                task.status, task.error_kind = '失败', TASK_FATAL
                # The download helper already provides a safe, actionable message.
                task.error = (str(exc) if getattr(exc, 'err_code', '') == 'result_download_failed'
                              else f'重新下载未成功（{type(exc).__name__}），未重新生成；请检查网络和保存目录后再试')
                self.log(f'[{idx}] {task.error}', idx)
            finally:
                task.ended = time.time()
                self.save_history([task])
                with self._lock:
                    self.ended = time.time()
                    self.status = previous_status
                    c = self.counts()
                    self.message = f"完成 {c['完成']}、失败 {c['失败']}。本次操作只下载已有结果。"
                    try:
                        self.write_manifest()
                    except OSError:
                        self.log('任务记录保存失败，请检查磁盘空间；不会重新生成')

        threading.Thread(target=retrieve, daemon=True).start()

    def save_history(self, tasks, status=None):
        try:
            task_history.record(self, tasks, status)
        except Exception:
            self.log('任务中心记录未能写入本机，请检查数据盘可用空间')
            return False
        return True


def _dispatch(prov, task: Task, run: Run, log: Callable, resolved: list) -> dict:
    """按 kind 调对应的生成方法。参考图已经是这一家要的形式了。"""
    if task.kind == "image":
        t = ImageTask(prompt=task.prompt, refs=resolved,
                      size=task.size or "1024x1536", model=task.model,
                      n=1, extra=task.extra)
        return prov.generate_image(
            t, task.dest, log=log, cancel=run.cancelled,
            poll_timeout=int(run.spec.get("poll_timeout") or 900)) or {}
    extra = dict(task.extra)
    if extra.get("video_refs"):
        from .uploader import video_to_url
        extra["video_refs"] = [video_to_url(v, run.cfg.get("upload") or {}, log=log)
                               for v in extra["video_refs"]]
    t = VideoTask(prompt=task.prompt, refs=resolved,
                  duration=task.duration or 5, ratio=task.ratio or "9:16",
                  model=task.model, resolution=task.resolution, extra=extra)
    return prov.generate_video(
        t, task.dest, log=log, cancel=run.cancelled,
        poll_timeout=int(run.spec.get("poll_timeout") or 2400)) or {}


def _tracked_dispatch(prov, task, run, log, resolved):
    from . import managed, managed_usage
    assignment = run.cfg.get('_usage')
    if assignment:
        try:
            managed.manager.authorize_task(assignment)
        except managed.LoginRequired as exc:
            task.status = '未发'
            raise ApiError(str(exc), kind=BATCH_FATAL) from None
    with managed_usage.tracking(assignment, task):
        if run.cfg.get('_adapter_sha256'):
            # Some downloaded adapters use their own HTTP client. Reserve the
            # attempt before entering their code so those calls are counted too.
            managed_usage.begin()
        result = _dispatch(prov, task, run, log, resolved)
        task.meta = result or {}
        return result


def _execute(run: Run, task: Task, prov, resolve: Callable, max_retry: int) -> None:
    """跑一条。重试在这个 worker 内串行，**不额外占并发槽** ——
    占槽的话重试期间别人进不来，一条难产的任务能把整批的吞吐拖下去。
    """
    task.started = time.time()

    # 成品已存在 → 跳过。**放在最前面**，连参考图都不用解析、不用占槽。
    if run.spec.get("skip_existing", True) and os.path.isfile(task.dest) \
            and os.path.getsize(task.dest) > 512:
        task.status = "跳过"
        task.ended = time.time()
        run.log(f"[{task.idx}] 已存在，跳过：{os.path.basename(task.dest)}", task.idx)
        return

    try:
        os.makedirs(os.path.dirname(task.dest) or ".", exist_ok=True)
    except OSError as exc:
        task.status, task.ended = "未发", time.time()
        task.error = f"无法创建成品目录：{exc}"
        run.log(task.error, task.idx)
        return
    task.status = "进行中"
    if run.cfg.get('_usage'):
        run.save_history([task])

    def log(*a):
        run.log(" ".join(str(x) for x in a), task.idx)

    limit = 1 if task.provider in NO_RETRY else max(1, max_retry + 1)

    for attempt in range(1, limit + 1):
        task.attempts = attempt
        if run.cancelled():
            # 没发出去 ≠ 失败。钱没花、服务商那边没有这条记录，重跑它是安全的。
            task.status = "未发"
            task.error = "整批已停，这一条没有发出去（没扣钱，可以直接重跑）"
            task.ended = time.time()
            return
        try:
            from . import production_diagnostics
            with production_diagnostics.attempt(run, task):
                # 参考图解析放在重试圈**里面**：上传失败也是可重试的技术失败
                if run.cfg.get('_usage'):
                    from . import managed
                    try:
                        managed.manager.authorize_task(run.cfg['_usage'])
                    except managed.LoginRequired as exc:
                        task.status = '未发'
                        raise ApiError(str(exc), kind=BATCH_FATAL) from None
                production_diagnostics.stage('references')
                resolved = [resolve(r, log) for r in task.refs]
                production_diagnostics.stage('submit')

                pool = getattr(run, "account_pool", None)
                account_slot = pool.slot(log=log, cancel=run.cancelled) if pool else nullcontext(None)
                with account_slot as acct, GATE.slot(task.provider, cancel=run.cancelled):
                    if run.cancelled():
                        raise CancelledWhileWaiting("此批次已停止，任务尚未提交")
                    p = prov
                    if acct:
                        p = providers.build(task.provider, acct.api_key,
                                            run.spec.get("base_url") or "", run.spec.get("proxy") or "",
                                            int(run.spec.get("timeout") or 900),
                                            adapter_sha256=run.cfg.get('_adapter_sha256', ''))
                    meta = _tracked_dispatch(p, task, run, log, resolved)
                    if acct:
                        accounts.bump(task.provider, acct.label)

            task.meta = meta or {}
            task.status = "完成"
            task.ended = time.time()
            log(f"[{task.idx}] 完成 {os.path.basename(task.dest)}"
                f"（{round(task.ended - task.started, 1)}s）")
            return

        except CancelledWhileWaiting as exc:
            task.status, task.error, task.ended = "未发", str(exc), time.time()
            return
        except ApiError as exc:
            task.error, task.error_kind = str(exc), exc.kind
            if getattr(exc, 'download_retry', None):
                task.download_retry = exc.download_retry
                task.status, task.ended = '失败', time.time()
                log(f'[{task.idx}] {task.error}')
                return
            if task.usage and task.usage['status'] in ('pending', 'unknown'):
                task.status = '失败'
                task.ended = time.time()
                task.error = '结果待确认，未自动重新生成。请按任务记录核对；' + str(exc)
                log(f'[{task.idx}] {task.error}')
                return
            if exc.kind == BATCH_FATAL:
                # 整批性质的（余额没了、密钥失效）：剩下的挨个去撞没有意义
                if task.status != '未发':
                    task.status = "失败"
                task.ended = time.time()
                run.stopped = True
                run.message = f"整批停止：{exc}"
                run._cancel.set()
                log(f"[{task.idx}] 整批致命，后续任务不再发：{exc}")
                return
            if exc.kind != RETRYABLE or attempt >= limit:
                task.status = "失败"
                task.ended = time.time()
                if task.provider in NO_RETRY and exc.kind == RETRYABLE:
                    why = ("这一家按次计费、文档明写不得自动重试，所以只发了一次。"
                           "要重跑请自己确认没扣过钱")
                    # **这句话必须进 task.error，不能只进日志。** 只进日志的话，
                    # manifest 和页面上的失败原因就只有一句「网络抖了」——
                    # 看的人会以为重试设置坏了，然后手动重跑整批，付两次钱。
                    task.error = f"{exc}（{why}）"
                elif exc.kind == TASK_FATAL:
                    why = "这一条本身的问题，重试没用"
                else:
                    why = f"重试 {attempt} 次都没成"
                log(f"[{task.idx}] 失败（{why}）：{exc}")
                return
            wait = exc.retry_after or min(20, 3 * attempt)
            log(f"[{task.idx}] 第 {attempt} 次失败，{wait:.0f} 秒后重试：{exc}")
            time.sleep(wait)

        except Exception as exc:                            # noqa: BLE001
            task.status = "失败"
            task.error = ("程序处理失败，请联系 Respect 支持" if distribution.ENABLED
                          else f"{type(exc).__name__}: {exc}")
            task.error_kind = "程序内部错误"
            task.ended = time.time()
            log(f"[{task.idx}] {task.error}" if distribution.ENABLED
                else f"[{task.idx}] 程序内部错误：{exc}\n{traceback.format_exc()}")
            return


def _separate_outputs(run: Run, previous_runs) -> None:
    """不同模型同名时保留各自成品，同一模型重复提交也不能覆盖仍在写的文件。"""
    reserved, other_models = set(), set()
    for previous in previous_runs:
        active = previous.status in ("排队中", "跑批中", "下载中")
        for task in previous.tasks:
            path = os.path.normcase(os.path.realpath(task.dest))
            if active or task.download_retry:
                reserved.add(path)
            if previous.output_route != run.output_route and (active or task.download_retry or task.status in ("完成", "跳过")):
                other_models.add(path)
    route_tag = hashlib.sha256(repr(run.output_route).encode()).hexdigest()[:12]
    for task in run.tasks:
        stem, ext = os.path.splitext(task.dest)
        model_path = f"{stem}_{route_tag}{ext}"
        path = os.path.normcase(os.path.realpath(task.dest))
        if path in other_models or os.path.isfile(model_path):
            task.dest = model_path
            path = os.path.normcase(os.path.realpath(model_path))
        if path in reserved:
            task.dest = f"{stem}_{run.id}{ext}"


def start(spec: dict, cfg: dict, *, previous_runs=()) -> Run:
    """展开任务、配好三层闸、开跑。立刻返回，实际执行在后台线程。"""
    public_model = spec.get("model")
    if distribution.ENABLED:
        spec, cfg = release.prepare(spec)
    tasks = build_tasks(spec)
    run = Run(tasks, spec, cfg)
    if distribution.ENABLED:
        run.label = next((m["label"] for m in run._private_profile["models"] if m["id"] == public_model), "所选模型")
    else:
        run.label = " · ".join(filter(None, (spec.get("provider"), spec.get("model"))))
    _separate_outputs(run, previous_runs)

    def stop_now(msg: str) -> Run:
        run.status, run.message = "已停止", msg
        run.ended = time.time()
        run.log(msg)
        run.save_history(tasks, '未发')
        return run

    if not tasks:
        return stop_now("一条任务都没有 —— 至少填一条提示词再开跑。")

    pid = spec.get("provider") or ""
    kind = spec.get("kind") or "image"

    # **「这家做不做这个」要排在「有没有密钥」前面。** 支持什么是类属性，
    # 不需要密钥就知道；排在后面的话，选错家的人先被告知"去填密钥"，
    # 填完再撞一次才知道这家根本不做出图 —— 两次都答非所问。
    cls = providers.get_class(pid, cfg.get('_adapter_sha256', ''))
    if not cls:
        return stop_now(f"没有「{pid}」这家。可用：{'、'.join(providers.REGISTRY)}")
    sup = tuple(getattr(cls, "supports", ()))
    if kind not in sup:
        return stop_now(
            f"{getattr(cls, 'name', pid)} 不做{'出图' if kind == 'image' else '出视频'}"
            f"（它支持：{'、'.join(sup) or '无'}）。换一家，或者换任务类型。")

    pcfg = config.provider_cfg(cfg, pid)
    api_key = (spec.get("api_key") or pcfg.get("api_key") or "").strip()
    spec["base_url"] = (spec.get("base_url") or pcfg.get("base_url") or "").strip()
    spec["proxy"] = (spec.get("proxy") or pcfg.get("proxy") or "").strip()
    spec.pop("api_key", None)          # 别留在 spec 里，manifest 会落盘

    if not api_key:
        return stop_now(f"「{pid}」还没填密钥。去「设置」填上，"
                        f"或者设环境变量 RESPECT_{pid.upper()}_API_KEY。")

    limits = cfg.get("limits") or {}
    GATE.configure(int(limits.get("global") or 8), limits.get("per_provider") or {})

    try:
        prov = providers.build(pid, api_key, spec["base_url"], spec["proxy"],
                               int(spec.get("timeout") or 900), adapter_sha256=cfg.get('_adapter_sha256', ''))
    except Exception as exc:                                # noqa: BLE001
        return stop_now(f"服务商建不起来：{exc}")

    if spec.get("ref_slots") and not distribution.ENABLED:
        caps = prov.capabilities().get(kind) or {}
        options = (caps.get("model_options") or {}).get(spec.get("model")) or {}
        max_refs = options.get("max_refs", caps.get("max_refs", 0))
        if max_refs and any(len(t.refs) > max_refs for t in tasks):
            return stop_now(f"这个模型每条最多 {max_refs} 张参考图，共用图、单条图和"
                            "各素材库取出的图合计超限。请减少参考图或素材库后再跑。")

    # 按账号串行的家：并发上限 = 账号数，而这个数只有从密钥文本里才解得出来，
    # 配置里那张 per_provider 表不知道它。不设的话会有多条挤在同一个账号上 ——
    # 表现不是报错，是那一家直接拒或排队超时，失败记录只会说「生成失败」。
    if getattr(prov, "per_account_serial", False):
        run.account_pool = accounts.configured_pool(pid, api_key)
        n = len(run.account_pool)
        if not n:
            return stop_now("未找到可用账号凭据")
        run.log(f"{prov.name} 按账号计费、一个账号同时只能跑一条 —— 当前 {n} 个账号，"
                f"就是 {n} 路并发，其余排队。想更快就在设置里多粘几个账号。")

    media = "image" if kind == "image" else "video"
    side, fmt = refs.rules_for(prov, media,
                               int(pcfg.get("ref_max_side") or 0),
                               str(pcfg.get("ref_format") or ""))
    resolve = refs.make_resolver(prov, spec.get("model") or "", media,
                                 refs.upload_config(cfg, spec.get("provider") or ""), side, fmt)

    workers = max(1, int(spec.get("concurrency") or 4))
    max_retry = int(spec.get("max_retry") or 0)
    if pid in NO_RETRY and max_retry > 0:
        run.log(f"{prov.name} 的创建请求按次计费、文档明写不得自动重试 —— "
                f"这一批每条只发一次，「失败重试」那个数对它不生效。")

    try:
        for directory in run.output_dirs:
            os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        return stop_now(f"无法创建成品目录：{exc}")

    if not run.save_history(tasks):
        return stop_now('无法暂存本批任务记录，释放客户端数据盘空间后再提交')

    def worker(t: Task) -> None:
        try:
            _execute(run, t, prov, resolve, max_retry)
        finally:
            run.save_history([t])
            try:
                run.write_manifest()      # 每条落一次：中途被强杀也留得下结果
            except Exception:             # noqa: BLE001
                pass

    def go() -> None:
        run.status = "跑批中"
        destinations = run.output_dirs[0] if len(run.output_dirs) == 1 else f"{len(run.output_dirs)} 个成品目录"
        run.log(f"开跑：{len(tasks)} 条，{workers} 路并发，{run.label}，输出到 {destinations}")
        try:
            budget = GATE.batch_limit(run.id, workers) if distribution.ENABLED else nullcontext()
            with budget, ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(worker, tasks))
        except Exception as exc:                            # noqa: BLE001
            run.message = f"跑批异常：{exc}"
            run.log(run.message)
        run.ended = time.time()
        c = run.counts()
        run.status = "已停止" if (run.stopped or run.cancelled()) else "已完成"
        if not run.message:
            parts = [f"完成 {c['完成']}", f"失败 {c['失败']}"]
            if c["未发"]:
                parts.append(f"未发 {c['未发']}（没扣钱）")
            if c["跳过"]:
                parts.append(f"跳过 {c['跳过']}")
            run.message = "、".join(parts) + f"，共 {round(run.ended - run.started, 1)} 秒。"
        run.log(run.message)
        run.write_manifest()

    threading.Thread(target=go, daemon=True).start()
    return run
