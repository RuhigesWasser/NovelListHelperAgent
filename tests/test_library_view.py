import unittest
import json
from unittest.mock import patch
import test_app


class LibraryViewTests(unittest.TestCase):
    setUp=test_app.AppTests.setUp
    post=test_app.AppTests.post

    def test_reader_and_incremental_chapter_download_keep_catalog_order(self):
        path=self.post('/api/books',{'title':'选章','category':'科幻','url':'https://book.sfacg.com/novel/10/'}).json()['path']
        entries=[{'title':f'第{i}章','url':f'https://m.sfacg.com/c/{i}/'} for i in range(1,6)]
        def read(platform,entry):return {**entry,'content':'正文 '+entry['title']}
        with patch('app.chapters.catalog',return_value=('sfacg',entries)),patch('app.chapters.read_chapter',side_effect=read):
            result=self.post('/api/books/chapters',{'path':path,'selected_urls':[e['url'] for e in reversed(entries[1:])]})
            self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['count'],4)
            result=self.post('/api/books/chapters',{'path':path,'selected_urls':[entries[0]['url'],entries[1]['url']]})
            self.assertEqual(result.json()['total'],5)
        reader=self.client.get('/api/books/reader',params={'path':path},headers=self.headers)
        self.assertEqual([e['title'] for e in reader.json()['chapters']],[e['title'] for e in entries])
        self.assertEqual(self.client.get('/api/books/reader',params={'path':path}).status_code,403)
        self.assertEqual(self.client.get('/api/books/reader',params={'path':'../settings.json'},headers=self.headers).status_code,400)

    def test_reader_handles_old_text_and_failed_download_preserves_it(self):
        path=self.post('/api/books',{'title':'旧正文','category':'科幻','url':'https://book.sfacg.com/novel/10/'}).json()['path']
        target=(self.local/'library'/path).with_suffix('.txt')
        text='第一章\n来源：https://m.sfacg.com/c/1/\n\n一\n\n第二章\n来源：https://m.sfacg.com/c/2/\n\n二'
        target.write_text(text,encoding='utf8')
        result=self.client.get('/api/books/reader',params={'path':path},headers=self.headers).json()
        self.assertEqual([c['content'] for c in result['chapters']],['一','二'])
        from app.providers import ProviderError
        with patch('app.chapters.preview',side_effect=ProviderError('无法读取')):
            self.assertEqual(self.post('/api/books/chapters',{'path':path}).status_code,400)
        self.assertEqual(target.read_text(encoding='utf8'),text)

    def test_existing_markdown_details_and_edit_preserve_chapters_and_sources(self):
        source={'retrieved':{'url':'https://example.test/book','title':'原书名'},'source_url':'https://tieba.baidu.com/p/123'}
        book={'title':'书库测试','category':'科幻','author':'作者甲','platform':'起点中文网','words':'123456',
              'status':'连载中','tags':'科幻|冒险','intro':'第一段\n第二段','review':'【无】','url':'https://example.test/book','provenance':source}
        result=self.post('/api/books',book).json();path=result['path']
        target=self.local/'library'/path;target.with_suffix('.txt').write_text('已有正文',encoding='utf8')
        details=self.client.get('/api/books/detail',params={'path':path},headers=self.headers).json()
        self.assertEqual(details['intro'],'第一段\n第二段');self.assertEqual(details['author'],'作者甲')
        self.assertTrue(details['text_path']);self.assertEqual(details['provenance'],source)
        listing=self.client.get('/api/books',headers=self.headers).json()[0]
        self.assertEqual(listing['tags'],'科幻|冒险');self.assertEqual(listing['words'],'123456')
        edit={'path':path,'revision':details['revision'],'book':{**book,'review':'值得再读','intro':'修改后的简介'}}
        saved=self.client.put('/api/books/detail',json=edit,headers=self.headers)
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(saved.json()['review'],'值得再读')
        self.assertEqual(saved.json()['provenance']['retrieved'],source['retrieved'])
        self.assertIn('review',saved.json()['provenance']['user_edited_fields'])
        self.assertEqual(target.with_suffix('.txt').read_text(encoding='utf8'),'已有正文')
        self.assertEqual(self.client.put('/api/books/detail',json=edit,headers=self.headers).status_code,409)

    def test_detail_rejects_escape_and_edit_cannot_move_book(self):
        path=self.post('/api/books',{'title':'书','category':'科幻'}).json()['path']
        detail=self.client.get('/api/books/detail',params={'path':path},headers=self.headers).json()
        self.assertEqual(self.client.get('/api/books/detail',params={'path':'../settings.json'},headers=self.headers).status_code,400)
        changed={'path':path,'revision':detail['revision'],'book':{'title':'其他书','category':'科幻'}}
        self.assertEqual(self.client.put('/api/books/detail',json=changed,headers=self.headers).status_code,400)
        self.assertTrue((self.local/'library'/path).exists())
