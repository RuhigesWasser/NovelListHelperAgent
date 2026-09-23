from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from app.paths import ROOT

active_pipeline = ContextVar('active_pipeline', default=None)


class PipelineCancelled(Exception):
    pass


class Jobs:
    def __init__(self, local):
        self.local = Path(local)
        self.db = self.local/'jobs.sqlite3'
        self.lock = threading.RLock()
        self.processes = {}
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ocr')
        self.closing = False
        self.pipeline = None
        self.pending_pipelines = set()
        self.cancelled_pipelines = set()
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, kind TEXT, source TEXT, engine TEXT, state TEXT, created TEXT, error TEXT)')
            if 'language' not in {row[1] for row in conn.execute('PRAGMA table_info(jobs)')}:
                conn.execute("ALTER TABLE jobs ADD COLUMN language TEXT NOT NULL DEFAULT 'zh'")
            columns = {row[1] for row in conn.execute('PRAGMA table_info(jobs)')}
            for name, default in [('auto_mode','off'),('organize_state',''),('organize_stage',''),('organize_error','')]:
                if name not in columns:
                    conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
            conn.execute("UPDATE jobs SET state='interrupted', error='服务已重启，请重试' WHERE state IN ('queued','running')")
            conn.execute("UPDATE jobs SET organize_state='interrupted',organize_stage='服务已重启，可继续整理' WHERE organize_state IN ('waiting','queued','running')")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def list(self):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM jobs ORDER BY created DESC')]

    def get(self, job_id):
        if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
            raise KeyError(job_id)
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def update(self, job_id, state, error=''):
        with self.connect() as conn:
                conn.execute('UPDATE jobs SET state=?,error=? WHERE id=?', (state, error, job_id))

    def recover(self,job_id,settings):
        with self.lock:
            if self.closing:raise ValueError('服务正在停止')
            job=self.get(job_id)
            if job_id in self.pending_pipelines or job['state'] in ('queued','running'):
                raise ValueError('任务仍在运行，请等待当前操作结束')
            if job['state']=='succeeded':
                return self.queue_pipeline(job_id,job['auto_mode'] if job['auto_mode']!='off' else 'local',settings)
            if not (self.local/'jobs'/job_id/'raw.json').exists():
                raise ValueError('尚未保存原始素材，请使用重新识别重新采集')
            self.cancelled_pipelines.discard(job_id)
            self.update(job_id,'queued')
            self.pipeline_status(job_id,'waiting' if job['auto_mode']!='off' else '')
            if job['auto_mode']!='off':self.pending_pipelines.add(job_id)
            self.pool.submit(self.run,job_id,dict(settings,kind=job['kind'],source=job['source'],engine=job['engine'],
                language=job['language'],auto_mode=job['auto_mode'],folder=str(self.local/'jobs'/job_id),resume=True))
            return self.get(job_id)

    def submit(self, kind, source, engine, settings, image=None, language='zh', auto_mode='off'):
        with self.lock:
            if self.closing:
                raise ValueError('服务正在停止')
            job_id = uuid.uuid4().hex
            folder = self.local/'jobs'/job_id
            folder.mkdir(parents=True)
            if image is not None:
                (folder/'input.png').write_bytes(image)
            with self.connect() as conn:
                conn.execute('INSERT INTO jobs (id,kind,source,engine,state,created,error,language,auto_mode,organize_state) VALUES (?,?,?,?,?,?,?,?,?,?)',
                             (job_id, kind, source, engine, 'queued', datetime.now(timezone.utc).isoformat(), '', language,auto_mode,'waiting' if auto_mode!='off' else ''))
            spec = dict(settings, folder=str(folder), kind=kind, source=source, engine=engine, language=language,auto_mode=auto_mode)
            if auto_mode != 'off':
                self.pending_pipelines.add(job_id)
            self.pool.submit(self.run, job_id, spec)
            return self.get(job_id)

    def run(self, job_id, spec):
        folder = self.local/'jobs'/job_id
        with self.lock:
            if self.closing or self.get(job_id)['state'] != 'queued':
                self.pending_pipelines.discard(job_id)
                return
            self.update(job_id, 'running')
            try:
                proc = subprocess.Popen([sys.executable, '-B', '-m', 'app.worker'], cwd=ROOT,
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                self.processes[job_id] = proc
            except OSError:
                self.update(job_id, 'failed', '无法启动识别进程')
                if spec['auto_mode'] != 'off':
                    self.pipeline_status(job_id,'failed','识别失败，尚未整理')
                self.pending_pipelines.discard(job_id)
                return
        try:
            proc.communicate(json.dumps(spec).encode('utf-8'), timeout=1800)
            with self.lock:
                if self.get(job_id)['state'] == 'running':
                    error = folder/'error.txt'
                    if proc.returncode == 0 and (folder/'result.json').is_file():
                        self.update(job_id, 'succeeded')
                    else:
                        self.update(job_id, 'failed', error.read_text(encoding='utf-8') if error.exists() else '识别进程异常结束')
            if self.get(job_id)['state'] == 'succeeded' and spec['auto_mode'] != 'off':
                self.run_pipeline(job_id, spec['auto_mode'], spec)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            with self.lock:
                if self.get(job_id)['state'] == 'running':
                    self.update(job_id, 'failed', '任务超过 30 分钟，请缩小输入后重试')
        except Exception:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
            with self.lock:
                if self.get(job_id)['state'] == 'running':
                    self.update(job_id, 'failed', '任务执行失败')
        finally:
            with self.lock:
                self.processes.pop(job_id, None)
                self.pending_pipelines.discard(job_id)
                if self.get(job_id)['organize_state'] == 'waiting':
                    self.pipeline_status(job_id,'failed','识别失败，尚未整理')
            spec.pop('key', None)

    def pipeline_status(self, job_id, state, stage='', error=''):
        with self.connect() as conn:
            conn.execute('UPDATE jobs SET organize_state=?,organize_stage=?,organize_error=? WHERE id=?',
                         (state,stage,error,job_id))

    def check_pipeline(self, job_id):
        if self.closing or job_id in self.cancelled_pipelines or self.get(job_id)['organize_state'] == 'cancelled':
            raise PipelineCancelled()

    def queue_pipeline(self, job_id, mode, settings):
        with self.lock:
            job = self.get(job_id)
            if self.closing or job['state'] != 'succeeded' or job_id in self.pending_pipelines or job['organize_state'] in ('queued','running'):
                raise ValueError('任务尚未识别完成，或已在整理队列中')
            with self.connect() as conn:
                conn.execute('UPDATE jobs SET auto_mode=? WHERE id=?',(mode,job_id))
            self.pipeline_status(job_id,'queued','等待整理')
            self.pending_pipelines.add(job_id)
            self.cancelled_pipelines.discard(job_id)
            self.pool.submit(self.run_pipeline,job_id,mode,dict(settings))
        return self.get(job_id)

    def run_pipeline(self, job_id, mode, settings):
        marker = active_pipeline.set(job_id)
        try:
            self.check_pipeline(job_id)
            self.pipeline_status(job_id,'running','提取书单')
            state, summary = self.pipeline(job_id, mode, settings)
            self.check_pipeline(job_id)
            self.pipeline_status(job_id,state,summary)
        except PipelineCancelled:
            self.pipeline_status(job_id,'cancelled','整理已取消，已完成部分保留')
        except Exception as exc:
            message = str(exc)
            if settings.get('key'):
                message = message.replace(settings['key'],'[已隐藏]')
            self.pipeline_status(job_id,'failed','整理失败，可继续重试',message[:1000])
        finally:
            settings.pop('key',None)
            active_pipeline.reset(marker)
            with self.lock:
                self.pending_pipelines.discard(job_id)

    def cancel(self, job_id):
        with self.lock:
            job = self.get(job_id)
            if job['organize_state'] in ('waiting','queued','running'):
                self.cancelled_pipelines.add(job_id)
                self.pipeline_status(job_id,'cancelled','整理已取消，已完成部分保留')
            if job['state'] in ('queued', 'running'):
                self.update(job_id, 'cancelled')
                if job_id in self.processes and self.processes[job_id].poll() is None:
                    self.processes[job_id].kill()

    def close(self):
        with self.lock:
            self.closing = True
            for job in self.list():
                self.cancel(job['id'])
        self.pool.shutdown(wait=True, cancel_futures=True)
