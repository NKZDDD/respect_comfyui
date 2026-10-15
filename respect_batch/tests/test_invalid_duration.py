from types import SimpleNamespace

import pytest

from core import apiutil as A, batch


@pytest.mark.parametrize('status', [0, 200, 400, 500])
def test_duration_code_never_retries(status):
    assert A.classify(status, 'please retry', 'invalid_duration') == A.TASK_FATAL


def test_polled_invalid_duration_only_submits_once(tmp_path, monkeypatch):
    calls = []
    def dispatch(*args):
        calls.append(True)
        raise A.task_failed({'status': 'failed', 'error': {
            'code': 'invalid_duration', 'message': '视频时长必须在 4～30 秒之间，请调整时长后重试。'}})
    monkeypatch.setattr(batch, '_dispatch', dispatch)
    task = batch.Task(1, 'video', 'fixture', 'fixture', 'x', [], str(tmp_path/'x.mp4'), duration=20)
    run = SimpleNamespace(spec={'skip_existing': False}, cfg={}, cancelled=lambda: False, log=lambda *a: None)
    batch._execute(run, task, object(), lambda r, log: r, max_retry=2)
    assert calls == [True]
    assert task.status == '失败' and task.attempts == 1
    assert task.error_kind == A.TASK_FATAL


def test_network_timeout_still_retryable():
    assert A.classify(0, 'network timeout') == A.RETRYABLE
