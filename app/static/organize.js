'use strict';
let plan={items:[],skipped:[]},planJob=null,organizing=false;
const planStates={draft:'待核对',review:'待选择',verified:'书名与作者一致',confirmed:'已选择',archived:'已归档'};
function sourceLink(item){
  if(!item.source_url)return node('span','来源：本地图片','help');
  const link=node('a',item.source_label||'查看原帖');link.href=item.source_url;link.target='_blank';link.rel='noopener noreferrer';return link;
}
async function loadPlan(id){
  if(organizing)return;
  const response=await json(`/api/jobs/${id}/books`);
  if(selected!==id)return;
  plan=response;planJob=id;renderPlan();
}
function draftValue(item){return Object.fromEntries(['title','author','platform','category','floor_index','image_index'].map(k=>[k,item[k]]));}
function renderPlan(){
  const target=$('#proposals');target.replaceChildren();
  $('#organize-status').textContent=`${plan.items.length} 本 · ${plan.items.filter(i=>i.state==='archived').length} 本已归档`;
  if(pipelineBusy){target.append(node('p','正在自动处理，完成后会显示需要你核对的内容。','help'));target.closest('#organizer').querySelectorAll('button,input,select').forEach(n=>n.disabled=true);return;}
  if(plan.review_notice)target.append(node('p',plan.review_notice,'detail-error'));
  const ordered=[...plan.items.entries()].sort((a,b)=>Number(a[1].state==='archived')-Number(b[1].state==='archived'));
  for(const [index,item]of ordered){
    const row=node('section',undefined,'proposal'),fields=node('div',undefined,'form-grid');
    row.append(node('h3',`楼层 ${item.floor} · 图片 ${item.image_index+1} · ${planStates[item.state]}`));
    row.append(sourceLink(item));
    for(const [key,label]of [['title','书名'],['author','作者'],['category','分类']]){
      const wrap=node('label',label),input=node('input');input.value=item[key];input.maxLength=key==='author'?200:key==='category'?50:100;
      input.oninput=()=>{item[key]=input.value;item.dirty=true;item.state='draft';};wrap.append(input);fields.append(wrap);
    }
    const wrap=node('label','平台'),select=node('select');
    for(const [value,label]of [['all','全部平台'],['qidian','起点中文网'],['ciweimao','刺猬猫'],['sfacg','菠萝包'],['fanqie','番茄小说'],['esj','ESJ Zone']]){const o=node('option',label);o.value=value;select.append(o);}
    select.value=item.platform;select.onchange=()=>{item.platform=select.value;item.dirty=true;item.state='draft';};wrap.append(select);fields.append(wrap);row.append(fields);
    const actions=node('div',undefined,'actions'),save=node('button','保存修改','quiet'),verify=node('button',item.manual_selection_required?'选择并核对':'查询核对','secondary');
    save.onclick=()=>planAction(async()=>{plan.items[index]=await json(`/api/jobs/${planJob}/books/${index}`,{method:'PUT',body:JSON.stringify(draftValue(item))});});
    verify.onclick=()=>planAction(()=>verifyItem(index));actions.append(save,verify);row.append(actions);
    for(const warning of item.warnings||[])if(!item.reason?.includes(warning))row.append(node('p',warning,'help'));
    if(item.error||item.archive_error||item.reason)row.append(node('p',item.error||item.archive_error||item.reason,'help'));
    if(item.fallback_error)row.append(node('p','多模态兜底：'+item.fallback_error,'help'));
    if(item.book)row.append(node('p',`${item.book.title} / ${item.book.author} · ${item.book.platform_label}`,'help'));
    const candidates=node('details');candidates.append(node('summary',`候选（${(item.candidates||[]).length}）`));
    candidates.open=item.state==='review';
    for(const candidate of item.candidates||[]){
      const choice=node('button',`${candidate.title} / ${candidate.author||'作者未知'} · ${candidate.platform_label} · ${matchNames[candidate.match]}`,'candidate-choice');
      choice.onclick=()=>planAction(async()=>{
        if(candidate.match==='author_conflict'&&!confirm('该候选作者不同。确认选择这本书？'))return;
        plan.items[index]=await post(`/api/jobs/${planJob}/books/${index}/verify`,{...draftValue(item),url:candidate.url});
      });candidates.append(choice);
    }
    if(item.candidates?.length)row.append(candidates);
    target.append(row);
  }
  for(const skipped of plan.skipped){const entry=node('p',`楼层 ${skipped.floor} · 图片 ${skipped.image_index+1}：${skipped.reason} `,'help');entry.append(sourceLink(skipped));target.append(entry);}
  target.closest('#organizer').querySelectorAll('button,input,select').forEach(n=>n.disabled=pipelineBusy||organizing);
}
async function planAction(action){
  if(organizing||!planJob)return;organizing=true;
  $('#organizer').querySelectorAll('button,input,select').forEach(n=>n.disabled=true);
  try{await action();}catch(error){notice(error.message,true);}
  finally{organizing=false;$('#organizer').querySelectorAll('button,input,select').forEach(n=>n.disabled=false);if(selected===planJob)renderPlan();else await loadPlan(selected);}
}
async function verifyItem(index){
  const item=plan.items[index];
  try{plan.items[index]=await post(`/api/jobs/${planJob}/books/${index}/verify`,draftValue(item));}
  catch(error){item.error=error.message;throw error;}
}
$('#extract-books').onclick=()=>planAction(async()=>{
  if(plan.items.length&&!confirm('重新提取将更新待整理书单，已确认和已归档条目保留。继续？'))return;
  await json(`/api/jobs/${planJob}/result`,{method:'PUT',body:JSON.stringify(resultData)});
  $('#organize-status').textContent='正在提取…';
  plan=await post(`/api/jobs/${planJob}/books/extract`,{method:$('#extract-method').value});
});
$('#verify-books').onclick=()=>planAction(async()=>{
  let failures=0;
  for(let i=0;i<plan.items.length;i++){
    if(plan.items[i].manual_selection_required)continue;
    if(['archived','confirmed','verified'].includes(plan.items[i].state)&&!plan.items[i].dirty)continue;
    $('#organize-status').textContent=`正在核对 ${i+1} / ${plan.items.length}`;
    try{await verifyItem(i);}catch{failures++;}
  }
  notice(`核对完成${failures?`，${failures} 项查询失败，可单独重试`:''}。`,!!failures);
});
$('#archive-books').onclick=()=>planAction(async()=>{
  if(plan.items.some(i=>i.dirty))throw Error('请先保存并核对修改过的书籍');
  plan=await post(`/api/jobs/${planJob}/books/archive`);await loadBooks();notice('归档完成。未确认的书籍保留在待整理列表。');
});
$('#add-proposal').onclick=()=>planAction(async()=>{
  const raw=await json(`/api/jobs/${planJob}/result`);
  const options=[];
  raw.images.forEach((count,f)=>{for(let i=0;i<count;i++)options.push({floor_index:f,image_index:i,floor:raw.floors[f]});});
  if(!options.length)throw Error('该任务没有图片');
  const answer=prompt('选择来源序号：\n'+options.map((o,i)=>`${i+1}. 楼层 ${o.floor} 图片 ${o.image_index+1}`).join('\n'),'1');
  if(answer===null)return;const source=options[Number(answer)-1];if(!source)throw Error('序号无效');
  const title=prompt('书名');if(!title?.trim())return;
  const item={...source,title:title.trim(),author:'',platform:'all',category:'待分类'};
  plan.items.push(await json(`/api/jobs/${planJob}/books/${plan.items.length}`,{method:'PUT',body:JSON.stringify(item)}));
});
