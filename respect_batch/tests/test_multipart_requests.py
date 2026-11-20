"""Inspect actual HTTP bodies, not the adapter's pre-serialization arguments."""
import base64
from email.parser import BytesParser
from email.policy import default
import io
import json
from pathlib import Path

import pytest
import requests
from PIL import Image

from core import assets, batch, managed_usage, release
from core.apiutil import HttpSession
from tests.test_batch import sandbox
from tests.test_managed import online, spec, wait


def form_parts(request):
    message = BytesParser(policy=default).parsebytes(
        ('Content-Type: ' + request.headers['Content-Type'] + '\r\n\r\n').encode() + request.body)
    fields, files = {}, []
    for part in message.iter_parts():
        name = part.get_param('name', header='content-disposition')
        if part.get_filename() is None:
            fields[name] = part.get_payload(decode=True).decode('utf-8')
        else:
            files.append((name, part.get_filename(), part.get_payload(decode=True)))
    return fields, files


@pytest.mark.parametrize('shape', ['mixed_list', 'proper_list', 'dict'])
def test_multipart_text_is_a_field_and_repeated_images_remain_files(monkeypatch, shape):
    fields = [('model', 'gpt-image-2'), ('prompt', '一张产品图'), ('n', '1')]
    images = [('image[]', ('first.png', b'first-bytes', 'image/png')),
              ('image[]', ('second.jpg', b'second-bytes', 'image/jpeg'))]
    parts = [(k, (None, v)) for k, v in fields] + images if shape == 'proper_list' else fields + images
    if shape == 'dict': parts = dict(fields + images[:1])
    calls = []
    def send(adapter, request, **settings):
        calls.append(request)
        got_fields, got_files = form_parts(request)
        assert got_fields == dict(fields)
        assert got_files == [(k, v[0], v[1]) for k, v in (images[:1] if shape == 'dict' else images)]
        assert request.headers['Authorization'] == 'Bearer FAKE'
        assert settings['verify'] is True
        response = requests.Response(); response.status_code = 200; response._content = b'{}'
        response.request = request; response.url = request.url
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    HttpSession('FAKE', 'https://upstream.invalid').request('POST', '/v1/images/edits', files=parts, retries=1)
    assert len(calls) == 1


@pytest.mark.parametrize('with_reference', [True, False])
@pytest.mark.parametrize('legacy_bundle', [True, False])
def test_downloaded_ny_adapter_sends_model_and_saves_result(online, monkeypatch, tmp_path, with_reference, legacy_bundle):
    manager, state = online
    source = Path(__file__).resolve().parents[2] / 'script-to-video-studio/core/providers/valeclouds.py'
    code = source.read_text(encoding='utf-8')
    if legacy_bundle:
        code = code.replace('            form = [(name, (None, value)) for name, value in form]\n', '')
    state['bundle'] = dict(protocol=1, version='ny-wire-test', modules={'valeclouds': code},
        providers=[dict(id='valeclouds', name='NY', module='valeclouds', **{'class': 'ValeCloudsProvider'})])
    state['grants'] = {'valeclouds': {'keys': [dict(api_key='FAKE-NY', key_id='ny-key', key_name='NY',
        assignment_id='ny-rev', base_url='https://upstream.invalid', models=['gpt-image-2.5-sunburst'])]}}
    manager.verify()
    image = io.BytesIO(); Image.effect_noise((64, 64), 100).convert('RGB').save(image, format='PNG')
    payload = image.getvalue()
    ref = tmp_path / 'ref.png'; ref.write_bytes(payload)
    monkeypatch.setattr(assets, 'readable', lambda path: path == str(ref))
    calls = []
    def send(adapter, request, **settings):
        calls.append(request)
        assert request.method == 'POST'
        assert request.headers['Authorization'] == 'Bearer FAKE-NY'
        if with_reference:
            assert request.url.endswith('/v1/images/edits')
            fields, files = form_parts(request)
            assert len(files) == 1 and files[0][2] == payload
        else:
            assert request.url.endswith('/v1/images/generations')
            fields = json.loads(request.body)
        response = requests.Response(); response.request = request; response.url = request.url
        # Behave like a server which reads form values separately from file parts.
        if not fields.get('model'):
            response.status_code = 400
            data = {'error': {'message': 'Model name not specified, model name cannot be empty'}}
        else:
            assert fields['model'] == 'gpt-image-2.5-sunburst' and fields['prompt'] == '测试产品图'
            response.status_code = 200
            data = {'data': [{'b64_json': base64.b64encode(payload).decode()}]}
        response._content = json.dumps(data).encode()
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    raw = spec('gpt-image-2.5-sunburst'); raw['tasks'][0]['prompt'] = '测试产品图'
    raw['refs'] = [str(ref)] if with_reference else []
    run = batch.start(raw, {}); wait(run)
    assert run.counts()['完成'] == 1
    assert len(calls) == 1
    with Image.open(run.tasks[0].dest) as output:
        assert output.size == (64, 64)
    events = managed_usage.pending('account-a')
    assert len(events) == 1 and events[0]['model'] == 'gpt-image-2.5-sunburst'
    assert events[0]['key_id'] == 'ny-key' and events[0]['status'] == 'completed'
