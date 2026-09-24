import unittest
import urllib.error
from unittest.mock import MagicMock,patch
from app.paths import add_tools
add_tools()
from direct_http import DirectFirst


class NetworkTests(unittest.TestCase):
    def test_direct_success_never_uses_system_proxy(self):
        direct=MagicMock()
        with patch('urllib.request.build_opener',return_value=direct) as build:
            client=DirectFirst();client.open('https://example.test')
        self.assertEqual(build.call_count,1)
        self.assertEqual(build.call_args.args[0].proxies,{})

    def test_transport_failure_tries_proxy_then_direct_again(self):
        direct,proxy=MagicMock(),MagicMock()
        direct.open.side_effect=[urllib.error.URLError('offline'),'direct result']
        with patch('urllib.request.build_opener',side_effect=[direct,proxy]) as build,patch('urllib.request.getproxies',return_value={'https':'http://127.0.0.1:7890'}),patch('urllib.request.proxy_bypass',return_value=False):
            client=DirectFirst();client.open('https://example.test')
            self.assertEqual(client.open('https://example.test'),'direct result')
        self.assertEqual(build.call_count,2);self.assertEqual(proxy.open.call_count,1)

    def test_permissions_and_no_proxy_do_not_retry(self):
        for error,proxies in [(urllib.error.HTTPError('url',403,'forbidden',{},None),{'https':'http://proxy'}),(urllib.error.URLError('offline'),{})]:
            direct=MagicMock();direct.open.side_effect=error
            with patch('urllib.request.build_opener',return_value=direct) as build,patch('urllib.request.getproxies',return_value=proxies):
                with self.assertRaises(urllib.error.URLError):DirectFirst().open('https://example.test')
            self.assertEqual(build.call_count,1)
