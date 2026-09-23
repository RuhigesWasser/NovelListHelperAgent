#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按题材/书名/书名.md 生成索引；--check 仅检查，不写入。"""
import argparse
from pathlib import Path
import sys


def render_index(root: Path, title: str) -> str:
    groups = []
    for category in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        if (not category.is_dir() or category.is_symlink()
                or category.name.startswith('.') or category.name == 'tmp'):
            continue
        books = [book.name for book in category.iterdir()
                 if book.is_dir() and not book.is_symlink()
                 and not book.name.startswith('.')
                 and (book / f'{book.name}.md').is_file()]
        if books:
            groups.append((category.name, sorted(books, key=str.casefold)))
    lines = ['```text', title]
    for i, (category, books) in enumerate(groups):
        last = i == len(groups) - 1
        lines.append(f'{"└──" if last else "├──"}{category}/  ({len(books)})')
        prefix = '    ' if last else '│   '
        for j, book in enumerate(books):
            lines.append(f'{prefix}{"└──" if j == len(books)-1 else "├──"}{book}/')
    return '\n'.join(lines + ['```', ''])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2],
                        help='书库根目录，默认 .agents 的上级目录')
    parser.add_argument('--title', default='变嫁推文整理', help='索引树标题')
    parser.add_argument('--check', action='store_true', help='索引缺失或过期时返回 1')
    args = parser.parse_args()
    if not args.root.is_dir():
        parser.error('--root 必须是已存在的目录')
    if any(c in args.title for c in '\r\n') or '`' in args.title:
        parser.error('--title 必须是单行文本，且不能包含反引号')
    try:
        result = render_index(args.root, args.title)
        target = args.root / '索引.md'
        if target.is_symlink():
            raise ValueError('索引.md 不能是符号链接')
        if target.is_file() and target.read_text(encoding='utf-8-sig') == result:
            print('索引已是最新')
            return 0
        if args.check:
            print('索引缺失或需要更新', file=sys.stderr)
            return 1
        target.write_text(result, encoding='utf-8')
        print(f'已更新：{target}')
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(f'[失败] {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
