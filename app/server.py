import base64
from contextlib import asynccontextmanager
import io
import json
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image, ImageOps
from app import library
from app.library import Book,component,LibraryError
from app.jobs import Jobs, active_pipeline
from app.paths import ROOT, add_tools
from app import providers, ocr_models, organize, chapters
from app.llm_settings import LlmSettings
from app.esj_session import ESJSession, ESJError
from app.esj_settings import ESJSettings
from app import recovery as recovery_tools
from llm_client import LlmOCR, LlmError


class Settings(BaseModel):
    id: str | None = Field(default=None, max_length=80)
    name: str = Field(default='默认配置', max_length=100)
    base_url: str = Field(default='', max_length=1000)
    model: str = Field(default='', max_length=200)
    key: str = Field(default='', max_length=4000)
    max_tokens: int = Field(default=32768, ge=128, le=262144)
    clear_key: bool = False
    remember_key: bool = True
    protocol: Literal['chat_completions','responses','anthropic','gemini','ollama'] = 'chat_completions'
    endpoint_mode: Literal['auto','full'] = 'auto'
    auth: Literal['auto','bearer','x-api-key','api-key','x-goog-api-key','custom','query','none'] = 'auto'
    key_header: str = Field(default='',max_length=100)
    api_version: str = Field(default='2023-06-01',max_length=100)
    timeout: float = Field(default=300,gt=0,le=600)
    stream: bool = False
    token_field: Literal['max_tokens','max_completion_tokens'] = 'max_tokens'
    headers: dict[str,str] = Field(default_factory=dict)
    extra_body: dict = Field(default_factory=dict)


class SettingsTest(Settings):
    kind: Literal['connection','vision'] = 'connection'


class ProfileSelection(BaseModel):
    id: str


class Task(BaseModel):
    kind: str
    source: str = Field(default='', max_length=2000)
    engine: str = 'builtin'
    image: str = Field(default='', max_length=28_000_000)
    language: str = 'zh'
    auto_mode: Literal['off','local','llm'] = 'local'


class ESJLogin(BaseModel):
    email: str = Field(default='', max_length=300, repr=False)
    password: str = Field(default='', max_length=1000, repr=False)
    remember: bool = False


class Extraction(BaseModel):
    method: Literal['local', 'llm'] = 'local'


class RecoverySettings(BaseModel):
    mode: Literal['off','text','vision'] = 'off'
    max_calls: int = Field(default=3,ge=1,le=10)
    max_tokens: int = Field(default=32768,ge=256,le=262144)


class Proposal(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    author: str = Field(default='', max_length=200)
    platform: Literal['sfacg', 'fanqie', 'esj', 'qidian', 'ciweimao', 'all'] = 'all'
    category: str = Field(default='待分类', min_length=1, max_length=50)
    floor_index: int = Field(default=0, ge=0)
    image_index: int = Field(default=0, ge=0)


class ProposalChoice(Proposal):
    url: str = Field(default='', max_length=2000)


class ModelDownload(BaseModel):
    language: str
    confirmed: bool = False


class DetailRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


class ChapterRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    selected_urls: list[str] | None = Field(default=None,max_length=3)


class ReOCR(BaseModel):
    floor: int = Field(ge=0)
    image: int = Field(ge=0)
    language: str = 'zh'
    engine: str = 'builtin'



def contained(base, path):
    path = Path(path).resolve()
    if not path.is_relative_to(Path(base).resolve()):
        raise HTTPException(400, '文件必须位于应用数据目录中')
    return path


def create_app(local, token, shutdown=lambda: None):
    local = Path(local)
    add_tools()
    llm_settings = LlmSettings(local)
    esj_session = ESJSession()
    esj_settings = ESJSettings(local)
    jobs = Jobs(local)
    book_lock = threading.RLock()

    @asynccontextmanager
    async def lifespan(app):
        yield
        jobs.close()
        llm_settings.close()
        esj_session.clear()
        esj_settings.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.jobs = jobs
    app.state.llm_settings = llm_settings
    app.state.esj_session = esj_session
    app.state.esj_settings = esj_settings

    def model_config():
        return {**llm_settings.current(),'recovery':recovery_tools.settings(local)}

    @app.get('/api/recovery/settings')
    def recovery_settings():
        return recovery_tools.settings(local)

    @app.post('/api/recovery/settings')
    def save_recovery_settings(value: RecoverySettings):
        if value.mode!='off':
            try:LlmOCR.from_config(llm_settings.current())
            except ValueError as exc:raise HTTPException(400,str(exc)) from None
        if value.mode=='vision':
            try:llm_settings.ensure_vision(llm_settings.current())
            except ValueError as exc:raise HTTPException(400,str(exc)) from None
        recovery_tools.write_json(local/'recovery-settings.json',value.model_dump())
        return value.model_dump()

    @app.get('/api/jobs/{job_id}/recovery')
    def recovery_status(job_id: str):
        job=jobs.get(job_id);folder=local/'jobs'/job_id
        def read(name,default):
            path=folder/name
            return json.loads(path.read_text(encoding='utf8')) if path.exists() else default
        floors=read('raw.json',{'floors':[]})['floors']
        progress=read('ocr-progress.json',{'images':{}})
        if not progress['images'] and job['state']=='succeeded':
            progress={'images':{f'{f}:{i}':{'state':'succeeded','text':text} for f,row in enumerate(read('result.json',[])) for i,text in enumerate(row['images'])}}
        return {'job':job,'floors':[f.get('floor',n+1) for n,f in enumerate(floors)],'total_images':sum(len(f.get('images',[])) for f in floors),
                'recovery':read('recovery.json',{'calls':0,'events':[]}),
                'ocr':progress}

    @app.post('/api/jobs/{job_id}/recover')
    def recover_job(job_id: str):
        job=jobs.get(job_id)
        try:
            if job['state']!='succeeded':check_ocr(job['engine'],job['language'])
            return jobs.recover(job_id,model_config())
        except ValueError as exc:raise HTTPException(409,str(exc)) from None

    @app.exception_handler(LibraryError)
    async def library_error(request,exc):
        return JSONResponse({'detail':exc.detail},status_code=exc.status_code)

    @app.exception_handler(LlmError)
    async def llm_error(request, exc):
        return JSONResponse({'detail':str(exc),'code':exc.code,'http_status':exc.http_status},status_code=400)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        # Validation errors must not echo a submitted API key or a whole uploaded image.
        return JSONResponse({'detail': '请求参数无效，请检查输入长度、数值和必填项'}, status_code=422)

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        host = request.headers.get('host', '')
        if host.split(':')[0] not in ('127.0.0.1', 'localhost'):
            return JSONResponse({'detail': '仅允许本机访问'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc != host:
            return JSONResponse({'detail': '拒绝跨来源请求'}, status_code=403)
        if request.url.path.startswith('/api/') and request.headers.get('x-session-token') != token:
            return JSONResponse({'detail': '会话已失效，请重新打开应用'}, status_code=403)
        try:
            if int(request.headers.get('content-length', '0')) > 30_000_000:
                return JSONResponse({'detail': '上传内容过大（上限约 20 MB 图片）'}, status_code=413)
        except ValueError:
            return JSONResponse({'detail': '无效请求长度'}, status_code=400)
        with esj_session.scope():
            response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob: data:; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({'detail': '未找到任务'}, status_code=404)

    @app.exception_handler(providers.ProviderError)
    async def provider_error(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=400)

    @app.get('/api/platforms')
    def platforms():
        return [{'id': key, **value} for key, value in providers.PLATFORMS.items()]

    @app.get('/api/esj/session')
    def esj_status():
        return {'connected': esj_session.connected, 'storage': 'memory_only', 'access_notice':esj_session.access_notice}

    @app.post('/api/esj/session')
    def esj_login(value: ESJLogin):
        try:
            email,password=esj_settings.resolve(value.email,value.password)
            result=esj_session.login(email,password)
            if 'remember' in value.model_fields_set:
                esj_settings.save(email,password,value.remember)
            return result
        except (ESJError,ValueError) as exc:
            raise HTTPException(400,str(exc)) from None
        finally:
            value.email = value.password = ''

    @app.get('/api/esj/settings')
    def esj_config():
        return esj_settings.public()

    @app.post('/api/esj/settings')
    def save_esj_config(value: ESJLogin):
        try:
            return esj_settings.save(value.email,value.password,value.remember)
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from None
        finally:
            value.email=value.password=''

    @app.delete('/api/esj/settings')
    def forget_esj_config():
        esj_settings.clear()
        esj_session.clear()
        return esj_config()

    @app.delete('/api/esj/session')
    def esj_logout():
        esj_session.clear()
        return esj_status()

    @app.get('/api/catalog/search')
    def catalog_search(q: str, platform: str = 'sfacg', author: str = '', page: int = 0):
        if not q.strip() or len(q) > 200 or len(author) > 200 or page < 0:
            raise HTTPException(400, '请填写有效书名、作者和页码')
        return providers.search(platform, q.strip(), author.strip(), page)

    @app.post('/api/catalog/detail')
    def catalog_detail(value: DetailRequest):
        return providers.detail(value.url)

    @app.get('/api/ocr/models')
    def models():
        return ocr_models.catalog()

    @app.post('/api/ocr/models')
    def install_model(value: ModelDownload):
        try:
            return ocr_models.install(value.language, value.confirmed)
        except Exception as exc:
            raise HTTPException(400, str(exc)) from None

    def check_ocr(engine, language):
        if engine not in ('builtin', 'llm') or language not in ('zh', 'japan', 'korean'):
            raise HTTPException(400, '不支持的识别引擎或语言')
        if engine == 'builtin':
            try:
                ocr_models.require(language)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None

    @app.get('/health')
    def health():
        return {'app': 'novel-list-helper', 'status': 'ready'}

    @app.get('/')
    def index():
        text = (ROOT/'app/static/index.html').read_text(encoding='utf-8')
        return HTMLResponse(text.replace('__SESSION_TOKEN__', token))

    @app.get('/api/settings')
    def read_settings():
        return {**llm_settings.public(),'data_dir':str(local),'runtime_dir':str(ROOT/'.runtime')}

    @app.post('/api/settings')
    def save_settings(value: Settings):
        try:
            llm_settings.save(value.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from None
        return read_settings()

    @app.post('/api/settings/activate')
    def activate_profile(value: ProfileSelection):
        try:
            llm_settings.activate(value.id)
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from None
        return read_settings()

    @app.delete('/api/settings/profiles/{profile_id}')
    def delete_profile(profile_id: str):
        try:
            llm_settings.delete(profile_id)
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from None
        return read_settings()

    @app.post('/api/settings/test')
    def test_settings(value: SettingsTest):
        current = llm_settings.draft(value.model_dump(exclude_unset=True))
        try:
            client = LlmOCR.from_config(current)
            result = client.test_connection() if value.kind=='connection' else client.test_vision()
        except LlmError as exc:
            if value.kind=='vision':
                llm_settings.mark_vision(current,{'ok':False,'kind':'vision','message':str(exc),'code':exc.code})
            raise
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from None
        if value.kind=='vision':
            llm_settings.mark_vision(current,result)
        return {**result,'protocol':current['protocol']}

    def llm_config(engine):
        current = model_config()
        if engine=='llm':
            try:
                llm_settings.ensure_vision(current)
                current['verification']=llm_settings.current().get('verification',{})
            except ValueError as exc:
                raise HTTPException(400,str(exc)) from None
        return current

    @app.get('/api/jobs')
    def list_jobs():
        return jobs.list()

    @app.post('/api/jobs')
    def submit(value: Task):
        check_ocr(value.engine, value.language)
        if value.kind not in ('image', 'tieba') or value.engine not in ('builtin', 'llm'):
            raise HTTPException(400, '不支持的任务类型或引擎')
        image = None
        if value.kind == 'image':
            try:
                image = base64.b64decode(value.image, validate=True)
                if len(image) > 20_000_000:
                    raise ValueError()
                with Image.open(io.BytesIO(image)) as source:
                    if source.width * source.height > 40_000_000:
                        raise ValueError()
                    output = io.BytesIO()
                    ImageOps.exif_transpose(source).convert('RGB').save(output, format='PNG')
                    image = output.getvalue()
            except Exception:
                raise HTTPException(400, '请选择有效图片（不超过 20 MB、4000 万像素）') from None
        else:
            from common import extract_tid
            try:
                extract_tid(value.source)
            except ValueError:
                raise HTTPException(400, '请输入贴吧帖子链接或数字 ID') from None
        current = llm_config(value.engine)
        if value.auto_mode == 'llm':
            try:
                LlmOCR.from_config(current)
            except ValueError as exc:
                raise HTTPException(400,str(exc)) from None
        llm_settings.remember_task(value.engine,value.language,value.auto_mode)
        return jobs.submit(value.kind, value.source, value.engine, current, image, value.language,value.auto_mode)

    @app.post('/api/jobs/{job_id}/organize')
    def start_organize(job_id: str, value: Extraction):
        config = model_config()
        try:
            if value.method == 'llm':
                LlmOCR.from_config(config)
            return jobs.queue_pipeline(job_id,value.method,config)
        except ValueError as exc:
            raise HTTPException(409,str(exc)) from None

    @app.post('/api/jobs/{job_id}/cancel')
    def cancel(job_id: str):
        jobs.cancel(job_id)
        return jobs.get(job_id)

    @app.post('/api/jobs/{job_id}/retry')
    def retry(job_id: str):
        job = jobs.get(job_id)
        if job['state'] in ('running', 'queued'):
            raise HTTPException(409, '任务仍在运行')
        folder = local/'jobs'/job_id
        image = (folder/'input.png').read_bytes() if job['kind'] == 'image' else None
        current = llm_config(job['engine'])
        check_ocr(job['engine'], job['language'])
        llm_settings.remember_task(job['engine'], job['language'])
        return jobs.submit(job['kind'], job['source'], job['engine'], current, image, job['language'],job['auto_mode'])

    @app.post('/api/jobs/{job_id}/reocr')
    def reocr(job_id: str, value: ReOCR):
        jobs.get(job_id)
        check_ocr(value.engine, value.language)
        folder = local/'jobs'/job_id
        try:
            raw = json.loads((folder/'raw.json').read_text(encoding='utf-8'))
            floor = raw['floors'][value.floor]
            path = contained(folder, floor['images'][value.image]['file'])
            image = path.read_bytes()
        except (OSError, IndexError):
            raise HTTPException(404, '未找到原始图片') from None
        current = llm_config(value.engine)
        llm_settings.remember_task(value.engine,value.language)
        new = jobs.submit('image', f'重识别：{job_id[:8]} / 楼层 {floor.get("floor", value.floor+1)} / 图片 {value.image+1}',
                         value.engine, current, image, value.language)
        (local/'jobs'/new['id']/'origin.json').write_text(json.dumps({'job_id':job_id,'floor_index':value.floor,
            'image_index':value.image,'language':value.language}, ensure_ascii=False), encoding='utf-8')
        return new

    @app.get('/api/jobs/{job_id}/result')
    def result(job_id: str):
        job = jobs.get(job_id)
        folder = local/'jobs'/job_id
        data = json.loads((folder/'result.json').read_text(encoding='utf-8')) if (folder/'result.json').exists() else []
        raw = json.loads((folder/'raw.json').read_text(encoding='utf-8')) if (folder/'raw.json').exists() else {'floors': []}
        return {'job': job, 'result': data, 'images': [len(f.get('images', [])) for f in raw['floors']],
                'floors': [f.get('floor', n + 1) for n, f in enumerate(raw['floors'])]}

    @app.put('/api/jobs/{job_id}/result')
    def edit_result(job_id: str, data: list[dict]):
        check_editable(job_id)
        if jobs.get(job_id)['state'] != 'succeeded':
            raise HTTPException(409, '任务尚未成功完成')
        path = local/'jobs'/job_id/'result.json'
        original = json.loads(path.read_text(encoding='utf-8'))
        if len(data) != len(original) or any(set(f) != {'text', 'images'} or not isinstance(f['text'], str)
            or not isinstance(f['images'], list) or not all(isinstance(t, str) for t in f['images'])
            or len(f['images']) != len(old['images']) for f, old in zip(data, original)):
            raise HTTPException(400, '请保持楼层和图片数量，仅修改文字')
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'ok': True}

    def plan_path(job_id):
        if jobs.get(job_id)['state'] != 'succeeded':
            raise HTTPException(409, '请等待识别完成')
        return local/'jobs'/job_id/'books.json'

    def check_editable(job_id):
        if (job_id in jobs.pending_pipelines or jobs.get(job_id)['organize_state'] in ('queued','running')) and active_pipeline.get() != job_id:
            raise HTTPException(409,'后台尚未结束此任务，请取消整理后等待当前请求结束，再修改')

    def write_plan(path, data):
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)

    @app.get('/api/jobs/{job_id}/books')
    def read_plan(job_id: str):
        path = plan_path(job_id)
        plan = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'items': [], 'skipped': []}
        raw = json.loads((path.parent/'raw.json').read_text(encoding='utf-8'))
        return organize.attach_sources(plan, jobs.get(job_id), raw)

    @app.post('/api/jobs/{job_id}/books/extract')
    def extract_books(job_id: str, value: Extraction):
        return extract_plan(job_id,value.method,model_config())

    def extract_plan(job_id, method, config):
        check_editable(job_id)
        path = plan_path(job_id)
        data = result(job_id)
        if method == 'llm':
            try:
                recovery=recovery_tools.Recovery(path.parent,config,lambda:jobs.check_pipeline(job_id) if active_pipeline.get()==job_id else None)
                plan = organize.extract_llm(data['result'], data['floors'], LlmOCR.from_config(config),recovery)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None
        else:
            raw=json.loads((path.parent/'raw.json').read_text(encoding='utf8'))
            plan = organize.extract(data['result'], data['floors'],raw.get('title',''))
        with book_lock:
            write_plan(path, plan)
        return read_plan(job_id)

    @app.post('/api/jobs/{job_id}/books/{item_id}/verify')
    def verify_book(job_id: str, item_id: int, value: ProposalChoice):
        path = plan_path(job_id)
        edit_proposal(job_id, item_id, Proposal(**value.model_dump()))
        data = result(job_id)
        if value.floor_index >= len(data['floors']) or value.image_index >= data['images'][value.floor_index]:
            raise HTTPException(400, '请选择有效图片来源')
        item = value.model_dump(exclude={'url'})
        item['floor'] = data['floors'][value.floor_index]
        try:
            if value.url:
                item.update(book=providers.detail(value.url), state='confirmed', candidates=[], warnings=[])
            else:
                item = organize.verify(item)
        except providers.ProviderError as exc:
            with book_lock:
                plan = read_plan(job_id)
                plan['items'][item_id].update(reason=f'查询失败：{exc}', error=str(exc))
                write_plan(path, plan)
            raise
        with book_lock:
            plan = read_plan(job_id)
            if item_id < 0 or item_id > len(plan['items']):
                raise HTTPException(400, '书籍序号无效')
            if item_id == len(plan['items']):
                plan['items'].append(item)
            else:
                plan['items'][item_id] = item
            write_plan(path, plan)
        return read_plan(job_id)['items'][item_id]

    @app.put('/api/jobs/{job_id}/books/{item_id}')
    def edit_proposal(job_id: str, item_id: int, value: Proposal):
        check_editable(job_id)
        path = plan_path(job_id)
        data = result(job_id)
        if value.floor_index >= len(data['floors']) or value.image_index >= data['images'][value.floor_index]:
            raise HTTPException(400, '请选择有效图片来源')
        item = {**value.model_dump(), 'floor': data['floors'][value.floor_index],
                'state': 'draft', 'candidates': [], 'warnings': []}
        with book_lock:
            plan = read_plan(job_id)
            if item_id < 0 or item_id > len(plan['items']):
                raise HTTPException(400, '书籍序号无效')
            if item_id == len(plan['items']):
                plan['items'].append(item)
            else:
                plan['items'][item_id] = item
            write_plan(path, plan)
        return read_plan(job_id)['items'][item_id]

    @app.post('/api/jobs/{job_id}/books/archive')
    def archive_plan(job_id: str):
        check_editable(job_id)
        path = plan_path(job_id)
        with book_lock:
            plan = read_plan(job_id)
            for item in plan['items']:
                if item['state'] not in ('verified', 'confirmed'):
                    continue
                book = item['book']
                try:
                    if active_pipeline.get() == job_id:
                        jobs.check_pipeline(job_id)
                    target = contained(local/'library',local/'library'/component(item['category'])/component(book['title'])/(book['title']+'.md'))
                    metadata = target.with_suffix('.metadata.json')
                    prior = json.loads(metadata.read_text(encoding='utf-8')) if target.exists() and metadata.exists() else {}
                    retrieved = (prior.get('lookup') or {}).get('retrieved') or {}
                    if retrieved.get('url') == book['url'] and providers.normalize(retrieved.get('author')) == providers.normalize(book['author']):
                        item.update(state='archived',path=target.relative_to(local/'library').as_posix(),existing=True)
                        item.pop('archive_error',None)
                        item.pop('reason',None)
                        continue
                    saved = save_book(Book(title=book['title'], category=item['category'], author=book['author'],
                        platform=book['platform_label'], words=str(book['word_count'] or ''), status=book['status'],
                        tags='|'.join(book['tags']), intro=book['intro'], url=book['url'],
                        source=f"{jobs.get(job_id)['source']} · 楼层 {item['floor']} · 图片 {item['image_index']+1}",
                        provenance={'retrieved': book, 'ocr_proposal': {k: item[k] for k in
                            ('title', 'author', 'platform', 'floor_index', 'image_index')}, 'job_id': job_id,
                            'recovery_original':item.get('recovery_original'),'recovery_image_text':item.get('recovery_ocr')}))
                    item.update(state='archived', path=saved['path'])
                    item.pop('archive_error', None)
                    item.pop('reason', None)
                except (HTTPException,LibraryError) as exc:
                    item['archive_error'] = str(exc.detail)
            write_plan(path, plan)
        return read_plan(job_id)

    def run_workflow(job_id, method, config):
        with esj_session.scope():
            plan = read_plan(job_id)
            if not plan['items']:
                plan = extract_plan(job_id,method,config)
            recovery=recovery_tools.Recovery(local/'jobs'/job_id,config,lambda:jobs.check_pipeline(job_id))
            ocr_result=result(job_id)['result']
            raw=json.loads((local/'jobs'/job_id/'raw.json').read_text(encoding='utf8'))
            for index, item in enumerate(plan['items']):
                jobs.check_pipeline(job_id)
                if item['state'] in ('archived','verified','confirmed'):
                    continue
                jobs.pipeline_status(job_id,'running',f'核对书籍 {index+1}/{len(plan["items"])}')
                try:
                    verified=recovery.lookup(item,lambda proposal:verify_book(job_id,index,ProposalChoice(**proposal)))
                    if verified['state']=='review' and config.get('recovery',{}).get('mode','off')!='off':
                        source=ocr_result[item['floor_index']]['images'][item['image_index']]
                        image_path=contained(local/'jobs'/job_id,raw['floors'][item['floor_index']]['images'][item['image_index']]['file'])
                        fixed=recovery.verify_book(verified,source,organize.verify,image_path)
                        jobs.check_pipeline(job_id)
                        with book_lock:
                            latest=read_plan(job_id);latest['items'][index]=fixed
                            write_plan(plan_path(job_id),latest)
                except (providers.ProviderError,HTTPException,ValueError) as exc:
                    reason = str(exc.detail) if isinstance(exc,HTTPException) else str(exc)
                    if config.get('key'):
                        reason = reason.replace(config['key'],'[已隐藏]')
                    with book_lock:
                        latest = read_plan(job_id)
                        latest['items'][index].update(state='review',reason=reason,error=reason)
                        write_plan(plan_path(job_id),latest)
            jobs.check_pipeline(job_id)
            jobs.pipeline_status(job_id,'running','归档书籍')
            plan = archive_plan(job_id)
            count = sum(i['state']=='archived' for i in plan['items'])
            pending = len(plan['items'])-count
            skipped = len(plan.get('skipped',[]))
            state = 'review' if pending or skipped else 'succeeded'
            return state,f'归档 {count} 本，待核对 {pending} 本，未提取图片 {skipped} 张'

    jobs.pipeline = run_workflow

    @app.get('/api/jobs/{job_id}/image/{floor}/{image}')
    def job_image(job_id: str, floor: int, image: int):
        jobs.get(job_id)
        folder = local/'jobs'/job_id
        try:
            raw = json.loads((folder/'raw.json').read_text(encoding='utf-8'))
            if floor < 0 or image < 0:
                raise IndexError()
            path = contained(folder, raw['floors'][floor]['images'][image]['file'])
            if not path.is_file():raise HTTPException(404,'图片不存在')
            return FileResponse(path)
        except (OSError, IndexError):
            raise HTTPException(404, '图片不存在') from None

    @app.get('/api/search')
    def search(q: str, page: int = 0):
        from search_novel import search_by_name, format_results
        if not q.strip() or len(q) > 200 or page < 0:
            raise HTTPException(400, '请填写有效关键词和页码')
        try:
            return format_results(q, search_by_name(q, page=page), False)
        except Exception:
            raise HTTPException(502, '菠萝包查询失败，请稍后重试') from None

    @app.get('/api/novels/{novel_id}')
    def novel(novel_id: int):
        from fetch_novel_fields import fetch_novel, extract_fields
        try:
            return extract_fields(fetch_novel(novel_id))
        except Exception:
            raise HTTPException(502, '书籍详情获取失败') from None

    @app.get('/api/books')
    def books():
        base = local/'library'
        return [{'title': p.stem, 'category': p.parent.parent.name, 'path': p.relative_to(base).as_posix(),
                 'is_esj': bool(re.search(r'^- 链接（如有）：https://(?:www\.)?esjzone\.(?:one|cc)/detail/',p.read_text(encoding='utf-8'),re.M)),
                 'choose_chapters': bool(re.search(r'^- 链接（如有）：https://(?:(?:www\.)?esjzone\.(?:one|cc)/detail/|(?:www\.|wap\.)?ciweimao\.com/book/)',p.read_text(encoding='utf-8'),re.M)),
                 'text_path': p.with_suffix('.txt').relative_to(base).as_posix() if p.with_suffix('.txt').exists() else None}
                for p in sorted(base.glob('*/*/*.md')) if p.name == p.parent.name + '.md']

    @app.post('/api/books')
    def save_book(book: Book):
        with book_lock:
            return library.save_book(local/'library',book)

    @app.get('/api/books/download')
    def download_book(path: str):
        target = contained(local/'library', local/'library'/path)
        if not target.is_file() or target.suffix not in ('.md', '.txt'):
            raise HTTPException(404, '文件不存在')
        return FileResponse(target, filename=target.name)

    def chapter_source(value):
        target = contained(local/'library', local/'library'/value.path)
        if not target.is_file() or target.suffix != '.md':
            raise HTTPException(404, '请先归档书籍')
        text = target.read_text(encoding='utf-8')
        link = re.search(r'^- 链接（如有）：(https://\S+)', text, re.M)
        if not link:
            raise HTTPException(400, '档案中没有有效书籍链接')
        return target,link[1]

    @app.post('/api/books/catalog')
    def book_catalog(value: ChapterRequest):
        _,url=chapter_source(value)
        platform,entries=chapters.catalog(url)
        if platform=='esj':
            suggested,reason=chapters.esj_catalog.recommend(entries)
        else:
            from app.mainland import suggested as suggest_chapters
            suggested,reason=suggest_chapters(platform,entries)
        return {'platform':platform,'entries':entries,'suggested_urls':[e['url'] for e in suggested],
                'selection_reason':reason}

    @app.post('/api/books/chapters')
    def book_chapters(value: ChapterRequest):
        target,url=chapter_source(value)
        result = chapters.preview(url,selected_urls=value.selected_urls)
        content = '\n\n'.join(f'{c["title"]}\n来源：{c["url"]}\n\n{c["content"]}' for c in result['chapters'])
        with book_lock:
            target.with_suffix('.txt').write_text(content, encoding='utf-8')
            target.with_suffix('.chapters.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'path': target.with_suffix('.txt').relative_to(local/'library').as_posix(),
                'count': len(result['chapters']), 'warnings': result['warnings']}

    @app.post('/api/shutdown')
    def stop():
        threading.Timer(0.3, shutdown).start()
        return {'ok': True}

    app.mount('/static', StaticFiles(directory=ROOT/'app/static'), name='static')
    return app
