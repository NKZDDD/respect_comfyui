"""Exercise Requests proxy resolution without contacting an upstream or a proxy."""
import io
import json
import http.client
import threading
from pathlib import Path
from urllib.request import getproxies_environment, proxy_bypass_environment

import pytest
import requests

from core import distribution, managed, managed_models, network, paths, providers, updates, uploader
from core.providers.base import Provider
from tests.test_batch import sandbox
from tests.test_updates import release
from tests.test_managed import online, spec


@pytest.fixture
def policy(sandbox, monkeypatch):
    monkeypatch.setattr(distribution, 'ENABLED', True)
    monkeypatch.setattr(distribution, 'MANAGED', True)
    monkeypatch.setattr(distribution, 'profile', managed.Manager().snapshot)
    # Restore the Requests methods when the test finishes.
    for name in ('merge_environment_settings', 'rebuild_proxies'):
        monkeypatch.setattr(requests.Session, name, getattr(requests.Session, name))
    network.install()
    return network


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


@pytest.mark.parametrize('mode', ['proxy', 'no_proxy', 'bypass', 'direct', 'custom'])
@pytest.mark.parametrize('operation', ['login', 'check_update', 'download_update', 'r2_upload'])
def test_account_update_and_r2_follow_network_policy(policy, monkeypatch, tmp_path, transport, mode, operation):
    proxy = 'http://127.0.0.1:19090'
    if mode != 'no_proxy':
        monkeypatch.setenv('https_proxy', proxy)
    if mode == 'bypass':
        monkeypatch.setenv('no_proxy', '*')
    if mode in ('direct', 'custom'):
        network.save(dict(mode=mode, proxy_url='http://127.0.0.1:19092'))
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
    selected = requests.utils.select_proxy(request.url, settings['proxies']) or None
    assert selected == ('http://127.0.0.1:19092' if mode == 'custom' else proxy if mode == 'proxy' else None)
    assert settings['verify'] is True
    assert request.url.startswith('https://')
    assert 'Authorization' not in request.headers


@pytest.mark.parametrize('mode', ['system', 'direct', 'custom'])
def test_managed_catalog_and_generation_use_selected_route(policy, monkeypatch, transport, mode):
    class ImageProvider(Provider):
        id, name, supports = 'network_test', 'Test', ('image',)

        def capabilities(self):
            return dict(supports=['image'], image={'models': ['gpt-image-test']})

    monkeypatch.setattr(distribution, 'ENABLED', True)
    monkeypatch.setattr(distribution, 'MANAGED', True)
    monkeypatch.setitem(providers.REGISTRY, ImageProvider.id, ImageProvider)
    monkeypatch.setenv('https_proxy', 'http://127.0.0.1:19090')
    monkeypatch.setenv('all_proxy', 'http://127.0.0.1:19091')
    network.save(dict(mode=mode, proxy_url='http://127.0.0.1:19092'))
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
        expected = {'system': 'http://127.0.0.1:19090', 'direct': None, 'custom': 'http://127.0.0.1:19092'}[mode]
        assert (requests.utils.select_proxy(request.url, settings['proxies']) or None) == expected
        assert settings['verify'] is True
        assert request.headers['Authorization'] == 'Bearer FAKE-UPSTREAM-KEY'


def test_downloaded_adapter_sessions_and_redirects_obey_latest_mode(policy, monkeypatch, transport):
    monkeypatch.setenv('https_proxy', 'http://127.0.0.1:19090')
    session = requests.Session()
    session.trust_env = False
    session.proxies = {'https://upstream.invalid': 'http://stale.invalid:80'}
    target = 'https://upstream.invalid/result/task-123'
    for mode, expected in [('system', 'http://127.0.0.1:19090'), ('direct', None), ('custom', 'http://127.0.0.1:19092')]:
        network.save(dict(mode=mode, proxy_url='http://127.0.0.1:19092'))
        session.get(target, proxies={'http': '', 'https': ''}, headers={'Authorization': 'Bearer FAKE'}, timeout=2)
        request, settings = transport['calls'][-1]
        assert (requests.utils.select_proxy(target, settings['proxies']) or None) == expected
        assert settings['verify'] is True and request.headers['Authorization'] == 'Bearer FAKE'
        redirected = requests.Request('GET', 'https://cdn.invalid/result.png').prepare()
        rebuilt = session.rebuild_proxies(redirected, session.proxies)
        assert (requests.utils.select_proxy(redirected.url, rebuilt) or None) == expected
    assert len(transport['calls']) == 3  # changing the route never sends a POST


def test_windows_system_proxy_and_bypass(policy, monkeypatch, transport):
    monkeypatch.setattr(requests.utils, 'getproxies', lambda: {'https': 'http://windows-proxy.invalid:8080'})
    monkeypatch.setattr(requests.utils, 'proxy_bypass', lambda host: host == 'local.invalid')
    for host, expected in [('upstream.invalid', 'http://windows-proxy.invalid:8080'), ('local.invalid', None)]:
        requests.get('https://' + host)
        request, settings = transport['calls'][-1]
        assert (requests.utils.select_proxy(request.url, settings['proxies']) or None) == expected


@pytest.mark.parametrize('error,expected_attempts', [(requests.exceptions.SSLError, 3), (requests.ReadTimeout, 1)])
def test_custom_proxy_does_not_silently_fallback_or_repost(policy, monkeypatch, transport, error, expected_attempts):
    from core.apiutil import HttpSession, ApiError
    monkeypatch.setattr('core.apiutil.time.sleep', lambda seconds: None)
    network.save(dict(mode='custom', proxy_url='http://127.0.0.1:19092'))
    monkeypatch.setenv('no_proxy', '*')
    attempts = []
    def fail(adapter, request, **settings):
        attempts.append(settings)
        raise error('connection interrupted')
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', fail)
    # A submit whose acceptance is unknown must not be sent again on another route.
    with pytest.raises(ApiError):
        HttpSession('FAKE', 'https://upstream.invalid').request('POST', '/v1/images/generations',
                                                            submit=True, retries=3)
    assert len(attempts) == expected_attempts
    for settings in attempts:
        assert requests.utils.select_proxy('https://upstream.invalid', settings['proxies']) == 'http://127.0.0.1:19092'
        assert settings['verify'] is True


@pytest.mark.parametrize('value', [dict(mode='bad'), dict(mode=[]), dict(mode='custom'),
    dict(mode='custom', proxy_url='socks5://localhost:1080'),
    dict(mode='custom', proxy_url='http://user:pass@localhost:8080'),
    dict(mode='custom', proxy_url='http://localhost:8080/path'),
    dict(mode='custom', proxy_url='http://localhost:8080?key=SECRET'),
    dict(mode='custom', proxy_url='http://localhost:99999'),
    dict(mode='system', api_key='SECRET')])
def test_invalid_preferences_do_not_replace_last_good_route(policy, value):
    good = network.save(dict(mode='custom', proxy_url='http://127.0.0.1:19092'))
    with pytest.raises(ValueError): network.save(value)
    assert network.load() == good


def test_local_setting_persistence_is_not_upstream_redacted(policy):
    good = dict(mode='custom', proxy_url='https://proxy.example:8443')
    assert network.save(good) == good == network.load()
    assert json.loads((Path(paths.data_dir()) / 'network.json').read_text()) == good


def test_network_api_available_before_login_but_requires_local_page_token(policy, monkeypatch):
    from core import server
    monkeypatch.setattr(managed, 'manager', managed.Manager())
    httpd = server.serve(port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
    def request(body=None, token=server._SESSION, origin=None, route='/api/network'):
        conn = http.client.HTTPConnection('127.0.0.1', httpd.server_port, timeout=3)
        headers = {'X-Respect-Session': token, 'Content-Type': 'application/json'}
        if origin: headers['Origin'] = origin
        conn.request('POST' if body is not None else 'GET', route, json.dumps(body) if body is not None else None, headers)
        response = conn.getresponse(); result = response.status, json.loads(response.read()); conn.close()
        return result
    try:
        assert request()[1]['network'] == network.DEFAULTS
        value = dict(mode='custom', proxy_url='http://127.0.0.1:7890')
        assert request(value)[1]['network'] == value
        assert request()[1]['network'] == value
        assert request(token='')[0] == 403
        assert request(value, token='wrong')[0] == 403
        assert request(value, origin='https://evil.invalid')[0] == 403
        assert request(dict(mode='custom', proxy_url='http://user:password@localhost:7890'))[0] == 400
        assert request(route='/api/boot')[0] == 401
        assert request({}, route='/api/config')[0] == 403
    finally:
        httpd.shutdown(); httpd.server_close(); thread.join()


def test_non_managed_sessions_remain_unchanged(policy, monkeypatch, transport):
    network.save(dict(mode='custom', proxy_url='http://127.0.0.1:19092'))
    monkeypatch.setattr(distribution, 'MANAGED', False)
    session = requests.Session(); session.trust_env = False
    session.get('https://upstream.invalid', proxies={'https': 'http://personal.invalid:8080'})
    assert transport['calls'][-1][1]['proxies']['https'] == 'http://personal.invalid:8080'


def test_change_route_after_submission_keeps_task_id_and_one_usage_attempt(policy, online, transport):
    from core import release as public, batch, managed_usage as usage
    from core.apiutil import HttpSession
    assignment = public.prepare(spec())[1]['_usage']
    task = batch.build_tasks(dict(provider='faker', model='fast', tasks=[dict(prompt='test')]))[0]
    session = HttpSession('FAKE', 'https://upstream.invalid', proxy='direct')
    with usage.tracking(assignment, task):
        network.save(dict(mode='direct'))
        transport['body'] = b'{"id":"remote-123","status":"queued"}'
        session.request('POST', '/v1/images/generations', submit=True)
        network.save(dict(mode='custom', proxy_url='http://127.0.0.1:7890'))
        transport['body'] = b'{"id":"remote-123","status":"completed"}'
        session.request('GET', '/v1/tasks/remote-123')
    assert [r.method for r, _ in transport['calls']] == ['POST', 'GET']
    assert not transport['calls'][0][1]['proxies']['https']
    assert transport['calls'][1][1]['proxies']['https'] == 'http://127.0.0.1:7890'
    events = usage.pending('account-a')
    assert len(events) == 1 and events[0]['task_id'] == 'remote-123'


def test_public_statistics_use_proxy_without_credentials_dns_or_redirects(policy, monkeypatch, transport):
    from core import statistics_transport as stats, supplier_statistics as supplier
    monkeypatch.setattr(stats.socket, 'getaddrinfo', lambda *a, **k: pytest.fail('Proxy must resolve the target'))
    network.save(dict(mode='custom', proxy_url='http://127.0.0.1:19092'))
    class Raw(io.BytesIO):
        def read1(self, size, decode_content=False): return super().read1(size)
    calls = []
    def send(adapter, request, **settings):
        calls.append((request, settings))
        response = requests.Response(); response.status_code = 200
        response.request = request; response.url = request.url
        response.raw = Raw(b'{"data": []}')
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    target = supplier.SOURCES['cangyuan'][0] + supplier.SOURCES['cangyuan'][1]
    assert stats.get_json(target) == {'data': []}
    request, settings = calls[0]
    assert settings['verify'] is True and settings['timeout'] == (8, 2)
    assert settings['proxies']['https'] == 'http://127.0.0.1:19092'
    assert not {'Authorization', 'Cookie'} & set(request.headers)
    with pytest.raises(ValueError): stats.get_json('https://localhost/admin')
    with pytest.raises(ValueError): stats.get_json(target + '&extra=1')
    assert len(calls) == 1


@pytest.mark.parametrize('scenario', ['redirect', 'oversized', 'deadline', 'tls'])
def test_statistics_proxy_keeps_safety_limits(policy, monkeypatch, transport, scenario):
    from core import statistics_transport as stats, supplier_statistics as supplier
    network.save(dict(mode='custom', proxy_url='http://127.0.0.1:19092'))
    monkeypatch.setattr(supplier, 'MAX_BYTES', 32)
    calls = []
    class Raw(io.BytesIO):
        def read1(self, size, decode_content=False): return super().read1(size)
    def send(adapter, request, **settings):
        calls.append(request)
        if scenario == 'tls': raise requests.exceptions.SSLError('invalid cert')
        response = requests.Response(); response.status_code = 302 if scenario == 'redirect' else 200
        response.headers['Location'] = 'https://localhost/private'
        response.request = request; response.url = request.url
        response.raw = Raw(b'x' * 100 if scenario == 'oversized' else b'{}')
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    if scenario == 'deadline':
        times = iter([0, 13]); monkeypatch.setattr(stats.time, 'monotonic', lambda: next(times))
    target = supplier.SOURCES['cangyuan'][0] + supplier.SOURCES['cangyuan'][1]
    with pytest.raises((ValueError, TimeoutError, requests.exceptions.SSLError)): stats.get_json(target)
    assert len(calls) == 1
