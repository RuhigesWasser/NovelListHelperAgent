import io
import json
import unittest
import urllib.request
from unittest.mock import Mock,patch
from app.esj_session import ESJSession, ESJError, current_session


class ESJSessionTests(unittest.TestCase):
    def test_direct_before_proxy_and_cookie_jar_shared(self):
        direct,proxy=Mock(),Mock()
        direct.open.side_effect=TimeoutError('direct timeout')
        proxy.open.side_effect=[io.BytesIO(b'first'),io.BytesIO(b'second')]
        with patch('app.esj_session.urllib.request.build_opener',side_effect=[direct,proxy]) as build,patch('app.esj_session.urllib.request.getproxies',return_value={'https':'http://127.0.0.1:9999'}):
            session=ESJSession()
            request=urllib.request.Request('https://www.esjzone.one/detail/1.html')
            self.assertEqual(session.fetch(request),b'first')
            self.assertEqual(session.fetch(request),b'second')
            self.assertEqual(direct.open.call_count,2)
            self.assertEqual(build.call_count,2)
            self.assertEqual(build.call_args_list[0].args[0].proxies,{})
            self.assertIs(build.call_args_list[0].args[-1].cookiejar,build.call_args_list[1].args[-1].cookiejar)

    def test_no_proxy_for_permission_failure_or_missing_proxy(self):
        import urllib.error
        for error,proxies in [(urllib.error.HTTPError('url',403,'forbidden',{},None),{'https':'http://proxy'}),(TimeoutError(),{})]:
            direct=Mock();direct.open.side_effect=error
            with patch('app.esj_session.urllib.request.build_opener',return_value=direct) as build,patch('app.esj_session.urllib.request.getproxies',return_value=proxies):
                session=ESJSession()
                with self.assertRaises(type(error)):session.fetch(urllib.request.Request('https://www.esjzone.one/'))
                self.assertEqual(build.call_count,1)

    def test_verified_login_keeps_only_memory_session(self):
        opener=Mock()
        opener.open.side_effect=[io.BytesIO(b'<JinJing>test-token</JinJing>'),
            io.BytesIO(json.dumps({'status':200,'msg':'請到水樓留言才可觀看更多小說'}).encode()),
            io.BytesIO(b'<a href="/my/logout">logout</a>')]
        with patch('app.esj_session.urllib.request.build_opener',return_value=opener):
            session=ESJSession()
            result=session.login('session@example.invalid','memory-password')
            self.assertTrue(result['connected'])
            self.assertIn('水楼',result['access_notice'])
            request=opener.open.call_args_list[1].args[0]
            self.assertIn(b'pwd=memory-password',request.data)
            self.assertNotIn(b'remember_me',request.data)
            self.assertFalse(hasattr(session,'email'))
            self.assertFalse(hasattr(session,'password'))
            self.assertFalse(hasattr(session.jar,'save'))
            with session.scope():self.assertIs(current_session.get(),session)
            self.assertIsNone(current_session.get())
            session.clear()
            self.assertFalse(session.connected)
            self.assertEqual(session.access_notice,'')

    def test_login_response_without_authenticated_page_is_not_success(self):
        opener=Mock()
        opener.open.side_effect=[io.BytesIO(b'<JinJing>test</JinJing>'),
            io.BytesIO(b'{"status":200}'),io.BytesIO(b'<div class="login-box">login</div>')]
        with patch('app.esj_session.urllib.request.build_opener',return_value=opener):
            session=ESJSession()
            with self.assertRaises(ESJError):session.login('a','b')
            self.assertFalse(session.connected)

    def test_login_error_never_echoes_server_message(self):
        opener=Mock()
        opener.open.side_effect=[io.BytesIO(b'<JinJing>test</JinJing>'),
            io.BytesIO(b'{"status":400,"msg":"account secret-password"}')]
        with patch('app.esj_session.urllib.request.build_opener',return_value=opener):
            session=ESJSession()
            with self.assertRaises(ESJError) as error:session.login('account','secret-password')
        self.assertNotIn('secret-password',str(error.exception))
        self.assertNotIn('account',str(error.exception))
