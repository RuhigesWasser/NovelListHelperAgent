import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from app.paths import ROOT
from app.agent_tools import AgentTools
from app.library import LibraryError
from app.llm_settings import LlmSettings
from app.server import Settings, RecoverySettings
from app import recovery
from scripts.package_apps import copy_source, archive


class EditionTests(unittest.TestCase):
    def test_reasoning_budget_and_saved_preferences(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            local=Path(directory)
            self.assertEqual(LlmSettings(local).current()['max_tokens'],32768)
            self.assertEqual(recovery.settings(local)['max_tokens'],32768)
            (local/'settings.json').write_text(json.dumps({'max_tokens':2048}))
            self.assertEqual(LlmSettings(local).current()['max_tokens'],2048)
            self.assertEqual(Settings(max_tokens=65536).max_tokens,65536)
            self.assertEqual(RecoverySettings(max_tokens=65536).max_tokens,65536)

    def test_agent_archive_without_server(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory, patch.dict(os.environ), patch('tempfile.tempdir',None):
            agent=AgentTools(Path(directory))
            try:
                result=agent.call('archive_book',{'title':'测试小说','category':'科幻','author':'作者'})
                self.assertEqual(result['path'],'科幻/测试小说/测试小说.md')
                self.assertIn('作者', (Path(directory)/'.local/library'/result['path']).read_text(encoding='utf8'))
                self.assertEqual(agent.call('list_books',{})[0]['title'],'测试小说')
                with self.assertRaises(LibraryError):
                    agent.call('archive_book',{'title':'测试小说','category':'科幻'})
            finally:agent.close()

    def test_agent_json_lines_and_unicode(self):
        proc=subprocess.run([sys.executable,'-B','-m','app.agent_tools','serve'],
            input='{"id":"中文","action":"不存在"}\n{"id":2,"action":"list_books"}\n',
            encoding='utf8',capture_output=True,cwd=ROOT)
        self.assertEqual(proc.returncode,0,proc.stderr)
        first,second=map(json.loads,proc.stdout.splitlines())
        self.assertEqual(first['id'],'中文');self.assertFalse(first['ok'])
        self.assertTrue(second['ok'])

    def test_source_package_omits_state(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            root=Path(directory);stage=root/'stage'
            copy_source(stage)
            self.assertTrue((stage/'app/agent_tools.py').exists())
            self.assertFalse((stage/'.local').exists())
            self.assertFalse((stage/'.runtime').exists())
            (stage/'.local').mkdir();(stage/'.local/secret').write_text('test')
            with self.assertRaises(ValueError):archive(stage,root/'invalid.zip')

    def test_three_independent_source_projects(self):
        import zipfile
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            root=Path(directory)
            for edition in ('agent','browser','windows'):
                target=copy_source(root/edition,edition)
                self.assertIn('MIT License',(target/'LICENSE').read_text())
                self.assertTrue((target/'README.md').is_file())
                self.assertEqual([p.name for p in (target/'docs').iterdir()],['USAGE.md'])
                self.assertFalse((target/'project.json').exists())
                self.assertFalse((target/'.runtime').exists())
                if edition=='agent':
                    self.assertFalse((target/'app').exists())
                    self.assertFalse((target/'.agents/scripts/app/server.py').exists())
                    command=[sys.executable,'-B','.agents/scripts/agent.py','schema']
                else:
                    self.assertFalse((target/'AGENTS.md').exists())
                    self.assertFalse((target/'.agents').exists())
                    self.assertTrue((target/'tools/tieba/ocr.py').is_file())
                    command=[sys.executable,'-B','-c',"from app.paths import ROOT; from app.server import create_app; import fetch_novel_fields; print(ROOT); print(fetch_novel_fields.__file__)"]
                result=subprocess.run(command,cwd=target,capture_output=True,encoding='utf8',env={**os.environ,'PYTHONUTF8':'1'})
                self.assertEqual(result.returncode,0,result.stderr)
                if edition=='agent':self.assertIn('archive_book',json.loads(result.stdout)['tools'])
                else:self.assertIn(str(target),result.stdout)
                self.assertEqual((target/'desktop/windows/Program.cs').exists(),edition=='windows')
                archive(target,root/(edition+'.zip'))
                with zipfile.ZipFile(root/(edition+'.zip')) as bundle:
                    self.assertIn('LICENSE',bundle.namelist())
                    self.assertEqual((bundle.getinfo('scripts/launcher.sh').external_attr>>16)&0o111,0o111)
