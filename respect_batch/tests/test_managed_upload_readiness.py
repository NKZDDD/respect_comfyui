import json

import pytest

from core import assets, release, uploader
from core.apiutil import ApiError
from tests.test_batch import sandbox
from tests.test_managed import online, spec


@pytest.mark.parametrize('storage,expected', [
    ({}, '当前账号未获 R2 上传授权'),
    ({'assigned': True, 'available': False, 'revision': 'rev'}, '后台 R2 上传当前不可用'),
    ({'assigned': True, 'available': True}, 'R2 上传授权信息不完整'),
])
def test_storage_status_refresh_and_reference_preflight(online, monkeypatch, tmp_path, storage, expected):
    manager, state = online
    state['bundle']['modules']['faker'] = state['bundle']['modules']['faker'].replace(
        'supports = ("image", "video")', 'supports = ("image", "video")\n    ref_mode = "url"')
    post = manager.post
    def with_storage(action, body, token=''):
        result = post(action, body, token)
        if action == 'verify': result['storage_config'] = dict(storage)
        return result
    monkeypatch.setattr(manager, 'post', with_storage)
    monkeypatch.setattr(assets, 'readable', lambda path: True)
    manager.verify()
    raw = spec()
    # No reference images means no upload is needed.
    release.prepare(raw)
    ref = tmp_path / 'reference.png'; ref.write_bytes(b'reference')
    raw['refs'] = [str(ref)]
    boot = release.public_boot()
    opts = boot['providers'][0]['image']['model_options'][raw['model']]
    assert opts['ref_mode'] == 'url' and opts['upload_ready'] is False
    assert expected in opts['upload_warning'] and expected in boot['upload_warning']
    assert '完整发行包' not in json.dumps(boot, ensure_ascii=False)
    with pytest.raises(ValueError, match=expected): release.prepare(raw)
    with pytest.raises(ApiError, match=expected):
        uploader.to_url(str(ref), manager.profile['config']['upload'])

    # An account grant received on refresh immediately restores the same model.
    storage.update(assigned=True, available=True, revision='granted-rev')
    manager.verify(refresh_models=True)
    boot = release.public_boot()
    opts = boot['providers'][0]['image']['model_options'][raw['model']]
    assert opts['upload_ready'] is True and opts['upload_warning'] == ''
    prepared, cfg = release.prepare(raw)
    assert prepared['model'] == 'fast' and prepared['refs'] == raw['refs']
    assert cfg['upload']['revision'] == 'granted-rev'
    public = json.dumps(release.redact(boot))
    assert 'granted-rev' not in public and 'FAKE-KEY' not in public


def test_cy_z_image_text_submission_needs_no_storage_and_keeps_model(online, monkeypatch, tmp_path):
    import base64
    import io
    from pathlib import Path
    import requests
    from PIL import Image
    from core import batch, managed_usage
    from tests.test_managed import wait

    manager, state = online
    source = Path(__file__).resolve().parents[2] / 'script-to-video-studio/core/providers/cangyuan.py'
    state['bundle'] = dict(protocol=1, version='cy-z-image-test', modules={'cangyuan': source.read_text(encoding='utf-8')},
        providers=[dict(id='cangyuan', name='CY', module='cangyuan', **{'class': 'CangyuanProvider'})])
    state['grants'] = {'cangyuan': {'keys': [dict(api_key='FAKE-CY', key_id='cy-key', key_name='CY',
        assignment_id='cy-rev', base_url='https://upstream.invalid', models=['Z-Image-Turbo'])]}}
    manager.verify()
    raw = spec('Z-Image-Turbo')
    opts = release.public_boot()['providers'][0]['image']['model_options'][raw['model']]
    assert opts['max_refs'] == 0 and opts['upload_ready'] is False
    image = io.BytesIO(); Image.effect_noise((64, 64), 100).convert('RGB').save(image, format='JPEG')
    calls = []
    def send(adapter, request, **kwargs):
        calls.append(request)
        assert request.url.endswith('/v1/images/generations')
        assert request.headers['Authorization'] == 'Bearer FAKE-CY'
        body = json.loads(request.body)
        assert body['model'] == 'Z-Image-Turbo' and body['prompt'] == '测试'
        assert body['size'] == '1:1' and 'images' not in body
        response = requests.Response(); response.status_code = 200
        response._content = json.dumps({'data': [{'b64_json': base64.b64encode(image.getvalue()).decode()}]}).encode()
        response.request = request; response.url = request.url
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    run = batch.start(raw, {}); wait(run)
    assert run.counts()['完成'] == 1 and len(calls) == 1
    with Image.open(run.tasks[0].dest) as output:
        assert output.size == (64, 64) and output.format == 'PNG'
    events = managed_usage.pending('account-a')
    assert len(events) == 1 and events[0]['key_id'] == 'cy-key' and events[0]['model'] == 'Z-Image-Turbo'
    monkeypatch.setattr(assets, 'readable', lambda path: True)
    raw['refs'] = [str(tmp_path / 'reference.png')]
    with pytest.raises(ValueError, match='最多 0 张参考图'): batch.start(raw, {})
    assert len(calls) == 1
