import copy
import json
import time

import pytest
import requests

from core import batch, managed, managed_usage, production_diagnostics as D
from core.apiutil import ApiError, HttpSession, TASK_FATAL
from tests.test_batch import sandbox
from tests.test_managed import online, spec, wait


def pending(owner='account-a'):
    with D.connection() as db:
        return [json.loads(row[0]) for row in db.execute('SELECT payload FROM events WHERE owner=? ORDER BY id', (owner,))]


@pytest.mark.parametrize('failure,code,hint,category,result', [
    ('missing', 400, 'model_missing', 'http', 'failed'),
    ('blend', 400, 'single_reference_only', 'http', 'failed'),
    ('gateway', 502, 'bad_gateway', 'http', 'unknown'),
    ('proxy', 0, 'proxy_connection', 'connection', 'unknown'),
    ('ok', 200, '', 'none', 'completed'),
])
def test_real_worker_and_http_report_correlation_without_resubmit(online, monkeypatch, failure, code, hint, category, result):
    manager, state = online
    # Use a downloaded provider, including the same HTTP/usage boundary as NY.
    src = state['bundle']['modules']['faker']
    src = src.replace('        return self._fake(task.model, dest, log)', '''        from core.apiutil import HttpSession
        session = HttpSession('sk-DO-NOT-REPORT', 'https://private-upstream.invalid')
        session.request('POST', '/v1/images/edits', files=[('model', task.model), ('prompt', task.prompt)], submit=True)
        return self._fake(task.model, dest, log)''', 1)
    state['bundle']['modules']['faker'] = src
    manager.verify()
    calls = []
    def send(adapter, request, **kw):
        calls.append(request)
        if failure == 'proxy':
            raise requests.exceptions.ProxyError('Unable to connect to proxy; sk-DO-NOT-REPORT prompt-DO-NOT-REPORT')
        messages = dict(missing='Model name not specified, model name cannot be empty',
                        blend='Midjourney V8.2 image-to-image accepts one reference; Blend is not enabled',
                        gateway='502 Bad Gateway', ok='')
        response = requests.Response(); response.status_code = code
        response.headers['x-request-id'] = '202611070921550092353688268d9d6VZd1Vf4G'
        response._content = json.dumps({'error': {'message': messages[failure]+' sk-DO-NOT-REPORT prompt-DO-NOT-REPORT'}} if failure != 'ok' else {}).encode()
        response.request = request; response.url = request.url
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    raw = spec(); raw['max_retry'] = 8; raw['tasks'][0]['prompt'] = 'prompt-DO-NOT-REPORT'
    run = batch.start(raw, {}); wait(run)
    assert len(calls) == 1
    events = pending(); assert len(events) == 1
    e = events[0]; p = e['production']
    assert e['status'] == code and e['category'] == category
    assert p.get('error_hint', '') == hint and p['result_state'] == result
    assert p['model'] == p['wire_model'] == 'fast' and p['key_id'] == 'key-1'
    assert p['batch_id'] == run.id and p['task_index'] == 1 and p['attempt'] == 1
    assert p['usage_event_id'] == managed_usage.pending('account-a')[0]['event_id']
    assert p['stage'] == ('complete' if failure == 'ok' else 'submit')
    if code:
        assert p['upstream_request_id'] == '202611070921550092353688268d9d6VZd1Vf4G'
    dumped = json.dumps(e)
    for secret in ('sk-DO-NOT-REPORT', 'prompt-DO-NOT-REPORT', 'private-upstream.invalid', raw['out_dir']):
        assert secret not in dumped


def test_reference_and_download_failures_have_correct_stage(online, monkeypatch):
    manager, state = online
    raw, cfg = __import__('core.release', fromlist=['prepare']).prepare(spec())
    task = batch.build_tasks(raw)[0]; task.refs = ['LOCAL-MATERIAL-PATH']
    run = batch.Run([task], raw, cfg)
    def resolve(*args):
        raise ApiError('当前账号未获 R2 上传授权', kind=TASK_FATAL)
    batch._execute(run, task, None, resolve, 0)
    e = pending()[0]
    assert e['production']['stage'] == 'references'
    assert e['production']['error_hint'] == 'r2_unauthorized'
    assert e['production']['result_state'] == 'not_submitted'
    assert not managed_usage.pending('account-a')
    assert 'LOCAL-MATERIAL-PATH' not in json.dumps(e)
    task.refs = []
    def fail_download(*a, **kw):
        raise requests.exceptions.ConnectionError('network')
    session = HttpSession('FAKE', 'https://private.invalid')
    monkeypatch.setattr(session, '_save_once', fail_download)
    with pytest.raises(ApiError), D.attempt(run, task):
        session.save_item('https://private.invalid/image?signature=PRIVATE', 'LOCAL-OUTPUT-PATH', retries=1)
    assert pending()[-1]['production']['stage'] == 'download'
    assert 'PRIVATE' not in json.dumps(pending()[-1])


def test_outbox_retry_ack_account_isolation_and_independent_sender(online, monkeypatch):
    manager, state = online
    run = batch.start(spec(), {}); wait(run)
    original = pending()[0]
    def offline(*args): raise managed.LoginRequired(status=503)
    monkeypatch.setattr(manager, 'post', offline)
    D.send(manager)
    assert pending() == [original] and '暂未同步' in manager._diagnostics_error
    manager._diagnostics_retry_at = 0
    manager.user['id'] = 'other-account'
    received = []
    def ack(action, body, token=''):
        received.extend(copy.deepcopy(body['events']))
        return {'accepted':[e['event_id'] for e in body['events']]}
    monkeypatch.setattr(manager, 'post', ack)
    D.send(manager)
    assert received == [] and pending() == [original]
    manager.user['id'] = 'account-a'
    D.send(manager); D.send(manager)
    assert received == [original] and pending() == []


def test_old_server_rejection_keeps_detailed_evidence(online, monkeypatch):
    manager, state = online
    run = batch.start(spec(), {}); wait(run)
    def old(*args): raise managed.LoginRequired(status=422)
    monkeypatch.setattr(manager, 'post', old)
    D.send(manager)
    assert len(pending()) == 1 and '需升级' in manager._diagnostics_error


def test_ack_cannot_remove_new_event_reusing_pruned_row_id(online, monkeypatch):
    manager, state = online
    run = batch.start(spec(), {}); wait(run)
    replacement = dict(pending()[0], event_id='00000000-0000-0000-0000-000000000009')
    def ack_after_prune(action, body, token=''):
        with D.connection() as db:
            db.execute('DELETE FROM events')
        D.persist('account-a', replacement)
        return {'accepted':[e['event_id'] for e in body['events']]}
    monkeypatch.setattr(manager, 'post', ack_after_prune)
    D.send(manager)
    assert pending() == [replacement]


def test_diagnostic_disk_failure_never_changes_success(online, monkeypatch):
    def broken(*args): raise OSError('disk full')
    monkeypatch.setattr(D, 'connection', broken)
    run = batch.start(spec(), {}); wait(run)
    assert run.counts()['完成'] == 1
    assert managed_usage.pending('account-a')[0]['status'] == 'completed'
    assert D.status('account-a')['recording_error']


def test_unacknowledged_diagnostics_wait_even_after_long_offline_period(sandbox):
    for i in range(5): D.persist('a', {'at':int(time.time()),'event_id':str(i)})
    D.persist('a', {'at':int(time.time())-90*86400,'event_id':'old'})
    assert {e['event_id'] for e in pending('a')} == {'0','1','2','3','4','old'}


def test_network_mode_is_captured_when_request_starts(online, monkeypatch):
    from core import network, release
    raw, cfg = release.prepare(spec())
    task = batch.build_tasks(raw)[0]
    run = batch.Run([task], raw, cfg)
    network.save({'mode':'direct'})
    def reply(*args, **kwargs):
        # User changes the next-request policy while the current request is in flight.
        network.save({'mode':'system'})
        r=requests.Response();r.status_code=200;r._content=b'{}'
        return r
    monkeypatch.setattr(requests, 'request', reply)
    with D.attempt(run, task):
        HttpSession('FAKE','https://private.invalid').request('POST','/v1/images/generations',submit=False)
    assert pending()[0]['production']['network_mode']=='direct'
