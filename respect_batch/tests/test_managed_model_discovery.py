"""Exercise discovery through downloaded Studio adapters, with no paid requests."""
import json
from pathlib import Path

import pytest
import requests

from tests.test_batch import sandbox
from tests.test_managed import online
from core import managed_models, model_catalog, providers, release
from core.apiutil import ApiError


def use_adapter(state, pid='valeclouds', cls='ValeCloudsProvider'):
    studio = Path(__file__).resolve().parents[2] / 'script-to-video-studio'
    source = studio / 'core/providers' / (pid + '.py')
    if not source.is_file():
        pytest.skip('Sibling Studio checkout required for adapter compatibility')
    state['bundle'] = dict(protocol=1, version='discovery-test', modules={pid: source.read_text(encoding='utf-8')},
        providers=[dict(id=pid, name=pid, module=pid, **{'class': cls})])
    state['grants'] = {pid: {'keys': [dict(api_key='PRIVATE-DISCOVERY-KEY', key_id='key-discovery',
        key_name='NY-vale' if pid == 'valeclouds' else 'CY', assignment_id='grant-discovery',
        base_url='https://upstream.invalid/v1', models=[])]}}


def endpoint(monkeypatch, body=None, status=200, error=None):
    calls = []

    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            assert url == 'https://upstream.invalid/v1/models'
            assert self.trust_env is False and kwargs['allow_redirects'] is False
            assert kwargs['headers']['Authorization'] == 'Bearer PRIVATE-DISCOVERY-KEY'
            if error:
                raise error

            class Response:
                status_code = status
                def json(self):
                    if isinstance(body, Exception):
                        raise body
                    return body
            return Response()

    monkeypatch.setattr(requests, 'Session', Session)
    monkeypatch.setattr(requests, 'request', lambda *a, **kw: pytest.fail('No generation or legacy list_models call'))
    return calls


def test_live_rows_preserve_types_parameters_and_exclude_non_media(online, monkeypatch):
    manager, state = online
    use_adapter(state)
    calls = endpoint(monkeypatch, {'data': [
        {'id': 'gpt-image-2.5-flare'},
        {'id': 'opaque-photo-id', 'output_modalities': ['image'],
         'supported_image_sizes': ['2048x2048'], 'max_reference_images': 12,
         'private_debug': 'PRIVATE-RESPONSE'},
        {'id': 'opaque-movie-id', 'type': 'video', 'capability_schema': {
            'durations': [30, 60], 'aspect_ratios': ['9:16'], 'resolutions': ['1080p']}},
        {'id': 'opaque-speech-id', 'output_modalities': ['audio']},
        {'id': 'lyria-3-pro'}, {'id': 'suno-v6'},
        {'id': 'opaque-chat-id', 'type': 'text'},
    ]})
    manager.verify(refresh_models=True)
    assert len(calls) == 1
    rows = {r['model']: r for r in release.catalog()}
    assert set(rows) == {'gpt-image-2.5-flare', 'opaque-photo-id', 'opaque-movie-id'}
    assert rows['opaque-photo-id']['options']['sizes'] == ['1024x1536', '1024x1024', '1536x1024', '2048x2048']
    assert rows['opaque-photo-id']['options']['resolutions'] == ['2048x2048']
    assert rows['opaque-photo-id']['options']['max_refs'] == 12
    assert rows['opaque-movie-id']['options']['durations'] == [30, 60]
    assert rows['opaque-movie-id']['options']['ratios'] == ['9:16']
    assert rows['opaque-movie-id']['route']['_usage']['key_id'] == 'key-discovery'
    assert not manager.profile['issues']
    public = json.dumps(release.public_boot())
    assert 'PRIVATE-' not in public


def test_unknown_notice_names_affected_models_without_disabling_known_models(online, monkeypatch):
    manager, state = online
    use_adapter(state)
    endpoint(monkeypatch, {'data': [{'id': 'gpt-image-2.5-flare'}, {'id': 'mystery-007'}]})
    manager.verify(refresh_models=True)
    assert [r['model'] for r in release.catalog()] == ['gpt-image-2.5-flare']
    notice = manager.profile['issues'][0]
    assert 'mystery-007' in notice and '1 个模型' in notice and '已列出的模型仍可选择' in notice
    assert '更新客户端' not in notice


@pytest.mark.parametrize('status,body,error,expected', [
    (401, {'error': 'PRIVATE-RESPONSE'}, None, 'HTTP 401，Key 鉴权失败'),
    (403, {}, None, 'HTTP 403'),
    (404, {}, None, 'HTTP 404'),
    (429, {}, None, 'HTTP 429'),
    (503, {}, None, 'HTTP 503'),
    (302, {}, None, 'HTTP 302'),
    (200, None, requests.Timeout('PRIVATE-RESPONSE'), '超时'),
    (200, None, requests.exceptions.SSLError('PRIVATE-RESPONSE'), 'HTTPS 连接失败'),
    (200, None, requests.ConnectionError('PRIVATE-RESPONSE'), '无法连接'),
    (200, ValueError('PRIVATE-RESPONSE'), None, '有效 JSON'),
    (200, {'error': 'PRIVATE-RESPONSE'}, None, '格式不兼容'),
    (200, {'data': []}, None, '未返回可用模型'),
])
def test_cangyuan_failure_reason_safe_and_no_fallback(online, monkeypatch, status, body, error, expected):
    manager, state = online
    use_adapter(state, 'cangyuan', 'CangyuanProvider')
    endpoint(monkeypatch, body, status, error)
    manager.verify(refresh_models=True)
    assert not release.catalog()  # Do not silently authorize the adapter's static catalogue.
    assert expected in manager.profile['issues'][0]
    assert 'PRIVATE-' not in json.dumps(manager.profile['issues'])


def test_cangyuan_refresh_recovers_and_bound_models_do_not_require_discovery(online, monkeypatch):
    manager, state = online
    use_adapter(state, 'cangyuan', 'CangyuanProvider')
    calls = endpoint(monkeypatch, {'data': [{'id': 'gpt-image-2.5-flare-1k'}]})
    manager.verify(refresh_models=True)
    assert len(calls) == 1 and not manager.profile['issues']
    row = release.catalog()[0]
    assert row['model'] == 'gpt-image-2.5-flare-1k'
    assert row['options']['max_refs'] == 16
    assert row['route']['api_key'] == 'PRIVATE-DISCOVERY-KEY'
    state['grants']['cangyuan']['keys'][0]['models'] = ['gpt-image-2.5-flare']
    manager.verify(refresh_models=True)
    assert len(calls) == 1  # Explicit bindings remain authoritative, no extra key or model lookup.
    assert [r['model'] for r in release.catalog()] == ['gpt-image-2.5-flare']


def test_adapter_readers_and_filters_are_used_and_metadata_is_sanitized(online, monkeypatch):
    manager, state = online
    cls = providers.REGISTRY['faker']
    pc = dict(api_key='test', base_url='https://upstream.invalid')
    monkeypatch.setattr(requests, 'Session', lambda: pytest.fail('custom reader must win'))
    monkeypatch.setattr(cls, 'catalog_rows', lambda self: [
        {'id': 'opaque', 'type': 'image', 'private_debug': 'PRIVATE-RESPONSE'},
        {'id': 'unavailable', 'type': 'image'}], raising=False)

    def filtered(self, rows):
        assert 'private_debug' not in rows[0]
        return [dict(rows[0], max_images=7)]
    monkeypatch.setattr(cls, 'filter_catalog', filtered, raising=False)
    got = model_catalog.fetch('faker', pc)
    assert got['ok'] and got['rows'] == [{'id': 'opaque', 'type': 'image', 'max_images': 7}]
    monkeypatch.delattr(cls, 'catalog_rows')
    got = model_catalog.fetch('faker', pc)
    assert got['ok'] and got['models'] == ['fast']  # Customized list_models remains supported.

    def broken(self):
        raise ApiError('PRIVATE-RESPONSE', status=401)
    monkeypatch.setattr(cls, 'list_models', broken)
    got = model_catalog.fetch('faker', pc)
    assert got['status'] == 401 and 'PRIVATE-' not in str(got)


def test_shared_key_precedence_and_non_media_bindings_remain_safe(online):
    manager, state = online
    cfg = state['grants']
    cfg['faker']['keys'][0]['models'] = ['midjourney-new', 'omni-fast', 'lyria-3-pro', 'suno-v6']
    cfg['faker']['keys'][1]['models'] = ['midjourney-new']
    profile = managed_models.build('account-a', cfg, {})
    assert {(r['model'], r['kind']) for r in profile['models']} == {
        ('midjourney-new', 'image'), ('omni-fast', 'video')}
    assert all(r['route']['_usage']['key_id'] == 'key-1' for r in profile['models'])
    assert not profile['issues']
