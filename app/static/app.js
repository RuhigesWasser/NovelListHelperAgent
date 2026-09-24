'use strict';
const token = document.querySelector('meta[name=session-token]').content;
const $ = (s) => document.querySelector(s);
let selected = null, resultData = [], imageUrls = [], polling = true;
const languageNames = {zh:'中文 / 英文',japan:'日文',korean:'韩文'};
const labels = {queued:'排队中',running:'处理中',succeeded:'已完成',failed:'失败',cancelled:'已取消',interrupted:'已中断'};
function node(tag, text, cls) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n; }
function notice(text, error=false) { const target=$('#book-create-notice');if(target&&$('#book-create-dialog')?.open){target.hidden=false;target.textContent=text;target.className=error?'detail-error':'help';} $('#notice').hidden=false; $('#notice').textContent=text; $('#notice').className=error?'error':''; }
async function api(path, options={}) { const r=await fetch(path,{...options,headers:{'X-Session-Token':token,'Content-Type':'application/json',...options.headers}}); if(!r.ok){let d;try{d=await r.json();}catch{}throw new Error(typeof d?.detail==='string'?d.detail:`请求失败 (${r.status})`);}return r; }
const json = async (path, options) => (await api(path, options)).json();
const post = (path, data={}) => json(path,{method:'POST',body:JSON.stringify(data)});
function view(name) { document.querySelectorAll('.view').forEach(v=>v.hidden=v.id!==name);document.querySelectorAll('.nav').forEach(n=>n.classList.toggle('active',n.dataset.view===name)); const titles={workspace:['采集与识别','抓取帖子或上传图片，识别后校对文字。'],library:['本地书库','查阅、筛选和管理已归档的小说。'],settings:['引擎与设置','配置模型接口与本地存储。']};$('#page-title').textContent=titles[name][0];$('#page-subtitle').textContent=titles[name][1];if(name==='library')loadBooks().catch(e=>notice(e.message,true)); }
document.querySelectorAll('.nav').forEach(n=>n.addEventListener('click',()=>view(n.dataset.view)));
document.querySelectorAll('[name=kind]').forEach(n=>n.addEventListener('change',()=>{const image=$('[name=kind]:checked').value==='image';$('#source-wrap').hidden=image;$('#upload-wrap').hidden=!image;$('#submit-task').textContent=image?'开始图片识别 →':'开始采集与识别 →';}));
let uploadFiles=[];
for(const id of ['#upload','#upload-folder'])$(id).addEventListener('change',()=>{
  uploadFiles=[...$(id).files].filter(f=>/^image\/(png|jpeg|webp)$/.test(f.type));
  $('#upload-name').textContent=uploadFiles.length?`已选 ${uploadFiles.length} 张图片`:'选择小说截图（可多选）';
  $(id==='#upload'?'#upload-folder':'#upload').value='';
});
$('#engine').addEventListener('change',()=>$('#engine-help').textContent=$('#engine').value==='builtin'?'OCR 在本机运行；启用 LLM 提取或多模态兜底时，会按设置发送文字或图片。':'图片将发送到你配置的 API 服务，可能产生调用费用。');
$('#engine').addEventListener('change',()=>$('#task-engine-summary').textContent=$('#engine').value==='builtin'?'内置 OCR':'多模态 LLM');
function asBase64(file){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=reject;r.readAsDataURL(file);});}
let failedBatch=[];
let organizeSettingsReady=Promise.resolve();
async function submitBatch(items){
  try{await organizeSettingsReady;}catch(error){notice(error.message,true);return;}
  const button=$('#submit-task');button.disabled=true;failedBatch=[];
  const progress=$('#batch-progress');progress.replaceChildren();let count=0;
  const engine=$('#engine').value,language=$('#ocr-language').value,auto_mode=$('#auto-mode').value;
  for(const item of items){
    try{
      if(item.file?.size>20000000)throw Error('图片超过 20 MB');
      const job=await post('/api/jobs',{kind:item.file?'image':'tieba',source:item.source,engine,language,auto_mode,image:item.file?await asBase64(item.file):''});
      selected=job.id;count++;
    }catch(error){failedBatch.push(item);progress.append(node('p',`${item.source}：${error.message}`));}
    button.textContent=`正在提交 ${count+failedBatch.length} / ${items.length}`;
  }
  progress.prepend(node('p',`已提交 ${count} 项，失败 ${failedBatch.length} 项。`));
  if(failedBatch.length){const retry=node('button','重试失败项','secondary');retry.type='button';retry.onclick=()=>submitBatch([...failedBatch]);progress.append(retry);}
  button.disabled=false;button.textContent='开始采集与识别 →';
  notice(`已提交 ${count} 项任务。完成后可从任务记录查看结果。`);jobsPage=0;await loadJobs();
}
$('#task-form').addEventListener('submit',async e=>{
  e.preventDefault();const isImage=$('[name=kind]:checked').value==='image';
  const items=isImage?uploadFiles.map(file=>({file,source:file.webkitRelativePath||file.name})):[...new Set($('#source').value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean))].map(source=>({source}));
  if(!items.length){notice(isImage?'请先选择图片':'请输入帖子链接',true);return;}
  await submitBatch(items);
});
let pipelineBusy=false,previousPipeline='';
let jobRows=[],jobsPage=0,jobSnapshot='';
const jobsPageSize=10;
const busyJob=j=>['queued','running'].includes(j.state)||['queued','running'].includes(j.organize_state);
$('#open-tasks').onclick=()=>$('#tasks-drawer').showModal();
$('#close-tasks').onclick=()=>$('#tasks-drawer').close();
$('#jobs-prev').onclick=()=>{jobsPage--;renderJobs();$('#jobs').scrollTop=0;};
$('#jobs-next').onclick=()=>{jobsPage++;renderJobs();$('#jobs').scrollTop=0;};
function renderJobs(){
  const jobs=jobRows,busy=busyJob,pages=Math.max(1,Math.ceil(jobs.length/jobsPageSize));
  jobsPage=Math.max(0,Math.min(jobsPage,pages-1));
  $('#jobs-page').textContent=`${jobsPage+1} / ${pages} 页`;
  $('#jobs-prev').disabled=jobsPage===0;$('#jobs-next').disabled=jobsPage===pages-1;
  const scroll=$('#jobs').scrollTop;
  const list=$('#jobs');list.replaceChildren();if(!jobs.length)list.append(node('div','暂无任务','small-empty'));
  for(const j of jobs.slice(jobsPage*jobsPageSize,(jobsPage+1)*jobsPageSize)){
    const row=node('div',undefined,j.id===selected?'job selected-job':'job'),head=node('div',undefined,'job-title'),open=node('button',j.source||'图片识别');
    open.title=j.source;open.onclick=()=>loadResult(j.id).then(()=>{$('#tasks-drawer').close();renderJobs();}).catch(err=>notice(err.message,true));
    const stage=j.state==='succeeded'?j.organize_state:'';
    const statusText=stage?({review:'待核对',succeeded:'整理完成',running:'整理中',queued:'等待整理',waiting:'等待整理',failed:'整理失败',cancelled:'整理已取消',interrupted:'整理已中断'}[stage]||'OCR 已完成'):(j.state==='succeeded'?'OCR 已完成':labels[j.state]||j.state);
    head.append(open,node('span',statusText,`pill ${stage||j.state}`));
    row.append(head,node('small',`${j.engine==='builtin'?('OCR · '+(languageNames[j.language]||languageNames.zh)):'LLM'} · ${new Date(j.created).toLocaleString()}`));
    if(j.organize_state)row.append(node('p',j.organize_stage||'等待识别后整理','help'));
    const actions=node('div',undefined,'job-actions');
    if(busy(j)){
      const cancel=node('button',j.state==='succeeded'?'取消整理':'取消','quiet');
      cancel.onclick=()=>post(`/api/jobs/${j.id}/cancel`).then(loadJobs).catch(err=>notice(err.message,true));actions.append(cancel);
    }else{
      const retry=node('button','重新识别','quiet');retry.onclick=()=>post(`/api/jobs/${j.id}/retry`).then(()=>{notice('已创建重试任务');loadJobs();}).catch(err=>notice(err.message,true));actions.append(retry);
      if(j.state==='succeeded'){
        const organize=node('button','继续自动整理','quiet');organize.onclick=()=>post(`/api/jobs/${j.id}/organize`,{method:['llm','vision'].includes(j.auto_mode)?j.auto_mode:'local'}).then(loadJobs).catch(err=>notice(err.message,true));actions.append(organize);
      }
    }
    const recover=node('button','恢复失败项','quiet');recover.onclick=()=>post(`/api/jobs/${j.id}/recover`).then(()=>{notice('恢复任务已加入队列');loadJobs();}).catch(e=>notice(e.message,true));if(!busy(j)&&(['failed','cancelled','interrupted'].includes(j.state)||['failed','review','interrupted','cancelled'].includes(j.organize_state)))actions.append(recover);row.append(actions);if(j.error||j.organize_error)row.append(node('p',j.error||j.organize_error,'help'));list.append(row);
  }
  $('#jobs').scrollTop=scroll;
}
async function loadJobs(){
  const jobs=await json('/api/jobs');
  const busy=j=>['queued','running'].includes(j.state)||['queued','running'].includes(j.organize_state);
  $('#stat-total').textContent=jobs.length;$('#stat-running').textContent=jobs.filter(busy).length;
  $('#stat-done').textContent=jobs.filter(j=>j.state==='succeeded'&&!busy(j)).length;
  $('#queue-count').textContent=`${jobs.length} 个任务`;
  jobRows=jobs;$('#task-total').textContent=jobs.length;
  const snapshot=JSON.stringify(jobs);if(snapshot!==jobSnapshot){renderJobs();jobSnapshot=snapshot;}
  const current=jobs.find(j=>j.id===selected);
  pipelineBusy=!!current&&['waiting','queued','running'].includes(current.organize_state);
  const version=current?`${current.id}:${current.organize_state}:${current.organize_stage}`:'';
  if(current?.state==='succeeded'&&($('#result-content').dataset.job!==selected||$('#result-content').dataset.state!==current.state))await loadResult(selected);
  else if(current?.state==='succeeded'&&version!==previousPipeline&&!organizing&&!plan.items.some(i=>i.dirty))await loadPlan(selected);
  previousPipeline=version;
  $('#save-result').disabled=pipelineBusy||current?.state!=='succeeded';
  if(pipelineBusy)$('#organizer').querySelectorAll('button,input,select').forEach(n=>n.disabled=true);
}
let resultPage=0,resultFloors=[],resultRender=0,resultLoad=0;
const resultPageSize=8;
async function loadResult(id){
  const request=++resultLoad,changed=$('#result-content').dataset.job!==id;selected=id;
  $('#result-footer').hidden=true;$('#result-content').hidden=true;$('#result-empty').hidden=false;
  $('#result-empty h3').textContent='正在读取识别结果…';
  const d=await json(`/api/jobs/${id}/result`);if(request!==resultLoad)return;
  pipelineBusy=['waiting','queued','running'].includes(d.job.organize_state);
  if(d.job.state!=='succeeded'&&!d.result.length){
    $('#result-empty h3').textContent='暂无可显示的结果';
    notice(d.job.error||'任务尚未完成，请稍后查看。',!!d.job.error);return;
  }
  resultData=d.result;resultFloors=d.floors||[];if(changed)resultPage=0;
  $('#organizer').hidden=d.job.state!=='succeeded';
  if(d.job.state==='succeeded')loadPlan(id).catch(e=>notice(e.message,true));
  else notice(d.job.error||'当前显示已保存的部分结果，恢复后继续处理。',true);
  loadRecoveryLog(id).catch(e=>notice(e.message,true));
  $('#result-empty').hidden=true;$('#result-content').hidden=false;
  $('#result-footer').hidden=false;$('#result-actions').hidden=false;
  $('#result-content').dataset.job=id;$('#result-content').dataset.state=d.job.state;
  $('#result-source').textContent=d.job.source;
  $('#result-engine').textContent=d.job.engine==='builtin'?('内置 OCR · '+(languageNames[d.job.language]||languageNames.zh)):'LLM 多模态';
  $('#save-result').disabled=pipelineBusy||d.job.state!=='succeeded';
  renderResultFields();$('#result-scroll').scrollTop=0;
}
function renderResultFields(){
  const id=selected,version=++resultRender,entries=[];
  resultData.forEach((floor,f)=>{if(!floor.images.length)entries.push({f,i:null});else floor.images.forEach((_,i)=>entries.push({f,i}));});
  const pages=Math.max(1,Math.ceil(entries.length/resultPageSize));resultPage=Math.max(0,Math.min(resultPage,pages-1));
  $('#result-page').textContent=`素材 ${entries.length?resultPage*resultPageSize+1:0}–${Math.min(entries.length,(resultPage+1)*resultPageSize)} / ${entries.length} · ${resultPage+1}/${pages} 页`;
  $('#result-prev').disabled=resultPage===0;$('#result-next').disabled=resultPage===pages-1;
  imageUrls.forEach(url=>URL.revokeObjectURL(url));imageUrls=[];
  const fields=$('#result-fields'),sections=new Map();fields.replaceChildren();
  for(const {f,i} of entries.slice(resultPage*resultPageSize,(resultPage+1)*resultPageSize)){
    const floor=resultData[f],floorNumber=resultFloors[f]??f+1;
    if(!sections.has(f)){
      const section=node('section',undefined,'result-floor');section.append(node('h3',`楼层 ${floorNumber}`));
      const text=node('textarea');text.value=floor.text;text.rows=2;text.setAttribute('aria-label',`楼层 ${floorNumber} 正文`);text.oninput=()=>floor.text=text.value;
      section.append(text);sections.set(f,section);fields.append(section);
    }
    if(i===null)continue;
    const pair=node('div',undefined,'image-pair'),img=node('img'),ta=node('textarea');
    img.alt=`楼层 ${floorNumber} 的第 ${i+1} 张原图（点击放大）`;img.tabIndex=0;img.setAttribute('role','button');
    img.onclick=()=>{if(img.src)window.open(img.src,'_blank','noopener');};
    img.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();img.click();}};
    ta.value=floor.images[i];ta.setAttribute('aria-label',`图片 ${i+1} 识别文字`);ta.oninput=()=>floor.images[i]=ta.value;
    pair.append(img,ta);addReocrAction(pair,id,f,i);sections.get(f).append(pair);
    api(`/api/jobs/${id}/image/${f}/${i}`).then(r=>r.blob()).then(blob=>{
      if(selected!==id||version!==resultRender||!img.isConnected)return;
      const url=URL.createObjectURL(blob);imageUrls.push(url);img.src=url;
    }).catch(()=>{img.alt='图片加载失败';});
  }
}
$('#result-prev').onclick=()=>{resultPage--;renderResultFields();$('#result-scroll').scrollTop=0;};
$('#result-next').onclick=()=>{resultPage++;renderResultFields();$('#result-scroll').scrollTop=0;};
$('#save-result').onclick=()=>json(`/api/jobs/${selected}/result`,{method:'PUT',body:JSON.stringify(resultData)}).then(()=>notice('校对结果已保存')).catch(e=>notice(e.message,true));
function downloadBlob(blob, name){const url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('#download-result').onclick=()=>downloadBlob(new Blob([JSON.stringify(resultData,null,2)],{type:'application/json'}),'识别结果.json');
$('#go-library').onclick=()=>{view('library');openBookCreate();$('#book-form').reset();clearLookup();$('#book-form').elements.source.value='贴吧/图片整理';$('#book-form').elements.url.value=$('#result-source').textContent.startsWith('http')?$('#result-source').textContent:'';notice('请根据校对结果填写书名，或搜索补全资料后保存。');};
async function downloadBook(path,name){try{const r=await api(`/api/books/download?path=${encodeURIComponent(path)}`);downloadBlob(await r.blob(),name);}catch(err){notice(err.message,true);}}
$('#download-index').onclick=()=>downloadBook('索引.md','索引.md');
$('#stop').onclick=async()=>{if(!confirm('停止服务将取消未完成任务。已保存的配置和密钥会保留。继续？'))return;try{await post('/api/shutdown');polling=false;notice('服务已停止。可以关闭页面；下次双击 Start.cmd 重新启动。');}catch(e){notice(e.message,true);}};
loadJobs().catch(e=>notice(e.message,true));setInterval(()=>{if(polling)loadJobs().catch(()=>{});},2500);
