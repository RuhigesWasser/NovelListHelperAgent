import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from PIL import Image
from app import image_books,organize
from app.paths import ROOT,add_tools
from app.recovery import Recovery
import test_organize
add_tools()
from llm_client import LlmOCR,fingerprint


class ImageBookTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'tmp');self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.image=self.folder/'image.png'
        Image.new('RGB',(300,1200),'white').save(self.image)
        self.result=[{'text':'','images':['布局变化，没有匹配模板']}];self.raw={'floors':[{'images':[{'file':str(self.image)}]}]}
        self.config={'base_url':'https://example.test/v1','model':'vision','recovery':{'mode':'vision','max_calls':3,'max_tokens':32768}}
        self.config['verification']={'ok':True,'fingerprint':fingerprint(self.config)}
    def recover(self):return Recovery(self.folder,self.config)
    def plan(self):return organize.extract(self.result,[17])

    def test_skipped_image_becomes_multiple_books_and_reuses_cache(self):
        response=json.dumps([{'title':'书一','author':'作者一'},{'title':'Book Two','author':'Author Two'}])
        recovery=self.recover()
        with patch.object(recovery,'ask',return_value=response) as ask:
            result=image_books.augment(self.plan(),self.result,[17],self.raw,self.folder,recovery)
            self.assertEqual(len(result['items']),2);self.assertFalse(result['skipped'])
            self.assertGreater(len(ask.call_args.args[2]),1)
            again=image_books.augment(result,self.result,[17],self.raw,self.folder,recovery)
            self.assertEqual(len(again['items']),2);self.assertEqual(ask.call_count,1)
            self.result[0]['images'][0]='校对后的文字'
            image_books.augment(result,self.result,[17],self.raw,self.folder,recovery)
            self.assertEqual(ask.call_count,2)

    def test_partial_book_and_archived_entry_are_preserved(self):
        old={'floor_index':0,'image_index':0,'floor':17,'title':'第一本','author':'确认的作者','platform':'all','category':'待分类','state':'archived','path':'old.md'}
        plan={'items':[old],'skipped':[]};before=copy.deepcopy(old)
        client=Mock();client.request.return_value=json.dumps([{'title':'第一本','author':'错误作者'},{'title':'第二本','author':'乙'}])
        result=image_books.augment(plan,self.result,[17],self.raw,self.folder,self.recover(),client)
        self.assertEqual(result['items'][0],before);self.assertEqual(len(result['items']),2)

    def test_invalid_response_and_budget_are_visible_without_erasing_local_result(self):
        for response in ('not json','[{"title":42}]',None):
            recovery=self.recover()
            with patch.object(recovery,'ask',return_value=response):
                result=image_books.augment(self.plan(),self.result,[17],self.raw,self.folder,recovery)
                self.assertEqual(len(result['skipped']),1);self.assertTrue(result['skipped'][0]['reason'])

    def test_text_mode_sends_no_images(self):
        self.config['recovery']['mode']='text';recovery=self.recover()
        with patch.object(recovery,'ask',return_value='[]') as ask:
            image_books.augment(self.plan(),self.result,[17],self.raw,self.folder,recovery)
        self.assertIsNone(ask.call_args.args[2])

    def test_one_book_title_disagreement_is_verified_as_alternatives(self):
        local=organize.extract([{'text':'','images':['书名：转生精灵的我才不会屈从现状！\n作者：云胜不知处']}],[17])
        alternate={**local['items'][0],'title':'转生精灵的我才会屈从现状！'}
        image_books.merge(local,[alternate],0,0)
        self.assertEqual(len(local['items']),1)
        self.assertEqual(local['items'][0]['alternative_titles'],[alternate['title']])
        confirmed={**local['items'][0],'state':'verified','book':{'url':'https://book.sfacg.com/novel/1/'}}
        with patch('app.organize.verify_query',side_effect=[confirmed,{'state':'review'}]):
            self.assertEqual(organize.verify(local['items'][0])['state'],'verified')

    def test_wrong_platform_falls_back_to_official_cross_platform_search(self):
        item={'title':'书','author':'作者','platform':'ciweimao'}
        good={**item,'platform':'all','state':'verified','book':{'url':'https://book.sfacg.com/novel/1/'}}
        with patch('app.organize.verify_query',side_effect=[{'state':'review'},good]) as verify:
            self.assertEqual(organize.verify(item),good)
            self.assertEqual(verify.call_args.args[0]['platform'],'all')

    def test_image_protocols_keep_every_crop(self):
        for protocol in ('chat_completions','responses','anthropic','gemini','ollama'):
            client=LlmOCR('https://example.test','model',protocol=protocol)
            body=json.dumps(client.payload('read',[b'one',b'two']))
            self.assertIn('b25l',body);self.assertIn('dHdv',body)

    def test_labelled_layouts_and_spatial_columns(self):
        for text in ('书名：第一本\n作者：甲\n书名：第二本\n作者：乙','Title: First Book\nAuthor: Alice\nTitle: Second Book\nAuthor: Bob','書名：作品甲\n作者：作者甲\n書名：作品乙\n作者：作者乙'):
            self.assertEqual(len(organize.extract([{'text':'','images':[text]}],[1])['items']),2)
        def box(text,x,y):return {'text':text,'box':[[x,y],[x+120,y],[x+120,y+20],[x,y+20]]}
        layout=[box('第一本',0,0),box('第二本',250,0),box('作者：甲',0,40),box('作者：乙',250,40)]
        hints=organize.layout_hints(layout)
        self.assertEqual([(h['title'],h['author']) for h in hints],[('第一本','甲'),('第二本','乙')])


class ImageBookRoutesTests(unittest.TestCase):
    setUp=test_organize.PlanTests.setUp
    post=test_organize.PlanTests.post
    make_job=test_organize.PlanTests.make_job

    def test_automatic_fallback_handles_previously_skipped_image(self):
        route=self.make_job();job_id=route.split('/')[3];folder=self.local/'jobs'/job_id
        Image.new('RGB',(30,50),'white').save(folder/'input.png')
        (folder/'result.json').write_text(json.dumps([{'text':'','images':['无法通过规则识别的截图']}]),encoding='utf8')
        (self.local/'recovery-settings.json').write_text('{"mode":"vision"}')
        config={'base_url':'https://example.test','model':'vision','recovery':{'mode':'vision'}}
        config['verification']={'ok':True,'fingerprint':fingerprint(config)}
        with patch('app.llm_settings.LlmSettings.current',return_value=config),patch('app.recovery.Recovery.ask',return_value='[{"title":"模型读到的书","author":"作者"}]') as ask:
            response=self.post(route+'/extract',{'method':'local'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['items'],[])
            self.assertEqual(ask.call_count,0)
            with patch('app.organize.verify',side_effect=lambda item:{**item,'state':'review','reason':'需要选择候选'}):
                from app.jobs import active_pipeline
                token=active_pipeline.set(job_id)
                try:state,stage=self.app.state.jobs.pipeline(job_id,'local',config)
                finally:active_pipeline.reset(token)
            result=self.client.get(route,headers=self.headers).json()
            self.assertEqual(result['items'][0]['extraction'],'vision')
            self.assertEqual(result['skipped'],[])
            self.assertEqual(ask.call_count,1)
            self.assertEqual(state,'review')
