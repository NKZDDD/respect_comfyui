import io
import threading

import pytest
from PIL import Image
from tests.test_model_statistics_ui import page, playwright  # noqa: F401
from tests.test_batch import sandbox  # noqa: F401
from tests.test_managed import online  # noqa: F401


def drop_image(page, selector, name='微信图片.png'):
    data = io.BytesIO()
    Image.new('RGB', (24, 24), 'green').save(data, format='PNG')
    transfer = page.evaluate_handle('''({bytes,name})=>{
      const transfer=new DataTransfer();
      transfer.items.add(new File([new Uint8Array(bytes)],name,{type:''}));
      return transfer;
    }''', dict(bytes=list(data.getvalue()), name=name))
    try:
        page.locator(selector).dispatch_event('drop', dict(dataTransfer=transfer))
    finally:
        transfer.dispose()


@pytest.mark.parametrize('kind', ['image', 'video'])
def test_file_drop_after_login_uses_current_references(page, kind):
    data = io.BytesIO()
    Image.new('RGB', (24, 24), 'green').save(data, format='PNG')
    uploads = []
    def upload(route):
        uploads.append(route.request.post_data_buffer)
        route.fulfill(json=dict(ok=True, path=f'D:/uploads/drop-{len(uploads)}.png', name='微信图片.png'))
    page.route('**/api/upload?*', upload)
    page.route('**/api/file?*', lambda r:r.fulfill(body=data.getvalue(), content_type='image/png'))
    # The permanent drop zone is bound before the login handler replaces SHARED.
    drop_image(page, '#sharedDrop')
    playwright.expect(page.locator('#sharedThumbs img')).to_have_count(1)
    auth = dict(ok=True, authenticated=False, user=dict(username='next-account'), usage={}, adapter={})
    page.route('**/api/auth/status', lambda r:r.fulfill(json=auth))
    page.locator('#managed-logout').click()
    playwright.expect(page.locator('#managed-login')).to_be_visible()
    def login(route):
        auth['authenticated'] = True
        route.fulfill(json=dict(ok=True))
    page.route('**/api/auth/login', login)
    page.locator('#managed-signin [name=username]').fill('next-account')
    page.locator('#managed-signin [name=password]').fill('test-only')
    page.locator('#managed-signin [type=submit]').click()
    playwright.expect(page.locator('#managed-login')).not_to_be_visible()
    playwright.expect(page.locator('#sharedThumbs img')).to_have_count(0)
    page.select_option('#kind', kind)
    drop_image(page, '#sharedDrop')
    playwright.expect(page.locator('#sharedThumbs img')).to_have_count(1, timeout=2000)
    page.wait_for_function('document.querySelector("#sharedThumbs img").naturalWidth>0')
    assert page.evaluate('buildSpec().refs') == ['D:/uploads/drop-2.png']
    drop_image(page, '#cards .cd', '单条.png')
    playwright.expect(page.locator('#cards .thumbs img')).to_have_count(1)
    assert page.evaluate('TASKS[0].refs[0].path') == 'D:/uploads/drop-3.png'
    page.locator('#managed-refresh').click()
    playwright.expect(page.locator('#sharedThumbs img')).to_have_count(1)
    assert page.evaluate('buildSpec().refs') == ['D:/uploads/drop-2.png']
    assert uploads == [data.getvalue()] * 3


@pytest.mark.parametrize('selector', ['#sharedDrop', '#cards .cd'])
def test_drop_without_file_explains_how_to_import(page, selector):
    page.route('**/api/upload?*', lambda r:pytest.fail('A link is not an image file'))
    transfer = page.evaluate_handle('''()=>{
      const transfer=new DataTransfer();
      transfer.setData('text/uri-list','file:///C:/WeChat/temporary.png');
      return transfer;
    }''')
    try:
        page.locator(selector).dispatch_event('drop', dict(dataTransfer=transfer))
    finally:
        transfer.dispose()
    playwright.expect(page.locator('#toast')).to_contain_text('没有收到可读取的图片文件')
    assert page.evaluate('buildSpec().refs') == []
    assert page.evaluate('TASKS[0].refs') == []


@pytest.mark.parametrize('kind', ['image', 'video'])
def test_uploaded_references_are_visible_and_removed_library_is_not_reported(page, kind):
    page.select_option('#kind', kind)
    data = io.BytesIO()
    Image.new('RGB', (24, 24), 'green').save(data, format='PNG')
    sequence = []
    def upload(route):
        sequence.append(1)
        route.fulfill(json=dict(ok=True, path=f'D:/uploads/{len(sequence)}.png', name='watch.png'))
    page.route('**/api/upload?*', upload)
    page.route('**/api/file?*', lambda r: r.fulfill(body=data.getvalue(), content_type='image/png'))
    file = dict(name='watch.png', mimeType='image/png', buffer=data.getvalue())
    page.locator('#sharedDrop').click()
    page.locator('#filePick').set_input_files(file)
    playwright.expect(page.locator('#sharedThumbs img')).to_be_visible()
    page.wait_for_function('document.querySelector("#sharedThumbs img").naturalWidth>0')
    page.locator('#cards textarea').fill('手表开箱展示。' * 60)
    page.locator('#cards button').filter(has_text='＋图').click()
    page.locator('#filePick').set_input_files(file)
    playwright.expect(page.locator('#cards .thumbs img')).to_be_visible()
    # Single-task references belong below the prompt, not squeezed beside it.
    prompt = page.locator('#cards textarea').bounding_box()
    thumb = page.locator('#cards .thumbs').bounding_box()
    assert thumb['y'] >= prompt['y'] + prompt['height']
    page.locator('#folderSection').evaluate('(e)=>e.open=true')
    page.locator('#btnAddLibrary').click()
    page.locator('#libraries input:not([webkitdirectory])').set_input_files([file, dict(file, name='watch2.png')])
    playwright.expect(page.locator('#libraries img')).to_have_count(2)
    playwright.expect(page.locator('#libraryMsg')).to_contain_text('共 2 张')
    page.locator('#managed-refresh').click()
    playwright.expect(page.locator('#libraries img')).to_have_count(2)
    playwright.expect(page.locator('#sharedThumbs img')).to_have_count(1)
    page.locator('#libraries button').filter(has_text='删除素材库').click()
    playwright.expect(page.locator('#libraries img')).to_have_count(0)
    assert page.locator('#libraryMsg').inner_text() == ''
    assert page.evaluate('buildSpec().ref_slots') == []
    assert len(page.evaluate('buildSpec().refs')) == 1


def test_preview_failure_is_visible_and_does_not_remove_reference(page):
    page.route('**/api/file?*', lambda r: r.fulfill(status=404))
    page.evaluate("SHARED=[{path:'D:/missing.png',name:'missing.png'}];render()")
    playwright.expect(page.locator('#sharedThumbs')).to_contain_text('预览失败')
    assert page.evaluate('buildSpec().refs') == ['D:/missing.png']


def test_retry_button_submits_only_the_existing_result_identity(page):
    data = dict(ok=True, id='run-1', status='已完成', seconds=100, message='下载失败', logs=[],
        counts={'总数':1,'完成':0,'失败':1,'未发':0,'跳过':0,'进行中':0,'待跑':0},
        tasks=[dict(idx=1,prompt='视频',status='失败',seconds=100,attempts=1,error='TLS 连接中断',can_retry_download=True)])
    page.route('**/api/run?*', lambda r:r.fulfill(json=data))
    calls=[]
    def retry(route):
        calls.append(route.request.post_data_json)
        data['tasks'][0].update(status='完成',error='',dest='D:/out.mp4',can_retry_download=False)
        data['counts'].update({'完成':1,'失败':0})
        route.fulfill(json=dict(ok=True))
    page.route('**/api/retry-download', retry)
    page.route('**/api/start', lambda r:pytest.fail('Retrieval must never start generation'))
    page.evaluate("document.querySelector('#progCard').classList.remove('hide');poll()")
    page.get_by_role('button',name='仅重新下载',exact=True).click()
    playwright.expect(page.locator('#taskBody')).to_contain_text('完成')
    assert calls == [dict(run_id='run-1', task_idx=1)]


def test_real_authenticated_folder_upload_and_preview(online, monkeypatch, tmp_path):
    from core import server, distribution, managed, assets
    from tools.build_managed import page as managed_page
    _, state = online
    monkeypatch.setattr(distribution, 'page', managed_page)
    folder=tmp_path/'watch-materials';folder.mkdir()
    for name in ('watch1.png','watch2.jpg'):
        Image.new('RGB',(40,40),'green').save(folder/name)
    httpd=server.serve(port=0)
    worker=threading.Thread(target=httpd.serve_forever,daemon=True);worker.start()
    url=f'http://127.0.0.1:{httpd.server_port}'
    try:
        with playwright.sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            context=browser.new_context(viewport=dict(width=1280,height=900))
            context.add_cookies([dict(name=managed.COOKIE,value=state['cookie'].split('=',1)[1],url=url)])
            tab=context.new_page()
            errors=[];tab.on('pageerror',lambda error:errors.append(str(error)))
            # All production/API networking uses the fake online fixture.
            tab.goto(url)
            tab.wait_for_selector('#managed-name:has-text("account-a")')
            tab.select_option('#kind','video')
            drop_image(tab, '#sharedDrop')
            playwright.expect(tab.locator('#sharedThumbs img')).to_have_count(1)
            tab.wait_for_function('document.querySelector("#sharedThumbs img").naturalWidth>0')
            stored = tab.evaluate('buildSpec().refs[0]')
            assert assets.readable(stored)
            with Image.open(stored) as image:
                assert image.size == (24, 24)
            tab.locator('#folderSection').evaluate('(e)=>e.open=true')
            tab.locator('#btnAddLibrary').click()
            tab.locator('#libraries input[webkitdirectory]').set_input_files(folder)
            playwright.expect(tab.locator('#libraries img')).to_have_count(2)
            tab.wait_for_function('[...document.querySelectorAll("#libraries img")].every(i=>i.naturalWidth>0)')
            tab.locator('#cards textarea').fill('手表展示视频')
            assert len(tab.evaluate('buildSpec().ref_slots[0]'))==2
            assert all(assets.readable(p) for p in tab.evaluate('buildSpec().ref_slots[0]'))
            tab.locator('#sharedDrop').scroll_into_view_if_needed()
            tab.screenshot(path=str(tmp_path/'real-folder-preview.png'))
            assert not errors
            browser.close()
    finally:
        httpd.shutdown();worker.join(3);httpd.server_close()
