#!/usr/bin/env python3
"""Check one topic folder before delivery: is every step of the topic-proof flow done?

Usage:  python scripts/check_topic.py work/<topic>

For the agent, not for the user. Run it before writing the report (step 11) and again before delivery.
Every ❌ line names the step to go back to and the command to run. Do that step, then run this check again.
Only items marked 「问用户」 need the user (for example: no video file and no consent to save one).
The result page and the board do not show these items.

Exit codes: 0 every step done; 1 something is missing; 2 no such folder.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect import MANIFEST, card_likes, parse_candidates  # noqa: E402
from report_parse import REPORT, find_sec, parse_rows, read, sections  # noqa: E402
from tp_common import load_config, utf8_stdio, work_dir  # noqa: E402

GROUPS = ("场景与原型", "矛盾", "观众说法")
PAGE = "选题验证结果页.html"
SKIP = "跳过候选.tsv"  # 片子ID<TAB>理由: cards the analyst judged off-topic from the card text


def ids_in(text):
    return set(re.findall(r"\d{15,}", text or ""))


def searched_keywords(col):
    """Keywords whose search finished with results, from every 搜索_*.json."""
    done, empty = [], []
    for p in sorted(col.glob("搜索_*.json")):
        try:
            d = json.loads(read(p))
        except json.JSONDecodeError:
            continue
        for s in d.get("searches", []):
            ok = s.get("ready", (s.get("nAuthor") or 0) > 0 or (s.get("nAnchor") or 0) > 0)
            (done if ok else empty).append(s.get("kw", ""))
    return done, empty


def passes(likes, floor):
    """Same prefilter as collect.py read -f: no like count on the card means read it."""
    return likes is None or likes >= floor


def report_keywords(s2):
    m = re.search(r"搜索词[：:]\s*([^\n]+)", s2 or "")
    if not m:
        return [], []
    line = m.group(1).split("。")[0]
    words, groups = [], []
    for part in re.split(r"[、,，;；]", line):
        g = re.search(r"[（(]([^）)]*)[）)]", part)
        w = re.sub(r"[（(][^）)]*[）)]", "", part).strip(" *_`")
        if w and w != "__":
            words.append(w)
            groups.append(g.group(1).strip() if g else "")
    return words, groups


def check(folder, cfg=None):
    """Returns a list of (ok, step, item, fix, ask_user)."""
    cfg = cfg or load_config()
    out = []

    def add(ok, step, item, fix="", ask=False):
        out.append((bool(ok), step, item, fix, ask))

    bench_dir, col = folder / "对标", folder / "采集"
    report = read(folder / REPORT)
    secs = sections(report) if report else {}
    s2 = find_sec(secs, "同题") if secs else ""
    bench_id = next(iter(ids_in((re.search(r"^\**对标[：:].*$", report, flags=re.M) or [""])[0])), "")

    # 2–3 transcript
    add((bench_dir / "逐字稿.md").exists(), 3, "对标逐字稿 对标/逐字稿.md",
        "没有视频文件时先问用户：要用户自己的文件，或经用户同意运行 save_media.py；然后运行 transcribe.py", ask=True)

    # 4 benchmark page and related videos
    rel = sorted(col.glob("推荐_*.json"))
    add(rel, 4, "推荐视频 采集/推荐_*.json", "python scripts/collect.py related <对标链接> --out D/采集")
    manifest = read(col / MANIFEST)
    read_ids = {line.split("\t")[0] for line in manifest.splitlines()[1:] if line.strip()}
    cache = read(work_dir(cfg) / "_cache" / "reads.jsonl")
    skipped = {line.split("\t")[0].strip() for line in read(col / SKIP).splitlines() if line.strip()}
    if bench_id:
        add(bench_id in read_ids, 4, f"对标读页和评论 {bench_id}", "python scripts/collect.py read <对标链接> --out D/采集")

    # 5 topic card
    card = re.search(r"一句话选题\s*[＝=]\s*([^；;\n]+)", s2)
    add(card and "__" not in card.group(1), 5, "选题卡（一句话选题、现实原型、依据）写在报告第 2 节",
        "按逐字稿写选题卡；有效台词少于 3 句时先截帧看画面；仍说不清就问用户")

    # 6 search: every keyword in the report was searched, 3–6 words, three groups
    done, empty = searched_keywords(col)
    words, groups = report_keywords(s2)
    add(3 <= len(words) <= 6, 6, f"搜索词 3–6 个（报告里现有 {len(words)} 个）", "按选题卡定词，写进报告第 2 节「搜索词：」一行")
    miss_g = [g for g in GROUPS if not any(g in x for x in groups)]
    add(not miss_g, 6, "搜索词三组都有：" + "、".join(GROUPS), "补上缺的组：" + "、".join(miss_g))
    not_run = [w for w in words if w not in done]
    add(words and not not_run, 6, "报告里的每个搜索词都已搜完",
        "python scripts/collect.py search " + " ".join(f'"{w}"' for w in not_run) + " --out D/采集" if not_run else "")
    if empty:
        add(False, 6, "空结果的搜索词：" + "、".join(empty), "按 docs/选题验证.md「搜索出现空结果」处理，情形记 D；过一段时间重搜", ask=True)

    # 7 read every candidate that passed the like prefilter
    floor = cfg["like_min"]
    for p in rel + sorted(col.glob("搜索_*.json")):
        need = {vid for vid, txt in parse_candidates(p) if vid != bench_id and passes(card_likes(txt) if txt else None, floor)}
        miss = sorted(v for v in need if v not in read_ids and v not in cache and v not in skipped)
        add(not miss, 7, f"候选视频已读页或写明跳过理由（{p.name}，{len(need)} 条过点赞预筛）",
            f"还差 {len(miss)} 条。可能同题的读页：python scripts/collect.py read <片子ID…> --out D/采集（全部要读时用 read -f D/采集/{p.name}）；"
            f"卡片文字明显不同题的，写进 D/采集/{SKIP}（片子ID、理由，一行一条）")
    if "\t失败\t" in manifest:
        add(False, 7, "采集汇总.tsv 里有「失败」", "问用户是否补采：重跑同一条 collect.py read", ask=True)

    # 9 comment clusters: benchmark pool and same-topic pool
    rows, _ = parse_rows(s2) if s2 else ([], 0)
    valid = [r for r in rows if not r["side"]]
    add((folder / "分簇_对标" / "评论分簇.md").exists(), 9, "对标评论分簇 分簇_对标/评论分簇.md",
        "comment_cluster.py sample → 逐条标注 → summarize")
    if valid:
        base = read(folder / "分簇_同题" / "评论底盘.md")
        miss = [r["title"] for r in valid if not (ids_in(r["url"]) & ids_in(base))]
        add((folder / "分簇_同题" / "评论分簇.md").exists() and not miss, 9,
            f"同题评论池含全部 {len(valid)} 条有效同题片，已标注并汇总",
            "把所有有效同题片的 评论.json 一起 sample --out D/分簇_同题 → 标注 → summarize" + (f"（缺：{'、'.join(miss)}）" if miss else ""))

    # 10 benchmark reconstruction and key frames
    rc = read(folder / "复原卡.md")
    add(rc and "__" not in rc, 10, "复原卡 复原卡.md 已填完（没有 __ 占位）", "按 docs/对标复原.md 填写")
    frames = list((bench_dir / "关键帧").glob("*.jpg"))
    add((frames and (bench_dir / "关键帧清单.md").exists()) or "未读" in rc, 10,
        f"关键帧（现有 {len(frames)} 张）或复原卡写明「未读」",
        "python scripts/frames.py D/对标 --at <转折秒数…>；只有音轨时在复原卡写「未读」")

    # 11 report and 12 result page
    add(report and re.search(r"情形[：:]\s*[A-D]", report) and "__" not in report, 11,
        "报告 选题验证报告.md 有「情形：」且没有 __ 占位", "按 templates/选题验证报告.md 写完")
    page = folder / PAGE
    add(page.exists() and report and page.stat().st_mtime >= (folder / REPORT).stat().st_mtime, 12,
        "结果页比报告新", "python scripts/board_data.py")
    return out


def main():
    utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="work/<topic>")
    a = ap.parse_args()
    folder = Path(a.folder).expanduser().resolve()
    if folder.is_file():
        folder = folder.parent
    if not folder.is_dir():
        print(f"找不到目录：{a.folder}")
        return 2
    res = check(folder)
    bad = [r for r in res if not r[0]]
    for ok, step, item, fix, ask in res:
        print(f"{'✅' if ok else '❌'} 第 {step} 步｜{item}" + ("" if ok else f"\n   → {fix}" + ("（问用户）" if ask else "")))
    if not bad:
        print("全部完成，可以交付。")
        return 0
    asks = sum(1 for r in bad if r[4])
    print(f"\n还缺 {len(bad)} 项。回到最早的缺项那一步，补齐后重跑本检查；不要先交付。"
          + (f"其中 {asks} 项要问用户，其余自己做完。" if asks else "全部自己做完，不用问用户。"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
