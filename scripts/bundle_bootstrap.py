"""Build a clean Windows bootstrap without copying virtualenvs or user data."""
import hashlib
from pathlib import Path
import shutil
import sys
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
UV_FILE='uv-0.12.17-py3-none-win_amd64.whl'
UV_HASH='7a14aafc5d5816cebfb8b61b8529fe6f9b99210363523fe2a9d441e757bd3cb7'
UV_PATH='54/19/1d5009571cecd0b1c4260823e95dc0c11ccc9429ad0a7cadebab855886cc/'+UV_FILE


def bundle_windows_bootstrap(destination):
    destination=Path(destination)
    python=Path(sys.base_prefix).resolve()
    local_python=any(python.is_relative_to(path.resolve()) for path in (ROOT/'.runtime',ROOT/'vendor/python'))
    if sys.platform!='win32' or sys.version_info[:2]!=(3,12) or not local_python:
        raise ValueError('Use the project-local Windows Python 3.12 environment to build the bootstrap.')
    if (destination/'vendor/python').exists():
        raise FileExistsError('Use a fresh staging directory; do not merge an existing runtime into a release.')
    wheel=ROOT/'.runtime/bootstrap'/UV_FILE;wheel.parent.mkdir(parents=True,exist_ok=True)
    if not wheel.exists() or hashlib.sha256(wheel.read_bytes()).hexdigest()!=UV_HASH:
        last=None
        for base in ('https://mirrors.tuna.tsinghua.edu.cn/pypi/web/packages/','https://files.pythonhosted.org/packages/'):
            for proxy in ({},None):
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler(proxy)).open(base+UV_PATH,timeout=90) as response:
                        data=response.read()
                    if hashlib.sha256(data).hexdigest()!=UV_HASH:raise ValueError('uv wheel checksum mismatch')
                    wheel.write_bytes(data);last=None;break
                except (OSError,ValueError) as error:last=error
            if last is None:break
        if last:raise last
    uv=destination/'vendor/uv';uv.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(wheel) as archive:
        binary=next(name for name in archive.namelist() if name.endswith('/scripts/uv.exe'))
        (uv/'uv.exe').write_bytes(archive.read(binary))
        for name in archive.namelist():
            if '.dist-info/licenses/' in name and not name.endswith('/'):
                relative=Path(name.split('.dist-info/licenses/',1)[1])
                if relative.is_absolute() or '..' in relative.parts:raise ValueError('Invalid license path')
                target=uv/'licenses'/relative;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(archive.read(name))
    def ignore(directory,names):
        return [name for name in names if name in ('site-packages','__pycache__','Scripts','.git','.local','.runtime') or name.endswith(('.pyc','.pyo'))]
    shutil.copytree(python,destination/'vendor/python',ignore=ignore,dirs_exist_ok=True)
    return destination/'vendor'
