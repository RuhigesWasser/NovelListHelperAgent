"""Shared book schema and archive writer for Agent tools and local applications."""
from datetime import date
import json
import os
import hashlib
from pathlib import Path
import re
from pydantic import BaseModel,Field
from app.paths import add_tools


class LibraryError(ValueError):
    def __init__(self,detail,status_code=400):
        super().__init__(detail)
        self.detail,self.status_code=detail,status_code


class Book(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=50)
    author: str = Field(default='', max_length=200)
    platform: str = Field(default='', max_length=100)
    words: str = Field(default='', max_length=30)
    status: str = Field(default='未知', max_length=30)
    tags: str = Field(default='', max_length=500)
    intro: str = Field(default='', max_length=30000)
    review: str = Field(default='【无】', max_length=10000)
    source: str = Field(default='手动整理', max_length=500)
    url: str = Field(default='', max_length=2000)
    overwrite: bool = False
    provenance: dict = Field(default_factory=dict)


def component(name):
    name = name.strip()
    if (not name or name in ('.', '..') or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or name.endswith(('.', ' ')) or name.split('.')[0].upper() in
            {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}):
        raise LibraryError('书名或分类包含不适合作为目录名的字符')
    return name


def read_book(base,path):
    base=Path(base).resolve();path=Path(path).resolve()
    if not path.is_relative_to(base) or path.suffix!='.md' or path.stem!=path.parent.name:
        raise LibraryError('无效的书籍路径')
    content=path.read_bytes();text=content.decode('utf-8-sig').replace('\r\n','\n')
    headings=r'基本信息|内容简介|笔者评语|元数据'
    sections=dict(re.findall(r'^## ('+headings+r')\s*\n(.*?)(?=^## (?:'+headings+r')\s*$|\Z)',text,re.M|re.S))
    fields=dict(re.findall(r'^- ([^：\n]+)：(.*)$',sections.get('基本信息','')+'\n'+sections.get('元数据',''),re.M))
    record={'title':path.stem,'category':path.parent.parent.name,'path':path.relative_to(base).as_posix(),
        'intro':sections.get('内容简介','').strip(),'review':sections.get('笔者评语','').strip(),
        'revision':hashlib.sha256(content).hexdigest(),'saved_on':fields.get('整理日期',''),
        'text_path':path.with_suffix('.txt').relative_to(base).as_posix() if path.with_suffix('.txt').is_file() else None}
    for key,label in {'author':'作者','platform':'平台','words':'字数','status':'状态','tags':'题材标签','source':'整理来源','url':'链接（如有）'}.items():record[key]=fields.get(label,'')
    metadata=path.with_suffix('.metadata.json')
    try:record['provenance']=json.loads(metadata.read_text(encoding='utf8')).get('lookup') or {} if metadata.exists() else {}
    except (ValueError,UnicodeError):record['provenance']={}
    from app import covers
    record['cover']=covers.public(path)
    return record


def save_book(base, book):
    base=Path(base).resolve()
    base.mkdir(parents=True,exist_ok=True)
    with (base/'.archive.lock').open('a+b') as handle:
        if handle.tell()==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_LOCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX)
        return _write_book(base,book)


def _write_book(base, book):
    add_tools()
    from update_index import render_index
    title, category = component(book.title), component(book.category)
    base = Path(base).resolve()
    path = (base/category/title/(title+'.md')).resolve()
    if not path.is_relative_to(base.resolve()):raise LibraryError('书籍目录必须位于书库中')
    if path.exists() and not book.overwrite:
        raise LibraryError('同分类下已有该书；确认覆盖后再保存',409)
    def line(text):
        return text.replace('\r', ' ').replace('\n', ' ')
    content = f'## 基本信息\n- 书名：{title}\n- 作者：{line(book.author)}\n- 平台：{line(book.platform)}\n- 字数：{line(book.words)}\n- 状态：{line(book.status)}\n- 题材标签：{line(book.tags)}\n## 内容简介\n{book.intro}\n## 笔者评语\n{book.review or "【无】"}\n## 元数据\n- 整理日期：{date.today().isoformat()}\n- 整理来源：{line(book.source)}\n- 链接（如有）：{line(book.url)}\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    path.with_suffix('.metadata.json').write_text(json.dumps({'lookup': book.provenance or None,
        'saved_on': date.today().isoformat()}, ensure_ascii=False, indent=2), encoding='utf-8')
    (base/'索引.md').write_text(render_index(base, '小说书单'), encoding='utf-8')
    return {'path': path.relative_to(base).as_posix()}
