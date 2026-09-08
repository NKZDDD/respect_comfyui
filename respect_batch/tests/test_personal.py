import copy
from pathlib import Path

import pytest

from core import config, model_catalog, paths, providers
from core.providers.ake import AkeProvider
from core.providers.base import ImageTask, VideoTask


def test_builtin_registry_falls_back_without_pyinstaller_marker(monkeypatch):
    monkeypatch.setattr(providers.pkgutil, 'iter_modules', lambda *a: [])
    monkeypatch.setattr(providers.sys, 'frozen', False, raising=False)
    monkeypatch.setattr(providers, 'WARNINGS', [])
    assert providers._builtin_names() == providers._BUILTIN_ORDER
    assert len(providers._builtin_names()) == 17


def test_catalog_separates_media_without_hiding_unclassified_models():
    cap = providers.REGISTRY['aicopy']().capabilities()
    result = {'models': ['gpt-image-2-new', 'sd2.5-new', 'brand-new', 'gpt-5.5']}
    got = model_catalog.apply_catalog(cap, result, 'test')
    assert got['image']['models'] == ['gpt-image-2-new', 'brand-new']
    assert got['video']['models'] == ['sd2.5-new', 'brand-new']
    assert got['model_catalog']['other'] == ['gpt-5.5']
    assert got['model_catalog']['all_models'] == result['models']
    assert 'gpt-image-2-new' not in cap['image']['models']


def test_live_catalog_survives_restart_but_not_key_change(tmp_path, monkeypatch):
    monkeypatch.setitem(paths._forced, 'data', str(tmp_path))
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg['providers']['ake'] = {'api_key': 'test-key-one'}
    monkeypatch.setattr(model_catalog, 'fetch', lambda *a: {'ok': True, 'models': ['sd-2.5']})
    assert model_catalog.refresh('ake', cfg)['ok']
    got = next(c for c in model_catalog.capabilities(cfg) if c['id'] == 'ake')
    assert got['video']['models'] == ['sd-2.5']
    assert 'test-key-one' not in (tmp_path / 'model-catalog.json').read_text()
    monkeypatch.setattr(model_catalog, 'fetch', lambda *a: {'ok': False, 'msg': 'HTTP 401'})
    assert not model_catalog.refresh('ake', cfg)['ok']
    assert next(c for c in model_catalog.capabilities(cfg) if c['id'] == 'ake')['video']['models'] == ['sd-2.5']
    cfg['providers']['ake']['api_key'] = 'test-key-two'
    changed = next(c for c in model_catalog.capabilities(cfg) if c['id'] == 'ake')
    assert 'model_catalog' not in changed


def test_catalog_rejects_redirect_and_keeps_error_free_of_secret(monkeypatch):
    class Response:
        status_code = 302
    class Session:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get(self, url, **kw):
            assert kw['allow_redirects'] is False
            assert self.trust_env is False
            return Response()
    monkeypatch.setattr(model_catalog.requests, 'Session', Session)
    got = model_catalog.fetch('ake', {'api_key': 'private-test-key'})
    assert not got['ok'] and got['msg'] == 'HTTP 302'
    assert 'private-test-key' not in str(got)


@pytest.mark.parametrize('model,seconds,field', [('sd2.0', 8, 'image_refs'), ('sd-2.5', 30, 'images')])
def test_ake_new_video_contract(monkeypatch, model, seconds, field):
    prov = AkeProvider()
    calls = []
    def request(method, path, **kw):
        calls.append((path, kw['json_body']))
        return {'url': 'https://example.com/result.mp4'}
    monkeypatch.setattr(prov.session, 'request', request)
    monkeypatch.setattr(prov.session, 'save_item', lambda *a: None)
    prov.generate_video(VideoTask(model=model, prompt='test', duration=seconds,
        refs=['https://example.com/ref.png']), 'unused', log=lambda *a: None)
    endpoint, body = calls[0]
    assert endpoint == '/v1/videos'
    assert body[field] == ['https://example.com/ref.png']
    assert 'reference_images' not in body
    if model == 'sd-2.5':
        assert body['resolution'] == '720p'
    else:
        assert body['duration'] == seconds


def test_ake_image_uses_published_chat_endpoint(monkeypatch):
    prov = AkeProvider()
    def request(method, path, **kw):
        assert path == '/v1/chat/completions'
        assert kw['json_body']['messages'][0]['content'] == 'test image'
        return {'choices': [{'message': {'content': '![image](https://example.com/a.png)'}}]}
    saved = []
    monkeypatch.setattr(prov.session, 'request', request)
    monkeypatch.setattr(prov.session, 'save_item', lambda url, dest: saved.append(url))
    prov.generate_image(ImageTask(model='grok-imagine-image-quality-lite', prompt='test image'), 'unused')
    assert saved == ['https://example.com/a.png']


def test_ake_1080_preserves_pixel_size_separator(monkeypatch):
    prov = AkeProvider()
    def request(method, path, **kw):
        assert kw['json_body']['size'] == '1920x1080'
        return {'url': 'https://example.com/video.mp4'}
    monkeypatch.setattr(prov.session, 'request', request)
    monkeypatch.setattr(prov.session, 'save_item', lambda *a: None)
    prov.generate_video(VideoTask(prompt='test', model='minimax_h3-1080p',
                                  resolution='1920x1080'), 'unused', log=lambda *a: None)
