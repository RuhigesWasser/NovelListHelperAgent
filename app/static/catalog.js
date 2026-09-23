'use strict';
let bookLookup = null;
let platformList = [];
const matchNames = {exact:'书名与作者一致', title_only:'仅书名一致', possible:'近似书名', author_conflict:'作者不同'};
const formFields = {title:'title',author:'author',platform:'platform_label',words:'word_count',
  status:'status',tags:'tags',intro:'intro',url:'url'};

function clearLookup() {
  bookLookup = null;
  $('#book-evidence').replaceChildren();
}

function fillBook(book) {
  bookLookup = book;
  const form = $('#book-form');
  for (const [field,key] of Object.entries(formFields)) {
    form.elements[field].value = key==='tags' ? book.tags.join('|') : (book[key]??'');
  }
  form.elements.source.value = book.platform_label+' 查询';
  const evidence = $('#book-evidence');
  evidence.replaceChildren(node('span',`来源：${book.platform_label} · 查询时间：${new Date(book.fetched_at).toLocaleString()}`));
  const source = node('a',' 查看来源');
  source.href=book.url;source.target='_blank';source.rel='noopener noreferrer';evidence.append(source);
  if (book.original_url) {
    const link=node('a',' · 原作链接');link.href=book.original_url;link.target='_blank';link.rel='noopener noreferrer';
    evidence.append(link);
  }
  notice('资料已填入。请核对书名、作者和分类后保存。');
}

async function loadPlatforms() {
  platformList = await json('/api/platforms');
  const select=$('#search-platform'),previous=select.value;
  select.replaceChildren();
  for(const item of [...platformList,{id:'all',name:'全部可用平台'}]){const option=node('option',item.name);option.value=item.id;select.append(option);}
  select.value=previous;
  updatePlatformNote();
}
function updatePlatformNote() {
  const item=platformList.find(p=>p.id===$('#search-platform').value);
  $('#platform-note').textContent=item?.note||'按书名查询候选；填写作者可减少同名误匹配。';
}
$('#search-platform').onchange=updatePlatformNote;
$('#new-book').onclick=()=>{$('#book-form').reset();clearLookup();};

$('#search-form').onsubmit=async event=>{
  event.preventDefault();
  const target=$('#search-results'),button=event.target.querySelector('button');
  button.disabled=true;target.replaceChildren(node('p','查询中…','help'));
  try {
    const params=new URLSearchParams({q:$('#search').value,author:$('#search-author').value,platform:$('#search-platform').value});
    const response=await json('/api/catalog/search?'+params);
    target.replaceChildren();
    for(const warning of response.warnings)if(warning!==$('#platform-note').textContent)target.append(node('p',warning,'help'));
    if(response.external_search_url) {
      const link=node('a','打开番茄站内搜索','secondary');
      link.href=response.external_search_url;link.target='_blank';link.rel='noopener noreferrer';
      target.append(link);
    }
    if(!response.items.length&&!response.warnings.length)target.append(node('p','未找到候选书籍','help'));
    for(const book of response.items) {
      const row=node('div',undefined,'search-item'),info=node('div',book.title),choose=node('button','选择','secondary');
      info.append(node('small',`${book.author||'作者未知'} · ${book.platform_label} · ${matchNames[book.match]}`));
      choose.onclick=async()=>{
        if(book.match==='author_conflict'&&!confirm('候选作者与输入不同。仍要读取这本书的资料吗？'))return;
        choose.disabled=true;
        try {fillBook(await post('/api/catalog/detail',{url:book.url}));}
        catch(error){notice(error.message,true);}
        finally{choose.disabled=false;}
      };
      row.append(info,choose);target.append(row);
    }
  } catch(error){target.replaceChildren();notice(error.message,true);}
  finally{button.disabled=false;}
};

$('#detail-form').onsubmit=async event=>{
  event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;
  try {fillBook(await post('/api/catalog/detail',{url:$('#detail-url').value}));}
  catch(error){notice(error.message,true);}
  finally{button.disabled=false;}
};

$('#book-form').onsubmit=async event=>{
  event.preventDefault();const data=Object.fromEntries(new FormData(event.target));
  data.overwrite=event.target.elements.overwrite.checked;
  if(bookLookup) {
    const edited=[];
    for(const [field,key]of Object.entries(formFields)) {
      const original=key==='tags'?bookLookup.tags.join('|'):String(bookLookup[key]??'');
      if(String(data[field])!==original)edited.push(field);
    }
    data.provenance={retrieved:bookLookup,user_edited_fields:edited};
  }
  try{await post('/api/books',data);notice('书籍与查询来源已保存，索引已更新。');await loadBooks();}
  catch(error){notice(error.message,true);}
};

async function loadModels() {
  const models=await json('/api/ocr/models'),panel=$('#ocr-models');panel.replaceChildren();
  for(const model of models) {
    const row=node('div',undefined,'storage-row');
    row.append(node('b',model.name),node('span',model.installed?'已安装':'未安装'));
    if(!model.installed) {
      const button=node('button','下载模型','secondary');
      button.onclick=async()=>{
        if(!confirm(`下载${model.name}识别模型？\n来源：RapidAI / ModelScope\n保存位置：项目 .runtime/models\n不会安装到系统目录。`))return;
        button.disabled=true;button.textContent='下载中…';
        try{await post('/api/ocr/models',{language:model.language,confirmed:true});await loadModels();notice('模型已下载并通过校验。');}
        catch(error){notice(error.message,true);button.disabled=false;button.textContent='重试下载';}
      };
      row.append(button);
    }
    panel.append(row);
  }
}

function addReocrAction(parent,jobId,floor,image) {
  const controls=node('div',undefined,'ocr-controls'),language=node('select');
  language.setAttribute('aria-label','重识别语言');
  for(const [value,label]of [['zh','中文 / 英文'],['japan','日文'],['korean','韩文']]) {
    const option=node('option',label);option.value=value;language.append(option);
  }
  const button=node('button','本地重识别','secondary');
  button.onclick=async()=>{
    button.disabled=true;
    try {
      await post(`/api/jobs/${jobId}/reocr`,{floor,image,language:language.value,engine:'builtin'});
      notice('已创建单图重识别任务，原结果保持不变。完成后从任务列表打开对照。');await loadJobs();
    }catch(error){notice(error.message,true);}
    finally{button.disabled=false;}
  };
  controls.append(language,button);parent.append(controls);
}
Promise.all([loadPlatforms(),loadModels()]).catch(error=>notice(error.message,true));

$('#engine').addEventListener('change',()=>{$('#ocr-language').disabled=$('#engine').value!=='builtin';});
