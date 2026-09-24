"""Read SFACG metadata and expose the project's stable JSON interface (MIT)."""
import argparse
import gzip
import json
import re
import sys
from urllib.parse import urlencode
from urllib.request import Request
from pathlib import Path
_network_dir = Path(__file__).resolve().parents[2]/"tieba-skills/scripts"
if not _network_dir.is_dir(): _network_dir = Path(__file__).resolve().parents[1]/"tieba"
sys.path.insert(0, str(_network_dir))
from direct_http import urlopen
from urllib.error import HTTPError,URLError

API_BASE='https://api.sfacg.com'
BOOK_URL_BASE='https://book.sfacg.com/novel/{novel_id}/'
# Public client protocol parameters; not a user's account credential.
HEADERS={'Accept':'application/vnd.sfacg.api+json;version=1',
         'Authorization':'Basic YW5kcm9pZHVzZXI6MWEjJDUxLXl0Njk7KkFjdkBxeHE=',
         'User-Agent':'boluobao/4.8.14(android;28)', 'Accept-Encoding':'gzip'}
EXPAND='intro,typeName,sysTags,customTag,tags,firstchapter,latestchapter'

class FetchError(RuntimeError):pass


def request_data(path,query):
    request=Request(API_BASE+path+'?'+urlencode(query),headers=HEADERS)
    try:
        with urlopen(request,timeout=20) as response:
            body=response.read()
            if response.headers.get('Content-Encoding','').lower()=='gzip':body=gzip.decompress(body)
        envelope=json.loads(body)
    except HTTPError as error:raise FetchError('菠萝包 HTTP '+str(error.code)) from None
    except (URLError,TimeoutError,OSError,ValueError) as error:raise FetchError('菠萝包请求失败：'+type(error).__name__) from None
    code=(envelope.get('status') or {}).get('errorCode',200)
    if code!=200 or envelope.get('data') is None:raise FetchError('菠萝包没有返回有效资料，状态 '+str(code))
    return envelope['data']


def extract_novel_id(raw):
    text=str(raw).strip()
    if text.isdecimal():return int(text)
    match=re.search(r'/novel/([0-9]+)(?:[/\?#]|$)',text)
    if not match:raise FetchError('请输入菠萝包书籍链接或数字 ID')
    return int(match[1])


def fetch_novel(novel_id):
    return request_data('/novels/'+str(int(novel_id)),{'expand':EXPAND})


def extract_fields(data):
    extra=data.get('expand') or {}
    intro=str(extra.get('intro') or '').strip()
    labels=[str(x.get('tagName') or '').strip() for x in extra.get('sysTags',[]) or []]
    labels.extend(str(x).strip() for x in extra.get('customTag',[]) or [])
    labels.extend(re.findall('「([^」]+)」',intro))
    result={key:data.get(key) for key in ('novelId','novelName','authorName')}
    result.update(platform='菠萝包',charCount=data.get('charCount') or 0,
                  status='完结' if data.get('isFinish') else '连载中',
                  tags=list(dict.fromkeys(x for x in labels if x)),intro=intro or '（无简介）',
                  novelUrl=BOOK_URL_BASE.format(novel_id=result['novelId']))
    return result


def main():
    parser=argparse.ArgumentParser(description='查询菠萝包书籍资料')
    parser.add_argument('ids',nargs='+')
    args=parser.parse_args()
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf8')
    results=[];errors=[]
    for value in args.ids:
        try:results.append(extract_fields(fetch_novel(extract_novel_id(value))))
        except FetchError as error:errors.append({'input':value,'error':str(error)})
    print(json.dumps({'results':results,'errors':errors} if errors else results,ensure_ascii=False,indent=2))
    return int(bool(errors))

if __name__=='__main__':raise SystemExit(main())
