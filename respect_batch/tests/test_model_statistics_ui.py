from pathlib import Path

import pytest

from tools.build_managed import page as managed_page

playwright = pytest.importorskip('playwright.sync_api')
ROOT = Path(__file__).resolve().parents[1]
ROWS = [dict(id='m1', label='GT · exact-fast-formoss', kind='video'),
        dict(id='m2', label='AK · wan-3.0-video', kind='video'),
        dict(id='m3', label='AK · unknown-model', kind='video'),
        dict(id='i1', label='CY · image-model', kind='image')]
STATS = {'ok': True, 'models': [
    dict(id='m1', model_id='exact-fast-formoss', stats=[dict(rate=95.16, seconds=336.92, samples=99, window='近 24 小时', basis='服务商统计')], state='ready'),
    dict(id='m2', model_id='wan-3.0-video', stats=[dict(rate=0, samples=3)], state='ready'),
    dict(id='m3', model_id='unknown-model', stats=[], state='unsupported'),
    dict(id='i1', model_id='image-model', stats=[dict(rate=90)], state='ready', stale=True),
    dict(id='not-authorized', model_id='not-authorized', stats=[dict(rate=100)], state='ready')]}


@pytest.fixture
def page():
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport=dict(width=1280, height=900))
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        caps = dict(id='preset', name='Respect', supports=['image', 'video'])
        for kind in ('image', 'video'):
            rows = [r for r in ROWS if r['kind'] == kind]
            caps[kind] = dict(models=[r['id'] for r in rows], model_labels={r['id']:r['label'] for r in rows},
                              model_options={r['id']:dict(ratios=['16:9'], durations=[5], sizes=['1024x1024'], max_refs=10) for r in rows})
        boot = dict(ok=True, distribution=True, providers=[caps], config=dict(defaults={}, limits={}, providers={}), default_out_dir='D:/test')
        def route(request):
            url = request.request.url
            if url.endswith('/api/boot'): value = boot
            elif '/api/auth/status' in url: value = dict(ok=True, authenticated=True, user=dict(username='tester'), usage={}, adapter={})
            elif '/api/model-statistics' in url:
                assert request.request.headers.get('x-respect-session') == 'test-session'
                value = STATS
            elif '/api/updates/' in url: value = dict(ok=True, current='test', phase='idle')
            else: value = dict(ok=True, idle=True)
            request.fulfill(json=value)
        page.route('http://127.0.0.1:9999/api/**', route)
        page.route('http://127.0.0.1:9999/', lambda r:r.fulfill(content_type='text/html',body=managed_page().replace(b'__RELEASE_SESSION__',b'test-session')))
        page.goto('http://127.0.0.1:9999/')
        playwright.expect(page.locator('.bms-selected')).to_contain_text('90.00%')
        yield page
        assert not errors
        browser.close()


def test_full_managed_page_exact_route_choice_unknown_zero_and_stale(page):
    assert page.locator('.bms-selected .stale').count() == 1
    page.select_option('#kind', 'video')
    playwright.expect(page.locator('.bms-selected')).to_contain_text('95.16%')
    assert page.locator('.bms-selected .lit').count() == 38
    assert '336.92 秒' in page.locator('.bms-selected').inner_text()
    page.locator('.bms-picker summary').click()
    assert page.locator('.bms-list article').count() == 3
    assert 'not-authorized' not in page.locator('.bms').inner_text()
    assert page.locator('.bms-list [data-route=m2] .zero').count() == 1
    assert '0.00%' not in page.locator('.bms-list [data-route=m3]').inner_text()
    page.locator('.bms-list [data-route=m2] button').click()
    assert page.locator('#model').input_value() == 'm2'
    assert page.evaluate('block().durations') == [5]
    page.evaluate('BatchModelStats.sync();BatchModelStats.sync()')
    assert page.locator('#model option[value=m2]').inner_text().count('0.00%') == 1


def test_search_and_mobile_layout(page):
    page.select_option('#kind', 'video')
    page.set_viewport_size(dict(width=390,height=844))
    page.locator('.bms-picker summary').click()
    page.locator('.bms-search').fill('wan-3.0')
    assert page.locator('.bms-list article').count() == 1
    box = page.locator('.bms-list article').bounding_box()
    assert box['x'] >= 0 and box['x']+box['width'] <= 390


def test_reset_discards_late_response_and_untrusted_markup(page):
    page.evaluate('''()=>{
      window.fetch=()=>new Promise(resolve=>window.lateStats=resolve);
      BatchModelStats.mount();BatchModelStats.reset();
      lateStats({ok:true,status:200,json:async()=>({ok:true,models:[]})});
    }''')
    assert page.locator('.bms').count() == 0
    page.evaluate('''()=>{
      window.fetch=async()=>({ok:true,status:200,json:async()=>({ok:true,models:[
        {id:'i1',model_id:'<img src=x onerror=alert(1)>',state:'ready',stats:[{rate:90,basis:'<script>bad</script>'}]}]})});
      BatchModelStats.mount();
    }''')
    playwright.expect(page.locator('.bms-selected')).to_contain_text('<img src=x')
    assert page.locator('.bms img, .bms script').count() == 0
