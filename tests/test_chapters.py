import unittest
import json
from unittest.mock import patch
from app import chapters, providers


class ChapterTests(unittest.TestCase):
    def test_catalog_skips_paid_and_deduplicates(self):
        html='<ul class="mulu_list"><a href="/c/1/">第一章</a><a href="/c/1/">重复</a><a href="/c/2/">第二章<span class="icon-lock2"></span></a><a href="/c/3/">第三章 VIP</a></ul>'
        with patch('app.providers.fetch_html',return_value=html):
            platform, entries=chapters.catalog('https://book.sfacg.com/novel/10/')
        self.assertEqual(platform,'sfacg')
        self.assertEqual([e['url'] for e in entries],['https://m.sfacg.com/c/1/'])

    def test_body_failure_is_not_title_only_success(self):
        with patch('app.providers.fetch_html',return_value='<div>需要登录</div>'):
            with self.assertRaises(providers.ProviderError):
                chapters.read_chapter('esj',{'title':'标题','url':'https://www.esjzone.one/forum/1/2.html'})
        with patch('app.providers.fetch_html',return_value='<div class="yuedu Content_Frame"><p>第一段。</p><p>第二段。</p><script>ad</script></div>'):
            result=chapters.read_chapter('sfacg',{'title':'标题','url':'https://m.sfacg.com/c/1/'})
        self.assertEqual(result['content'],'第一段。\n\n第二段。')

    def test_partial_chapters_report_failure(self):
        entries=[{'title':str(i),'url':str(i)} for i in range(5)]
        with patch('app.chapters.catalog',return_value=('sfacg',entries)),patch('app.chapters.read_chapter',side_effect=[{'content':'one'},providers.ProviderError('不可读'),{'content':'three'}]) as read:
            result=chapters.preview('url')
        self.assertEqual(read.call_count,3)
        self.assertEqual(len(result['chapters']),2)
        self.assertEqual(result['warnings'],['1（1）：不可读'])

    def test_fanqie_public_catalog_and_decoding(self):
        from app.fanqie_text import decode
        page={'page':{'chapterListWithVolume':[[{'itemId':'2','title':'第一章','needPay':0},
                                              {'itemId':'3','title':'付费','needPay':1}]]}}
        with patch('app.providers.fetch_html',return_value='window.__INITIAL_STATE__='+json.dumps(page)):
            platform,entries=chapters.catalog('https://fanqienovel.com/page/1')
        self.assertEqual(len(entries),1)
        data={'reader':{'chapterData':{'bookId':'1','itemId':'2','needPay':0,'content':'<p>\ue3e9一段正文</p>'}}}
        html='awesome-font/c/dc027189e0ba4cd.woff2 window.__INITIAL_STATE__='+json.dumps(data)
        with patch('app.providers.fetch_html',return_value=html):
            result=chapters.read_chapter(platform,entries[0])
        self.assertEqual(result['content'],'在一段正文')
        self.assertEqual(decode('普通正文','no font'),'普通正文')
        for encoded,source in [('\ue3e9','awesome-font/c/changed.woff2'),('\uf001',html)]:
            with self.assertRaises(providers.ProviderError):decode(encoded,source)

    def test_fanqie_rejects_wrong_chapter_and_paid_content(self):
        entry={'book_id':'1','chapter_id':'2','url':'https://fanqienovel.com/reader/2'}
        for changes in ({'itemId':'3'},{'needPay':1},{'isChapterLock':True},{'content':''}):
            data={'reader':{'chapterData':{'bookId':'1','itemId':'2','content':'<p>正文</p>',**changes}}}
            with patch('app.providers.fetch_html',return_value='window.__INITIAL_STATE__='+json.dumps(data)):
                with self.assertRaises(providers.ProviderError):chapters.read_chapter('fanqie',entry)
