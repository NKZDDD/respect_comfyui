// Local connection preferences must remain reachable even when login is offline.
(() => {
 const dialog=document.createElement('dialog');dialog.id='batch-network-dialog';
 dialog.innerHTML=`<form><div class="network-heading"><h2>联网设置</h2><button type="button" data-close>关闭</button></div>
 <label>联网方式<select name="mode"><option value="system">跟随系统代理（默认）</option><option value="direct">直连</option><option value="custom">指定代理地址</option></select></label>
 <label data-address hidden>HTTP / HTTPS 代理地址<input name="proxy_url" placeholder="http://127.0.0.1:7890" maxlength="2048" autocomplete="off" spellcheck="false"></label>
 <p data-help></p><p class="network-note">用于登录、模型目录、生成、查询和文件传输。TUN / VPN 由系统接管，直连模式仍可能经过它。</p>
 <p class="network-note">保存后，后续请求使用新设置。不会重新提交已发任务；下载或连接恢复后可手动重试查询。</p>
 <p role="status" data-message></p><button type="submit" class="primary">保存联网设置</button></form>`;
 document.body.append(dialog);
 const button=document.createElement('button');button.id='batch-network-button';button.textContent='联网设置';document.body.append(button);
 const style=document.createElement('style');style.textContent=`#batch-network-button{position:fixed;right:128px;bottom:16px;z-index:30;box-shadow:0 3px 16px #0002}
 #batch-network-dialog{box-sizing:border-box;border:1px solid #e4e8f0;border-radius:20px;padding:26px;width:min(540px,92vw);max-height:90vh;color:#182536}
 #batch-network-dialog::backdrop{background:#17243766}.network-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}
 #batch-network-dialog label{display:block;margin:18px 0}#batch-network-dialog label[hidden]{display:none}
 #batch-network-dialog input,#batch-network-dialog select{box-sizing:border-box;display:block;width:100%;margin-top:8px}
 #batch-network-dialog p{line-height:1.6;overflow-wrap:anywhere}.network-note,#batch-network-dialog [data-help]{color:#64748b;font-size:14px}
 #batch-network-dialog [data-message]{min-height:1.6em}#batch-network-dialog [data-message].error{color:#bd2525}`;document.head.append(style);
 const form=dialog.querySelector('form'),mode=form.elements.mode,address=form.elements.proxy_url;
 const status=dialog.querySelector('[data-message]'),save=form.querySelector('[type=submit]');
 const message=(text,error=false)=>{status.textContent=text;status.classList.toggle('error',error);};
 function render(){
   const custom=mode.value==='custom';dialog.querySelector('[data-address]').hidden=!custom;address.required=custom;
   dialog.querySelector('[data-help]').textContent={
     system:'读取系统手动代理、代理环境变量及绕过规则。PAC 自动配置脚本不受支持，请改为指定代理地址。',
     direct:'忽略应用代理设置，直接连接目标。适合当前网络可以直接访问服务的电脑。',
     custom:'填写本机代理软件提供的 HTTP / HTTPS 端口。需要先启动代理软件；不支持在地址中填写账号密码或 SOCKS 地址。'
   }[mode.value];
 }
 mode.onchange=render;
 button.onclick=async()=>{
   dialog.showModal();save.disabled=true;message('正在读取设置…');
   try{const result=await api('/api/network');if(!result.ok)throw new Error(result.msg||'读取失败');
     mode.value=result.network.mode;address.value=result.network.proxy_url;message('');
   }catch(e){message('读取设置失败，可重新选择并保存。',true);}
   finally{render();save.disabled=false;}
 };
 dialog.querySelector('[data-close]').onclick=()=>dialog.close();
 form.onsubmit=async e=>{
   e.preventDefault();save.disabled=true;message('正在保存…');
   try{const result=await api('/api/network',{mode:mode.value,proxy_url:mode.value==='custom'?address.value.trim():''});
     if(!result.ok){message(result.msg||'保存失败',true);return;}
     mode.value=result.network.mode;address.value=result.network.proxy_url;render();
     message('已保存。未登录时可重新登录；已登录时点击“刷新后台配置与模型”重新拉取模型。');
   }catch(e){message('无法连接本地程序，设置未确认保存，请重新打开后检查。',true);}
   finally{save.disabled=false;}
 };
 render();
})();
