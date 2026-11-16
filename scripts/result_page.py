#!/usr/bin/env python3
"""Turn one topic folder into a 4-screen result page (1920×1080, dark "orb" style, good for screen recording).

Usage:  python scripts/result_page.py work/<topic>            # or the path of its 选题验证报告.md
Writes: work/<topic>/选题验证结果页.html — open it in a browser; no server and no network needed.

Screens: ① verdict ② same-topic hits ③ comment mechanism ④ benchmark structure and key frames.
Keys: ↓/↑/space/PageDown change screen, 1–4 jump, R replays the screen. URL ?p=2 opens screen 2, ?static=1 turns off animation.
Reads only files in the folder (选题验证报告.md, 分簇_*/评论分簇.md, 对标/关键帧清单.md). Every percentage is copied from
评论分簇.md as the script printed it; this page computes none.
Exit codes: 0 ok; 1 no report found.
"""
import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_parse import REPORT, parse_topic  # noqa: E402
from tp_common import load_config, utf8_stdio  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent / "web" / "result_page.html"
OUT_NAME = "选题验证结果页.html"


def brand(cfg=None):
    cfg = cfg or load_config()
    return {"name": cfg.get("board_title") or "格厚AI · 爆款内容工厂",
            "sub": cfg.get("board_subtitle") or "GEHOU · NEURAL CONTENT ENGINE"}


def render(data):
    page = TEMPLATE.read_text(encoding="utf-8")
    return page.replace("__TITLE__", html.escape("选题验证 · " + data["title"])).replace(
        "__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))


def build(path, cfg=None):
    """Write the page for one topic folder; returns (output path, data) or (None, None) if there is no report."""
    folder = Path(path)
    if folder.is_file():
        folder = folder.parent
    data = parse_topic(folder)
    if not data:
        return None, None
    data["brand"] = brand(cfg)
    data["gen"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = folder / OUT_NAME
    out.write_text(render(data), encoding="utf-8")
    return out, data


def summary(d):
    cb = (d["clusters"]["bench"] or {}).get("items", [])
    warn = []
    if not d["case"]["L"]:
        warn.append("没有找到「情形：」一行")
    if not d["rows"]:
        warn.append("没有找到同题表（要有「作者」列和「a ÷ b ＝ x」列）")
    if not d["clusters"]["bench"]:
        warn.append("没有 分簇_对标/评论分簇.md，第 3 屏只显示报告里的文字")
    if not d["frames"]:
        warn.append("没有关键帧，第 4 屏只显示框架线")
    return (f"情形 {d['case']['L'] or '？'}｜有效同题 {d['valid']} 条｜最高 ×{d['maxX']:.2f}｜对标评论 {d['bench']['c'] or '？'}"
            f"｜评论簇 {len(cb)}｜框架线 {len(d['structure']['steps'])} 段｜关键帧 {len(d['frames'])} 张"), warn


def main():
    utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help=f"work/<topic> folder or its {REPORT}")
    a = ap.parse_args()
    out, d = build(Path(a.path).expanduser().resolve())
    if not out:
        print(f"找不到 {REPORT}：{a.path}")
        return 1
    line, warn = summary(d)
    print(f"✅ {out}")
    print(line)
    for w in warn:
        print("⚠️ " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
