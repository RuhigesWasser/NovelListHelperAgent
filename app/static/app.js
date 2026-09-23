'use strict';
const token = document.querySelector('meta[name=session-token]').content;
const $ = (s) => document.querySelector(s);
let selected = null, resultData = [], imageUrls = [], polling = true;
const languageNames = {zh:'中文 / 英文',japan:'日文',korean:'韩文'};
const labels = {queued:'排队中',running:'处理中',succeeded:'已完成',failed:'失败',cancelled:'已取消',interrupted:'已中断'};
function node(tag, text, cls) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n; }
function notice(text, error=false) { $('#notice').hidden=false; $('#notice').textContent=text; $('#notice').className=error?'error':''; }
async function api(path, options={}) { const r=await fetch(path,{...options,headers:{'X-Session-Token':token,'Content-Type':'application/json',...options.headers}}); if(!r.ok){let d;try{d=await r.json();}catch{}throw new Error(typeof d?.detail==='string'?d.detail:`请求失败 (${r.status})`);}return r; }
const json = async (path, options) => (await api(path, options)).json();
const post = (path, data={}) => json(path,{method:'POST',body:JSON.stringify(data)});
function view(name) { document.querySelectorAll('.view').forEach(v=>v.hidden=v.id!==name);document.querySelectorAll('.nav').forEach(n=>n.classList.toggle('active',n.dataset.view===name)); const titles={workspace:['采集与识别','抓取帖子或上传图片，识别后校对文字。'],library:['本地书库','填写书籍资料，按题材保存。'],settings:['引擎与设置','配置模型接口与本地存储。']};$('#page-title').textContent=titles[name][0];$('#page-subtitle').textContent=titles[name][1];if(name==='library')loadBooks().catch(e=>notice(e.message,true)); }
document.querySelectorAll('.nav').forEach(n=>n.addEventListener('click',()=>view(n.dataset.view)));
document.querySelectorAll('[name=kind]').forEach(n=>n.addEventListener('change',()=>{const image=$('[name=kind]:checked').value==='image';$('#source-wrap').hidden=image;$('#upload-wrap').hidden=!image;$('#submit-task').textContent=image?'开始图片识别 →':'开始采集与识别 →';}));
let uploadFiles=[];
for(const id of ['#upload','#upload-folder'])$(id).addEventListener('change',()=>{
  uploadFiles=[...$(id).files].filter(f=>/^image\/(png|jpeg|webp)$/.test(f.type));
  $('#upload-name').textContent=uploadFiles.length?`已选 ${uploadFiles.length} 张图片`:'选择小说截图（可多选）';
  $(id==='#upload'?'#upload-folder':'#upload').value='';
});
$('#engine').addEventListener('change',()=>$('#engine-help').textContent=$('#engine').value==='builtin'?'在本机 CPU 上运行，图片不会发送给模型服务。':'图片将发送到你配置的 API 服务，可能产生调用费用。');
function asBase64(file){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=reject;r.readAsDataURL(file);});}
let failedBatch=[];
async function submitBatch(items){
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
  notice(`已提交 ${count} 项任务。完成后点击任务查看结果。`);await loadJobs();
}
$('#task-form').addEventListener('submit',async e=>{
  e.preventDefault();const isImage=$('[name=kind]:checked').value==='image';
  const items=isImage?uploadFiles.map(file=>({file,source:file.webkitRelativePath||file.name})):[...new Set($('#source').value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean))].map(source=>({source}));
  if(!items.length){notice(isImage?'请先选择图片':'请输入帖子链接',true);return;}
  await submitBatch(items);
});
let pipelineBusy=false,previousPipeline='';
async function loadJobs(){
  const jobs=await json('/api/jobs');
  const busy=j=>['queued','running'].includes(j.state)||['queued','running'].includes(j.organize_state);
  $('#stat-total').textContent=jobs.length;$('#stat-running').textContent=jobs.filter(busy).length;
  $('#stat-done').textContent=jobs.filter(j=>j.state==='succeeded'&&!busy(j)).length;
  $('#queue-count').textContent=`${jobs.length} 个任务`;
  const list=$('#jobs');list.replaceChildren();if(!jobs.length)list.append(node('div','暂无任务','small-empty'));
  for(const j of jobs){
    const row=node('div',undefined,'job'),head=node('div',undefined,'job-title'),open=node('button',j.source||'图片识别');
    open.title=j.source;open.onclick=()=>loadResult(j.id).catch(err=>notice(err.message,true));
    head.append(open,node('span',labels[j.state]||j.state,`pill ${j.state}`));
    row.append(head,node('small',`${j.engine==='builtin'?('OCR · '+(languageNames[j.language]||languageNames.zh)):'LLM'} · ${new Date(j.created).toLocaleString()}`));
    if(j.organize_state)row.append(node('p',j.organize_stage||'等待识别后整理','help'));
    const actions=node('div',undefined,'job-actions');
    if(busy(j)){
      const cancel=node('button',j.state==='succeeded'?'取消整理':'取消','quiet');
      cancel.onclick=()=>post(`/api/jobs/${j.id}/cancel`).then(loadJobs).catch(err=>notice(err.message,true));actions.append(cancel);
    }else{
      const retry=node('button','重新识别','quiet');retry.onclick=()=>post(`/api/jobs/${j.id}/retry`).then(()=>{notice('已创建重试任务');loadJobs();}).catch(err=>notice(err.message,true));actions.append(retry);
      if(j.state==='succeeded'){
        const organize=node('button','继续自动整理','quiet');organize.onclick=()=>post(`/api/jobs/${j.id}/organize`,{method:j.auto_mode==='llm'?'llm':'local'}).then(loadJobs).catch(err=>notice(err.message,true));actions.append(organize);
      }
    }
    const recover=node('button','恢复失败项','quiet');recover.onclick=()=>post(`/api/jobs/${j.id}/recover`).then(()=>{notice('恢复任务已加入队列');loadJobs();}).catch(e=>notice(e.message,true));if(!busy(j)&&(['failed','cancelled','interrupted'].includes(j.state)||['failed','review','interrupted','cancelled'].includes(j.organize_state)))actions.append(recover);row.append(actions);if(j.error||j.organize_error)row.append(node('p',j.error||j.organize_error,'help'));list.append(row);
  }
  const current=jobs.find(j=>j.id===selected);
  pipelineBusy=!!current&&['waiting','queued','running'].includes(current.organize_state);
  const version=current?`${current.id}:${current.organize_state}:${current.organize_stage}`:'';
  if(current?.state==='succeeded'&&($('#result-content').dataset.job!==selected||$('#result-content').dataset.state!==current.state))await loadResult(selected);
  else if(current?.state==='succeeded'&&version!==previousPipeline&&!organizing&&!plan.items.some(i=>i.dirty))await loadPlan(selected);
  previousPipeline=version;
  $('#save-result').disabled=pipelineBusy||current?.state!=='succeeded';
  if(pipelineBusy)$('#organizer').querySelectorAll('button,input,select').forEach(n=>n.disabled=true);
}
async function loadResult(id){const d=await json(`/api/jobs/${id}/result`);selected=id;pipelineBusy=['waiting','queued','running'].includes(d.job.organize_state);if(d.job.state!=='succeeded'&&!d.result.length){$('#result-content').hidden=true;$('#result-empty').hidden=false;notice(d.job.error||'任务尚未完成，请稍后查看。',!!d.job.error);return;}resultData=d.result;$('#organizer').hidden=d.job.state!=='succeeded';if(d.job.state==='succeeded')loadPlan(id).catch(e=>notice(e.message,true));else notice(d.job.error||'当前显示已保存的部分结果，恢复后继续处理。',true);loadRecoveryLog(id).catch(e=>notice(e.message,true));$('#result-empty').hidden=true;$('#result-content').hidden=false;$('#result-content').dataset.job=id;$('#result-content').dataset.state=d.job.state;$('#result-source').textContent=d.job.source;$('#result-engine').textContent=d.job.engine==='builtin'?('内置 OCR · '+(languageNames[d.job.language]||languageNames.zh)):'LLM 多模态';imageUrls.forEach(u=>URL.revokeObjectURL(u));imageUrls=[];const fields=$('#result-fields');fields.replaceChildren();for(let f=0;f<resultData.length;f++){const floor=resultData[f],floorNumber=d.floors?.[f]??(f+1),section=node('section',undefined,'result-floor');section.append(node('h3',`楼层 ${floorNumber}`));const text=node('textarea');text.value=floor.text;text.rows=2;text.setAttribute('aria-label',`楼层 ${floorNumber} 正文`);text.oninput=()=>floor.text=text.value;section.append(text);for(let i=0;i<floor.images.length;i++){const pair=node('div',undefined,'image-pair'),img=node('img'),ta=node('textarea');img.alt=`楼层 ${floorNumber} 的第 ${i+1} 张原图（点击放大）`;img.tabIndex=0;img.setAttribute('role','button');img.onclick=()=>{if(img.src)window.open(img.src,'_blank','noopener');};img.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();img.click();}};ta.value=floor.images[i];ta.setAttribute('aria-label',`图片 ${i+1} 识别文字`);ta.oninput=()=>floor.images[i]=ta.value;pair.append(img,ta);addReocrAction(pair,id,f,i);section.append(pair);api(`/api/jobs/${id}/image/${f}/${i}`).then(r=>r.blob()).then(b=>{if(selected!==id)return;const url=URL.createObjectURL(b);imageUrls.push(url);img.src=url;}).catch(()=>{img.alt='图片加载失败';});}fields.append(section);} }
$('#save-result').onclick=()=>json(`/api/jobs/${selected}/result`,{method:'PUT',body:JSON.stringify(resultData)}).then(()=>notice('校对结果已保存')).catch(e=>notice(e.message,true));
function downloadBlob(blob, name){const url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('#download-result').onclick=()=>downloadBlob(new Blob([JSON.stringify(resultData,null,2)],{type:'application/json'}),'识别结果.json');
$('#go-library').onclick=()=>{view('library');$('#book-form').reset();clearLookup();$('#book-form').elements.source.value='贴吧/图片整理';$('#book-form').elements.url.value=$('#result-source').textContent.startsWith('http')?$('#result-source').textContent:'';notice('请根据校对结果填写书名，或搜索补全资料后保存。');};
async function downloadBook(path,name){try{const r=await api(`/api/books/download?path=${encodeURIComponent(path)}`);downloadBlob(await r.blob(),name);}catch(err){notice(err.message,true);}}
async function loadBooks(){
  const list=$('#books');list.replaceChildren();const books=await json('/api/books');
  if(!books.length)list.append(node('div','暂无书籍','small-empty'));
  for(const b of books){
    const row=node('div',undefined,'book-item'),info=node('div',b.title),actions=node('div',undefined,'actions');
    info.append(node('small',b.category));
    const exportBook=node('button','导出资料','quiet');exportBook.onclick=()=>downloadBook(b.path,b.title+'.md');actions.append(exportBook);
    const chapterLabel=(b.choose_chapters||b.is_esj)?'选择章节':'获取前 3 章';const chapters=node('button',chapterLabel,'quiet');
    chapters.onclick=async()=>{if((b.choose_chapters||b.is_esj)){await chooseChapters(b);return;}chapters.disabled=true;chapters.textContent='读取中…';try{
      const result=await post('/api/books/chapters',{path:b.path});
      notice(`已保存 ${result.count} 章。${result.warnings.join('；')}`);await loadBooks();
    }catch(error){notice(error.message,true);chapters.disabled=false;chapters.textContent=chapterLabel;}};
    actions.append(chapters);
    if(b.text_path){const text=node('button','导出正文','quiet');text.onclick=()=>downloadBook(b.text_path,b.title+'.txt');actions.append(text);}
    row.append(info,actions);list.append(row);
  }
}
$('#download-index').onclick=()=>downloadBook('索引.md','索引.md');
$('#stop').onclick=async()=>{if(!confirm('停止服务将取消未完成任务。已保存的配置和密钥会保留。继续？'))return;try{await post('/api/shutdown');polling=false;notice('服务已停止。可以关闭页面；下次双击 Start.cmd 重新启动。');}catch(e){notice(e.message,true);}};
loadJobs().catch(e=>notice(e.message,true));setInterval(()=>{if(polling)loadJobs().catch(()=>{});},2500);
