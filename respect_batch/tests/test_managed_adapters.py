import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_managed import online, spec, wait
from tests.test_batch import sandbox, FAKE_PROVIDER
from core import adapter_format, batch, distribution, managed, managed_adapters, managed_usage, providers, release


def bundle(limit=3, version='test-v1'):
    source = FAKE_PROVIDER.replace('"default_model": "fast",', f'"default_model": "fast", "max_refs": {limit!r},')
    return dict(protocol=1, version=version, modules={'faker': source},
                providers=[dict(id='faker', name='图片服务', module='faker', **{'class': 'FakerProvider'})])


def metadata(b):
    return dict(enabled=True, protocol=1, version=b['version'], sha256=adapter_format.digest(b),
                providers=[p['id'] for p in b['providers']], missing=[])


def test_refresh_changes_refs_and_actual_implementation(online, monkeypatch, tmp_path):
    m, state = online
    state['bundle'] = bundle(0)
    m.verify(refresh_models=True)
    raw = spec()
    ref = tmp_path / 'ref.png'
    from PIL import Image
    Image.effect_noise((64, 64), 100).save(ref)
    from core import assets
    monkeypatch.setattr(assets, 'readable', lambda path: True)
    raw['refs'] = [str(ref)]
    with pytest.raises(ValueError, match='最多 0'):
        release.prepare(raw)
    old = providers.REGISTRY['faker']
    state['bundle'] = bundle(3, 'test-v2')
    state['bundle']['modules']['faker'] = state['bundle']['modules']['faker'].replace('b"FAKE" * 200', 'b"REMOTE" * 200')
    m.verify()  # Automatic verification notices a changed digest even with unchanged Key grants.
    assert providers.REGISTRY['faker'] is not old
    prepared, cfg = release.prepare(raw)
    assert release.catalog()[0]['options']['max_refs'] == 3
    assert cfg['_adapter_sha256'] == adapter_format.digest(state['bundle'])
    run = batch.start(raw, {})
    wait(run)
    assert run.counts()['完成'] == 1
    assert Path(run.tasks[0].dest).read_bytes() == b'REMOTE' * 200
    events = managed_usage.pending('account-a')
    assert len(events) == 1 and events[0]['status'] == 'completed'
    assert events[0]['key_id'] == 'key-1'


def test_unlimited_is_not_overridden_by_legacy_zero(online):
    m, state = online
    state['bundle'] = bundle(0, 'unlimited')
    state['bundle']['modules']['faker'] = state['bundle']['modules']['faker'].replace('"max_refs": 0,', '"max_refs": 0, "refs_unlimited": True,')
    m.verify()
    assert all(r['options']['max_refs'] is None for r in release.catalog() if r['kind'] == 'image')


def test_corruption_missing_package_and_missing_dependency_fail_closed(online):
    m, state = online
    post = m.post
    for failure in ('missing', 'checksum', 'dependency'):
        state['bundle'] = bundle(3, failure)
        def broken(action, body, token=''):
            result = post(action, body, token)
            if action == 'verify' and failure == 'missing':
                result['adapter_config'] = {'enabled': False}
            if action == 'adapters' and failure == 'checksum':
                result['bundle'] = bundle(9, 'tampered')
            return result
        m.post = broken
        if failure == 'dependency':
            state['bundle']['modules']['faker'] += '\nimport absent_batch_test_dependency\n'
        with pytest.raises(managed.LoginRequired):
            m.verify(refresh_models=True)
        assert m.profile is None and m.until == 0
    m.post = post


def test_cache_is_only_reused_after_matching_online_metadata(online):
    m, state = online
    before = len([c for c in state['calls'] if c[0] == 'adapters'])
    m.verify(refresh_models=True)
    assert len([c for c in state['calls'] if c[0] == 'adapters']) == before
    cache = next((Path(managed.paths.data_dir()) / 'adapter-cache').glob('*.json'))
    cache.write_text('{}')
    m.verify(refresh_models=True)
    assert len([c for c in state['calls'] if c[0] == 'adapters']) == before + 1
    m.logout(state['cookie'])
    assert not providers.REGISTRY
    assert not m.snapshot()['models']


def test_running_batches_pin_original_adapter_on_refresh(online):
    m, state = online
    state['bundle'] = bundle(3, 'pinned-1')
    m.verify()
    raw = spec('slow'); raw['repeat'] = 2; raw['concurrency'] = 1
    run = batch.start(raw, {})
    state['bundle'] = bundle(8, 'pinned-2')
    state['bundle']['modules']['faker'] = state['bundle']['modules']['faker'].replace('b"FAKE" * 200', 'b"NEW" * 200')
    m.verify()
    wait(run)
    assert all(Path(t.dest).read_bytes() == b'FAKE' * 200 for t in run.tasks)
    run2 = batch.start(spec('fast'), {})
    wait(run2)
    assert Path(run2.tasks[0].dest).read_bytes() == b'NEW' * 200


def test_managed_stage_contains_no_builtin_provider_code(tmp_path):
    from tools.build_managed import stage
    target = stage(tmp_path / 'staged')
    assert {p.name for p in (target / 'core/providers').glob('*.py')} == {'base.py', '__init__.py'}


def test_all_current_studio_adapters_load_on_batch_runtime(tmp_path):
    studio = Path(__file__).resolve().parents[2] / 'script-to-video-studio'
    if not studio.is_dir():
        pytest.skip('Sibling Studio checkout is needed for cross-client compatibility verification')
    output = tmp_path / 'bundle.json'
    subprocess.run([sys.executable, str(studio / 'tools/build_provider_bundle.py'), str(output),
                    '--version', 'batch-runtime-test'], cwd=studio, check=True, capture_output=True)
    actual = json.loads(output.read_bytes())
    classes = managed_adapters.load(actual)
    assert set(classes) == {r['id'] for r in actual['providers']}
    assert len(classes) >= 28
    assert {'cangyuan', 'cangyuan_video', 'chaomo_banana', 'hongniao'} <= set(classes)
    for pid, cls in classes.items():
        cap = cls().capabilities()
        assert cap['id'] == pid and set(cap['supports']) <= {'image', 'video'}


def test_server_adapter_image_request_refs_and_jpeg_result(online, monkeypatch, tmp_path):
    """Execute an actual server adapter absent from the old Batch client, without paid calls."""
    import base64
    import io
    import requests
    from PIL import Image
    from core import assets, refs
    from tests.test_managed import fake_response
    studio = Path(__file__).resolve().parents[2] / 'script-to-video-studio'
    source = (studio / 'core/providers/cangyuan.py').read_text(encoding='utf-8')
    m, state = online
    state['bundle'] = dict(protocol=1, version='real-cangyuan', modules={'cangyuan': source},
        providers=[dict(id='cangyuan', name='图片通道', module='cangyuan', **{'class': 'CangyuanProvider'})])
    state['grants'] = {'cangyuan': {'keys': [dict(api_key='FAKE-CANGYUAN', key_id='cy-key', key_name='图片通道',
        assignment_id='cy-rev', base_url='https://upstream.invalid', models=['gpt-image-2.5-flare-1k'])]}}
    m.verify()
    assert release.catalog()[0]['options']['max_refs'] == 16
    image = io.BytesIO(); Image.effect_noise((64, 64), 100).convert('RGB').save(image, format='JPEG')
    calls = []
    def http(method, url, **kw):
        calls.append((method, url, kw))
        return fake_response({'data': [{'b64_json': base64.b64encode(image.getvalue()).decode()}]})
    monkeypatch.setattr(requests, 'request', http)
    monkeypatch.setattr(assets, 'readable', lambda path: True)
    monkeypatch.setattr(refs, 'make_resolver', lambda *a, **kw: lambda path, log: 'https://reference.invalid/' + Path(path).name)
    monkeypatch.setattr('core.uploader.configured', lambda *a: True)
    raw = spec('gpt-image-2.5-flare-1k')
    raw['refs'] = [str(tmp_path / f'{i}.png') for i in range(15)]
    run = batch.start(raw, {}); wait(run)
    assert run.counts()['完成'] == 1
    assert len(calls) == 1 and calls[0][1].endswith('/v1/images/edits')
    assert len(calls[0][2]['json']['images']) == 15
    assert calls[0][2]['headers']['Authorization'] == 'Bearer FAKE-CANGYUAN'
    with Image.open(run.tasks[0].dest) as output:
        assert output.format == 'PNG' and output.size == (64, 64)
    records = managed_usage.pending('account-a')
    assert len(records) == 1 and records[0]['key_id'] == 'cy-key' and records[0]['status'] == 'completed'
