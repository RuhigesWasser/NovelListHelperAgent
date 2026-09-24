"""Local cover storage and platform URL refresh."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime,timezone
import hashlib
import io
import ipaddress
import json
from pathlib import Path
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from PIL import Image,ImageOps,UnidentifiedImageError
from app import library,providers
from app.paths import replace_file
from direct_http import DirectFirst

MAX_BYTES=8*1024*1024
IMAGE_HOSTS=('bookcover.yuewen.com','rss.sfacg.com','rs.sfacg.com','byteimg.com','kuangxiangit.com','telegra.ph','esjzone.one','esjzone.cc')
_locks={}
_locks_guard=threading.Lock()


class CoverError(ValueError):pass


def lock_for(path):
    with _locks_guard:return _locks.setdefault(str(Path(path).resolve()),threading.RLock())


def metadata(path):
    file=Path(path).with_suffix('.cover.json')
    try:return json.loads(file.read_text(encoding='utf8')) if file.exists() else {}
    except (ValueError,UnicodeError):return {}


def image_path(path,info=None):
    info=metadata(path) if info is None else info
    name=info.get('file','')
    if not re.fullmatch(r'cover-[a-f0-9]{24}\.(?:jpg|png)',name):return None
    target=(Path(path).parent/name).resolve()
    if not target.is_relative_to(Path(path).parent.resolve()) or not target.is_file():return None
    return target


def public(path):
    info=metadata(path)
    return {key:info.get(key,'') for key in ('origin','updated_at','error','version','width','height')} | {'has_image':image_path(path,info) is not None}


def save_metadata(path,info):
    target=Path(path).with_suffix('.cover.json')
    temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf8')
    replace_file(temporary,target)


def validate_remote(url):
    try:
        parts=urllib.parse.urlsplit(url)
        if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password or parts.port not in (None,80,443):raise ValueError()
        # An explicit proxy resolves CDN names itself; local fake-IP DNS must
        # not turn known platform CDNs into false private-network failures.
        known=any(parts.hostname==host or parts.hostname.endswith('.'+host) for host in IMAGE_HOSTS)
        if known and urllib.request.getproxies().get(parts.scheme) and not urllib.request.proxy_bypass(parts.hostname):return
        addresses=socket.getaddrinfo(parts.hostname,parts.port or (443 if parts.scheme=='https' else 80),type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError()
    except (ValueError,OSError):raise CoverError('封面地址不是可访问的公网图片地址') from None


class CoverRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        validate_remote(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def download(url):
    validate_remote(url)
    request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'image/webp,image/png,image/jpeg,image/*;q=0.8'})
    try:
        with DirectFirst(CoverRedirect()).open(request,timeout=15) as response:
            data=response.read(MAX_BYTES+1)
    except urllib.error.HTTPError as error:raise CoverError('封面服务器返回 HTTP '+str(error.code)) from None
    except (OSError,TimeoutError):raise CoverError('封面下载失败，请稍后重试') from None
    if len(data)>MAX_BYTES:raise CoverError('封面超过 8 MB')
    return data


def store_image(path,data,origin,source_url='',book_url=''):
    if len(data)>MAX_BYTES:raise CoverError('封面超过 8 MB')
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ('JPEG','PNG','WEBP','GIF') or source.width*source.height>20_000_000:raise CoverError('不支持的封面格式或图片尺寸过大')
            source.load()
            image=ImageOps.exif_transpose(source)
            transparent='A' in image.getbands() or 'transparency' in image.info
            image=image.convert('RGBA' if transparent else 'RGB')
            image.thumbnail((1200,1600),Image.Resampling.LANCZOS)
            output=io.BytesIO();extension='png' if transparent else 'jpg'
            image.save(output,format='PNG' if transparent else 'JPEG',**({} if transparent else {'quality':90}))
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError):raise CoverError('返回内容不是可读取的图片') from None
    normalized=output.getvalue();version=hashlib.sha256(normalized).hexdigest()[:24]
    file=Path(path).parent/f'cover-{version}.{extension}'
    if file.is_symlink():raise CoverError('封面缓存路径无效')
    if not file.exists():
        temporary=file.with_name(file.name+'.'+uuid.uuid4().hex+'.tmp')
        temporary.write_bytes(normalized);temporary.replace(file)
    info={'file':file.name,'version':version,'origin':origin,'width':image.width,'height':image.height,
          'source_url':source_url,'book_url':book_url,'updated_at':datetime.now(timezone.utc).isoformat(),'error':''}
    expiry=urllib.parse.parse_qs(urllib.parse.urlsplit(source_url).query).get('x-expires',[''])[0]
    if expiry.isdigit():info['source_expires_at']=int(expiry)
    save_metadata(path,info)
    return public(path)


def refresh(base,path,replace_manual=False):
    path=Path(path).resolve()
    with lock_for(path):
        current=metadata(path)
        if current.get('origin')=='manual' and not replace_manual:return public(path)
        try:
            book=library.read_book(base,path)
            old=(book.get('provenance') or {}).get('retrieved') or {}
            cached_url=old.get('cover_url','') if old.get('url')==book['url'] else ''
            platform,_,_,_=providers.resolve_url(book['url'])
            # Signed URLs are refreshed before use. Other stale URLs get one
            # renewed detail lookup after a failed image request.
            if platform=='fanqie' or (platform=='qidian' and urllib.parse.urlsplit(cached_url).path.endswith('/180')) or replace_manual or image_path(path) or not cached_url:
                cached_url=providers.detail(book['url']).get('cover_url','')
                renewed=True
            else:renewed=False
            if not cached_url:raise CoverError('来源页面没有提供封面')
            try:data=download(cached_url)
            except CoverError:
                if renewed:raise
                cached_url=providers.detail(book['url']).get('cover_url','')
                if not cached_url:raise CoverError('来源页面没有提供封面')
                data=download(cached_url)
            return store_image(path,data,'platform',cached_url,book['url'])
        except (CoverError,providers.ProviderError,library.LibraryError) as error:
            current['error']=str(error)
            save_metadata(path,current)
            return public(path)


def upload(base,path,data):
    library.read_book(base,path)
    with lock_for(path):return store_image(path,data,'manual')


class CoverQueue:
    def __init__(self,base,scope=nullcontext):
        self.base=Path(base);self.scope=scope
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='cover')
        self.pending=set();self.lock=threading.Lock()

    def enqueue(self,relative,replace_manual=False):
        path=(self.base/relative).resolve()
        library.read_book(self.base,path)
        with self.lock:
            if relative in self.pending:return False
            if metadata(path).get('origin')=='manual' and not replace_manual:return False
            self.pending.add(relative)
        def work():
            try:
                with self.scope():refresh(self.base,path,replace_manual)
            finally:
                with self.lock:self.pending.discard(relative)
        try:self.pool.submit(work)
        except RuntimeError:
            with self.lock:self.pending.discard(relative)
            raise
        return True

    def is_pending(self,relative):
        with self.lock:return relative in self.pending

    def close(self):self.pool.shutdown(wait=True,cancel_futures=True)
