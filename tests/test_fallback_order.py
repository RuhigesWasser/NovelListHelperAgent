import json
import unittest
from unittest.mock import patch,Mock
from PIL import Image
import test_organize
from app import providers
from app.jobs import active_pipeline


class FallbackOrderTests(unittest.TestCase):
    setUp=test_organize.PlanTests.setUp
    post=test_organize.PlanTests.post
    make_job=test_organize.PlanTests.make_job

    def run_flow(self,job_id,config):
        token=active_pipeline.set(job_id)
        try:return self.app.state.jobs.pipeline(job_id,'local',config)
        finally:active_pipeline.reset(token)

    def setup_job(self):
        route=self.make_job();job_id=route.split('/')[3]
        folder=self.local/'jobs'/job_id
        Image.new('RGB',(100,100)).save(folder/'input.png')
        return route,job_id,folder

    def test_successful_ocr_is_not_sent_to_model(self):
        route,job_id,folder=self.setup_job()
        book=providers.record('sfacg',1,'书名','https://book.sfacg.com/novel/1/',author='作者')
        with patch('app.organize.verify',side_effect=lambda item:{**item,'state':'verified','book':book}),patch('app.recovery.Recovery.ask') as ask:
            state,_=self.run_flow(job_id,{'base_url':'https://example.test','model':'vision','recovery':{'mode':'vision'}})
        self.assertEqual(state,'succeeded');ask.assert_not_called()

    def test_only_failed_image_uses_vision_after_ocr_verification(self):
        from llm_client import fingerprint
        route,job_id,folder=self.setup_job()
        (folder/'raw.json').write_text(json.dumps({'floors':[{'floor':17,'images':[{'file':str(folder/'input.png')},{'file':str(folder/'input.png')}]}]}),encoding='utf8')
        (folder/'result.json').write_text(json.dumps([{'text':'','images':['书名\nVIP\n校园\n作者\n1万字\n月票\n点赞','陌生布局']}]),encoding='utf8')
        config={'base_url':'https://example.test','model':'vision','recovery':{'mode':'vision'}}
        config['verification']={'ok':True,'fingerprint':fingerprint(config)}
        calls=[]
        def verify(item):
            calls.append('verify:'+item['title'])
            book=providers.record('sfacg',item['image_index']+1,item['title'],f'https://book.sfacg.com/novel/{item["image_index"]+1}/',author=item['author'])
            return {**item,'state':'verified','book':book}
        def model(*args,**kwargs):calls.append('vision');return '[{"title":"第二本","author":"第二作者"}]'
        with patch('app.organize.verify',side_effect=verify),patch('app.recovery.Recovery.ask',side_effect=model) as ask:
            state,_=self.run_flow(job_id,config)
        self.assertEqual(calls,['verify:书名','vision','verify:第二本'])
        self.assertEqual(state,'succeeded');self.assertEqual(ask.call_count,1)

    def test_unconfigured_or_disabled_model_leaves_candidates_and_hint(self):
        for config in ({},{'recovery':{'mode':'vision'}},{'base_url':'https://example.test','model':'vision','recovery':{'mode':'off'}}):
            route,job_id,folder=self.setup_job()
            candidate={'title':'近似书名','author':'作者','url':'https://book.sfacg.com/novel/1/'}
            with patch('app.organize.verify',side_effect=lambda item:{**item,'state':'review','reason':'仅近似匹配','candidates':[candidate]}),patch('app.recovery.Recovery.ask') as ask:
                state,_=self.run_flow(job_id,config)
            plan=self.client.get(route,headers=self.headers).json()
            self.assertEqual(state,'review');ask.assert_not_called()
            self.assertEqual(plan['items'][0]['candidates'],[candidate]);self.assertIn('配置多模态 LLM',plan['review_notice'])

    def test_failed_vision_keeps_candidates_for_final_manual_review(self):
        from llm_client import fingerprint
        route,job_id,folder=self.setup_job()
        config={'base_url':'https://example.test','model':'vision','recovery':{'mode':'vision'}}
        config['verification']={'ok':True,'fingerprint':fingerprint(config)}
        candidate={'title':'近似书名','author':'作者'}
        with patch('app.organize.verify',side_effect=lambda item:{**item,'state':'review','reason':'仅近似匹配','candidates':[candidate]}),patch('app.recovery.Recovery.ask',return_value=None) as ask:
            state,_=self.run_flow(job_id,config)
        plan=self.client.get(route,headers=self.headers).json()
        self.assertEqual(state,'review');self.assertEqual(ask.call_count,1)
        self.assertEqual(plan['items'][0]['candidates'],[candidate]);self.assertTrue(plan['items'][0]['fallback_error'])
        self.assertEqual(plan['skipped'],[])

    def test_partial_ocr_failure_continues_automatic_pipeline(self):
        route,job_id,folder=self.setup_job();jobs=self.app.state.jobs
        jobs.update(job_id,'queued');(folder/'error.txt').write_text('一张图片 OCR 失败',encoding='utf8')
        process=Mock(returncode=2)
        with patch('app.jobs.subprocess.Popen',return_value=process),patch.object(jobs,'run_pipeline') as pipeline:
            jobs.run(job_id,{'auto_mode':'local'})
        self.assertEqual(jobs.get(job_id)['state'],'succeeded')
        self.assertIn('OCR 失败',jobs.get(job_id)['error']);pipeline.assert_called_once()

    def test_multi_book_setting_is_persistent_and_default_off(self):
        self.assertFalse(self.client.get('/api/organize/settings',headers=self.headers).json()['auto_multi_book'])
        self.assertEqual(self.post('/api/organize/settings',{'auto_multi_book':True}).status_code,200)
        self.assertTrue(json.loads((self.local/'organize-settings.json').read_text())['auto_multi_book'])
        self.assertTrue(self.client.get('/api/organize/settings',headers=self.headers).json()['auto_multi_book'])

    def multi_job(self):
        route,job_id,folder=self.setup_job()
        (folder/'result.json').write_text(json.dumps([{'text':'','images':['书名：甲书\n作者：甲作者\n书名：乙书\n作者：乙作者']}]),encoding='utf8')
        return route,job_id

    def test_multi_book_off_requires_individual_choice(self):
        route,job_id=self.multi_job()
        with patch('app.organize.verify') as verify,patch('app.recovery.Recovery.ask') as ask:
            state,stage=self.run_flow(job_id,{})
        verify.assert_not_called();ask.assert_not_called();self.assertEqual(state,'review')
        self.app.state.jobs.pipeline_status(job_id,state,stage)
        plan=self.client.get(route,headers=self.headers).json();self.assertEqual(len(plan['items']),2)
        self.assertTrue(all(item['manual_selection_required'] for item in plan['items']))
        first=plan['items'][0]
        book=providers.record('sfacg',1,first['title'],'https://book.sfacg.com/novel/1/',author=first['author'])
        with patch('app.organize.verify',side_effect=lambda item:{**item,'state':'verified','book':book}):
            response=self.post(route+'/0/verify',first)
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['user_selected'])
        archived=self.post(route+'/archive',{}).json()
        self.assertEqual([item['state'] for item in archived['items']],['archived','review'])

    def test_multi_book_on_archives_all_verified_books(self):
        route,job_id=self.multi_job()
        def verify(item):
            book=providers.record('sfacg',1,item['title'],'https://book.sfacg.com/novel/'+('1/' if item['title']=='甲书' else '2/'),author=item['author'])
            return {**item,'state':'verified','book':book}
        with patch('app.organize.verify',side_effect=verify):state,_=self.run_flow(job_id,{'auto_multi_book':True})
        self.assertEqual(state,'succeeded')
        plan=self.client.get(route,headers=self.headers).json()
        self.assertTrue(all(item['state']=='archived' for item in plan['items']))

    def test_multimodal_discovers_multiple_books_but_does_not_archive_when_off(self):
        from llm_client import fingerprint
        route,job_id,folder=self.setup_job()
        (folder/'result.json').write_text('[{"text":"","images":[""]}]',encoding='utf8')
        config={'base_url':'https://example.test','model':'vision','recovery':{'mode':'vision'}}
        config['verification']={'ok':True,'fingerprint':fingerprint(config)}
        with patch('app.recovery.Recovery.ask',return_value='[{"title":"甲书","author":"甲"},{"title":"乙书","author":"乙"}]'),patch('app.organize.verify') as verify:
            state,_=self.run_flow(job_id,config)
        verify.assert_not_called();self.assertEqual(state,'review')

    def test_manually_selected_book_can_use_fallback_without_selecting_others(self):
        from llm_client import fingerprint
        route,job_id=self.multi_job();state,stage=self.run_flow(job_id,{})
        self.app.state.jobs.pipeline_status(job_id,state,stage)
        first=self.client.get(route,headers=self.headers).json()['items'][0]
        def review(item):return {**item,'state':'review','reason':'仍需核对'}
        with patch('app.organize.verify',side_effect=review):self.post(route+'/0/verify',first)
        config={'base_url':'https://example.test','model':'vision','recovery':{'mode':'vision'}}
        config['verification']={'ok':True,'fingerprint':fingerprint(config)}
        with patch('app.organize.verify',side_effect=review) as verify,patch('app.recovery.Recovery.ask',return_value='[]') as ask:
            self.run_flow(job_id,config)
        self.assertEqual(ask.call_count,1)
        self.assertTrue(all(call.args[0]['title']=='甲书' for call in verify.call_args_list))
