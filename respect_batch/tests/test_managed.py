import copy
import http.client
import json
from pathlib import Path
import threading
import time

import pytest
import requests

from tests.test_batch import sandbox
from core import batch, config, distribution, managed, managed_models, managed_usage as usage, paths, providers, release
from core.apiutil import ApiError, HttpSession


def grants():
    return {'faker': {'keys': [
        dict(api_key='FAKE-KEY-ONE', key_id='key-1', key_name='图片一号', assignment_id='rev-1',
             base_url='https://upstream.invalid', models=['fast']),
        dict(api_key='FAKE-KEY-TWO', key_id='key-2', key_name='图片二号', assignment_id='rev-2',
             base_url='https://upstream.invalid', models=['slow'])]}}


@pytest.fixture
def online(sandbox, monkeypatch):
    m = managed.Manager()
    m._headers = {'X-Studio-Flavor': 'batch'}
    m.start_sender = lambda: None
    monkeypatch.setattr(managed, 'manager', m)
    monkeypatch.setattr(distribution, 'ENABLED', True)
    monkeypatch.setattr(distribution, 'MANAGED', True)
    monkeypatch.setattr(distribution, 'profile', m.snapshot)
    state = {'grants': grants(), 'uid': 'account-a', 'calls': []}
    def post(action, body, token=''):
        state['calls'].append((action, copy.deepcopy(body), token))
        if action in ('login', 'refresh'):
            return dict(access_token='a'*50, refresh_token='r'*50)
        if action == 'verify':
            return dict(valid=True, user=dict(id=state['uid'], username=state['uid'], expires_at=None),
                        provider_config=state['grants'], storage_config={})
        if action == 'usage':
            return {'accepted': [e['event_id'] for e in body['events']]}
        return {'ok': True}
    monkeypatch.setattr(m, 'post', post)
    token = m.login(dict(username='tester', password='test-password'))
    state['cookie'] = managed.COOKIE + '=' + token
    return m, state


def spec(model='fast', kind='image'):
    row = next(r for r in release.catalog() if r['model'] == model and r['kind'] == kind)
    return dict(provider='preset', model=row['id'], kind=kind,
                tasks=[{'prompt': '测试', 'refs': []}], out_dir=str(Path(paths.data_dir())/'out'), max_retry=0)


def wait(run):
    end = time.monotonic()+8
    while run.status in ('跑批中','排队中') and time.monotonic()<end:
        time.sleep(.02)
    assert run.status not in ('跑批中','排队中')


def test_model_union_routes_to_key_and_ignores_local_config(online):
    m, state = online
    assert {r['model'] for r in release.catalog()} == {'fast','slow'}
    Path(paths.config_path()).write_text('{"providers":{"faker":{"api_key":"WRONG"}}}')
    for model, key in [('fast','FAKE-KEY-ONE'),('slow','FAKE-KEY-TWO')]:
        _, cfg = release.prepare(spec(model))
        assert cfg['providers']['faker']['api_key'] == key
        assert cfg['_usage']['owner'] == 'account-a'
    public = json.dumps(release.redact(release.public_boot()), ensure_ascii=False)
    assert '图片一号' in public and '图片二号' in public
    assert all(s not in public for s in ['FAKE-KEY', 'upstream.invalid', 'base_url', 'assignment_id'])


def test_refresh_revocation_overlap_and_account_switch(online):
    m, state = online
    old = spec('fast')
    state['grants']['faker']['keys'][1]['models'] = ['fast','slow']
    m.verify(refresh_models=True)
    assert release.prepare(old)[1]['_usage']['key_id']=='key-1'
    assignment=release.prepare(old)[1]['_usage']
    state['grants']['faker']['keys'].pop(0)
    m.verify(refresh_models=True)
    assert release.prepare(old)[1]['_usage']['key_id']=='key-2'
    with pytest.raises(managed.LoginRequired):
        m.authorize_task(assignment)
    state['uid']='account-b'
    m.login(dict(username='other',password='p'))
    with pytest.raises(managed.LoginRequired):
        m.require(state['cookie'])
    state['grants']={}
    m.verify(refresh_models=True)
    assert not release.catalog()
    with pytest.raises(ValueError):
        release.prepare(old)


def test_discovery_failure_never_uses_static_full_catalog(online,monkeypatch):
    m,state=online
    state['grants']['faker']['keys'][0]['models']=[]
    from core import model_catalog
    monkeypatch.setattr(model_catalog,'fetch',lambda *a: {'ok':False})
    m.verify(refresh_models=True)
    assert {r['model'] for r in release.catalog()}=={'slow'}
    assert m.profile['issues']


def test_offline_and_expiry_fail_closed_and_refresh_is_serialized(online,monkeypatch):
    m,state=online
    orig=m.post
    def post(action,body,token=''):
        if action=='verify':
            raise managed.LoginRequired('离线','auth_unavailable',503)
        return orig(action,body,token)
    monkeypatch.setattr(m,'post',post)
    with pytest.raises(managed.LoginRequired):
        m.require(state['cookie'],force=True)
    with pytest.raises(managed.LoginRequired):
        m.authorize_task(release.prepare(spec())[1]['_usage'])
    refreshes=[]
    def rotate(action,body,token=''):
        if action=='verify' and token=='a'*50:
            raise managed.LoginRequired('到期','access_expired')
        if action=='refresh':
            refreshes.append(body)
            return dict(access_token='b'*50,refresh_token='s'*50)
        return orig(action,body,token)
    monkeypatch.setattr(m,'post',rotate)
    threads=[threading.Thread(target=lambda: m.require(state['cookie'])) for _ in range(4)]
    for t in threads:t.start()
    for t in threads:t.join()
    assert len(refreshes)==1
    m.user['expires_at']=int(time.time())-1
    with pytest.raises(managed.LoginRequired):m.require(state['cookie'])


def test_uncertain_refresh_token_never_reused(online,monkeypatch):
    m,state=online
    def broken(action,*args):
        raise managed.LoginRequired('expired' if action=='verify' else 'offline',
                                    'access_expired' if action=='verify' else 'auth_unavailable',503)
    monkeypatch.setattr(m,'post',broken)
    with pytest.raises(managed.LoginRequired):m.require(state['cookie'],force=True)
    assert m.tokens is None and not release.catalog()


def fake_response(data,status=200):
    r=requests.Response();r.status_code=status;r._content=json.dumps(data).encode();r.encoding='utf-8'
    return r


@pytest.mark.parametrize('outcome,expected', [('success','completed'),('timeout','unknown'),('poll','pending'),('rejected','failed')])
def test_usage_tracks_submission_not_polling_and_no_uncertain_retries(online,monkeypatch,outcome,expected):
    m,state=online
    calls=[]
    def http(method,url,**kw):
        calls.append(method)
        if method=='POST':
            if outcome=='timeout':raise requests.Timeout()
            if outcome=='rejected':return fake_response({'error':{'message':'invalid duration'}},422)
            return fake_response({'id':'provider-task-id','status':'queued'})
        if outcome=='poll':raise requests.ConnectionError()
        return fake_response({'id':'provider-task-id','status':'completed'})
    monkeypatch.setattr(requests,'request',http)
    original=providers.REGISTRY['faker'].generate_image
    def generate(self,task,dest,**kw):
        self.session.request('POST','/v1/images/generations',retries=3)
        for _ in range(3):self.session.request('GET','/v1/tasks/id',retries=1)
        Path(dest).write_bytes(b'x'*800)
        return {'task_id':'provider-task-id'}
    monkeypatch.setattr(providers.REGISTRY['faker'],'generate_image',generate)
    raw=spec();raw['max_retry']=2
    run=batch.start(raw,{})
    wait(run)
    events=usage.pending('account-a')
    assert len(events)==1 and events[0]['status']==expected
    assert calls.count('POST')==1
    assert events[0]['key_id']=='key-1'
    if expected in ('pending','completed'):assert events[0]['task_id']=='provider-task-id'
    m.send_usage()
    assert not usage.pending('account-a')
    manifest=Path(run.manifest_path).read_text(encoding='utf-8')
    assert 'FAKE-KEY' not in manifest and 'upstream.invalid' not in manifest


def test_ack_race_and_cross_account_backlog(online):
    m,state=online
    assignment=release.prepare(spec())[1]['_usage']
    task=batch.build_tasks(dict(provider='faker',model='fast',tasks=[{'prompt':'t'}]))[0]
    with usage.tracking(assignment,task):
        usage.begin();old=usage.pending('account-a');usage.note('submitted','tid')
        usage.acknowledge('account-a',old)
        assert usage.pending('account-a')
    state['uid']='account-b'
    m.login(dict(username='b',password='p'))
    before=len(state['calls']);m.send_usage()
    assert len(state['calls'])==before
    assert usage.pending('account-a')
    state['uid']='account-a';m.login(dict(username='a',password='p'));m.send_usage()
    assert not usage.pending('account-a')


def test_skip_and_upload_failure_do_not_count_generation(online,monkeypatch):
    raw=spec()
    prepared,_=release.prepare(raw)
    task=batch.build_tasks(prepared)[0]
    Path(task.dest).parent.mkdir(parents=True,exist_ok=True);Path(task.dest).write_bytes(b'x'*800)
    run=batch.start(raw,{})
    wait(run)
    assert run.counts()['跳过']==1 and not usage.pending('account-a')


def test_http_login_gate_cookie_refresh_and_no_local_config(online,monkeypatch):
    from core import server
    from tools.build_managed import page
    m,state=online
    monkeypatch.setattr(distribution,'page',page)
    monkeypatch.setitem(server._RUN,'cur',None)
    httpd=server.serve(port=0)
    thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
    def request(route,body=None,cookie=''):
        conn=http.client.HTTPConnection('127.0.0.1',httpd.server_port,timeout=3)
        headers={'X-Respect-Session':server._SESSION,'Content-Type':'application/json','Cookie':cookie}
        conn.request('POST' if body is not None else 'GET',route,json.dumps(body) if body is not None else None,headers)
        result=conn.getresponse();status=result.status;payload=result.read();conn.close()
        return status,payload
    try:
        assert request('/api/boot')[0]==401
        assert request('/api/start',{'spec':spec()})[0]==401
        assert request('/api/config',{},state['cookie'])[0]==403
        assert request('/api/boot',cookie=state['cookie'])[0]==200
        assert request('/api/auth/refresh',{},state['cookie'])[0]==200
        assert request('/api/auth/logout',{},state['cookie'])[0]==200
        assert request('/api/boot',cookie=state['cookie'])[0]==401
        html=request('/')[1].decode()
        assert 'managed-signin' in html and 'base_url' not in html and 'id="tab-set"' not in html
    finally:httpd.shutdown();httpd.server_close();thread.join()


def test_stage_contains_no_profile_and_build_manifest_checks_executable(tmp_path,monkeypatch):
    from tools.build_managed import stage,manifests
    target=stage(tmp_path/'stage')
    module=(target/'core/distribution.py').read_text(encoding='utf-8')
    assert 'MANAGED = True' in module and 'manager.snapshot()' in module
    assert not (target/'config.json').exists()
    assert len(list((target/'core/providers').glob('*.py')))>=19
    exe=tmp_path/'RespectBatch-User.exe';exe.write_bytes(b'fake binary')
    manifest=manifests(exe,tmp_path)
    monkeypatch.setattr(paths,'PROGRAM_DIR',str(tmp_path))
    assert managed.build_headers()['X-Studio-Build']==manifest['build_sha256']
    exe.write_bytes(b'changed binary')
    with pytest.raises(managed.LoginRequired):managed.build_headers()


def test_managed_r2_uses_signature_without_local_credentials(online,monkeypatch,tmp_path):
    from core import uploader
    m,state=online
    cfg=dict(backend='managed',enabled=True,revision='a'*32,owner='account-a')
    monkeypatch.setattr(uploader,'encode_ref',lambda *a,**k:(b'pngbytes','image/png','.png',''))
    path=tmp_path/'ref.png';path.write_bytes(b'pngbytes')
    seen=[]
    def ticket(config,data,mime):
        seen.append((config,data,mime))
        return {'upload_url':'https://storage.invalid/signed','public_url':'https://cdn.invalid/ref.png'}
    monkeypatch.setattr(m,'storage_ticket',ticket)
    monkeypatch.setattr(requests.Session,'put',lambda *a,**k:fake_response({},200))
    assert uploader.to_url(str(path),cfg)=='https://cdn.invalid/ref.png'
    assert seen and all(k not in cfg for k in ('secret_key','access_key','api_key'))


def test_post_poll_does_not_create_new_usage_and_task_id_is_retained(online,monkeypatch):
    assignment=release.prepare(spec())[1]['_usage']
    task=batch.build_tasks(dict(provider='faker',model='fast',tasks=[{'prompt':'t'}]))[0]
    monkeypatch.setattr(requests,'request',lambda method,url,**kw: fake_response(
        {'taskId':'remote-123','status':'queued' if url.endswith('create_task') else 'completed'}))
    with usage.tracking(assignment,task):
        session=HttpSession('fake','https://upstream.invalid')
        session.request('POST','/api/multimodal/create_task')
        for _ in range(5):session.request('POST','/api/multimodal/get_result')
    events=usage.pending('account-a')
    assert len(events)==1 and events[0]['task_id']=='remote-123' and events[0]['status']=='completed'


def test_confirmed_rejection_retry_has_separate_attempt_ids(online,monkeypatch):
    calls=[]
    def http(*a,**kw):
        calls.append(1)
        return fake_response({'error':'rate limited'},429) if len(calls)==1 else fake_response({'id':'ok'})
    monkeypatch.setattr(requests,'request',http)
    monkeypatch.setattr(batch.time,'sleep',lambda seconds: None)
    def generate(self,task,dest,**kw):
        self.session.request('POST','/v1/images/generations',retries=3)
        Path(dest).write_bytes(b'x'*800)
        return {'task_id':'ok'}
    monkeypatch.setattr(providers.REGISTRY['faker'],'generate_image',generate)
    raw=spec();raw['max_retry']=1
    run=batch.start(raw,{})
    wait(run)
    events=usage.pending('account-a')
    assert len(calls)==2 and len(events)==2
    assert {e['status'] for e in events}=={'failed','completed'}
    assert len({e['event_id'] for e in events})==2


def test_crash_recovery_retains_id_and_sets_unknown_or_pending(online):
    m,state=online
    assignment=release.prepare(spec())[1]['_usage']
    task=batch.build_tasks(dict(provider='faker',model='fast',tasks=[{'prompt':'t'}]))[0]
    with usage.tracking(assignment,task):
        usage.begin()
        saved=usage.snapshot()
    saved['sequence']+=10;saved['status']='attempted'
    usage.persist('account-a',saved)
    usage.recover_interrupted('account-a')
    first=usage.pending('account-a')[0]
    assert first['event_id']==saved['event_id'] and first['status']=='unknown'
    saved.update(sequence=first['sequence']+1,status='submitted',task_id='task-x')
    usage.persist('account-a',saved);usage.recover_interrupted('account-a')
    assert usage.pending('account-a')[0]['status']=='pending'


def test_no_submission_when_usage_disk_is_unavailable(online,monkeypatch):
    def fail(*a):raise ValueError('disk unavailable')
    monkeypatch.setattr(usage,'persist',fail)
    monkeypatch.setattr(requests,'request',lambda *a,**k:pytest.fail('must persist before submission'))
    assignment=release.prepare(spec())[1]['_usage']
    task=batch.build_tasks(dict(provider='faker',model='fast',tasks=[{'prompt':'t'}]))[0]
    with pytest.raises(ValueError):
        with usage.tracking(assignment,task):HttpSession('fake','https://upstream.invalid').request('POST','/v1/images/generations')


def test_r2_available_fields_and_unsupported_grant_notice(online):
    cfg=grants();cfg['unsupported-route']={'keys':[{'api_key':'FAKE'}]}
    profile=managed_models.build('a',cfg,dict(assigned=True,available=True,revision='a'*32))
    from core.uploader import configured
    assert configured(profile['config']['upload']) and profile['issues']


def test_discovered_model_parameters_override_adapter_defaults(online,monkeypatch):
    from core import model_catalog
    m,state=online
    state['grants']['faker']['keys'][0]['models']=[]
    monkeypatch.setattr(model_catalog,'fetch',lambda *a:dict(ok=True,rows=[
        dict(id='fast',type='video',durations_seconds=[7,12],ratios=['16:9'],max_images=15)]))
    m.verify(refresh_models=True)
    row=next(r for r in release.catalog() if r['kind']=='video')
    assert row['options']['durations']==[7,12] and row['options']['max_refs']==15


def test_http_200_upstream_timeout_is_unknown_not_a_confirmed_rejection(online,monkeypatch):
    assignment=release.prepare(spec())[1]['_usage']
    task=batch.build_tasks(dict(provider='faker',model='fast',tasks=[{'prompt':'t'}]))[0]
    monkeypatch.setattr(requests,'request',lambda *a,**k:fake_response({'error':{'message':'upstream network timeout'}}))
    with pytest.raises(ApiError):
        with usage.tracking(assignment,task):
            HttpSession('fake','https://upstream.invalid').request('POST','/v1/images/generations')
            raise ApiError('no image returned')
    assert usage.pending('account-a')[0]['status']=='unknown'
