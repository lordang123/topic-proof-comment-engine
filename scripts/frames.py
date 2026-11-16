#!/usr/bin/env python3
"""Extract key frames for the key-frame record of the benchmark card (docs/对标复原.md).

Usage:  python scripts/frames.py <folder from save_media.py | video file> [--at SEC ...] [--cuts 8] [--out DIR] [--keep-media]

Frames taken:
  - the opening: 0, 1, 2, 3 seconds;
  - each --at time (the turning points you picked from the transcript);
  - up to --cuts scene changes (shot cuts found by ffmpeg; 0 = none);
  - the end: 0.5 seconds before the last frame.
Frames are JPG, 720 px wide, written to DIR/关键帧/ (default: next to the video), with 关键帧清单.md.
Read the images yourself and write the key-frame record. A frame you did not look at is 「未读」.

After a successful run, the files saved by save_media.py (listed in 保存清单.json) are deleted,
unless you pass --keep-media. A video file you supplied yourself is never deleted.
The frames are someone else's content too: keep them on your own computer only.

Exit codes: 0 ok; 1 failed.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tp_common import utf8_stdio  # noqa: E402
from transcribe import MANIFEST, delete_saved  # noqa: E402

OPENING = [0.0, 1.0, 2.0, 3.0]
MIN_GAP = 0.4  # frames closer than this are the same moment


def tool(name):
    exe = shutil.which(name)
    if not exe:
        raise SystemExit(f"找不到 {name}（随 ffmpeg 一起装）。")
    return exe


def resolve(path):
    """Return (picture file, manifest or None)."""
    if not path.exists():
        raise SystemExit(f"找不到：{path}")
    man = (path if path.is_dir() else path.parent) / MANIFEST
    if path.is_dir():
        if not man.exists():
            raise SystemExit(f"{path} 里没有 {MANIFEST}。请直接给视频文件。")
        data = json.loads(man.read_text(encoding="utf-8"))
        pic = data.get("picture_for_frames")
        if not pic:
            raise SystemExit("这次只保存了音轨（--audio-only），没有画面，截不了帧。关键帧记录写「未读」。")
        return path / pic, man
    if man.exists():
        data = json.loads(man.read_text(encoding="utf-8"))
        if path.name in {f["file"] for f in data.get("files", [])}:
            return path, man
    return path, None


def duration(video):
    r = subprocess.run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(video)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except (ValueError, KeyError, json.JSONDecodeError):
        raise SystemExit(f"读不出时长：{video}")


def scene_cuts(video, limit, threshold=0.35):
    """Times of the strongest shot changes, at most `limit`."""
    if limit <= 0:
        return []
    r = subprocess.run([tool("ffmpeg"), "-hide_banner", "-nostats", "-i", str(video), "-an",
                        "-vf", f"select='gt(scene,{threshold})',metadata=print", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    found, t = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
        m = re.search(r"lavfi\.scene_score=([\d.]+)", line)
        if m and t is not None:
            found.append((float(m.group(1)), t))
            t = None
    return sorted(t for _, t in sorted(found, reverse=True)[:limit])


def plan(dur, at, cuts):
    """Merge all wanted times: [(seconds, reason)], sorted, inside the video, no near-duplicates."""
    want = [(t, "开头") for t in OPENING] + [(t, "转折") for t in at] + [(t, "切镜") for t in cuts] + [(dur - 0.5, "结尾")]
    out = []
    for t, why in sorted(((min(max(t, 0.0), max(dur - 0.5, 0.0)), why) for t, why in want), key=lambda x: x[0]):
        if out and t - out[-1][0] < MIN_GAP:
            if why == "转折":  # a picked turning point wins over an automatic frame at the same moment
                out[-1] = (out[-1][0], why)
            continue
        out.append((round(t, 2), why))
    return out


def grab(video, t, dst):
    r = subprocess.run([tool("ffmpeg"), "-y", "-loglevel", "error", "-nostats", "-ss", f"{t:.2f}", "-i", str(video),
                        "-frames:v", "1", "-vf", "scale=720:-2", "-q:v", "3", str(dst)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0 and dst.exists() and dst.stat().st_size > 0


def main():
    utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("--at", nargs="*", type=float, default=[], help="turning points in seconds")
    ap.add_argument("--cuts", type=int, default=8, help="max scene-change frames (0 = none)")
    ap.add_argument("--out")
    ap.add_argument("--keep-media", action="store_true")
    a = ap.parse_args()
    video, man = resolve(Path(a.src).expanduser().resolve())
    out = (Path(a.out).resolve() if a.out else video.parent) / "关键帧"
    out.mkdir(parents=True, exist_ok=True)

    dur = duration(video)
    times = plan(dur, a.at, scene_cuts(video, a.cuts))
    rows, bad = [], []
    for t, why in times:
        name = f"t{t:07.2f}s_{why}.jpg"
        if grab(video, t, out / name):
            rows.append(f"| {t:.2f} | {why} | 关键帧/{name} |")
        else:
            bad.append(f"{t:.2f}")
    if not rows:
        print("一张帧也没截到。")
        return 1
    md = ["# 关键帧清单", "", f"来源：{video.name}，时长 {dur:.1f} 秒，共 {len(rows)} 张。", "",
          "逐张看图后再写复原卡的关键帧记录。没看的写「未读」，不编。", "",
          "| 秒 | 类型 | 文件 |", "|---|---|---|"] + rows
    if bad:
        md += ["", f"截取失败的时间点：{'、'.join(bad)}"]
    (out.parent / "关键帧清单.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"✅ {len(rows)} 张 → {out}" + (f"（失败 {len(bad)} 个）" if bad else ""))

    if man:
        data = json.loads(man.read_text(encoding="utf-8"))
        data["needs_frames"] = False
        man.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if not (man.parent / "逐字稿.md").exists():
            print("还没有逐字稿，保存的文件先留着：转录完成后由 transcribe.py 删除。")
        elif not a.keep_media:
            gone = delete_saved(man)
            if gone:
                print("已删除保存的媒体文件（要保留请加 --keep-media）：" + "、".join(gone))
    return 0


if __name__ == "__main__":
    sys.exit(main())
