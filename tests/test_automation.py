import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
import test_app
from app import providers
from app.jobs import Jobs
from app.esj_session import ESJSession, current_session


class WorkflowTests(unittest.TestCase):
    setUp = test_app.AppTests.setUp
    post = test_app.AppTests.post

    def ready_job(self, title='自动样例'):
        jobs=self.app.state.jobs
        with patch.object(jobs.pool,'submit'):
            job=jobs.submit('image','自动化样例','builtin',{},b'image')
        folder=self.local/'jobs'/job['id']
        (folder/'raw.json').write_text(json.dumps({'floors':[{'floor':1,'images':[{'file':str(folder/'input.png')}]}]}),encoding='utf8')
        (folder/'result.json').write_text(json.dumps([{'text':'','images':[f'{title}\nVIP\n科幻|\n测试作者\n1万字\n月票\n点赞']}]),encoding='utf8')
        jobs.update(job['id'],'succeeded')
        return job['id']

    def wait(self, job_id):
        for _ in range(150):
            job=self.app.state.jobs.get(job_id)
            if job['organize_state'] not in ('queued','running'):return job
            time.sleep(.02)
        self.fail('workflow did not finish')

    def test_background_archive_and_repeat_keeps_existing_files(self):
        job_id=self.ready_job()
        book=providers.record('sfacg',1,'自动样例','https://book.sfacg.com/novel/1/',author='测试作者',intro='原文')
        with patch('app.providers.search',return_value={'items':[providers.match(book,'自动样例','测试作者')]}),patch('app.providers.detail',return_value=book):
            response=self.post(f'/api/jobs/{job_id}/organize',{})
            self.assertEqual(response.status_code,200)
            self.assertEqual(self.wait(job_id)['organize_state'],'succeeded')
            file=self.local/'library/科幻/自动样例/自动样例.md'
            file.write_text('用户补写评语',encoding='utf8')
            second=self.ready_job()
            self.post(f'/api/jobs/{second}/organize',{})
            self.assertEqual(self.wait(second)['organize_state'],'succeeded')
        self.assertEqual(file.read_text(encoding='utf8'),'用户补写评语')
        plan=json.loads((self.local/'jobs'/second/'books.json').read_text(encoding='utf8'))
        self.assertTrue(plan['items'][0]['existing'])

    def test_one_lookup_failure_is_review_and_can_resume(self):
        job_id=self.ready_job()
        with patch('app.providers.search',side_effect=providers.ProviderError('站点超时')):
            self.post(f'/api/jobs/{job_id}/organize',{})
            self.assertEqual(self.wait(job_id)['organize_state'],'review')
        plan=self.client.get(f'/api/jobs/{job_id}/books',headers=self.headers).json()
        self.assertIn('站点超时',plan['items'][0]['reason'])
        self.assertEqual(list((self.local/'library').glob('*/*/*.md')),[])

    def test_cancel_running_lookup_prevents_archive_and_blocks_manual_edits(self):
        job_id=self.ready_job()
        entered,release=threading.Event(),threading.Event()
        def lookup(*args):
            entered.set();release.wait(3)
            return {'items':[]}
        with patch('app.providers.search',side_effect=lookup):
            self.post(f'/api/jobs/{job_id}/organize',{})
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.post(f'/api/jobs/{job_id}/books/extract',{}).status_code,409)
            self.assertEqual(self.post(f'/api/jobs/{job_id}/organize',{}).status_code,409)
            self.post(f'/api/jobs/{job_id}/cancel',{})
            self.assertEqual(self.post(f'/api/jobs/{job_id}/organize',{}).status_code,409)
            self.assertEqual(self.post(f'/api/jobs/{job_id}/books/extract',{}).status_code,409)
            release.set()
            self.app.state.jobs.pool.submit(lambda:None).result(timeout=3)
        self.assertEqual(self.app.state.jobs.get(job_id)['organize_state'],'cancelled')
        self.assertEqual(list((self.local/'library').glob('*/*/*.md')),[])

    def test_ocr_completion_triggers_workflow(self):
        jobs=self.app.state.jobs
        with patch.object(jobs.pool,'submit'):
            job=jobs.submit('image','source','builtin',{},b'image',auto_mode='local')
        folder=self.local/'jobs'/job['id']
        (folder/'result.json').write_text('[]',encoding='utf8')
        seen=[];jobs.pipeline=lambda *args:(seen.append(args[0]) or ('succeeded','已归档'))
        with patch('app.jobs.subprocess.Popen') as process:
            process.return_value.returncode=0
            jobs.run(job['id'],{'auto_mode':'local'})
        self.assertEqual(seen,[job['id']])
        self.assertEqual(jobs.get(job['id'])['organize_state'],'succeeded')

    def test_restart_marks_workflow_interrupted(self):
        job_id=self.ready_job()
        self.app.state.jobs.pipeline_status(job_id,'running','核对')
        other=Jobs(self.local)
        try:self.assertEqual(other.get(job_id)['organize_state'],'interrupted')
        finally:other.close()

    def test_esj_session_clears_and_never_enters_settings(self):
        self.app.state.esj_session.connected=True
        status=self.client.get('/api/esj/session',headers=self.headers).json()
        self.assertEqual(status,{'connected':True,'storage':'memory_only','access_notice':''})
        with patch.object(self.app.state.esj_session,'login',return_value=status) as login:
            response=self.post('/api/esj/session',{'email':'test@example.invalid','password':'test-secret'})
        self.assertNotIn('test-secret',response.text)
        self.assertNotIn('test@example.invalid',response.text)
        self.assertEqual(login.call_args.args,('test@example.invalid','test-secret'))
        self.assertFalse((self.local/'settings.json').exists())
        self.client.delete('/api/esj/session',headers=self.headers)
        self.assertFalse(self.app.state.esj_session.connected)
        self.assertEqual(len(self.app.state.esj_session.jar),0)

    def test_session_is_used_in_background_context(self):
        job_id=self.ready_job()
        def lookup(*args):
            self.assertIs(current_session.get(),self.app.state.esj_session)
            return {'items':[]}
        with patch('app.providers.search',side_effect=lookup):
            self.post(f'/api/jobs/{job_id}/organize',{})
            self.assertEqual(self.wait(job_id)['organize_state'],'review')
