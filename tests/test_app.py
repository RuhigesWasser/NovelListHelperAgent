import base64
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from app.paths import ROOT
from app.server import create_app


class AppTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT/'tmp/app-tests'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.local = Path(self.temp.name)
        for name in ('jobs', 'library'):
            (self.local/name).mkdir()
        self.app = create_app(self.local, 'test-session')
        self.client = TestClient(self.app, base_url='http://127.0.0.1')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.headers = {'X-Session-Token': 'test-session'}

    def post(self, path, body):
        return self.client.post(path, json=body, headers=self.headers)

    def test_local_security_and_page(self):
        self.assertEqual(self.client.get('/api/settings').status_code, 403)
        self.assertEqual(self.client.get('/api/settings', headers={**self.headers, 'Origin':'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/', headers={'Host':'evil.example'}).status_code, 403)
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('test-session', page.text)
        self.assertEqual(page.headers['Cache-Control'], 'no-store')

    def test_key_never_persists(self):
        response = self.post('/api/settings', {'base_url':'https://example.test/v1','model':'vision','key':'secret-memory-only','remember_key':False})
        self.assertTrue(response.json()['has_key'])
        self.assertNotIn('secret-memory-only', response.text)
        self.assertNotIn('secret-memory-only', (self.local/'settings.json').read_text(encoding='utf8'))
        changed = self.post('/api/settings', {'base_url':'https://other.example/v1','model':'vision'})
        self.assertFalse(changed.json()['has_key'])
        self.post('/api/settings', {'clear_key': True})
        self.assertFalse(self.client.get('/api/settings', headers=self.headers).json()['has_key'])
        invalid=self.post('/api/settings', {'key':'private-key-'*500})
        self.assertEqual(invalid.status_code,422)
        self.assertNotIn('private-key', invalid.text)

    def test_invalid_sources_and_engine(self):
        for data in ({'kind':'image','image':'not base64'}, {'kind':'tieba','source':'hello'},
                     {'kind':'image','engine':'llm'}, {'kind':'anything'}):
            self.assertEqual(self.post('/api/jobs', data).status_code, 400)

    def test_archive_index_and_no_escape(self):
        book = {'title':'测试书','category':'科幻','author':'作者','intro':'简介'}
        result = self.post('/api/books', book)
        self.assertEqual(result.status_code, 200)
        path = self.local/'library/科幻/测试书/测试书.md'
        self.assertIn('## 元数据', path.read_text(encoding='utf-8'))
        self.assertIn('测试书', (self.local/'library/索引.md').read_text(encoding='utf-8'))
        self.assertEqual(self.post('/api/books', book).status_code, 409)
        self.assertEqual(self.post('/api/books', {**book,'overwrite':True}).status_code, 200)
        self.assertEqual(self.post('/api/books', {**book,'title':'../escape'}).status_code, 400)
        self.assertEqual(self.client.get('/api/books/download',params={'path':'../../settings.json'},headers=self.headers).status_code,400)
        self.assertEqual(self.client.get('/api/books/download',params={'path':result.json()['path']},headers=self.headers).status_code,200)

    def test_mock_search_and_fill(self):
        with patch('search_novel.search_by_name', return_value=[{'novelId':12,'novelName':'测试书','authorName':'测试作者'}]):
            r = self.client.get('/api/search', params={'q':'测试书'}, headers=self.headers)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()[0]['novelId'],12)
        with patch('fetch_novel_fields.fetch_novel', return_value={'novelId':12,'novelName':'测试书','expand':{'intro':'简介'}}):
            self.assertEqual(self.client.get('/api/novels/12',headers=self.headers).json()['intro'],'简介')

    def test_real_image_job_edit_and_download(self):
        font_path = Path('C:/Windows/Fonts/msyh.ttc')
        if not font_path.exists():
            self.skipTest('Windows Chinese font required for real OCR')
        im = Image.new('RGB',(700,220),'white')
        ImageDraw.Draw(im).text((20,50),'书名：星河旅人 123',font=ImageFont.truetype(str(font_path),36),fill='black')
        buf = io.BytesIO(); im.save(buf,format='PNG')
        response = self.post('/api/jobs', {'kind':'image','source':'sample.png','auto_mode':'off','image':base64.b64encode(buf.getvalue()).decode()})
        self.assertEqual(response.status_code,200)
        job_id = response.json()['id']
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            job=self.app.state.jobs.get(job_id)
            if job['state'] not in ('queued','running'): break
            time.sleep(.2)
        self.assertEqual(job['state'],'succeeded',job)
        result=self.client.get(f'/api/jobs/{job_id}/result',headers=self.headers).json()['result']
        self.assertIn('星河旅人',result[0]['images'][0])
        self.assertEqual(self.client.get(f'/api/jobs/{job_id}/image/0/0',headers=self.headers).status_code,200)
        result[0]['images'][0]='校对结果'
        self.assertEqual(self.client.put(f'/api/jobs/{job_id}/result',json=result,headers=self.headers).status_code,200)
        self.assertEqual(self.client.put(f'/api/jobs/{job_id}/result',json=[],headers=self.headers).status_code,400)
        self.assertEqual(json.loads((self.local/'jobs'/job_id/'result.json').read_text(encoding='utf-8'))[0]['images'][0],'校对结果')

    def test_cancel_queued_and_resume_marker(self):
        with patch.object(self.app.state.jobs.pool,'submit'):
            job=self.app.state.jobs.submit('tieba','123','builtin',{})
            self.post(f'/api/jobs/{job["id"]}/cancel',{})
            self.assertEqual(self.app.state.jobs.get(job['id'])['state'],'cancelled')

    def test_result_keeps_original_floor_numbers(self):
        with patch.object(self.app.state.jobs.pool, 'submit'):
            job = self.app.state.jobs.submit('tieba', '123', 'builtin', {})
        folder = self.local/'jobs'/job['id']
        (folder/'raw.json').write_text(json.dumps({'floors': [
            {'floor': 1, 'text': 'one', 'images': []},
            {'floor': 17, 'text': 'seventeen', 'images': []}]}), encoding='utf-8')
        (folder/'result.json').write_text(json.dumps([
            {'text': 'one', 'images': []}, {'text': 'seventeen', 'images': []}]), encoding='utf-8')
        self.app.state.jobs.update(job['id'], 'succeeded')
        result = self.client.get(f'/api/jobs/{job["id"]}/result', headers=self.headers)
        self.assertEqual(result.json()['floors'], [1, 17])

    def test_catalog_routes_and_model_consent(self):
        platforms=self.client.get('/api/platforms',headers=self.headers).json()
        self.assertEqual({p['id'] for p in platforms},{'sfacg','fanqie','esj','qidian','ciweimao'})
        with patch('app.providers.fetch_html',return_value='<title>輕小說 - 原創 - ESJ Zone</title>'):
            result=self.client.get('/api/catalog/search',params={'q':'书名','platform':'esj'},headers=self.headers)
        self.assertTrue(result.json()['warnings'])
        self.assertEqual(self.post('/api/catalog/detail',{'url':'https://127.0.0.1/'}).status_code,400)
        self.assertEqual(self.post('/api/ocr/models',{'language':'japan','confirmed':False}).status_code,400)

    def test_reocr_preserves_original_and_uses_selected_language(self):
        from app import ocr_models
        with patch.object(self.app.state.jobs.pool,'submit'),patch.object(ocr_models,'require',return_value=Path('model.onnx')):
            job=self.app.state.jobs.submit('image','original','builtin',{},b'image')
            folder=self.local/'jobs'/job['id']
            (folder/'raw.json').write_text(json.dumps({'floors':[{'floor':9,'images':[{'file':str(folder/'input.png')}]}]}),encoding='utf-8')
            (folder/'result.json').write_text('original-result',encoding='utf-8')
            self.app.state.jobs.update(job['id'],'succeeded')
            result=self.post(f'/api/jobs/{job["id"]}/reocr',{'floor':0,'image':0,'language':'japan'})
            self.assertEqual(result.status_code,200)
            self.assertNotEqual(result.json()['id'],job['id'])
            self.assertEqual(result.json()['language'],'japan')
            self.assertEqual((folder/'result.json').read_text(encoding='utf8'),'original-result')
            origin=json.loads((self.local/'jobs'/result.json()['id']/'origin.json').read_text(encoding='utf-8'))
            self.assertEqual(origin['job_id'],job['id'])

    def test_archived_lookup_and_manual_overwrite(self):
        book={'title':'来源测试','category':'科幻','provenance':{'retrieved':{'url':'https://example.test/book'},'user_edited_fields':['intro']}}
        self.assertEqual(self.post('/api/books',book).status_code,200)
        path=self.local/'library/科幻/来源测试/来源测试.metadata.json'
        self.assertEqual(json.loads(path.read_text(encoding='utf8'))['lookup'],book['provenance'])
        self.assertEqual(self.post('/api/books',{'title':'来源测试','category':'科幻','overwrite':True}).status_code,200)
        self.assertIsNone(json.loads(path.read_text(encoding='utf8'))['lookup'])

    def test_llm_connection_success_does_not_allow_text_only_ocr(self):
        from test_llm import service
        with service('chat_completions',text='OK') as (url,calls):
            settings={'base_url':url,'model':'text-only','name':'Text model','remember_key':False}
            self.assertEqual(self.post('/api/settings',settings).status_code,200)
            connection=self.post('/api/settings/test',{'kind':'connection'})
            self.assertTrue(connection.json()['ok'])
            vision=self.post('/api/settings/test',{'kind':'vision'})
            self.assertEqual(vision.status_code,400)
            self.assertEqual(vision.json()['code'],'vision_unverified')
            buffer=io.BytesIO();Image.new('RGB',(40,40),'white').save(buffer,format='PNG')
            job=self.post('/api/jobs',{'kind':'image','engine':'llm','image':base64.b64encode(buffer.getvalue()).decode()})
            self.assertEqual(job.status_code,400)
            self.assertEqual(self.app.state.jobs.list(),[])

    def test_profile_selection_and_api_never_echo_key(self):
        first=self.post('/api/settings',{'id':'new','name':'A','key':'saved-test-key','remember_key':True}).json()
        second=self.post('/api/settings',{'id':'new','name':'B'}).json()
        chosen=self.post('/api/settings/activate',{'id':first['active_id']})
        self.assertEqual(chosen.json()['name'],'A')
        self.assertTrue(chosen.json()['has_key'])
        self.assertNotIn('saved-test-key',chosen.text)
        stored=json.loads((self.local/'settings.json').read_text(encoding='utf8'))
        self.assertEqual(stored['active_id'],first['active_id'])
        deleted=self.client.delete('/api/settings/profiles/'+first['active_id'],headers=self.headers)
        self.assertEqual(deleted.status_code,200)
        self.assertNotIn('saved-test-key',(self.local/'settings.json').read_text(encoding='utf8'))


if __name__=='__main__':
    unittest.main()
