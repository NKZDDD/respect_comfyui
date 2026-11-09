"""Bound model parameters can refresh; authorization and Key routing remain fixed."""
import pytest

from core import managed_models, model_catalog as M, providers
from core.providers.base import Provider

FAST = 'seedance-2.0-fast-通用'
WAN = 'wan3.0-vedio-deal'


class FixtureYQ(Provider):
    id = 'yueqi'
    default_base_url = 'https://yueqi.icu'
    supports = ('video',)
    refresh_bound_capabilities = True
    ref_mode = 'url'
    def capabilities(self):
        return dict(id=self.id, supports=['video'], video=dict(models=[FAST, WAN], max_refs=None,
            model_options={FAST: dict(max_refs=1), WAN: dict(max_refs=0)}))


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    monkeypatch.setitem(providers.REGISTRY, 'yueqi', FixtureYQ)


def row(model, maximum):
    return dict(id=model, type='video', capability_schema={'max_reference_images': maximum})


def config():
    return {'yueqi': {'keys': [dict(api_key='test-a', key_id='a', key_name='YQ A', models=[FAST]),
                              dict(api_key='test-b', key_id='b', key_name='YQ B', models=[WAN])]}}


def test_batch_updates_each_bound_model_and_keeps_key_authorization(monkeypatch):
    calls = []
    def fetch(pid, pc):
        calls.append(pc['api_key'])
        return {'ok': True, 'rows': [row(FAST, 3), row(WAN, 10), row('unassigned', 50)]}
    monkeypatch.setattr(M, 'fetch', fetch)
    profile = managed_models.build('owner', config(), {})
    models = profile['models']
    assert not profile['issues'] and calls == ['test-a', 'test-b']
    assert [m['model'] for m in models] == [FAST, WAN]
    assert [m['options']['max_refs'] for m in models] == [3, 10]
    assert [m['route']['_usage']['key_id'] for m in models] == ['a', 'b']
    assert [m['route']['api_key'] for m in models] == ['test-a', 'test-b']


@pytest.mark.parametrize('live', [{'ok': False, 'msg': 'SECRET'}, {'ok': True, 'rows': []}, RuntimeError('SECRET')])
def test_batch_metadata_failure_warns_but_preserves_bound_models(monkeypatch, live):
    def fetch(*a):
        if isinstance(live, Exception):
            raise live
        return live
    monkeypatch.setattr(M, 'fetch', fetch)
    profile = managed_models.build('owner', config(), {})
    assert [m['model'] for m in profile['models']] == [FAST, WAN]
    assert len(profile['issues']) == 2 and 'SECRET' not in repr(profile['issues'])


@pytest.mark.parametrize('maximum', [0, 3, None])
def test_batch_explicit_null_clears_stale_zero_and_preserves_real_zero(monkeypatch, maximum):
    monkeypatch.setattr(M, 'fetch', lambda *a: {'ok': True, 'rows': [row(FAST, maximum), row(WAN, maximum)]})
    profile = managed_models.build('owner', config(), {})
    assert all(m['options']['max_refs'] == maximum for m in profile['models'])


def test_bindings_without_opt_in_do_not_add_network_calls(monkeypatch):
    monkeypatch.setattr(FixtureYQ, 'refresh_bound_capabilities', False)
    monkeypatch.setattr(M, 'fetch', lambda *a: pytest.fail('unexpected network'))
    profile = managed_models.build('owner', config(), {})
    assert [m['options']['max_refs'] for m in profile['models']] == [1, 0]
