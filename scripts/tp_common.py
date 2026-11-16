"""Shared helpers for topic-proof-comment-engine scripts. Standard library only; works on macOS and Windows."""
import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
JS_DIR = SCRIPTS / "js"
IS_WIN = sys.platform == "win32"

DEFAULTS = {
    "work_dir": "work",
    "comment_min": 500,
    "years_back": 1,
    "like_min": 1500,
    "reply_top": 3,
    "max_top": 200,
    "hot_k": 45,
    "pos_m": 45,
    "chunk": 20,
    "max_keywords": 6,
    "whisper_model": "large-v3",
    "hf_endpoint": "",
    "transcribe_prompt": "以下是普通话短视频的口播和对话。",
    "board_title": "格厚AI · 爆款内容工厂",
    "board_subtitle": "GEHOU · NEURAL CONTENT ENGINE",
}


def utf8_stdio():
    """Windows consoles default to a legacy code page; force UTF-8 so Chinese and emoji print."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def load_config():
    cfg = dict(DEFAULTS)
    p = Path(os.environ.get("TOPIC_PROOF_CONFIG") or ROOT / "config.json")
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    return cfg


def work_dir(cfg=None):
    cfg = cfg or load_config()
    p = Path(cfg["work_dir"])
    if not p.is_absolute():
        p = ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def video_id(s):
    """Accept a numeric id or a douyin.com/video/<id> URL. Share short links are not resolved."""
    m = re.search(r"(\d{15,})", str(s))
    if not m:
        raise ValueError(f"认不出视频 ID：{s!r}。请给 https://www.douyin.com/video/<id> 形式的链接。")
    return m.group(1)


def video_url(vid):
    return f"https://www.douyin.com/video/{vid}"


def num(s):
    """'1.2万' -> 12000, '3,456' -> 3456, '2亿' -> 200000000. None when not a count."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(s)
    m = re.match(r"^([0-9.]+)\s*(万|亿|w|W)?$", str(s).replace(",", "").strip())
    if not m:
        return None
    mult = {"万": 1e4, "w": 1e4, "W": 1e4, "亿": 1e8}.get(m.group(2), 1)
    return round(float(m.group(1)) * mult)


def run_with_timeout(cmd, seconds, stdin_text=None, stdout=None, stderr=None):
    """Run cmd; kill its whole process tree on timeout. Returns (returncode, timed_out)."""
    kw = {}
    if IS_WIN:
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE if stdin_text is not None else None,
                         stdout=stdout, stderr=stderr, **kw)
    try:
        if stdin_text is not None:
            p.stdin.write(stdin_text.encode("utf-8"))
            p.stdin.close()
        return p.wait(timeout=seconds), False
    except subprocess.TimeoutExpired:
        kill_tree(p)
        return 124, True
    except KeyboardInterrupt:
        kill_tree(p)
        raise


def kill_tree(p):
    if IS_WIN:
        subprocess.call(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(p.pid, sig)
            except (ProcessLookupError, PermissionError):
                break
            try:
                p.wait(timeout=1)
                break
            except subprocess.TimeoutExpired:
                continue
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii=True: lone surrogates from emoji in page text would crash ensure_ascii=False
    Path(path).write_text(json.dumps(data, ensure_ascii=True, indent=1), encoding="utf-8")


def read_text(path):
    return Path(path).read_text(encoding="utf-8", errors="replace")
