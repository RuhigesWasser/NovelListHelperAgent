"""An ESJ login session held in RAM only. No cookie or credential files."""
from contextlib import contextmanager
from contextvars import ContextVar
import http.cookiejar
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup


BASE = 'https://www.esjzone.one'
HOSTS = {'www.esjzone.one', 'esjzone.one'}
current_session = ContextVar('esj_session', default=None)


class ESJError(ValueError):
    pass


class ESJRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != 'https' or target.hostname not in HOSTS:
            raise ESJError('ESJ 登录请求重定向到其他站点，已停止')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ESJSession:
    def __init__(self):
        self.lock = threading.RLock()
        self.clear()

    def clear(self):
        with self.lock:
            self.jar = http.cookiejar.CookieJar()
            self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), ESJRedirect(), urllib.request.HTTPCookieProcessor(self.jar))
            self.proxy_opener = None
            self.connected = False
            self.access_notice = ''

    def _request(self, request):
        try:
            with self.opener.open(request, timeout=15) as response:
                return response.read(4_000_001)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            # Authentication/permission failures are not connection failures.
            if isinstance(exc, urllib.error.HTTPError) and exc.code < 500:
                raise
            proxies = urllib.request.getproxies()
            if not proxies.get(urllib.parse.urlsplit(request.full_url).scheme):
                raise
        if self.proxy_opener is None:
            self.proxy_opener = urllib.request.build_opener(urllib.request.ProxyHandler(), ESJRedirect(), urllib.request.HTTPCookieProcessor(self.jar))
        with self.proxy_opener.open(request, timeout=45) as response:
            return response.read(4_000_001)

    def login(self, email, password):
        candidate = ESJSession()
        headers = {'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                   'Referer': BASE+'/my/login', 'Origin': BASE}
        try:
            request = urllib.request.Request(BASE+'/my/login', data=b'plxf=getAuthToken', headers=headers)
            token = re.search(r'<JinJing>(.*?)</JinJing>', candidate._request(request).decode('utf-8'), re.S)
            if not token:
                raise ESJError('ESJ 未返回登录令牌')
            # No remember_me; neither submitted credentials nor cookies are serialized.
            request = urllib.request.Request(BASE+'/inc/mem_login.php',
                data=urllib.parse.urlencode({'email': email, 'pwd': password}).encode(),
                headers={**headers, 'Authorization': token[1]})
            result = json.loads(candidate._request(request))
            if result.get('status') not in (200,301):
                raise ESJError('ESJ 未接受登录，请核对账号或网站验证要求')
            home = BeautifulSoup(candidate._request(urllib.request.Request(BASE+'/',headers={'User-Agent':'Mozilla/5.0'})).decode('utf-8'),'html.parser')
            if not home.select_one('a[href="/my/logout"]'):
                raise ESJError('ESJ 未建立有效登录态，请在网站确认账号状态')
            notice = '站点要求先在水楼留言才能查看更多小说，部分作品仍不可读。' if '水樓' in result.get('msg','') and '留言' in result.get('msg','') else ''
        except (urllib.error.URLError, TimeoutError):
            raise ESJError('ESJ 登录连接失败，请稍后重试') from None
        except (UnicodeError, json.JSONDecodeError):
            raise ESJError('ESJ 未返回有效登录响应') from None
        with self.lock:
            self.jar, self.opener, self.connected = candidate.jar, candidate.opener, True
            self.proxy_opener = candidate.proxy_opener
            self.access_notice = notice
        return {'connected': True, 'storage': 'memory_only', 'access_notice':notice}

    @contextmanager
    def scope(self):
        marker = current_session.set(self)
        try:
            yield
        finally:
            current_session.reset(marker)

    def fetch(self, request):
        with self.lock:
            return self._request(request)
