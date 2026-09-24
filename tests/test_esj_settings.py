import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_app
from app.esj_settings import ESJSettings
from app.paths import ROOT


class ESJSettingsTests(unittest.TestCase):
    def test_saved_account_restores_without_password_in_public_response(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            store=ESJSettings(directory)
            public=store.save('fake@example.invalid','fake-password',True)
            self.assertNotIn('fake-password',json.dumps(public))
            restored=ESJSettings(directory)
            self.assertEqual(restored.resolve('',''),('fake@example.invalid','fake-password'))
            with self.assertRaises(ValueError):restored.resolve('different@example.invalid','')
            restored.close()
            self.assertTrue((Path(directory)/'esj-settings.json').exists())

    def test_uncheck_removes_disk_copy_but_keeps_current_configuration(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            store=ESJSettings(directory)
            store.save('fake@example.invalid','fake-password',True)
            store.save('fake@example.invalid','',False)
            self.assertFalse((Path(directory)/'esj-settings.json').exists())
            self.assertEqual(store.resolve('','')[1],'fake-password')
            self.assertFalse(ESJSettings(directory).public()['has_password'])
            store.clear()
            self.assertFalse(store.public()['has_password'])


class AccountRoutesTests(unittest.TestCase):
    setUp=test_app.AppTests.setUp
    post=test_app.AppTests.post

    def test_save_restore_login_and_explicit_forget(self):
        result=self.post('/api/esj/settings',{'email':'fake@example.invalid','password':'not-a-real-secret','remember':True})
        self.assertEqual(result.status_code,200)
        self.assertNotIn('not-a-real-secret',result.text)
        with patch.object(self.app.state.esj_session,'login',return_value={'connected':True}) as login:
            self.assertEqual(self.post('/api/esj/session',{'remember':True}).status_code,200)
            self.assertEqual(login.call_args.args,('fake@example.invalid','not-a-real-secret'))
        self.client.delete('/api/esj/session',headers=self.headers)
        self.assertTrue((self.local/'esj-settings.json').exists())
        self.client.delete('/api/esj/settings',headers=self.headers)
        self.assertFalse((self.local/'esj-settings.json').exists())
        self.assertFalse(self.app.state.esj_session.connected)

    def test_temporary_developer_login_does_not_replace_saved_account(self):
        self.post('/api/esj/settings',{'email':'fake-saved@example.invalid','password':'fake-saved','remember':True})
        before=(self.local/'esj-settings.json').read_bytes()
        with patch.object(self.app.state.esj_session,'login',return_value={'connected':True}):
            self.post('/api/esj/session',{'email':'fake-temporary@example.invalid','password':'fake-temporary'})
        self.assertEqual((self.local/'esj-settings.json').read_bytes(),before)
