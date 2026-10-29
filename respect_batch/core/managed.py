"""Online login and in-memory account configuration for the public batch client."""
import copy
import hashlib
import json
import secrets
import threading
import time
import uuid
from http.cookies import SimpleCookie
from pathlib import Path

import requests

from . import distribution, paths, managed_usage

AUTH_URL = 'https://login.respect.chat'
VERSION = '2026.10.29.2'
COOKIE = 'respect_batch_login'


def enabled():
    return distribution.ENABLED and getattr(distribution, 'MANAGED', False)


class LoginRequired(ValueError):
    def __init__(self, message='请先登录', code='login_required', status=401):
        super().__init__(message)
        self.code, self.status = code, status


def build_headers():
    """The release manifest is public registration data, never a secret or login bypass."""
    manifest = Path(paths.PROGRAM_DIR) / 'batch-build.json'
    try:
        data = json.loads(manifest.read_text(encoding='utf-8'))
        name = data['exe']
        if Path(name).name != name or '/' in name or '\\' in name or ':' in name:
            raise ValueError()
        with (manifest.parent / name).open('rb') as fp:
            digest = hashlib.file_digest(fp, 'sha256').hexdigest()
        if data['version'] != VERSION or data['sha256'] != digest:
            raise ValueError()
        return {'X-Studio-Flavor': 'batch', 'X-Studio-Version': VERSION, 'X-Studio-Build': digest,
                'X-Respect-Application': 'batch'}
    except (OSError, ValueError, KeyError, TypeError):
        raise LoginRequired('批量程序版本文件缺失或校验失败，请重新下载安装', 'client_unregistered', 426) from None


class Manager:
    def __init__(self):
        self.lock = threading.RLock()
        self.tokens = None
        self.user = None
        self.local_session = ''
        self.profile = None
        self.configs = None
        self.storage = None
        self.until = 0
        self._headers = None
        self._recovered = set()
        self._worker_started = False
        self._device = None

    def device_id(self):
        with self.lock:
            if self._device:
                return self._device
            file = Path(paths.data_dir()) / 'login-device.txt'
            file.parent.mkdir(parents=True, exist_ok=True)
            if file.is_file():
                self._device = str(uuid.UUID(file.read_text().strip()))
            else:
                self._device = str(uuid.uuid4())
                file.write_text(self._device, encoding='ascii')
            return self._device

    def post(self, action, body, token=''):
        if self._headers is None:
            self._headers = build_headers()
        headers = dict(self._headers)
        if token:
            headers['Authorization'] = 'Bearer ' + token
        try:
            with requests.Session() as session:
                session.trust_env = False
                response = session.post(AUTH_URL + '/api/v1/auth/' + action, json=body,
                    headers=headers, timeout=(8, 30), allow_redirects=False)
            payload = response.json()
            if response.status_code != 200:
                error = payload.get('error', {})
                raise LoginRequired(str(error.get('message') or '登录服务返回错误')[:300],
                    str(error.get('code') or 'auth_error'), response.status_code)
            if not isinstance(payload, dict):
                raise ValueError()
            return payload
        except LoginRequired:
            raise
        except (requests.RequestException, ValueError, AttributeError):
            raise LoginRequired('登录服务连接失败，请重试；已发任务不会重新提交', 'auth_unavailable', 503) from None

    def _tokens(self, data):
        if any(not isinstance(data.get(k), str) or not 40 <= len(data[k]) <= 128 for k in ('access_token', 'refresh_token')):
            raise LoginRequired('登录服务未返回有效凭证', 'auth_response_invalid', 503)
        self.tokens = {k: data[k] for k in ('access_token', 'refresh_token')}

    def clear(self):
        with self.lock:
            self.tokens = self.user = self.profile = self.configs = self.storage = None
            self.local_session = ''
            self.until = 0

    def login(self, body):
        username, password = body.get('username'), body.get('password')
        if not isinstance(username, str) or not isinstance(password, str) or not username.strip() or not password:
            raise LoginRequired('请填写账号和密码', status=400)
        with self.lock:
            self.clear()
            self._tokens(self.post('login', dict(username=username, password=password,
                device_id=self.device_id(), device_name='Respect 批量客户端')))
            self.local_session = secrets.token_urlsafe(32)
            try:
                self.verify(refresh_models=True)
            except Exception:
                self.clear()
                raise
            if self.user['id'] not in self._recovered:
                managed_usage.recover_interrupted(self.user['id'])
                self._recovered.add(self.user['id'])
            self.start_sender()
            return self.local_session

    def verify(self, refresh_models=False):
        from . import managed_models
        with self.lock:
            if not self.tokens:
                raise LoginRequired()
            self.until = 0
            for attempt in range(2):
                try:
                    result = self.post('verify', {'device_id': self.device_id()}, self.tokens['access_token'])
                    break
                except LoginRequired as exc:
                    if exc.code == 'access_expired' and attempt == 0:
                        try:
                            self._tokens(self.post('refresh', dict(device_id=self.device_id(), refresh_token=self.tokens['refresh_token'])))
                        except Exception:
                            self.clear()  # Refresh may have rotated remotely; never reuse old tokens.
                            raise
                        continue
                    if exc.status in (401, 403):
                        self.clear()
                    raise
            if result.get('valid') is not True or not isinstance(result.get('user'), dict) or not result['user'].get('id'):
                raise LoginRequired('登录服务未确认授权', 'auth_response_invalid', 503)
            user = {k: result['user'].get(k) for k in ('id', 'username', 'expires_at')}
            configs, storage = result.get('provider_config', {}), result.get('storage_config', {})
            if refresh_models or self.profile is None or configs != self.configs or storage != self.storage or user['id'] != (self.user or {}).get('id'):
                try:
                    self.profile = managed_models.build(user['id'], configs, storage)
                except (ValueError, TypeError, KeyError):
                    self.profile = None
                    raise LoginRequired('后台模型配置无法加载，请联系管理员检查授权或重新刷新', 'configuration_invalid', 503) from None
                self.configs, self.storage = copy.deepcopy(configs), copy.deepcopy(storage)
            self.user = user
            self.until = time.monotonic() + 60

    def matches(self, cookie):
        try:
            values = SimpleCookie(cookie or '')
            return bool(self.local_session) and COOKIE in values and secrets.compare_digest(values[COOKIE].value, self.local_session)
        except Exception:
            return False

    def require(self, cookie=None, force=False):
        with self.lock:
            if (cookie is not None and not self.matches(cookie)) or not self.tokens:
                raise LoginRequired()
            if force or time.monotonic() >= self.until:
                self.verify()
            if not self.user or (self.user.get('expires_at') is not None and time.time() >= self.user['expires_at']):
                raise LoginRequired('账号已到期，请联系管理员', 'account_expired', 403)

    def authorize_task(self, assignment):
        with self.lock:
            self.require()
            if self.user['id'] != assignment['owner'] or not any(
                    m['route']['_usage'] == assignment for m in self.profile['models']):
                raise LoginRequired('账号或 Key 授权已变化，尚未提交的任务已停止', 'assignment_changed', 403)

    def snapshot(self):
        from . import config
        with self.lock:
            return copy.deepcopy(self.profile) if self.profile else dict(preview=False, managed=True,
                models=[], config=copy.deepcopy(config.DEFAULTS), issues=[])

    def status(self, cookie):
        try:
            self.require(cookie)
            with self.lock:
                return dict(ok=True, authenticated=True, user=dict(self.user), issues=self.profile['issues'],
                            usage=managed_usage.status(self.user['id']))
        except LoginRequired as exc:
            return dict(ok=True, authenticated=False, msg=str(exc), code=exc.code)

    def logout(self, cookie):
        with self.lock:
            if not self.matches(cookie):
                raise LoginRequired()
            tokens = self.tokens
            self.clear()
            if tokens:
                self.post('logout', dict(device_id=self.device_id(), refresh_token=tokens['refresh_token']))

    def send_usage(self):
        with self.lock:
            if not self.user or not self.tokens:
                return
            owner, token = self.user['id'], self.tokens['access_token']
            events = managed_usage.pending(owner)
            if not events:
                return
            body = dict(device_id=self.device_id(), events=events)
            while len(json.dumps(body).encode()) > 14000 and events:
                events.pop()
            if not events:
                return
            result = self.post('usage', body, token)
            if result.get('accepted') == [e['event_id'] for e in events]:
                managed_usage.acknowledge(owner, events)

    def storage_ticket(self, cfg, data, mime):
        with self.lock:
            self.require()
            if self.user['id'] != cfg.get('owner'):
                raise LoginRequired('参考图属于另一个登录账号，请重新创建任务')
            return self.post('storage/sign', dict(device_id=self.device_id(), revision=cfg.get('revision', ''),
                sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), content_type=mime), self.tokens['access_token'])

    def start_sender(self):
        if self._worker_started:
            return
        self._worker_started = True
        def worker():
            while True:
                time.sleep(5)
                try:
                    self.send_usage()
                except Exception:
                    pass  # Durable records remain pending; never restart generation.
        threading.Thread(target=worker, daemon=True, name='batch-usage-upload').start()


manager = Manager()
