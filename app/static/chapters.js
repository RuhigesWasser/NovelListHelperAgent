'use strict';
let chapterRequest=0;
async function chooseChapters(book){
  const requestId=++chapterRequest;
  const dialog=$('#chapter-dialog'),list=$('#chapter-options'),save=$('#chapter-save');
  $('#chapter-heading').textContent=book.title+' · 选择章节';
  $('#chapter-note').textContent='正在读取目录，请稍候。ESJ 直连失败后会尝试系统代理。';
  list.replaceChildren();$('#chapter-selected').textContent='';save.disabled=true;save.onclick=null;dialog.showModal();
  let data;
  try{data=await post('/api/books/catalog',{path:book.path});}
  catch(error){if(requestId===chapterRequest)$('#chapter-note').textContent=error.message;return;}
  if(!dialog.open||requestId!==chapterRequest)return;
  const selected=new Set(data.suggested_urls);
  const selection=()=>{
    const titles=[...selected].map(url=>data.entries.find(e=>e.url===url).title);
    $('#chapter-selected').textContent=titles.length?`已选 ${titles.length}/3，保存顺序：${titles.join(' → ')}`:'请选择最多 3 项';
    save.disabled=!selected.size;
  };
  $('#chapter-note').textContent=data.selection_reason+' 未编号条目可能是正文，也可能是公告、插图或随笔。';
  let lastGroup=null;
  for(const entry of data.entries){
    const group=entry.group||'目录';
    if(group!==lastGroup){list.append(node('h3',group));lastGroup=group;}
    const label=node('label',undefined,'chapter-option'),check=node('input');check.type='checkbox';check.checked=selected.has(entry.url);
    check.onchange=()=>{
      if(check.checked&&selected.size>=3){check.checked=false;$('#chapter-note').textContent='最多选择 3 项，请先取消一项。';return;}
      if(check.checked)selected.add(entry.url);else selected.delete(entry.url);selection();
    };
    label.append(check,node('span',entry.title),node('small',entry.kind||''));list.append(label);
  }
  selection();
  save.onclick=async()=>{
    save.disabled=true;list.querySelectorAll('input').forEach(n=>n.disabled=true);
    $('#chapter-note').textContent='正在读取所选内容，请稍候。';
    try{
      const result=await post('/api/books/chapters',{path:book.path,selected_urls:[...selected]});
      if(requestId===chapterRequest)dialog.close();notice(`${book.title}：已保存 ${result.count} 项。${result.warnings.join('；')}`);await loadBooks();
    }catch(error){if(requestId===chapterRequest){$('#chapter-note').textContent=error.message;save.disabled=false;list.querySelectorAll('input').forEach(n=>n.disabled=false);}}
  };
}
$('#chapter-close').onclick=()=>$('#chapter-dialog').close();
$('#chapter-dialog').addEventListener('close',()=>chapterRequest++);
