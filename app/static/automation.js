'use strict';
async function loadEsjConfig(){
  const config=await json('/api/esj/settings');
  $('#esj-email').value=config.email;$('#esj-password').value='';$('#esj-remember').checked=config.remember;
  $('#esj-password').placeholder=config.has_password?'已设置，留空沿用':'';
  $('#esj-saved-note').textContent=config.has_password?(config.remember?'账号配置已保存。':'账号配置仅供本次运行使用。'):'尚未设置账号密码。';
}
async function submitEsj(login){
  const form=$('#esj-login-form');form.querySelectorAll('button').forEach(b=>b.disabled=true);
  let data={email:$('#esj-email').value.trim(),password:$('#esj-password').value,remember:$('#esj-remember').checked};
  $('#esj-password').value='';
  try{
    if(login)$('#esj-status').textContent='正在登录：先直连，连接失败后尝试系统代理，可能需要等待。';
    const pending=post(login?'/api/esj/session':'/api/esj/settings',data);data=null;await pending;
    await loadEsjConfig();await loadEsjStatus();notice(login?'ESJ 登录成功。':'ESJ 账号配置已更新。');
  }catch(error){if(login)$('#esj-status').textContent=error.message;notice(error.message,true);}
  finally{data=null;$('#esj-password').value='';form.querySelectorAll('button').forEach(b=>b.disabled=false);}
}
$('#esj-login-form').onsubmit=event=>{event.preventDefault();submitEsj(true);};
$('#esj-save').onclick=()=>submitEsj(false);
$('#esj-forget').onclick=async()=>{try{await json('/api/esj/settings',{method:'DELETE'});await loadEsjConfig();await loadEsjStatus();notice('账号配置与登录会话已清除。');}catch(error){notice(error.message,true);}};
window.addEventListener('pageshow',()=>$('#esj-password').value='');
window.addEventListener('pagehide',()=>$('#esj-login-form').reset());
loadEsjConfig().catch(e=>notice(e.message,true));
$('#background-organize').onclick=async()=>{
  if(!selected||organizing)return;
  if(plan.items.some(i=>i.dirty)){notice('请先保存书单修改，再启动后台整理。',true);return;}
  try{
    await json(`/api/jobs/${selected}/result`,{method:'PUT',body:JSON.stringify(resultData)});
    await post(`/api/jobs/${selected}/organize`,{method:$('#extract-method').value});
    notice('后台整理已加入队列，关闭网页后仍会继续。');await loadJobs();
  }catch(error){notice(error.message,true);}
};
async function loadEsjStatus(){
  const status=await json('/api/esj/session');
  $('#esj-status').textContent=(status.connected?'已登录 · 仅限本次运行':'未登录 · 仅查询公开范围')+(status.access_notice?`。${status.access_notice}`:'');
  $('#esj-logout').disabled=!status.connected;
}
$('#esj-refresh').onclick=()=>loadEsjStatus().catch(e=>notice(e.message,true));
$('#esj-logout').onclick=async()=>{
  try{await json('/api/esj/session',{method:'DELETE'});await loadEsjStatus();notice('ESJ 内存会话已清除。');}
  catch(error){notice(error.message,true);}
};
loadEsjStatus().catch(e=>notice(e.message,true));
