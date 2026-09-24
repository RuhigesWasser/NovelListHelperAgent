import json
import unittest
from unittest.mock import Mock, patch
from app import organize, providers
import test_app


class ExtractionTests(unittest.TestCase):
    def test_compact_sfacg_header_without_vote_counters(self):
        for metadata in ('连载中|校园|16万字','连载中1校园|16万字','连载中｜校园｜16万字','连载中|校园116万字','连载中|校园16万字'):
            hint=organize.image_hint('测试小说的\n第二行\nVIP\n'+metadata+'\nEnglishAuthor\n这是简介，不是书名')
            self.assertEqual((hint['title'],hint['author'],hint['platform'],hint['category']),('测试小说的第二行','EnglishAuthor','sfacg','校园'))
        plan=organize.extract([{'text':'','images':['']}],[1])
        self.assertIn('未识别到文字',plan['skipped'][0]['reason'])
    def test_unarchived_reasons_and_floor_links(self):
        raw={'floors':[{'floor':17,'pid':153897201634,'page':1}]}
        plan={'items':[{'floor_index':0,'state':'review','warnings':['公开搜索只返回原创作品']}],
              'skipped':[{'floor_index':0,'reason':'没有书名'}]}
        output=organize.attach_sources(plan,{'kind':'tieba','source':'https://tieba.baidu.com/p/10983604857'},raw)
        self.assertIn('原创',output['items'][0]['reason'])
        self.assertEqual(output['items'][0]['source_url'],'https://tieba.baidu.com/p/10983604857?pid=153897201634#153897201634')
        self.assertEqual(output['skipped'][0]['source_url'],output['items'][0]['source_url'])
        old=organize.attach_sources({'items':[{'floor_index':0,'state':'draft'}]},
            {'kind':'tieba','source':'123'},{'floors':[{'floor':31,'page':2}]})
        self.assertTrue(old['items'][0]['source_url'].endswith('?pn=2'))
        self.assertIn('所在页',old['items'][0]['source_label'])

    def test_cover_fragments_and_ad_are_not_extra_books(self):
        text = '18:23\n冒牌侦探小姐又带着神父诈\n冒牌侦探小姐\n又带着神父诈骗了\n骗了！\nVIP\n小薄ovo\n魔幻|\n小苒ovo\n119万字\n连载中\n月票>\n点赞'
        result = organize.extract([{'text':'', 'images':[text, 'NAKAMASAICHIKA\nNO.223'] }], [17])
        self.assertEqual(len(result['items']), 1)
        item = result['items'][0]
        self.assertEqual(item['title'], '冒牌侦探小姐又带着神父诈骗了！')
        self.assertEqual(item['author'], '小苒ovo')
        self.assertEqual(item['floor'], 17)
        self.assertEqual(len(result['skipped']), 1)

    def test_fanqie_ignores_recommendations_and_esj_count(self):
        text = '已加书架\n当器灵的那些年\n当器灵的那些年\n连载中·33.6万字\n清风牧月\n简介\n番茄原创\n东方仙侠\n读这本书的人还在读\n其他小说'
        self.assertEqual(organize.image_hint(text)['title'], '当器灵的那些年')
        self.assertEqual(organize.image_hint(text)['platform'], 'fanqie')
        self.assertEqual(organize.image_hint('百297,131\n奥术朋克中的狙击手想要愉\n悦\nesjzone.one')['title'], '奥术朋克中的狙击手想要愉悦')

    def test_ambiguous_or_author_missing_never_auto_verifies(self):
        item = {'title':'同名书','author':'作者','platform':'all'}
        book = providers.record('sfacg', 1, '同名书', 'https://book.sfacg.com/novel/1/', author='作者')
        exact = providers.match(book, '同名书', '作者')
        for candidates in ([exact,exact], [providers.match(book,'同名书')], []):
            with patch('app.providers.search',return_value={'items':candidates}),patch('app.providers.detail') as detail:
                self.assertEqual(organize.verify(item)['state'], 'review')
                detail.assert_not_called()
        with patch('app.providers.search',return_value={'items':[exact]}),patch('app.providers.detail',return_value={**book,'author':'不同作者'}):
            self.assertEqual(organize.verify(item)['state'], 'review')

    def test_llm_schema_and_missing_image(self):
        client=Mock()
        client.request.return_value='```json\n[{"floor_index":0,"image_index":0,"title":"书名"}]\n```'
        result=organize.extract_llm([{'text':'','images':['OCR','illustration']}],[9],client)
        self.assertEqual(result['items'][0]['floor'],9)
        self.assertEqual(len(result['skipped']),1)
        client.request.return_value='[{"floor_index":-1,"image_index":0,"title":"bad"}]'
        with self.assertRaises(ValueError):
            organize.extract_llm([{'text':'','images':['OCR']}],[9],client)


class PlanTests(unittest.TestCase):
    setUp = test_app.AppTests.setUp
    post = test_app.AppTests.post

    def make_job(self):
        with patch.object(self.app.state.jobs.pool, 'submit'):
            job=self.app.state.jobs.submit('image','real source','builtin',{},b'image')
        folder=self.local/'jobs'/job['id']
        (folder/'raw.json').write_text(json.dumps({'floors':[{'floor':17,'images':[{'file':str(folder/'input.png')}]}]}),encoding='utf8')
        (folder/'result.json').write_text(json.dumps([{'text':'','images':['书名\nVIP\n科幻|\n作者\n12万字\n月票\n点赞']}]),encoding='utf8')
        self.app.state.jobs.update(job['id'],'succeeded')
        return '/api/jobs/'+job['id']+'/books'

    def test_extract_verify_archive_and_repeat_without_overwrite(self):
        path=self.make_job()
        plan=self.post(path+'/extract',{}).json()
        book=providers.record('sfacg',1,'书名','https://book.sfacg.com/novel/1/',author='作者',intro='平台原文')
        item=plan['items'][0]
        with patch('app.providers.search',return_value={'items':[providers.match(book,'书名','作者')]}),patch('app.providers.detail',return_value=book):
            result=self.post(path+'/0/verify',item)
        self.assertEqual(result.json()['state'],'verified')
        job_id=path.split('/')[3]
        self.app.state.jobs.pipeline_status(job_id,'review','待核对 1 本')
        plan_file=self.local/'jobs'/job_id/'books.json'
        pending_plan=json.loads(plan_file.read_text(encoding='utf8'))
        pending_plan['review_notice']='仍需手动核对'
        plan_file.write_text(json.dumps(pending_plan),encoding='utf8')
        archived=self.post(path+'/archive',{}).json()['items'][0]
        self.assertEqual(archived['state'],'archived')
        self.assertEqual(self.app.state.jobs.get(job_id)['organize_state'],'succeeded')
        self.assertIn('归档 1 本',self.app.state.jobs.get(job_id)['organize_stage'])
        self.assertNotIn('review_notice',self.client.get(path,headers=self.headers).json())
        file=self.local/'library'/archived['path']
        before=file.read_bytes()
        self.assertIn('楼层 17',before.decode())
        self.assertEqual(self.post(path+'/archive',{}).status_code,200)
        self.assertEqual(file.read_bytes(),before)
        self.assertEqual(self.client.get(path,headers=self.headers).json()['items'][0]['state'],'archived')

    def test_edit_invalidates_verification_and_failure_keeps_draft(self):
        path=self.make_job()
        item=self.post(path+'/extract',{}).json()['items'][0]
        with patch('app.providers.search',side_effect=providers.ProviderError('查询失败')):
            self.assertEqual(self.post(path+'/0/verify',{**item,'title':'改过的书名'}).status_code,400)
        saved=self.client.get(path,headers=self.headers).json()['items'][0]
        self.assertEqual(saved['title'],'改过的书名')
        self.assertEqual(saved['state'],'draft')
        self.assertIn('查询失败',saved['reason'])
        self.post(path+'/archive',{})
        self.assertEqual(list((self.local/'library').glob('*/*/*.md')),[])

    def test_chapter_export_and_failed_refresh_keeps_saved_text(self):
        saved=self.post('/api/books',{'title':'章节样例','category':'科幻','url':'https://book.sfacg.com/novel/1/'}).json()
        result={'chapters':[{'title':'第一章','url':'https://m.sfacg.com/c/2/','content':'公开正文'}], 'warnings':[]}
        with patch('app.chapters.preview',return_value=result):
            response=self.post('/api/books/chapters',{'path':saved['path']})
        self.assertEqual(response.json()['count'],1)
        path=response.json()['path']
        exported=self.client.get('/api/books/download',params={'path':path},headers=self.headers)
        self.assertIn('公开正文',exported.text)
        with patch('app.chapters.preview',side_effect=providers.ProviderError('读取失败')):
            self.assertEqual(self.post('/api/books/chapters',{'path':saved['path']}).status_code,400)
        self.assertEqual((self.local/'library'/path).read_bytes(),exported.content)


if __name__=='__main__':
    unittest.main()
