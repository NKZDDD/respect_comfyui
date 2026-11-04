"""Exercise Requests proxy resolution without contacting an upstream or a proxy."""
import io
import json
from urllib.request import getproxies_environment, proxy_bypass_environment

import pytest
import requests

from core import distribution, managed, managed_models, providers, updates, uploader
from core.providers.base import Provider
from tests.test_batch import sandbox
from tests.test_updates import release


@pytest.fixture
def transport(monkeypatch):
    # Isolate the test from the developer's Windows proxy, CA and netrc settings.
    import os
    for name in list(os.environ):
        if name.lower().endswith('_proxy') or name in ('REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE'):
            monkeypatch.delenv(name)
    monkeypatch.setattr(requests.utils, 'getproxies', getproxies_environment)
    monkeypatch.setattr(requests.utils, 'proxy_bypass', proxy_bypass_environment)
    monkeypatch.setattr(requests.sessions, 'get_netrc_auth', lambda url: None)
    state = {'body': b'{}', 'calls': []}

    def send(adapter, request, **kwargs):
        state['calls'].append((request, kwargs))
        response = requests.Response()
        response.status_code = 200
        response.url, response.request = request.url, request
        response._content = state['body']
        response._content_consumed = True
        response.raw = io.BytesIO(state['body'])
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    return state


@pytest.mark.parametrize('mode', ['proxy', 'no_proxy', 'bypass'])
@pytest.mark.parametrize('operation', ['login', 'check_update', 'download_update', 'r2_upload'])
def test_account_update_and_r2_follow_system_network(sandbox, monkeypatch, tmp_path, transport, mode, operation):
    proxy = 'http://127.0.0.1:19090'
    if mode != 'no_proxy':
        monkeypatch.setenv('https_proxy', proxy)
    if mode == 'bypass':
        monkeypatch.setenv('no_proxy', '*')
    if operation == 'login':
        manager = managed.Manager()
        manager._headers = {'X-Respect-Application': 'batch'}
        transport['body'] = b'{"ok": true}'
        assert manager.post('login', {'username': 'test', 'password': 'fake'}) == {'ok': True}
    elif operation == 'check_update':
        monkeypatch.setattr(managed, 'build_headers', lambda: {'X-Respect-Application': 'batch'})
        transport['body'] = json.dumps(dict(application='batch', policy_protocol=1,
                                           client={'allowed': True}, release=None)).encode()
        manager = updates.UpdateManager()
        manager._check()
        assert manager.phase == 'current'
    elif operation == 'download_update':
        transport['body'] = b'MZ-install-test'
        manager = updates.UpdateManager()
        manager._download(release())
        assert manager.phase == 'ready'
        assert manager.installer.read_bytes() == transport['body']
    else:
        ref = tmp_path / 'ref.png'
        ref.write_bytes(b'pngbytes')
        monkeypatch.setattr(uploader, 'encode_ref', lambda *a, **k: (b'pngbytes', 'image/png', '.png', ''))
        monkeypatch.setattr(managed.manager, 'storage_ticket', lambda *a: dict(
            upload_url='https://storage.invalid/signed', public_url='https://cdn.invalid/ref.png'))
        cfg = dict(backend='managed', enabled=True, revision='test', owner='test')
        assert uploader.to_url(str(ref), cfg) == 'https://cdn.invalid/ref.png'
    assert len(transport['calls']) == 1
    request, settings = transport['calls'][0]
    assert requests.utils.select_proxy(request.url, settings['proxies']) == (proxy if mode == 'proxy' else None)
    assert settings['verify'] is True
    assert request.url.startswith('https://')
    assert 'Authorization' not in request.headers


def test_managed_catalog_and_generation_stay_direct(sandbox, monkeypatch, transport):
    class ImageProvider(Provider):
        id, name, supports = 'network_test', 'Test', ('image',)

        def capabilities(self):
            return dict(supports=['image'], image={'models': ['gpt-image-test']})

    monkeypatch.setattr(distribution, 'ENABLED', True)
    monkeypatch.setattr(distribution, 'MANAGED', True)
    monkeypatch.setitem(providers.REGISTRY, ImageProvider.id, ImageProvider)
    monkeypatch.setenv('https_proxy', 'http://127.0.0.1:19090')
    monkeypatch.setenv('all_proxy', 'http://127.0.0.1:19091')
    transport['body'] = b'{"data": [{"id": "gpt-image-test", "type": "image"}]}'
    profile = managed_models.build('test', {ImageProvider.id: dict(
        api_key='FAKE-UPSTREAM-KEY', base_url='https://upstream.invalid', models=[])}, {})
    assert not profile['issues'] and len(profile['models']) == 1
    route = profile['models'][0]['route']
    transport['body'] = b'{"id": "fake-task-id"}'
    provider = ImageProvider(api_key=route['api_key'], base_url=route['base_url'], proxy=route['proxy'])
    assert provider.session.request('POST', '/v1/images/generations', retries=1)['id'] == 'fake-task-id'
    assert [request.method for request, _ in transport['calls']] == ['GET', 'POST']
    for request, settings in transport['calls']:
        assert not requests.utils.select_proxy(request.url, settings['proxies'])
        assert settings['verify'] is True
        assert request.headers['Authorization'] == 'Bearer FAKE-UPSTREAM-KEY'
