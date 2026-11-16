"""Offline tests: no browser, no network, no model. Run: python -m unittest discover -s tests"""
import json
import io
from contextlib import redirect_stdout
from unittest.mock import patch
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_env  # noqa: E402
import collect  # noqa: E402
import ego_run  # noqa: E402
import frames  # noqa: E402
import save_media  # noqa: E402
import transcribe  # noqa: E402
import board_data  # noqa: E402
import report_parse  # noqa: E402
import result_page  # noqa: E402
from tp_common import DEFAULTS, num, run_with_timeout, video_id  # noqa: E402

PY = sys.executable
CC = str(ROOT / "scripts" / "comment_cluster.py")


def fake_comments():
    rows = [("作者回复一下", 999, True), ("我们厂也是这样，三年只发一盒月饼", 500, False),
            ("月饼都是过期的", 300, False), ("老板良心呢", 120, False), ("哈哈哈", 5, False),
            ("这不就是我家那位吗", 60, False), ("@朋友 快看", 0, False), ("👍👍", 2, False)]
    return [{"i": i, "isAuthor": a, "authorLiked": False, "isReply": False, "text": t, "when": "3天前",
             "digg": d, "replies": 0, "pos": i + 1, "stratum": "赞高"} for i, (t, d, a) in enumerate(rows)]


class Common(unittest.TestCase):
    def test_num(self):
        self.assertEqual(num("1.2万"), 12000)
        self.assertEqual(num("3,456"), 3456)
        self.assertEqual(num("2亿"), 200000000)
        self.assertIsNone(num("抢首评"))

    def test_video_id(self):
        self.assertEqual(video_id("https://www.douyin.com/video/7000000000000000001?x=1"), "7000000000000000001")
        with self.assertRaises(ValueError):
            video_id("https://v.douyin.com/abc/")

    def test_timeout_kills(self):
        t0 = time.time()
        rc, timed_out = run_with_timeout([PY, "-c", "import time; time.sleep(30)"], 1)
        self.assertTrue(timed_out)
        self.assertEqual(rc, 124)
        self.assertLess(time.time() - t0, 10)

    def test_skill_copies_identical(self):
        a = (ROOT / ".agents/skills/选题验证/SKILL.md").read_text(encoding="utf-8")
        b = (ROOT / ".claude/skills/选题验证/SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(a, b, "两份 SKILL.md 不一致：改一份要同步另一份")

    def test_config_example_matches_defaults(self):
        ex = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(set(ex), set(DEFAULTS))


class Environment(unittest.TestCase):
    def test_model_formats(self):
        cases = [("mlx", "weights.npz", True), ("mlx", "weights.safetensors", True),
                 ("faster", "model.bin", True), ("mlx", "weights.npz.incomplete", False),
                 ("mlx", None, False)]
        for engine, filename, ready in cases:
            with self.subTest(engine=engine, filename=filename), tempfile.TemporaryDirectory() as td:
                models = Path(td)
                sub = models / ("mlx" if engine == "mlx" else "faster") / "snapshot"
                sub.mkdir(parents=True)
                if filename:
                    (sub / filename).write_bytes(b"model fixture")
                output = io.StringIO()
                with patch.object(check_env, "MODELS", models), patch.object(check_env, "pick_engine", return_value=engine), \
                        patch.object(check_env.ego_run, "ego_exe", return_value=None), redirect_stdout(output):
                    check_env.main()
                tag = "[ OK ]" if ready else "[缺少]"
                self.assertIn(f"{tag} 转录模型已下载", output.getvalue())


class Privacy(unittest.TestCase):
    def test_page_script_returns_no_nickname_or_region(self):
        js = (ROOT / "scripts/js/page_read.js").read_text(encoding="utf-8")
        ret = js[js.index("return { i, isAuthor"):]
        ret = ret[: ret.index("}")]
        for bad in ("nick", "meta", "avatar", "ip"):
            self.assertNotIn(bad, ret)
        self.assertIn("split('·')[0]", js)

    def test_ego_run_refuses_claim(self):
        self.assertEqual(ego_run.run_js("await claimTaskSpace('x')"), 2)


class Collect(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.cfg = dict(DEFAULTS, work_dir=self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def log(self, visits, end):
        return "\n".join(["[ego] noise"] + ["@@VISIT@@ " + json.dumps(v, ensure_ascii=False) for v in visits]
                         + ["@@END@@ " + json.dumps(end)])

    def test_finish_batch(self):
        out = Path(self.td.name) / "采集"
        out.mkdir()
        visits = [
            {"n": 1, "id": "111111111111111111", "comment_n": 800, "digg": "1.2万", "comment": "800", "pub": "发布时间：2026-01-02 10:00",
             "pub_year": 2026, "year_ok": True, "comments": fake_comments(), "comments_loaded": 8},
            {"n": 2, "id": "222222222222222222", "comment_n": 300, "comments_skip": "评论数 ≤500"},
            {"n": 3, "id": "333333333333333333", "comment_n": 900, "comments": [], "comments_err": "评论区 10 秒内没有评论项"},
        ]
        rc, rows, end = collect.finish_batch(self.log(visits, {"stop": "跑完 3 次，无异常", "remaining": ["444444444444444444"]}), out, self.cfg)
        self.assertEqual(rc, 2)  # one failure, not stopped
        man = (out / "采集汇总.tsv").read_text(encoding="utf-8")
        self.assertIn("111111111111111111\t成功\t8", man)
        self.assertIn("222222222222222222\t跳过", man)
        self.assertIn("333333333333333333\t失败", man)
        self.assertIn("444444444444444444\t未访问", man)
        saved = (out / "111111111111111111" / "评论.json").read_text(encoding="utf-8")
        self.assertNotIn("nick", saved)
        self.assertFalse((out / "333333333333333333" / "评论.json").exists())
        top = (out / "111111111111111111" / "评论_TOP.md").read_text(encoding="utf-8")
        self.assertNotIn("作者回复一下", top)

    def test_finish_batch_stop(self):
        out = Path(self.td.name)
        rc, _, _ = collect.finish_batch(self.log([{"n": 1, "id": "1" * 18, "stop_here": True}],
                                                 {"stop": "第 1 次读不到评论数：疑似受限，或视频已删除"}), out, self.cfg)
        self.assertEqual(rc, 3)
        rc, _, _ = collect.finish_batch("no end marker", out, self.cfg)
        self.assertEqual(rc, 3)

    def test_cache_skip(self):
        now = time.time()
        self.assertIn("缓存", collect.cached_skip({"comment_n": 100, "fetched_ts": now - 86400}, self.cfg, now))
        self.assertIsNone(collect.cached_skip({"comment_n": 100, "fetched_ts": now - 40 * 86400}, self.cfg, now))
        self.assertIsNone(collect.cached_skip({"comment_n": 900, "fetched_ts": now, "comments_path": "/nope"}, self.cfg, now))

    def test_candidates_and_likes(self):
        p = Path(self.td.name) / "r.json"
        p.write_text(json.dumps({"visits": [{"rel": [{"id": "5" * 19, "txt": "01:23 | 标题 | 3.4万 | @某人"}]}]}), encoding="utf-8")
        self.assertEqual(collect.parse_candidates(p), [("5" * 19, "01:23 | 标题 | 3.4万 | @某人")])
        self.assertEqual(collect.card_likes("01:23 | 标题 | 3.4万 | @某人"), 34000)
        s = Path(self.td.name) / "s.json"
        s.write_text(json.dumps({"searches": [{"cards": [{"id": "6" * 19, "txt": "x"}]}]}), encoding="utf-8")
        self.assertEqual(collect.parse_candidates(s)[0][0], "6" * 19)


class CommentCluster(unittest.TestCase):
    def test_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "v1" / "评论.json"
            src.parent.mkdir()
            src.write_text(json.dumps(fake_comments(), ensure_ascii=False), encoding="utf-8")
            out = Path(td) / "分簇"
            r = subprocess.run([PY, CC, "sample", str(src), "--out", str(out)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            tsv = (out / "评论样本.tsv").read_text(encoding="utf-8")
            self.assertNotIn("作者回复一下", tsv)
            self.assertEqual(len(tsv.strip().splitlines()), 8)  # header + 7
            labels = {"簇": [{"名": "三年只发一盒月饼", "定义": "厂里福利差", "含": "月饼", "不含": "骂老板", "格": "感受·共情"},
                            {"名": "骂老板", "定义": "指责老板", "含": "良心", "不含": "月饼", "格": "思辨·不认同"}],
                      "标签": [[1, "三年只发一盒月饼", "B2"], [2, "三年只发一盒月饼", "B3"], [3, "骂老板", "B1"],
                             [4, "其他", "B8"], [5, "三年只发一盒月饼", "B2"], [6, "无法判定", "B5"], [7, "无法判定", "B8"]]}
            (out / "评论标签.json").write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
            r = subprocess.run([PY, CC, "summarize", str(out)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            rep = (out / "评论分簇.md").read_text(encoding="utf-8")
            # (500+300+60) / (500+300+120+5+60+0+2) = 860/987
            self.assertIn(f"{860 / 987:.1%}", rep)
            self.assertIn("核心机制（按赞）：**感受·共情**", rep)
            bad = dict(labels, 标签=labels["标签"][:-1])
            (out / "评论标签.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
            r = subprocess.run([PY, CC, "summarize", str(out), "--force"], capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("没标", r.stderr)


class Transcribe(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(transcribe.mlx_repo("large-v3"), "mlx-community/whisper-large-v3-mlx")
        self.assertEqual(transcribe.ts(3725.25, srt=True), "01:02:05,250")
        self.assertTrue(transcribe.doubtful({"text": "哈哈哈哈哈哈哈哈哈哈", "avg_logprob": -0.1, "no_speech_prob": 0}))
        self.assertTrue(transcribe.doubtful({"text": "x", "avg_logprob": -1.5, "no_speech_prob": 0}))
        self.assertFalse(transcribe.doubtful({"text": "今天我们聊聊加班", "avg_logprob": -0.2, "no_speech_prob": 0.1}))
        self.assertIn(transcribe.pick_engine(), ("mlx", "faster"))


class SaveMedia(unittest.TestCase):
    def test_helpers(self):
        h = save_media.hours_since("发布时间：2026-11-12 10:00", datetime(2026, 11, 13, 10, 0))
        self.assertAlmostEqual(h, 24.0)
        self.assertIsNone(save_media.hours_since(None, datetime.now()))

    def test_parse_and_assemble(self):
        import base64
        data = bytes(range(256)) * 10
        a, b = base64.b64encode(data[:1000]).decode(), base64.b64encode(data[1000:]).decode()
        log = f"noise\n@@CHUNK@@ audio 1 {b}\n@@CHUNK@@ audio 0 {a}\n@@RESULT@@ " + json.dumps({"saved": [{"kind": "audio", "total": len(data)}]})
        pieces, r, rest = save_media.parse_log(log)
        self.assertEqual(save_media.assemble(pieces, "audio", len(data)), data)
        self.assertEqual(r["saved"][0]["kind"], "audio")
        self.assertFalse(any("@@CHUNK@@" in x for x in rest))
        with self.assertRaises(ValueError):
            save_media.assemble(pieces, "audio", len(data) + 1)
        with self.assertRaises(ValueError):
            save_media.assemble({"audio": {0: a, 2: b}}, "audio", len(data))

    def test_page_script_rules(self):
        js = (ROOT / "scripts" / "js" / "page_save.js").read_text(encoding="utf-8")
        code = "\n".join(x for x in js.splitlines() if not x.strip().startswith("//"))
        for bad in ("User-Agent", "Referer", "a_bogus", "X-Bogus", "aweme/v1", "document.cookie", "claimTaskSpace"):
            self.assertNotIn(bad, code)

    def test_delete_only_listed(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "音轨.m4a").write_bytes(b"x")
            (d / "我自己的.mp4").write_bytes(b"y")
            (d / "保存清单.json").write_text(json.dumps({"audio_for_transcribe": "音轨.m4a",
                                                     "files": [{"file": "音轨.m4a"}, {"file": "../escape.mp4"}]}), encoding="utf-8")
            src, man = transcribe.resolve_source(d)
            self.assertEqual(src.name, "音轨.m4a")
            self.assertIsNone(transcribe.resolve_source(d / "我自己的.mp4")[1])
            self.assertEqual(transcribe.delete_saved(man), ["音轨.m4a"])
            self.assertTrue((d / "我自己的.mp4").exists())


class Frames(unittest.TestCase):
    def test_plan(self):
        p = frames.plan(20.0, [2.1, 9.0], [9.2, 15.0])
        times = [t for t, _ in p]
        self.assertEqual(times[:4], [0.0, 1.0, 2.0, 3.0])  # 2.1 merges into 2.0 and wins as 转折
        self.assertIn((2.0, "转折"), p)
        self.assertIn((9.0, "转折"), p)
        self.assertNotIn(9.2, times)
        self.assertEqual(p[-1], (19.5, "结尾"))
        self.assertTrue(all(b - a >= frames.MIN_GAP for a, b in zip(times, times[1:])))

    def test_audio_only_and_flow(self):
        import shutil
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "音轨.m4a").write_bytes(b"x")
            (d / "保存清单.json").write_text(json.dumps({"audio_for_transcribe": "音轨.m4a", "picture_for_frames": None,
                                                     "files": [{"file": "音轨.m4a"}], "needs_frames": False}), encoding="utf-8")
            with self.assertRaises(SystemExit):
                frames.resolve(d)
            if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
                self.skipTest("no ffmpeg")
            v = d / "画面.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10",
                            "-t", "6", str(v)], check=True)
            (d / "保存清单.json").write_text(json.dumps({"audio_for_transcribe": "音轨.m4a", "picture_for_frames": "画面.mp4",
                                                     "files": [{"file": "音轨.m4a"}, {"file": "画面.mp4"}], "needs_frames": True}),
                                          encoding="utf-8")
            r = subprocess.run([PY, str(ROOT / "scripts" / "frames.py"), str(d), "--at", "4", "--cuts", "0"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(v.exists())  # no transcript yet: keep the media
            self.assertGreaterEqual(len(list((d / "关键帧").glob("*.jpg"))), 5)
            (d / "逐字稿.md").write_text("x", encoding="utf-8")
            r = subprocess.run([PY, str(ROOT / "scripts" / "frames.py"), str(d), "--cuts", "0"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertFalse(v.exists())
            self.assertFalse((d / "音轨.m4a").exists())


FAKE_REPORT = """# 选题验证：测试选题

对标：[测试标题](https://www.douyin.com/video/7000000000000000001)｜[测试作者](https://www.douyin.com/user/TEST)｜赞 1.2万／评 1000／藏 300／转 200｜40 秒｜发布 2026-01-02｜采集 2026-02-01

## 1 结论

**情形：B，有更高一级。建议：做，先看第一条。**

有效同题 2 条，最高一条是对标的 2.5 倍。第二句。

**最大的未知项：** 测试未知项。

## 2 同题片

| 视频 | 作者 | 赞／评／藏／转 | 评论数 ÷ 对标 | 时长 | 发布日 | 采集日 | 同题理由 |
|---|---|---|---|---|---|---|---|
| [同题一](https://www.douyin.com/video/7000000000000000002) | [作者甲](https://www.douyin.com/user/A) | 2万／2500／1／1 | 2500 ÷ 1000 ＝ 2.50 | 00:30 | 2025-05-01 | 2026-02-01 | 理由一 |
| [同题二](https://www.douyin.com/video/7000000000000000003) | 作者乙 | 1万／800／1／1 | 800 ÷ 1000 ＝ 0.80 | 00:40 | 2026-01-01 | 2026-02-01 | 理由二 |
| [旧片（旁证，不计有效）](https://www.douyin.com/video/7000000000000000004) | 作者丙 | 1万／900／1／1 | 900 ÷ 1000 ＝ 0.90 | 00:40 | 2023-01-01 | 2026-02-01 | 旁证 |

**选题卡**：一句话选题＝新人被老员工抢功；现实原型＝职场抢功；依据＝逐字稿第 2 段（8 秒）。

搜索词：词一（场景与原型）、词二（矛盾）。推荐里有效同题 1 条，搜索后新增 1 条。

## 3 评论机制

**对标**：核心机制＝感受·共情；同时激活＝思辨·认同；片外＝0%。

**同题片（合并评论池）**：核心机制＝感受·共情；与对标一致。

**还没激活、选题有条件激活的格**：无

## 4 对标结构

“开场”（钩子）→“转折”（反转）→“提问”（低门槛）

完播上做得好的点：测试。
"""

FAKE_CLUSTERS = """## 实测底盘（脚本产出，可核）

样本 **50 条**（已去掉作者评论），抓取 **2026-02-01 10:00**，距发布 **1 h**，页面评论总数 1000、**采样率 5.0%**。样本总赞 **400**。

## 簇统计（一条只进一个主簇，占比可相加）

| 簇 | 条数 | 占条数 | 赞和 | 占赞 | 主要动作 | 格 | 大簇 |
|---|---|---|---|---|---|---|---|
| 我也这样 | 30 | 60.0% | 300 | **75.0%** | B2 讲自己 | 感受·共情 | ★ |
| 其他 | 20 | 40.0% | 100 | **25.0%** | B8 玩 | — |  |

## 各簇高赞原句（每簇前 3，完整原句只留在本文件）

**我也这样**（75.0%）
- 120 赞｜#3｜我们厂也是这样，三年只发一盒月饼

## 评论动作分布（B0–B8）

| 码 | 动作 | 条数 | 占条数 | 赞和 | 占赞 |
|---|---|---|---|---|---|
| B2 | 讲自己 | 30 | 60.0% | 300 | 75.0% |

## 四格加总（簇的赞加到它的格；片外、无法判定、其他不进四格）

| 格 | 按赞 | 按条数 |
|---|---|---|
| 思辨·认同 | 0.0% | 0.0% |
| 思辨·不认同 | 0.0% | 0.0% |
| 感受·共情 | 100.0% | 100.0% |
| 感受·反感 | 0.0% | 0.0% |

核心机制（按赞）：**感受·共情**；同时激活（≥15%）：无。
"""


def fake_topic(root, name="测试选题", frames=True):
    d = Path(root) / name
    (d / "分簇_对标").mkdir(parents=True)
    (d / "选题验证报告.md").write_text(FAKE_REPORT, encoding="utf-8")
    (d / "分簇_对标" / "评论分簇.md").write_text(FAKE_CLUSTERS, encoding="utf-8")
    if frames:
        (d / "对标" / "关键帧").mkdir(parents=True)
        (d / "对标" / "关键帧" / "t0005.00s_转折.jpg").write_bytes(b"jpg")
        (d / "对标" / "关键帧清单.md").write_text(
            "| 秒 | 类型 | 文件 |\n|---|---|---|\n| 5.00 | 转折 | 关键帧/t0005.00s_转折.jpg |\n| 9.00 | 结尾 | 关键帧/缺失.jpg |\n", encoding="utf-8")
    return d


class Pages(unittest.TestCase):
    def test_search_is_always_required(self):
        for f in (".agents/skills/选题验证/SKILL.md", "docs/选题验证.md", "AGENTS.md"):
            text = (ROOT / f).read_text(encoding="utf-8")
            self.assertIn("必做", text, f)
            self.assertNotIn("<2 条时搜索", text, f)
            self.assertNotIn("不够再搜索", text, f)
            self.assertNotIn("冲突", text, f)

    def test_parse_topic(self):
        with tempfile.TemporaryDirectory() as td:
            t = report_parse.parse_topic(fake_topic(td))
        self.assertEqual(t["case"]["L"], "B")
        self.assertEqual(t["case"]["advice"], "做，先看第一条。")
        self.assertEqual(t["bench"]["c"], 1000)
        self.assertEqual(t["bench"]["like"], "1.2万")
        self.assertEqual((t["valid"], t["maxX"], t["over"]), (2, 2.5, 1))
        self.assertTrue(t["rows"][2]["side"])
        self.assertEqual(t["topic_card"], "新人被老员工抢功")
        self.assertEqual(t["search"], "词一（场景与原型）、词二（矛盾）")
        self.assertEqual([s["how"] for s in t["structure"]["steps"]], ["钩子", "反转", "低门槛"])
        cb = t["clusters"]["bench"]
        self.assertEqual((cb["n"], cb["likes"], cb["core"]), (50, 400, "感受·共情"))
        self.assertEqual(cb["items"][0]["pct"], 75.0)  # copied, not computed
        self.assertTrue(cb["items"][0]["quote"].endswith("……"))
        self.assertEqual(len(t["frames"]), 1)  # the missing image is skipped

    def test_result_page(self):
        with tempfile.TemporaryDirectory() as td:
            out, d = result_page.build(fake_topic(td))
            page = out.read_text(encoding="utf-8")
            self.assertEqual(out.name, "选题验证结果页.html")
            self.assertNotIn("__DATA__", page)
            self.assertIn("对标/关键帧/t0005.00s_转折.jpg", page)
            empty = Path(td) / "没有报告"
            empty.mkdir()
            self.assertIsNone(result_page.build(empty)[0])

    def test_board_data_and_empty(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = dict(DEFAULTS, work_dir=str(Path(td) / "work"))
            data, warn = board_data.collect(cfg=cfg)
            self.assertEqual(data["topics"], [])  # empty work folder: the page shows the guide
            fake_topic(Path(td) / "work")
            data, warn = board_data.collect(cfg=cfg)
            t = data["topics"][0]
            self.assertEqual((t["case"]["L"], t["valid"], t["core"], t["n_frames"]), ("B", 2, "感受·共情", 1))
            self.assertTrue(t["page"].endswith("选题验证结果页.html"))
            self.assertEqual(warn, [])

    def test_brand_from_config_and_demo_is_fake(self):
        # the brand shown on both pages comes from config.json, not from the page
        self.assertIn("D.brand.name", (ROOT / "scripts/web/result_page.html").read_text(encoding="utf-8"))
        self.assertIn("BR.name", (ROOT / "board/index.html").read_text(encoding="utf-8"))
        demo = (ROOT / "board/demo_data.js").read_text(encoding="utf-8")
        self.assertNotRegex(demo, r"douyin\.com/(video|user)/")
        self.assertIn('"demo": true', demo)
        self.assertIn("示例数据 · 非真实账号", (ROOT / "board/index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
