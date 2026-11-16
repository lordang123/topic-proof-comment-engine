#!/usr/bin/env python3
"""Douyin page collection for topic verification. Every page visit goes through ego_run.py (one page at a time).

  related <video>  --out DIR [--pages 2]
      Read the benchmark page and its "related videos" panel. Writes DIR/推荐_<time>.json.
  search  <kw>...  --out DIR
      Search from the home page, first screen of the "视频" tab per keyword (at most 6). Writes DIR/搜索_<time>.json.
  read    <video>... --out DIR   |   read -f <推荐_*.json | 搜索_*.json | ids.txt> --out DIR
      Open each candidate once: counts, publish date, author link; sample comments when count > 500 and year qualifies.
      Writes DIR/<id>/评论.json, DIR/<id>/评论_TOP.md, DIR/读数_<time>.json, DIR/采集汇总.tsv.
      Options: --force (ignore cache)  --read-only (no comments)  --like-min N (prefilter for -f; default from config)

<video> is a numeric id or https://www.douyin.com/video/<id>.
Exit codes for read: 0 ok; 2 some comment grabs failed (other videos still ran); 3 stopped (possible restriction);
                     75 another ego task held the lock too long; 76 you took over the browser space.
"""
import argparse
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tp_common import JS_DIR, load_config, num, utf8_stdio, video_id, video_url, work_dir, write_json, read_text  # noqa: E402
import ego_run  # noqa: E402

MANIFEST = "采集汇总.tsv"
MANIFEST_HEAD = "片子ID\t状态\t条数\t原因\n"


def cache_path(cfg):
    p = work_dir(cfg) / "_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def stamp():
    return datetime.now().strftime("%H%M%S")


def parse_marked(text, tag):
    """Return parsed JSON objects from lines starting with tag."""
    out = []
    for line in text.splitlines():
        i = line.find(tag + " ")
        if i >= 0:
            try:
                out.append(json.loads(line[i + len(tag) + 1:]))
            except json.JSONDecodeError:
                pass
    return out


def run_script(name, repl, seconds, out_dir, label):
    js = (JS_DIR / name).read_text(encoding="utf-8")
    for k, v in repl.items():
        js = js.replace(k, v)
    log = Path(out_dir) / f"ego日志_{label}_{stamp()}.txt"
    rc = ego_run.run_js(js, seconds, str(log))
    return rc, read_text(log) if log.exists() else ""


# ---------------- related ----------------
def cmd_related(a, cfg):
    vid = video_id(a.video)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rc, text = run_script("related.js", {"__VID__": vid, "__MAXN__": str(a.pages)}, 120 * a.pages + 120, out, "推荐")
    res = parse_marked(text, "@@RESULT@@")
    if not res:
        print(f"没有拿到结果（ego 退出码 {rc}）。看日志：{out}")
        return rc or 3
    d = res[-1]
    p = out / f"推荐_{stamp()}.json"
    write_json(p, d)
    v0 = (d.get("visits") or [{}])[0]
    print(f"对标 {video_url(vid)}｜赞 {v0.get('digg')}｜评 {v0.get('comment')}｜藏 {v0.get('collect')}｜转 {v0.get('share')}｜{v0.get('pub')}")
    print("| # | 推荐视频 | 卡片文字 |\n|---|---|---|")
    for i, x in enumerate(v0.get("rel") or [], 1):
        print(f"| {i} | {video_url(x['id'])} | {x['txt'][:80].replace('|', '｜')} |")
    print(f"\n停因：{d.get('stop')}\n结果文件：{p}")
    return 0 if "无异常" in str(d.get("stop")) else 3


# ---------------- search ----------------
def cmd_search(a, cfg):
    kws = a.keywords[: cfg["max_keywords"]]
    if len(a.keywords) > len(kws):
        print(f"搜索词超过 {cfg['max_keywords']} 个，只用前 {len(kws)} 个", file=sys.stderr)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rc, text = run_script("search.js", {"__KWS__": json.dumps(kws, ensure_ascii=False)}, 90 * len(kws) + 120, out, "搜索")
    res = parse_marked(text, "@@RESULT@@")
    if not res:
        print(f"没有拿到结果（ego 退出码 {rc}）。看日志：{out}")
        return rc or 3
    d = res[-1]
    p = out / f"搜索_{stamp()}.json"
    write_json(p, d)
    ss = d.get("searches", [])
    rec = {"at": d.get("started"), "n": len(ss), "gaps_s": [s.get("gap_after_s") for s in ss if s.get("gap_after_s")],
           "empty": [s.get("idx") for s in ss if not s.get("ready")], "stop": d.get("stop")}
    with open(cache_path(cfg) / "search_log.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    for s in ss:
        print(f"## {s['idx']}. {s['kw']}｜卡片 {s.get('nAnchor', 0)} 张" + ("｜空结果" if not s.get("ready") else ""))
        for c in (s.get("cards") or [])[:20]:
            print(f"- {c['link']}  {c['txt'][:90]}")
        if s.get("empty_body"):
            print(f"  页面文字前 300 字：{s['empty_body']}")
    print(f"\n停因：{d.get('stop')}\n结果文件：{p}")
    return 0 if "无异常" in str(d.get("stop")) else 3


# ---------------- read ----------------
def load_cache(cfg):
    d = {}
    p = cache_path(cfg) / "reads.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                d[r["id"]] = r
            except (json.JSONDecodeError, KeyError):
                pass
    return d


def cached_skip(r, cfg, now=None):
    """Reason not to read again, or None."""
    now = now or time.time()
    age_d = (now - r.get("fetched_ts", 0)) / 86400
    c = r.get("comment_n")
    if c is None:
        return None
    if c > cfg["comment_min"] and r.get("comments_path") and Path(r["comments_path"]).exists():
        return f"已有评论文件（{c} 评）"
    if c <= cfg["comment_min"] and age_d <= (7 if c > cfg["comment_min"] * 0.6 else 30):
        return f"缓存 {age_d:.0f} 天前 {c} 评"
    if r.get("year_ok") is False and age_d <= 30:
        return f"缓存：发布 {r.get('pub_year')} 年，年份不合格"
    return None


def card_likes(txt):
    for part in reversed([p.strip() for p in txt.split("|")]):
        n = num(part)
        if n is not None and not re.match(r"^\d{1,2}:\d{2}$", part):
            return n
    return None


def parse_candidates(path):
    """(id, card text) from a related/search result JSON or a text file of ids."""
    t = read_text(path)
    try:
        d = json.loads(t)
        if "visits" in d:
            return [(x["id"], x.get("txt", "")) for x in (d["visits"][0].get("rel") or [])]
        if "searches" in d:
            return [(c["id"], c.get("txt", "")) for s in d["searches"] for c in (s.get("cards") or [])]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        pass
    return [(m.group(1), "") for m in re.finditer(r"(\d{15,})", t)]


def pick_ids(a, cfg):
    cache = {} if a.force else load_cache(cfg)
    if a.file:
        cands, floor = parse_candidates(a.file), (a.like_min if a.like_min is not None else cfg["like_min"])
    else:
        cands, floor = [(video_id(v), "") for v in a.videos], None
    keep, seen = [], set()
    for vid, txt in cands:
        if vid in seen:
            continue
        seen.add(vid)
        why = cached_skip(cache[vid], cfg) if vid in cache else None
        likes = card_likes(txt) if txt else None
        if not why and floor is not None and likes is not None and likes < floor:
            why = f"卡片点赞 {likes} < {floor}"
        if why:
            print(f"跳过 {vid}：{why}", file=sys.stderr)
        else:
            keep.append(vid)
    print(f"[选取] 访问 {len(keep)} 条，跳过 {len(seen) - len(keep)} 条", file=sys.stderr)
    return keep


def write_manifest(outdir, rows):
    path = Path(outdir) / MANIFEST
    old = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            f = line.split("\t")
            if f and f[0]:
                old[f[0]] = (f + ["", "", ""])[:4]
    for r in rows:
        old[r[0]] = [str(x).replace("\t", " ").replace("\n", " ") for x in r]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(MANIFEST_HEAD)
        for f in old.values():
            fh.write("\t".join(f) + "\n")
    return path


def finish_batch(text, outdir, cfg):
    """Save visits from one ego run. Returns (exit_code, rows, end)."""
    visits, ends = parse_marked(text, "@@VISIT@@"), parse_marked(text, "@@END@@")
    end = ends[-1] if ends else None
    fetched = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    rows, mrows = [], []
    cache_file = cache_path(cfg) / "reads.jsonl"
    for v in visits:
        cm = v.pop("comments", None)
        cpath = None
        if v.get("stop_here"):
            mrows.append((v["id"], "失败", 0, "读不到评论数：疑似受限，或视频已删除"))
        elif cm is None:
            mrows.append((v["id"], "跳过", 0, v.get("comments_skip") or "未抓评论"))
        elif not cm:
            mrows.append((v["id"], "失败", 0, (v.get("comments_err") or "抓到 0 条") + f"（页面评论数 {v.get('comment_n')}）"))
        else:
            mrows.append((v["id"], "成功", len(cm), ""))
            d = Path(outdir) / v["id"]
            d.mkdir(parents=True, exist_ok=True)
            cpath = d / "评论.json"
            write_json(cpath, cm)
            main = [c for c in cm if not c.get("isAuthor")]
            top = sorted(main, key=lambda c: c.get("digg", 0), reverse=True)[:50]
            L = [f"# 评论 TOP50（按赞）｜抓取 {fetched}｜抽样 {len(cm)} 条，去掉作者后 {len(main)} 条｜↳＝楼中回复", "",
                 "| # | 赞 | 回复 | 评论 | 时间 | 作者赞过 |", "|---|---|---|---|---|---|"]
            for i, c in enumerate(top, 1):
                txt = str(c.get("text", "")).replace("|", "｜").replace("\n", " ")
                L.append(f"| {i} | {c.get('digg', 0)} | {c.get('replies', 0)} | {'↳ ' if c.get('isReply') else ''}{txt} | {c.get('when', '')} | {'♥' if c.get('authorLiked') else ''} |")
            (d / "评论_TOP.md").write_text("\n".join(L) + "\n", encoding="utf-8")
        v["comments_count"] = len(cm) if cm is not None else None
        v["comments_path"] = str(cpath) if cpath else None
        v["fetched"] = fetched
        rows.append(v)
        if v.get("comment_n") is not None:
            rec = {"id": v["id"], "fetched_ts": time.time(), "fetched": fetched, "comment_n": v.get("comment_n"),
                   "digg_n": v.get("digg_n"), "pub": v.get("pub"), "pub_year": v.get("pub_year"), "year_ok": v.get("year_ok"),
                   "author_name": v.get("author_name"), "author_sec": v.get("author_sec"), "comments_path": v["comments_path"]}
            with open(cache_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=True) + "\n")
    rem = (end or {}).get("remaining") or []
    mrows += [(i, "未访问", 0, "本批在前面停下：" + str((end or {}).get("stop", ""))[:60]) for i in rem]
    write_manifest(outdir, mrows)
    stopped = end is None or "疑似受限" in str(end.get("stop")) or str(end.get("stop", "")).startswith(("错误", "打开页面出错"))
    nfail = sum(1 for r in mrows if r[1] == "失败")
    return (3 if stopped else (2 if nfail else 0)), rows, end


def print_rows(rows):
    print("| # | 视频 | 赞 | 评 | 藏 | 转 | 发布 | 作者 | 评论 | 备注 |\n|---|---|---|---|---|---|---|---|---|---|")
    for k, v in enumerate(rows, 1):
        au = f"[{v.get('author_name') or '作者'}](https://www.douyin.com/user/{v['author_sec']})" if v.get("author_sec") else "链接待补"
        cmt = f"{v['comments_count']} 条（加载 {v.get('comments_loaded')}）" if v.get("comments_count") is not None else "—"
        note = v.get("comments_skip") or v.get("comments_err") or ("停：读不到评论数" if v.get("stop_here") else "")
        pub = (v.get("pub") or "").replace("发布时间：", "").strip()
        print(f"| {k} | {video_url(v['id'])} | {v.get('digg')} | {v.get('comment')} | {v.get('collect')} | {v.get('share')} | {pub} | {au} | {cmt} | {note} |")


def cmd_read(a, cfg):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ids = pick_ids(a, cfg)
    if not ids:
        print("没有需要访问的视频（都被缓存或预筛跳过）")
        return 0
    conf = {"commentMin": cfg["comment_min"], "minYear": datetime.now().year - cfg["years_back"], "maxTop": cfg["max_top"],
            "hotK": cfg["hot_k"], "posM": cfg["pos_m"], "replyTop": cfg["reply_top"], "readOnly": bool(a.read_only)}
    chunk, rc, all_rows = cfg["chunk"], 0, []
    while ids:
        batch, ids = ids[:chunk], ids[chunk:]
        repl = {"__IDS__": json.dumps(batch), "__CFG__": json.dumps(conf)}
        js = (JS_DIR / "page_read.js").read_text(encoding="utf-8")
        for k, v in repl.items():
            js = js.replace(k, v)
        log = out / f"ego日志_读页_{stamp()}.txt"
        erc = ego_run.run_js(js, len(batch) * 75 + 240, str(log))
        if erc in (75, 76, 127):
            write_manifest(out, [(i, "未访问", 0, f"ego 退出码 {erc}") for i in batch + ids])
            print(f"ego 退出码 {erc}，本批未跑。未访问：{' '.join(batch + ids)}")
            rc = erc
            break
        r, rows, end = finish_batch(read_text(log) if log.exists() else "", out, cfg)
        all_rows += rows
        print(f"停因：{(end or {}).get('stop', '没有结束标记（脚本超时或崩溃）')}", file=sys.stderr)
        if r == 2:
            rc = 2
        elif r != 0:
            rc = r
            if ids:
                write_manifest(out, [(i, "未访问", 0, "前一批停下：疑似受限或脚本中断") for i in ids])
                print(f"后续未跑：{' '.join(ids)}")
            break
        if ids:
            time.sleep(random.uniform(8, 15))
    print_rows(all_rows)
    p = out / f"读数_{stamp()}.json"
    write_json(p, {"visits": all_rows})
    print(f"\n读数文件：{p}\n汇总清单：{out / MANIFEST}")
    nfail = sum(1 for line in (out / MANIFEST).read_text(encoding="utf-8").splitlines()[1:] if "\t失败\t" in line)
    if nfail:
        print(f"评论抓取失败 {nfail} 条（不是 0 条评论，要补采；见汇总清单）")
    return rc


def main():
    utf8_stdio()
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("related")
    s.add_argument("video")
    s.add_argument("--out", required=True)
    s.add_argument("--pages", type=int, default=2)
    s.set_defaults(f=cmd_related)
    s = sp.add_parser("search")
    s.add_argument("keywords", nargs="+")
    s.add_argument("--out", required=True)
    s.set_defaults(f=cmd_search)
    s = sp.add_parser("read")
    s.add_argument("videos", nargs="*")
    s.add_argument("-f", "--file")
    s.add_argument("--out", required=True)
    s.add_argument("--force", action="store_true")
    s.add_argument("--read-only", action="store_true")
    s.add_argument("--like-min", type=int)
    s.set_defaults(f=cmd_read)
    a = ap.parse_args()
    if a.cmd == "read" and not (a.videos or a.file):
        ap.error("read 要给视频，或用 -f 给候选文件")
    return a.f(a, cfg)


if __name__ == "__main__":
    sys.exit(main())
