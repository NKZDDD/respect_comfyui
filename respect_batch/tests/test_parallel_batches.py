import os
import threading
from pathlib import Path

from core import accounts, batch, distribution, managed, release, server
from tests.test_batch import sandbox  # noqa: F401
from tests.test_managed import online, spec, wait  # noqa: F401
from tests.test_model_statistics_ui import playwright
from tools.build_managed import page as managed_page


def test_two_models_through_managed_page(online, monkeypatch, tmp_path):
    _, state = online
    monkeypatch.setattr(server, '_RUNS', {})
    monkeypatch.setattr(distribution, 'page', managed_page)
    monkeypatch.setattr(server.updates.manager, 'check', lambda: dict(phase='current', required=False))
    monkeypatch.setattr(server.assets, 'pick_dir', lambda start: dict(ok=True, path=str(tmp_path / 'out')))
    entered = {model: threading.Event() for model in ('fast', 'slow')}
    finish = {model: threading.Event() for model in entered}
    seen = []

    def generate(provider, task, run, log, refs):
        seen.append((task.model, provider.session.api_key))
        entered[task.model].set()
        assert finish[task.model].wait(30)
        Path(task.dest).write_bytes(task.model.encode() * 200)
        return {}

    monkeypatch.setattr(batch, '_dispatch', generate)
    httpd = server.serve(port=0)
    listener = threading.Thread(target=httpd.serve_forever, daemon=True)
    listener.start()
    address = f'http://127.0.0.1:{httpd.server_port}'
    ids = {m['model']: m['id'] for m in release.catalog() if m['kind'] == 'image'}
    try:
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch()
            page = browser.new_page()
            page.context.add_cookies([dict(name=managed.COOKIE, value=state['cookie'].split('=', 1)[1], url=address)])
            page.goto(address)
            page.locator('#btnPickDir').click()
            playwright.expect(page.locator('#outDir')).to_have_value(str(tmp_path / 'out'))
            selected = tmp_path / '单独交付' / '成品'
            monkeypatch.setattr(server.assets, 'pick_dir', lambda start: dict(ok=True, path=str(selected)))
            page.get_by_text('高级（一般不用动）', exact=True).click()
            for model in ('fast', 'slow'):
                if model == 'slow':
                    page.locator('#btnNewBatch').click()
                    assert page.locator('#cards textarea').input_value() == ''
                page.select_option('#model', ids[model])
                page.locator('#cards textarea').fill('同一提示词')
                if not page.locator('#outputGroups').evaluate('(el)=>el.open'):
                    page.locator('#outputGroups summary').click()
                page.locator('#pickRangeDir').click()
                playwright.expect(page.locator('#folderName')).to_have_value(str(selected))
                page.locator('#assignFolder').click()
                page.locator('#repeat').fill('2')
                page.locator('#conc').fill('1')
                page.locator('#btnRun').click()
                assert entered[model].wait(3)
            first, second = server._RUNS.values()
            replay = page.evaluate("id=>api('/api/start',{spec:buildSpec(),submission_id:id})",
                                   second.submission_id)
            assert replay['id'] == second.id and len(server._RUNS) == 2
            assert seen == [('fast', 'FAKE-KEY-ONE'), ('slow', 'FAKE-KEY-TWO')]
            assert first.tasks[0].dest != second.tasks[0].dest
            assert all(Path(t.dest).parent == selected for r in (first, second) for t in r.tasks)
            picker = page.locator('#batchPicker')
            playwright.expect(picker.locator('option')).to_have_count(2)
            picker.select_option(first.id)
            playwright.expect(page.locator('#btnStop')).to_be_visible()
            page.locator('#btnStop').click()
            assert first._cancel.wait(3) and not second.cancelled()
            finish['fast'].set()
            wait(first)
            assert first.counts()['未发'] == 1
            page.reload()
            playwright.expect(picker.locator('option')).to_have_count(2)
            assert '仍有任务' in page.evaluate("async()=> (await api('/api/updates/install',{})).msg")
            finish['slow'].set()
            wait(second)
            assert second.counts()['完成'] == 2
            assert Path(first.tasks[0].dest).read_bytes() == b'fast' * 200
            assert Path(second.tasks[0].dest).read_bytes() == b'slow' * 200
            assert Path(first.manifest_path).is_file() and Path(second.manifest_path).is_file()
            opened = []
            if os.name == 'nt':
                monkeypatch.setattr(os, 'startfile', opened.append)
            else:
                monkeypatch.setattr(server.subprocess, 'Popen', lambda args: opened.append(args[-1]))
            picker.select_option(second.id)
            playwright.expect(page.locator('#runOutputDirs option')).to_have_text(str(selected))
            with page.expect_response('**/api/open') as response:
                page.locator('#btnOpenOut').click()
            assert response.value.json()['ok'] and opened == [str(selected)]
            denied = page.evaluate("body=>api('/api/open',body)", dict(run_id=second.id, path=str(tmp_path)))
            assert not denied['ok'] and opened == [str(selected)]
            rerun = spec('slow')
            rerun.update(tasks=[dict(prompt='同一提示词', output_folder=str(selected))],
                         out_dir=str(tmp_path / 'out'), repeat=2)
            response = page.evaluate("s=>api('/api/start',{spec:s})", rerun)
            again = server._RUNS[response['id']]
            wait(again)
            assert again.counts()['跳过'] == 2
            assert [t.dest for t in again.tasks] == [t.dest for t in second.tasks]
            browser.close()
    finally:
        for event in finish.values():
            event.set()
        for run in server._RUNS.values():
            wait(run)
        httpd.shutdown()
        listener.join(3)
        httpd.server_close()


def test_serial_account_shared_across_overlapping_grants():
    a = 'deviceId=account1;token=a'
    b = 'deviceId=account2;token=b'
    first = accounts.configured_pool('serial-test', a)
    second = accounts.configured_pool('serial-test', a + '\n' + b)
    third = accounts.configured_pool('serial-test', a)
    with first.slot() as item:
        assert item.api_key == a
        with second.slot() as other:
            assert other.api_key == b
        assert third.busy() == 1
    assert third.busy() == 0
