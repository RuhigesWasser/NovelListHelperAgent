'use strict';
async function loadRecoverySettings(){
  const data=await json('/api/recovery/settings');
  $('#recovery-mode').value=data.mode;$('#recovery-calls').value=data.max_calls;$('#recovery-tokens').value=data.max_tokens;
}
$('#recovery-settings').onsubmit=async event=>{
  event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;
  try{await post('/api/recovery/settings',{mode:$('#recovery-mode').value,max_calls:Number($('#recovery-calls').value),max_tokens:Number($('#recovery-tokens').value)});notice('恢复设置已保存，后续任务和恢复操作使用当前设置。');}
  catch(error){notice(error.message,true);}finally{button.disabled=false;}
};
async function loadRecoveryLog(id){
  const data=await json(`/api/jobs/${id}/recovery`);if(selected!==id)return;
  const target=$('#recovery-log');target.replaceChildren();
  const items=Object.entries(data.ocr.images),failed=items.filter(([,i])=>i.state==='failed');
  target.append(node('p',`已保存图片 ${items.length-failed.length}/${data.total_images} · 恢复模型调用 ${data.recovery.calls} 次`,'help'));
  for(const [key,item]of failed){const [f,i]=key.split(':').map(Number);target.append(node('p',`楼层 ${data.floors[f]??f+1} · 图片 ${i+1}：${item.error}`,'help'));}
  const actions={search:'重新查询',reocr:'重新识图',repair_json:'修复书单格式',retry_lookup:'重试查询'};
  for(const event of data.recovery.events)target.append(node('p',`${actions[event.action]||event.action}：${event.message}`,'help'));
}
loadRecoverySettings().catch(e=>notice(e.message,true));
