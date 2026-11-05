import json
import threading
import time

import pytest

from core import supplier_statistics as M



def test_supplier_percentage_is_not_recomputed_and_empty_samples_are_unknown():
    data = {'data': {'wan': {'success_rate': 97, 'total': 4, 'success': 1, 'avg_latency_s': 80},
                     'unused': {'success_rate': 100, 'total': 0}}}
    rows = M.normalize('ake', data)['models']
    assert rows[0]['rate'] == 97 and rows[0]['samples'] == 4
    assert rows[1]['rate'] is None and rows[1]['samples'] == 0


def test_zhongheng_maps_numeric_id_to_exact_public_name():
    result = M.normalize('zhongheng', {'generated_at': '2026-11-05T02:00:00Z', 'data': [
        {'model_id': 158, 'success_rate': 95.97, 'completed_count': 124, 'average_duration_seconds': 341.85}]},
        {'data': [{'id': '158', 'public_name': 'sedanco2.0-300秒必出'}]})
    assert result['models'][0]['model'] == 'sedanco2.0-300秒必出'
    assert result['models'][0]['rate'] == 95.97 and result['source_at'] > 0


def test_wuxian_preserves_groups_and_zero_samples():
    result = M.normalize('wuxianhuabu', {'data': [
        {'display_name': 'same', 'group_name': 'A', 'recent_performance': {'sample_size': 4, 'success_count': 3}},
        {'display_name': 'same', 'group_name': 'B', 'recent_performance': {'sample_size': 0, 'success_count': 0}}]})
    assert [(r['model'], r['variant'], r['rate']) for r in result['models']] == [('same', 'A', 75), ('same', 'B', None)]


def test_cangyuan_rejections_and_octopus_user_issues_have_different_denominators():
    result = M.normalize('cangyuan', {'data': {'ready': True, 'models': {'wan': {'tasks': [
        {'status': 'SUCCESS'}, {'status': 'REJECTED'}, {'status': 'FAILURE'}], 'average_ms': 80000}}}})
    assert result['models'][0]['rate'] == 33.33 and result['models'][0]['seconds'] == 80
    result = M.normalize('octopus', {'data': {'models': [{'model_name': 'wan', 'samples': [
        {'status': 'success'}, {'status': 'user_issue'}, {'status': 'failure'}]}]}})
    assert result['models'][0]['rate'] == 50 and result['models'][0]['samples'] == 2


@pytest.mark.parametrize('pid', ['julun', 'kunji', 'zeroapi', 'xiaobalong', 'valeclouds'])
def test_request_metrics_keep_valid_zero_but_not_missing_or_invalid(pid):
    result = M.normalize(pid, {'data': {'models': [
        {'model_name': 'zero', 'success_rate': 0, 'request_count': 2},
        {'model_name': 'empty', 'success_rate': 100, 'request_count': 0},
        {'model_name': 'hidden', 'success_rate': 100, 'has_data': False},
        {'model_name': 'bad', 'success_rate': 101},
        {'model_name': 'nan', 'success_rate': float('nan')} ]}})
    assert [r['rate'] for r in result['models']] == [0, None, None, None, None]
    assert result['scope'] == 'request'


def test_invalid_payload_does_not_masquerade_as_no_data():
    for payload in ({'success': False, 'data': {}}, {'data': {}}, {'data': {'ready': False}}):
        with pytest.raises((ValueError, KeyError)):
            M.normalize('cangyuan', payload)
    with pytest.raises(ValueError):
        M.normalize('octopus', {'data': {'models': [{'model_name': 'x', 'samples': [{'status': 'mystery'}]}]}})


def test_blocked_network_never_blocks_snapshot_and_coalesces_requests():
    entered, release = threading.Event(), threading.Event()
    calls = []
    def fetch(pid):
        calls.append(pid); entered.set(); release.wait(5)
        return {'models': [M.row('exact-model', 90)], 'source_at': 0, 'scope': 'task'}
    cache = M.StatisticsCache(fetch)
    try:
        assert cache.snapshot('ake')['state'] == 'loading'
        assert entered.wait(1)
        start = time.monotonic()
        for _ in range(50):
            assert cache.snapshot('ake')['refreshing']
        assert time.monotonic() - start < .5
        assert calls == ['ake']
        release.set(); cache.queue.join()
        result = cache.snapshot('ake')
        result['models'][0]['rate'] = -1
        assert cache.snapshot('ake')['models'][0]['rate'] == 90
    finally:
        release.set(); cache.close()


def test_failed_refresh_keeps_last_good_timestamp_and_marks_it_stale():
    clock = [1800000000]
    def fetch(pid):
        if clock[0] > 1800000000:
            raise TimeoutError('never send this upstream body or credential')
        return {'models': [M.row('x', 80)], 'source_at': 0, 'scope': 'task'}
    cache = M.StatisticsCache(fetch, lambda: clock[0])
    try:
        cache.snapshot('ake');cache.queue.join()
        clock[0] += M.TTL + 1
        cache.snapshot('ake');cache.queue.join()
        data = cache.snapshot('ake')
        assert data['state'] == 'error' and data['stale']
        assert data['fetched_at'] == 1800000000 and data['models'][0]['rate'] == 80
        assert 'credential' not in json.dumps(data)
    finally:
        cache.close()


def test_custom_address_never_fetches_or_receives_another_suppliers_metrics():
    cache = M.StatisticsCache(lambda pid: pytest.fail('must not fetch'))
    assert cache.snapshot('julun', 'https://different.example')['state'] == 'unsupported'
    assert cache.snapshot('gate')['state'] == 'unsupported'
    assert not cache.threads
    assert M.matches('cangyuan_video', 'https://ai.cangyuansuanli.cn')
    assert M.matches('zhongheng', 'https://cnd-coo-new.pages.dev')
    assert not M.matches('ake', 'https://snumom.com.evil.example')
