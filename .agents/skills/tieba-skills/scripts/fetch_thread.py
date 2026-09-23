"""Download Tieba floors and images, optionally run OCR (Shiye, MIT)."""
import argparse
import asyncio
import hashlib
import importlib
import json
from pathlib import Path
import sys
from urllib.request import Request,urlopen
from common import ensure_utf8_stdout,extract_tid,project_root
from ocr import add_ocr_arguments,make_engine,recognize_thread,write_json

UA={'User-Agent':'Mozilla/5.0','Referer':'https://tieba.baidu.com/'}
MAX_EDGE=2048
MAX_FILE_BYTES=3500000


def ensure_aiotieba():
    try:importlib.import_module('aiotieba')
    except ImportError:raise RuntimeError('缺少 aiotieba；请通过项目启动器确认安装，或在自己的虚拟环境中安装依赖。') from None


def pick_url(image,size):
    order={'origin':('origin_src','big_src','src'),'big':('big_src','src'),'src':('src',)}[size]
    return next((getattr(image,key,'') for key in order if getattr(image,key,'')),'')


def img_hash(url):return hashlib.sha256(url.encode('utf8')).hexdigest()[:32]


def download(url,path):
    destination=Path(path)
    destination.parent.mkdir(parents=True,exist_ok=True)
    for attempt in range(2):
        try:
            with urlopen(Request(url,headers=UA),timeout=30) as response:destination.write_bytes(response.read())
            return
        except OSError:
            if attempt:raise


def preprocess(path):
    from PIL import Image,ImageOps
    with Image.open(path) as original:
        if max(original.size)<=MAX_EDGE and Path(path).stat().st_size<=MAX_FILE_BYTES:return
        image=ImageOps.exif_transpose(original).convert('RGB')
        image.thumbnail((MAX_EDGE,MAX_EDGE),Image.Resampling.LANCZOS)
        temporary=Path(str(path)+'.preview.jpg')
        image.save(temporary,format='JPEG',quality=85,optimize=True)
    temporary.replace(path)


async def fetch_thread(tid,img_dir,size,rn,preserve_images=False):
    from aiotieba import Client
    folder=Path(img_dir).resolve();folder.mkdir(parents=True,exist_ok=True)
    result={'tid':tid,'url':f'https://tieba.baidu.com/p/{tid}','title':'','fname':'','floors':[]}
    cached={};page=1
    async with Client() as client:
        while True:
            response=await client.get_posts(tid,pn=page,rn=rn)
            if page==1:result.update(title=response.thread.title or '',fname=response.forum.fname or '')
            for post in response.objs:
                images=[]
                for position,picture in enumerate(post.contents.imgs,start=1):
                    url=pick_url(picture,size)
                    digest=img_hash(url)
                    if url not in cached:
                        path=folder/f'f{post.floor}_{position}_{digest}.jpg'
                        download(url,str(path))
                        if not preserve_images:preprocess(str(path))
                        cached[url]=str(path)
                    images.append({'url':url,'file':cached[url],'hash':digest})
                result['floors'].append({'floor':post.floor,'pid':post.pid,'page':page,'text':post.text or '', 'images':images})
            if not response.has_more:break
            page+=1
            await asyncio.sleep(0.3)
    result['floor_count']=len(result['floors'])
    return result


def main():
    parser=argparse.ArgumentParser(description='采集贴吧楼层、图片和 OCR 结果')
    parser.add_argument('input')
    for key in ('img-dir','out','raw-out'):parser.add_argument('--'+key)
    parser.add_argument('--size',choices=['origin','big','src'],default='origin')
    parser.add_argument('--rn',type=int,default=30)
    add_ocr_arguments(parser)
    args=parser.parse_args();ensure_utf8_stdout()
    try:
        if args.out and args.raw_out and Path(args.out).resolve()==Path(args.raw_out).resolve():raise ValueError('原始数据与识别结果应使用不同输出文件')
        tid=extract_tid(args.input)
        engine=make_engine(args);ensure_aiotieba()
        folder=Path(args.img_dir) if args.img_dir else Path(project_root())/'tmp'/f'tieba_{tid}'
        raw=asyncio.run(fetch_thread(tid,str(folder),args.size,args.rn,preserve_images=engine is not None))
        if args.raw_out:
            path=Path(args.raw_out);path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf8')
        write_json(recognize_thread(raw,engine) if engine is not None else raw,args.out)
        return 0
    except Exception as error:
        print(f'采集失败：{type(error).__name__}: {error}',file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
