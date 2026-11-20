"""Evidence for batch sign-in and local login-page transitions."""
import hashlib
import json
import time
import uuid

from . import production_diagnostics as queue


PROCESS = uuid.uuid4().hex
KNOWN_CODES = frozenset('''access_expired invalid_session refresh_reused invalid_credentials
    account_disabled account_expired device_limit rate_limited auth_busy auth_unavailable
    auth_response_invalid client_unregistered update_required client_update_required
    configuration_invalid invalid_request https_required login_required application_not_granted application_mismatch'''.split())


def reason(error):
    code = getattr(error, 'code', '')
    return code if code in KNOWN_CODES else 'other_error'


def event(operation, error=False, category='none', status=0, request_id='', duration_ms=0, at=None):
    from .managed import VERSION
    return dict(event_id=str(uuid.uuid4()), kind='auth', operation=operation,
                at=int(time.time()) if at is None else at, outcome='error' if error else 'success',
                category=category, status=status, request_id=request_id,
                duration_ms=min(604800000, max(0, duration_ms)), version=VERSION)


def record(owner, operation, **details):
    if owner:
        queue.persist(owner, event(operation, **details))


def fingerprint(value):
    # The browser can identify its diagnostic context without revealing its HttpOnly cookie.
    return hashlib.sha256(('batch-login-diagnostic:' + value).encode()).hexdigest() if value else ''


def bind(local_session, owner):
    try:
        with queue.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS login_pages
                (marker TEXT PRIMARY KEY, owner TEXT NOT NULL, process TEXT NOT NULL,
                 at INTEGER NOT NULL, state TEXT NOT NULL, ended TEXT NOT NULL, request_id TEXT NOT NULL)''')
            now = int(time.time())
            db.execute('DELETE FROM login_pages WHERE at < ? AND process <> ?', (now - 30*86400, PROCESS))
            db.execute('INSERT INTO login_pages VALUES (?,?,?,?,?,?,?)',
                       (fingerprint(local_session), owner, PROCESS, now, 'ready', '', ''))
    except Exception:
        queue.recording_failed()


def ended(marker, owner, cause, error):
    request_id = getattr(error, 'request_id', '')
    cause = cause + '.' + reason(error) if error else cause
    record(owner, 'session_cleared.' + cause, error=bool(error),
           category=getattr(error, 'diagnostic_category', 'unknown') if error else 'none',
           request_id=request_id)
    if marker:
        try:
            with queue.connection() as db:
                db.execute('UPDATE login_pages SET ended=?, request_id=? WHERE marker=?',
                           (cause, request_id, marker))
        except Exception:
            queue.recording_failed()


def page(marker, state, *, request_id='', category='none', at=None):
    """Record one transition atomically, attributed only to a previously authenticated cookie."""
    if not marker:
        return
    try:
        with queue.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='login_pages'").fetchone():
                return
            row = db.execute('SELECT owner,process,state,ended,request_id FROM login_pages WHERE marker=?',
                             (marker,)).fetchone()
            if not row:
                return
            owner, process, previous, cause, cause_request = row
            if state == 'login_required':
                state = cause or ('client_restarted' if process != PROCESS else 'local_session_missing')
                request_id = cause_request
            elif cause and state != 'ready':
                state, request_id = cause, cause_request
            if state == 'ready' and (cause or process != PROCESS):
                return
            if state == previous:
                return
            payload = event('page_restored' if state == 'ready' else 'login_page.' + state,
                            error=state != 'ready', category=category, request_id=request_id, at=at)
            db.execute('INSERT INTO events(owner,at,payload) VALUES(?,?,?)',
                       (owner, payload['at'], json.dumps(payload)))
            db.execute('UPDATE login_pages SET state=?, at=? WHERE marker=?',
                       (state, int(time.time()), marker))
    except Exception:
        queue.recording_failed()
