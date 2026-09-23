"""SFACG keyword search CLI and candidate normalization (MIT)."""
import argparse
import json
import sys
from fetch_novel_fields import request_data,FetchError,BOOK_URL_BASE

class SearchError(FetchError):pass


def norm(value):return ''.join((value or '').split())


def search_by_name(keyword,size=20,page=0):
    if page<0:raise SearchError('页码不能小于零')
    try:return request_data('/search/novels',{'key':keyword,'page':page,'size':max(1,min(size,50))}).get('items') or []
    except FetchError as error:raise SearchError(str(error)) from None


def format_results(keyword,items,exact_only=False):
    candidates=[]
    for item in items:
        identifier=item.get('novelId')
        title=item.get('novelName') or ''
        exact=bool(identifier and norm(title)==norm(keyword))
        if exact_only and not exact:continue
        candidates.append(dict(novelId=identifier,novelName=title,authorName=item.get('authorName'),
                               categoryId=item.get('categoryId'),coverUrl=item.get('novelCover'),
                               novelUrl=BOOK_URL_BASE.format(novel_id=identifier) if identifier else None,exactMatch=exact))
    return candidates


def render_table(blocks):
    for block in blocks:
        print(block['query'])
        for row in block['results']:print(str(row['novelId']),row['novelName'],row['authorName'] or '',sep=' | ')


def main():
    parser=argparse.ArgumentParser(description='搜索菠萝包书籍')
    parser.add_argument('names',nargs='+')
    parser.add_argument('--size',type=int,default=20)
    parser.add_argument('--page',type=int,default=0)
    for flag in ('exact','table','json'):parser.add_argument('--'+flag,action='store_true')
    args=parser.parse_args()
    if args.page<0:parser.error('页码不能小于零')
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf8')
    blocks=[];errors=[];empty=[]
    for name in args.names:
        try:
            hits=search_by_name(name,args.size,args.page)
            rows=format_results(name,hits,args.exact)
            blocks.append({'query':name,'count':len(rows),'results':rows})
            if not rows:empty.append({'query':name,'hits':len(hits)})
        except SearchError as error:errors.append({'query':name,'error':str(error)})
    if args.table and not args.json:render_table(blocks)
    else:print(json.dumps({'results':blocks,'errors':errors,'empty':empty} if errors or empty else blocks,ensure_ascii=False,indent=2))
    return int(bool(errors or empty))

if __name__=='__main__':raise SystemExit(main())
