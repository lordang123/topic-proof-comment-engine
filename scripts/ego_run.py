#!/usr/bin/env python3
"""Run one ego-browser script safely. The only entry point for every browser script in this repo.

Usage:  python scripts/ego_run.py <script.js> [timeout_seconds=180] [output_file]

What it does, every time:
  1. Takes a machine-wide lock, so only one ego task reads Douyin at a time (no parallel access).
  2. Uses a fresh task space named tp-<time>-<pid>. It never reuses or claims a space the user owns.
  3. Refuses scripts that call claimTaskSpace / takeOverTaskSpace.
  4. Runs the script with a hard timeout, then closes this space's tabs and finishes the space.

ego-browser prints the script's console.log on stderr. With an output file, that stream goes to the file.

Exit codes: script's own code; 2 bad script; 75 lock not acquired in time;
            76 the user took over the space during the run (rerun is fine); 124 timeout; 127 ego-browser missing.
"""
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tp_common import JS_DIR, IS_WIN, run_with_timeout, utf8_stdio  # noqa: E402

LOCK = Path(tempfile.gettempdir()) / "topic-proof-ego.lock"
LOCK_WAIT_S = 1800


def log(msg):
    print(f"[ego_run {datetime.now():%H:%M:%S}] {msg}", file=sys.stderr, flush=True)


class GlobalLock:
    """Cross-platform exclusive lock on a file. Released automatically if the process dies."""

    def __enter__(self):
        self.fh = open(LOCK, "a+")
        start = last = time.monotonic()
        while True:
            try:
                if IS_WIN:
                    import msvcrt
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() - start > LOCK_WAIT_S:
                    raise TimeoutError
                if time.monotonic() - last >= 60 or last == start:
                    log("另一个 ego 任务在跑，排队等待（同一时间只开一个抖音页面）")
                    last = time.monotonic() + 0.001
                time.sleep(1)

    def __exit__(self, *exc):
        try:
            if IS_WIN:
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()


def ego_exe():
    exe = shutil.which("ego-browser")
    if not exe:
        home_bin = Path.home() / ".local" / "bin" / ("ego-browser.exe" if IS_WIN else "ego-browser")
        if home_bin.exists():
            exe = str(home_bin)
    return exe


def run_snippet(exe, js_text, seconds, out_path=None):
    """Feed js_text to `ego-browser nodejs`. Returns (rc, captured_text)."""
    with tempfile.TemporaryDirectory() as td:
        cap = Path(td) / "out.txt"
        with open(out_path or cap, "w", encoding="utf-8", errors="replace") as fh:
            rc, timed_out = run_with_timeout([exe, "nodejs"], seconds, stdin_text=js_text, stdout=fh, stderr=fh)
        text = Path(out_path or cap).read_text(encoding="utf-8", errors="replace")
    if timed_out:
        log(f"超过 {seconds} 秒，已终止脚本进程")
    return rc, text


def cleanup(exe, space, mode):
    """mode 'only': close this space and finish it. mode 'sweep': clean leftover tp-* spaces owned by the agent."""
    js = (JS_DIR / "cleanup.js").read_text(encoding="utf-8")
    js = js.replace("__MODE__", mode).replace("__SPACE__", space)
    _, text = run_snippet(exe, js, 60)
    return text


def run_js(script_text, seconds=180, out_path=None):
    if "claimTaskSpace" in script_text or "takeOverTaskSpace" in script_text:
        log("拒收：脚本里有 claimTaskSpace / takeOverTaskSpace。本入口每次给新空间，不抢用户的空间。")
        return 2
    exe = ego_exe()
    if not exe:
        log("找不到 ego-browser 命令。先安装 ego lite 并完成首次引导，见 docs/安装.md")
        return 127
    try:
        with GlobalLock():
            space = f"tp-{datetime.now():%y%m%d%H%M%S}-{os.getpid()}"
            log(f"领到空间 {space}")
            sweep = cleanup(exe, space, "sweep")
            for line in sweep.splitlines():
                if line.startswith(("SWEPT", "SWEEP")):
                    log("清残留：" + line.strip())
            wrapped = "{\nconst EGO_SPACE = '" + space + "';\n" + script_text + "\n}\n"
            rc, _ = run_snippet(exe, wrapped, seconds, out_path)
            if out_path:
                n = sum(1 for _ in open(out_path, encoding="utf-8", errors="replace"))
                log(f"脚本输出 {n} 行 → {out_path}")
            log(f"脚本退出码 {rc}")
            done = cleanup(exe, space, "only")
            if "USER_OWNED" in done:
                log(f"你在运行中接管了空间 {space}。空间和标签留给你，不动。下次运行会用新空间。")
                return 76
            return 124 if rc == 124 else rc
    except TimeoutError:
        log(f"等了 {LOCK_WAIT_S // 60} 分钟仍有其他 ego 任务在跑，放弃本次")
        return 75


def main():
    utf8_stdio()
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    script = Path(sys.argv[1]).read_text(encoding="utf-8")
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 180
    out = sys.argv[3] if len(sys.argv) > 3 else None
    return run_js(script, seconds, out)


if __name__ == "__main__":
    sys.exit(main())
