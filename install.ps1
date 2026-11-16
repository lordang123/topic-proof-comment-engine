# topic-proof-comment-engine 一键安装（Windows 10/11）。可重复运行，已装的会跳过。
# 用法：在仓库文件夹的地址栏输入 powershell 回车，然后粘贴：
#   Set-ExecutionPolicy -Scope Process Bypass -Force; .\install.ps1
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
Set-Location $PSScriptRoot
function Say($m) { Write-Host "`n== $m" -ForegroundColor Cyan }
function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Need($cmd, $id) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
    Write-Host "安装 $id …"
    winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements
    Refresh-Path
  } else { Write-Host "已有 $cmd" }
}

Say "1/5 系统工具（winget）"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
  throw "没有 winget。请在 Microsoft Store 安装「应用安装程序」后重试。"
}
function Rest($a) { if ($a.Length -gt 1) { $a[1..($a.Length - 1)] } else { @() } }
$Py = $null
foreach ($c in @(@("py", "-3.12"), @("py", "-3.11"), @("py", "-3.13"), @("python"))) {
  if (Get-Command $c[0] -ErrorAction SilentlyContinue) {
    $r = @(Rest $c)
    & $c[0] @r -c "import sys; sys.exit(sys.version_info < (3, 10))" 2>$null
    if ($LASTEXITCODE -eq 0) { $Py = $c; break }
  }
}
if (-not $Py) {
  Need "python" "Python.Python.3.12"
  Refresh-Path
  $Py = @("py", "-3.12")
}
Need "ffmpeg" "Gyan.FFmpeg"
Refresh-Path

Say "2/5 Python 环境（.venv）与依赖"
if (-not (Test-Path .venv)) { $r = @(Rest $Py); & $Py[0] @r -m venv .venv }
$VPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $VPy -m pip install --upgrade pip -q
& $VPy -m pip install -r requirements.txt

Say "3/5 显卡"
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
  Write-Host "检测到 NVIDIA 显卡，安装 CUDA 运行库（约 1 GB）…"
  & $VPy -m pip install -r requirements-gpu.txt
} else {
  Write-Host "没检测到 NVIDIA 显卡驱动。转录将用 CPU，较慢。有 N 卡请先装驱动再重跑本脚本。"
}

Say "4/5 下载转录模型（约 3 GB，中断后重跑可续传）"
& $VPy scripts\transcribe.py --prepare

Say "5/5 自检"
& $VPy scripts\check_env.py

Write-Host @"

还要你自己做 2 件事（agent 做不了）：
  1. 安装 ego lite 浏览器并完成首次引导：见 docs\安装.md 第三节。
  2. 在 ego lite 里打开 https://www.douyin.com ，扫码登录。

之后在本文件夹打开 Claude Code 或 Codex，说：「验证这条：<抖音视频链接>」。
命令里的 python 指 .venv\Scripts\python.exe。
"@
