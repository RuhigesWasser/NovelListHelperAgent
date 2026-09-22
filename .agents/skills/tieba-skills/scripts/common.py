#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tieba-skills 公共辅助函数"""
import os
import re
import sys


def project_root(start: str | None = None) -> str:
    """
    从 start（默认当前目录）向上查找项目根目录。

    项目根的特征：目录下存在 AGENTS.md/AGENT.md 或 .agents 目录（本项目规范文件）。
    找不到时回退到 start 本身。
    """
    cur = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.exists(os.path.join(cur, "AGENTS.md")) or os.path.exists(os.path.join(cur, "AGENT.md")):
            return cur
        if os.path.isdir(os.path.join(cur, ".agents")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.path.abspath(start or os.getcwd())
        cur = parent


def extract_tid(raw: str) -> int:
    """从贴吧帖子链接或纯数字中提取 tid"""
    raw = raw.strip()
    m = re.search(r"/p/(\d+)", raw)
    if m:
        return int(m.group(1))
    m = re.search(r"tid=(\d+)", raw)
    if m:
        return int(m.group(1))
    if raw.isdigit():
        return int(raw)
    raise ValueError(f"无法识别贴吧帖子链接或 tid: {raw!r}（支持 https://tieba.baidu.com/p/<tid> 或纯数字）")


def ensure_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
