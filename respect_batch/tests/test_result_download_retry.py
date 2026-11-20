import io
import json
import time
import threading
import http.client
from pathlib import Path

import pytest
import requests
from PIL import Image

from core import batch, release, server, managed_usage, production_diagnostics
from core.apiutil import HttpSession, ApiError, TASK_FATAL, RETRYABLE
from tests.test_managed import online, spec  # noqa: F401
from tests.test_batch import sandbox  # noqa: F401


def finish(run):
    until = time.monotonic() + 4
    while run.status == '下载中' and time.monotonic() < until:
        time.sleep(.01)
    assert run.status != '下载中'


def test_tls_failure_keeps_result_for_get_only_retry_and_same_usage(online, monkeypatch, tmp_path):
    _, state = online
    selected = tmp_path / '独立交付' / '产品图'
    request = spec()
    request['tasks'][0]['output_folder'] = str(selected)
    raw, cfg = release.prepare(request)
    task = batch.build_tasks(raw)[0]
    run = batch.Run([task], raw, cfg)
    source = 'https://cdn.invalid/result.png?Signature=PRIVATE-SIGNATURE'
    session = HttpSession('FAKE-KEY', 'https://upstream.invalid')
    calls, downloads = [], []
    ready = threading.Event()
    def send(method,url,**kwargs):
        calls.append(method)
        response=requests.Response();response.status_code=200
        response._content=b'{"id":"provider-task-1","status":"queued"}'
        return response
    def save(item,dest,**kwargs):
        downloads.append(item)
        if not ready.is_set():
            raise requests.exceptions.SSLError('unexpected EOF '+source)
        Path(dest).write_bytes(b'valid-result')
        return dest
    monkeypatch.setattr(requests,'request',send)
    monkeypatch.setattr(session,'_save_once',save)
    class Provider:
        def generate_image(self, value, dest, **kwargs):
            session.request('POST','/v1/images/generations',json_body={'model':value.model})
            session.save_item(source,dest,retries=1)
    batch._execute(run,task,Provider(),lambda r,log:r,8)
    run.status='已完成'
    assert calls==['POST'] and task.attempts==1 and task.download_retry
    assert task.status=='失败' and 'TLS' in task.error
    before=managed_usage.pending('account-a')[0]
    assert before['status']=='pending'
    assert 'PRIVATE-SIGNATURE' not in json.dumps(run.snapshot())
    ready.set()
    run.retry_download(task.idx)
    finish(run)
    assert task.status=='完成' and task.attempts==1 and not task.download_retry
    assert Path(task.dest).parent == selected and Path(task.dest).read_bytes() == b'valid-result'
    assert calls==['POST'] and downloads==[source,source]
    reports=managed_usage.pending('account-a')
    assert len(reports)==1 and reports[0]['event_id']==before['event_id']
    assert reports[0]['status']=='completed' and reports[0]['sequence']>before['sequence']
    with production_diagnostics.connection() as db:
        events=[json.loads(r[0]) for r in db.execute('SELECT payload FROM events')]
    assert events[-1]['production']['usage_event_id']==before['event_id']
    assert events[-1]['outcome']=='success'
    assert 'PRIVATE-SIGNATURE' not in json.dumps(events)


def test_empty_result_is_never_reclassified_as_retryable_generation(monkeypatch,tmp_path):
    session=HttpSession('KEY','https://api.invalid')
    def empty(*args,**kwargs):
        raise ApiError('取回 0 字节',kind=RETRYABLE)
    monkeypatch.setattr(session,'_save_once',empty)
    with pytest.raises(ApiError) as caught:
        session.save_item('https://cdn.invalid/file.mp4',str(tmp_path/'file.mp4'),retries=1)
    assert caught.value.kind==TASK_FATAL
    assert caught.value.err_code=='result_download_failed'
    assert caught.value.download_retry[0] is session


def test_real_download_reuses_source_after_tls_and_keeps_certificate_checks(monkeypatch,tmp_path):
    session=HttpSession('KEY','https://api.invalid')
    data=io.BytesIO();Image.new('RGB',(24,24),'green').save(data,format='PNG',compress_level=0)
    url='https://cdn.invalid/file.png?Signature=PRIVATE'
    calls=[]
    def get(source,**kwargs):
        calls.append((source,kwargs))
        if len(calls)==1:
            raise requests.exceptions.SSLError('EOF')
        r=requests.Response();r.status_code=200;r.raw=io.BytesIO(data.getvalue())
        r.headers['Content-Length']=str(len(data.getvalue()))
        return r
    monkeypatch.setattr(requests,'get',get)
    monkeypatch.setattr('core.apiutil.time.sleep',lambda _:None)
    destination=tmp_path/'file.png'
    session.save_item(url,str(destination),retries=2)
    assert destination.read_bytes()==data.getvalue()
    assert len(calls)==2 and all(c[0]==url and c[1].get('verify',True) for c in calls)


def test_retry_endpoint_checks_account_session_batch_and_in_flight_state(online,monkeypatch):
    manager,state=online
    raw,cfg=release.prepare(spec());task=batch.build_tasks(raw)[0]
    run=batch.Run([task],raw,cfg);run.status='已完成';task.status='失败'
    entered,unblock=threading.Event(),threading.Event()
    class Session:
        def save_item(self,*args,**kwargs):
            entered.set();unblock.wait(5)
    task.download_retry=(Session(),'https://cdn.invalid/private')
    next_run=batch.Run([],raw,cfg)
    next_run.status='跑批中'
    monkeypatch.setattr(server, '_RUNS', {run.id: run, next_run.id: next_run})
    httpd=server.serve(port=0);worker=threading.Thread(target=httpd.serve_forever,daemon=True);worker.start()
    def post(body,token=True):
        conn=http.client.HTTPConnection('127.0.0.1',httpd.server_port,timeout=3)
        headers={'Cookie':state['cookie'],'Content-Type':'application/json'}
        if token:headers['X-Respect-Session']=server._SESSION
        conn.request('POST','/api/retry-download',json.dumps(body),headers)
        r=conn.getresponse();out=r.status,json.loads(r.read());conn.close();return out
    body=dict(run_id=run.id,task_idx=1)
    try:
        assert post(body,False)[0]==403
        assert post(dict(body,run_id='other'))[0]==400
        assert post(dict(body,url='https://not-allowed.invalid'))[0]==400
        owner=manager.user['id'];manager.user['id']='other'
        assert post(body)[0]==403
        manager.user['id']=owner
        assert post(body)[1]['ok']
        assert entered.wait(2)
        assert post(body)[0]==400
    finally:
        unblock.set();finish(run)
        httpd.shutdown();worker.join(3);httpd.server_close()
