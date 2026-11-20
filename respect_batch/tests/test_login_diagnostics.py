import json
import uuid

import requests

from core import login_diagnostics as login, managed, production_diagnostics as queue
from tests.test_batch import sandbox
from tests.test_managed import online


def events(owner='account-a'):
    with queue.connection() as db:
        return [json.loads(row[0]) for row in db.execute(
            'SELECT payload FROM events WHERE owner=? ORDER BY id', (owner,))]


def transport(monkeypatch, manager, reply):
    monkeypatch.setattr(manager, 'post', managed.Manager.post.__get__(manager))
    def send(adapter, req, **kwargs):
        status, payload = reply(req.url.rsplit('/', 1)[-1], req.headers, json.loads(req.body))
        response = requests.Response()
        response.status_code = status
        response._content = json.dumps(payload).encode()
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)


def test_expired_access_rotates_once_and_correlates_without_locking(online, monkeypatch):
    m, state = online
    original = m.post
    calls = []
    def reply(action, headers, body):
        calls.append((action, headers['X-Studio-Request-ID']))
        if len(calls) == 1:
            return 401, {'error': {'code':'access_expired'}}
        return 200, original(action, body)
    transport(monkeypatch, m, reply)
    m.until = 0
    assert m.status(state['cookie'])['authenticated']
    assert m.status(state['cookie'])['authenticated']
    rows = events()
    assert [e['operation'] for e in rows] == ['verify.access_expired', 'refresh', 'verify']
    assert [e['request_id'] for e in rows] == [r for _, r in calls]
    assert len({uuid.UUID(r) for _, r in calls}) == 3
    assert [e['status'] for e in rows] == [401,200,200]


def test_refresh_lost_clears_once_and_replays_only_to_original_account(online, monkeypatch):
    m, state = online
    refresh_ids = []
    def reply(action, headers, body):
        if action == 'verify':
            return 401, {'error':{'code':'access_expired'}}
        assert action == 'refresh'
        refresh_ids.append(headers['X-Studio-Request-ID'])
        raise requests.exceptions.SSLError('private.example password Bearer abc')
    transport(monkeypatch, m, reply)
    m.until = 0
    for _ in range(3):
        assert not m.status(state['cookie'])['authenticated']
    rows = events()
    assert [e['operation'] for e in rows] == ['verify.access_expired','refresh.auth_unavailable',
        'session_cleared.refresh_failed.auth_unavailable','login_page.refresh_failed.auth_unavailable']
    assert len(refresh_ids) == 1 and {e['request_id'] for e in rows[1:]} == set(refresh_ids)
    assert rows[1]['category'] == 'tls' and rows[1]['status'] == 0
    dumped = json.dumps(rows)
    for private in ('Bearer', 'private.example', 'password', state['cookie'], 'r'*50):
        assert private not in dumped
    new = managed.Manager()
    new._headers = {}
    sent = []
    def receive(action, headers, body):
        assert action == 'diagnostics' and 'X-Studio-Request-ID' not in headers
        sent.extend(body['events'])
        return 200, {'accepted':[e['event_id'] for e in body['events']]}
    transport(monkeypatch, new, receive)
    new.user, new.tokens = {'id':'account-b'}, {'access_token':'b'*50}
    queue.send(new)
    assert not sent and events() == rows
    new.user, new.tokens = {'id':'account-a'}, {'access_token':'a'*50}
    queue.send(new)
    assert sent == rows and not events()


def test_transient_verify_timeout_restores_same_session_and_page_error_is_scoped(online, monkeypatch):
    m, state = online
    cookie = state['cookie']
    marker = m.status(cookie)['diagnostic_session']
    original = m.post
    def timeout(*args):
        raise requests.exceptions.Timeout('local secret')
    transport(monkeypatch, m, timeout)
    m.until = 0
    assert not m.status(cookie)['authenticated'] and m.matches(cookie)
    monkeypatch.setattr(m, 'post', original)
    assert m.status(cookie)['authenticated']
    body = dict(session=marker, state='ready', at=1234)
    m.report_page(cookie, body)
    assert [e['operation'] for e in events()] == [
        'verify.auth_unavailable','login_page.auth_unavailable','page_restored']
    body['state'] = 'workspace_load_failed'
    m.report_page(cookie, body)
    m.report_page(cookie, body)
    state['uid'] = 'account-b'
    new_cookie = managed.COOKIE+'='+m.login({'username':'b','password':'secret'})
    m.report_page(new_cookie, body)
    assert sum(e['operation']=='login_page.workspace_load_failed' for e in events()) == 1
    assert not events('account-b')
    assert not m.status(None)['authenticated']


def test_restart_attribution_without_persisting_login_credentials(online, monkeypatch):
    m, state = online
    monkeypatch.setattr(login, 'PROCESS', uuid.uuid4().hex)
    new = managed.Manager()
    for _ in range(2):
        assert not new.status(state['cookie'])['authenticated']
    assert [e['operation'] for e in events()] == ['login_page.client_restarted']
    with queue.connection() as db:
        assert m.local_session not in repr(db.execute('SELECT * FROM login_pages').fetchall())
