"""Public chapter excerpts. Catalog order and source URLs are preserved."""
from datetime import datetime, timezone
import json
import uuid
import re
from app.paths import replace_file
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from app import providers
from app.fanqie_text import decode
from app import esj_catalog


def catalog(url):
    platform, book_id, canonical, _ = providers.resolve_url(url)
    if platform in ('qidian','ciweimao'):
        from app import mainland
        return platform,getattr(mainland,platform+'_catalog')(book_id)
    if platform == 'fanqie':
        if '/reader/' in canonical:
            book_id = providers.initial_state(providers.fetch_html(canonical))['reader']['chapterData']['bookId']
            canonical = f'https://fanqienovel.com/page/{book_id}'
        page = providers.initial_state(providers.fetch_html(canonical)).get('page', {})
        entries = []
        for volume in page.get('chapterListWithVolume', []):
            for chapter in volume:
                if chapter.get('needPay') or chapter.get('isChapterLock') or chapter.get('isPaidPublication') or chapter.get('isPaidStory'):
                    continue
                entries.append({'title': chapter['title'], 'url': f'https://fanqienovel.com/reader/{chapter["itemId"]}',
                                'book_id': str(book_id), 'chapter_id': str(chapter['itemId'])})
        if not entries:
            raise providers.ProviderError('番茄页面没有公开免费章节目录')
        return platform, entries
    catalog_url = f'https://m.sfacg.com/i/{book_id}/' if platform == 'sfacg' else canonical
    html = providers.fetch_html(catalog_url)
    if platform == 'esj':
        entries = esj_catalog.parse(html,catalog_url,book_id)
        if not entries:
            raise providers.ProviderError('没有读到 ESJ 章节目录；未登录或账号权限不足时可能无法访问')
        return platform, entries
    soup = BeautifulSoup(html, 'html.parser')
    entries, seen = [], set()
    for link in soup.select('.mulu_list a[href]' if platform == 'sfacg' else '#chapterList a[href]'):
        target = urljoin(catalog_url, link['href'])
        parsed = urlsplit(target)
        pattern = r'/c/\d+/' if platform == 'sfacg' else rf'/forum/{book_id}/\d+\.html'
        if parsed.hostname != urlsplit(catalog_url).hostname or not re.fullmatch(pattern, parsed.path):
            continue
        title = link.get_text(' ', strip=True)
        if target in seen or link.select_one('.icon-lock2') or 'VIP' in title.upper():
            continue
        seen.add(target)
        entries.append({'title': title, 'url': target})
    if not entries:
        raise providers.ProviderError('没有找到公开章节目录，页面可能需要登录')
    return platform, entries


def read_chapter(platform, entry):
    if platform in ('qidian','ciweimao'):
        from app import mainland
        return {**entry,'content':mainland.chapter(platform,entry),'fetched_at':datetime.now(timezone.utc).isoformat(),'method':'public_html'}
    html = providers.fetch_html(entry['url'])
    if platform == 'fanqie':
        data = providers.initial_state(html).get('reader', {}).get('chapterData', {})
        if str(data.get('itemId')) != entry['chapter_id'] or str(data.get('bookId')) != entry['book_id']:
            raise providers.ProviderError('番茄页面未返回对应章节')
        if data.get('needPay') or data.get('isChapterLock') or data.get('isPaidPublication') or data.get('isPaidStory'):
            raise providers.ProviderError('该章不是公开免费正文')
        content = BeautifulSoup(data.get('content', ''), 'html.parser')
        text = '\n\n'.join(p.get_text('', strip=True) for p in content.select('p') if p.get_text(strip=True))
        if not text:
            raise providers.ProviderError('番茄章节正文为空')
        return {**entry, 'content': decode(text, html), 'fetched_at': datetime.now(timezone.utc).isoformat(),
                'method': 'public_html_font_mapping'}
    soup = BeautifulSoup(html, 'html.parser')
    if platform == 'sfacg' and '本章为VIP章节' in soup.get_text():
        raise providers.ProviderError('该章不是公开免费正文')
    content = soup.select_one('.yuedu.Content_Frame' if platform == 'sfacg' else '.forum-content')
    if not content:
        raise providers.ProviderError('没有读到章节正文，可能需要登录或页面结构已变化')
    for element in content.select('script,style,iframe,button,.ad'):
        element.decompose()
    if platform == 'sfacg':
        paragraphs = content.select('p')
        text = '\n\n'.join(p.get_text('', strip=True) for p in paragraphs if p.get_text(strip=True))
    else:
        text = content.get_text('\n', strip=True)
    if not text:
        raise providers.ProviderError('章节正文为空')
    return {**entry, 'content': text, 'fetched_at': datetime.now(timezone.utc).isoformat()}


def preview(url, limit=3, selected_urls=None):
    platform, entries = catalog(url)
    selection_note = ''
    if selected_urls is not None:
        by_url={e['url']:e for e in entries}
        if not selected_urls or len(set(selected_urls))!=len(selected_urls) or any(u not in by_url for u in selected_urls):
            raise providers.ProviderError('请选择本书目录中的不同章节')
        selected=set(selected_urls)
        chosen=[entry for entry in entries if entry['url'] in selected]
        selection_note='用户选择的目录条目'
    elif platform=='ciweimao':
        from app.mainland import suggested
        chosen,selection_note=suggested(platform,entries)
        if not chosen:raise providers.ProviderError(selection_note)
    elif platform=='esj':
        chosen,selection_note=esj_catalog.recommend(entries,limit)
        if not chosen:raise providers.ProviderError(selection_note)
    else:chosen=entries[:limit]
    chapters, warnings = [], []
    positions={entry['url']:index for index,entry in enumerate(entries)}
    for entry in chosen:
        try:
            chapters.append({**read_chapter(platform, entry),'catalog_order':positions[entry['url']]})
        except providers.ProviderError as exc:
            warnings.append(f'{entry["title"]}（{entry["url"]}）：{exc}')
    if not chapters:
        raise providers.ProviderError('；'.join(warnings) or '未获取到免费正文')
    return {'chapters': chapters, 'warnings': warnings, 'requested': len(chosen),
            'order': selection_note or '网站目录顺序', 'book_url': url,
            'catalog_urls':[entry['url'] for entry in entries]}


def saved(target):
    structured=target.with_suffix('.chapters.json')
    if structured.is_file():
        return json.loads(structured.read_text(encoding='utf8'))
    text_file=target.with_suffix('.txt')
    if not text_file.is_file():return {'chapters':[]}
    text=text_file.read_text(encoding='utf8')
    matches=list(re.finditer(r'^([^\n]+)\n来源：(https?://[^\s]+)\n',text,re.M))
    entries=[]
    for index,match in enumerate(matches):
        end=matches[index+1].start() if index+1<len(matches) else len(text)
        entries.append({'title':match[1],'url':match[2],'content':text[match.end():end].strip()})
    if not entries:entries=[{'title':'已保存正文','url':'','content':text}]
    return {'chapters':entries}


def save(target,result):
    previous=saved(target)
    merged={entry.get('url') or entry['title']:entry for entry in previous['chapters']}
    merged.update({entry.get('url') or entry['title']:entry for entry in result['chapters']})
    positions={url:index for index,url in enumerate(result.get('catalog_urls',[]))}
    for entry in merged.values():
        if entry.get('url') in positions:entry['catalog_order']=positions[entry['url']]
    entries=sorted(merged.values(),key=lambda entry:entry.get('catalog_order',10**9))
    combined={**result,'chapters':entries}
    content='\n\n'.join(f'{c["title"]}\n来源：{c.get("url", "")}\n\n{c["content"]}' for c in entries)
    for suffix,body in (('.chapters.json',json.dumps(combined,ensure_ascii=False,indent=2)),('.txt',content)):
        destination=target.with_suffix(suffix)
        temporary=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(body,encoding='utf8');replace_file(temporary,destination)
    return combined
