// This script is embedded only in the managed public build.
const loginPanel=document.createElement('section');
loginPanel.id='managed-login';
loginPanel.innerHTML=`<form id="managed-signin"><h1>Respect 批量创作</h1>
 <p>使用管理员分配的账号登录，获取可用模型。</p>
 <label>账号<input name="username" autocomplete="username" required maxlength="64"></label>
 <label>密码<input name="password" type="password" autocomplete="current-password" required maxlength="128"></label>
 <p id="managed-error" role="status"></p><button type="submit">登录</button>
 <button type="button" id="managed-recheck">重新检查连接</button></form>`;
document.body.append(loginPanel);
document.body.classList.add('managed-locked');
const style=document.createElement('style');
style.textContent=`#managed-login{display:none;max-width:390px;margin:12vh auto;padding:32px;background:#fff;border-radius:20px;box-shadow:0 12px 50px #1e356518}
 .managed-locked>main,.managed-locked>header{display:none}.managed-locked>#managed-login{display:block}
 #managed-login label{display:block;margin:18px 0}#managed-login input{display:block;width:100%;margin-top:8px;box-sizing:border-box}
 #managed-error{color:#bd2525;min-height:1.5em}#managed-login button{margin-right:8px}
 #managed-account{display:flex;gap:10px;align-items:center;flex-wrap:wrap}#managed-usage{font-size:12px;color:#63718b}`;
document.head.append(style);
const accountBar=document.createElement('div');
accountBar.id='managed-account';
accountBar.innerHTML='<span id="managed-name"></span><span id="managed-usage"></span><button id="managed-refresh" class="mini">刷新后台配置与模型</button><button id="managed-logout" class="mini">退出登录</button>';
document.querySelector('header').append(accountBar);
let managedBusy=false;
async function managedStatus(load=false){
  if(managedBusy)return;
  managedBusy=true;
  try{
    const state=await api('/api/auth/status');
    if(!state.authenticated){
      document.body.classList.add('managed-locked');
      $('#managed-error').textContent=state.msg||'请先登录';
      return;
    }
    const wasLocked=document.body.classList.contains('managed-locked');
    document.body.classList.remove('managed-locked');
    $('#managed-name').textContent=state.user.username;
    $('#managed-usage').textContent=state.usage.error||(state.usage.pending?`用量待同步 ${state.usage.pending} 条`:'用量已同步');
    $('#managed-refresh').disabled=RUNNING;
    $('#managed-logout').disabled=RUNNING;
    if(load||wasLocked)await boot();
    msg('#releaseNotice',false,(state.issues||[]).join('；'));
  }catch(e){
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
    SHARED=[];VIDEO_REFS=[];LIBRARIES=[];TASKS=[{prompt:'',refs:[]}];
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
