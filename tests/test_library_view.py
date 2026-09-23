import unittest
import test_app


class LibraryViewTests(unittest.TestCase):
    setUp=test_app.AppTests.setUp
    post=test_app.AppTests.post

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
