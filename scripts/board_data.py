#!/usr/bin/env python3
"""Refresh the orb board (board/index.html): scan the work folder and write board/data.js.

Usage:  python scripts/board_data.py            # then open board/index.html in a browser
        python scripts/board_data.py --no-pages # do not (re)build each topic's result page

What it does, in order:
  1. Finds every work/<topic>/ that has 选题验证报告.md.
  2. Builds (or rebuilds) each topic's 选题验证结果页.html with result_page.py, so the board can link to it.
  3. Reads my_account.json if you made one (copy my_account.example.json and fill it in). No file → no account module.
  4. Writes board/data.js. The board opens from file:// — no server, no network.

The board with no topics shows a guide. board/index.html?demo=1 shows made-up example data with a watermark.
Every percentage is copied from 评论分簇.md as comment_cluster.py printed it; this script computes none.
Exit codes: 0 ok.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_parse import REPORT, parse_topic  # noqa: E402
from result_page import build as build_page, brand, OUT_NAME  # noqa: E402
from tp_common import ROOT, load_config, utf8_stdio, work_dir  # noqa: E402

BOARD = ROOT / "board"
ACCOUNT = ROOT / "my_account.json"
RECENT_NAMES = ("选题验证报告.md", "复原卡.md", "评论分簇.md", "逐字稿.md", "关键帧清单.md", "元数据.md")


def rel(p):
    return Path(os.path.relpath(p, BOARD)).as_posix()


def slim(t, folder):
    """Only what the board shows."""
    cb, cs = t["clusters"]["bench"] or {}, t["clusters"]["same"] or {}
    hits = [{k: r[k] for k in ("title", "url", "author", "c", "x", "like", "date", "dur", "why")} for r in t["rows"] if not r["side"]]
    frames = [f for f in t["frames"] if f["kind"] == "转折"] or t["frames"]
    return {
        "name": t["name"], "title": t["title"], "case": t["case"], "bench": t["bench"],
        "valid": t["valid"], "maxX": t["maxX"], "hits": hits, "search": t["search"],
        "core": (t["mech"]["bench"] or {}).get("core") or cb.get("core", ""),
        "also": (t["mech"]["bench"] or {}).get("also") or cb.get("also", ""),
        "same_core": (t["mech"]["same"] or {}).get("core") or cs.get("core", ""),
        "cells": cb.get("cells", []), "n_comments": cb.get("n", 0) + cs.get("n", 0),
        "clusters": [{k: c[k] for k in ("name", "pct", "cell", "quote", "qlike")} for c in cb.get("items", []) if c["name"] != "其他"][:5],
        "actions": cb.get("actions", [])[:3],
        "steps": t["structure"]["steps"], "n_frames": len(t["frames"]),
        "frames": [{"t": f["t"], "kind": f["kind"], "src": rel(folder / f["file"])} for f in frames[:3]],
        "has_card": t["has_card"], "has_transcript": t["has_transcript"],
        "page": rel(folder / OUT_NAME) if (folder / OUT_NAME).exists() else "",
        "report": rel(folder / REPORT), "date": datetime.fromtimestamp(t["mtime"]).strftime("%Y-%m-%d %H:%M"),
    }


def recent(folders, n=8):
    """The newest output files, as [time, '<topic>/<sub>/<file>']."""
    files = []
    for d in folders:
        for p in d.rglob("*.md"):
            if p.name in RECENT_NAMES:
                files.append((p.stat().st_mtime, p.relative_to(d.parent).as_posix()))
    files.sort(reverse=True)
    return [[datetime.fromtimestamp(m).strftime("%m-%d %H:%M"), name] for m, name in files[:n]]


def load_account():
    if not ACCOUNT.exists():
        return None
    try:
        a = json.loads(ACCOUNT.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"⚠️ my_account.json 不是合法 JSON，账号模块不显示：{e}")
        return None
    works = [w for w in a.get("works", []) if w.get("title")]
    return {"name": a.get("name", "我的账号"), "updated": a.get("updated", ""), "works": works,
            "followers": a.get("followers"), "likes_total": a.get("likes_total")}


def collect(pages=True, cfg=None):
    cfg = cfg or load_config()
    wd = work_dir(cfg)
    folders = sorted([d for d in wd.iterdir() if d.is_dir() and (d / REPORT).exists()], key=lambda d: -(d / REPORT).stat().st_mtime)
    topics, warn = [], []
    for d in folders:
        if pages:
            build_page(d, cfg)
        t = parse_topic(d)
        if not t["case"]["L"]:
            warn.append(f"{d.name}：报告里没有「情形：」一行")
        topics.append(slim(t, d))
    return {"gen": datetime.now().strftime("%Y-%m-%d %H:%M"), "demo": False, "brand": brand(cfg),
            "work": rel(wd), "topics": topics, "recent": recent(folders), "account": load_account()}, warn


def main():
    utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-pages", action="store_true")
    a = ap.parse_args()
    data, warn = collect(pages=not a.no_pages)
    BOARD.mkdir(exist_ok=True)
    out = BOARD / "data.js"
    out.write_text("window.BOARD_DATA=" + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    n = len(data["topics"])
    print(f"✅ {out}")
    print(f"选题 {n} 个｜有效同题 {sum(t['valid'] for t in data['topics'])} 条｜"
          f"关键帧 {sum(t['n_frames'] for t in data['topics'])} 张｜账号模块 {'有' if data['account'] else '无（没有 my_account.json）'}")
    if not n:
        print("还没有验证过选题：看板会显示引导。想先看效果，打开 board/index.html?demo=1。")
    for w in warn:
        print("⚠️ " + w)
    print(f"打开：{BOARD / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
