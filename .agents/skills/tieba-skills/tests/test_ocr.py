"""python -m unittest discover -s .agents/skills/tieba-skills/tests -v"""
import base64
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from PIL import Image, ImageDraw, ImageFont
import ocr
import fetch_thread


class TestOCR(unittest.TestCase):
    def test_fetch_preserves_reply_ids_and_pages(self):
        posts=[]
        for floor,pid in [(1,101),(42,142)]:
            posts.append(SimpleNamespace(thread=SimpleNamespace(title='帖子'),forum=SimpleNamespace(fname='小说'),
                objs=[SimpleNamespace(floor=floor,pid=pid,text='正文',contents=SimpleNamespace(imgs=[]))],has_more=floor==1))
        client=MagicMock()
        client.get_posts=AsyncMock(side_effect=posts)
        client.__aenter__=AsyncMock(return_value=client)
        client.__aexit__=AsyncMock(return_value=False)
        with patch.dict(sys.modules,{'aiotieba':SimpleNamespace(Client=lambda:client)}):
            result=asyncio.run(fetch_thread.fetch_thread(123,str(self.root),'origin',30,True))
        self.assertEqual([(f['floor'],f['pid'],f['page']) for f in result['floors']],[(1,101,1),(42,142,2)])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.image = self.root / '图片.jpg'
        # 故意使用与后缀不一致的格式，确保 API MIME 来自实际重新编码。
        Image.new('RGB', (40, 40), 'white').save(self.image, format='PNG')

    def serve(self, status=200, content='识别文字', finish='stop', raw=None):
        self.requests = []
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append((self.path, dict(self.headers), body))
                self.send_response(status)
                self.end_headers()
                self.wfile.write(raw if raw is not None else json.dumps({
                    'choices': [{'finish_reason': finish, 'message': {'content': content}}]
                }).encode('utf-8'))
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join()
        self.addCleanup(cleanup)
        return f'http://127.0.0.1:{server.server_port}/v1'

    def test_llm_real_http_contract(self):
        engine = ocr.LlmOCR(self.serve(), 'vision-test', 'test-key')
        self.assertEqual(engine(self.image), '识别文字')
        route, headers, body = self.requests[0]
        self.assertEqual(route, '/v1/chat/completions')
        self.assertEqual(headers['Authorization'], 'Bearer test-key')
        self.assertEqual(body['model'], 'vision-test')
        uri = body['messages'][0]['content'][1]['image_url']['url']
        self.assertTrue(uri.startswith('data:image/png;base64,'))
        with Image.open(io.BytesIO(base64.b64decode(uri.split(',')[1]))) as im:
            self.assertEqual(im.size, (40, 40))

    def test_no_text_preserves_empty_result(self):
        engine = ocr.LlmOCR(self.serve(content='__NO_TEXT__'), 'test', '')
        self.assertEqual(engine(self.image), '')

    def test_truncation_is_error(self):
        engine = ocr.LlmOCR(self.serve(finish='length'), 'test', '')
        with self.assertRaisesRegex(RuntimeError, '未完整'):
            engine(self.image)

    def test_http_error_does_not_echo_response_secret(self):
        engine = ocr.LlmOCR(self.serve(status=401, raw=b'private-api-key'), 'test', '')
        with self.assertRaises(RuntimeError) as error:
            engine(self.image)
        self.assertIn('401', str(error.exception))
        self.assertNotIn('private-api-key', str(error.exception))

    def test_invalid_json_is_error(self):
        engine = ocr.LlmOCR(self.serve(raw=b'not JSON'), 'test', '')
        with self.assertRaisesRegex(RuntimeError, 'JSON'):
            engine(self.image)

    def test_dedup_order_and_relative_paths(self):
        duplicate = self.root / 'duplicate.png'
        duplicate.write_bytes(self.image.read_bytes())
        data = {'floors': [{'text': '第一层', 'images': [{'file': self.image.name}]},
                           {'text': '第二层', 'images': [{'file': duplicate.name}, {'file': self.image.name}]},
                           {'text': '第三层', 'images': []}]}
        engine = Mock(return_value='')
        result = ocr.recognize_thread(data, engine, self.root)
        self.assertEqual(engine.call_count, 1)
        self.assertEqual(result, [{'text': '第一层', 'images': ['']},
                                  {'text': '第二层', 'images': ['', '']},
                                  {'text': '第三层', 'images': []}])

    def test_missing_image_is_error(self):
        with self.assertRaises(FileNotFoundError):
            ocr.recognize_thread({'floors': [{'images': [{'file': 'missing.png'}]}]}, Mock(), self.root)

    def test_builtin_tiles_own_overlap_by_center(self):
        path = self.root / 'long.png'
        Image.new('RGB', (200, 2800)).save(path)
        engine = ocr.BuiltinOCR.__new__(ocr.BuiltinOCR)
        box = lambda y: [[0, y-5], [10, y-5], [10, y+5], [0, y+5]]
        engine.engine = Mock(side_effect=[([[box(1390), '上一段', 1], [box(1410), '下一段', 1]], []),
                                          ([[box(90), '上一段', 1], [box(110), '下一段', 1]], [])])
        self.assertEqual(engine(path), '上一段\n下一段')

    def test_fetch_builtin_final_and_raw_outputs(self):
        data = {'floors': [{'text': '正文', 'images': [{'file': str(self.image)}]}]}
        out, raw = self.root/'final.json', self.root/'raw.json'
        argv = ['fetch_thread.py', '123', '--ocr', 'builtin', '--img-dir', str(self.root),
                '--out', str(out), '--raw-out', str(raw)]
        with (patch.object(sys, 'argv', argv), patch.object(fetch_thread, 'make_engine', return_value=Mock(return_value='书名')),
              patch.object(fetch_thread, 'ensure_aiotieba'), patch.object(fetch_thread, 'fetch_thread', return_value=data) as fetch):
            self.assertEqual(fetch_thread.main(), 0)
        self.assertTrue(fetch.call_args.kwargs['preserve_images'])
        self.assertEqual(json.loads(raw.read_text(encoding='utf-8')), data)
        self.assertEqual(json.loads(out.read_text(encoding='utf-8')), [{'text': '正文', 'images': ['书名']}])

    def test_llm_configuration_validation(self):
        for url in ('', 'file:///tmp/a', 'https://user:pass@example.test/v1', 'https://example.test/v1#fragment'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                ocr.LlmOCR(url, 'test', '')
        self.assertEqual(ocr.LlmOCR('https://example.test/v1/chat/completions', 'test', '').url,
                         'https://example.test/v1/chat/completions')

    def test_missing_tieba_dependency_never_installs_automatically(self):
        with patch.dict(sys.modules, {'aiotieba': None}), patch('subprocess.run') as install:
            with self.assertRaisesRegex(RuntimeError, '确认安装'):
                fetch_thread.ensure_aiotieba()
            install.assert_not_called()

    def test_failed_ocr_keeps_raw_and_existing_final(self):
        data = {'floors': [{'text': '', 'images': [{'file': str(self.image)}]}]}
        out, raw = self.root/'final.json', self.root/'raw.json'
        out.write_text('existing result', encoding='utf-8')
        argv = ['fetch_thread.py', '123', '--ocr', 'llm', '--img-dir', str(self.root),
                '--out', str(out), '--raw-out', str(raw)]
        with (patch.object(sys, 'argv', argv), patch.object(fetch_thread, 'make_engine', return_value=Mock(side_effect=RuntimeError('API failed'))),
              patch.object(fetch_thread, 'ensure_aiotieba'), patch.object(fetch_thread, 'fetch_thread', return_value=data)):
            self.assertEqual(fetch_thread.main(), 1)
        self.assertEqual(out.read_text(encoding='utf-8'), 'existing result')
        self.assertEqual(json.loads(raw.read_text(encoding='utf-8')), data)

    def test_builtin_real_chinese_long_image_and_blank(self):
        font_path = Path('C:/Windows/Fonts/msyh.ttc')
        if not font_path.is_file():
            self.skipTest('真实中文测试需要微软雅黑字体')
        try:
            import rapidocr_onnxruntime
        except ImportError:
            self.skipTest('未安装内置 OCR 依赖')
        font = ImageFont.truetype(str(font_path), 40)
        im = Image.new('RGB', (1100, 3000), 'white')
        draw = ImageDraw.Draw(im)
        for y, text in ((50, '书名：星河旅人'), (1375, '作者：测试作者'), (2800, '状态：连载中 123456')):
            draw.text((40, y), text, font=font, fill='black')
        path = self.root/'real.png'
        im.save(path)
        engine = ocr.BuiltinOCR()
        result = engine(path)
        for expected in ('星河旅人', '测试作者', '连载中', '123456'):
            self.assertIn(expected, result)
        self.assertEqual(result.count('测试作者'), 1)
        self.assertEqual(engine(self.image), '')


if __name__ == '__main__':
    unittest.main()
