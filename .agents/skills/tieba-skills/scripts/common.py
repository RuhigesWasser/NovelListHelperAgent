"""Path and input utilities for the Shiye command-line tools (MIT)."""
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import re
import sys


def project_root(start=None):
    origin=Path(start or Path.cwd()).resolve()
    for directory in (origin,*origin.parents):
        if any((directory/name).exists() for name in ('pyproject.toml','.agents','AGENTS.md','AGENT.md')):
            return str(directory)
    return str(origin)


def extract_tid(raw):
    value=str(raw).strip()
    if value.isdecimal():return int(value)
    parts=urlsplit(value)
    match=re.search(r'/p/([0-9]+)(?:/|$)',parts.path)
    candidate=match.group(1) if match else parse_qs(parts.query).get('tid',[''])[0]
    if candidate.isdecimal():return int(candidate)
    raise ValueError('请输入贴吧帖子 URL 或数字 ID')


def ensure_utf8_stdout():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
