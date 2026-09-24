import json
import unittest
from unittest.mock import patch
from app import providers as p


class ProvidersTest(unittest.TestCase):
    def test_author_conflict_never_matches_exact(self):
        candidate={'title':'当器灵的那些年','author':'另一位作者'}
        self.assertEqual(p.match(candidate,'当器灵的那些年','清风牧月')['match'],'author_conflict')
        self.assertEqual(p.match(candidate,'当器灵的那些年')['match'],'title_only')
        self.assertEqual(p.match(candidate,'当器灵的那些年','另一位作者')['match'],'exact')

    def test_url_routing_and_rejection(self):
        self.assertEqual(p.resolve_url('https://book.sfacg.com/Novel/123/?x=1')[:2],('sfacg','123'))
        self.assertEqual(p.resolve_url('https://fanqienovel.com/reader/123')[-1],'reader')
        self.assertEqual(p.resolve_url('https://esjzone.one/detail/123.html')[0],'esj')
        for url in ('http://127.0.0.1/page/1','https://fanqienovel.com.evil.test/page/1',
                    'https://user:pass@fanqienovel.com/page/1','https://fanqienovel.com:444/page/1',
                    'https://syosetu.org/novel/1','https://esjzone.one/forum/1/2.html'):
            with self.subTest(url=url),self.assertRaises(p.ProviderError):p.resolve_url(url)

    def test_redirect_never_follows_unknown_host(self):
        for url in ('http://fanqienovel.com/page/1','https://127.0.0.1/','https://other.example/'):
            with self.assertRaises(p.ProviderError):p.validate_fetch_url(url)

    def test_fanqie_embedded_json_without_js_execution(self):
        page={'bookId':'12','bookName':'测试书','author':'作者','wordNumber':350205,'abstract':'原简介',
              'categoryV2':json.dumps([{'Name':'仙侠'}])}
        html='<span class="info-label-yellow">连载中</span><script>window.__INITIAL_STATE__='+json.dumps({'page':page})+';</script>'
        book=p.parse_fanqie(html,'12','https://fanqienovel.com/page/12')
        self.assertEqual(book['word_count'],350205)
        self.assertEqual(book['tags'],['仙侠'])
        self.assertEqual(book['status'],'连载中')
        self.assertEqual(book['field_sources']['author']['method'],'public_html')
        with self.assertRaises(p.ProviderError):p.parse_fanqie(html,'99','https://fanqienovel.com/page/99')
        with self.assertRaises(p.ProviderError):p.initial_state('<script>window.__INITIAL_STATE__=alert(1)</script>')

    def test_esj_keeps_original_url_and_unknown_status(self):
        html='''<div class="book-detail"><h2>书名</h2></div><ul class="book-detail">
        <li><strong>作者:</strong><a>おにっく</a></li><li><strong>Web生肉:</strong>
        <a href="https://syosetu.org/novel/320297">原作</a></li></ul><span id="txt">351,617</span>
        <div class="description">介绍<br>下一行</div><div class="widget-tags"><a class="tag">同人</a></div>'''
        book=p.parse_esj(html,'1','https://esjzone.one/detail/1.html')
        self.assertEqual(book['original_url'],'https://syosetu.org/novel/320297')
        self.assertEqual(book['author'],'おにっく')
        self.assertEqual(book['status'],'未知')
        self.assertEqual(book['word_count'],351617)
        self.assertEqual(book['intro'],'介绍\n下一行')
        with self.assertRaises(p.ProviderError):p.parse_esj('请登录','1','https://esjzone.one/detail/1.html')

    def test_unsupported_search_does_not_send_request(self):
        with patch.object(p,'fetch_html') as fetch:
            with self.assertRaises(p.ProviderError):p.search('unknown','书名')
            fetch.assert_not_called()

    def test_fanqie_mobile_search_and_matching(self):
        import io
        payload={'code':0,'data':{'ret_data':[{'title':'<em>当器灵</em>的那些年',
          'author':'清风牧月','book_id':'7647153574379539480','abstract':'简介','category':'仙侠'}]}}
        with patch('app.providers.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())) as request:
            result=p.search('fanqie','当器灵的那些年','清风牧月',page=2)
            self.assertIn('offset=20',request.call_args.args[0].full_url)
            self.assertNotIn('Cookie',request.call_args.args[0].headers)
        self.assertEqual(result['items'][0]['match'],'exact')
        self.assertEqual(result['items'][0]['url'],'https://fanqienovel.com/page/7647153574379539480')
        self.assertEqual(result['items'][0]['field_sources']['title']['method'],'platform_api')

    def test_reader_link_resolves_book_before_detail(self):
        reader='window.__INITIAL_STATE__='+json.dumps({'reader':{'chapterData':{'bookId':'99'}}})
        detail='<b>已完结</b>window.__INITIAL_STATE__='+json.dumps({'page':{'bookId':'99','bookName':'测试书'}})
        with patch.object(p,'fetch_html',side_effect=[reader,detail]) as fetch:
            result=p.detail('https://fanqienovel.com/reader/123')
            self.assertEqual(result['book_id'],'99')
            self.assertEqual(fetch.call_args.args[0],'https://fanqienovel.com/page/99')


if __name__=='__main__':unittest.main()
