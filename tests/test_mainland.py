import json
import unittest
from unittest.mock import patch
from app import providers,mainland,organize,chapters


def page(data):
    return '<script id="vite-plugin-ssr_pageContext" type="application/json">'+json.dumps({'pageContext':{'pageProps':{'pageData':data}}})+'</script>'


class MainlandTests(unittest.TestCase):
    def test_canonical_urls_and_foreign_redirect(self):
        for url in ('https://book.qidian.com/info/123/','https://www.qidian.com/book/123/','https://m.qidian.com/book/123/'):
            self.assertEqual(providers.resolve_url(url)[:3],('qidian','123','https://m.qidian.com/book/123/'))
        self.assertEqual(providers.resolve_url('https://wap.ciweimao.com/book/456')[0],'ciweimao')
        for url in ('https://qidian.com.evil.test/book/123','https://m.qidian.com@evil.test/book/123'):
            with self.assertRaises(providers.ProviderError):providers.resolve_url(url)

    def test_qidian_detail_from_matching_embedded_book(self):
        data={'bookInfo':{'bookId':123,'bookName':'测试小说','authorName':'作者','wordsCnt':34567,'bookStatus':'连载',
                          'desc':'第一段<br>第二段','bookLabels':[{'tag':'冒险'}],'chanName':'玄幻'}}
        record=mainland.qidian_detail(page(data),'123','https://m.qidian.com/book/123/')
        self.assertEqual(record['intro'],'第一段\n第二段')
        self.assertEqual(record['word_count'],34567)
        self.assertEqual(record['status'],'连载中')
        data['bookExtra']={'ugcTagInfos':[{'tagName':'世界观'},{'TagName':'冒险'}]}
        self.assertEqual(mainland.qidian_detail(page(data),'123','https://m.qidian.com/book/123/')['tags'],['玄幻','冒险','世界观'])
        with self.assertRaises(providers.ProviderError):mainland.qidian_detail(page(data),'999','https://m.qidian.com/book/999/')

    def test_qidian_search_pagination_and_author_conflict(self):
        html=page({'bookInfo':{'records':[{'bid':123,'bName':'测试小说','bAuth':'作者'}]}})
        with patch('app.providers.fetch_html',return_value=html) as fetch:
            result=providers.search('qidian','测试小说','其他作者',page=2)
        self.assertIn('pageNum=3',fetch.call_args.args[0])
        self.assertEqual(result['items'][0]['match'],'author_conflict')

    def test_qidian_prefers_matching_high_resolution_cover(self):
        html=page({'bookInfo':{'bookId':123,'bookName':'书','authorName':'作者'}})
        html+='<meta property="og:image" content="//bookcover.yuewen.com/123/180">'
        data={'@graph':[{'@type':'Book','identifier':{'value':'999'},'image':'https://example.test/wrong'},
                        {'@type':'Book','identifier':{'value':'123'},'image':'https://bookcover.yuewen.com/123/600'}]}
        html+='<script type="application/ld+json">'+json.dumps(data)+'</script>'
        self.assertEqual(mainland.qidian_detail(html,'123','https://m.qidian.com/book/123/')['cover_url'],'https://bookcover.yuewen.com/123/600')

    def test_qidian_catalog_skips_paid_and_checks_read_identity(self):
        data={'bookId':123,'vs':[{'vS':0,'vN':'正文','cs':[{'sS':1,'id':10,'cN':'第一章'}]},
                               {'vS':1,'vN':'付费','cs':[{'sS':1,'id':11,'cN':'第二章'}]}]}
        with patch('app.providers.fetch_html',return_value=page(data)):
            items=mainland.qidian_catalog('123')
        self.assertEqual([e['chapter_id'] for e in items],['10'])
        data={'bookInfo':{'bookId':123},'chapterInfo':{'chapterId':10,'vipStatus':0,'price':0,'content':'<p>正文</p>'}}
        with patch('app.providers.fetch_html',return_value=page(data)):
            self.assertEqual(chapters.read_chapter('qidian',items[0])['content'],'正文')
        data['chapterInfo']['vipStatus']=1
        with patch('app.providers.fetch_html',return_value=page(data)):
            with self.assertRaises(providers.ProviderError):chapters.read_chapter('qidian',items[0])
        data['chapterInfo'].update(vipStatus=0,chapterId=20)
        with patch('app.providers.fetch_html',return_value=page(data)):
            with self.assertRaises(providers.ProviderError):chapters.read_chapter('qidian',items[0])

    def test_ciweimao_search_and_truncated_title_remains_review(self):
        html='<input name="keyword"><div class="cnt"><p class="tit"><a href="https://www.ciweimao.com/book/12" title="今天的完整书名">书名</a></p><p><a href="/reader/3">作者</a></p></div>'
        with patch('app.providers.fetch_html',return_value=html) as fetch:
            result=providers.search('ciweimao','今天的…书名','作者')
        self.assertNotIn('%E2%80%A6',fetch.call_args.args[0])
        self.assertEqual(result['items'][0]['match'],'possible')

    def test_ciweimao_detail_tags_status_and_identity(self):
        html='<meta property="og:novel:book_name" content="测试书"><meta property="og:novel:author" content="作者"><meta property="og:novel:read_url" content="https://www.ciweimao.com/book/12"><p class="book-grade">总字数：<b>123,456</b></p><p class="update-state">已完结·本站首发</p><div class="book-desc">简介</div>'
        book=mainland.ciweimao_detail(html,'12','https://www.ciweimao.com/book/12')
        self.assertEqual(book['word_count'],123456);self.assertEqual(book['status'],'完结')
        with self.assertRaises(providers.ProviderError):mainland.ciweimao_detail(html,'13','https://www.ciweimao.com/book/13')

    def test_ciweimao_catalog_uses_read_link_not_front_matter(self):
        html='<a href="https://wap.ciweimao.com/chapter/2">立即阅读</a><h2>设定</h2><ul class="catalogue-list"><li><a href="/chapter/1">设定集</a></li></ul><h2>正文</h2><ul class="catalogue-list"><li><a href="/chapter/2">第一章</a></li><li><a href="/chapter/3">第二章</a></li></ul>'
        with patch('app.providers.fetch_html',return_value=html):items=mainland.ciweimao_catalog('12')
        selected,reason=mainland.suggested('ciweimao',items)
        self.assertEqual([i['chapter_id'] for i in selected],['2','3'])
        self.assertEqual(items[0]['group'],'设定')

    def test_verification_page_never_becomes_chapter_or_empty_search(self):
        html='<title>验证码 - 刺猬猫</title><div id="J_BookCnt">请完成验证</div>'
        with patch('app.providers.fetch_html',return_value=html):
            with self.assertRaisesRegex(providers.ProviderError,'网页验证'):mainland.ciweimao_search('书名')
            with self.assertRaisesRegex(providers.ProviderError,'网页验证'):mainland.chapter('ciweimao',{'url':'https://wap.ciweimao.com/chapter/2'})

    def test_real_screenshot_shapes_multiple_books_and_author_link(self):
        qidian='斗破之魂族妖女\n清湘著\n清渊渊>\n玄幻·东方玄幻\n起点读书'
        shelf='我的书架\n我怎么会是女主角，不对不对!\n在家的咸鱼/31.2万字\n未读\n我是雪之下雪乃\n更新\n如修/43.5万字'
        plan=organize.extract([{'text':'','images':[qidian,shelf]}],[9],'刺猬猫和起点')
        self.assertEqual(len(plan['items']),3)
        self.assertEqual(plan['items'][0]['author'],'清渊渊')
        self.assertEqual(plan['items'][0]['platform'],'qidian')
        self.assertEqual([i['image_index'] for i in plan['items']],[0,1,1])
        self.assertEqual(plan['items'][2]['author'],'如修')

    def test_cropped_last_shelf_row_is_retained_without_invented_author(self):
        text='我的书架\n已知书\n作者/20万字\n上次读到：第一章\n另一部被裁切的书\n更新\n书城\n排行\n我的'
        hints=organize.image_hints(text,'刺猬猫')
        self.assertEqual([x['title'] for x in hints],['已知书','另一部被裁切的书'])
        self.assertEqual(hints[1]['author'],'')
