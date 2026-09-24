import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app import ocr_models as m
from app.paths import ROOT


class ModelTest(unittest.TestCase):
    def setUp(self):
        scratch=ROOT/'tmp/model-tests';scratch.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)/'models'
        self.context=patch.object(m,'DIRECTORY',self.directory)
        self.context.start();self.addCleanup(self.context.stop)

    def test_consent_required_before_any_write_or_network(self):
        with patch('app.ocr_models.urlopen') as network:
            with self.assertRaises(ValueError):m.install('japan',False)
            network.assert_not_called()
        self.assertFalse(self.directory.exists())

    def test_require_does_not_download(self):
        with patch('app.ocr_models.urlopen') as network:
            with self.assertRaises(ValueError):m.require('japan')
            network.assert_not_called()

    def test_checksum_failure_never_installs(self):
        with patch('app.ocr_models.urlopen',return_value=io.BytesIO(b'wrong')):
            with self.assertRaisesRegex(ValueError,'校验失败'):m.install('japan',True)
        self.assertFalse((self.directory/m.MODELS['japan']['file']).exists())
        self.assertEqual(list(self.directory.glob('*.part')),[])

    def test_verified_model_usable_and_not_downloaded_again(self):
        data=b'test-model'
        models={'japan':{'name':'日文','file':'japan.onnx','sha256':hashlib.sha256(data).hexdigest()}}
        with patch.object(m,'MODELS',models),patch('app.ocr_models.urlopen',return_value=io.BytesIO(data)) as network:
            m.install('japan',True)
            self.assertEqual(m.require('japan').read_bytes(),data)
            m.install('japan',True)
            self.assertEqual(network.call_count,1)


if __name__=='__main__':unittest.main()
