import io
import json
from pathlib import Path
import tempfile
import os
import threading
import unittest
from unittest.mock import patch
from PIL import Image
from app import covers,library
from app.paths import ROOT
import test_app


def png():
    stream=io.BytesIO();Image.new('RGBA',(24,32),(40,130,80,128)).save(stream,format='PNG');return stream.getvalue()


class CoverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        saved=library.save_book(self.base,library.Book(title='测试书',category='科幻',url='https://book.sfacg.com/novel/123/'))
        self.path=self.base/saved['path']

    def test_actual_format_local_file_and_edit_preservation(self):
        info=covers.upload(self.base,self.path,png())
        self.assertTrue(info['has_image']);self.assertEqual(info['origin'],'manual')
        self.assertEqual(covers.image_path(self.path).suffix,'.png')
        with Image.open(covers.image_path(self.path)) as image:self.assertEqual(image.size,(24,32))
        library.save_book(self.base,library.Book(title='测试书',category='科幻',review='修改',overwrite=True))
        self.assertEqual(library.read_book(self.base,self.path)['cover']['version'],info['version'])

    def test_manual_is_not_automatically_replaced(self):
        covers.upload(self.base,self.path,png())
        with patch('app.providers.detail') as detail:
            result=covers.refresh(self.base,self.path)
        detail.assert_not_called();self.assertEqual(result['origin'],'manual')

    def test_failed_refresh_keeps_previous_image(self):
        covers.store_image(self.path,png(),'platform')
        old=covers.image_path(self.path)
        with patch('app.providers.detail',side_effect=covers.providers.ProviderError('暂不可用')):
            info=covers.refresh(self.base,self.path)
        self.assertTrue(info['has_image']);self.assertEqual(covers.image_path(self.path),old);self.assertIn('暂不可用',info['error'])

    def test_fanqie_refreshes_signed_url_before_download(self):
        saved=library.save_book(self.base,library.Book(title='番茄',category='科幻',url='https://fanqienovel.com/page/123',
            provenance={'retrieved':{'url':'https://fanqienovel.com/page/123','cover_url':'https://old.test/image?x-expires=1'}}))
        path=self.base/saved['path'];fresh='https://new.test/image?x-expires=9999999999'
        with patch('app.providers.detail',return_value={'cover_url':fresh}) as detail,patch('app.covers.download',return_value=png()) as download:
            result=covers.refresh(self.base,path)
        detail.assert_called_once();download.assert_called_once_with(fresh)
        self.assertTrue(result['has_image']);self.assertEqual(covers.metadata(path)['source_expires_at'],9999999999)

    def test_stale_url_is_resolved_once(self):
        library.save_book(self.base,library.Book(title='测试书',category='科幻',url='https://book.sfacg.com/novel/123/',overwrite=True,
            provenance={'retrieved':{'url':'https://book.sfacg.com/novel/123/','cover_url':'https://old.test/image'}}))
        with patch('app.providers.detail',return_value={'cover_url':'https://new.test/image'}) as detail,patch('app.covers.download',side_effect=[covers.CoverError('HTTP 403'),png()]) as download:
            result=covers.refresh(self.base,self.path)
        self.assertTrue(result['has_image']);self.assertEqual(download.call_count,2);detail.assert_called_once()

    def test_invalid_images_and_private_network_are_rejected(self):
        with self.assertRaises(covers.CoverError):covers.upload(self.base,self.path,b'<html>not an image</html>')
        with patch('app.covers.MAX_BYTES',10):
            with self.assertRaises(covers.CoverError):covers.upload(self.base,self.path,png())
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(covers.CoverError):covers.validate_remote('https://example.test/image')
        self.assertFalse(covers.public(self.path)['has_image'])

    def test_metadata_cannot_reference_other_files(self):
        self.path.with_suffix('.cover.json').write_text(json.dumps({'file':'../secret.png'}))
        self.assertIsNone(covers.image_path(self.path))

    @unittest.skipUnless(os.name=='nt','Windows file-sharing behavior')
    def test_cover_metadata_update_survives_short_reader_lock(self):
        covers.save_metadata(self.path,{'error':'old'})
        reader=self.path.with_suffix('.cover.json').open('rb')
        timer=threading.Timer(.08,reader.close);timer.start()
        try:covers.save_metadata(self.path,{'error':'new'})
        finally:timer.join();reader.close()
        self.assertEqual(covers.metadata(self.path)['error'],'new')

    def test_queue_deduplicates_requests_and_clears_pending(self):
        queue=covers.CoverQueue(self.base);self.addCleanup(queue.close)
        relative=self.path.relative_to(self.base).as_posix()
        with patch.object(queue.pool,'submit') as submit:
            self.assertTrue(queue.enqueue(relative));self.assertFalse(queue.enqueue(relative))
            self.assertTrue(queue.is_pending(relative))
            with patch('app.covers.refresh',return_value={'has_image':False}):submit.call_args.args[0]()
        self.assertFalse(queue.is_pending(relative))

    def test_known_cdn_uses_explicit_proxy_despite_fake_ip_dns(self):
        with patch('urllib.request.getproxies',return_value={'https':'http://127.0.0.1:7890'}),patch('urllib.request.proxy_bypass',return_value=False),patch('socket.getaddrinfo') as dns:
            covers.validate_remote('https://bookcover.yuewen.com/qdbimg/book/600')
            dns.assert_not_called()
        with patch('urllib.request.getproxies',return_value={}),patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(covers.CoverError):covers.validate_remote('https://bookcover.yuewen.com/image')


class CoverRoutesTests(unittest.TestCase):
    setUp=test_app.AppTests.setUp
    post=test_app.AppTests.post

    def test_archive_enqueues_cover_after_saving_book(self):
        with patch('app.covers.CoverQueue.enqueue',return_value=True) as enqueue:
            result=self.post('/api/books',{'title':'自动封面','category':'科幻','url':'https://book.sfacg.com/novel/123/',
                'provenance':{'retrieved':{'cover_url':'https://rss.sfacg.com/cover.jpg'}}})
        self.assertEqual(result.status_code,200)
        enqueue.assert_called_once_with(result.json()['path'])
        self.assertTrue((self.local/'library'/result.json()['path']).exists())

    def test_upload_and_authenticated_image_route(self):
        import base64
        path=self.post('/api/books',{'title':'封面','category':'科幻'}).json()['path']
        response=self.client.put('/api/books/cover',json={'path':path,'image':base64.b64encode(png()).decode()},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/api/books/cover',params={'path':path}).status_code,403)
        image=self.client.get('/api/books/cover',params={'path':path},headers=self.headers)
        self.assertEqual(image.headers['content-type'],'image/png')
        self.assertEqual(image.content[:8],b'\x89PNG\r\n\x1a\n')
        self.assertEqual(self.post('/api/books/cover',{'path':path}).status_code,409)
        self.assertTrue(self.client.get('/api/books',headers=self.headers).json()[0]['cover']['has_image'])
