import json
import io
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
from app.paths import ROOT,add_tools
from app import organize,providers
from app.recovery import Recovery,recognize_images
import test_app
add_tools()


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp');self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.config={'key':'hidden-test-key','recovery':{'mode':'text','max_calls':3,'max_tokens':512}}

    def test_worker_keeps_raw_when_engine_initialization_fails(self):
        from app import worker
        (self.folder/'input.png').write_bytes(b'image')
        spec={'folder':str(self.folder),'kind':'image','engine':'builtin'}
        with patch('sys.stdin',io.StringIO(json.dumps(spec))),patch('ocr.BuiltinOCR',side_effect=RuntimeError('引擎不可用')):
            self.assertEqual(worker.main(),1)
        self.assertTrue((self.folder/'raw.json').exists())

    def test_partial_ocr_preserved_and_only_failed_image_retried(self):
        files=[self.folder/f'{i}.png' for i in range(3)]
        for i,file in enumerate(files):file.write_bytes(str(i).encode())
        raw={'floors':[{'text':'楼层正文','images':[{'file':str(p)} for p in files]}]}
        engine=Mock(side_effect=['first',RuntimeError('failed hidden-test-key'),'third'])
        recovery=Recovery(self.folder,self.config)
        self.assertEqual(recognize_images(raw,engine,self.folder,recovery),1)
        progress=(self.folder/'ocr-progress.json').read_text(encoding='utf8')
        self.assertNotIn('hidden-test-key',progress)
        self.assertIn('third',progress)
        retry=Mock(return_value='second')
        self.assertEqual(recognize_images(raw,retry,self.folder,recovery),0)
        retry.assert_called_once_with(files[1])
        self.assertEqual(json.loads((self.folder/'result.json').read_text(encoding='utf8'))[0]['images'],['first','second','third'])

    def test_identical_images_use_one_ocr_call(self):
        a=self.folder/'a';b=self.folder/'b';a.write_bytes(b'same');b.write_bytes(b'same')
        raw={'floors':[{'images':[{'file':str(a)},{'file':str(b)}]}]}
        engine=Mock(return_value='same text')
        recognize_images(raw,engine,self.folder,Recovery(self.folder,{}))
        engine.assert_called_once()

    def test_json_repair_and_budget_persist(self):
        response=json.dumps([{'floor_index':0,'image_index':0,'title':'测试小说'}])
        first=Mock();first.request.return_value='bad JSON'
        repair=Mock();repair.request.return_value=response
        config={**self.config,'recovery':{'mode':'text','max_calls':1,'max_tokens':512}}
        with patch('llm_client.LlmOCR.from_config',return_value=repair):
            recovery=Recovery(self.folder,config)
            plan=organize.extract_llm([{'text':'','images':['测试小说']}],[17],first,recovery)
            self.assertEqual(plan['items'][0]['floor'],17)
            restored=Recovery(self.folder,config)
            self.assertIsNone(restored.ask('search','anything'))
        repair.request.assert_called_once()
        self.assertEqual(restored.state['calls'],1)

    def test_text_mode_does_not_send_images(self):
        with patch('llm_client.LlmOCR.from_config') as client:
            recovery=Recovery(self.folder,self.config)
            self.assertIsNone(recovery.ask('reocr','image',b'image'))
            self.assertIsNone(recovery.read_image(self.folder/'missing'))
        client.assert_not_called()

    def test_network_retry_is_bounded_and_does_not_retry_permissions(self):
        recovery=Recovery(self.folder,self.config)
        query=Mock(side_effect=[providers.ProviderError('站点连接失败'),{'state':'review'}])
        self.assertEqual(recovery.lookup({},query),{'state':'review'})
        self.assertEqual(query.call_count,2)
        self.assertEqual(recovery.state['calls'],0)
        forbidden=Mock(side_effect=providers.ProviderError('账号权限不足'))
        with self.assertRaises(providers.ProviderError):recovery.lookup({},forbidden)
        forbidden.assert_called_once()

    def test_query_repair_uses_official_verification(self):
        item={'title':'测试小兑','author':'甲','platform':'sfacg','state':'review','reason':'未匹配'}
        book=providers.record('sfacg',1,'测试小说','https://book.sfacg.com/novel/1/',author='甲')
        model=Mock();model.request.return_value=json.dumps({'action':'search','title':'测试小说','author':'甲','platform':'sfacg'})
        with patch('llm_client.LlmOCR.from_config',return_value=model),patch('app.providers.search',return_value={'items':[providers.match(book,'测试小说','甲')]}),patch('app.providers.detail',return_value=book):
            result=Recovery(self.folder,self.config).verify_book(item,'测试小说\n甲',organize.verify)
        self.assertEqual(result['state'],'verified')
        self.assertEqual(result['recovery_original']['title'],'测试小兑')

    def test_arbitrary_action_and_invented_author_are_not_executed(self):
        for proposal in [{'action':'shell','command':'anything'}, {'action':'search','title':'测试小说','author':'候选作者','platform':'sfacg'}]:
            model=Mock();model.request.return_value=json.dumps(proposal)
            verify=Mock()
            with patch('llm_client.LlmOCR.from_config',return_value=model):
                item={'title':'测试小兑','author':'','platform':'sfacg','state':'review'}
                result=Recovery(self.folder,self.config).verify_book(item,'测试小兑',verify)
            verify.assert_not_called();self.assertEqual(result,item)

    def test_agent_can_request_image_then_search_with_shared_budget(self):
        from PIL import Image
        image=self.folder/'image.png';Image.new('RGB',(50,50),'white').save(image)
        model=Mock();model.request.side_effect=[json.dumps({'action':'reocr'}),'测试小说\n甲',
            json.dumps({'action':'search','title':'测试小说','author':'甲','platform':'sfacg'})]
        config={**self.config,'recovery':{'mode':'vision','max_calls':3,'max_tokens':512}}
        from llm_client import fingerprint
        config['verification']={'ok':True,'fingerprint':fingerprint(config)}
        item={'title':'测试小兑','author':'','platform':'sfacg','state':'review'}
        with patch('llm_client.LlmOCR.from_config',return_value=model):
            result=Recovery(self.folder,config).verify_book(item,'测试小兑',lambda value:{**value,'state':'verified'},image)
        self.assertEqual(result['state'],'verified')
        self.assertEqual(model.request.call_count,3)
        self.assertIsInstance(model.request.call_args_list[1].args[1],bytes)
        self.assertIn('甲',result['recovery_ocr'])


class RecoveryRoutesTests(unittest.TestCase):
    setUp=test_app.AppTests.setUp
    post=test_app.AppTests.post

    def test_legacy_result_count_and_missing_image(self):
        jobs=self.app.state.jobs
        with patch.object(jobs.pool,'submit'):job=jobs.submit('image','legacy','builtin',{})
        folder=self.local/'jobs'/job['id']
        (folder/'raw.json').write_text(json.dumps({'floors':[{'images':[{'file':str(folder/'missing.png')}]}]}),encoding='utf8')
        (folder/'result.json').write_text(json.dumps([{'text':'','images':['saved text']}]),encoding='utf8')
        jobs.update(job['id'],'succeeded')
        status=self.client.get(f'/api/jobs/{job["id"]}/recovery',headers=self.headers).json()
        self.assertEqual(status['total_images'],1)
        self.assertEqual(status['ocr']['images']['0:0']['state'],'succeeded')
        self.assertEqual(self.client.get(f'/api/jobs/{job["id"]}/image/0/0',headers=self.headers).status_code,404)

    def test_resume_queues_same_job_with_raw_and_checkpoint(self):
        jobs=self.app.state.jobs
        with patch.object(jobs.pool,'submit'):
            job=jobs.submit('image','source','builtin',{},b'image')
        folder=self.local/'jobs'/job['id'];(folder/'raw.json').write_text('{"floors":[]}',encoding='utf8')
        (folder/'ocr-progress.json').write_text('{"images":{}}',encoding='utf8')
        jobs.update(job['id'],'failed','failed image')
        with patch.object(jobs.pool,'submit') as queued:
            response=self.post(f'/api/jobs/{job["id"]}/recover',{})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['id'],job['id'])
        self.assertTrue(queued.call_args.args[2]['resume'])
        self.assertTrue((folder/'ocr-progress.json').exists())

    def test_no_raw_requires_explicit_recapture(self):
        jobs=self.app.state.jobs
        with patch.object(jobs.pool,'submit'):job=jobs.submit('tieba','123','builtin',{})
        jobs.update(job['id'],'failed')
        self.assertEqual(self.post(f'/api/jobs/{job["id"]}/recover',{}).status_code,409)

    def test_real_worker_resumes_partial_ocr_without_fetching_thread(self):
        from PIL import Image,ImageDraw,ImageFont
        jobs=self.app.state.jobs
        with patch.object(jobs.pool,'submit'):job=jobs.submit('tieba','invalid-id-no-network','builtin',{})
        folder=self.local/'jobs'/job['id']
        first,second=folder/'first.png',folder/'second.png'
        def make(path,text):
            image=Image.new('RGB',(600,160),'white')
            ImageDraw.Draw(image).text((30,45),text,font=ImageFont.load_default(size=42),fill='black')
            image.save(path)
        make(first,'FIRST BOOK');second.write_bytes(b'broken-image')
        raw={'floors':[{'floor':17,'text':'','images':[{'file':str(first)},{'file':str(second)}]}]}
        (folder/'raw.json').write_text(json.dumps(raw),encoding='utf8');jobs.update(job['id'],'failed')
        def resume():
            self.assertEqual(self.post(f'/api/jobs/{job["id"]}/recover',{}).status_code,200)
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                current=jobs.get(job['id'])
                if current['state'] not in ('queued','running'):return current
                time.sleep(.1)
            self.fail('OCR worker timeout')
        self.assertEqual(resume()['state'],'failed')
        status=self.client.get(f'/api/jobs/{job["id"]}/recovery',headers=self.headers).json()
        self.assertEqual(status['ocr']['images']['0:0']['state'],'succeeded')
        self.assertEqual(status['ocr']['images']['0:1']['state'],'failed')
        self.assertEqual(status['floors'],[17])
        partial=self.client.get(f'/api/jobs/{job["id"]}/result',headers=self.headers).json()
        self.assertIn('FIRST',partial['result'][0]['images'][0])
        make(second,'SECOND BOOK')
        self.assertEqual(resume()['state'],'succeeded')
        result=json.loads((folder/'result.json').read_text(encoding='utf8'))
        self.assertIn('SECOND',result[0]['images'][1])

    def test_http_model_query_repair_archives_in_background(self):
        from test_llm import service
        jobs=self.app.state.jobs
        with patch.object(jobs.pool,'submit'):job=jobs.submit('image','sample','builtin',{},b'image')
        folder=self.local/'jobs'/job['id']
        (folder/'raw.json').write_text(json.dumps({'floors':[{'floor':1,'images':[{'file':str(folder/'input.png')}]}]}),encoding='utf8')
        (folder/'result.json').write_text(json.dumps([{'text':'','images':['测试小兑\nVIP\n校园\n测试作者\n1万字\n月票\n点赞']}]),encoding='utf8')
        jobs.update(job['id'],'succeeded')
        book=providers.record('sfacg',1,'测试小说','https://book.sfacg.com/novel/1/',author='测试作者')
        action=json.dumps({'action':'search','title':'测试小说','author':'测试作者','platform':'sfacg'})
        with service('chat_completions',text=action) as (url,calls):
            self.post('/api/settings',{'base_url':url,'model':'test','auth':'none','extra_body':{'max_tokens':9999}})
            self.assertEqual(self.post('/api/recovery/settings',{'mode':'text','max_calls':2,'max_tokens':512}).status_code,200)
            def search(platform,title,author):
                return {'items':[providers.match(book,title,author)] if title=='测试小说' else []}
            with patch('app.providers.search',side_effect=search),patch('app.providers.detail',return_value=book):
                self.post(f'/api/jobs/{job["id"]}/recover',{})
                for _ in range(200):
                    state=jobs.get(job['id'])
                    if state['organize_state'] not in ('queued','running'):break
                    time.sleep(.02)
            self.assertEqual(state['organize_state'],'succeeded',state)
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0]['body']['max_tokens'],512)
        self.assertTrue((self.local/'library/校园/测试小说/测试小说.md').exists())
        log=json.loads((folder/'recovery.json').read_text(encoding='utf8'))
        self.assertEqual(log['calls'],1)
