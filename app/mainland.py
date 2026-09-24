"""Qidian and Ciweimao adapters for their publicly served website data."""
import json
import re
from urllib.parse import quote,urljoin,urlsplit
from bs4 import BeautifulSoup
from app import providers


def page_data(html):
    soup=BeautifulSoup(html,'html.parser')
    script=soup.select_one('#vite-plugin-ssr_pageContext')
    if not script:raise providers.ProviderError('起点没有返回书籍数据，可能需要浏览器验证或页面已变化')
    try:return json.loads(script.string or script.text)['pageContext']['pageProps']['pageData']
    except (ValueError,KeyError,TypeError):raise providers.ProviderError('起点页面数据结构已变化') from None


def status(value):
    return '完结' if value in ('已完结','完本','完结') else ('连载中' if value in ('连载','连载中') else '未知')


def plain(value):
    return BeautifulSoup(value or '', 'html.parser').get_text('\n',strip=True)


def qidian_detail(html,book_id,url):
    page=page_data(html)
    data=page.get('bookInfo') or {}
    if str(data.get('bookId'))!=book_id or not data.get('bookName'):raise providers.ProviderError('起点详情与书籍 ID 不一致')
    soup=BeautifulSoup(html,'html.parser')
    image=soup.select_one('meta[property="og:image"]')
    cover_url=urljoin(url,image['content']) if image else ''
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            for value in json.loads(script.text).get('@graph',[]):
                if value.get('@type')=='Book' and str((value.get('identifier') or {}).get('value'))==book_id and isinstance(value.get('image'),str):cover_url=urljoin(url,value['image'])
        except (ValueError,TypeError,AttributeError):continue
    return providers.record('qidian',book_id,data['bookName'],url,author=data.get('authorName') or '',
        intro=plain(data.get('desc')),word_count=data.get('wordsCnt'),status=status(data.get('bookStatus')),
        tags=list(dict.fromkeys([x for x in (data.get('chanName'),data.get('subCateName')) if x]+[x['tag'] for x in data.get('bookLabels',[]) if x.get('tag')]+[x.get('tagName') or x['TagName'] for x in (page.get('bookExtra') or {}).get('ugcTagInfos',[]) if x.get('tagName') or x.get('TagName')])),
        cover_url=cover_url)


def qidian_search(title,page=0):
    url='https://m.qidian.com/soushu/'+quote(title,safe='')+'.html?pageNum='+str(page+1)
    data=page_data(providers.fetch_html(url))
    info=data.get('bookInfo')
    if not isinstance(info,dict) or not isinstance(info.get('records'),list):raise providers.ProviderError('起点未返回搜索结果列表')
    result=[]
    for row in info['records']:
        identifier=str(row.get('bid',''))
        if not identifier.isdigit() or not row.get('bName'):continue
        book=providers.record('qidian',identifier,row['bName'],f'https://m.qidian.com/book/{identifier}/',
            author=row.get('bAuth') or '',intro=plain(row.get('desc')),status=status(row.get('state')),
            tags=[row['cat']] if row.get('cat') else [])
        for field in book['field_sources'].values():field['url']=url
        result.append(book)
    return result


def check_ciweimao(soup):
    if soup.title and soup.title.get_text(strip=True) in ('验证码 - 刺猬猫','验证'):
        raise providers.ProviderError('刺猬猫要求网页验证，当前未取得内容；请打开来源链接在浏览器查看。')


def ciweimao_detail(html,book_id,url):
    soup=BeautifulSoup(html,'html.parser');check_ciweimao(soup)
    def meta(name):
        node=soup.find('meta',attrs={'property':name})
        return node.get('content','') if node else ''
    title=meta('og:novel:book_name')
    identity=meta('og:novel:read_url')
    if not title or not re.search(r'/book/'+re.escape(book_id)+r'/?$',identity):raise providers.ProviderError('刺猬猫没有返回对应书籍详情')
    text=soup.select_one('.book-grade');words=None
    if text:
        match=re.search(r'总字数[：:]\s*([\d,]+)',text.get_text(' ',strip=True))
        if match:words=int(match[1].replace(',',''))
    state=soup.select_one('.update-state')
    description=soup.select_one('.book-desc')
    return providers.record('ciweimao',book_id,title,url,author=meta('og:novel:author'),word_count=words,
        intro=description.get_text('\n',strip=True) if description else meta('og:description'),
        status=status(state.get_text(strip=True).split('·')[0]) if state else '未知',
        tags=list(dict.fromkeys(x.get_text(strip=True) for x in soup.select('.book-info .label-box .label'))),cover_url=meta('og:image'))


def ciweimao_search(title,page=0):
    query=re.split(r'…|\.{3}',title,maxsplit=1)[0].strip() or title
    url='https://www.ciweimao.com/get-search-book-list/0-0-0-0-0-0/'+quote('全部')+'/'+quote(query,safe='')+'/'+str(page+1)
    soup=BeautifulSoup(providers.fetch_html(url),'html.parser');check_ciweimao(soup)
    result=[];seen=set()
    for link in soup.select('.cnt .tit a[href]'):
        match=re.fullmatch(r'/book/(\d+)/?',urlsplit(link['href']).path)
        if not match or match[1] in seen:continue
        seen.add(match[1]);card=link.find_parent(class_='cnt')
        author=card.select_one('a[href*="/reader/"]');intro=card.select_one('.desc')
        book=providers.record('ciweimao',match[1],link.get('title') or link.get_text(strip=True),f'https://www.ciweimao.com/book/{match[1]}',
            author=author.get_text(strip=True) if author else '',intro=intro.get_text('\n',strip=True) if intro else '')
        for field in book['field_sources'].values():field['url']=url
        result.append(book)
    if not result and not soup.select('input[name="keyword"]'):raise providers.ProviderError('刺猬猫未返回可解析的搜索页面')
    return result


def qidian_catalog(book_id):
    url=f'https://m.qidian.com/book/{book_id}/catalog/'
    data=page_data(providers.fetch_html(url))
    if str(data.get('bookId'))!=book_id:raise providers.ProviderError('起点目录与书籍 ID 不一致')
    entries=[]
    for volume in data.get('vs',[]):
        if str(volume.get('vS'))!='0':continue
        for chapter in volume.get('cs',[]):
            if str(chapter.get('sS'))!='1':continue
            identifier=str(chapter.get('id',''))
            if identifier.isdigit():entries.append({'title':chapter['cN'],'url':f'https://m.qidian.com/chapter/{book_id}/{identifier}/',
                'book_id':book_id,'chapter_id':identifier,'group':volume.get('vN',''),'kind':'免费章节'})
    if not entries:raise providers.ProviderError('起点未返回公开免费章节')
    return entries


def ciweimao_catalog(book_id):
    url=f'https://wap.ciweimao.com/book/{book_id}'
    soup=BeautifulSoup(providers.fetch_html(url),'html.parser');check_ciweimao(soup)
    entries=[];seen=set()
    start=next((a.get('href','') for a in soup.select('a[href]') if a.get_text(strip=True)=='立即阅读'),'')
    for link in soup.select('.catalogue-list a[href]'):
        target=urljoin(url,link['href']);parsed=urlsplit(target)
        match=re.fullmatch(r'/chapter/(\d+)/?',parsed.path)
        if parsed.hostname!='wap.ciweimao.com' or not match or target in seen:continue
        title=link.get_text(strip=True)
        if link.select_one('.icon-lock,.icon-lock2') or re.search(r'VIP|付费',title,re.I):continue
        seen.add(target);heading=link.find_previous('h2')
        entries.append({'title':title,'url':target,'book_id':book_id,'chapter_id':match[1],
            'group':heading.get_text(strip=True) if heading else '', 'recommended_start':target==start})
    if not entries:raise providers.ProviderError('刺猬猫未返回章节目录')
    return entries


def suggested(platform,entries):
    if platform=='ciweimao':
        first=next((i for i,e in enumerate(entries) if e.get('recommended_start')),None)
        if first is None:return [],'目录含设定或番外，请选择要读取的正文条目'
        return entries[first:first+3],'从网站“立即阅读”指向的正文开始选择，跳过前置设定与番外'
    return entries[:3],'按公开免费目录选择前 3 章'


def chapter(platform,entry):
    html=providers.fetch_html(entry['url'])
    if platform=='qidian':
        data=page_data(html);info=data.get('chapterInfo') or {}
        if str(data.get('bookInfo',{}).get('bookId'))!=entry['book_id'] or str(info.get('chapterId'))!=entry['chapter_id']:raise providers.ProviderError('起点章节与所选目录不一致')
        if str(info.get('vipStatus'))!='0' or float(info.get('price') or 0)>0:raise providers.ProviderError('该章不是公开免费章节')
        body=plain(info.get('content'))
        if not body or (info.get('riskbe') or {}).get('be'):raise providers.ProviderError('起点未返回可读章节正文')
        return body
    soup=BeautifulSoup(html,'html.parser');check_ciweimao(soup)
    if soup.select_one('.chapter-vip,.paywall'):raise providers.ProviderError('刺猬猫章节需要登录或订阅')
    node=soup.select_one('#J_BookCnt .read-body, .read-body, #J_BookCnt')
    if not node:raise providers.ProviderError('刺猬猫未返回公开正文，可能需要网页验证或登录')
    for child in node.select('script,style,.chapter-author-say,button'):child.decompose()
    body=node.get_text('\n',strip=True)
    if re.search(r'订阅本章|购买本章|请先登录|登录后阅读',body):raise providers.ProviderError('刺猬猫章节需要登录或订阅')
    if not body:raise providers.ProviderError('刺猬猫章节正文为空')
    return body
