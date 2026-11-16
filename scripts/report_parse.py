"""Read the files of one topic folder (work/<topic>/) into plain data for the result page and the board.

Only reads files that the other scripts and templates/选题验证报告.md produce. Never computes a share that the
scripts did not print: every percentage here is copied from 评论分簇.md.
Standard library only.
"""
import json
import re
from pathlib import Path

REPORT = "选题验证报告.md"
CASE_TAG = {"A": "可复现的选题", "B": "有更高一级的同题片", "C": "同题证据薄弱", "D": "搜索未完成"}
CELLS = ["思辨·认同", "思辨·不认同", "感受·共情", "感受·反感"]


# ---------- small helpers ----------

def read(p):
    try:
        return Path(p).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def strip_md(s):
    s = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", s or "")
    s = re.sub(r"\*\*|`|<!--.*?-->", "", s)
    s = re.sub(r"[🟢🟡🔴]\s*", "", s)
    return s.strip()


def link(cell):
    """Cell → (text, url). Supports [t](u) and a bare URL."""
    m = re.search(r"\[(.+?)\]\((https?://[^)]+)\)", cell or "")
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = re.search(r"https?://\S+", cell or "")
    if m:
        return "", m.group(0)
    return strip_md(cell), ""


def pct(s):
    m = re.search(r"(-?[\d.]+)\s*%", s or "")
    return float(m.group(1)) if m else None


def count(s):
    """'1.5万' → 15000; '1,319' → 1319; '' → 0."""
    s = str(s or "").replace(",", "")
    m = re.search(r"([\d.]+)\s*万", s)
    if m:
        return int(round(float(m.group(1)) * 10000))
    m = re.search(r"\d+(?:\.\d+)?", s)
    return int(float(m.group(0))) if m else 0


def sections(text, level=2):
    """Split on '## ' (or '### '); returns {title: body} in order, plus '_head' for the text before the first one."""
    mark = "#" * level + " "
    out, cur, buf = {}, "_head", []
    for ln in text.splitlines():
        if ln.startswith(mark):
            out[cur] = "\n".join(buf)
            cur, buf = ln[len(mark):].strip(), []
        else:
            buf.append(ln)
    out[cur] = "\n".join(buf)
    return out


def find_sec(secs, *keys):
    for t, b in secs.items():
        if any(k in t for k in keys):
            return b
    return ""


def tables(block):
    """All markdown tables in a block: [(header, rows)]."""
    res, cur = [], []
    for ln in (block or "").splitlines() + [""]:
        s = ln.strip()
        if s.startswith("|"):
            if not re.match(r"^\|[-:| ]+\|$", s):
                cur.append([c.strip() for c in s.strip("|").split("|")])
        elif cur:
            res.append((cur[0], cur[1:]))
            cur = []
    return res


def col(header, *keys):
    for i, h in enumerate(header):
        if any(k in h for k in keys):
            return i
    return -1


def paragraphs(block):
    out, buf = [], []
    for ln in (block or "").splitlines() + [""]:
        s = ln.strip()
        if s and not s.startswith("|") and not s.startswith("<!--"):
            buf.append(s)
        elif buf:
            out.append(" ".join(buf))
            buf = []
    return out


# ---------- the report ----------

def parse_head(text):
    """`对标：[标题](url)｜[作者](url)｜赞 __／评 __／藏 __／转 __｜时长｜发布 __｜采集 __`"""
    b = {"title": "", "url": "", "author": "", "author_url": "", "like": "", "c": 0, "collect": "", "share": "",
         "dur": "", "date": ""}
    m = re.search(r"^\**对标[：:]\**\s*(.+)$", text, flags=re.M)
    if not m:
        return b
    parts = [p.strip() for p in m.group(1).split("｜")]
    b["title"], b["url"] = link(parts[0])
    for p in parts[1:]:
        if "douyin.com/user" in p or (not b["author"] and p.startswith("[")):
            b["author"], b["author_url"] = link(p)
        elif "赞" in p and "评" in p:
            for key, name in (("like", "赞"), ("c", "评"), ("collect", "藏"), ("share", "转")):
                mm = re.search(name + r"\s*([\d.,]+\s*万?)", p)
                if mm:
                    b[key] = count(mm.group(1)) if key == "c" else mm.group(1).replace(" ", "")
        elif re.search(r"[\d.]+\s*秒|^\d{1,2}:\d{2}$", p):
            b["dur"] = p
        elif p.startswith("发布"):
            mm = re.search(r"\d{4}-\d{2}-\d{2}", p)
            b["date"] = mm.group(0) if mm else strip_md(p[2:])
    return b


def parse_case(block):
    t = strip_md(block)
    m = re.search(r"情形[：:]\s*([A-D])([^。\n]*)", t)
    if not m:
        return {"L": "", "label": "未解析", "tag": "报告里没有「情形：」", "lead": "", "advice": "", "unknown": ""}
    label = m.group(2).strip("，,；; ")
    adv = re.search(r"建议[：:]\s*([^\n]+?)(?:$|\n)", t)
    advice = adv.group(1).split("最大的未知项")[0].strip() if adv else ""
    unk = re.search(r"最大的未知项[：:]\s*([^\n]+)", t)
    lead = ""
    for p in paragraphs(block):
        s = strip_md(p)
        if re.search(r"情形[：:]|^建议[：:]|^最大的未知项|^证据边界", s):
            continue
        lead = s
        break
    sents = [x for x in re.split(r"(?<=[。！？])", lead) if x.strip()]
    return {"L": m.group(1), "label": label, "tag": CASE_TAG[m.group(1)],
            "lead": sents[0].strip() if sents else "", "rest": "".join(sents[1:2]).strip(),
            "advice": advice, "unknown": unk.group(1).strip() if unk else ""}


def parse_rows(block):
    """The same-topic table: needs a 作者 column and a ÷ column."""
    for h, rows in tables(block):
        ci, ai = col(h, "÷"), col(h, "作者")
        if ci < 0 or ai < 0:
            continue
        ri, di, ti, wi = col(h, "赞／评", "赞/评", "读数"), col(h, "发布"), col(h, "时长"), col(h, "理由")
        out, bench_c = [], 0
        for r in rows:
            r = r + [""] * (len(h) - len(r))
            t, u = link(r[0])
            au, auu = link(r[ai])
            au = re.sub(r"[（(].*?[）)]", "", au).strip()
            m = re.search(r"([\d,]+)\s*÷\s*([\d,]+)\s*[＝=]\s*([\d.]+)", r[ci])
            c = int(m.group(1).replace(",", "")) if m else 0
            if m:
                bench_c = int(m.group(2).replace(",", ""))
            why = strip_md(r[wi]) if wi >= 0 else ""
            side = bool(re.search(r"旁证|不计有效", r[0] + why))
            out.append({"title": re.sub(r"[（(]旁证[^）)]*[）)]", "", t).strip(), "url": u, "author": au.lstrip("@"),
                        "author_url": auu, "c": c, "x": float(m.group(3)) if m else 0.0,
                        "like": (r[ri].split("／")[0].split("/")[0].strip() if ri >= 0 else ""),
                        "date": (re.search(r"\d{4}-\d{2}-\d{2}", r[di]) or [""])[0] if di >= 0 else "",
                        "dur": re.sub(r"[（(].*?[）)]", "", r[ti]).strip() if ti >= 0 else "",
                        "why": why, "side": side})
        return out, bench_c
    return [], 0


def parse_mech(block):
    """Section 3: the 对标 line and the 同题 line."""
    def one(key):
        m = re.search(r"\*\*" + key + r"[^*]*\*\*[：:]?(.+)", block or "")
        if not m:
            return {}
        t = strip_md(m.group(1))
        g = lambda k: (re.search(k + r"[＝=]\s*([^；;。，]+)", t) or [None, ""])[1].strip()
        return {"core": g("核心机制"), "also": g("同时激活"), "combo": g("组合"), "text": t}
    m = re.search(r"\*\*还没激活[^*]*\*\*[：:]?\s*(.+)", block or "")
    return {"bench": one("对标"), "same": one("同题片"), "open": strip_md(m.group(1)) if m else ""}


def parse_structure(block):
    """Section 4: the framework line 'A（手法）→ B（手法）→ …' and the next paragraph."""
    paras = [p for p in paragraphs(block) if not p.startswith("复原卡")]
    steps = []
    if paras and "→" in paras[0]:
        for s in paras[0].split("→"):
            s = strip_md(s).strip("。 ")
            m = re.match(r"^(.*?)[（(]([^）)]*)[）)]", s)  # text after the （手法） is a note, drop it
            steps.append({"say": (m.group(1) if m else s).strip("“”\"「」 "), "how": m.group(2) if m else ""})
        paras = paras[1:]
    return {"steps": steps, "note": strip_md(paras[0]) if paras else ""}


# ---------- script outputs next to the report ----------

def parse_clusters(md_path):
    """评论分簇.md from comment_cluster.py summarize. All numbers copied as printed."""
    t = read(md_path)
    if not t:
        return None
    out = {"file": str(md_path), "n": 0, "likes": 0, "page_total": 0, "rate": "", "items": [], "cells": [], "actions": [],
           "core": "", "also": ""}
    m = re.search(r"样本\s*\*\*(\d+)\s*条", t)
    out["n"] = int(m.group(1)) if m else 0
    m = re.search(r"样本总赞\s*\*\*(\d+)", t)
    out["likes"] = int(m.group(1)) if m else 0
    m = re.search(r"页面评论总数\s*(\d+)", t)
    out["page_total"] = int(m.group(1)) if m else 0
    m = re.search(r"采样率\s*([\d.]+%)", t)
    out["rate"] = m.group(1) if m else ""
    for h, rows in tables(t):
        if h and h[0] == "簇" and col(h, "占赞") >= 0:
            ni, pi, ai, gi = col(h, "条数"), col(h, "占赞"), col(h, "主要动作"), col(h, "格")
            for r in rows:
                if len(r) < len(h):
                    continue
                out["items"].append({"name": r[0], "n": r[ni], "pct": pct(r[pi]) or 0.0,
                                     "action": r[ai] if ai >= 0 else "", "cell": r[gi] if gi >= 0 else "",
                                     "big": "★" in r[-1], "quote": "", "qlike": 0})
        elif h and h[0] == "格" and col(h, "按赞") >= 0:
            out["cells"] = [{"cell": r[0], "like": pct(r[1]) or 0.0, "n": pct(r[2]) or 0.0} for r in rows if len(r) >= 3]
        elif h and h[0] == "码" and col(h, "动作") >= 0:
            out["actions"] = [{"code": r[0], "name": r[1], "n_pct": pct(r[3]) or 0.0, "like_pct": pct(r[5]) or 0.0}
                              for r in rows if len(r) >= 6]
    m = re.search(r"核心机制[^：:]*[：:]\s*\**([^*；;\n]+)", t)
    out["core"] = m.group(1).strip() if m else ""
    m = re.search(r"同时激活[^：:]*[：:]\s*([^\n]+)", t)
    out["also"] = strip_md(m.group(1)).rstrip("。") if m else ""
    # one representative quote per cluster: first quote line under its bold name, first 14 characters
    for c in out["items"]:
        m = re.search(r"^\*\*" + re.escape(c["name"]) + r"\*\*.*?\n((?:- .+\n?)+)", t, flags=re.M)
        if not m:
            continue
        for ln in m.group(1).splitlines():
            mm = re.match(r"^- (\d+) 赞[｜|:：](?:#\d+[｜|])?(.+)$", ln.strip())
            if mm and int(mm.group(1)) > 0:
                q = mm.group(2).strip()
                c["quote"], c["qlike"] = (q if len(q) <= 14 else q[:14] + "……"), int(mm.group(1))
                break
    return out


def parse_frames(folder):
    """关键帧清单.md from frames.py: [(seconds, kind, relative file)] relative to the topic folder."""
    for p in (folder / "对标" / "关键帧清单.md", folder / "关键帧清单.md"):
        t = read(p)
        if not t:
            continue
        base = p.parent.relative_to(folder)
        out = []
        for h, rows in tables(t):
            if col(h, "类型") < 0:
                continue
            for r in rows:
                if len(r) >= 3 and (folder / base / r[2]).exists():
                    out.append({"t": float(r[0] or 0), "kind": r[1], "file": (base / r[2]).as_posix()})
        return out
    return []


def parse_topic(folder):
    """Everything about one work/<topic>/ folder. Returns None if it has no report."""
    folder = Path(folder)
    rp = folder / REPORT
    text = read(rp)
    if not text:
        return None
    secs = sections(text)
    m = re.search(r"^# (?:选题验证[：:]\s*)?(.+)$", text, flags=re.M)
    title = strip_md(m.group(1)) if m else folder.name
    s1, s2, s3, s4 = (find_sec(secs, "1 结论", "结论"), find_sec(secs, "2 同题", "同题片"),
                      find_sec(secs, "3 评论", "评论机制"), find_sec(secs, "4 对标", "对标结构"))
    bench = parse_head(secs.get("_head", ""))
    rows, bench_c = parse_rows(s2)
    bench["c"] = bench["c"] or bench_c
    valid = [r for r in rows if not r["side"]]
    xs = [r["x"] for r in valid]
    m = re.search(r"搜索词[：:]\s*([^\n]+)", s2)
    search = strip_md(m.group(1)).split("。")[0] if m else ""
    m = re.search(r"一句话选题\s*[＝=]\s*([^；;\n]+)", s2)
    topic_card = strip_md(m.group(1)).strip() if m else ""
    meta = {}
    try:
        meta = json.loads(read(folder / "对标" / "保存清单.json") or "{}")
    except json.JSONDecodeError:
        pass
    return {
        "name": folder.name, "title": title, "report": REPORT,
        "case": parse_case(s1), "bench": bench, "rows": rows,
        "valid": len(valid), "maxX": max(xs) if xs else 0.0, "over": len([x for x in xs if x >= 1]),
        "cmin": min((r["c"] for r in valid), default=0), "cmax": max((r["c"] for r in valid), default=0),
        "search": search, "topic_card": topic_card, "mech": parse_mech(s3), "structure": parse_structure(s4),
        "clusters": {"bench": parse_clusters(folder / "分簇_对标" / "评论分簇.md"),
                     "same": parse_clusters(folder / "分簇_同题" / "评论分簇.md")},
        "frames": parse_frames(folder),
        "has_transcript": (folder / "对标" / "逐字稿.md").exists(),
        "has_card": (folder / "复原卡.md").exists(),
        "saved_deleted": bool(meta.get("deleted_at")),
        "mtime": rp.stat().st_mtime,
    }
