import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from PIL import Image
from app.paths import ROOT, add_tools
from app.llm_settings import LlmSettings

add_tools()
from llm_client import LlmOCR, LlmError, endpoint, fingerprint


def reply(protocol, text):
    return {
        'chat_completions':{'choices':[{'finish_reason':'stop','message':{'content':text}}]},
        'responses':{'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':text}]}]},
        'anthropic':{'stop_reason':'end_turn','content':[{'type':'text','text':text}]},
        'gemini':{'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':text}]}}]},
        'ollama':{'done':True,'done_reason':'stop','message':{'content':text}},
    }[protocol]


def stream_reply(protocol, text):
    if protocol=='chat_completions':
        return [{'choices':[{'delta':{'content':text},'finish_reason':None}]},
                {'choices':[{'delta':{},'finish_reason':'stop'}]}]
    if protocol=='responses':
        return [{'type':'response.output_text.delta','delta':text},
                {'type':'response.completed','response':reply(protocol,text)}]
    if protocol=='anthropic':
        return [{'type':'content_block_delta','delta':{'type':'text_delta','text':text}},
                {'type':'message_delta','delta':{'stop_reason':'end_turn'}},{'type':'message_stop'}]
    if protocol=='gemini':
        return [reply(protocol,text)]
    return [reply(protocol,text)]


@contextmanager
def service(protocol, text='234567', streaming=False, error=None):
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append({'path':self.path,'body':data,'headers':dict(self.headers)})
            self.send_response(400 if error else 200)
            self.send_header('Content-Type','application/x-ndjson' if streaming and protocol=='ollama'
                             else 'text/event-stream' if streaming else 'application/json')
            self.end_headers()
            if error:
                self.wfile.write(json.dumps({'error':{'message':error}}).encode())
            elif streaming:
                for event in stream_reply(protocol,text):
                    self.wfile.write(((('' if protocol=='ollama' else 'data: ')+json.dumps(event))+'\n\n').encode())
            else:
                self.wfile.write(json.dumps(reply(protocol,text)).encode())
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}',calls
    finally:server.shutdown();server.server_close();thread.join()


class LlmProtocolTests(unittest.TestCase):
    def test_endpoint_paths_and_query_preserved(self):
        expected={'chat_completions':'/v1/chat/completions','responses':'/v1/responses',
                  'anthropic':'/v1/messages','ollama':'/api/chat','gemini':'/v1beta/models/vision:generateContent'}
        for protocol,suffix in expected.items():
            self.assertEqual(endpoint('https://service.test',protocol,'vision'),'https://service.test'+suffix)
        url='https://service.test/openai/deployments/vision/chat/completions?api-version=2024-10-21'
        self.assertEqual(endpoint(url,'chat_completions','vision'),url)
        self.assertEqual(endpoint('https://service.test/custom/run?x=1','responses','vision','full'),
                         'https://service.test/custom/run?x=1')

    def test_all_protocols_over_real_http_json_and_stream(self):
        img=Image.new('RGB',(30,30),'white');buf=io.BytesIO();img.save(buf,format='PNG')
        for protocol in ('chat_completions','responses','anthropic','gemini','ollama'):
            for streaming in (False,True):
                with self.subTest(protocol=protocol,stream=streaming),service(protocol,streaming=streaming) as (url,calls):
                    client=LlmOCR(url,'vision','secret-test',protocol=protocol,stream=streaming)
                    self.assertEqual(client.request('Read this',buf.getvalue()),'234567')
                    body=calls[0]['body']
                    if protocol=='chat_completions': encoded=body['messages'][0]['content'][1]['image_url']['url'].split(',')[1]
                    elif protocol=='responses': encoded=body['input'][0]['content'][1]['image_url'].split(',')[1]
                    elif protocol=='anthropic': encoded=body['messages'][0]['content'][0]['source']['data']
                    elif protocol=='gemini': encoded=body['contents'][0]['parts'][1]['inline_data']['data']
                    else:encoded=body['messages'][0]['images'][0]
                    self.assertEqual(base64.b64decode(encoded),buf.getvalue())
                    headers={k.lower():v for k,v in calls[0]['headers'].items()}
                    if protocol in ('chat_completions','responses'):self.assertEqual(headers['authorization'],'Bearer secret-test')
                    elif protocol=='anthropic':self.assertEqual(headers['x-api-key'],'secret-test')
                    elif protocol=='gemini':self.assertEqual(headers['x-goog-api-key'],'secret-test')
                    else:self.assertNotIn('authorization',headers)

    def test_custom_auth_and_generation_options(self):
        with service('chat_completions') as (url,calls):
            client=LlmOCR(url+'/custom?api-version=v1','vision','key-value',endpoint_mode='full',auth='api-key',
                          token_field='max_completion_tokens',headers={'X-Route':'a'},extra_body={'temperature':0})
            client.request('test')
            self.assertEqual(calls[0]['path'],'/custom?api-version=v1')
            self.assertIn('max_completion_tokens',calls[0]['body'])
            self.assertNotIn('max_tokens',calls[0]['body'])
            self.assertEqual(calls[0]['body']['temperature'],0)
            self.assertEqual({k.lower():v for k,v in calls[0]['headers'].items()}['api-key'],'key-value')
        client=LlmOCR('https://service.test/custom?version=1','vision','abc',endpoint_mode='full',auth='query',key_header='access_token')
        self.assertIn('access_token=abc',client.url)

    def test_text_model_is_reported_and_ignored_images_fail_probe(self):
        with service('chat_completions',error='This model does not support image inputs.') as (url,calls):
            with self.assertRaises(LlmError) as error:LlmOCR(url,'text-only').test_vision()
            self.assertEqual(error.exception.code,'vision_unsupported')
        with service('chat_completions',text='I cannot see the image') as (url,calls):
            with self.assertRaises(LlmError) as error:LlmOCR(url,'ignores-images').test_vision()
            self.assertEqual(error.exception.code,'vision_unverified')

    def test_vision_probe_and_connection_are_distinct(self):
        with service('responses') as (url,calls),patch('llm_client.secrets.choice',side_effect=list('234567')):
            client=LlmOCR(url,'vision',protocol='responses')
            self.assertTrue(client.test_connection()['ok'])
            self.assertTrue(client.test_vision()['ok'])
            self.assertEqual(len(calls[0]['body']['input'][0]['content']),1)
            self.assertEqual(len(calls[1]['body']['input'][0]['content']),2)
            self.assertNotIn('234567',calls[1]['body']['input'][0]['content'][0]['text'])

    def test_stream_interruption_is_not_success(self):
        client=LlmOCR('http://localhost:1234','vision')
        with self.assertRaises(LlmError) as error:
            client.parse_stream(io.BytesIO(b'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\n\n'))
        self.assertEqual(error.exception.code,'incomplete')

    def test_error_redacts_key_including_query_encoding(self):
        client=LlmOCR('https://service.test','vision','abc+123')
        error=client.api_error({'error':{'message':'failed key=abc%2B123 / abc+123'}},401)
        self.assertNotIn('abc',str(error))


class ProfileTests(unittest.TestCase):
    def setUp(self):
        directory=ROOT/'tmp/profile-tests';directory.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=directory);self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        self.store=LlmSettings(self.path)

    def test_persistent_profiles_selection_and_preferences_restore(self):
        first=self.store.save({'id':'new','name':'Provider A','base_url':'https://a.test','model':'vision',
                              'key':'persistent-key','remember_key':True,'protocol':'responses'})
        self.store.save({'id':'new','name':'Provider B','base_url':'http://localhost:11434','model':'local','protocol':'ollama'})
        self.store.activate(first['active_id']);self.store.remember_task('llm','zh')
        self.store.close()
        restored=LlmSettings(self.path)
        self.assertEqual(restored.current()['key'],'persistent-key')
        self.assertEqual(restored.current()['protocol'],'responses')
        self.assertEqual(restored.preferences['engine'],'llm')
        self.assertNotIn('persistent-key',json.dumps(restored.public()))

    def test_session_key_not_saved_and_remote_change_clears_key(self):
        self.store.save({'base_url':'https://a.test/v1','model':'vision','key':'session-key','remember_key':False})
        self.assertEqual(self.store.current()['key'],'session-key')
        self.assertNotIn('session-key',(self.path/'settings.json').read_text(encoding='utf8'))
        self.assertEqual(LlmSettings(self.path).current()['key'],'')
        same=self.store.draft({'base_url':'https://a.test/v1/responses','protocol':'responses'})
        self.assertEqual(same['key'],'session-key')
        other=self.store.draft({'base_url':'https://other.test/v1'})
        self.assertEqual(other['key'],'')

    def test_legacy_settings_and_verification_invalidation(self):
        (self.path/'settings.json').write_text(json.dumps({'base_url':'https://a.test/v1','model':'old','max_tokens':2048}))
        store=LlmSettings(self.path)
        self.assertEqual(store.current()['model'],'old')
        store.mark_vision(store.current(),{'ok':True,'kind':'vision'})
        store.save({'model':'text-only'})
        self.assertNotIn('verification',store.current())

    def test_delete_profile_removes_saved_secret(self):
        result=self.store.save({'id':'new','name':'temporary','key':'deleted-key'})
        self.store.delete(result['active_id'])
        self.assertNotIn('deleted-key',(self.path/'settings.json').read_text(encoding='utf8'))

    def test_cli_restores_selected_config_without_writing_it(self):
        import argparse
        import ocr
        self.store.save({'base_url':'https://a.test/v1','model':'vision','key':'saved-key','protocol':'responses'})
        self.store.mark_vision(self.store.current(),{'ok':True,'kind':'vision'})
        before=(self.path/'settings.json').read_bytes()
        args=argparse.Namespace(ocr='llm',llm_api_key_env='NOVEL_TEST_UNUSED_KEY')
        with patch('app.llm_settings.LlmSettings',return_value=self.store):
            client=ocr.make_engine(args)
        self.assertEqual(client.protocol,'responses')
        self.assertEqual(client.url,'https://a.test/v1/responses')
        self.assertEqual(client.key,'saved-key')
        self.assertEqual((self.path/'settings.json').read_bytes(),before)


if __name__=='__main__':unittest.main()
