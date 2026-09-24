"""Official catalog queries, metadata normalization and author matching."""
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
import http.cookiejar
import threading
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup
from app.paths import add_tools
from app.esj_session import current_session, ESJSession, ESJError, HOSTS as ESJ_HOSTS

add_tools()
from direct_http import DirectFirst, urlopen
PLATFORMS = {
    'qidian': {'name':'起点中文网','search':True,'detail':True,'note':'使用官方移动页查询资料和公开免费章节。'},
    'ciweimao': {'name':'刺猬猫','search':True,'detail':True,'note':'支持书名搜索与详情；部分阅读页需要网页验证或登录。'},
    'sfacg': {'name': '菠萝包', 'search': True, 'detail': True},
    'fanqie': {'name': '番茄小说', 'search': True, 'detail': True,
               'note': '按书名查询番茄候选，可填写作者核对同名作品。'},
    'esj': {'name': 'ESJ Zone', 'search': True, 'detail': True,
            'note': '按书名搜索 ESJ 公开可见作品。当前匿名响应以原创分类为主。'},
}
HOSTS = {'m.sfacg.com', 'fanqienovel.com', 'www.fanqienovel.com', 'esjzone.one', 'www.esjzone.one',
         'esjzone.cc', 'www.esjzone.cc','m.qidian.com','www.qidian.com','book.qidian.com','www.ciweimao.com','wap.ciweimao.com'}
_site_clients=threading.local()

FANQIE_SEARCH = 'https://novel.snssdk.com/api/novel/channel/homepage/search/search/v1/'
ESJ_BASE = 'https://www.esjzone.one'


class ProviderError(ValueError):
    pass


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text or '').casefold() if c.isalnum())


def match(candidate, title, author=''):
    same_title = normalize(candidate['title']) == normalize(title)
    supplied_author, found_author = normalize(author), normalize(candidate.get('author'))
    if supplied_author and found_author and supplied_author != found_author:
        state, reason = 'author_conflict', '作者不同，不能确认同一本书'
    elif same_title and supplied_author and found_author == supplied_author:
        state, reason = 'exact', '书名与作者一致'
    elif same_title:
        state, reason = 'title_only', '书名一致，作者尚未核对'
    else:
        state, reason = 'possible', '近似书名，需要确认'
    return dict(candidate, match=state, match_reason=reason,
                similarity=round(SequenceMatcher(None, normalize(title), normalize(candidate['title'])).ratio(), 3))


def record(platform, book_id, title, url, **fields):
    fetched = datetime.now(timezone.utc).isoformat()
    result = {'platform': platform, 'platform_label': PLATFORMS[platform]['name'], 'book_id': str(book_id),
              'title': title, 'author': '', 'word_count': None, 'status': '未知', 'tags': [], 'intro': '',
              'url': url, 'original_url': '', 'fetched_at': fetched, **fields}
    method = 'platform_api' if platform == 'sfacg' else 'public_html'
    session = current_session.get()
    if platform == 'esj' and session and session.connected:
        method = 'session_html'
    result['field_sources'] = {key: {'url': url, 'method': method, 'fetched_at': fetched}
        for key in ('title', 'author', 'word_count', 'tags', 'intro', 'original_url','cover_url')
        if result.get(key) not in (None, '', [])}
    if result['status'] != '未知':
        result['field_sources']['status'] = {'url': url, 'method': method, 'fetched_at': fetched}
    return result


def resolve_url(url):
    try:
        parsed = urllib.parse.urlsplit(url.strip())
        port = parsed.port
    except ValueError:
        raise ProviderError('书籍链接格式无效') from None
    if parsed.scheme != 'https' or parsed.username or parsed.password or port not in (None, 443):
        raise ProviderError('请使用支持站点的 HTTPS 书籍链接')
    host, path = (parsed.hostname or '').lower(), parsed.path
    if host in ('qidian.com','www.qidian.com','book.qidian.com','m.qidian.com'):
        match=re.fullmatch(r'/(?:book|info)/(\d+)/?',path)
        if match:return 'qidian',match[1],f'https://m.qidian.com/book/{match[1]}/','detail'
    if host in ('ciweimao.com','www.ciweimao.com','wap.ciweimao.com','www.hbooker.com'):
        match=re.fullmatch(r'/book/(\d+)/?',path)
        if match:return 'ciweimao',match[1],f'https://www.ciweimao.com/book/{match[1]}','detail'
    if host in ('book.sfacg.com', 'www.book.sfacg.com'):
        m = re.fullmatch(r'/novel/(\d+)/?', path, re.I)
        if m:
            return 'sfacg', m[1], f'https://book.sfacg.com/novel/{m[1]}/', 'detail'
    elif host in ('fanqienovel.com', 'www.fanqienovel.com'):
        m = re.fullmatch(r'/(page|reader)/(\d+)/?', path)
        if m:
            return 'fanqie', m[2], f'https://fanqienovel.com/{m[1]}/{m[2]}', m[1]
    elif host in ('esjzone.one', 'www.esjzone.one', 'esjzone.cc', 'www.esjzone.cc'):
        m = re.fullmatch(r'/detail/(\d+)\.html', path)
        if m:
            return 'esj', m[1], f'https://{host}{path}', 'detail'
    raise ProviderError('暂不支持此链接；支持起点、刺猬猫、菠萝包、番茄及 ESJ 书籍详情链接')


def validate_fetch_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or p.hostname not in HOSTS or p.username or p.password or p.port not in (None, 443):
        raise ProviderError('站点重定向到不支持的地址，已停止请求')


class SiteRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_fetch_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_html(url):
    validate_fetch_url(url)
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html'})
    try:
        session = current_session.get()
        if urllib.parse.urlsplit(url).hostname in ESJ_HOSTS:
            body = (session or ESJSession()).fetch(request)
        else:
            opener=DirectFirst(SiteRedirect())
            if urllib.parse.urlsplit(url).hostname in ('www.ciweimao.com','wap.ciweimao.com'):
                if not hasattr(_site_clients,'ciweimao'):
                    _site_clients.ciweimao=DirectFirst(SiteRedirect(),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                    with _site_clients.ciweimao.open(urllib.request.Request('https://www.ciweimao.com/',headers={'User-Agent':'Mozilla/5.0'}),timeout=20) as landing:landing.read()
                opener=_site_clients.ciweimao
                request.add_header('Referer','https://www.ciweimao.com/')
            with opener.open(request, timeout=20) as response:
                body = response.read(4_000_001)
        if len(body) > 4_000_000:
            raise ProviderError('页面超过解析大小限制')
        text = body.decode('utf-8')
    except ESJError as exc:
        raise ProviderError(str(exc)) from None
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 429):
            raise ProviderError(f'站点限制访问（HTTP {exc.code}），请稍后重试或手动填写') from None
        raise ProviderError(f'站点请求失败（HTTP {exc.code}）') from None
    except (urllib.error.URLError, TimeoutError, UnicodeError):
        raise ProviderError('站点连接失败或未返回可解析页面') from None
    return text


def initial_state(html):
    marker = 'window.__INITIAL_STATE__='
    if marker not in html:
        raise ProviderError('页面没有书籍数据，可能需要登录或页面结构已变化')
    try:
        return json.JSONDecoder().raw_decode(html.split(marker, 1)[1].lstrip())[0]
    except (ValueError, TypeError):
        raise ProviderError('页面内嵌数据格式已变化') from None


def parse_fanqie(html, book_id, url):
    page = initial_state(html).get('page') or {}
    if not page.get('bookName') or str(page.get('bookId')) != str(book_id):
        raise ProviderError('页面未返回对应书籍详情')
    try:
        categories = json.loads(page.get('categoryV2') or '[]')
    except (ValueError, TypeError):
        categories = []
    soup = BeautifulSoup(html, 'html.parser')
    status_node = soup.select_one('.info-label-yellow')
    visible = status_node.get_text(strip=True) if status_node else ''
    # Only an explicit visible status is used; numeric undocumented enums are not guessed.
    status = '连载中' if visible == '连载中' else ('完结' if visible in ('已完结', '完结') else '未知')
    return record('fanqie', book_id, page['bookName'], url, author=page.get('author') or '',
        word_count=page.get('wordNumber') or None, status=status,
        tags=[c['Name'] for c in categories if isinstance(c, dict) and c.get('Name')],
        intro=page.get('abstract') or '', cover_url=page.get('thumbUri') or '')


def parse_esj(html, book_id, url):
    soup = BeautifulSoup(html, 'html.parser')
    heading = soup.select_one('.book-detail h2')
    if heading is None:
        session = current_session.get()
        if session and session.connected:
            raise ProviderError('ESJ 已登录，但未返回此作品详情。'+(session.access_notice or '作品可能受限、已下架或页面结构已变化。'))
        raise ProviderError('未读到公开书籍详情；页面可能受限、已下架或结构已变化')
    values = {}
    for item in soup.select('ul.book-detail > li'):
        label = item.find('strong')
        if label:
            key = label.get_text(strip=True).rstrip(':：')
            values[key] = item.get_text(' ', strip=True).split(label.get_text(strip=True), 1)[-1].strip()
    original = ''
    for item in soup.select('ul.book-detail > li'):
        if any(x in item.get_text() for x in ('Web生肉', '原作', '原文')):
            link = item.select_one('a[href]')
            if link and urllib.parse.urlsplit(link['href']).scheme in ('http', 'https'):
                original = link['href']
                break
    count = soup.select_one('#txt')
    count_text = count.get_text(strip=True).replace(',', '') if count else ''
    description = soup.select_one('.description')
    tags = list(dict.fromkeys(a.get_text(strip=True) for a in soup.select('.widget-tags a.tag')))
    cover=soup.select_one('.product-gallery img,.book-cover img')
    cover_url=urllib.parse.urljoin(url,cover.get('data-src') or cover.get('src','')) if cover else ''
    return record('esj', book_id, heading.get_text(strip=True), url, author=values.get('作者', ''),
        word_count=int(count_text) if count_text.isdigit() else None, tags=tags,
        intro=description.get_text('\n', strip=True) if description else '', original_url=original,
        updated_at=values.get('更新日期', ''), kind=values.get('類型', ''),cover_url=cover_url)


def detail(url):
    platform, book_id, canonical, kind = resolve_url(url)
    if platform == 'sfacg':
        from fetch_novel_fields import fetch_novel, extract_fields
        try:
            raw = fetch_novel(int(book_id))
            data = extract_fields(raw)
        except Exception:
            raise ProviderError('菠萝包详情接口暂不可用') from None
        status = data['status'] if isinstance(raw.get('isFinish'), bool) else '未知'
        return record(platform, book_id, data['novelName'], canonical, author=data['authorName'] or '',
            word_count=raw.get('charCount'), status=status, tags=data['tags'], intro=data['intro'],cover_url=raw.get('novelCover') or '')
    html = fetch_html(canonical)
    if platform in ('qidian','ciweimao'):
        from app import mainland
        return getattr(mainland,platform+'_detail')(html,book_id,canonical)
    if platform == 'fanqie':
        if kind == 'reader':
            book_id = str(initial_state(html).get('reader', {}).get('chapterData', {}).get('bookId', ''))
            if not book_id.isdigit():
                raise ProviderError('阅读页未提供书籍 ID，请粘贴书籍详情链接')
            canonical = f'https://fanqienovel.com/page/{book_id}'
            html = fetch_html(canonical)
        return parse_fanqie(html, book_id, canonical)
    return parse_esj(html, book_id, canonical)


def search_one(platform, title, author='', page=0):
    if platform not in PLATFORMS:
        raise ProviderError('不支持的平台')
    if not PLATFORMS[platform]['search']:
        return {'items': [], 'warnings': [PLATFORMS[platform]['note']],
                'external_search_url': ''}
    if platform in ('qidian','ciweimao'):
        from app import mainland
        candidates=[match(item,title,author) for item in getattr(mainland,platform+'_search')(title,page)]
    elif platform == 'fanqie':
        candidates = [match(item, title, author) for item in search_fanqie(title, page)]
    elif platform == 'esj':
        response = search_esj(title, page)
        candidates = [match(item, title, author) for item in response['items']]
        warnings = response['warnings']
    else:
        from search_novel import search_by_name
        try:
            items = search_by_name(title, page=page)
        except Exception:
            raise ProviderError('菠萝包搜索接口暂不可用') from None
        candidates = [match(record('sfacg', row['novelId'], row.get('novelName') or '',
                       f'https://book.sfacg.com/novel/{row["novelId"]}/', author=row.get('authorName') or ''), title, author)
                      for row in items if row.get('novelId') and row.get('novelName')]
    order = {'exact': 0, 'title_only': 1, 'possible': 2, 'author_conflict': 3}
    candidates.sort(key=lambda c: (order[c['match']], -c['similarity']))
    return {'items': candidates, 'warnings': warnings if platform == 'esj' else [], 'external_search_url': ''}


def parse_esj_search(html, search_url):
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    for card in soup.select('.card-body'):
        link = card.select_one('.card-title a[href]')
        if not link:
            continue
        found = re.fullmatch(r'/detail/(\d+)\.html', link['href'])
        if not found:
            continue
        author = card.select_one('.card-author')
        author_text = re.sub(r'^作者\s*[:：]?\s*', '', author.get_text(' ', strip=True)) if author else ''
        count = card.select_one('.icon-file-text')
        count_text = count.parent.get_text(strip=True).replace(',', '') if count else ''
        item = record('esj', found[1], link.get_text(' ', strip=True), ESJ_BASE+link['href'],
            author=author_text, word_count=int(count_text) if count_text.isdigit() else None)
        for source in item['field_sources'].values():
            source['url'] = search_url
        results.append(item)
    warnings = []
    if not results and soup.title and '原創' in soup.title.get_text():
        warnings.append('本次公开响应范围为“原创”，没有返回候选；这不代表翻译作品不存在。')
    return {'items': results, 'warnings': warnings}


def search_esj(title, page=0):
    """ESJ's /tags/{keyword}/{page}.html search used by open-source clients."""
    url = ESJ_BASE+'/tags/'+urllib.parse.quote(title, safe='')+f'/{page+1}.html'
    html = fetch_html(url)
    result = parse_esj_search(html, url)
    session = current_session.get()
    if session and session.connected and session.access_notice:
        result['warnings'].append(session.access_notice)
    return result


def search_fanqie(title, page=0):
    """Query the public mobile book search endpoint."""
    params = {'device_platform': 'android', 'parent_enterfrom': 'novel_channel_search.tab.',
              'offset': page * 10, 'aid': 1967, 'q': title}
    url = FANQIE_SEARCH + '?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
        if payload.get('code') != 0:
            raise ProviderError(f'番茄搜索失败：{payload.get("message", "未知错误")}')
        rows = payload['data']['ret_data']
    except (urllib.error.URLError, TimeoutError):
        raise ProviderError('番茄搜索请求失败，请稍后重试') from None
    except (ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, ProviderError):
            raise
        raise ProviderError('番茄搜索响应格式变化') from None
    result = []
    for row in rows:
        book_id = str(row['book_id'])
        name = BeautifulSoup(row['title'], 'html.parser').get_text()
        item = record('fanqie', book_id, name, f'https://fanqienovel.com/page/{book_id}',
                      author=row.get('author') or '', intro=row.get('abstract') or '',
                      tags=[row['category']] if row.get('category') else [])
        for source in item['field_sources'].values():
            source.update(method='platform_api', url=url)
        result.append(item)
    return result


def search(platform, title, author='', page=0):
    if platform != 'all':
        return search_one(platform, title, author, page)
    merged = {'items': [], 'warnings': [], 'external_search_url': ''}
    for key in PLATFORMS:
        try:
            response = search_one(key, title, author, page)
            merged['items'].extend(response['items'])
            merged['warnings'].extend(response['warnings'])
        except ProviderError as exc:
            merged['warnings'].append(str(exc))
    return merged
