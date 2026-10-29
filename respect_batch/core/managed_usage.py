"""Account-scoped durable usage outbox; records are reconciliation evidence, not bills."""
import contextvars
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import paths

_context = contextvars.ContextVar('batch_usage', default=None)
_lock = threading.RLock()
_error = ''


@contextmanager
def connection():
    path = Path(paths.data_dir()) / 'usage-outbox.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS reports(owner TEXT,event_id TEXT,sequence INTEGER,payload TEXT,dirty INTEGER,PRIMARY KEY(owner,event_id))')
    try:
        with db:
            yield db
    finally:
        db.close()


def persist(owner, event):
    global _error
    try:
        with _lock, connection() as db:
            db.execute('INSERT INTO reports VALUES(?,?,?,?,1) ON CONFLICT(owner,event_id) DO UPDATE SET '
                       'sequence=excluded.sequence,payload=excluded.payload,dirty=1',
                       (owner, event['event_id'], event['sequence'], json.dumps(event)))
        _error = ''
    except (OSError, sqlite3.Error):
        _error = '用量记录暂存失败，请检查磁盘空间；已发任务不会重新提交'
        raise ValueError(_error) from None


def active():
    return _context.get() is not None


def begin():
    ctx = _context.get()
    if ctx is None:
        return
    if ctx.get('event') and ctx['event']['status'] != 'failed':
        from .apiutil import ApiError, TASK_FATAL
        raise ApiError('上一提交结果待确认，不自动重新生成，请核对任务记录', kind=TASK_FATAL)
    now = int(time.time())
    event = dict(event_id=str(uuid.uuid4()), sequence=1, provider=ctx['provider'],
                 model=ctx['model'], kind=ctx['kind'], source='managed',
                 assignment_id=ctx['assignment_id'], key_id=ctx['key_id'], key_name=ctx['key_name'],
                 task_id='', status='attempted', resumed=False, started_at=now, updated_at=now)
    persist(ctx['owner'], event)  # Must succeed before a new billable request.
    ctx['event'] = event


def note(status, task_id=''):
    ctx = _context.get()
    if not ctx or not ctx.get('event'):
        return
    event = ctx['event']
    event.update(sequence=event['sequence'] + 1, status=status, updated_at=int(time.time()))
    if task_id:
        event['task_id'] = str(task_id)[:200]
    try:
        persist(ctx['owner'], event)
    except ValueError:
        pass  # Never turn successful generation into a resubmission on disk errors.


def response(method, data):
    if not active():
        return
    from .apiutil import extract_task_id, extract_status, FAIL_STATES
    if extract_status(data) in FAIL_STATES:
        note('failed')
    elif method.upper() == 'POST':
        note('submitted', extract_task_id(data))


def failed_request(status=0):
    # Network/5xx/invalid JSON may occur after the upstream accepted a request.
    note('failed' if 400 <= status < 500 and status not in (408, 409, 425) else 'unknown')


def snapshot():
    ctx = _context.get()
    return dict(ctx['event']) if ctx and ctx.get('event') else None


@contextmanager
def tracking(assignment, task):
    if not assignment:
        yield
        return
    token = _context.set(dict(assignment, provider=task.provider, model=task.model, kind=task.kind))
    try:
        yield
        event = snapshot()
        if event:
            note('completed', (task.meta or {}).get('task_id', ''))
    except Exception:
        event = snapshot()
        if event and event['status'] not in ('failed', 'unknown'):
            note('pending' if event['task_id'] else 'unknown')
        raise
    finally:
        event = snapshot()
        if event:
            task.usage = event
        _context.reset(token)


def pending(owner):
    with _lock, connection() as db:
        return [json.loads(row[0]) for row in db.execute(
            'SELECT payload FROM reports WHERE owner=? AND dirty=1 ORDER BY rowid LIMIT 20', (owner,))]


def acknowledge(owner, events):
    with _lock, connection() as db:
        for event in events:
            db.execute('UPDATE reports SET dirty=0 WHERE owner=? AND event_id=? AND sequence=?',
                       (owner, event['event_id'], event['sequence']))


def status(owner):
    try:
        with _lock, connection() as db:
            count = db.execute('SELECT COUNT(*) FROM reports WHERE owner=? AND dirty=1', (owner,)).fetchone()[0]
        return {'pending': count, 'error': _error}
    except (OSError, sqlite3.Error):
        return {'pending': None, 'error': '用量记录目录不可用'}


def recover_interrupted(owner):
    """After a process restart, never present interrupted attempts as confirmed failures."""
    with _lock, connection() as db:
        rows = db.execute('SELECT payload FROM reports WHERE owner=?', (owner,)).fetchall()
        for row in rows:
            event = json.loads(row[0])
            if event['status'] in ('attempted', 'submitted'):
                event.update(status='pending' if event['task_id'] else 'unknown',
                             sequence=event['sequence']+1, updated_at=int(time.time()))
                db.execute('UPDATE reports SET sequence=?,payload=?,dirty=1 WHERE owner=? AND event_id=?',
                           (event['sequence'], json.dumps(event), owner, event['event_id']))
