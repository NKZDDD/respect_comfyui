import http.client
import json
import threading
from types import SimpleNamespace

from core import distribution, model_statistics as M, release, server
from tests.test_batch import sandbox
from tests.test_managed import online


def test_exact_routes_filter_public_catalog_and_keep_key_addresses(online, monkeypatch):
    manager, state = online
    rows = manager.profile['models']
    # Two authorized Keys for distinct models; third address isn't this supplier.
    rows[0]['route']['base_url'] = 'https://good.invalid'
    rows[1]['route']['base_url'] = 'https://custom.invalid'
    calls = []
    def snapshot(pid, base):
        calls.append((pid, base))
        return dict(state='ready', models=[dict(model='fast', rate=95.16),
                    dict(model='fast-suffix', rate=10), dict(model='forbidden', rate=100)]
                    if base == 'https://good.invalid' else [])
    monkeypatch.setattr(M, 'CACHE', SimpleNamespace(snapshot=snapshot))
    data = M.snapshot()
    assert len(calls) == len(set(calls))
    assert data['models'][0]['stats'][0]['rate'] == 95.16
    assert not data['models'][1]['stats']
    assert {r['id'] for r in data['models']} == {r['id'] for r in rows}
    text = json.dumps(release.redact(data))
    assert all(s not in text for s in ('FAKE-KEY', 'good.invalid', 'custom.invalid', 'forbidden', 'fast-suffix', 'assignment_id', 'key-1'))
    state['grants']['faker']['keys'].pop(0)
    manager.verify(refresh_models=True)
    assert {r['model_id'] for r in M.snapshot()['models']} == {'slow'}
    manager.clear()
    assert M.snapshot()['models'] == []


def test_statistics_endpoint_requires_cookie_page_token_and_same_origin(online, monkeypatch):
    manager, state = online
    monkeypatch.setattr(M, 'CACHE', SimpleNamespace(snapshot=lambda *a: dict(state='ready', models=[])))
    httpd = server.serve(port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    def get(cookie=state['cookie'], token=server._SESSION, origin=None):
        headers = {'Cookie': cookie, 'X-Respect-Session': token}
        if origin: headers['Origin'] = origin
        conn = http.client.HTTPConnection('127.0.0.1', httpd.server_port, timeout=3)
        conn.request('GET', '/api/model-statistics', headers=headers)
        response = conn.getresponse()
        status, body = response.status, response.read()
        conn.close()
        return status, body
    try:
        assert get(cookie='')[0] == 401
        assert get(token='')[0] == 403
        assert get(origin='https://evil.invalid')[0] == 403
        assert get()[0] == 200
        before = len(state['calls'])
        for _ in range(3): assert get()[0] == 200
        assert len(state['calls']) == before
        state['uid'] = 'new-account'
        manager.login(dict(username='new', password='test'))
        assert get()[0] == 401
    finally:
        httpd.shutdown(); httpd.server_close(); thread.join()


def test_vendored_statistics_normalizers_match_studio():
    # Build remains standalone; this check guards accidental divergence in this workspace.
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    studio = root.parent / 'script-to-video-studio/auth_service/studio_auth/model_statistics.py'
    if studio.exists():
        assert (root/'core/supplier_statistics.py').read_text(encoding='utf-8') == studio.read_text(encoding='utf-8').replace(
            'from .provider_probe import', 'from .statistics_transport import')
