import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent/'pyproject.toml').is_file())


def replace_file(source,target):
    """Allow brief Windows reader/virus-scanner locks to release before replace."""
    for attempt in range(6):
        try:
            Path(source).replace(target)
            return
        except PermissionError:
            if os.name!='nt' or attempt==5:raise
            time.sleep(.02*(attempt+1))


def configure(root=ROOT):
    """Process-local paths only; no changes to registry, PATH or the user's profile."""
    root = Path(root).resolve()
    runtime, local = root / '.runtime', root / '.local'
    for path in (runtime, local, local/'tmp', local/'jobs', local/'library', local/'logs'):
        if not path.resolve().is_relative_to(root):
            raise RuntimeError('运行环境或数据目录不能链接到应用目录之外')
        path.mkdir(parents=True, exist_ok=True)
    for key, value in {
        'TEMP': local/'tmp', 'TMP': local/'tmp', 'TMPDIR': local/'tmp',
        'XDG_CACHE_HOME': runtime/'cache', 'XDG_CONFIG_HOME': local/'config',
        'XDG_DATA_HOME': local/'data', 'HF_HOME': runtime/'cache/huggingface',
        'MPLCONFIGDIR': runtime/'cache/matplotlib', 'PIP_CACHE_DIR': runtime/'cache/pip',
    }.items():
        os.environ[key] = str(value)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['PYTHONNOUSERSITE'] = '1'
    os.environ['PYTHONUTF8'] = '1'
    sys.dont_write_bytecode = True
    tempfile.tempdir = str(local/'tmp')
    return local


def add_tools():
    directories=('tools/tieba','tools/sfacg','tools/library') if (ROOT/'tools').is_dir() else ('.agents/skills/tieba-skills/scripts', '.agents/skills/sfacg-skills/scripts', '.agents/scripts')
    for relative in directories:
        sys.path.insert(0, str(ROOT/relative))
