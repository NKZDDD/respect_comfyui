"""Client for authenticated provider relay protocol 1 (shared by Studio and Batch)."""

import base64
import hashlib
import json
import mimetypes
import os
import time
from pathlib import Path

from . import relay_transport, submitted
from .apiutil import TASK_FATAL, ApiError, _atomic_output, _check_saved

PREFIX = "respect-relay-v1|"
CHUNK = 512 * 1024


def route(key):
    return isinstance(key, str) and key.startswith(PREFIX)


def ticket(pid, key):
    _, owner, kid, revision, field = key.split("|")
    return owner, {"provider": pid, "key_id": kid, "revision": revision, "field": field}


def catalog(pid, key):
    owner, params = ticket(pid, key)
    try:
        response = relay_transport.call(owner, "catalog", params)
        rows = response["rows"]
        names = sorted({r["id"] for r in rows})
        return {
            "ok": bool(names),
            "models": names,
            "rows": rows,
            "strict": response.get("strict", False),
            "msg": "服务器已读取模型目录" if names else "服务器返回空模型目录",
        }
    except Exception:  # noqa: BLE001 - one provider's catalogue failure is non-fatal
        return {
            "ok": False,
            "models": [],
            "rows": [],
            "msg": "服务器读取模型目录失败，请检查该服务商的授权与线路",
        }


def catalogs(pid, keys):
    results = [catalog(pid, key) for key in dict.fromkeys(keys)]
    if len(results) == 1:
        return results[0]
    rows = {r["id"]: r for result in results for r in result["rows"]}
    return {
        "ok": bool(rows),
        "models": sorted(rows),
        "rows": list(rows.values()),
        "partial": any(not r["ok"] for r in results),
        "strict": all(r.get("strict") for r in results),
        "msg": "已合并服务器返回的模型目录" if rows else results[0]["msg"],
    }


def inline(ref):
    if ref.startswith(("http://", "https://", "data:")):
        return ref
    path = Path(ref)
    mime = mimetypes.guess_type(path.name)[0]
    if not mime or not mime.startswith("image/"):
        from PIL import Image

        with Image.open(path) as image:
            mime = Image.MIME.get(image.format)
    if not mime:
        raise ApiError("无法识别参考图片格式", kind=TASK_FATAL)
    return "data:" + mime + ";base64," + base64.b64encode(path.read_bytes()).decode()


class Result:
    def __init__(self, owner):
        self.owner = owner

    def save_item(self, job, dest, log=print):
        try:
            with _atomic_output(dest) as part:
                with open(part, "wb") as out:
                    offset = 0
                    while True:
                        chunk = relay_transport.call(self.owner, "read", {"job": job, "offset": offset})
                        data = base64.b64decode(chunk["data"], validate=True)
                        out.write(data)
                        offset += len(data)
                        if offset == chunk["total"] and offset:
                            break
                        if not data or offset > chunk["total"]:
                            raise ValueError("invalid result length")
                _check_saved(part, "relay", extension=os.path.splitext(dest)[1].lower())
        except Exception as exc:
            err = ApiError(
                "转发结果已生成，下载中断。请仅重新下载原任务。",
                kind=TASK_FATAL,
                err_code="result_download_failed",
            )
            err.download_retry = (self, job)
            raise err from exc


def retrieve(owner, job, dest, cancel=None, poll_interval=5, poll_timeout=2400, log=print):
    deadline = time.monotonic() + poll_timeout
    while time.monotonic() < deadline and not (cancel and cancel()):
        try:
            state = relay_transport.call(owner, "status", {"job": job})["state"]
        except Exception as exc:
            raise ApiError(
                f"暂时无法查询转发任务 {job}，请按原任务编号取回",
                kind=TASK_FATAL,
                err_code="submitted_pending",
            ) from exc
        if state == "ready":
            Result(owner).save_item(job, dest, log)
            return {"task_id": job, "source": "server_relay"}
        if state == "failed":
            submitted.discard()
            err = ApiError("服务商明确拒绝了原转发任务", kind=TASK_FATAL, err_code="relay_rejected")
            err.provider_task_failed = True
            raise err
        if state in ("unknown", "upload"):
            break
        time.sleep(max(1, min(poll_interval, 10)))
    raise ApiError(
        f"转发任务 {job} 结果待确认，请按原编号查询",
        kind=TASK_FATAL,
        err_code="submitted_pending",
    )


class Relay:
    per_account_serial = False  # Credentials and upstream concurrency belong to the server.

    def __init__(self, cls, key):
        self.adapter = cls()
        self.owner, self.params = ticket(cls.id, key)

    def __getattr__(self, name):
        return getattr(self.adapter, name)

    def generate(
        self,
        kind,
        task,
        dest,
        log=print,
        cancel=None,
        poll_interval=5,
        poll_timeout=2400,
    ):
        job = relay_transport.event_id()
        log(f"服务器转发任务编号：{job}")
        def call(action, **fields):
            return relay_transport.call(self.owner, action, dict(job=job, **fields))

        try:
            payload = dict(vars(task), refs=[inline(r) for r in task.refs])
            raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
            if len(raw) > 160 * 1024 * 1024:
                raise ApiError("转发任务及参考素材超过 160 MiB，尚未提交生成", kind=TASK_FATAL)
            reply = call(
                "open",
                **self.params,
                kind=kind,
                model=task.model,
                checksum=hashlib.sha256(raw).hexdigest(),
            )
            if reply["state"] == "upload":
                for offset in range(0, len(raw), CHUNK):
                    if cancel and cancel():
                        raise ApiError("转发已停止，尚未生成", kind=TASK_FATAL)
                    data = base64.b64encode(raw[offset : offset + CHUNK]).decode()
                    call("part", offset=offset, data=data)
        except ApiError:
            submitted.discard()
            raise
        except Exception as exc:
            if getattr(exc, "code", "") in ("relay_conflict", "already_submitted"):
                raise ApiError(
                    "已有同编号转发任务，请先核对原任务",
                    kind=TASK_FATAL,
                    err_code="submitted_pending",
                ) from exc
            submitted.discard()
            raise ApiError(
                f"转发准备失败，此次尚未提交生成：{exc}",
                kind=TASK_FATAL,
                err_code="relay_not_submitted",
            ) from exc
        # Record before submit: a lost acknowledgement must never create a new job.
        submitted.remember(job, relay_job=True, owner=self.owner)
        if reply["state"] == "upload":
            deadline = time.monotonic() + poll_timeout
            while True:
                try:
                    call("submit")
                    break
                except Exception as exc:
                    if (
                        getattr(exc, "code", "") == "relay_busy"
                        and time.monotonic() < deadline
                        and not (cancel and cancel())
                    ):
                        time.sleep(3)
                        continue
                    code = getattr(exc, "code", "")
                    if code in (
                        "route_changed",
                        "assignment_changed",
                        "relay_payload",
                        "quota_exhausted",
                        "relay_busy",
                        "relay_unavailable",
                        "quota_event_closed",
                    ):
                        submitted.discard()
                        raise ApiError(str(exc), kind=TASK_FATAL, err_code=code) from exc
                    raise ApiError(str(exc), kind=TASK_FATAL, err_code="submitted_pending") from exc
        return retrieve(self.owner, job, dest, cancel, poll_interval, poll_timeout, log)

    def generate_image(self, task, dest, **kw):
        return self.generate("image", task, dest, **kw)

    def generate_video(self, task, dest, **kw):
        return self.generate("video", task, dest, **kw)

    def resume(self, record, dest, **kw):
        if not record.get("resume", {}).get("relay_job"):
            raise ApiError(
                "这条旧任务由直连提交。请从原服务商取回，或恢复原直连线路后续查。",
                kind=TASK_FATAL,
                err_code="submitted_pending",
            )
        return retrieve(self.owner, record["task_id"], dest, **kw)
