'use strict';
let currentProfileId='default', profileState=null;
const profileFields={name:'profile-name',base_url:'base-url',model:'model',protocol:'llm-protocol',
  endpoint_mode:'endpoint-mode',auth:'auth-mode',key_header:'key-header',api_version:'api-version',
  max_tokens:'max-tokens',timeout:'llm-timeout',token_field:'token-field'};
const newProfile={name:'新配置',base_url:'',model:'',protocol:'chat_completions',endpoint_mode:'auto',
  auth:'auto',key_header:'',api_version:'2023-06-01',max_tokens:32768,timeout:300,token_field:'max_tokens',
  remember_key:true,stream:false,headers:{},extra_body:{}};

function renderProfile(profile) {
  for(const [key,id]of Object.entries(profileFields))$('#'+id).value=profile[key]??newProfile[key];
  $('#api-key').value='';
  $('#remember-key').checked=profile.remember_key??true;
  $('#llm-stream').checked=!!profile.stream;
  $('#llm-headers').value=JSON.stringify(profile.headers||{},null,2);
  $('#extra-body').value=JSON.stringify(profile.extra_body||{},null,2);
  $('#key-status').textContent=profile.has_key?(profile.remember_key?'密钥已保存，留空表示继续使用。':'密钥已在内存中设置，重启后需重新填写。'):'此配置尚未设置密钥。';
  $('#llm-test-status').textContent=profile.verification?.message||'尚未进行图片能力测试。';
}
function acceptSettings(data,restoreTask=false) {
  profileState=data;currentProfileId=data.active_id;
  const select=$('#llm-profile');select.replaceChildren();
  for(const profile of data.profiles){const option=node('option',profile.name);option.value=profile.id;select.append(option);}
  select.value=currentProfileId;renderProfile(data);
  $('#data-dir').textContent=`数据目录：${data.data_dir}`;
  if(restoreTask){$('#engine').value=data.preferences.engine;$('#ocr-language').value=data.preferences.language;$('#auto-mode').value=data.preferences.auto_mode||'local';$('#engine').dispatchEvent(new Event('change'));}
  updateProfileHint();
}
async function loadSettings(){acceptSettings(await json('/api/settings'),true);}
function updateProfileHint(){
  $('#llm-current').hidden=$('#engine').value!=='llm';
  $('#llm-current').textContent=profileState?`当前配置：${profileState.name} · ${profileState.model||'未设置模型'}`:'尚未选择 LLM 配置';
}
$('#engine').addEventListener('change',updateProfileHint);
function parseObject(id,label){
  let value;try{value=JSON.parse($('#'+id).value||'{}');}catch{throw Error(label+'必须是有效 JSON 对象');}
  if(!value||typeof value!=='object'||Array.isArray(value))throw Error(label+'必须是 JSON 对象');
  return value;
}
function readProfile(){
  const data={id:currentProfileId,key:$('#api-key').value,remember_key:$('#remember-key').checked,stream:$('#llm-stream').checked};
  for(const [key,id]of Object.entries(profileFields))data[key]=['max_tokens','timeout'].includes(key)?Number($('#'+id).value):$('#'+id).value;
  data.headers=parseObject('llm-headers','附加请求头');data.extra_body=parseObject('extra-body','附加生成参数');
  return data;
}
$('#new-profile').onclick=()=>{
  currentProfileId='new';const select=$('#llm-profile');
  if(!select.querySelector('option[value="new"]')){const option=node('option','新配置（未保存）');option.value='new';select.append(option);}
  select.value='new';renderProfile(newProfile);$('#profile-name').focus();
};
$('#llm-profile').onchange=async()=>{
  if($('#llm-profile').value==='new'){currentProfileId='new';renderProfile(newProfile);return;}
  try{acceptSettings(await post('/api/settings/activate',{id:$('#llm-profile').value}));notice('已切换配置，下次启动自动恢复。');}
  catch(error){notice(error.message,true);}
};
$('#delete-profile').onclick=async()=>{
  if(currentProfileId==='new'){acceptSettings(await json('/api/settings'));return;}
  if(!confirm('删除这份配置及其保存的密钥？'))return;
  try{acceptSettings(await json('/api/settings/profiles/'+encodeURIComponent(currentProfileId),{method:'DELETE'}));notice('配置已删除。');}
  catch(error){notice(error.message,true);}
};
$('#settings-form').onsubmit=async event=>{
  event.preventDefault();try{acceptSettings(await post('/api/settings',readProfile()));notice('配置已保存并选用。');}
  catch(error){notice(error.message,true);}
};
$('#clear-key').onclick=async()=>{
  if(currentProfileId==='new'){$('#api-key').value='';return;}
  try{acceptSettings(await post('/api/settings',{id:currentProfileId,clear_key:true}));notice('该配置的密钥已清除。');}
  catch(error){notice(error.message,true);}
};
async function testProfile(kind){
  const button=$('#'+(kind==='vision'?'test-vision':'test-api'));button.disabled=true;
  $('#llm-test-status').textContent=kind==='vision'?'正在发送随机数字图片…':'正在测试 API 调用…';
  try{
    const result=await post('/api/settings/test',{...readProfile(),kind});
    $('#llm-test-status').textContent=`${result.message} 耗时 ${result.latency_ms} ms。`;
  }catch(error){$('#llm-test-status').textContent=error.message;notice(error.message,true);}
  finally{button.disabled=false;}
}
$('#test-api').onclick=()=>testProfile('connection');
$('#test-vision').onclick=()=>testProfile('vision');
loadSettings().catch(error=>notice(error.message,true));
