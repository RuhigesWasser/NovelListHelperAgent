import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from scripts import bundle_bootstrap
from app.paths import ROOT


class DistributionTests(unittest.TestCase):
    def test_bootstrap_omits_machine_state_and_keeps_licenses(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            root=Path(directory);python=root/'.runtime/python';python.mkdir(parents=True)
            (python/'python.exe').write_bytes(b'python')
            (python/'LICENSE.txt').write_text('Python license')
            for folder in ('Lib/site-packages','Lib/__pycache__','Scripts'):
                path=python/folder;path.mkdir(parents=True,exist_ok=True);(path/'private.txt').write_text('not shipped')
            (python/'Lib/site.py').write_text('stdlib')
            wheel=root/'.runtime/bootstrap'/bundle_bootstrap.UV_FILE;wheel.parent.mkdir()
            with zipfile.ZipFile(wheel,'w') as archive:
                archive.writestr('uv-0.12.17.data/scripts/uv.exe',b'uv')
                archive.writestr('uv-0.12.17.dist-info/licenses/LICENSE-MIT','uv license')
            digest=hashlib.sha256(wheel.read_bytes()).hexdigest()
            with patch.object(bundle_bootstrap,'ROOT',root),patch.object(bundle_bootstrap,'UV_HASH',digest),patch('sys.base_prefix',str(python)),patch('sys.platform','win32'),patch('sys.version_info',(3,12,14)):
                bundle_bootstrap.bundle_windows_bootstrap(root/'release')
            release=root/'release'
            self.assertTrue((release/'vendor/python/Lib/site.py').is_file())
            self.assertTrue((release/'vendor/python/LICENSE.txt').is_file())
            self.assertTrue((release/'vendor/uv/licenses/LICENSE-MIT').is_file())
            self.assertEqual(list(release.rglob('private.txt')),[])

    def test_bootstrap_rejects_non_project_python(self):
        with patch('sys.base_prefix','C:/external-python'):
            with self.assertRaises(ValueError):bundle_bootstrap.bundle_windows_bootstrap(ROOT/'tmp/unused-distribution')
