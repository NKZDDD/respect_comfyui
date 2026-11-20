"""Account-bound production evidence. Never store raw bodies, prompts or credentials."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid

from . import paths

_current = ContextVar('batch_production_diagnostics', default=None)
_lock = threading.RLock()
_dropped = 0
_recording_error = False


def label(value, limit=160):
    value = str(value or '')
    if (len(value) > limit or not re.fullmatch(r'[\w .:/(){}+@-]*', value)
            or re.search(r'\bsk-|bearer|secret|password|https?://', value, re.I)):
        return ''
    return value


def opaque_id(value):
    # Adapters sometimes use local filenames as their synthetic task ID.
    # Those can contain prompt text; only ordinary upstream ID shapes are retained.
    value = str(value or '')
    return label(value) if re.fullmatch(r'[a-zA-Z0-9_-]{1,160}', value) else ''


def error_info(error):
    """Recognized error tokens only; arbitrary provider messages can contain secrets."""
    if error is None:
        return dict(category='none', status=0, exception_type='', error_hint='', upstream_request_id='')
    text = str(error)[:8192]
    status = getattr(error, 'status', 0)
    match = re.search(r'\bHTTP\s*[:=]?\s*([45]\d\d)\b', text, re.I)
    if not isinstance(status, int) or not 400 <= status <= 599:
        status = int(match[1]) if match else 0
    request = re.search(r'request[_ -]?id[\s"\x27:=\\]+([a-zA-Z0-9_-]{8,128})', text, re.I)
    nodes, names, seen = [error], [], set()
    while nodes and len(seen) < 20:
        item = nodes.pop(0)
        if not isinstance(item, BaseException) or id(item) in seen:
            continue
        seen.add(id(item)); names.append(type(item).__name__.lower())
        nodes.extend([item.__cause__, item.__context__, getattr(item, 'reason', None)])
    types = ' '.join(names)
    hint = ('proxy_connection' if 'proxyerror' in types or 'ProxyError' in text else
            'model_missing' if re.search(r'model name (?:not specified|cannot be empty)', text, re.I) else
            'single_reference_only' if re.search(r'accepts one reference|Blend is not enabled', text, re.I) else
            'r2_unauthorized' if re.search(r'未获.*R2.*授权', text, re.I) else
            'r2_unavailable' if '图片上传服务尚未配置' in text or 'R2 上传授权生成失败' in text else
            'bad_gateway' if status == 502 else '')
    category = ('authentication' if status in (401, 403) else 'http' if status else
                'connection' if hint == 'proxy_connection' else
                'dns' if 'gaierror' in types or 'nameresolution' in types else
                'tls' if 'ssl' in types or 'certificate' in types else
                'timeout' if 'timeout' in types else
                'connection' if 'connection' in types else
                'validation' if isinstance(error, ValueError) or hint.startswith('r2_') else 'unknown')
    return dict(category=category, status=status, exception_type=label(type(error).__name__, 80),
                error_hint=hint, upstream_request_id=label(request[1], 128) if request else '')


@contextmanager
def connection():
    file = Path(paths.data_dir()) / 'production-diagnostics.sqlite3'
    file.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(file, timeout=.25)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS events '
                   '(id INTEGER PRIMARY KEY,owner TEXT NOT NULL,at INTEGER NOT NULL,payload TEXT NOT NULL)')
        with db:
            yield db
    finally:
        db.close()


def recording_failed():
    global _dropped, _recording_error
    _dropped += 1
    _recording_error = True


def persist(owner, event):
    global _recording_error
    try:
        with _lock, connection() as db:
            db.execute('INSERT INTO events(owner,at,payload) VALUES(?,?,?)',
                       (owner, event['at'], json.dumps(event, ensure_ascii=False)))
        _recording_error = False
    except Exception:
        recording_failed()


def stage(name):
    state = _current.get()
    if state is not None:
        state['stage'] = name


def observe_network():
    state = _current.get()
    if state is not None:
        try:
            from . import network
            state['network_mode'] = network.load()['mode']
        except Exception:
            state['network_mode'] = 'unknown'


@contextmanager
def attempt(run, task, *, reuse_usage=False):
    """One record per worker attempt, including errors before a billable submit."""
    assignment = run.cfg.get('_usage') or {}
    if not assignment.get('owner'):
        yield
        return
    state = dict(stage='authorize', observed={}, network_mode='unknown')
    previous_usage = task.usage
    token = _current.set(state)
    observe_network()
    started, error = time.monotonic(), None
    try:
        yield
    except Exception as exc:
        error = exc
        raise
    finally:
        try:
            from . import managed
            info = error_info(error)
            usage = task.usage if reuse_usage or task.usage is not previous_usage else {}
            usage = usage or {}
            production = dict(application='batch', batch_id=label(run.id), task_index=task.idx,
                attempt=task.attempts, provider=label(task.provider), model=label(task.model),
                key_id=label(assignment.get('key_id')), key_name=label(assignment.get('key_name')),
                usage_event_id=usage.get('event_id', ''), task_id=opaque_id(usage.get('task_id')),
                result_state=usage.get('status', 'not_submitted'), reference_count=len(task.refs),
                stage=state['stage'] if error else 'complete', network_mode=state['network_mode'],
                adapter_hash=run.cfg.get('_adapter_sha256', ''), **state['observed'])
            production.update({k:v for k,v in info.items() if k not in ('category', 'status') and v})
            event = dict(event_id=str(uuid.uuid4()), at=int(time.time()), kind='provider',
                operation=production['stage'], outcome='error' if error else 'success',
                duration_ms=min(604800000, max(0, round((time.monotonic()-started)*1000))),
                status=info['status'] or state['observed'].get('http_status', 0),
                category=info['category'], version=managed.VERSION, production=production)
            persist(assignment['owner'], event)
        except Exception:
            # Evidence must never change retries, task results, or charging behavior.
            global _dropped, _recording_error
            _dropped += 1
            _recording_error = True
        finally:
            _current.reset(token)


def observe_response(response):
    state = _current.get()
    if state is None:
        return
    try:
        state['observed']['http_status'] = int(response.status_code)
        headers = response.headers
        state['observed']['upstream_request_id'] = label(
            headers.get('x-request-id') or headers.get('request-id') or headers.get('x-tt-logid'), 128)
    except Exception:
        pass


def request_call(fn):
    @wraps(fn)
    def wrapped(session, method, path, **kw):
        state = _current.get()
        if state is not None:
            try:
                # Do not upload arbitrary paths or signed query strings.
                state['stage'] = 'submit' if method.upper() == 'POST' else 'query'
                body = kw.get('json_body') or kw.get('raw_body')
                if isinstance(body, dict) and (body.get('task_id') or body.get('taskId')):
                    state['stage'] = 'query'
                elif kw.get('submit') is False:
                    state['stage'] = 'request'
                model = body.get('model') if isinstance(body, dict) else None
                if model is None and kw.get('files'):
                    parts = kw['files'].items() if isinstance(kw['files'], dict) else kw['files']
                    for name, value in parts:
                        if name == 'model':
                            model = value[1] if isinstance(value, tuple) else value
                            break
                if method.upper() == 'POST' or model is not None:
                    state['observed']['wire_model'] = label(model)
                state['observed'].pop('http_status', None)
                state['observed'].pop('upstream_request_id', None)
            except Exception:
                pass
        return fn(session, method, path, **kw)
    return wrapped


def download_call(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        stage('download')
        observe_network()
        return fn(*args, **kwargs)
    return wrapped


def status(owner):
    try:
        with _lock, connection() as db:
            count = db.execute('SELECT COUNT(*) FROM events WHERE owner=?', (owner,)).fetchone()[0]
        return dict(pending=count, recording_error=_recording_error, dropped=_dropped)
    except Exception:
        return dict(pending=None, recording_error=True, dropped=_dropped)


def send(manager):
    if time.monotonic() < getattr(manager, '_diagnostics_retry_at', 0):
        return
    # Snapshot owner and its token together. The network call does not hold the production/auth lock.
    with manager.lock:
        if not manager.user or not manager.tokens:
            return
        owner, token = manager.user['id'], manager.tokens['access_token']
    try:
        with _lock, connection() as db:
            rows = db.execute('SELECT id,payload FROM events WHERE owner=? ORDER BY id LIMIT 20', (owner,)).fetchall()
        if not rows:
            return
        events = [json.loads(row[1]) for row in rows]
        body = dict(device_id=manager.device_id(), events=events,
                    dropped=min(_dropped, 2147483647), recording_error=_recording_error)
        while len(json.dumps(body).encode('utf-8')) > 14000 and len(events) > 1:
            events.pop(); rows.pop()
        result = manager.post('diagnostics', body, token)
        if result.get('accepted') != [e['event_id'] for e in events]:
            raise ValueError('diagnostics not acknowledged')
        with _lock, connection() as db:
            # SQLite can reuse IDs after the queue becomes empty.
            db.executemany('DELETE FROM events WHERE id=? AND owner=? AND payload=?',
                           [(row[0], owner, row[1]) for row in rows])
        manager._diagnostics_error = ''
        manager._diagnostics_retry_delay = 0
    except Exception as exc:
        manager._diagnostics_error = ('诊断服务需升级，记录已暂存' if getattr(exc, 'status', 0) in (404, 422)
                                      else '诊断暂未同步，恢复连接后自动补报')
        delay = min(300, max(15, getattr(manager, '_diagnostics_retry_delay', 0)*2))
        manager._diagnostics_retry_delay = delay
        manager._diagnostics_retry_at = time.monotonic()+delay
