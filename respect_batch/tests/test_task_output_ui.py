from tests.test_model_statistics_ui import page  # noqa: F401


def test_copy_previous_prompt_and_assign_ranges(page):
    cards = page.locator('#cards textarea')
    cards.first.fill('外套')
    page.evaluate("TASKS[0].refs.push({path:'first.png',name:'first.png'})")
    page.locator('#btnAdd').click()
    assert cards.nth(1).input_value() == '外套'
    assert page.evaluate('buildSpec().tasks.map(t=>t.refs)') == [['first.png'], []]
    cards.nth(1).fill('手表')
    page.locator('#btnAdd').click()
    assert cards.nth(2).input_value() == '手表'
    assert cards.first.input_value() == '外套'

    page.locator('#outputGroups summary').click()
    page.locator('#folderTo').fill('2')
    page.locator('#folderName').fill('春装')
    page.locator('#assignFolder').click()
    assert page.locator('#cards .output-folder').all_text_contents() == ['成品子文件夹 · 春装'] * 2
    page.locator('#folderFrom').fill('3')
    page.locator('#folderTo').fill('4')
    page.locator('#assignFolder').click()
    assert page.evaluate('buildSpec().tasks.map(t=>t.output_folder)') == ['春装', '春装', None]
    page.locator('#folderTo').fill('3')
    page.locator('#folderName').fill('')
    page.locator('#assignFolder').click()
    cards.nth(1).fill('')
    assert page.evaluate('buildSpec().tasks.map(t=>t.output_folder)') == ['春装', '任务3-3']
    page.locator('#clearFolder').click()
    assert page.evaluate('buildSpec().tasks.map(t=>t.output_folder)') == ['春装', None]

    page.locator('#btnAdd').click()
    cards.last.evaluate(r"""field => {
        const data = new DataTransfer();
        data.setData('text', '镜头一\n镜头二');
        field.dispatchEvent(new ClipboardEvent('paste', {clipboardData:data, bubbles:true, cancelable:true}));
    }""")
    assert page.evaluate('buildSpec().tasks.map(t=>t.prompt)') == ['外套', '手表', '镜头一', '镜头二']


def test_choose_and_paste_independent_destinations(page):
    other_drive = r'E:\客户交付\第一组'
    share = r'\\fileserver\共享\第二组'
    starts = []

    def pick(route):
        starts.append(route.request.post_data_json['start'])
        result = dict(ok=True, path=other_drive) if len(starts) == 1 else dict(ok=False, msg='取消了')
        route.fulfill(json=result)

    page.route('**/api/pick_dir', pick)
    page.locator('#cards textarea').fill('外套')
    page.locator('#btnAdd').click()
    page.locator('#btnAdd').click()
    page.locator('#outputGroups summary').click()
    page.locator('#folderTo').fill('2')
    page.locator('#pickRangeDir').click()
    target = page.locator('#folderName')
    page.wait_for_function("document.querySelector('#folderName').value.length > 0")
    assert target.input_value() == other_drive
    page.locator('#pickRangeDir').click()
    page.wait_for_function("!document.querySelector('#pickRangeDir').disabled")
    assert target.input_value() == other_drive and starts == ['D:/test', other_drive]
    page.locator('#assignFolder').click()
    assert page.locator('#cards .output-folder').all_text_contents() == ['成品目录 · ' + other_drive] * 2
    page.locator('#folderFrom').fill('2')
    target.fill(share)
    page.locator('#assignFolder').click()
    assert page.evaluate('buildSpec().tasks.map(t=>t.output_folder)') == [other_drive, share, None]
    assert page.locator('#outDir').input_value() == 'D:/test'
    page.locator('#clearFolder').click()
    assert page.evaluate('buildSpec().tasks.map(t=>t.output_folder)') == [other_drive, None, None]
