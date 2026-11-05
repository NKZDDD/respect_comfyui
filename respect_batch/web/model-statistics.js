// Managed Batch only. Opaque route IDs remain the values submitted for production.
window.BatchModelStats=(()=>{
  let root=null, details=null, search=null, list=null, selected=null, note=null;
  let data=new Map(), labels=new Map(), controller=null, epoch=0, timer=null, limit=60;
  const node=(tag,cls,text)=>{const n=document.createElement(tag);n.className=cls||'';if(text!==undefined)n.textContent=text;return n;};
  const valid=n=>typeof n==='number'&&Number.isFinite(n)&&n>=0;
  const rate=r=>valid(r?.rate)&&r.rate<=100?r.rate:null;
  function reset(){
    epoch++;controller?.abort();controller=null;clearTimeout(timer);
    root?.remove();root=null;data.clear();labels.clear();
  }
  function metric(row,stat){
    const value=rate(stat), tone=row.stale?'stale':value===null?'unknown':value===0?'zero':'known';
    const box=node('div','bms-metric '+tone), line=node('div','bms-line');
    line.append(node('span','bms-light'),node('span','', '成功率'),node('strong','',value===null?'暂无数据':value.toFixed(2)+'%'));
    const meter=node('div','bms-meter');meter.setAttribute('aria-hidden','true');
    const filled=value===null?0:Math.round(value*40/100);
    for(let i=0;i<40;i++)meter.append(node('i',i<filled?'lit':''));
    box.append(line,meter,node('div','bms-duration','平均耗时 '+(valid(stat?.seconds)&&stat.seconds>0?stat.seconds.toFixed(2)+' 秒':'—')));
    if(stat?.variant)box.append(node('div','bms-meta','分组：'+stat.variant));
    const meta=[stat?.window,valid(stat?.samples)?'样本 '+stat.samples+' 条':'',stat?.basis].filter(Boolean).join(' · ');
    if(meta)box.append(node('div','bms-meta',meta));
    const stamp=row.source_at||row.fetched_at;
    const state=row.stale?'历史数据，暂未刷新':row.state==='loading'?'正在读取公开统计':row.state==='error'?'统计暂不可用':row.state==='unsupported'?'暂无匹配的公开统计':!stat?'此模型暂无公开数据':'';
    if(stamp||state)box.append(node('div','bms-meta',[state,stamp?'更新于 '+new Date(stamp*1000).toLocaleString():''].filter(Boolean).join(' · ')));
    return box;
  }
  function card(id,choose){
    const row=data.get(id)||{state:'loading',stats:[]}, box=node('article','bms-card');
    box.dataset.route=id;
    box.append(node('b','bms-name',labels.get(id)||id));
    if(row.model_id)box.append(node('div','bms-model-id',row.model_id));
    (row.stats.length?row.stats:[null]).forEach(stat=>box.append(metric(row,stat)));
    if(choose){
      const current=$('#model').value===id, button=node('button','mini',current?'当前模型':'选择此模型');
      button.type='button';button.disabled=current;
      button.onclick=()=>{
        const select=$('#model');
        if(![...select.options].some(o=>o.value===id))return;
        select.value=id;select.dispatchEvent(new Event('change',{bubbles:true}));
        details.open=false;select.focus();details.open=false;
      };
      box.append(button);
    }
    return box;
  }
  function visible(){return [...$('#model').options].filter(o=>o.value);}
  function drawList(){
    if(!details?.open)return;
    const query=search.value.trim().toLowerCase();
    const options=visible().filter(o=>(labels.get(o.value)+' '+(data.get(o.value)?.model_id||'')).toLowerCase().includes(query));
    list.replaceChildren(...options.slice(0,limit).map(o=>card(o.value,true)));
    note.textContent=`当前${$('#kind').value==='video'?'视频':'图片'}可选模型 ${visible().length} 个，匹配 ${options.length} 个。`;
    if(!options.length)list.append(node('p','bms-meta','没有匹配的可用模型'));
    if(options.length>limit){const more=node('button','mini','显示更多模型');more.onclick=()=>{limit+=60;drawList();};list.append(more);}
  }
  function sync(){
    if(!root)return;
    for(const option of visible()){
      if(!labels.has(option.value))labels.set(option.value,option.textContent);
      const row=data.get(option.value), stats=row?.stats||[], value=stats.length===1?rate(stats[0]):null;
      const suffix=row?.stale?'历史数据':value!==null?value.toFixed(2)+'%':stats.length>1?'分组统计':'暂无数据';
      option.textContent=labels.get(option.value)+' · '+suffix;
    }
    selected.replaceChildren();
    if($('#model').value)selected.append(card($('#model').value,false));
    drawList();
  }
  async function refresh(){
    if(!root||controller)return;
    const current=epoch, request=new AbortController();controller=request;
    const timeout=setTimeout(()=>request.abort(),8000);
    try{
      const response=await fetch('/api/model-statistics',{headers:sessionHeaders(),signal:request.signal});
      if(current!==epoch)return;
      if(response.status===401||response.status===403){reset();return;}
      if(!response.ok)throw new Error('statistics');
      const body=await response.json();if(current!==epoch)return;
      if(!body.ok||!Array.isArray(body.models))throw new Error('statistics');
      data=new Map(body.models.map(r=>[r.id,r]));sync();
    }catch(e){
      if(current===epoch){
        for(const option of visible()){
          const previous=data.get(option.value);
          data.set(option.value,previous?{...previous,stale:true,state:'error'}:{stats:[],state:'error'});
        }
        sync();
      }
    }finally{
      clearTimeout(timeout);
      if(current===epoch){controller=null;timer=setTimeout(()=>document.hidden?(timer=setTimeout(refresh,15000)):refresh(),15000);}
    }
  }
  function mount(){
    // New boot means a refreshed authorization catalogue, possibly a new account.
    reset();root=node('section','bms');root.id='batch-model-statistics';
    selected=node('div','bms-selected');details=node('details','bms-picker');
    const summary=node('summary','','查看模型成功率 / 按卡片选模型');
    search=node('input','bms-search');search.type='search';search.placeholder='搜索 Key 名称或完整模型名';search.setAttribute('aria-label',search.placeholder);
    search.oninput=()=>{limit=60;drawList();};note=node('p','bms-meta');list=node('div','bms-list');
    details.append(summary,search,note,list);details.ontoggle=drawList;
    root.append(node('p','bms-caption','服务商公布的模型统计 · 按当前 Key 可用模型显示。不同服务统计口径见卡片说明。'),selected,details);
    $('#model').closest('.step').append(root);sync();refresh();
  }
  return {mount,sync,reset};
})();
