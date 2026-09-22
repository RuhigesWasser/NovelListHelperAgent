#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
贴吧帖子楼层抓取脚本（匿名读取）
================================

用 aiotieba 读取任意贴吧帖子链接的全部楼层：楼层正文文本 + 楼层内嵌图片。
图片按“原图优先”下载到本地并做尺寸/体积预处理（便于后续 AI 识图），
输出中间 JSON（含楼层号、正文、图片本地路径），供下一步识图后合并为最终数组。

用法:
    python fetch_thread.py <帖子链接或tid> [--img-dir DIR] [--out FILE] [--size origin|big|src]
    python fetch_thread.py https://tieba.baidu.com/p/10085546563?fr=frs
    python fetch_thread.py 10085546563 --img-dir D:\\tmp\\imgs --out thread.json

图片默认缓存到「项目根/tmp/tieba_<tid>」（项目根 = 含 AGENTS.md/AGENT.md 或 .agents 的目录）。

依赖: aiotieba（未安装时脚本会自动 pip install；识图预处理依赖 Pillow，缺失时仅跳过压缩）
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import urllib.request

from common import ensure_utf8_stdout, extract_tid, project_root

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Referer": "https://tieba.baidu.com/"}

# Read 工具对单图约 5MiB(Base64) 的限制；超过阈值或长边过长时先压缩
MAX_FILE_BYTES = 3_500_000
MAX_EDGE = 2048


def ensure_aiotieba() -> None:
    try:
        import aiotieba  # noqa: F401
    except ImportError:
        print("[提示] 未安装 aiotieba，正在自动安装……", file=sys.stderr)
        subprocess.run([sys.executable, "-m", "pip", "install", "aiotieba"], check=True)
        import aiotieba  # noqa: F401


def pick_url(img, size: str) -> str:
    """按 size 选择图片链接：origin=原图 / big=960px / src=720px"""
    if size == "origin":
        return img.origin_src or img.big_src or img.src
    if size == "big":
        return img.big_src or img.src
    return img.src


def img_hash(url: str) -> str:
    m = re.search(r"/([a-f0-9]{32,})\.", url)
    return m.group(1) if m else ""


def download(url: str, path: str) -> None:
    """下载图片到 path（带重试一次）"""
    last_err: Exception | None = None
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            with open(path, "wb") as f:
                f.write(data)
            return
        except Exception as e:
            last_err = e
    raise last_err or RuntimeError("下载失败")


def preprocess(path: str) -> None:
    """压缩超大/超长图片，保证 AI 识图可读（Pillow 缺失时跳过）"""
    try:
        if os.path.getsize(path) <= MAX_FILE_BYTES:
            return
        from PIL import Image

        im = Image.open(path)
        w, h = im.size
        scale = min(1.0, MAX_EDGE / max(w, h))
        if scale < 1.0:
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        if im.mode in ("RGBA", "P", "LA"):
            im = im.convert("RGB")
        tmp = path + ".tmp.jpg"
        im.save(tmp, "JPEG", quality=85, optimize=True)
        os.replace(tmp, path)
        print(f"  [压缩] {os.path.basename(path)} -> {os.path.getsize(path)} bytes", file=sys.stderr)
    except ImportError:
        print(f"  [警告] 未安装 Pillow，跳过 {os.path.basename(path)} 的压缩（图片可能过大无法识图）", file=sys.stderr)
    except Exception as e:
        print(f"  [警告] 图片预处理失败 {os.path.basename(path)}: {e}", file=sys.stderr)


async def fetch_thread(tid: int, img_dir: str, size: str, rn: int) -> dict:
    from aiotieba import Client

    seen_hashes: set[str] = set()
    floors: list[dict] = []
    title, fname = "", ""
    pn = 1
    async with Client() as client:
        while True:
            posts = await client.get_posts(tid, pn=pn, rn=rn)
            if pn == 1:
                title = posts.thread.title or ""
                fname = posts.forum.fname or ""
            for post in posts.objs:
                floor_item: dict = {"floor": post.floor, "text": post.text or "", "images": []}
                for i, img in enumerate(post.contents.imgs, 1):
                    url = pick_url(img, size)
                    h = img_hash(url)
                    if not h:
                        h = f"{post.floor}_{i}"
                    fname_ = f"f{post.floor}_{i}_{h}.jpg"
                    path = os.path.join(img_dir, fname_)
                    if h in seen_hashes:
                        # 同一图片重复出现（跨楼层），复用已下载文件
                        pass
                    else:
                        seen_hashes.add(h)
                        download(url, path)
                        preprocess(path)
                    floor_item["images"].append({"url": url, "file": path, "hash": h})
                floors.append(floor_item)
            if not posts.has_more:
                break
            pn += 1
            await asyncio.sleep(0.3)  # 翻页间隔，避免触发风控

    return {
        "tid": tid,
        "url": f"https://tieba.baidu.com/p/{tid}",
        "fname": fname,
        "title": title,
        "floor_count": len(floors),
        "floors": floors,
    }


def main() -> int:
    ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description="抓取贴吧帖子楼层文本与图片")
    parser.add_argument("input", help="贴吧帖子链接或纯数字 tid")
    parser.add_argument("--img-dir", help="图片下载目录（默认：项目根/tmp/tieba_帖子ID）")
    parser.add_argument("--out", help="中间 JSON 输出路径（默认仅打印到 stdout）")
    parser.add_argument("--size", choices=["origin", "big", "src"], default="origin", help="图片尺寸：origin=原图(默认) big=960px src=720px")
    parser.add_argument("--rn", type=int, default=30, help="每页楼层数（默认 30）")
    args = parser.parse_args()

    try:
        tid = extract_tid(args.input)
        ensure_aiotieba()
        img_dir = args.img_dir or os.path.join(project_root(), "tmp", f"tieba_{tid}")
        os.makedirs(img_dir, exist_ok=True)
        print(f"[抓取] tid={tid} 图片目录={img_dir}", file=sys.stderr)

        data = asyncio.run(fetch_thread(tid, img_dir, args.size, args.rn))

        text = json.dumps(data, ensure_ascii=False, indent=2)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"[完成] 已写入 {args.out}", file=sys.stderr)
        print(text)
        return 0
    except Exception as e:
        print(f"[失败] {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
