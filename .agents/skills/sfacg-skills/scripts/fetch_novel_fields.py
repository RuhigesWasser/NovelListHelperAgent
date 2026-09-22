#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
菠萝包小说（sfacg）信息提取脚本
================================

根据菠萝包小说接口（OpenAPI: GET https://api.sfacg.com/novels/{novelId}）
提取小说所需字段，直接输出精简 JSON。

用法:
    python fetch_novel_fields.py <小说ID或链接> [更多ID或链接...]
    python fetch_novel_fields.py 739541
    python fetch_novel_fields.py https://book.sfacg.com/novel/739541/
    python fetch_novel_fields.py 739541 123456

输出:
    每个小说一个精简 JSON 对象，仅含所需字段（novelId、novelName、authorName、
    platform、charCount、status、tags、intro、novelUrl）；后续生成书名.md
    文档由项目 AGENT.md 规范负责，本脚本不生成 Markdown。
"""

import argparse
import gzip
import json
import re
import sys
import urllib.error
import urllib.request

API_BASE = "https://api.sfacg.com"
BOOK_URL_BASE = "https://book.sfacg.com/novel/{novel_id}/"

# 接口文档中要求的请求头（来自 OpenAPI 示例，已实测可用）
HEADERS = {
    "Host": "api.sfacg.com",
    "Accept-Charset": "UTF-8",
    "Authorization": "Basic YW5kcm9pZHVzZXI6MWEjJDUxLXl0Njk7KkFjdkBxeHE=",
    "User-Agent": "boluobao/4.8.14(android;28)/BDFZH2/31cc3dcc-e28f-33fb-8ec7-dae2b890eeaf",
    "Accept": "application/vnd.sfacg.api+json;version=1",
    "Accept-Encoding": "gzip",
    "sfsecurity": (
        "nonce=5BAA32A6-9AB7-4CF6-8BB1-1B964F99FDF6&timestamp=1673616403984&"
        "devicetoken=31CC3DCC-E28F-33FB-8EC7-DAE2B890EEAF&sign=1F2A670DF33290D8E13DDBF161DE6137"
    ),
}

# expand 参数：请求扩展字段列表（来自 OpenAPI 示例）
EXPAND = (
    "chapterCount,bigBgBanner,bigNovelCover,typeName,intro,fav,ticket,pointCount,tags,sysTags,"
    "signlevel,discount,discountExpireDate,totalNeedFireMoney,rankinglist,originTotalNeedFireMoney,"
    "firstchapter,latestchapter,latestcommentdate,essaytag,auditCover,preOrderInfo,customTag,topic,"
    "unauditedCustomtag,homeFlag,isbranch,essayawards"
)


class FetchError(Exception):
    """接口调用失败"""


def extract_novel_id(raw: str) -> int:
    """从小说ID或书籍链接中提取 novelId"""
    raw = raw.strip()
    m = re.search(r"/novel/(\d+)", raw)
    if m:
        return int(m.group(1))
    if raw.isdigit():
        return int(raw)
    raise FetchError(f"无法识别小说ID或链接: {raw!r}（支持纯数字ID或 https://book.sfacg.com/novel/<ID>/ 形式）")


def fetch_novel(novel_id: int) -> dict:
    """调用菠萝包小说接口获取书籍详情"""
    url = f"{API_BASE}/novels/{novel_id}?expand={EXPAND}"
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
        raise FetchError(f"接口返回 HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise FetchError(f"网络请求失败: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise FetchError(f"接口返回非 JSON 数据: {e}") from e

    status = payload.get("status") or {}
    data = payload.get("data")
    if not data or status.get("errorCode") not in (200, None):
        raise FetchError(f"接口返回错误 status={status.get('errorCode')} msg={status.get('msg')}")
    return data


def _dedup(seq):
    seen, out = set(), []
    for s in seq:
        s = (s or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def extract_fields(data: dict) -> dict:
    """从接口 data 中提取所需字段（精简输出）"""
    exp = data.get("expand") or {}
    sys_tags = [t.get("tagName", "") for t in (exp.get("sysTags") or []) if t.get("tagName")]
    custom_tags = [t for t in (exp.get("customTag") or []) if t]
    intro = (exp.get("intro") or "").strip()
    # 简介末尾常带「变嫁」「纯爱」「1v1」等作者自标标签
    intro_tags = re.findall(r"「([^」]+)」", intro)

    return {
        "novelId": data.get("novelId"),
        "novelName": data.get("novelName"),
        "authorName": data.get("authorName"),
        "platform": "菠萝包",
        "charCount": data.get("charCount") or 0,
        "status": "完结" if data.get("isFinish") else "连载中",
        "tags": _dedup(sys_tags + custom_tags + intro_tags),
        "intro": intro or "（无简介）",
        "novelUrl": BOOK_URL_BASE.format(novel_id=data.get("novelId")),
    }


def main():
    parser = argparse.ArgumentParser(description="提取菠萝包小说所需字段")
    parser.add_argument("ids", nargs="+", help="小说ID或 book.sfacg.com 书籍链接，可传多个")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    results, errors = [], []
    for raw in args.ids:
        try:
            novel_id = extract_novel_id(raw)
            data = fetch_novel(novel_id)
            results.append(extract_fields(data))
        except FetchError as e:
            errors.append({"input": raw, "error": str(e)})

    out = results if not errors else {"results": results, "errors": errors}
    print(json.dumps(out, ensure_ascii=False, indent=2))

    if errors:
        print(f"\n[警告] {len(errors)} 个输入获取失败：", file=sys.stderr)
        for e in errors:
            print(f"  - {e['input']}: {e['error']}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
