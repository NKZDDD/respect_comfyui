"""Persist managed batch task updates until the signed-in owner's upload is acknowledged."""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from . import paths


@contextmanager
def queue():
    location = Path(paths.data_dir()) / 'task-history-outbox.sqlite3'
    location.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(location, timeout=15)
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS pending(owner TEXT,batch TEXT,idx INTEGER,seq INTEGER,'
                       'payload TEXT NOT NULL,PRIMARY KEY(owner,batch,idx))')
            yield db
    finally:
        db.close()


def record(run, tasks, status=None):
    owner = run.cfg.get('_usage', {}).get('owner')
    if not owner:
        return
    with queue() as db:
        for task in tasks:
            task.history_sequence += 1
            row = dict(batch=run.id, idx=task.idx, created=int(run.started), kind=task.kind,
                       model=run.label, prompt=task.prompt, sequence=task.history_sequence,
                       status=status or ('待取回' if task.download_retry else task.status))
            db.execute('INSERT INTO pending VALUES(?,?,?,?,?) ON CONFLICT(owner,batch,idx) DO UPDATE SET '
                       'seq=excluded.seq,payload=excluded.payload WHERE excluded.seq>pending.seq',
                       (owner,run.id,task.idx,row['sequence'],json.dumps(row,ensure_ascii=False)))


def send(manager):
    with manager.lock:
        if not manager.user or not manager.tokens:
            return False
        owner, token = manager.user['id'], manager.tokens['access_token']
    rows, keys, length = [], [], 0
    with queue() as db:
        for batch,idx,seq,payload in db.execute('SELECT batch,idx,seq,payload FROM pending WHERE owner=? '
                                                'ORDER BY rowid LIMIT 64',(owner,)):
            rows.append(json.loads(payload))
            keys.append([batch,idx,seq])
            length += len(payload.encode())
            if length >= 128_000:
                break
    if not rows:
        return False
    answer = manager.post('batch-tasks', dict(device_id=manager.device_id(),tasks=rows),token)
    if answer.get('accepted') != keys:
        raise ValueError('任务中心未确认收件')
    with queue() as db:
        db.executemany('DELETE FROM pending WHERE owner=? AND batch=? AND idx=? AND seq=?',
                       [(owner,*key) for key in keys])
    return True


def sender(manager):
    delay = 2
    while True:
        time.sleep(delay)
        try:
            delay = .1 if send(manager) else 5
            manager.history_error = ''
        except Exception:
            manager.history_error = '任务中心暂未同步，任务保存在本机等待补传'
            delay = min(60,max(5,delay*2))

