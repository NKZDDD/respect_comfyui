import json

import pytest
from core import batch, task_history
from tests.test_batch import sandbox  # noqa: F401
from tests.test_managed import online, spec, wait  # noqa: F401


def test_real_batch_records_full_prompt_and_replays_only_for_owner(online, monkeypatch):
    manager,_ = online
    request = spec()
    text = '服装纹理和结构\n' * 500
    request['tasks'][0]['prompt'] = text
    monkeypatch.setattr(batch,'_dispatch',lambda *args:{})
    run = batch.start(request,{})
    wait(run)
    def read():
        with task_history.queue() as db:
            return db.execute('SELECT owner,payload FROM pending').fetchall()
    owner,raw = read()[0]
    row = json.loads(raw)
    assert owner=='account-a' and row['prompt']==text.strip() and row['status']=='完成'
    assert 'FAKE-KEY' not in raw
    manager.user['id']='another'
    assert not task_history.send(manager) and read()
    manager.user['id']=owner
    def fail(*args):
        raise OSError('offline')
    monkeypatch.setattr(manager,'post',fail)
    with pytest.raises(OSError): task_history.send(manager)
    assert read()
    def acknowledge(action,body,token):
        assert action=='batch-tasks' and body['tasks']==[row]
        task_history.record(run,run.tasks,'待取回')  # New state while acknowledgement is in flight.
        return {'accepted':[[row['batch'],row['idx'],row['sequence']]]}
    monkeypatch.setattr(manager,'post',acknowledge)
    assert task_history.send(manager)
    assert json.loads(read()[0][1])['status']=='待取回'
    monkeypatch.setattr(manager,'post',lambda a,b,t:{'accepted':[[r['batch'],r['idx'],r['sequence']] for r in b['tasks']]})
    assert task_history.send(manager) and not read()

