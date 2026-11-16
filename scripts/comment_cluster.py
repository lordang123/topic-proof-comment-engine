#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Comment clustering. The script does only deterministic work (sample, sum, check).
The clusters are defined by the model for each comment section, per docs/评论机制.md section 4.

  1) sample:    python scripts/comment_cluster.py sample <评论.json>... [--out DIR] [--publish "YYYY-MM-DD HH:MM"]
                    [--fetched "YYYY-MM-DD HH:MM"] [--page-total N] [--note "one line"] [--force]
     Drops the author's own comments, numbers the rest, writes DIR/评论样本.tsv (for labeling) and DIR/评论底盘.md.
     Several json files = one same-topic pool; the 来源 column records each file's folder. Default DIR = folder of the first json.
  2) The model reads 评论样本.tsv and writes DIR/评论标签.json (format below).
  3) summarize: python scripts/comment_cluster.py summarize DIR [--top 20] [--force]
     Counts, like sums, shares, main action, B0–B8 distribution; four-grid shares once clusters carry 「格」.
     Writes DIR/评论分簇.md. Incomplete or invalid labels stop with an error and no result.
  recheck:      python scripts/comment_cluster.py recheck DIR <other_labels.json>
     Agreement between two label files on shared ids (cluster and B code separately). Below 80% exits 2.

评论标签.json:
{
  "簇": [
    {"名": "三年只发一盒月饼", "定义": "一句话", "含": "…", "不含": "…",
     "格": "感受·共情", "触发点": "S19「一盒月饼」"}        <- 格 and 触发点 are added in step 4
  ],
  "标签": [[1, "三年只发一盒月饼", "B2"], [2, "其他", "B7"]]   <- or {"1": {"簇": "...", "B": "B2"}}
}
Reserved cluster names: 「其他」 (small clusters merged) and 「无法判定」 (emoji only, @ only, unreadable). No definition needed.
格 is one of: 思辨·认同 / 思辨·不认同 / 感受·共情 / 感受·反感 / 片外.

Each comment goes into exactly one cluster, so cluster shares add up. Like share = cluster like sum / sample like sum (author comments excluded).
The input never contains commenter nicknames or IP regions; this script does not read them either.
"""
import argparse, csv, json, os, random, sys
from collections import Counter, defaultdict
from datetime import datetime

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SAMPLE, BASE, LABEL, REPORT = '评论样本.tsv', '评论底盘.md', '评论标签.json', '评论分簇.md'
B_CODES = {'B0', 'B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8'}
B_NAME = {'B1': '表态', 'B2': '讲自己', 'B3': '给信息', 'B4': '提问', 'B5': '招呼人',
          'B6': '对创作者说', 'B7': '抒发', 'B8': '玩', 'B0': '其他'}
GRIDS = ['思辨·认同', '思辨·不认同', '感受·共情', '感受·反感']
RESERVED = {'其他', '无法判定'}
RECHECK_N, RECHECK_SEED = 10, 20261113


def die(msg):
    sys.exit('错误：' + msg)


def to_int(v):
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v or '').strip()
    if not s:
        return 0
    if s.endswith('万'):
        return int(round(float(s[:-1]) * 10000))
    try:
        return int(float(s))
    except ValueError:
        die(f'赞数无法解析：{s!r}')


def load_comments(p):
    d = json.load(open(p, encoding='utf-8-sig'))
    if isinstance(d, dict):
        d = d.get('comments') or d.get('data') or []
    if not isinstance(d, list):
        die(f'{p} 不是评论数组')
    out = []
    for c in d:
        if 'text' not in c:
            die(f'{p} 缺字段 text（实际字段：{sorted(c.keys())}）')
        if not any(k in c for k in ('digg', 'digg_count', 'like_count')):
            die(f'{p} 缺赞数字段，需 digg／digg_count／like_count 之一（实际字段：{sorted(c.keys())}）')
        if c.get('isAuthor'):
            continue
        text = ' '.join(str(c.get('text') or '').split())
        if not text:
            continue
        out.append({
            'text': text,
            'digg': to_int(c.get('digg', c.get('digg_count', c.get('like_count')))),
            'replies': to_int(c.get('replies', c.get('reply_count', 0))),
            'isReply': bool(c.get('isReply')),
            'stratum': str(c.get('stratum') or ''),
        })
    return out


# ---------------- 1 样本 ----------------
def cmd_sample(a):
    srcs = [os.path.abspath(p) for p in a.json]
    out_dir = os.path.abspath(a.out or os.path.dirname(srcs[0]))
    os.makedirs(out_dir, exist_ok=True)
    tsv, base = os.path.join(out_dir, SAMPLE), os.path.join(out_dir, BASE)
    if os.path.exists(tsv) and not a.force:
        die(f'已存在 {tsv}。评论没换就直接复用；确要重做加 --force（旧的 {LABEL} 会对不上，要重标）。')

    rows, per_src = [], []
    for p in srcs:
        cs = load_comments(p)
        name = os.path.basename(os.path.dirname(p)) or os.path.basename(p)
        per_src.append((name, len(cs), sum(c['digg'] for c in cs)))
        for c in cs:
            c['src'] = name
            rows.append(c)
    if not rows:
        die('去掉作者评论后没有评论')
    n, tot = len(rows), sum(c['digg'] for c in rows)
    if tot == 0:
        die('样本总赞为 0，检查赞数字段')

    with open(tsv, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, delimiter='\t', lineterminator='\n')
        w.writerow(['序号', '来源', '赞', '回复数', '楼中回复', '抽样层', '文本'])
        for i, c in enumerate(rows, 1):
            w.writerow([i, c['src'], c['digg'], c['replies'], '↳' if c['isReply'] else '', c['stratum'],
                        c['text'].replace('\t', ' ')])

    fetched = a.fetched or datetime.fromtimestamp(os.path.getmtime(srcs[0])).strftime('%Y-%m-%d %H:%M')
    gap = ''
    if a.publish:
        h = (datetime.strptime(fetched, '%Y-%m-%d %H:%M') - datetime.strptime(a.publish, '%Y-%m-%d %H:%M')).total_seconds() / 3600
        gap = f'，距发布 **{h:.1f} h**（{h/24:.1f} 天，{"未饱和" if h < 24*14 else "已饱和"}）'
    samp = f'，页面评论总数 {a.page_total}、**采样率 {n/a.page_total:.1%}**' if a.page_total else ''
    srt = sorted(rows, key=lambda c: c['digg'], reverse=True)
    z = sum(1 for c in rows if c['digg'] == 0)
    rec = sorted(random.Random(RECHECK_SEED).sample(range(1, n + 1), min(RECHECK_N, n)))

    L = []
    if a.note:
        L += [f'> {a.note}', '']
    L.append('## 实测底盘（脚本产出，可核）\n')
    L.append(f'样本 **{n} 条**（已去掉作者评论），抓取 **{fetched}**{gap}{samp}。'
             f'样本总赞 **{tot}**，总回复 **{sum(c["replies"] for c in rows)}**，楼中回复 {sum(c["isReply"] for c in rows)} 条。\n')
    L.append(f'0 赞评论 {z} 条（{z/n:.0%}）；TOP10 占赞 {sum(c["digg"] for c in srt[:10])/tot:.1%}，'
             f'TOP1 占赞 {srt[0]["digg"]/tot:.1%}。\n')
    if len(per_src) > 1:
        L.append('| 来源 | 条数 | 赞和 |\n|---|---|---|')
        L += [f'| {s} | {k} | {v} |' for s, k, v in per_src]
        L.append('')
    L.append(f'来源文件：' + '；'.join(f'`{p}`' for p in srcs) + '\n')
    L.append(f'复核抽样序号（固定种子 {RECHECK_SEED}）：{", ".join(map(str, rec))}\n')
    open(base, 'w', encoding='utf-8', newline='\n').write('\n'.join(L))

    print(f'✅ 样本 {n} 条 → {tsv}')
    print(f'   底盘 → {base}')
    print(f'下一步：按 docs/评论机制.md 第四节第 2 步定簇、逐条标注，写 {os.path.join(out_dir, LABEL)}；'
          f'再运行 python scripts/comment_cluster.py summarize {out_dir}')


# ---------------- 2 汇总 ----------------
def read_sample(d):
    p = os.path.join(d, SAMPLE)
    if not os.path.exists(p):
        die(f'找不到 {p}，先运行 sample')
    with open(p, encoding='utf-8', newline='') as f:
        r = csv.DictReader(f, delimiter='\t')
        return {int(x['序号']): {'digg': int(x['赞']), 'text': x['文本'], 'reply': x['楼中回复'] == '↳', 'src': x['来源']} for x in r}


def read_labels(p):
    if not os.path.exists(p):
        die(f'找不到 {p}')
    d = json.load(open(p, encoding='utf-8-sig'))
    defs = d.get('簇') or []
    if isinstance(defs, dict):
        defs = [dict(v, 名=k) for k, v in defs.items()]
    raw = d.get('标签') or []
    lab = {}
    items = raw.items() if isinstance(raw, dict) else ((x[0], x) for x in raw)
    for k, v in items:
        if isinstance(v, dict):
            lab[int(k)] = (str(v.get('簇', '')).strip(), str(v.get('B', '')).strip().upper())
        else:
            if len(v) < 3:
                die(f'标签行格式错：{v}，应为 [序号, 簇名, B码]')
            lab[int(v[0])] = (str(v[1]).strip(), str(v[2]).strip().upper())
    return defs, lab


def validate(sample, defs, lab):
    errs = []
    names = [str(x.get('名', '')).strip() for x in defs]
    for nm in names:
        if not nm:
            errs.append('「簇」里有一项没写「名」')
        elif nm in RESERVED:
            errs.append(f'「{nm}」是保留名，不用在「簇」里定义')
    dup = [k for k, v in Counter(names).items() if v > 1]
    if dup:
        errs.append(f'簇名重复：{dup}')
    for x in defs:
        g = x.get('格')
        if g and g not in GRIDS + ['片外']:
            errs.append(f'簇「{x.get("名")}」的格「{g}」不在 {GRIDS + ["片外"]} 里')
    known = set(names) | RESERVED
    miss = sorted(set(sample) - set(lab))
    if miss:
        errs.append(f'{len(miss)} 条没标：序号 {miss[:20]}{" …" if len(miss) > 20 else ""}')
    extra = sorted(set(lab) - set(sample))
    if extra:
        errs.append(f'标签里有样本没有的序号：{extra[:20]}')
    bad_c = sorted({c for c, _ in lab.values() if c not in known})
    if bad_c:
        errs.append(f'簇名没在「簇」里定义：{bad_c}')
    bad_b = sorted({b for _, b in lab.values() if b not in B_CODES})
    if bad_b:
        errs.append(f'B 码不合法：{bad_b}（只取 B0–B8）')
    if errs:
        die('标签不合法，没有出结果：\n- ' + '\n- '.join(errs))


def cmd_sum(a):
    d = os.path.abspath(a.dir)
    out = os.path.join(d, REPORT)
    if os.path.exists(out) and not a.force:
        die(f'已存在 {out}。标签改过就加 --force 重算。')
    sample = read_sample(d)
    defs, lab = read_labels(os.path.join(d, LABEL))
    validate(sample, defs, lab)

    n, tot = len(sample), sum(c['digg'] for c in sample.values())
    by = defaultdict(list)
    for i, (c, _) in lab.items():
        by[c].append(i)
    top1 = max(sample, key=lambda i: sample[i]['digg'])
    dom = sample[top1]['digg'] / tot >= 0.30
    tot_ex = tot - sample[top1]['digg']

    def stat(ids):
        s = sum(sample[i]['digg'] for i in ids)
        bs = Counter()
        for i in ids:
            bs[lab[i][1]] += sample[i]['digg'] or 0.001
        main_b = bs.most_common(1)[0][0] if bs else ''
        s_ex = s - (sample[top1]['digg'] if top1 in ids else 0)
        return len(ids), s, main_b, s_ex

    real = [x['名'] for x in defs]
    stats = {nm: stat(by.get(nm, [])) for nm in real + ['其他', '无法判定']}
    order = sorted(real, key=lambda nm: stats[nm][1], reverse=True)
    top5_cnt = set(sorted(real, key=lambda nm: stats[nm][0], reverse=True)[:5])
    big = {nm for nm in real if stats[nm][1] / tot >= 0.05 or nm in top5_cnt}
    defmap = {x['名']: x for x in defs}

    L = [open(os.path.join(d, BASE), encoding='utf-8').read().rstrip(), '']
    L.append('## 簇定义（大模型按 docs/评论机制.md 第四节定，见 评论标签.json）\n')
    L.append('| 簇 | 定义 | 含 | 不含 |\n|---|---|---|---|')
    for nm in order:
        x = defmap[nm]
        L.append(f'| {nm} | {x.get("定义", "")} | {x.get("含", "")} | {x.get("不含", "")} |')

    L.append('\n## 簇统计（一条只进一个主簇，占比可相加）\n')
    head = '| 簇 | 条数 | 占条数 | 赞和 | 占赞 |' + (' 去掉最高赞一条后 |' if dom else '') + ' 主要动作 | 格 | 大簇 |'
    L.append(head)
    L.append('|' + '---|' * (head.count('|') - 1))
    for nm in order + ['其他', '无法判定']:
        k, s, mb, s_ex = stats[nm]
        if nm in RESERVED and k == 0:
            continue
        ex = f' {s_ex/tot_ex:.1%} |' if dom else ''
        g = defmap.get(nm, {}).get('格', '') if nm not in RESERVED else '—'
        L.append(f'| {nm} | {k} | {k/n:.1%} | {s} | **{s/tot:.1%}** |{ex} {mb} {B_NAME.get(mb, "")} | {g} | {"★" if nm in big else ""} |')
    L.append('\n★＝大簇（占样本赞 ≥5%，或条数前 5）：必须回片里找触发点（docs/评论机制.md 第四节第 4 步）。')

    L.append('\n## 各簇高赞原句（每簇前 3，完整原句只留在本文件）\n')
    for nm in order + ['其他']:
        ids = sorted(by.get(nm, []), key=lambda i: sample[i]['digg'], reverse=True)[:3]
        if not ids:
            continue
        L.append(f'**{nm}**（{stats[nm][1]/tot:.1%}）')
        L += [f'- {sample[i]["digg"]} 赞｜#{i}{"｜↳" if sample[i]["reply"] else ""}｜{sample[i]["text"][:80]}' for i in ids]
        L.append('')

    L.append('## 评论动作分布（B0–B8）\n')
    L.append('| 码 | 动作 | 条数 | 占条数 | 赞和 | 占赞 |\n|---|---|---|---|---|---|')
    bc, bs = Counter(), Counter()
    for i, (_, b) in lab.items():
        bc[b] += 1
        bs[b] += sample[i]['digg']
    for b in sorted(B_CODES, key=lambda b: bs[b], reverse=True):
        if bc[b]:
            L.append(f'| {b} | {B_NAME[b]} | {bc[b]} | {bc[b]/n:.1%} | {bs[b]} | {bs[b]/tot:.1%} |')

    if any(x.get('格') for x in defs):
        L.append('\n## 四格加总（簇的赞加到它的格；片外、无法判定、其他不进四格）\n')
        gz, gc = Counter(), Counter()
        gz_ex = Counter()
        undone = [nm for nm in real if not defmap[nm].get('格')]
        for nm in real:
            g = defmap[nm].get('格')
            if not g:
                continue
            k, s, _, s_ex = stats[nm]
            gz[g] += s
            gc[g] += k
            gz_ex[g] += s_ex
        in4 = sum(gz[g] for g in GRIDS)
        in4c = sum(gc[g] for g in GRIDS)
        in4_ex = sum(gz_ex[g] for g in GRIDS)
        L.append('| 格 | 按赞 | 按条数 |' + (' 去掉最高赞一条后（按赞） |' if dom else ''))
        L.append('|---|---|---|' + ('---|' if dom else ''))
        for g in GRIDS:
            pz = gz[g] / in4 if in4 else 0
            pc = gc[g] / in4c if in4c else 0
            ex = f' {gz_ex[g]/in4_ex:.1%} |' if dom and in4_ex else (' — |' if dom else '')
            L.append(f'| {g} | {pz:.1%} | {pc:.1%} |{ex}')
        off = gz['片外'] / tot
        L.append(f'\n片外占样本赞 {off:.1%}' + ('，**≥30%，结论标「可信度低」**' if off >= 0.30 else '') + '。')
        if in4:
            core = max(GRIDS, key=lambda g: gz[g])
            co = [g for g in GRIDS if g != core and gz[g] / in4 >= 0.15]
            L.append(f'核心机制（按赞）：**{core}**；同时激活（≥15%）：{"、".join(co) or "无"}。')
            if dom and in4_ex:
                core2 = max(GRIDS, key=lambda g: gz_ex[g])
                L.append(f'去掉最高赞一条后核心：**{core2}**' + ('（与上面不同，两个都报）' if core2 != core else '（不变）') + '。')
        if undone:
            L.append(f'⚠️ 还没定格的簇：{undone}。四格占比只算了已定格的簇。')

    L.append(f'\n## 全局 TOP{a.top} 高赞（核对标注用）\n')
    for k, i in enumerate(sorted(sample, key=lambda i: sample[i]['digg'], reverse=True)[:a.top], 1):
        L.append(f'{k}. **{sample[i]["digg"]}** 赞｜#{i}｜{lab[i][0]}｜{lab[i][1]}｜{sample[i]["text"][:90]}')

    L.append('\n## 自动检验\n')
    chk = []
    if dom:
        chk.append(f'⚠️ **单条支配**：最高赞 #{top1} 占样本赞 {sample[top1]["digg"]/tot:.1%}（≥30%）。已并列「去掉最高赞一条后」。')
    other = stats['其他'][1] / tot
    if other > 0.15:
        chk.append(f'⚠️ **「其他」占赞 {other:.1%}（>15%）**：有主簇没分出来，退回第四节第 2 步重分。')
    b0 = bc['B0'] / n
    if b0 > 0.10:
        chk.append(f'⚠️ B0 占条数 {b0:.1%}（>10%）：动作分类有漏，回查。')
    if len(real) > 8:
        chk.append(f'⚠️ 簇数 {len(real)}（>8）：小簇合并进「其他」或相近簇。')
    if len(real) < 2:
        chk.append(f'⚠️ 簇数 {len(real)}（<2）：分得太粗。')
    chk.append(f'「其他」{other:.1%}、「无法判定」{stats["无法判定"][1]/tot:.1%}（占赞）。')
    L += ['- ' + x for x in chk]

    open(out, 'w', encoding='utf-8', newline='\n').write('\n'.join(L) + '\n')
    print(f'✅ 已落盘 {out}')
    print('\n'.join(L[next(k for k, x in enumerate(L) if x.strip() == '## 自动检验'):]))


# ---------------- 复核 ----------------
def cmd_recheck(a):
    d = os.path.abspath(a.dir)
    sample = read_sample(d)
    _, l1 = read_labels(os.path.join(d, LABEL))
    _, l2 = read_labels(a.other)
    common = sorted(set(l1) & set(l2) & set(sample))
    if not common:
        die('两份标签没有共同序号')
    c_ok = sum(l1[i][0] == l2[i][0] for i in common)
    b_ok = sum(l1[i][1] == l2[i][1] for i in common)
    m = len(common)
    print(f'共同序号 {m} 条｜簇一致 {c_ok}/{m}＝{c_ok/m:.0%}｜B 码一致 {b_ok}/{m}＝{b_ok/m:.0%}')
    for i in common:
        if l1[i] != l2[i]:
            print(f'  #{i} 主标 {l1[i]} ｜复核 {l2[i]}｜{sample[i]["text"][:50]}')
    if c_ok / m < 0.8 or b_ok / m < 0.8:
        print('⚠️ 一致率 <80%：簇定义或编码有歧义，改定义后重标。')
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    s = sp.add_parser('sample', aliases=['样本'])
    s.add_argument('json', nargs='+')
    s.add_argument('--out')
    s.add_argument('--publish')
    s.add_argument('--fetched')
    s.add_argument('--page-total', type=int)
    s.add_argument('--note')
    s.add_argument('--force', action='store_true')
    s.set_defaults(f=cmd_sample)
    t = sp.add_parser('summarize', aliases=['汇总'])
    t.add_argument('dir')
    t.add_argument('--top', type=int, default=20)
    t.add_argument('--force', action='store_true')
    t.set_defaults(f=cmd_sum)
    r = sp.add_parser('recheck', aliases=['复核'])
    r.add_argument('dir')
    r.add_argument('other')
    r.set_defaults(f=cmd_recheck)
    a = ap.parse_args()
    a.f(a)


if __name__ == '__main__':
    main()
