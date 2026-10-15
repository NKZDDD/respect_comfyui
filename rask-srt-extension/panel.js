(function () {
  'use strict';
  const existing = document.getElementById('rask-srt-assistant');
  if (existing) { existing.hidden=false; existing.dispatchEvent(new Event('rask-open')); return; }
  const C=globalThis.RaskSrtCore, E=globalThis.RaskSrtEngine;
  const host=document.createElement('div');
  host.id='rask-srt-assistant';
  host.style.cssText='all:initial;position:fixed;right:18px;top:18px;z-index:2147483646;';
  const shadow=host.attachShadow({mode:'open'});
  shadow.innerHTML=`
    <style>
      :host{color-scheme:light} *{box-sizing:border-box} [hidden]{display:none!important}
      .panel{width:440px;max-width:calc(100vw - 36px);font:13px/1.55 system-ui,"Microsoft YaHei",sans-serif;color:#1b283c;background:#fff;border:1px solid #d9e2ed;border-radius:16px;box-shadow:0 14px 50px #16325333;overflow:hidden}
      header{padding:15px 17px;display:flex;align-items:center;gap:10px;border-bottom:1px solid #e9eef5;background:#f8faff}
      .mark{background:#255ee5;color:white;font-weight:750;padding:6px 9px;border-radius:9px;font-size:14px} h1{font-size:15px;line-height:1.4;margin:0} small{color:#738198;font-size:11px}
      .headtext{flex:1}.icon{background:transparent;color:#607086;border:0;padding:5px 9px;font-size:17px}
      main{max-height:calc(100vh - 115px);overflow:auto;padding:16px}.intro{color:#58687e;margin:0 0 12px}
      .upload{border:1px dashed #adc1ee;border-radius:10px;background:#f7faff;padding:12px;display:block;margin-bottom:12px}
      input{display:block;max-width:100%;margin-top:6px;font-size:12px}input::file-selector-button{background:#e9efff;color:#224fc7;border:0;border-radius:5px;padding:6px 9px;margin-right:8px;cursor:pointer}
      .buttons{display:flex;gap:7px;flex-wrap:wrap}button{font:inherit;border:1px solid #d7dfec;background:white;border-radius:7px;padding:8px 11px;cursor:pointer;color:#304567}button.primary{background:#255ee5;border-color:#255ee5;color:white;font-weight:650}button:disabled{opacity:.43;cursor:not-allowed}button:not(:disabled):hover{filter:brightness(.95)}
      .status{margin:13px 0 7px;padding:10px;border-radius:8px;background:#eef4ff;color:#304d83;white-space:pre-wrap;overflow-wrap:anywhere}.status.error{background:#fff0eb;color:#a34120}
      progress{display:block;width:100%;height:6px;accent-color:#255ee5;margin:0 0 13px}
      .stats{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}.stat{padding:4px 8px;border-radius:6px;background:#f1f4f8;font-size:12px}.stat.green{background:#eaf7f0;color:#147b4c}.stat.orange{background:#fff2e3;color:#9b5c16}
      .preview{border:1px solid #e2e8f1;border-radius:8px;max-height:255px;overflow:auto}.item{padding:9px 11px;border-bottom:1px solid #e9eef5}.item:last-child{border-bottom:0}.line{display:flex;justify-content:space-between;gap:8px}.tag{font-size:11px;color:#255ee5}.detail{color:#63748b;font-size:12px;overflow-wrap:anywhere}.arabic{color:#53657a;margin-top:3px;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.muted{color:#6a7b91;font-size:12px;margin:11px 0 0}.foot{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:12px}.foot button{padding:5px 9px;font-size:12px}
      details{margin-top:10px}summary{cursor:pointer;color:#4f6384}.log{max-height:150px;overflow:auto;font-size:12px}.log div{padding:5px 0;border-bottom:1px solid #edf0f6;overflow-wrap:anywhere}
    </style>
    <section class="panel" aria-label="Rask SRT 说话人助手">
      <header><span class="mark">SRT</span><div class="headtext"><h1>说话人助手</h1><small>Rask · 仅按 SRT 起止时间匹配</small></div><button class="icon" id="minimize" title="收起 / 展开">−</button><button class="icon" id="close" title="隐藏面板">×</button></header>
      <main>
        <p class="intro">导入含 <b>[SPEAKER_00]</b> 标记的 SRT，按起止时间选择说话人。原文或译文均可，正文不参与匹配。</p>
        <label class="upload">选择 SRT 文件<input id="file" type="file" accept=".srt,text/plain,application/x-subrip"></label>
        <div class="buttons"><button id="scan" disabled>重新扫描</button><button id="apply" class="primary" disabled>应用说话人</button><button id="stop" disabled>停止</button></div>
        <div id="status" class="status" role="status">请在 Rask 字幕列表已载入后导入 SRT。</div>
        <progress id="progress" max="100" value="0"></progress>
        <div id="stats" class="stats"></div><div id="preview" class="preview" hidden></div>
        <details id="logs" hidden><summary>本次页面点选记录</summary><div id="log" class="log"></div></details>
        <p class="muted">运行时请保持此页面在前台，不要手动滚动、编辑或切换项目。未找到或时间有歧义的片段会跳过。</p>
        <div class="foot"><small>只选择说话人 · 不点击生成 / Apply changes</small><button id="export" disabled>导出记录</button></div>
      </main>
    </section>`;
  document.documentElement.append(host);
  const $=id=>shadow.getElementById(id);
  let cues=[], filename='', plan=null, latestPlan=null, busy=false, ctx=null, records=[], errorText='';
  const labels={ready:'待修改',same:'已一致',missing:'未找到',blocked:'跳过',checking:'正在检查',pending:'已点选，待核对',selected:'已点选，等待复核',already:'执行时已一致',verified:'页面复核通过',unverified:'需人工核对',skipped:'未修改'};
  function status(text, error=false){$('status').textContent=text;$('status').classList.toggle('error',error);}
  function controls(){
    $('file').disabled=busy;$('scan').disabled=busy||!cues.length;
    const count=plan?.items.filter(i=>i.status==='ready').length||0;
    $('apply').disabled=busy||!count;$('apply').textContent=count?`应用说话人（${count} 条）`:'应用说话人';
    $('stop').disabled=!busy;$('export').disabled=busy||(!latestPlan&&!records.length&&!errorText);
  }
  function el(tag,text,className){const e=document.createElement(tag);e.textContent=text;if(className)e.className=className;return e;}
  const time=ms=>{const total=Math.floor(ms/1000);return `${String(Math.floor(total/60)).padStart(2,'0')}:${String(total%60).padStart(2,'0')}.${String(ms%1000).padStart(3,'0')}`;};
  function renderPlan(){
    const items=latestPlan?.items||[];
    $('stats').replaceChildren();
    for(const [type,title,css] of [['ready','待修改',''],['same','已一致','green'],['missing','未找到','orange'],['blocked','跳过','orange']]){
      $('stats').append(el('span',`${title} ${items.filter(i=>i.status===type).length}`,`stat ${css}`));
    }
    $('preview').replaceChildren();$('preview').hidden=!items.length;
    for(const item of items){
      const card=el('div','','item'),line=el('div','','line');
      line.append(el('b',`#${item.cue.number} · ${time(item.cue.start)}`),el('span',labels[item.status],'tag'));
      card.append(line,el('div',item.reason||`${item.segment.speaker} → ${item.cue.speaker}`,'detail'));
      const text=el('div',item.cue.text,'arabic');text.dir='auto';text.title=item.cue.text;card.append(text);$('preview').append(card);
    }
  }
  function renderRecords(){
    $('logs').hidden=!records.length;$('log').replaceChildren();
    for(const r of records)$('log').append(el('div',`#${r.number} ${r.before} → ${r.target}：${labels[r.status]||r.status}${r.reason?'；'+r.reason:''}`));
  }
  function context(){
    return {page:E.pageKey(),cancelled:false,onProgress:p=>{
      $('progress').value=p.scroll;
      status(`${ctx.phase} 已读取 ${p.seen} 个页面片段 · 滚动 ${p.scroll}%`);
    },onPhase:phase=>{ctx.phase=phase;status(phase);}};
  }
  async function startScan(){
    if(busy||!cues.length)return;
    busy=true;plan=null;latestPlan=null;records=[];errorText='';renderRecords();renderPlan();controls();
    ctx=context();ctx.phase='正在扫描';status('正在从顶部滚动扫描…');
    try{
      latestPlan=await E.scan(cues,ctx);plan=latestPlan;renderPlan();
      const good=plan.items.filter(i=>i.status==='ready'||i.status==='same').length;
      const skipped=cues.length-good;
      status(`扫描完成：SRT ${cues.length} 条，页面 ${plan.segments.length} 条，匹配 ${good} 条。${skipped?`\n${skipped} 条未匹配或有歧义，不会修改。`:'\n请检查预览，再点击“应用说话人”。'}`,skipped>0);
      $('progress').value=100;
    }catch(error){errorText=error.message;status(errorText,true);}
    finally{busy=false;controls();}
  }
  $('file').addEventListener('change',async()=>{
    const file=$('file').files[0];if(!file)return;
    plan=null;latestPlan=null;cues=[];records=[];errorText='';renderPlan();renderRecords();controls();
    if(file.size>10*1024*1024){status('SRT 超过 10 MB，请检查文件。',true);return;}
    try{
      const parsed=C.parseSrt(new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer()));
      if(parsed.errors.length)throw new Error(`SRT 格式有 ${parsed.errors.length} 处问题（块 ${parsed.errors.slice(0,8).map(e=>e.block).join('、')}），请修复后导入；每条须有时间、[SPEAKER_XX] 和正文。`);
      filename=file.name;cues=parsed.cues;await startScan();
    }catch(error){errorText=error.message;status(errorText,true);controls();}
  });
  $('scan').addEventListener('click',startScan);
  $('apply').addEventListener('click',async()=>{
    if(busy||!plan)return;
    busy=true;records=[];errorText='';ctx=context();ctx.phase='正在选择说话人';controls();
    try{
      await E.apply(plan,ctx,r=>{if(!records.includes(r))records.push(r);renderRecords();});
      const verified=records.filter(r=>r.status==='verified').length;
      status(`本轮结束：${verified}/${records.length} 条页面复核通过。\n请检查 Rask 的保存提示；刷新后重新扫描，可检查服务端是否保留了修改。${verified<records.length?'\n未通过的片段请查看点选记录。':''}`,verified<records.length);
      $('progress').value=100;
    }catch(error){errorText=error.message;status(errorText,true);}
    finally{
      const confirmed=records.filter(r=>r.status==='verified').length;
      const clicked=records.filter(r=>r.clickedAt||r.status==='verified').length;
      const total=plan.items.filter(i=>i.status==='ready').length;
      plan=null;busy=false;renderRecords();controls();$('logs').open=true;
      $('preview').hidden=true;
      $('stats').replaceChildren(el('span',`页面复核通过 ${confirmed}`,'stat green'),
        el('span',`需核对 ${clicked-confirmed}`,'stat orange'),el('span',`未操作 ${total-clicked}`,'stat'));
    }
  });
  $('stop').addEventListener('click',()=>{if(ctx)ctx.cancelled=true;status('正在停止…已点选的片段将保留在记录中。');});
  $('minimize').addEventListener('click',()=>{const main=shadow.querySelector('main');main.hidden=!main.hidden;$('minimize').textContent=main.hidden?'+':'−';});
  $('close').addEventListener('click',()=>{host.hidden=true;});
  host.addEventListener('rask-open',()=>{shadow.querySelector('main').hidden=false;$('minimize').textContent='−';});
  $('export').addEventListener('click',()=>{
    const data={extension:'Rask SRT 说话人助手',version:'1.0.1',exportedAt:new Date().toISOString(),file:filename,
      page:latestPlan?.page||ctx?.page,scan:latestPlan,changes:records,error:errorText,
      note:'verified 仅表示重新滚动后的页面值匹配，不代表服务端保存确认。插件不点击 Apply changes、Translate 或生成按钮。'};
    const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}));
    const a=document.createElement('a');a.href=url;a.download=`rask-speakers-${new Date().toISOString().replace(/[:.]/g,'-')}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
  });
})();
