"""Offline browser regression tests. Never contacts or edits a real Rask project."""
import json
import os
import re
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / '_test'
ARTIFACTS.mkdir(exist_ok=True)
if not os.environ.get('RASK_SAMPLE_SRT') or not os.environ.get('RASK_SAMPLE_HTML'):
    raise SystemExit('Set RASK_SAMPLE_SRT and RASK_SAMPLE_HTML to the private regression fixtures (see 使用说明.md).')
SAMPLE = Path(os.environ['RASK_SAMPLE_SRT'])
SAMPLE_HTML = Path(os.environ['RASK_SAMPLE_HTML'])

FIXTURE = r'''<!doctype html><html><head><meta charset="utf-8"><style>
body{font:14px system-ui;background:#f2f5fb;margin:20px;color:#243450}h2{font-size:20px}
#list{height:420px;width:650px;overflow:auto;border:1px solid #bac8dd;background:white;position:relative}
[data-item-index]{height:150px;box-sizing:border-box;border-bottom:1px solid #ddd;padding:10px}
[role=combobox]{cursor:pointer;background:#edf1fc;padding:4px;width:150px}
[role=listbox]{position:fixed;left:220px;top:100px;z-index:100;background:white;border:1px solid #aaa;padding:10px}
[role=option]{padding:7px;cursor:pointer} [contenteditable]{display:inline-block;margin:4px}
[data-testid=project-page-transcription-segment]{display:block!important}
</style></head><body><h2>Rask 虚拟字幕列表 · 离线测试</h2><p>同一时刻只渲染少量片段，滚动后销毁并重建。</p>
<div id="list" data-virtuoso-scroller="true"><div data-testid="virtuoso-item-list"></div></div>
<button onclick="window.billable++">Apply changes</button><button onclick="window.billable++">Translate</button>
<script>(()=>{
window.billable=0; window.clicks=[]; window.cfg=CFG; window.cues=CUES;
window.speakers=cues.map(c=>'SPEAKER_'+String((Number(c.speaker.split('_')[1])+1)%5).padStart(2,'0'));
const list=document.getElementById('list'),items=list.firstElementChild;
function timestamp(ms){const s=Math.floor(ms/1000);return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')+','+String(ms%1000).padStart(3,'0')}
function label(i){return i===2?'自定义角色名':'Speaker '+(i+1)}
function render(){
 const start=Math.max(0,Math.floor(list.scrollTop/150)-1),end=Math.min(cues.length,start+6);
 items.style.paddingTop=start*150+'px';items.style.paddingBottom=(cues.length-end)*150+'px';items.replaceChildren();
 for(let i=start;i<end;i++){
  if(cfg.omit===i)continue;
  const row=document.createElement('div');row.dataset.itemIndex=i;
  const select=document.createElement('div'),combo=document.createElement('div'),input=document.createElement('input');
  combo.setAttribute('role','combobox');combo.tabIndex=0;combo.setAttribute('aria-controls','choices-'+i);combo.textContent=label(Number(speakers[i].split('_')[1]));
  input.value=speakers[i];input.hidden=true;select.append(combo,input);row.append(select);
  for(const ms of [cues[i].start,cues[i].end]){const time=document.createElement('div');time.contentEditable='true';time.textContent=timestamp(ms);row.append(time)}
  const text=document.createElement('div');text.contentEditable='true';text.dataset.testid='project-page-transcription-segment';text.textContent=cues[i].text;row.append(text);
  combo.addEventListener('mousedown',e=>{
   e.preventDefault(); const menu=document.createElement('ul');menu.id='choices-'+i;menu.setAttribute('role','listbox');combo.setAttribute('aria-expanded','true');
   menu.addEventListener('keydown',e=>{if(e.key==='Escape'){menu.remove();combo.setAttribute('aria-expanded','false')}});
   for(let j=0;j<5;j++){
    const value='SPEAKER_'+String(j).padStart(2,'0');if(cfg.missingOption===value)continue;
    const option=document.createElement('li');option.setAttribute('role','option');option.dataset.value=value;option.textContent=label(j);
    option.onclick=()=>{const old=speakers[i];window.clicks.push({index:i,value});speakers[i]=value;menu.remove();render();
      if(cfg.rollback)setTimeout(()=>{speakers[i]=old;render()},800);
    };menu.append(option);
   }
   document.body.append(menu);
  });items.append(row);
 }
}
let timer;list.addEventListener('scroll',()=>{clearTimeout(timer);timer=setTimeout(render,cfg.delay||40)});render();
})();
</script></body></html>'''

def scripts(page, panel=False):
    for name in ['core.js', 'engine.js'] + (['panel.js'] if panel else []):
        page.add_script_tag(path=str(ROOT / name))

def fixture(page, cues, **cfg):
    page.set_content(FIXTURE.replace('CFG', json.dumps(cfg)).replace('CUES', json.dumps(cues)))
    scripts(page)

def scan(page, cues):
    return page.evaluate('c => RaskSrtEngine.scan(c,{page:RaskSrtEngine.pageKey()})', cues)

results=[]
def passed(name):
    results.append(name)
    print('PASS: '+name, flush=True)

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(viewport={'width':1280,'height':900})
    page.route('**/*', lambda route: route.abort())
    scripts(page)
    parsed=page.evaluate('s => RaskSrtCore.parseSrt(s)',SAMPLE.read_text(encoding='utf-8-sig'))
    assert not parsed['errors'] and len(parsed['cues'])==31
    cues=parsed['cues']

    # Inspect the actual supplied DOM, without executing any captured scripts.
    html=SAMPLE_HTML.read_text(encoding='utf-8')
    soup=BeautifulSoup(html,'html.parser')
    listing=soup.select_one('[data-virtuoso-scroller="true"]')
    page.set_content(str(listing))
    scripts(page)
    actual=page.evaluate('() => [...document.querySelectorAll("[data-item-index]")].map(RaskSrtEngine.readRow)')
    assert len(actual)==5 and actual[0]['speaker']=='SPEAKER_01'
    plan=page.evaluate('x => RaskSrtEngine.buildPlan(x.rows,x.cues)',{'rows':actual,'cues':cues})
    assert plan[0]['status']=='ready' and plan[0]['cue']['speaker']=='SPEAKER_02'
    assert len([r for r in plan if r['status']=='missing'])==26
    duplicate=page.evaluate('x=>RaskSrtEngine.buildPlan([x.rows[0],{...x.rows[0],index:99,text:"translated"}],[x.cues[0]])',{'rows':actual,'cues':cues})
    assert duplicate[0]['status']=='blocked'
    passed('supplied HTML: five mounted rows, first speaker mismatch, 26 missing reported')

    fixture(page,cues)
    page.add_script_tag(path=str(ROOT/'panel.js'))
    translated_srt=re.sub(r'(\[SPEAKER_\d+\]:)[^\n]*',r'\1 Entirely different translated text.',SAMPLE.read_text(encoding='utf-8-sig'))
    page.locator('#rask-srt-assistant').locator('input[type=file]').set_input_files({
        'name':'translated-speakers.srt','mimeType':'text/plain','buffer':translated_srt.encode('utf-8')})
    page.wait_for_function("document.getElementById('rask-srt-assistant').shadowRoot.getElementById('status').textContent.includes('扫描完成')",timeout=120000)
    assert page.locator('#rask-srt-assistant').get_by_text('待修改 31',exact=True).count()==1
    assert page.evaluate('window.clicks.length')==0
    page.screenshot(path=str(ARTIFACTS/'preview.png'))
    page.locator('#rask-srt-assistant').get_by_role('button',name='应用说话人（31 条）').click()
    page.wait_for_function("document.getElementById('rask-srt-assistant').shadowRoot.getElementById('status').textContent.includes('本轮结束')",timeout=240000)
    status=page.locator('#rask-srt-assistant').locator('#status').inner_text()
    assert '31/31' in status,status
    assert page.locator('#rask-srt-assistant').get_by_text('页面复核通过 31',exact=True).count()==1
    assert not page.locator('#rask-srt-assistant').locator('#preview').is_visible()
    assert page.evaluate('window.speakers')==[c['speaker'] for c in cues]
    assert page.evaluate('window.clicks.length')==31
    assert page.evaluate('window.billable')==0
    assert page.evaluate('window.cues')==cues
    page.screenshot(path=str(ARTIFACTS/'completed.png'))
    with page.expect_download() as download:
        page.locator('#rask-srt-assistant').get_by_role('button',name='导出记录').click()
    download.value.save_as(ARTIFACTS/'changes.json')
    exported=json.loads((ARTIFACTS/'changes.json').read_text(encoding='utf-8'))
    assert len(exported['changes'])==31 and all(r['status']=='verified' for r in exported['changes'])
    assert exported['version']=='1.0.1'
    passed('panel: 31 translated cues match Arabic page by time only; verify all, preserve text, export log, no generation clicks')
    if os.environ.get('RASK_UI_ONLY'):
        (ARTIFACTS/'ui-results.json').write_text(json.dumps({'passed':results},indent=2),encoding='utf-8')
        browser.close()
        raise SystemExit(0)

    fixture(page,cues[:9],delay=1200)
    slow=scan(page,cues[:9])
    assert len(slow['segments'])==9 and all(i['status']=='ready' for i in slow['items'])
    passed('delayed virtual rendering: 1.2 second delay still scans every row')

    fixture(page,cues[:1])
    single=scan(page,cues[:1])
    single_result=page.evaluate('p=>RaskSrtEngine.apply(p,{page:RaskSrtEngine.pageKey()})',single)
    assert single_result[0]['status']=='verified'
    passed('single short row: works without a scrollable viewport')

    fixture(page,cues[:3],missingOption='SPEAKER_02')
    plan=scan(page,cues[:3])
    report=page.evaluate('p=>RaskSrtEngine.apply(p,{page:RaskSrtEngine.pageKey()})',plan)
    assert report[0]['status']=='skipped' and 'SPEAKER_02' in report[0]['reason']
    assert report[1]['status']=='verified' and report[2]['status']=='verified'
    assert page.evaluate('window.clicks.length')==2
    passed('missing dropdown value: skip exactly that cue, never guess by visible label')

    fixture(page,cues[:3])
    plan=scan(page,cues[:3])
    stopped=page.evaluate('''async p=>{
      const ctx={page:RaskSrtEngine.pageKey()};let error='';const log=[];
      try{await RaskSrtEngine.apply(p,ctx,r=>{if(!log.includes(r))log.push(r);if(r.status==='selected')ctx.cancelled=true})}catch(e){error=e.message}
      return {error,log,clicks:window.clicks};
    }''',plan)
    assert stopped['error'] and len(stopped['clicks'])==1 and len(stopped['log'])==1
    passed('stop after first selection: no second click, first action retained in log')

    fixture(page,cues[:2],rollback=True)
    plan=scan(page,cues[:2])
    rollback=page.evaluate('p=>RaskSrtEngine.apply(p,{page:RaskSrtEngine.pageKey()})',plan)
    assert all(r['status']=='unverified' for r in rollback),rollback
    passed('optimistic UI rollback is not reported as verified')

    fixture(page,cues[:8],omit=2)
    incomplete=page.evaluate('''async c=>{try{await RaskSrtEngine.scan(c,{page:RaskSrtEngine.pageKey()});return ''}catch(e){return e.message}}''',cues[:8])
    assert incomplete
    assert page.evaluate('window.clicks.length')==0
    passed('missing virtual row: incomplete scan blocked rather than silently successful')

    mismatch=page.evaluate('''async()=>{try{await RaskSrtEngine.scan([],{page:'https://another-project/'});return ''}catch(e){return e.message}}''')
    assert mismatch
    passed('project navigation guard stops execution')
    browser.close()

(ARTIFACTS/'browser-results.json').write_text(json.dumps({'version':json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))['version'],'passed':results},ensure_ascii=False,indent=2),encoding='utf-8')
print(f'ALL {len(results)} BROWSER CHECKS PASSED',flush=True)
