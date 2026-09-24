'use strict';
let libraryBooks=[],detailBook=null,detailRequest=0;
let coverPoll=null;
const coverBlobs=new Map(),coverLoads=new Map();
function coverElement(book,large=false){
  const cover=node('div',undefined,large?'book-mark large-cover':'book-mark');cover.setAttribute('aria-hidden','true');
  let hue=0;for(const ch of book.category)hue=(hue+ch.charCodeAt(0))%95;
  cover.style.setProperty('--book-hue',String(110+hue));cover.append(node('small',book.platform||'藏书'),node('strong',book.category==='待分类'?'书':book.category.slice(0,2)||'书'),node('i','拾页'));
  if(book.cover?.has_image){
    const img=node('img');img.alt='';img.decoding='async';img.loading=large?'eager':'lazy';
    img.onload=()=>cover.classList.add('has-cover');img.onerror=()=>{img.remove();cover.classList.remove('has-cover');};cover.append(img);
    const key=book.path+'@'+book.cover.version;
    if(!coverLoads.has(key)&&!coverBlobs.has(key)){
      const promise=api('/api/books/cover?'+new URLSearchParams({path:book.path,v:book.cover.version})).then(r=>r.blob()).then(blob=>{
        const url=URL.createObjectURL(blob);coverBlobs.set(key,url);return url;
      }).finally(()=>coverLoads.delete(key));coverLoads.set(key,promise);
    }
    Promise.resolve(coverBlobs.get(key)||coverLoads.get(key)).then(url=>{if(img.isConnected)img.src=url;}).catch(()=>{img.remove();});
  }
  return cover;
}
const bookDialog=$('#book-detail-dialog');
const splitTags=value=>String(value||'').split(/[|｜]/).map(x=>x.trim()).filter(Boolean);
function wordNumber(value){const text=String(value||'').replace(/[,，\s]/g,'');const match=text.match(/\d+(?:\.\d+)?/);return match?Number(match[0])*(text.includes('亿')?1e8:text.includes('万')?1e4:1):0;}
function wordLabel(value){if(!value)return '字数未知';const number=wordNumber(value);return number>=10000?`${(number/10000).toFixed(1).replace(/\.0$/,'')} 万字`:`${number.toLocaleString('zh-CN')} 字`;}
function externalLink(label,url){try{const parsed=new URL(url);if(!['https:','http:'].includes(parsed.protocol))return null;const link=node('a',label,'source-link');link.href=parsed.href;link.target='_blank';link.rel='noopener noreferrer';return link;}catch{return null;}}
function filterOptions(id,values,label){const select=$(id),previous=select.value;select.replaceChildren();const all=node('option',label);all.value='';select.append(all);for(const value of [...new Set(values.filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh-CN'))){const option=node('option',value);option.value=value;select.append(option);}select.value=values.includes(previous)?previous:'';}
async function loadBooks(){
  const books=await json('/api/books');libraryBooks=books;
  filterOptions('#library-category',books.map(b=>b.category),'全部分类');
  filterOptions('#library-platform',books.map(b=>b.platform),'全部平台');
  $('#library-total').textContent=books.length;
  $('#library-text-total').textContent=books.filter(b=>b.text_path).length;
  $('#library-platform-total').textContent=new Set(books.map(b=>b.platform).filter(Boolean)).size;
  renderLibrary();
  const valid=new Set(books.map(b=>b.path+'@'+b.cover?.version));
  for(const [key,url] of coverBlobs){if(!valid.has(key)){URL.revokeObjectURL(url);coverBlobs.delete(key);}}
  if(detailBook&&bookDialog.open&&!$('#library-edit-form')){
    const latest=books.find(b=>b.path===detailBook.path);
    if(latest&&(JSON.stringify(latest.cover)!==JSON.stringify(detailBook.cover)||latest.cover_pending!==detailBook.cover_pending)){detailBook={...detailBook,cover:latest.cover,cover_pending:latest.cover_pending};renderBookDetail();}
  }
  clearTimeout(coverPoll);
  if(!$('#library').hidden&&books.some(b=>b.cover_pending))coverPoll=setTimeout(()=>loadBooks().catch(e=>notice(e.message,true)),1500);
}
function renderLibrary(){
  const query=$('#library-query').value.trim().toLocaleLowerCase(),category=$('#library-category').value,platform=$('#library-platform').value,status=$('#library-status').value;
  const books=libraryBooks.filter(b=>(!category||b.category===category)&&(!platform||b.platform===platform)&&(!status||(b.status||'未知')===status)&&(!query||[b.title,b.author,b.tags].join(' ').toLocaleLowerCase().includes(query)));
  const sort=$('#library-sort').value;
  books.sort((a,b)=>sort==='title'?a.title.localeCompare(b.title,'zh-CN'):sort==='words'?wordNumber(b.words)-wordNumber(a.words):(b.saved_on||'').localeCompare(a.saved_on||'')||a.title.localeCompare(b.title,'zh-CN'));
  $('#library-count').textContent=`显示 ${books.length} / ${libraryBooks.length} 本`;
  const list=$('#books');list.replaceChildren();
  if(!books.length){const empty=node('div',undefined,'library-empty');empty.append(node('h3',libraryBooks.length?'没有匹配的书籍':'书库还是空的'),node('p',libraryBooks.length?'换个关键词，或清除筛选条件。':'从帖子或截图开始整理，也可以手动添加书籍。'));list.append(empty);return;}
  for(const book of books){
    const card=node('article',undefined,'book-card');
    const top=node('div',undefined,'book-card-top'),cover=coverElement(book);
    const info=node('div',undefined,'book-card-info'),heading=node('h3'),open=node('button',book.title,'book-title');open.type='button';open.setAttribute('aria-label',`查看《${book.title}》详情`);open.onclick=()=>openBookDetail(book.path);heading.append(open);
    const meta=node('div',undefined,'book-meta');meta.append(node('span',book.status||'未知','book-state'),node('span',wordLabel(book.words)));
    info.append(heading,node('p',`${book.author||'作者未填写'} · ${book.platform||'平台未填写'}`,'book-author'),meta);
    top.append(cover,info);card.append(top,node('p',book.intro||'暂无简介，可在详情中补充。','book-excerpt'));
    const tags=node('div',undefined,'book-tags'),labels=splitTags(book.tags).filter(t=>t!==book.category);tags.append(node('span',book.category,'book-category'));for(const tag of labels.slice(0,4))tags.append(node('span',tag,'book-tag'));if(labels.length>4)tags.append(node('span',`+${labels.length-4}`,'book-tag'));card.append(tags);
    const bottom=node('div',undefined,'book-card-bottom');bottom.append(node('span',book.text_path?'正文已保存':'未保存正文',book.text_path?'saved-text':'muted-text'));
    const actions=node('div',undefined,'card-buttons'),detail=node('button','查看详情','quiet');detail.onclick=()=>openBookDetail(book.path);actions.append(detail);
    if(book.text_path){const read=node('button','阅读正文','quiet');read.onclick=()=>readBookText(book);actions.append(read);}
    bottom.append(actions);card.append(bottom);list.append(card);
  }
}
function openBookCreate(){$('#book-create-notice').hidden=true;if(!$('#book-create-dialog').open)$('#book-create-dialog').showModal();}
$('#add-library-book').onclick=()=>{$('#book-form').reset();clearLookup();openBookCreate();};
$('#book-create-close').onclick=()=>$('#book-create-dialog').close();
$('#book-detail-close').onclick=()=>bookDialog.close();
bookDialog.addEventListener('close',()=>{detailRequest++;detailBook=null;});
$('#book-reader-close').onclick=()=>$('#book-reader-dialog').close();
$('#library-query').addEventListener('input',renderLibrary);
for(const id of ['#library-category','#library-platform','#library-status','#library-sort'])$(id).onchange=renderLibrary;
$('#library-reset').onclick=()=>{for(const id of ['#library-query','#library-category','#library-platform','#library-status'])$(id).value='';$('#library-sort').value='updated';renderLibrary();};

async function openBookDetail(path){
  const request=++detailRequest;detailBook=null;
  $('#book-detail-title').textContent='正在读取资料…';$('#book-detail-subtitle').textContent='';$('#book-detail-category').textContent='';$('#book-detail-error').hidden=true;$('#book-detail-body').replaceChildren();$('#book-detail-actions').replaceChildren();
  if(!bookDialog.open)bookDialog.showModal();
  try{const book=await json('/api/books/detail?'+new URLSearchParams({path}));if(request!==detailRequest)return;detailBook=book;renderBookDetail();}
  catch(error){if(request===detailRequest){$('#book-detail-title').textContent='无法打开书籍';detailError(error.message);}}
}
function detailError(message){$('#book-detail-error').textContent=message;$('#book-detail-error').hidden=false;}
function detailSection(title,text){const section=node('section',undefined,'detail-section');section.append(node('h3',title),node('p',text,'detail-paragraph'));return section;}
function renderBookDetail(){
  const book=detailBook;$('#book-detail-error').hidden=true;$('#book-detail-title').textContent=book.title;$('#book-detail-category').textContent=book.category;
  $('#book-detail-subtitle').textContent=`${book.author||'作者未填写'} · ${book.platform||'平台未填写'}`;
  const body=$('#book-detail-body');body.replaceChildren();
  const coverPanel=node('section',undefined,'cover-panel'),coverTools=node('div',undefined,'cover-tools');
  coverPanel.append(coverElement(book,true));
  const state=book.cover_pending?'正在获取封面…':book.cover?.has_image?(book.cover.origin==='manual'?'手动封面 · 已保存在本地':'平台封面 · 已缓存，可离线查看'):'尚未缓存封面';
  coverTools.append(node('p',state,'help'));
  if(book.cover?.error)coverTools.append(node('p',book.cover.error+(book.cover.has_image?'，保留原封面。':''),'help'));
  const refresh=node('button',book.cover?.origin==='manual'?'恢复平台封面':book.cover?.has_image?'刷新封面':'获取封面','secondary');refresh.disabled=book.cover_pending||!book.url;
  refresh.onclick=async()=>{refresh.disabled=true;try{await post('/api/books/cover',{path:book.path,replace_manual:book.cover?.origin==='manual'});await loadBooks();}catch(error){detailError(error.message);refresh.disabled=false;}};
  const upload=node('button','上传封面','secondary'),file=node('input');file.type='file';file.accept='image/jpeg,image/png,image/webp,image/gif';file.hidden=true;file.setAttribute('aria-label','选择封面图片');upload.disabled=book.cover_pending;upload.onclick=()=>file.click();
  file.onchange=async()=>{const image=file.files[0];if(!image)return;if(image.size>8*1024*1024){detailError('请选择不超过 8 MB 的图片');return;}upload.disabled=true;try{await json('/api/books/cover',{method:'PUT',body:JSON.stringify({path:book.path,image:await asBase64(image)})});await loadBooks();}catch(error){detailError(error.message);upload.disabled=false;}};
  const controls=node('div',undefined,'actions');controls.append(refresh,upload,file);coverTools.append(controls);coverPanel.append(coverTools);body.append(coverPanel);
  const facts=node('dl',undefined,'detail-facts');for(const [name,value] of [['状态',book.status||'未知'],['篇幅',wordLabel(book.words)],['整理日期',book.saved_on||'未记录']]){const item=node('div');item.append(node('dt',name),node('dd',value));facts.append(item);}body.append(facts);
  const tags=node('div',undefined,'book-tags');for(const tag of splitTags(book.tags))tags.append(node('span',tag,'book-tag'));body.append(tags,detailSection('内容简介',book.intro||'暂无简介'),detailSection('我的评语',book.review&&book.review!=='【无】'?book.review:'尚未添加评语'));
  const source=detailSection('资料来源',book.source||'未记录'),links=node('div',undefined,'source-links');const original=externalLink('查看书籍原页 ↗',book.url);if(original)links.append(original);
  const provenance=book.provenance||{};
  const seen=new Set([book.url]);
  const sourceURL=String(book.source||'').match(/https?:\/\/[^\s]+/);
  if(sourceURL&&!seen.has(sourceURL[0])){const link=externalLink('查看推荐来源 ↗',sourceURL[0]);if(link)links.append(link);seen.add(sourceURL[0]);}
  for(const [key,label] of [['source_url','查看推荐原帖 ↗'],['original_url','查看原作 ↗']]){const url=provenance[key]||provenance.retrieved?.[key];if(url&&!seen.has(url)){const link=externalLink(label,url);if(link)links.append(link);seen.add(url);}}
  source.append(links);body.append(source);
  const actions=$('#book-detail-actions');actions.replaceChildren();
  const edit=node('button','编辑资料','secondary');edit.onclick=editBookDetail;
  const download=node('button','导出资料','secondary');download.onclick=()=>downloadBook(book.path,book.title+'.md');
  const chaptersButton=node('button',book.text_path?'更新章节':'获取章节','secondary');chaptersButton.onclick=()=>getBookChapters(book,chaptersButton);
  actions.append(edit,download,chaptersButton);
  if(book.text_path){const read=node('button','阅读已保存正文','primary');read.onclick=()=>readBookText(book);actions.append(read);const exportText=node('button','导出正文','quiet');exportText.onclick=()=>downloadBook(book.text_path,book.title+'.txt');actions.append(exportText);}
}
async function getBookChapters(book,button){
  if(/https:\/\/(?:www\.|wap\.)?(?:esjzone\.(?:one|cc)|ciweimao\.com)\//.test(book.url)){bookDialog.close();await chooseChapters(book);return;}
  button.disabled=true;button.textContent='正在获取…';$('#book-detail-error').hidden=true;
  try{const result=await post('/api/books/chapters',{path:book.path});await loadBooks();if(bookDialog.open&&detailBook?.path===book.path){detailBook=await json('/api/books/detail?'+new URLSearchParams({path:book.path}));renderBookDetail();}notice(`已保存 ${result.count} 章。${result.warnings.join('；')}`);}
  catch(error){if(bookDialog.open)detailError(error.message);else notice(error.message,true);button.disabled=false;button.textContent='重试获取章节';}
}
function editBookDetail(){
  const book=detailBook,body=$('#book-detail-body');body.replaceChildren();$('#book-detail-actions').replaceChildren();
  body.append(node('p','编辑此书的已保存资料，书名和分类保持不变。','help'));
  const form=node('form');form.id='library-edit-form';const grid=node('div',undefined,'form-grid');
  for(const [key,label] of [['author','作者'],['platform','平台'],['words','字数'],['status','状态'],['tags','标签（用 | 分隔）'],['source','整理来源'],['url','书籍链接'],['intro','内容简介'],['review','我的评语']]){
    const wrap=node('label',label),input=node(key==='status'?'select':['intro','review'].includes(key)?'textarea':'input');input.name=key;input.id='library-edit-'+key;wrap.htmlFor=input.id;
    if(key==='status'){for(const state of ['未知','连载中','完结']){const option=node('option',state);option.value=state;input.append(option);}}
    else if(['intro','review'].includes(key)){input.rows=key==='intro'?7:4;input.maxLength=key==='intro'?30000:10000;}
    else input.maxLength=({author:200,platform:100,words:30,tags:500,source:500,url:2000})[key];
    input.value=key==='status'?(['未知','连载中','完结'].includes(book.status)?book.status:'未知'):key==='review'&&book[key]==='【无】'?'':book[key]||'';wrap.append(input);if(['intro','review','url','tags'].includes(key))wrap.className='span-full';grid.append(wrap);
  }
  const actions=node('div',undefined,'actions'),save=node('button','保存修改','primary'),cancel=node('button','取消','secondary');save.type='submit';cancel.type='button';cancel.onclick=()=>{renderBookDetail();};actions.append(save,cancel);form.append(grid,actions);body.append(form);
  form.onsubmit=async event=>{
    event.preventDefault();save.disabled=true;cancel.disabled=true;$('#book-detail-error').hidden=true;
    const values=Object.fromEntries(new FormData(form));
    try{const updated=await json('/api/books/detail',{method:'PUT',body:JSON.stringify({path:book.path,revision:book.revision,book:{...values,title:book.title,category:book.category}})});await loadBooks();if(bookDialog.open&&detailBook?.path===book.path){detailBook=updated;renderBookDetail();}notice('书籍资料已更新。');}
    catch(error){if(bookDialog.open)detailError(error.message);save.disabled=false;cancel.disabled=false;}
  };
}
let readerRequest=0;
async function readBookText(book){
  const request=++readerRequest,dialog=$('#book-reader-dialog');$('#book-reader-title').textContent=book.title;$('#book-reader-note').textContent='正在打开已保存正文…';$('#book-reader-text').textContent='';if(!dialog.open)dialog.showModal();
  try{const response=await api('/api/books/download?'+new URLSearchParams({path:book.text_path}));const text=await response.text();if(request!==readerRequest)return;$('#book-reader-note').textContent='本地已保存内容';$('#book-reader-text').textContent=text;}
  catch(error){if(request===readerRequest)$('#book-reader-note').textContent=error.message;}
}
$('#book-reader-dialog').addEventListener('close',()=>readerRequest++);
$('#library-covers').onclick=async()=>{const button=$('#library-covers');button.disabled=true;try{const result=await post('/api/books/covers/missing');notice(result.queued?`正在补全 ${result.queued} 本书的封面。`:'没有需要补全的封面。');await loadBooks();}catch(error){notice(error.message,true);}finally{button.disabled=false;}};
