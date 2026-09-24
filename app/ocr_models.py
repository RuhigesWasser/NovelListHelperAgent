from app.paths import add_tools
add_tools()
from direct_http import urlopen
"""Opt-in language assets. Model URLs and digests are from RapidAI's v3.9.2 manifest."""
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import urllib.request
from app.paths import ROOT

DIRECTORY = ROOT/'.runtime/models'
MODELS = {
    'japan': {'name': '日文', 'file': 'japan_PP-OCRv4_rec_mobile.onnx',
              'sha256': 'e1075a67dba758ecfc7ebc78a10ae61c95ac8fb66a9c86fab5541e33f085cb7a'},
    'korean': {'name': '韩文', 'file': 'korean_PP-OCRv4_rec_mobile.onnx',
              'sha256': 'ab151ba9065eccd98f884cf4d927db091be86137276392072edd4f9d43ad7426'},
}
BASE = 'https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv4/rec/'
_lock = threading.Lock()


def valid(path, digest):
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest


def catalog():
    return [{'language': 'zh', 'name': '中文 / 英文', 'installed': True, 'download_url': None}] + [
        {'language': key, 'name': value['name'], 'installed': valid(DIRECTORY/value['file'], value['sha256']),
         'download_url': BASE+value['file']} for key, value in MODELS.items()]


def require(language):
    if language == 'zh':
        return None
    if language not in MODELS:
        raise ValueError('不支持的 OCR 语言')
    entry = MODELS[language]
    path = DIRECTORY/entry['file']
    if not valid(path, entry['sha256']):
        raise ValueError(f'{entry["name"]}模型尚未安装或校验失败，请在设置中确认下载')
    return path


def install(language, confirmed=False):
    if not confirmed:
        raise ValueError('需要明确确认后才能下载语言模型')
    if language not in MODELS:
        raise ValueError('不支持的可选模型')
    with _lock:
        entry = MODELS[language]
        if valid(DIRECTORY/entry['file'], entry['sha256']):
            return catalog()
        if not DIRECTORY.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError('模型目录必须位于应用目录内')
        DIRECTORY.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            request = urllib.request.Request(BASE+entry['file'], headers={'User-Agent':'NovelListHelperAgent/0.2'})
            with urlopen(request, timeout=60) as response, tempfile.NamedTemporaryFile(dir=DIRECTORY, suffix='.part', delete=False) as target:
                temp_path = Path(target.name)
                size = 0
                for chunk in iter(lambda: response.read(1024*1024), b''):
                    size += len(chunk)
                    if size > 100_000_000:
                        raise ValueError('模型文件超过下载大小限制')
                    target.write(chunk)
            if not valid(temp_path, entry['sha256']):
                raise ValueError('模型校验失败，未安装')
            os.replace(temp_path, DIRECTORY/entry['file'])
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()
        return catalog()
