// This script is embedded only in the managed public build.
const loginPanel=document.createElement('section');
loginPanel.id='managed-login';
loginPanel.innerHTML=`<form id="managed-signin"><h1>Respect 批量创作</h1>
 <p>提交任务后，完整提示词将永久保存到任务中心。你、平台管理员和归属期间的直属主账号可以查看。</p>
 <label>账号<input name="username" autocomplete="username" required maxlength="64"></label>
 <label>密码<input name="password" type="password" autocomplete="current-password" required maxlength="128"></label>
 <p id="managed-error" role="status"></p><button type="submit">登录</button>
 <button type="button" id="managed-recheck">重新检查连接</button></form>`;
document.body.append(loginPanel);
document.body.classList.add('managed-locked');
const taskCenterNote=document.createElement('p');
taskCenterNote.className='hint';
taskCenterNote.textContent='提交后完整提示词将永久保存到账号中心，归属期间的直属主账号及平台管理员可查看。';
document.querySelector('#cards').before(taskCenterNote);
const style=document.createElement('style');
style.textContent=`#managed-login{display:none;max-width:390px;margin:12vh auto;padding:32px;background:#fff;border-radius:20px;box-shadow:0 12px 50px #1e356518}
 .managed-locked>main,.managed-locked>header{display:none}.managed-locked>#managed-login{display:block}
 #managed-login label{display:block;margin:18px 0}#managed-login input{display:block;width:100%;margin-top:8px;box-sizing:border-box}
 #managed-error{color:#bd2525;min-height:1.5em}#managed-login button{margin-right:8px}
 #managed-account{display:flex;gap:10px;align-items:center;flex-wrap:wrap}#managed-usage{font-size:12px;color:#63718b}`;
document.head.append(style);
const accountBar=document.createElement('div');
accountBar.id='managed-account';
accountBar.innerHTML='<span id="managed-name"></span><span id="managed-usage"></span><span id="managed-adapter"></span><button id="managed-refresh" class="mini">刷新后台配置与模型</button><button id="managed-logout" class="mini">退出登录</button>';
document.querySelector('header').append(accountBar);
let managedBusy=false, managedAdapter='';
// A pending page transition belongs to this tab and the original authenticated cookie.
let pageSession='', lastPageState='', pendingPages=[], sendingPages=false;
try{
  pageSession=sessionStorage.getItem('batchDiagnosticSession')||'';
  const saved=JSON.parse(sessionStorage.getItem('batchPendingPages')||'[]');
  if(Array.isArray(saved))pendingPages=saved.slice(-32);
}catch{}
function savePendingPages(){
  try{sessionStorage.setItem('batchPendingPages',JSON.stringify(pendingPages));}catch{}
}
async function sendPageTransition(){
  if(sendingPages||!pendingPages.length)return;
  sendingPages=true;
  try{
    while(pendingPages.length){
      const item=pendingPages[0];
      const result=await api('/api/auth/page',item);
      if(!result.ok)return;
      if(pendingPages[0]===item)pendingPages.shift();
      savePendingPages();
    }
  }catch{}finally{sendingPages=false;}
}
function notePage(state){
  if(!pageSession || lastPageState===state)return;
  lastPageState=state;
  pendingPages.push({session:pageSession,state,at:Math.floor(Date.now()/1000)});
  if(pendingPages.length>32)pendingPages.shift();
  savePendingPages();
  void sendPageTransition();
}
async function managedStatus(load=false){
  if(managedBusy)return;
  managedBusy=true;
  let failureStage='local_status_unreachable';
  try{
    void sendPageTransition();
    const state=await api('/api/auth/status');
    if(!state.ok)throw new Error();
    if(!state.authenticated){
      lastPageState='';
      resetRuns();
      window.BatchModelStats?.reset();
      document.body.classList.add('managed-locked');
      $('#managed-error').textContent=state.msg||'请先登录';
      return;
    }
    const wasLocked=document.body.classList.contains('managed-locked');
    if(pageSession!==state.diagnostic_session)lastPageState='';
    pageSession=state.diagnostic_session||'';
    try{sessionStorage.setItem('batchDiagnosticSession',pageSession);}catch{}
    failureStage='workspace_load_failed';
    document.body.classList.remove('managed-locked');
    $('#managed-name').textContent=state.user.username;
    $('#managed-adapter').textContent=state.adapter?.version?`适配包 ${state.adapter.version}`:'';
    $('#managed-refresh').title='同步账号授权、服务商适配包和模型参数';
    $('#managed-usage').textContent=state.usage.error||(state.usage.pending?`用量待同步 ${state.usage.pending} 条`:'用量已同步');
    if(state.diagnostics){const d=state.diagnostics;
      const notice=d.recording_error?'诊断暂存异常':d.error||(d.pending?`诊断待同步 ${d.pending} 条`:'');
      if(notice)$('#managed-usage').textContent+=' · '+notice;
      if(d.dropped)$('#managed-usage').textContent+=` · 诊断缺失 ${d.dropped} 条`;
    }
    if(state.task_history_error)$('#managed-usage').textContent+=' · '+state.task_history_error;
    $('#managed-refresh').disabled=RUNNING;
    $('#managed-logout').disabled=RUNNING;
    if(load||wasLocked||(!RUNNING&&managedAdapter!==(state.adapter?.sha256||''))){
      await boot();managedAdapter=state.adapter?.sha256||'';
    }
    msg('#releaseNotice',false,(state.issues||[]).join('；'));
    if(wasLocked)notePage('ready');
  }catch(e){
    notePage(failureStage);
    window.BatchModelStats?.reset();
    document.body.classList.add('managed-locked');
    $('#managed-error').textContent='连接失败，请重试。已发任务不会重新提交。';
  }finally{managedBusy=false;}
}
$('#managed-signin').onsubmit=async e=>{
  e.preventDefault();const form=e.currentTarget,button=form.querySelector('[type=submit]');button.disabled=true;
  try{
    const result=await api('/api/auth/login',{username:form.elements.username.value,password:form.elements.password.value});
    form.elements.password.value='';
    if(!result.ok){$('#managed-error').textContent=result.msg||'登录失败';return;}
    SHARED=[];VIDEO_REFS=[];LIBRARIES=[];pendingSubmission=null;resetTaskList();
    await managedStatus(true);
  }catch(e){$('#managed-error').textContent='登录连接失败，请重试';}
  finally{button.disabled=false;}
};
$('#managed-recheck').onclick=()=>managedStatus(true);
$('#managed-refresh').onclick=async()=>{
  const button=$('#managed-refresh');button.disabled=true;
  const selection={kind:$('#kind').value,model:$('#model').value,out:$('#outDir').value,conc:$('#conc').value,retry:$('#retry').value};
  try{
    const result=await api('/api/auth/refresh',{});
    if(!result.ok){toast(result.msg);return;}
    await managedStatus(true);
    if([...$('#kind').options].some(o=>o.value===selection.kind)){$('#kind').value=selection.kind;onKind();}
    if([...$('#model').options].some(o=>o.value===selection.model)){$('#model').value=selection.model;onModel();}
    $('#outDir').value=selection.out;$('#conc').value=selection.conc;$('#retry').value=selection.retry;updateGo();
  }catch(e){toast('刷新失败，请重试');}finally{button.disabled=false;}
};
$('#managed-logout').onclick=async()=>{
  try{const result=await api('/api/auth/logout',{});if(!result.ok)toast(result.msg);}
  finally{await managedStatus();}
};
managedStatus(true);
setInterval(()=>managedStatus(),15000);
