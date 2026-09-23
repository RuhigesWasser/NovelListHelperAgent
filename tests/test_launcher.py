"""Exercise the real PowerShell consent/cleanup flow in a disposable project copy."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('powershell.exe'), 'Windows PowerShell required')
class LauncherTests(unittest.TestCase):
    def setUp(self):
        scratch=ROOT/'tmp/launcher-tests'
        scratch.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'scripts').mkdir()
        shutil.copy2(ROOT/'scripts/launcher.ps1',self.root/'scripts/launcher.ps1')
        for name in ('uv.lock','pyproject.toml'):
            shutil.copy2(ROOT/name,self.root/name)

    def launch(self,mode,input=''):
        return subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
             str(self.root/'scripts/launcher.ps1'),'-Mode',mode,'-NoBrowser'],input=input,
             text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=30)

    def test_decline_creates_no_runtime_or_data(self):
        result=self.launch('setup','n\n')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertFalse((self.root/'.runtime').exists())
        self.assertFalse((self.root/'.local').exists())

    def test_cleanup_decline_preserves_files(self):
        (self.root/'.local').mkdir()
        marker=self.root/'.local/keep.txt';marker.write_text('data')
        result=self.launch('clean','no\n')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue(marker.exists())

    def test_cleanup_only_own_directories(self):
        for relative in ('.local/jobs','.runtime/cache','.agents/.venv-ocr'):
            directory=self.root/relative;directory.mkdir(parents=True)
            (directory/'example.txt').write_text('temporary')
        (self.root/'user-document.txt').write_text('keep')
        result=self.launch('clean','CLEAN\n')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        for relative in ('.local','.runtime','.agents/.venv-ocr'):
            self.assertFalse((self.root/relative).exists())
        self.assertTrue((self.root/'user-document.txt').exists())
        self.assertTrue((self.root/'pyproject.toml').exists())

    def test_cleanup_unlinks_junction_without_touching_target(self):
        outside=self.root/'must-keep';outside.mkdir()
        (outside/'safe.txt').write_text('keep')
        (self.root/'.runtime').mkdir()
        link=self.root/'.runtime/alias'
        # Names are generated inside this isolated test directory; all deletion stays in the launcher.
        script=f"New-Item -ItemType Junction -Path '{link}' -Target '{outside}' | Out-Null"
        made=subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True)
        self.assertEqual(made.returncode,0)
        result=self.launch('clean','CLEAN\n')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertFalse((self.root/'.runtime').exists())
        self.assertTrue((outside/'safe.txt').exists())


if __name__=='__main__':
    unittest.main()
