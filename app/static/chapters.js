'use strict';
let chapterRequest=0;
async function chooseChapters(book){
  const requestId=++chapterRequest;
  const dialog=$('#chapter-dialog'),list=$('#chapter-options'),save=$('#chapter-save');
  $('#chapter-heading').textContent=book.title+' · 下载内容';
  $('#chapter-note').textContent='正在读取目录。先直连，连接失败后尝试系统代理；ESJ 可能较慢。';
  list.replaceChildren();$('#chapter-selected').textContent='';save.disabled=true;save.onclick=null;dialog.showModal();
  let data;
  try{data=await post('/api/books/catalog',{path:book.path});}
  catch(error){if(requestId===chapterRequest)$('#chapter-note').textContent=error.message;return;}
  if(!dialog.open||requestId!==chapterRequest)return;
  const cached=new Set(data.saved_urls),selected=new Set(data.suggested_urls.filter(url=>!cached.has(url)));
  const tools=node('div',undefined,'chapter-tools'),search=node('input');search.placeholder='筛选章节标题';search.setAttribute('aria-label','筛选章节标题');
  const selectAll=node('button','选择筛选结果','secondary'),missing=node('button','选择未下载','secondary'),clear=node('button','清空选择','quiet');
  tools.append(search,selectAll,missing,clear);list.append(tools);
  const rows=[];
  const selection=()=>{
    for(const row of rows)row.check.checked=selected.has(row.entry.url);
    $('#chapter-selected').textContent=`目录 ${data.entries.length} 项 · 已下载 ${cached.size} 项 · 已选 ${selected.size} 项`;
    save.disabled=!selected.size;save.textContent='下载所选内容';
  };
  $('#chapter-note').textContent='按网站目录顺序保存；已保存的其他章节会保留。公告、插图等条目可自行取消。';
  let lastGroup=null;
  for(const entry of data.entries){
    const group=entry.group||'目录';
    if(group!==lastGroup){list.append(node('h3',group));lastGroup=group;}
    const label=node('label',undefined,'chapter-option'),check=node('input');check.type='checkbox';
    check.onchange=()=>{if(check.checked)selected.add(entry.url);else selected.delete(entry.url);selection();};
    label.append(check,node('span',entry.title),node('small',cached.has(entry.url)?'已下载':entry.kind||''));list.append(label);rows.push({entry,label,check});
  }
  search.oninput=()=>{const query=search.value.trim().toLocaleLowerCase();for(const row of rows)row.label.hidden=!row.entry.title.toLocaleLowerCase().includes(query);};
  selectAll.onclick=()=>{for(const row of rows)if(!row.label.hidden)selected.add(row.entry.url);selection();};
  missing.onclick=()=>{for(const row of rows)if(!row.label.hidden&&!cached.has(row.entry.url))selected.add(row.entry.url);selection();};
  clear.onclick=()=>{selected.clear();selection();};selection();
  save.onclick=async()=>{
    save.disabled=true;list.querySelectorAll('input,button').forEach(n=>n.disabled=true);
    const urls=data.entries.filter(entry=>selected.has(entry.url)).map(entry=>entry.url),warnings=[];let count=0,finished=0;
    for(const url of urls){
      if(requestId!==chapterRequest||!dialog.open)break;
      $('#chapter-note').textContent=`正在下载 ${finished+1} / ${urls.length} 项；关闭窗口将在当前章节完成后停止。`;
      try{const result=await post('/api/books/chapters',{path:book.path,selected_urls:[url]});count+=result.count;warnings.push(...result.warnings);cached.add(url);selected.delete(url);}
      catch(error){warnings.push(data.entries.find(entry=>entry.url===url).title+'：'+error.message);}
      finished++;
    }
    await loadBooks();
    if(requestId===chapterRequest&&dialog.open){
      list.querySelectorAll('input,button').forEach(n=>n.disabled=false);selection();
      for(const row of rows)row.label.querySelector('small').textContent=cached.has(row.entry.url)?'已下载':row.entry.kind||'';
      $('#chapter-note').textContent=`已保存 ${count} 项。`+(warnings.length?warnings.join('；'):'可继续选择，或关闭后阅读。');
    }else notice(`已保存 ${count} 项。`+(warnings.length?warnings.join('；'):''));
  };
}
$('#chapter-close').onclick=()=>$('#chapter-dialog').close();
$('#chapter-dialog').addEventListener('close',()=>chapterRequest++);
