#!/usr/bin/env python3
"""Save the current video for study and research (optional). First choice: a file you already have.

Usage:  python scripts/save_media.py <video> --out DIR [--audio-only]

<video> is a numeric id or https://www.douyin.com/video/<id>.

Use it only for personal study and research, and only for content you have the right to watch.
It handles one video per run. Do not share, publish or reuse the saved file.

How it works: the video page opens in a tab of your own logged-in ego browser and plays as usual.
A hook records the addresses that the page's own player requests. In that same page, the whole file
is read back with a Range request. No platform API, no signatures, no cookie export, no forged headers.
If the page has no plain media stream (encrypted, image post, private, removed), it stops with an error.

By default the audio and the picture are saved: the picture is needed for the key frames (frames.py).
Separate tracks stay separate files; nothing is merged. --audio-only saves the audio only (no key frames).

Every saved file is checked: bytes = total in content-range; ffprobe finds the right stream type;
duration differs from the page's video duration by 1 second or less. A failed check deletes the file.

Writes DIR/音画.mp4, or DIR/音轨.m4a + DIR/画面.mp4 (only 音轨.m4a with --audio-only), DIR/保存清单.json, DIR/元数据.md.
Deletion: with a picture, frames.py deletes the saved files after it extracts the key frames.
With --audio-only, transcribe.py deletes them after it finishes. --keep-media on either script keeps them.

Exit codes: 0 ok; 1 failed (read the message); ego codes 75/76/127 are passed through.
"""
import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tp_common import JS_DIR, utf8_stdio, video_id, video_url, read_text  # noqa: E402
import ego_run  # noqa: E402

CHUNK = 2 * 1024 * 1024
NAMES = {"audio": "音轨.m4a", "av": "音画.mp4", "video": "画面.mp4"}
MANIFEST = "保存清单.json"
MAX_GAP_S = 1.0


def probe(path):
    """Return (stream types, duration in seconds) from ffprobe."""
    exe = shutil.which("ffprobe")
    if not exe:
        raise SystemExit("找不到 ffprobe（随 ffmpeg 一起装）。没有它无法校验保存的文件。")
    r = subprocess.run([exe, "-v", "error", "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    try:
        d = json.loads(r.stdout or "{}")
        kinds = sorted({s.get("codec_type") for s in d.get("streams", []) if s.get("codec_type")})
        return kinds, float(d.get("format", {}).get("duration") or 0)
    except (ValueError, json.JSONDecodeError):
        return [], 0.0


def check_file(path, kind, page_dur):
    """Return an error message, or None when the file is the right type and length."""
    kinds, dur = probe(path)
    need = {"audio": ["audio"], "av": ["audio", "video"], "video": ["video"]}[kind]
    if not all(k in kinds for k in need):
        return f"{path.name} 的流类型是 {kinds or '无法识别'}，应有 {need}"
    if page_dur and abs(dur - page_dur) > MAX_GAP_S:
        return f"{path.name} 时长 {dur:.1f} 秒，页面上是 {page_dur:.1f} 秒，相差超过 {MAX_GAP_S:.0f} 秒"
    return None


def parse_log(text):
    """Split the ego log into file pieces and the final result."""
    pieces, result, rest = {}, None, []
    for line in text.splitlines():
        if line.startswith("@@CHUNK@@ "):
            _, key, seq, b64 = line.split(" ", 3)
            pieces.setdefault(key, {})[int(seq)] = b64
        elif "@@RESULT@@ " in line:
            result = json.loads(line.split("@@RESULT@@ ", 1)[1])
            rest.append(line)
        else:
            rest.append(line)
    return pieces, result, rest


def assemble(pieces, key, expect):
    parts = pieces.get(key, {})
    if sorted(parts) != list(range(len(parts))):
        raise ValueError(f"{key} 的数据片不连续")
    data = b"".join(base64.b64decode(parts[i]) for i in range(len(parts)))
    if len(data) != expect:
        raise ValueError(f"{key} 收到 {len(data)} 字节，应为 {expect} 字节")
    return data


def hours_since(pub, fetched):
    m = re.search(r"(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?", pub or "")
    if not m:
        return None
    t = datetime.strptime(m.group(1) + " " + (m.group(2) or "00:00"), "%Y-%m-%d %H:%M")
    return (fetched.replace(tzinfo=None) - t).total_seconds() / 3600


def main():
    utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--out", required=True)
    ap.add_argument("--audio-only", action="store_true", help="save the audio only; no key frames possible")
    a = ap.parse_args()
    vid = video_id(a.video)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    fallback = "请自己在抖音里保存视频（有权保存时），把文件交给 transcribe.py。"

    fetched = datetime.now().astimezone()
    js = (JS_DIR / "page_save.js").read_text(encoding="utf-8")
    js = js.replace("__ID__", vid).replace("__WANT__", "audio" if a.audio_only else "all").replace("__CHUNK__", str(CHUNK))
    log = out / "ego日志_保存.txt"
    rc = ego_run.run_js(js, 300, str(log))
    if rc in (75, 76, 127):
        return rc
    pieces, r, rest = parse_log(read_text(log) if log.exists() else "")
    log.write_text("\n".join(rest) + "\n", encoding="utf-8")  # keep the log small: drop the data lines
    if not r:
        print(f"没有读到页面结果（ego 退出码 {rc}）。日志：{log}")
        return 1
    if r.get("stop"):
        print(f"停：{r['stop']}。{fallback}")
        return 1

    page_dur = r.get("duration")
    saved, errors = [], []
    for s in r.get("saved", []):
        dst = out / NAMES[s["kind"]]
        try:
            dst.write_bytes(assemble(pieces, s["kind"], s["total"]))
        except (ValueError, KeyError) as e:
            errors.append(str(e))
            continue
        err = check_file(dst, s["kind"], page_dur)
        if err:
            errors.append(err)
            dst.unlink(missing_ok=True)
            continue
        saved.append({"file": dst.name, "kind": s["kind"], "bytes": s["total"]})
    if errors or not saved:
        for x in saved:
            (out / x["file"]).unlink(missing_ok=True)
        print("校验不通过，已删除：" + "；".join(errors or ["没有收到文件"]) + "。" + fallback)
        return 1

    audio = next(x["file"] for x in saved if x["kind"] in ("audio", "av"))
    picture = next((x["file"] for x in saved if x["kind"] in ("video", "av")), None)
    (out / MANIFEST).write_text(json.dumps({
        "video": video_url(vid), "saved_at": fetched.isoformat(timespec="seconds"), "audio_for_transcribe": audio,
        "picture_for_frames": picture, "files": saved, "needs_frames": bool(picture), "delete_after_transcribe": True,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    h = hours_since(r.get("pub"), fetched)
    author = f"[{r.get('author_name') or '作者'}]({r['author_href']})" if r.get("author_href") else "链接待补"
    files = "；".join(f"{x['file']} {x['bytes'] / 1048576:.2f} MB" for x in saved)
    md = [
        f"# 元数据：{r.get('title') or vid}", "",
        f"- **链接**：{video_url(vid)}",
        f"- **作者**：{author}",
        f"- **简介**：{(r.get('desc') or '').replace(chr(10), ' ')}",
        f"- **读数**：赞 {r.get('digg')}｜评 {r.get('comment')}｜藏 {r.get('collect')}｜转 {r.get('share')}",
        f"- **发布**：{(r.get('pub') or '未采').replace('发布时间：', '').strip()}",
        f"- **采集时间**：{fetched:%Y-%m-%d %H:%M:%S %z}" + (f"（距发布 {h:.1f} 小时）" if h is not None else ""),
        f"- **时长**：{page_dur:.1f} 秒（页面），保存的文件已核对" if page_dur else "- **时长**：页面未给出",
        f"- **保存的文件**：{files}。只供个人学习研究，截完关键帧（只取音轨时为转录后）默认删除，不转发、不公开。",
    ]
    (out / "元数据.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print(f"\n下一步：python scripts/transcribe.py \"{out}\"" + ("；读逐字稿定转折点后：python scripts/frames.py \"" + str(out) + "\" --at <秒> …" if picture else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
