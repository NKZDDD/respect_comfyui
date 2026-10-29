"""Batch-only update policy, verified downloads and installer handoff."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
from urllib.parse import urlsplit

import requests

from . import managed, paths


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,5}(?:\.\d{1,5}){3}', value):
        raise ValueError('更新版本号无效')
    return tuple(map(int, value.split('.')))


def validate_release(data):
    if not isinstance(data, dict) or data.get('flavor') != 'batch' or data.get('application') != 'batch':
        raise ValueError('更新包不属于对外批量版，已拒绝安装')
    version(data.get('version'))
    url = urlsplit(data.get('url', ''))
    name = f"Respect-Batch-Setup-{data['version']}.exe"
    if (url.scheme != 'https' or url.port not in (None, 443) or not url.hostname or
            not re.fullmatch(r'(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,63}', url.hostname) or
            url.hostname.endswith(('.local', '.internal', '.localhost', '.r2.cloudflarestorage.com')) or
            url.username or url.password or url.query or url.fragment or
            not re.fullmatch(r'/[A-Za-z0-9_./-]+', url.path) or '..' in url.path.split('/') or
            '//' in url.path or url.path.rsplit('/', 1)[-1] != name):
        raise ValueError('请配置批量版安装包的公网 HTTPS 直链')
    if type(data.get('bytes')) is not int or not 0 < data['bytes'] <= 2 * 1024**3:
        raise ValueError('更新包大小无效')
    for field in ('sha256', 'build_sha256'):
        if not re.fullmatch(r'[a-f0-9]{64}', str(data.get(field, ''))):
            raise ValueError('更新包校验信息无效')
    return {k: data.get(k, '') for k in ('application', 'flavor', 'version', 'url', 'sha256', 'build_sha256', 'bytes', 'notes')}


class UpdateManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.phase = 'idle'
        self.message = '检查更新'
        self.release = None
        self.received = 0
        self.installer = None
        self.required = False
        self.install_callback = None

    def status(self):
        with self.lock:
            return dict(current=managed.VERSION, phase=self.phase, message=self.message,
                        release=self.release, received=self.received, required=self.required)

    def check(self):
        with self.lock:
            if self.phase in ('checking', 'downloading', 'installing'):
                return self.status()
            self.phase, self.message = 'checking', '正在检查批量版更新'
        threading.Thread(target=self._check, daemon=True).start()
        return self.status()

    def _check(self):
        try:
            try:
                headers = managed.build_headers()
            except managed.LoginRequired:
                headers = {'X-Studio-Flavor': 'batch', 'X-Studio-Version': managed.VERSION,
                           'X-Studio-Build': 'damaged', 'X-Respect-Application': 'batch'}
            with requests.Session() as session:
                session.trust_env = False
                with session.get(managed.AUTH_URL + '/api/v1/updates/latest',
                        params={'application':'batch', 'flavor':'batch'}, headers=headers,
                        timeout=(10, 20), stream=True, allow_redirects=False) as response:
                    if response.status_code != 200:
                        raise ValueError('检查更新失败，请检查网络或升级登录服务')
                    response.raw.decode_content = True
                    raw = response.raw.read(65537)
            if len(raw) > 65536:
                raise ValueError('更新信息过大')
            data = json.loads(raw)
            if (data.get('application') != 'batch' or data.get('policy_protocol') != 1 or
                    type(data.get('client', {}).get('allowed')) is not bool):
                raise ValueError('服务端尚未支持按应用更新，请管理员升级服务端')
            release = validate_release(data['release']) if data.get('release') else None
            required = not data['client']['allowed']
            with self.lock:
                keep = self.installer and self.release == release and self.installer.is_file()
                self.release, self.required = release, required
                if not keep:
                    self.installer, self.received = None, 0
                available = release and (version(release['version']) > version(managed.VERSION) or
                                         required and version(release['version']) == version(managed.VERSION))
                self.phase = 'ready' if keep else 'available' if available else 'current'
                self.message = ('更新已就绪，重启完成安装' if keep else
                                '必须更新后才能继续使用' if available and required else
                                '有新版本可下载' if available else
                                str(data['client'].get('message', '当前版本未通过校验')) if required else
                                '当前已是最新发布版本')
        except Exception as exc:
            with self.lock:
                self.release = self.installer = None
                self.phase, self.message = 'error', str(exc) if isinstance(exc, ValueError) else '检查更新失败，请重试'

    def download(self):
        with self.lock:
            if self.phase in ('checking', 'downloading', 'installing'):
                return self.status()
            if not self.release or version(self.release['version']) < version(managed.VERSION):
                raise ValueError('请先检查更新')
            self.phase, self.message, self.received, self.installer = 'downloading', '正在下载更新', 0, None
            threading.Thread(target=self._download, args=(dict(self.release),), daemon=True).start()
            return self.status()

    def _download(self, release):
        partial = None
        try:
            release = validate_release(release)
            folder = Path(paths.data_dir()) / 'updates'
            folder.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(folder).free < release['bytes'] + 128 * 1024**2:
                raise ValueError('数据盘空间不足，请清理后重试')
            target = folder / f"Respect-Batch-Setup-{release['version']}.exe"
            partial = target.with_suffix('.part')
            digest, count = hashlib.sha256(), 0
            with requests.Session() as session:
                session.trust_env = False
                with session.get(release['url'], timeout=(15, 60), stream=True, allow_redirects=False,
                                 headers={'Accept-Encoding':'identity'}) as response:
                    if response.status_code != 200:
                        raise ValueError(f'下载失败（HTTP {response.status_code}），请检查发布地址')
                    with partial.open('wb') as fp:
                        for chunk in response.iter_content(1024 * 1024):
                            count += len(chunk)
                            if count > release['bytes']:
                                raise ValueError('下载大小与发布信息不匹配')
                            fp.write(chunk)
                            digest.update(chunk)
                            with self.lock:
                                self.received = count
            if count != release['bytes'] or digest.hexdigest() != release['sha256']:
                raise ValueError('更新包校验失败，请重新下载')
            partial.replace(target)
            with self.lock:
                self.phase, self.message, self.installer = 'ready', '更新已就绪，重启完成安装', target
        except Exception as exc:
            if partial:
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    pass
            with self.lock:
                self.phase, self.message = 'error', str(exc) if isinstance(exc, ValueError) else '下载中断，请重试'

    def install(self, run):
        # Caller holds the same lock as /api/start, so installation and new batches cannot race.
        with self.lock:
            if run and run.status in ('跑批中', '排队中'):
                raise ValueError('仍有任务运行，请等待批次收尾后重启更新')
            if self.phase != 'ready' or not self.installer or not self.install_callback:
                raise ValueError('请先下载更新，或从批量版程序中操作')
            if self.installer.stat().st_size != self.release['bytes']:
                raise ValueError('更新包已改变，请重新下载')
            with self.installer.open('rb') as fp:
                if hashlib.file_digest(fp, 'sha256').hexdigest() != self.release['sha256']:
                    raise ValueError('更新包已改变，请重新下载')
            self.install_callback(self.installer)
            self.phase, self.message = 'installing', '正在退出并安装更新，完成后自动重新打开'
            return self.status()


def launch_installer(installer):
    # NSIS /D is last and unquoted, per its argument protocol; Popen does not invoke a shell.
    folder = str(Path(paths.PROGRAM_DIR).resolve())
    if any(c in folder for c in ('"', '\r', '\n')):
        raise ValueError('安装目录包含不支持的字符')
    command = subprocess.list2cmdline([str(installer), '/S', f'/BATCHUPDATE={os.getpid()}']) + ' /D=' + folder
    subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)


manager = UpdateManager()
