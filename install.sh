#!/bin/bash
# topic-proof-comment-engine 一键安装（macOS）。可重复运行，已装的会跳过。
# 用法：在仓库目录里运行  bash install.sh
set -euo pipefail
cd "$(dirname "$0")"
say() { printf '\n== %s\n' "$1"; }

say "1/4 系统工具"
if ! command -v brew >/dev/null 2>&1; then
  echo "没有 Homebrew。请先按 https://brew.sh 的说明安装，再重跑本脚本。"; exit 1
fi
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then echo "安装 Python 3.12 …"; brew install python@3.12; PY=python3.12; fi
echo "Python：$($PY --version)"
command -v ffmpeg >/dev/null 2>&1 || { echo "安装 ffmpeg …"; brew install ffmpeg; }
echo "ffmpeg：已就绪"

say "2/4 Python 环境（.venv）与依赖"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip -q
.venv/bin/python -m pip install -r requirements.txt

say "3/4 下载转录模型（约 3 GB，中断后重跑可续传）"
.venv/bin/python scripts/transcribe.py --prepare

say "4/4 自检"
.venv/bin/python scripts/check_env.py || true

cat <<'TXT'

还要你自己做 2 件事（agent 做不了）：
  1. 安装 ego lite 浏览器并完成首次引导：见 docs/安装.md 第三节。
  2. 在 ego lite 里打开 https://www.douyin.com ，扫码登录。

之后在本目录打开 Claude Code 或 Codex，说：「验证这条：<抖音视频链接>」。
命令里的 python 指 .venv/bin/python。
TXT
