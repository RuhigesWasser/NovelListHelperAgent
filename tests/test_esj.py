import unittest
from unittest.mock import patch
from app import providers as p

HTML='''<title>搜尋結果 - ESJ Zone</title><div class="card-body">
<h5 class="card-title"><a href="/detail/1712397853.html">尼爾今天沒幹勁</a></h5>
<div class="card-author"><a>就是我</a></div><div class="column"><i class="icon-file-text"></i>188,004</div>
</div><aside><a href="/detail/999.html">侧栏推荐</a></aside>'''


class ESJTests(unittest.TestCase):
    def test_authenticated_search_keeps_permission_notice_and_source(self):
        from app.esj_session import ESJSession
        session=ESJSession()
        session.connected=True
        session.access_notice='站点要求先在水楼留言'
        with session.scope(),patch.object(p,'fetch_html',return_value=HTML):
            result=p.search('esj','尼爾今天沒幹勁','就是我')
        self.assertIn(session.access_notice,result['warnings'])
        self.assertEqual(result['items'][0]['field_sources']['title']['method'],'session_html')
        session.clear()

    def test_search_result_excludes_sidebar(self):
        with patch.object(p,'fetch_html',return_value=HTML) as fetch:
            result=p.search('esj','尼爾今天沒幹勁','就是我',page=1)
        self.assertTrue(fetch.call_args.args[0].endswith('/2.html'))
        self.assertEqual(len(result['items']),1)
        self.assertEqual(result['items'][0]['match'],'exact')
        self.assertEqual(result['items'][0]['word_count'],188004)

    def test_original_scope_empty_is_explained(self):
        result=p.parse_esj_search('<title>輕小說 - 原創 - ESJ Zone</title>','https://www.esjzone.one/tags/test/1.html')
        self.assertEqual(result['items'],[])
        self.assertIn('原创',result['warnings'][0])
