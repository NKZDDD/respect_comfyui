// Updates remain accessible before login, including when the old version is blocked.
(() => {
 const dialog=document.createElement('dialog');dialog.id='batch-update-dialog';
 dialog.innerHTML=`<div class="update-heading"><h2>对外批量版 · 软件更新</h2><button data-close>关闭</button></div>
 <p data-version></p><p data-message role="status"></p><progress max="100" value="0" hidden></progress>
 <p data-notes></p><div class="update-actions"><button data-check>检查更新</button><button data-download hidden>下载更新</button><button data-install hidden>重启完成更新</button></div>`;
 document.body.append(dialog);
 const button=document.createElement('button');button.id='batch-update-button';button.textContent='软件更新';
 document.body.append(button);
 const style=document.createElement('style');style.textContent=`#batch-update-button{position:fixed;right:20px;bottom:16px;z-index:30;box-shadow:0 3px 16px #0002}#batch-update-dialog{border:1px solid #e4e8f0;border-radius:20px;padding:26px;width:min(520px,85vw);color:#182536}#batch-update-dialog::backdrop{background:#17243766}.update-heading,.update-actions{display:flex;align-items:center;gap:12px;justify-content:space-between}#batch-update-dialog progress{width:100%;height:16px}#batch-update-dialog [data-notes]{white-space:pre-wrap;color:#64748b}`;document.head.append(style);
 let polling=null, installing=false;
 const el=s=>dialog.querySelector(s);
 const render=s=>{
   el('[data-version]').textContent='当前版本：'+s.current+(s.release?'　推荐版本：'+s.release.version:'');
   el('[data-message]').textContent=s.message;
   el('[data-notes]').textContent=s.release?.notes||'';
   el('[data-download]').hidden=!s.release||!['available','error'].includes(s.phase);
   el('[data-install]').hidden=s.phase!=='ready';
   el('[data-check]').disabled=['checking','downloading','installing'].includes(s.phase);
   const progress=el('progress');progress.hidden=s.phase!=='downloading';progress.value=s.release?.bytes?Math.floor(100*s.received/s.release.bytes):0;
   if(s.required&&!dialog.open)dialog.showModal();
   if(s.phase==='ready')button.textContent='更新已就绪';
   installing=s.phase==='installing';
   if(!['checking','downloading','installing'].includes(s.phase)&&polling){clearInterval(polling);polling=null;}
 };
 async function status(){try{const s=await api('/api/updates/status');if(s.ok)render(s);}catch{if(installing)el('[data-message]').textContent='程序已退出，安装完成后将自动重新打开。';}}
 async function action(name){
   try{const s=await api('/api/updates/'+name,{});if(!s.ok){el('[data-message]').textContent=s.msg;return;}render(s);
     if(!polling)polling=setInterval(status,1000);
   }catch{el('[data-message]').textContent='无法连接批量程序，请重新打开应用';}
 }
 button.onclick=()=>{dialog.showModal();status();};el('[data-close]').onclick=()=>dialog.close();
 el('[data-check]').onclick=()=>action('check');el('[data-download]').onclick=()=>action('download');el('[data-install]').onclick=()=>action('install');
 action('check');
})();
