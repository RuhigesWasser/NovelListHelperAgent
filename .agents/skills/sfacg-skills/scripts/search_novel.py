#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
菠萝包小说（sfacg）书名搜索脚本
================================

根据书名（或部分书名关键词）在菠萝包搜索小说，返回小说ID等基本字段。
配合 fetch_novel_fields.py 使用：先搜索得到 novelId，再提取推荐模板所需完整字段。

用法:
    python search_novel.py <书名或关键词> [更多关键词...]
    python search_novel.py 最强魔法少女
    python search_novel.py 变嫁 --size 20
    python search_novel.py "最强魔法少女才不会白给雑鱼反派" --exact
    python search_novel.py 魔法少女 --table

参数:
    --size N   每页返回数量（默认 20，最大 50）
    --exact    仅保留与书名完全一致的匹配（忽略空白差异）
    --table    输出易读表格（默认输出 JSON）
    --json     显式指定输出 JSON（默认行为）

输出:
    JSON 模式: 每个查询一个对象，含 novelId、novelName、authorName、coverUrl、novelUrl、exactMatch
    退出码: 任一查询失败或无命中时返回 1
"""

import argparse
import gzip
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# 复用 fetch_novel_fields.py 的请求头与常量，保持一致且避免重复维护
try:
    from fetch_novel_fields import API_BASE, BOOK_URL_BASE, HEADERS, FetchError
except ImportError:
    sys.stderr.write(
        "[错误] 缺少依赖文件 fetch_novel_fields.py：请将 search_novel.py 与 "
        "fetch_novel_fields.py 放在同一目录运行。\n"
    )
    sys.exit(2)

SEARCH_PATH = "/search/novels"


class SearchError(Exception):
    """搜索接口调用失败"""


def norm(s: str) -> str:
    """去除全部空白（含全角空格），用于书名精确比对"""
    return re.sub(r"\s+", "", s or "")


def search_by_name(keyword: str, size: int = 20) -> list:
    """调用菠萝包搜索接口，按书名关键词搜索，返回 data.items 列表"""
    params = {"key": keyword, "page": 0, "size": size}
    url = f"{API_BASE}{SEARCH_PATH}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                raw = gzip.decompress(raw)
            payload = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise SearchError(f"接口返回 HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise SearchError(f"网络请求失败: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise SearchError(f"接口返回非 JSON 数据: {e}") from e

    status = payload.get("status") or {}
    data = payload.get("data")
    if data is None or status.get("errorCode") not in (200, None):
        raise SearchError(f"接口返回错误 status={status.get('errorCode')} msg={status.get('msg')}")
    return data.get("items") or []


def format_results(keyword: str, items: list, exact_only: bool) -> list:
    """将接口 items 整理为输出字段，并按需过滤精确同名"""
    results = []
    for it in items:
        novel_id = it.get("novelId")
        novel_name = it.get("novelName") or ""
        results.append({
            "novelId": novel_id,
            "novelName": novel_name,
            "authorName": it.get("authorName"),
            "categoryId": it.get("categoryId"),
            "coverUrl": it.get("novelCover"),
            "novelUrl": BOOK_URL_BASE.format(novel_id=novel_id) if novel_id else None,
            "exactMatch": bool(novel_id and norm(novel_name) == norm(keyword)),
        })
    if exact_only:
        results = [r for r in results if r["exactMatch"]]
    return results


def render_table(blocks: list) -> None:
    """输出易读表格"""
    for block in blocks:
        print(f"## 查询：{block['query']}（命中 {block['count']} 条）")
        for r in block["results"]:
            mark = "【精确】" if r.get("exactMatch") else ""
            name = r["novelName"] or "（无书名）"
            author = r["authorName"] or "-"
            print(f"  {r['novelId']}\t{name}\t{author}\t{mark}")
        print()


def main():
    parser = argparse.ArgumentParser(description="按书名搜索菠萝包小说并获取书ID")
    parser.add_argument("names", nargs="+", help="书名或书名关键词，可传多个")
    parser.add_argument("--size", type=int, default=20, help="每页返回数量（默认 20，最大 50）")
    parser.add_argument("--exact", action="store_true", help="仅保留与书名完全一致的匹配")
    parser.add_argument("--table", action="store_true", help="输出易读表格")
    parser.add_argument("--json", action="store_true", help="输出 JSON（默认）")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    size = max(1, min(args.size, 50))
    blocks, errors, empty = [], [], []
    for keyword in args.names:
        try:
            items = search_by_name(keyword, size)
        except SearchError as e:
            errors.append({"query": keyword, "error": str(e)})
            continue
        results = format_results(keyword, items, args.exact)
        if not results:
            empty.append({"query": keyword, "hits": len(items)})
        blocks.append({"query": keyword, "count": len(results), "results": results})

    if args.table and not args.json:
        render_table(blocks)
    else:
        out = blocks
        if errors or empty:
            out = {"results": blocks, "errors": errors, "empty": empty}
        print(json.dumps(out, ensure_ascii=False, indent=2))

    for e in errors:
        print(f"[警告] 查询失败 {e['query']}: {e['error']}", file=sys.stderr)
    for m in empty:
        hint = ""
        if args.exact:
            hint = f"；去掉 --exact 可查看 {m['hits']} 条近似结果" if m["hits"] else "；可尝试更换关键词"
        print(f"[警告] 未找到匹配 {m['query']!r}{hint}", file=sys.stderr)

    if errors or empty:
        sys.exit(1)


if __name__ == "__main__":
    main()
