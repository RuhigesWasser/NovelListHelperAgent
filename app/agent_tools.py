"""JSON tools for an external Agent. No browser or running web server required."""
import argparse
import asyncio
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
import uuid
from app.paths import ROOT,configure,add_tools
from app import providers,organize,chapters,library
from app.esj_session import ESJSession
from app.esj_settings import ESJSettings


TOOLS={
    'fetch_thread':{'description':'抓取贴吧正文和图片，返回可供 Agent 读取的本地素材路径。','input':{'source':'贴吧 URL 或 ID'}},
    'ocr_image':{'description':'使用内置 OCR 读取本地图片。','input':{'path':'本地图片路径','language':'zh / japan / korean（默认 zh）'}},
    'extract_books':{'description':'从 OCR JSON 提取待核对书单，书架支持同图多书。','input':{'result':'楼层数组，每项包含 text、images 字符串数组','floors':'可选真实楼层号数组','context':'可选帖子标题，用于判断平台'}},
    'extract_image_books':{'description':'多模态直接读取截图并返回待核对书单；不自动归档。','input':{'paths':'本地图片路径数组','llm':'可选临时 LLM 配置，不保存；省略时使用当前已保存配置'}},
    'search_books':{'description':'搜索官方平台候选，不将近似结果当成已确认。','input':{'title':'书名','author':'可选作者','platform':'qidian / ciweimao / sfacg / fanqie / esj / all'}},
    'book_detail':{'description':'读取平台详情、简介、标签和字段来源。','input':{'url':'支持的书籍详情 URL'}},
    'chapter_catalog':{'description':'获取目录与前三章建议；ESJ 无法确认时交由 Agent/用户选择。','input':{'url':'书籍 URL'}},
    'read_chapters':{'description':'读取选定章节，未指定时读取前三项；返回正文与来源。','input':{'url':'书籍 URL','selected_urls':'可选目录链接数组'}},
    'archive_book':{'description':'按项目格式写入书库并更新索引。默认不覆盖。','input':library.Book.model_json_schema()},
    'list_books':{'description':'列出本地书籍档案。','input':{}},
    'refresh_cover':{'description':'刷新已归档书籍的本地封面，失败时保留旧图。','input':{'path':'书库相对路径','replace_manual':'是否替换手动封面，默认 false'}},
    'login_saved_esj':{'description':'使用用户已保存配置建立内存会话；不返回账号密码。serve 模式可复用此会话。','input':{}},
}


class AgentTools:
    def __init__(self,root=ROOT):
        self.local=configure(root)
        add_tools()
        self.esj=ESJSession()

    def close(self):self.esj.clear()

    def call(self,action,data):
        with self.esj.scope():return self._call(action,data)

    def _call(self,action,data):
        if action=='fetch_thread':
            from common import extract_tid
            from fetch_thread import fetch_thread
            folder=self.local/'agent'/uuid.uuid4().hex;folder.mkdir(parents=True)
            raw=asyncio.run(fetch_thread(extract_tid(data['source']),str(folder/'images'),'origin',30,True))
            path=folder/'raw.json';path.write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf8')
            return {'raw_path':str(path),'data':raw}
        if action=='ocr_image':
            import ocr
            return {'text':ocr.BuiltinOCR(data.get('language','zh'))(Path(data['path']))}
        if action=='extract_books':
            result=data['result']
            return organize.extract(result,data.get('floors',list(range(1,len(result)+1))),data.get('context',''))
        if action=='extract_image_books':
            import shutil
            from app import image_books
            from app.llm_settings import LlmSettings
            from app.recovery import Recovery
            from llm_client import LlmOCR
            settings=LlmSettings(self.local)
            try:
                config=data.get('llm') or settings.current()
                settings.ensure_vision(config,persist=False)
                client=LlmOCR.from_config(config)
                folder=self.local/'agent'/uuid.uuid4().hex;folder.mkdir(parents=True)
                images=[]
                for index,source in enumerate(data['paths']):
                    source=Path(source);target=folder/(str(index)+source.suffix)
                    shutil.copy2(source,target);images.append({'file':str(target)})
                result=[{'text':'','images':['']*len(images)}]
                return image_books.augment({'items':[],'skipped':[]},result,[1],{'floors':[{'images':images}]},folder,Recovery(folder,config),client)
            finally:settings.close()
        if action=='search_books':return providers.search(data.get('platform','all'),data['title'],data.get('author',''))
        if action=='book_detail':return providers.detail(data['url'])
        if action=='chapter_catalog':
            platform,items=chapters.catalog(data['url'])
            from app.mainland import suggested
            selected,reason=chapters.esj_catalog.recommend(items) if platform=='esj' else suggested(platform,items)
            return {'platform':platform,'entries':items,'suggested_urls':[x['url'] for x in selected],'reason':reason}
        if action=='read_chapters':return chapters.preview(data['url'],selected_urls=data.get('selected_urls'))
        if action=='archive_book':
            saved=library.save_book(self.local/'library',library.Book(**data))
            if data.get('url'):
                from app import covers
                saved['cover']=covers.refresh(self.local/'library',self.local/'library'/saved['path'])
            return saved
        if action=='refresh_cover':
            from app import covers
            path=(self.local/'library'/data['path']).resolve()
            library.read_book(self.local/'library',path)
            return covers.refresh(self.local/'library',path,bool(data.get('replace_manual')))
        if action=='list_books':
            base=self.local/'library'
            return [{'title':p.stem,'path':p.relative_to(base).as_posix()} for p in base.glob('*/*/*.md') if p.stem==p.parent.name]
        if action=='login_saved_esj':
            config=ESJSettings(self.local)
            try:return self.esj.login(*config.resolve('',''))
            finally:config.close()
        raise ValueError('未知工具：'+str(action))


def main():
    sys.stdout.reconfigure(encoding='utf8')
    sys.stdin.reconfigure(encoding='utf8')
    parser=argparse.ArgumentParser(description='Script toolkit for external Agents. JSON input/output; no app server needed.')
    parser.add_argument('mode',choices=['schema','run','serve'])
    args=parser.parse_args()
    if args.mode=='schema':
        print(json.dumps({'version':1,'tools':TOOLS},ensure_ascii=False,indent=2));return 0
    toolkit=AgentTools()
    def execute(text):
        request={}
        try:
            request=json.loads(text)
            if not isinstance(request,dict):raise ValueError('请求必须是 JSON 对象')
            with redirect_stdout(sys.stderr):result=toolkit.call(request['action'],request.get('input',{}))
            return {'id':request.get('id'),'ok':True,'result':result}
        except Exception as error:
            # User data is not echoed by schema validation exceptions.
            from pydantic import ValidationError
            message='工具参数无效' if isinstance(error,ValidationError) else str(error)
            return {'id':request.get('id') if isinstance(request,dict) else None,'ok':False,'error':message}
    try:
        if args.mode=='run':
            response=execute(sys.stdin.read());print(json.dumps(response,ensure_ascii=False));return 0 if response['ok'] else 1
        for line in sys.stdin:
            if line.strip():print(json.dumps(execute(line),ensure_ascii=False),flush=True)
        return 0
    finally:toolkit.close()


if __name__=='__main__':raise SystemExit(main())
