import hashlib
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import managed, paths, updates
from tests.test_batch import sandbox


def release(data=b'MZ-install-test', **overrides):
    return dict(application='batch', flavor='batch', version='2026.10.30.1',
                url='https://cdn.example.com/batch-updates/batch/Respect-Batch-Setup-2026.10.30.1.exe',
                sha256=hashlib.sha256(data).hexdigest(), build_sha256='b'*64,
                bytes=len(data), notes='test', **overrides)


class Response:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status
        self.raw = io.BytesIO(data)
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, size): yield self.data


def network(monkeypatch, response):
    calls=[]
    class Session:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def get(self,url,**kwargs):
            calls.append((url,kwargs))
            return response
    monkeypatch.setattr(updates.requests,'Session',Session)
    return calls


@pytest.mark.parametrize('field,value', [('application','studio'),('flavor','all'),
    ('url','https://cdn.example.com/Respect-Studio-Setup-2026.10.30.1.exe'),
    ('url','http://cdn.example.com/Respect-Batch-Setup-2026.10.30.1.exe'),('bytes',True),('sha256','bad')])
def test_reject_wrong_application_and_invalid_manifest(field,value):
    row=release();row[field]=value
    with pytest.raises(ValueError): updates.validate_release(row)


@pytest.mark.parametrize('body,status,ready',[(b'MZ-install-test',200,True),(b'wrong',200,False),(b'',302,False)])
def test_download_checks_real_bytes_and_refuses_redirects(sandbox,monkeypatch,body,status,ready):
    m=updates.UpdateManager();m.release=release()
    calls=network(monkeypatch,Response(body,status))
    m._download(m.release)
    assert (m.phase=='ready') is ready
    assert not calls[0][1]['allow_redirects']
    assert not list((Path(paths.data_dir())/'updates').glob('*.part'))
    assert bool(m.installer) is ready


def test_check_targets_batch_and_supports_login_blocked_update(sandbox,monkeypatch):
    import json
    row=release()
    response=dict(application='batch',policy_protocol=1,client={'allowed':False,'code':'update_required'},release=row)
    calls=network(monkeypatch,Response(json.dumps(response).encode()))
    monkeypatch.setattr(managed,'build_headers',lambda:{'X-Studio-Flavor':'batch'})
    m=updates.UpdateManager();m._check()
    assert m.phase=='available' and m.required
    assert calls[0][1]['params']=={'application':'batch','flavor':'batch'}
    response['application']='studio'
    network(monkeypatch,Response(json.dumps(response).encode()))
    m._check()
    assert m.phase=='error'


def test_install_rechecks_hash_and_waits_for_workers(sandbox):
    m=updates.UpdateManager();m.release=release()
    m.installer=Path(paths.data_dir())/'installer.exe';m.installer.write_bytes(b'MZ-install-test')
    m.phase='ready';calls=[];m.install_callback=calls.append
    with pytest.raises(ValueError,match='任务运行'):
        m.install(SimpleNamespace(status='跑批中'))
    assert not calls
    m.installer.write_bytes(b'MZ-unknown-test')
    with pytest.raises(ValueError,match='改变'):
        m.install(None)
    assert not calls
    m.installer.write_bytes(b'MZ-install-test')
    assert m.install(None)['phase']=='installing' and calls==[m.installer]


def test_handoff_targets_only_batch_with_safe_process_arguments(monkeypatch,tmp_path):
    calls=[]
    monkeypatch.setattr(paths,'PROGRAM_DIR',str(tmp_path/'batch & directory'))
    monkeypatch.setattr(updates.subprocess,'Popen',lambda *a,**k:calls.append((a,k)))
    updates.launch_installer(tmp_path/'update package.exe')
    cmd=calls[0][0][0]
    assert '/BATCHUPDATE=' in cmd and '/STUDIOUPDATE=' not in cmd
    assert cmd.endswith(' /D='+str((tmp_path/'batch & directory').resolve()))
    assert calls[0][1].get('shell') is not True


def test_release_upload_uses_separate_r2_prefix_and_exports_no_credentials(tmp_path,monkeypatch):
    import json
    from tools import upload_update
    row=release()
    manifest=tmp_path/'release.json';manifest.write_text(json.dumps(row),encoding='utf-8')
    (tmp_path/'Respect-Batch-Setup-2026.10.30.1.exe').write_bytes(b'MZ-install-test')
    calls=[]
    class Missing(Exception): response={'Error':{'Code':'404'}}
    class Client:
        def head_object(self,**kwargs): raise Missing()
        def put_object(self,**kwargs): calls.append(kwargs)
    monkeypatch.setattr(upload_update.uploader,'_client',lambda cfg:Client())
    monkeypatch.setattr(upload_update,'verify_public',lambda r:None)
    output,data=upload_update.upload_release(manifest,dict(bucket='fake',access_key='not-real-access',secret_key='not-real-secret',public_base_url='https://cdn.example.com'))
    assert calls[0]['Key'].startswith('batch-updates/batch/Respect-Batch-Setup-')
    assert calls[0]['IfNoneMatch']=='*'
    assert data['application']=='batch' and data['mandatory'] is False
    assert 'not-real-' not in output.read_text(encoding='utf-8')


def test_release_upload_rejects_studio_before_upload(tmp_path,monkeypatch):
    import json
    from tools import upload_update
    row=release();row['application']='studio';row['flavor']='all'
    manifest=tmp_path/'release.json';manifest.write_text(json.dumps(row),encoding='utf-8')
    calls=[]
    monkeypatch.setattr(upload_update.uploader,'_client',lambda cfg:calls.append(cfg))
    with pytest.raises(ValueError,match='不属于'):
        upload_update.upload_release(manifest,dict(bucket='fake',access_key='fake',secret_key='fake',public_base_url='https://cdn.example.com'))
    assert not calls
