import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from app.paths import ROOT

BASH=shutil.which('bash') if os.name!='nt' else next((str(p) for p in [Path('C:/Program Files/Git/bin/bash.exe')] if p.exists()),None)


@unittest.skipUnless(BASH,'Bash is required')
class PosixLauncherTests(unittest.TestCase):
    def setUp(self):
        scratch=ROOT/'tmp/posix-tests';scratch.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=scratch,prefix='含 空格-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'scripts').mkdir()
        shutil.copy2(ROOT/'scripts/launcher.sh',self.root/'scripts/launcher.sh')
        for name in ['pyproject.toml','uv.lock']:shutil.copy2(ROOT/name,self.root/name)
        self.fake=self.root/'fake-bin';self.fake.mkdir()
        self.system='Linux';self.arch='x86_64'

    def run_launcher(self,mode,answer):
        uname=self.fake/'uname'
        uname.write_text(f'#!/bin/sh\ncase "$1" in -s) echo {self.system};; -m) echo {self.arch};; esac\n',encoding='utf8')
        uname.chmod(0o755)
        # A fixture uname exercises routing, not an emulation of the target OS.
        command='export PATH="$PWD/fake-bin:$PATH"; exec bash scripts/launcher.sh "$1" --no-browser'
        return subprocess.run([BASH,'-c',command,'test',mode],cwd=self.root,input=answer.encode('utf8'),
                              capture_output=True,timeout=15)

    def test_all_four_targets_can_decline_without_creating_state(self):
        for system,arch in [('Linux','x86_64'),('Linux','aarch64'),('Darwin','x86_64'),('Darwin','arm64')]:
            self.system,self.arch=system,arch
            result=self.run_launcher('setup','n\n')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse((self.root/'.runtime').exists())
            self.assertFalse((self.root/'.local').exists())

    def test_clean_decline_keeps_data(self):
        (self.root/'.local').mkdir();file=self.root/'.local/keep';file.write_text('keep')
        self.assertEqual(self.run_launcher('clean','no\n').returncode,0)
        self.assertTrue(file.exists())

    def test_clean_only_removes_named_application_directories(self):
        for name in ['.runtime','.local','.agents/.venv-ocr']:
            path=self.root/name;path.mkdir(parents=True);(path/'dummy').write_text('remove')
        keep=self.root/'keep.txt';keep.write_text('keep')
        result=self.run_launcher('clean','CLEAN\n')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(keep.exists())
        self.assertFalse((self.root/'.runtime').exists())
        self.assertFalse((self.root/'.local').exists())

    def test_script_syntax(self):
        for file in [ROOT/'scripts/launcher.sh',*ROOT.glob('*.sh'),*ROOT.glob('*.command')]:
            result=subprocess.run([BASH,'-n',str(file)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_cleanup_unlinks_runtime_without_deleting_target(self):
        outside=self.root/'external-keep';outside.mkdir();(outside/'keep').write_text('keep')
        try:(self.root/'.runtime').symlink_to(outside,target_is_directory=True)
        except OSError:self.skipTest('Host does not permit creating directory symlinks')
        result=self.run_launcher('clean','CLEAN\n')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue((outside/'keep').exists())
        self.assertFalse((self.root/'.runtime').is_symlink())
