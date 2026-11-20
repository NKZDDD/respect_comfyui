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


def test_login_diagnostics_offline_page_replays_once_after_local_recovery(page):
    base = 'http://127.0.0.1:9999/api/auth/'
    status = dict(ok=True, authenticated=True, user=dict(username='tester'), usage={},
                  adapter={}, diagnostic_session='a'*64)
    delivered = []
    reachable = True
    def auth_status(route):
        if reachable:
            route.fulfill(json=status)
        else:
            route.abort()
    def page_event(route):
        if reachable:
            delivered.append(route.request.post_data_json)
            route.fulfill(json={'ok': True})
        else:
            route.abort()
    page.route(base+'status', auth_status)
    page.route(base+'page', page_event)
    page.evaluate('managedStatus()')
    reachable = False
    page.evaluate('managedStatus()')
    playwright.expect(page.locator('#managed-login')).to_be_visible()
    assert page.evaluate("JSON.parse(sessionStorage.batchPendingPages).map(e=>e.state)") == ['local_status_unreachable']
    reachable = True
    page.evaluate('managedStatus()')
    page.wait_for_function("JSON.parse(sessionStorage.batchPendingPages).length === 0")
    assert [e['state'] for e in delivered] == ['local_status_unreachable','ready']
    assert all(e['session']==status['diagnostic_session'] for e in delivered)
    playwright.expect(page.locator('#managed-login')).not_to_be_visible()


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


def test_failed_image_refresh_keeps_mode_and_blocks_empty_submission_until_recovery(page):
    original = page.evaluate('CAPS[0]')
    failed = {**original, 'image': dict(models=[], model_labels={}, model_options={},
        empty_message='暂无可用图片模型。模型目录未完整加载，请刷新后台配置与模型。')}
    boot = dict(ok=True, distribution=True, providers=[failed],
                config=dict(defaults={}, limits={}, providers={}), default_out_dir='D:/test')
    page.route('http://127.0.0.1:9999/api/boot', lambda r: r.fulfill(json=boot))
    submissions = []
    page.on('request', lambda r: submissions.append(r) if r.url.endswith('/api/start') else None)
    page.locator('#cards textarea').fill('一条尚未提交的图片任务')
    page.locator('#managed-refresh').click()
    playwright.expect(page.locator('#modelNotice')).to_contain_text('模型目录未完整加载')
    assert page.locator('#kind').input_value() == 'image'
    assert page.locator('#kind option').count() == 2
    assert page.locator('#model').input_value() == ''
    assert page.locator('#cards textarea').input_value() == '一条尚未提交的图片任务'
    playwright.expect(page.locator('#btnRun')).to_be_disabled()
    page.evaluate('startRun()')
    assert submissions == []
    assert page.locator('.bms-selected article').count() == 0

    page.select_option('#kind', 'video')
    playwright.expect(page.locator('#btnRun')).to_be_enabled()
    page.select_option('#kind', 'image')
    boot['providers'] = [original]
    page.locator('#managed-refresh').click()
    playwright.expect(page.locator('#model')).to_have_value('i1')
    playwright.expect(page.locator('#btnRun')).to_be_enabled()
    assert page.locator('#modelNotice').inner_text() == ''
    assert submissions == []


def test_network_preferences_reachable_before_login_and_do_not_resubmit(page, tmp_path):
    state = dict(mode='system', proxy_url='')
    calls = []
    def network_route(route):
        if route.request.method == 'POST':
            state.update(route.request.post_data_json)
        route.fulfill(json=dict(ok=True, network=state))
    page.route('http://127.0.0.1:9999/api/network', network_route)
    page.on('request', lambda r: calls.append(r.url) if r.url.endswith(('/api/start', '/api/auth/refresh')) else None)
    page.locator('#cards textarea').fill('保留这条未提交任务')
    page.locator('#batch-network-button').click()
    dialog = page.locator('#batch-network-dialog')
    playwright.expect(dialog.locator('[name=mode]')).to_have_value('system')
    dialog.locator('[name=mode]').select_option('custom')
    dialog.locator('[name=proxy_url]').fill('http://127.0.0.1:7890')
    dialog.locator('[type=submit]').click()
    playwright.expect(dialog.locator('[data-message]')).to_contain_text('已保存')
    assert state == dict(mode='custom', proxy_url='http://127.0.0.1:7890')
    page.screenshot(path=str(tmp_path / 'network-desktop.png'))
    dialog.locator('[data-close]').click()
    assert page.locator('#cards textarea').input_value() == '保留这条未提交任务'
    assert calls == []
    # A broken proxy can be changed without logging in. Test small screens too.
    page.route('http://127.0.0.1:9999/api/auth/status', lambda r:r.fulfill(json=dict(ok=True, authenticated=False)))
    page.evaluate('managedStatus()')
    page.set_viewport_size(dict(width=390, height=844))
    playwright.expect(page.locator('#managed-login')).to_be_visible()
    page.locator('#batch-network-button').click()
    playwright.expect(dialog.locator('[name=proxy_url]')).to_have_value('http://127.0.0.1:7890')
    box = dialog.bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= 390
    page.screenshot(path=str(tmp_path / 'network-mobile.png'))
    dialog.locator('[name=mode]').select_option('direct')
    dialog.locator('[type=submit]').click()
    playwright.expect(dialog.locator('[data-message]')).to_contain_text('已保存')
    assert state == dict(mode='direct', proxy_url='')
    assert calls == []


def test_managed_r2_warning_refresh_and_reference_modes(page):
    cap = page.evaluate('CAPS[0]')
    options = cap['image']['model_options']['i1']
    warning = '当前账号未获 R2 上传授权，请管理员在后台为账号开启“R2 授权”，然后刷新后台配置与模型。'
    options.update(ref_mode='url', upload_ready=False, upload_warning=warning)
    boot = dict(ok=True, distribution=True, providers=[cap],
                config=dict(defaults={}, limits={}, providers={}), default_out_dir='D:/test')
    page.route('http://127.0.0.1:9999/api/boot', lambda r:r.fulfill(json=boot))
    submissions = []
    page.on('request', lambda r: submissions.append(r) if r.url.endswith('/api/start') else None)
    page.locator('#cards textarea').fill('保留这条带图任务')
    page.locator('#managed-refresh').click()
    playwright.expect(page.locator('#btnRun')).to_be_enabled()
    page.evaluate("SHARED.push('D:/reference.png');render()")
    playwright.expect(page.locator('#refWarn')).to_contain_text(warning)
    playwright.expect(page.locator('#btnRun')).to_be_disabled()
    page.evaluate('startRun()')
    assert submissions == []
    # Direct image-byte adapters must not require the account to have R2.
    options['ref_mode'] = 'data_uri'
    page.locator('#managed-refresh').click()
    playwright.expect(page.locator('#btnRun')).to_be_enabled()
    assert page.locator('#refWarn').inner_text() == ''
    options.update(ref_mode='url', upload_ready=True, upload_warning='')
    page.locator('#managed-refresh').click()
    playwright.expect(page.locator('#btnRun')).to_be_enabled()
    assert page.locator('#cards textarea').input_value() == '保留这条带图任务'
    assert page.evaluate('SHARED') == ['D:/reference.png']
    assert submissions == []
    # Z-Image-Turbo cannot take references even if the account has R2 access.
    options['max_refs'] = 0
    page.locator('#managed-refresh').click()
    playwright.expect(page.locator('#refWarn')).to_contain_text('只支持文字生成，不接受参考图')
    playwright.expect(page.locator('#btnRun')).to_be_disabled()
    page.evaluate('SHARED=[];render()')
    playwright.expect(page.locator('#btnRun')).to_be_enabled()
    assert submissions == []
