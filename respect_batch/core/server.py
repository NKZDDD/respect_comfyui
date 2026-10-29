# -*- coding: utf-8 -*-
"""本地 HTTP 服务 + 单页界面。只监听 127.0.0.1。

为什么是浏览器界面而不是 Tk 窗口：这个程序要显示的是**一张会动的表**
（几十上百条任务各自的状态、耗时、失败原因）加一片滚动日志。
HTML 画这个是几十行，Tk 画这个是几百行还不好看。

为什么只绑 127.0.0.1：页面上有密钥。绑 0.0.0.0 等于把同一个局域网里
所有人都放进设置页 —— 而这件事不会有任何提示。
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import (accounts, assets, batch, config, distribution, paths, providers,
               release, templates, uploader, model_catalog, managed, updates)

# 当前这一次跑批。**故意只留一个**：并发在批内部，不在批之间。
# 允许同时开几批的话，三层闸还是全局的，两批会互相抢槽，
# 而页面上各自显示自己的进度，看起来像"变慢了"却查不出原因。
_RUN: dict = {"cur": None}
_LOCK = threading.RLock()
_SESSION = secrets.token_urlsafe(32)
PERSONAL = False


def _json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "RespectBatch"

    def log_message(self, fmt, *args):        # 每个请求刷一行会把日志淹掉
        pass

    # ---------------------------------------------------------------- 基础
    def _send(self, code: int, body: bytes, ctype: str, cookie: str = '') -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass                              # 页面刷新时正常发生，不是错

    def _ok(self, obj) -> None:
        self._send(200, _json_bytes(release.redact(obj)), "application/json; charset=utf-8")

    def _err(self, msg: str, code: int = 400) -> None:
        self._send(code, _json_bytes({"ok": False, "msg": release.redact(str(msg))}),
                   "application/json; charset=utf-8")

    def _release_access(self, route: str, post: bool = False) -> bool:
        if not distribution.ENABLED and not PERSONAL:
            return True
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        def deny(message, code=403):
            # Windows 在关闭仍有未读请求体的连接时会发 RST，吞掉 403 响应。
            # 只排空有界的小请求，不解析或执行被拒绝的内容。
            if post:
                previous_timeout = self.connection.gettimeout()
                try:
                    size = int(self.headers.get("Content-Length") or 0)
                    if 0 < size <= 1024 * 1024:
                        self.connection.settimeout(2)
                        self.rfile.read(size)
                except (ValueError, OSError):
                    pass
                finally:
                    self.connection.settimeout(previous_timeout)
            self._err(message, code)
            return False
        if (self.headers.get("Host") not in hosts or
                self.headers.get("Origin") not in (None, *[f"http://{h}" for h in hosts])):
            return deny("请从本程序打开的页面操作")
        allowed = ({"/api/upload", "/api/start", "/api/cancel", "/api/pick_dir", "/api/open"}
                   if post else {"/", "/index.html", "/api/boot", "/api/run", "/api/file"})
        if managed.enabled():
            allowed |= ({'/api/auth/login', '/api/auth/logout', '/api/auth/refresh'} if post else {'/api/auth/status'})
            allowed |= ({'/api/updates/check', '/api/updates/download', '/api/updates/install'} if post else {'/api/updates/status'})
        if distribution.ENABLED and route not in allowed:
            return deny("发行版未开放此功能")
        if (post or route in ("/api/boot", "/api/run")) and not secrets.compare_digest(
                self.headers.get("X-Respect-Session", ""), _SESSION):
            return deny("页面已失效，请重新打开程序页面")
        if managed.enabled() and not route.startswith('/api/updates/') and route not in ('/', '/index.html', '/api/auth/login', '/api/auth/status'):
            try:
                # Logout still works when offline; refresh can recover an expired grant.
                if route in ('/api/auth/logout', '/api/auth/refresh'):
                    if not managed.manager.matches(self.headers.get('Cookie')):
                        raise managed.LoginRequired()
                else:
                    managed.manager.require(self.headers.get('Cookie'), force=route == '/api/start')
                current = _RUN['cur']
                if route in ('/api/run', '/api/cancel', '/api/open') and current and current.cfg.get('_usage', {}).get('owner') != (managed.manager.user or {}).get('id'):
                    raise managed.LoginRequired('该批次属于另一个账号，请切回原账号查看', 'run_owner_mismatch', 403)
            except managed.LoginRequired as exc:
                return deny(str(exc), exc.status)
        return True

    def _body(self) -> dict:
        """请求体解析失败要**响亮地失败**。

        原来这里 except 掉返回 `{}` —— 于是一个发坏了的请求会变成"空的 spec"，
        跑批那边照常受理、报一句「任务清单是空的」。人会回去检查自己那一屏
        提示词（明明写着），怎么都查不到是请求根本没送到。
        """
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0 or n > 8 * 1024 * 1024:
            raise ValueError('请求内容过大')
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except UnicodeDecodeError as exc:
            raise ValueError(f"请求体不是合法 UTF-8（{exc}）—— "
                             f"命令行调接口时中文容易在这一步被终端编码弄坏，"
                             f"改成 --data-binary @文件 发") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"请求体不是合法 JSON：{exc}") from exc

    # ---------------------------------------------------------------- GET
    def do_GET(self) -> None:                               # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._release_access(u.path):
            return
        try:
            if u.path == '/api/updates/status' and managed.enabled():
                return self._ok({'ok': True, **updates.manager.status()})
            if u.path == '/api/auth/status' and managed.enabled():
                return self._ok(managed.manager.status(self.headers.get('Cookie')))
            if u.path in ("/", "/index.html"):
                if distribution.ENABLED:
                    page = distribution.page().replace(b"__RELEASE_SESSION__", _SESSION.encode())
                else:
                    with open(paths.res("web", "index.html"), "rb") as f:
                        page = f.read()
                    if PERSONAL:
                        page = page.replace(b"__RELEASE_SESSION__", _SESSION.encode())
                return self._send(200, page, "text/html; charset=utf-8")

            if u.path == "/api/boot":
                if distribution.ENABLED:
                    return self._ok(release.public_boot())
                cfg = config.load()
                return self._ok({
                    "ok": True,
                    "providers": model_catalog.capabilities(cfg),
                    "status": providers.status(),
                    "config": config.masked(cfg),
                    "data_dir": paths.data_dir(),
                    "default_out_dir": paths.default_out_dir(),
                    "templates": templates.load(),
                    "upload_ready": uploader.configured(cfg.get("upload") or {}),
                })

            if u.path == "/api/run":
                with _LOCK:
                    run = _RUN["cur"]
                if not run:
                    return self._ok({"ok": True, "idle": True})
                frm = int((q.get("log_from") or ["0"])[0])
                return self._ok({"ok": True, "idle": False,
                                 **run.snapshot(log_from=frm)})

            if u.path == "/api/file":
                # 只放行 uploads 目录里的 —— 不限制的话这个进程就成了
                # 本机文件读取器，而浏览器里任何页面都能往 127.0.0.1 发请求。
                path = (q.get("path") or [""])[0]
                if not assets.readable(path):
                    return self._err("这个文件不给看", 403)
                with open(path, "rb") as f:
                    return self._send(200, f.read(), assets.content_type(path))

            return self._err("没有这个地址", 404)
        except FileNotFoundError as exc:
            return self._err(f"找不到界面文件：{exc}", 500)
        except Exception as exc:                            # noqa: BLE001
            if not distribution.ENABLED:
                traceback.print_exc()
            return self._err(f"{type(exc).__name__}: {exc}", 500)

    # ---------------------------------------------------------------- POST
    def do_POST(self) -> None:                              # noqa: N802
        u = urlparse(self.path)
        if not self._release_access(u.path, post=True):
            return

        # 上传走**裸字节**，必须在 _body() 之前拦掉 —— 它会把同一个流当 JSON 读，
        # 读完之后字节就没了。文件名放 query 里（不进 body），省一个 multipart 解析器。
        if u.path == "/api/upload":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = self.rfile.read(n) if n else b""
                name = unquote((parse_qs(u.query).get("name") or [""])[0])
                return self._ok({"ok": True, **assets.save(data, name)})
            except ValueError as exc:
                return self._err(str(exc), 400)
            except Exception as exc:                        # noqa: BLE001
                if not distribution.ENABLED:
                    traceback.print_exc()
                return self._err(f"存不下这张图：{exc}", 500)

        try:
            body = self._body()
        except ValueError as exc:
            return self._err(str(exc), 400)
        try:
            if managed.enabled() and u.path.startswith('/api/updates/'):
                if u.path == '/api/updates/check':
                    return self._ok({'ok': True, **updates.manager.check()})
                if u.path == '/api/updates/download':
                    return self._ok({'ok': True, **updates.manager.download()})
                if u.path == '/api/updates/install':
                    with _LOCK:
                        return self._ok({'ok': True, **updates.manager.install(_RUN['cur'])})
            if managed.enabled() and u.path.startswith('/api/auth/'):
                with _LOCK:
                    if u.path != '/api/auth/login' and not managed.manager.matches(self.headers.get('Cookie')):
                        raise managed.LoginRequired()
                    current = _RUN['cur']
                    if current and current.status in ('跑批中', '排队中'):
                        raise ValueError('请先停止新任务并等待当前批次收尾，再刷新配置或切换账号')
                    if u.path == '/api/auth/login':
                        token = managed.manager.login(body)
                        _RUN['cur'] = None
                        return self._send(200, _json_bytes({'ok': True}), 'application/json; charset=utf-8',
                            f'{managed.COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/')
                    if u.path == '/api/auth/refresh':
                        managed.manager.verify(refresh_models=True)
                        return self._ok({'ok': True})
                    if u.path == '/api/auth/logout':
                        managed.manager.logout(self.headers.get('Cookie'))
                        _RUN['cur'] = None
                        return self._send(200, _json_bytes({'ok': True}), 'application/json; charset=utf-8',
                            f'{managed.COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            if u.path == "/api/config":
                cfg = config.apply_from_page(config.load(), body.get("config") or {})
                config.save(cfg)
                return self._ok({"ok": True, "config": config.masked(cfg),
                                 "msg": f"已保存到 {paths.config_path()}"})

            if u.path == "/api/import_studio":
                return self._ok(config.import_from_studio())

            if u.path == "/api/rescan":
                return self._ok({"ok": True, "status": providers.reload_all(),
                                 "providers": model_catalog.capabilities(config.load())})

            if u.path == "/api/models":
                # 实拉这把 Key 能用的模型。一手、无限画布这些家的清单是
                # 接口给的、按 Key 变，写死的列表对它们不准。
                pid = body.get("provider") or ""
                cfg = config.load()
                return self._ok(model_catalog.refresh(pid, cfg))

            if u.path == "/api/selftest":
                pid = body.get("provider") or ""
                cfg = config.load()
                pc = config.provider_cfg(cfg, pid)
                key = (pc.get("api_key") or "").strip()
                if not key:
                    return self._ok({"ok": False, "msg": "这一家还没填密钥"})
                prov = providers.build(pid, key, pc.get("base_url") or "",
                                       pc.get("proxy") or "", 60)
                # 服务商自己的自检优先。统一的「拉模型列表」对凭据不止一把的家
                # 是**假绿灯**：HVTALD 的 WebDAV 账号密码填错，模型列表照样有货。
                own = prov.selftest()
                if own is not None:
                    return self._ok({"ok": bool(own.get("ok")), **own})
                ms = prov.list_models()
                if ms:
                    return self._ok({"ok": True,
                                     "msg": f"连得上，这把 Key 能看到 {len(ms)} 个模型",
                                     "models": ms})
                return self._ok({"ok": False,
                                 "msg": "连上了但一个模型都没拉到 —— 多半是 Key 不对、"
                                        "分组没权限，或者这家没有 /v1/models 端点"})

            if u.path == "/api/upload_selftest":
                cfg = config.load()
                return self._ok(uploader.selftest(cfg.get("upload") or {}))

            if u.path == "/api/pick_dir":
                return self._ok(assets.pick_dir(body.get("start") or ""))

            if u.path == "/api/template_save":
                return self._ok(templates.save_one(body.get("name") or "",
                                                   body.get("spec") or {}))

            if u.path == "/api/template_delete":
                return self._ok(templates.delete(body.get("name") or ""))

            if u.path == "/api/accounts":
                pid = body.get("provider") or ""
                return self._ok({"ok": True, "report": accounts.report(pid)})

            if u.path == "/api/start":
                with _LOCK:
                    if managed.enabled():
                        if updates.manager.status()['phase'] == 'installing':
                            raise ValueError('正在安装更新，请等待程序重新启动')
                        managed.manager.require(self.headers.get('Cookie'))
                    cur = _RUN["cur"]
                    if cur and cur.status in ("跑批中", "排队中"):
                        return self._ok({"ok": False,
                                         "msg": "已经有一批在跑了。要么等它跑完，"
                                                "要么先点「停止」。"})
                    cfg = config.load()
                    spec = dict(body.get("spec") or {})
                    d = cfg.get("defaults") or {}
                    if not distribution.ENABLED:
                        spec.setdefault("out_dir", d.get("out_dir"))
                        spec.setdefault("concurrency", d.get("concurrency", 4))
                        spec.setdefault("max_retry", d.get("max_retry", 2))
                        spec.setdefault("timeout", d.get("timeout", 900))
                        spec.setdefault("skip_existing", d.get("skip_existing", True))
                        spec.setdefault("poll_timeout",
                                        d.get("poll_timeout_image", 900)
                                        if spec.get("kind") == "image"
                                        else d.get("poll_timeout_video", 2400))
                    run = batch.start(spec, cfg)
                    _RUN["cur"] = run
                return self._ok({"ok": True, "id": run.id, **run.snapshot()})

            if u.path == "/api/cancel":
                with _LOCK:
                    run = _RUN["cur"]
                if not run:
                    return self._ok({"ok": False, "msg": "现在没有在跑的批次"})
                run.cancel()
                return self._ok({"ok": True})

            if u.path == "/api/open":
                path = (body.get("path") or "").strip()
                if distribution.ENABLED:
                    cur = _RUN["cur"]
                    allowed = [cur.manifest_path, os.path.dirname(cur.tasks[0].dest)] if cur and cur.tasks else []
                    if os.path.abspath(path) not in [os.path.abspath(p) for p in allowed]:
                        return self._err("只能打开本次任务的成品目录或记录", 403)
                if not path or not os.path.exists(path):
                    return self._ok({"ok": False, "msg": f"路径不存在：{path}"})
                if os.name == "nt":
                    os.startfile(path)                      # noqa: S606
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", path])        # noqa: S603,S607
                else:
                    subprocess.Popen(["xdg-open", path])    # noqa: S603,S607
                return self._ok({"ok": True})

            return self._err("没有这个地址", 404)
        except managed.LoginRequired as exc:
            return self._err(str(exc), exc.status)
        except ValueError as exc:
            return self._err(str(exc), 400)
        except Exception as exc:                            # noqa: BLE001
            if not distribution.ENABLED:
                traceback.print_exc()
            return self._err(f"{type(exc).__name__}: {exc}", 500)


def serve(host: str = "127.0.0.1", port: int = 8790) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), Handler, bind_and_activate=False)
    try:
        if os.name == "nt":
            # Windows 的 SO_REUSEADDR 允许两个进程同时绑定，浏览器会打开旧程序。
            httpd.allow_reuse_address = False
            httpd.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        httpd.server_bind()
        httpd.server_activate()
    except BaseException:
        httpd.server_close()
        raise
    httpd.daemon_threads = True
    return httpd
