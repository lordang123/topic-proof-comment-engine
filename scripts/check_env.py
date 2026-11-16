#!/usr/bin/env python3
"""Self-check. Lists what is missing and the command that fixes it. Exit 0 = ready to run.

Usage:  python scripts/check_env.py
"""
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tp_common import ROOT, IS_WIN, utf8_stdio  # noqa: E402
from transcribe import MODELS, pick_engine, mlx_repo  # noqa: E402
import ego_run  # noqa: E402

MAC = sys.platform == "darwin"


def fix(mac, win):
    return mac if MAC else win


def main():
    utf8_stdio()
    bad = 0

    def row(ok, name, hint="", optional=False):
        nonlocal bad
        tag = "[ OK ]" if ok else ("[可选]" if optional else "[缺少]")
        print(f"{tag} {name}" + ("" if ok else f"  → {hint}"))
        if not ok and not optional:
            bad += 1

    print("== 系统")
    row(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}（要 3.10 或更新）",
        fix("brew install python@3.12", "winget install Python.Python.3.12"))
    row(bool(shutil.which("ffmpeg")), "ffmpeg（抽音轨）", fix("brew install ffmpeg", "winget install Gyan.FFmpeg，然后重开终端"))
    row(bool(shutil.which("ffprobe")), "ffprobe（校验保存的文件）", "随 ffmpeg 一起装")

    print("== 浏览器")
    exe = ego_run.ego_exe()
    row(bool(exe), "ego-browser 命令", "安装 ego lite 并完成首次引导，见 docs/安装.md 第三节")
    if exe:
        try:
            r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
            print(f"       版本：{((r.stdout or r.stderr).strip().splitlines() or [""])[0][:60]}")
        except (subprocess.SubprocessError, OSError):
            pass
        print("       抖音登录状态本脚本不检查：在 ego lite 里打开 douyin.com，确认右上角是你的头像。")

    print("== 转录")
    engine = pick_engine()
    print(f"       本机引擎：{'mlx-whisper（Apple 芯片 GPU）' if engine == 'mlx' else 'faster-whisper'}")
    pip = f'"{sys.executable}" -m pip install -r requirements.txt'
    if engine == "mlx":
        row(importlib.util.find_spec("mlx_whisper") is not None, "mlx-whisper", pip)
    else:
        ok = importlib.util.find_spec("faster_whisper") is not None
        row(ok, "faster-whisper", pip)
        if ok:
            from transcribe import faster_device
            dev, comp = faster_device()
            print(f"       设备：{dev}（{comp}）" + ("" if dev == "cuda" else "。没有可用的 NVIDIA 显卡，用 CPU，较慢。"))
            if IS_WIN and shutil.which("nvidia-smi") and dev != "cuda":
                print(f'       有 NVIDIA 显卡但没启用：运行 "{sys.executable}" -m pip install -r requirements-gpu.txt')
    row(importlib.util.find_spec("huggingface_hub") is not None, "huggingface_hub（下载模型）", pip)
    sub = MODELS / ("mlx" if engine == "mlx" else "faster")
    patterns = ("*.safetensors", "weights.npz") if engine == "mlx" else ("model.bin",)
    has_model = any(p.is_file() for pattern in patterns for p in sub.rglob(pattern))
    row(has_model, "转录模型已下载", f'"{sys.executable}" scripts/transcribe.py --prepare（约 3 GB）')

    print("== 仓库")
    cfg = ROOT / "config.json"
    print(f"       配置：{'config.json' if cfg.exists() else '默认值（要改就复制 config.example.json 为 config.json）'}")
    for p in [".claude/skills/选题验证/SKILL.md", ".agents/skills/选题验证/SKILL.md"]:
        row((ROOT / p).exists(), p, "仓库不完整，重新下载")

    print("\n" + ("全部通过，可以开始。" if not bad else f"{bad} 项要处理。"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
