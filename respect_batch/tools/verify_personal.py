"""验证真实自用 EXE：空目录启动、全部适配器、Key 保存及模型刷新重启；只调用本机模拟接口。"""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import urllib.error


def verify(exe, bundle=False):
    root = Path(__file__).resolve().parents[1]
    scratch = Path(tempfile.mkdtemp(prefix='personal-check-', dir=root / 'release-build'))
    if bundle:
        exe = exe.resolve()
        single = exe.parent
    else:
        single = scratch / 'single'; single.mkdir()
        exe = Path(shutil.copy2(exe, single / exe.name))
        assert len(list(single.iterdir())) == 1
    env = os.environ.copy()
    env['LOCALAPPDATA'] = str(scratch / 'appdata')
    env.pop('RESPECT_BATCH_DATA_DIR', None)
    temp = scratch / 'temp'; temp.mkdir()
    env['TEMP'] = env['TMP'] = str(temp)
    process = None
    count = 0
    url = token = ''
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    seen = []
    fake_key = 'LOCAL-VERIFICATION-KEY'
    class Mock(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            seen.append((self.path, self.headers.get('Authorization')))
            data = json.dumps({'data': [{'id': 'minimax_h3-768p'},
                {'id': 'sd-2.5'}, {'id': 'grok-imagine-image-quality-lite'}]}).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(data)))
            self.end_headers(); self.wfile.write(data)
    mock = ThreadingHTTPServer(('127.0.0.1', 0), Mock)
    threading.Thread(target=mock.serve_forever, daemon=True).start()
    def stop():
        if process is not None and process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, check=False)
            process.wait(timeout=10)
    def start():
        nonlocal process, count, url, token
        count += 1
        log = scratch / f'start-{count}.log'
        with log.open('wb') as stream:
            process = subprocess.Popen([str(exe), '--no-browser'], cwd=single,
                env=env, stdout=stream, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            match = re.search(r'http://127\.0\.0\.1:\d+/', log.read_bytes().decode('utf-8', 'replace'))
            if match:
                url = match.group(); break
            if process.poll() is not None:
                raise RuntimeError('启动失败：' + str(log))
            time.sleep(.15)
        else:
            raise RuntimeError('启动超时：' + str(log))
        status, home = request('')
        assert status == 200 and b'id="tab-set"' in home
        token = re.search(rb"const SESSION='([^']+)'", home).group(1).decode()
        assert not token.startswith('__')
        assert '自用版'.encode() in home
        assert b'CFG=fresh.config; CAPS=fresh.providers; CFG.__uploadReady=!!fresh.upload_ready;' in home
    def request(route, body=None, headers=None):
        if isinstance(body, dict): body = json.dumps(body).encode()
        req = urllib.request.Request(url + route, data=body,
            headers={'X-Respect-Session': token, **(headers or {})})
        try:
            with opener.open(req, timeout=30) as r: return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
    def api(route, body=None):
        status, raw = request(route, body)
        assert status == 200, (route, status)
        assert fake_key.encode() not in raw
        return json.loads(raw)
    checks = []
    try:
        start()
        boot = api('api/boot')
        if len(boot['providers']) != 17 or boot['status']['errors']:
            diagnostic = {'providers': [p['id'] for p in boot['providers']],
                'errors': boot['status']['errors'], 'data_dir': boot['data_dir']}
            (scratch / 'provider-diagnostic.json').write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding='utf-8')
            raise RuntimeError('Provider load failed; diagnostic: ' + str(scratch / 'provider-diagnostic.json'))
        assert Path(boot['data_dir']) == scratch / 'appdata' / 'Respect-Batch-Personal'
        assert not any(p.get('api_key') for p in boot['config']['providers'].values())
        assert len([p for p in boot['providers'] if p.get('model_catalog')]) == 7
        checks.append(('native_bundle' if bundle else 'single_exe_empty_directory') + '_17_providers_and_7_live_snapshots')
        checks.append('no_preinstalled_credentials')
        assert request('api/boot', headers={'Origin':'https://foreign.invalid'})[0] == 403
        assert request('api/config', {}, {'X-Respect-Session':''})[0] == 403
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        assert request('api/upload?name=local-test.png', png)[0] == 200
        checks.append('local_reference_import_and_cross_origin_protection')
        saved = api('api/config', {'config': {'providers': {'ake': {
            'api_key':fake_key, 'base_url':f'http://127.0.0.1:{mock.server_port}'}}}})
        assert saved['config']['providers']['ake']['api_key'] == '********'
        refreshed = api('api/models', {'provider':'ake'})
        assert refreshed['ok'] and len(refreshed['models']) == 3
        assert len(refreshed['capability']['image']['models']) == 1
        assert len(refreshed['capability']['video']['models']) == 2
        assert seen == [('/v1/models', 'Bearer ' + fake_key)]
        api('api/config', {'config': {'providers': {'ake': {'api_key':'********'}}}})
        stop(); start()
        warm = api('api/boot')
        ake = next(p for p in warm['providers'] if p['id']=='ake')
        assert ake['model_catalog']['source'] == '当前 Key 拉取'
        assert len(ake['video']['models']) == 2
        checks.append('editable_keys_masked_save_model_refresh_and_restart_persistence')
        api('api/config', {'config': {'providers': {'ake': {'api_key':'CHANGED-TEST-KEY'}}}})
        ake = next(p for p in api('api/boot')['providers'] if p['id']=='ake')
        assert ake['model_catalog']['total'] == 11
        checks.append('model_cache_isolated_after_key_change')
        assert api('api/run')['idle']
        return {'ok':True, 'checks':checks, 'paid_generation_requests':0, 'scratch':str(scratch)}
    finally:
        stop(); mock.shutdown(); mock.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('exe', type=Path)
    parser.add_argument('--bundle', action='store_true', help='先验证尚未封装的原生目录包')
    args = parser.parse_args()
    print(json.dumps(verify(args.exe, args.bundle), ensure_ascii=False, indent=2))
