#!/usr/bin/env python3
"""Local speech-to-text for one video or audio file. Nothing is uploaded.

Usage:  python scripts/transcribe.py <video_or_audio | folder from save_media.py> [--out DIR] [--model large-v3]
                                     [--prompt "..."] [--keep-media]
        python scripts/transcribe.py --prepare [--model large-v3]      (download the model only)

Engine is chosen by platform:
  macOS on Apple Silicon -> mlx-whisper (GPU)
  everything else        -> faster-whisper (NVIDIA GPU with CUDA when present, else CPU int8)
Force with --engine mlx|faster, or --device cpu|cuda for faster-whisper.

Models are stored in <repo>/models/. When Hugging Face is unreachable, the download retries
through the mirror https://hf-mirror.com (or the "hf_endpoint" set in config.json).
On a CPU-only Windows PC large-v3 is slow; try --model medium or --model small.

Writes DIR/逐字稿.md, DIR/逐字稿.srt, DIR/转录.json. Lines that look unreliable are marked 「疑」:
the transcript is a draft to check against the audio, not ground truth.

Files saved by save_media.py (listed in 保存清单.json) are deleted after a successful transcription
only when no picture was saved (--audio-only). With a picture, frames.py deletes them after the key frames.
--keep-media keeps them. Files you supplied yourself are never deleted.
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tp_common import ROOT, IS_WIN, load_config, utf8_stdio  # noqa: E402

MODELS = ROOT / "models"
MIRROR = "https://hf-mirror.com"


def pick_engine(forced=None):
    if forced:
        return {"mlx": "mlx", "faster": "faster"}[forced]
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return "mlx"
    return "faster"


def mlx_repo(name):
    if "/" in name:
        return name
    if name in ("turbo", "large-v3-turbo"):
        return "mlx-community/whisper-large-v3-turbo"
    return f"mlx-community/whisper-{name}-mlx"


def add_nvidia_dll_dirs():
    """Windows: make the CUDA libraries installed by pip (nvidia-cublas-cu12, nvidia-cudnn-cu12) findable."""
    if not IS_WIN:
        return
    import site
    bases = list(site.getsitepackages()) + [site.getusersitepackages()]
    for base in bases:
        nv = Path(base, "nvidia")
        if nv.is_dir():
            for sub in nv.glob("*/bin"):
                os.add_dll_directory(str(sub))
                os.environ["PATH"] = str(sub) + os.pathsep + os.environ.get("PATH", "")


def faster_device(forced=None):
    if forced:
        if forced == "cuda":
            add_nvidia_dll_dirs()
        return forced, ("float16" if forced == "cuda" else "int8")
    try:
        add_nvidia_dll_dirs()
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def prepare(engine, model):
    """Download the model if needed and return its local path. Runs in a child process so HF_ENDPOINT can change."""
    if Path(model).expanduser().is_dir():  # a local model folder: use as is, no download
        return str(Path(model).expanduser().resolve())
    MODELS.mkdir(parents=True, exist_ok=True)
    if engine == "mlx":
        from huggingface_hub import snapshot_download
        return snapshot_download(repo_id=mlx_repo(model), cache_dir=str(MODELS / "mlx"))
    from faster_whisper.utils import download_model
    return download_model(model, cache_dir=str(MODELS / "faster"))


def prepare_with_fallback(engine, model, cfg):
    if Path(model).expanduser().is_dir():
        return str(Path(model).expanduser().resolve())
    cmd = [sys.executable, __file__, "--prepare-only", "--engine", engine, "--model", model]
    endpoints = [os.environ.get("HF_ENDPOINT") or cfg.get("hf_endpoint") or None]
    if MIRROR not in endpoints:
        endpoints.append(MIRROR)
    for ep in endpoints:
        env = dict(os.environ)
        if ep:
            env["HF_ENDPOINT"] = ep
            print(f"模型下载源：{ep}", file=sys.stderr)
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[-1]
        print(f"模型下载失败（{ep or 'huggingface.co'}）：{r.stderr.strip()[-300:]}", file=sys.stderr)
    raise SystemExit("模型下载失败。检查网络，或在 config.json 里设 hf_endpoint 后重试。")


def extract_audio(src, wav):
    exe = shutil.which("ffmpeg")
    if not exe:
        raise SystemExit("找不到 ffmpeg。macOS：brew install ffmpeg；Windows：winget install Gyan.FFmpeg")
    r = subprocess.run([exe, "-y", "-loglevel", "error", "-nostats", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"抽音轨失败：{r.stderr.strip()[-300:]}")


def run_mlx(wav, model_path, prompt):
    import mlx_whisper
    # word_timestamps + hallucination_silence_threshold: skip the stock phrases Whisper invents over silence.
    raw = mlx_whisper.transcribe(str(wav), path_or_hf_repo=model_path, language="zh", initial_prompt=prompt,
                                 condition_on_previous_text=False, word_timestamps=True,
                                 hallucination_silence_threshold=2.0, verbose=None)
    segs = [{"start": float(s["start"]), "end": float(s["end"]), "text": str(s["text"]).strip(),
             "avg_logprob": float(s.get("avg_logprob", 0)), "no_speech_prob": float(s.get("no_speech_prob", 0))}
            for s in raw.get("segments", [])]
    return segs, {"engine": "mlx-whisper", "device": "apple-gpu", "compute_type": "float16"}


def run_faster(wav, model_path, prompt, device_forced=None):
    from faster_whisper import WhisperModel
    device, compute = faster_device(device_forced)
    try:
        model = WhisperModel(model_path, device=device, compute_type=compute)
    except Exception as e:
        if device != "cuda":
            raise
        print(f"GPU 初始化失败，改用 CPU：{str(e)[:200]}", file=sys.stderr)
        device, compute = "cpu", "int8"
        model = WhisperModel(model_path, device=device, compute_type=compute)
    it, info = model.transcribe(str(wav), language="zh", initial_prompt=prompt, vad_filter=True,
                                condition_on_previous_text=False, beam_size=5)
    segs = [{"start": float(s.start), "end": float(s.end), "text": s.text.strip(),
             "avg_logprob": float(s.avg_logprob), "no_speech_prob": float(s.no_speech_prob)} for s in it]
    return segs, {"engine": "faster-whisper", "device": device, "compute_type": compute}


# Stock phrases Whisper is known to invent over silence or music (from subtitle credits in its training data).
HALLUCINATIONS = ("请不吝点赞", "订阅 转发", "打赏支持", "明镜与点点", "字幕由", "Amara", "感谢观看", "谢谢观看", "中文字幕")


def doubtful(seg):
    t = seg["text"]
    if seg["avg_logprob"] < -1.0 or seg["no_speech_prob"] > 0.6:
        return True
    if any(h in t for h in HALLUCINATIONS):
        return True
    if seg.get("end", 0) - seg.get("start", 0) > 15 and len(t) < 40:  # a long span with little text = likely silence
        return True
    if re.search(r"(.{2,6})\1{3,}", t):  # the same short phrase repeated 4+ times = likely a loop
        return True
    return False


def ts(sec, srt=False):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}" if srt else f"{m + h * 60:02d}:{s:02d}.{ms // 100}"


MANIFEST = "保存清单.json"


def resolve_source(path):
    """A file, or a folder written by save_media.py. Returns (media file, manifest path or None).
    The manifest is returned only when the file is one that save_media.py saved."""
    if not path.exists():
        raise SystemExit(f"找不到：{path}")
    man = (path if path.is_dir() else path.parent) / MANIFEST
    if path.is_dir():
        if not man.exists():
            raise SystemExit(f"{path} 是文件夹，但里面没有 {MANIFEST}。请直接给视频或音频文件。")
        data = json.loads(man.read_text(encoding="utf-8"))
        return path / data["audio_for_transcribe"], man
    if man.exists():
        data = json.loads(man.read_text(encoding="utf-8"))
        if path.name in {f["file"] for f in data.get("files", [])}:
            return path, man
    return path, None


def delete_saved(man):
    """Delete only the files listed in the manifest, inside the manifest's folder."""
    data = json.loads(man.read_text(encoding="utf-8"))
    if not data.get("delete_after_transcribe", True):
        return []
    gone = []
    for f in data.get("files", []):
        p = man.parent / Path(f["file"]).name
        if p.exists():
            p.unlink()
            gone.append(p.name)
    data["deleted_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    man.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return gone


def write_outputs(out, src, segs, meta):
    out.mkdir(parents=True, exist_ok=True)
    srt = []
    for i, s in enumerate(segs, 1):
        srt += [str(i), f"{ts(s['start'], True)} --> {ts(s['end'], True)}", s["text"], ""]
    (out / "逐字稿.srt").write_text("\n".join(srt), encoding="utf-8")
    n_doubt = sum(doubtful(s) for s in segs)
    md = [f"# 逐字稿：{src.name}", "",
          f"引擎 {meta['engine']}（{meta['device']}，{meta['compute_type']}）｜模型 {meta['model']}｜{len(segs)} 段｜标「疑」{n_doubt} 段", "",
          "这是语音识别初稿。说话人、错字、屏幕字幕要对照原片核对；标「疑」的行优先核。", "",
          "| # | 开始 | 结束 | 台词 | 疑 |", "|---|---|---|---|---|"]
    for i, s in enumerate(segs, 1):
        md.append(f"| {i} | {ts(s['start'])} | {ts(s['end'])} | {s['text'].replace('|', '｜')} | {'疑' if doubtful(s) else ''} |")
    (out / "逐字稿.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out / "转录.json").write_text(json.dumps({**meta, "source": src.name, "segments": segs}, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    return n_doubt


def main():
    utf8_stdio()
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("--model", default=cfg["whisper_model"])
    ap.add_argument("--prompt", default=cfg["transcribe_prompt"])
    ap.add_argument("--engine", choices=["mlx", "faster"])
    ap.add_argument("--device", choices=["cpu", "cuda"])
    ap.add_argument("--keep-media", action="store_true", help="keep the files saved by save_media.py")
    ap.add_argument("--prepare", action="store_true", help="download the model and exit")
    ap.add_argument("--prepare-only", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    engine = pick_engine(a.engine)

    if a.prepare_only:
        print(prepare(engine, a.model))
        return 0
    model_path = prepare_with_fallback(engine, a.model, cfg)
    if a.prepare:
        print(f"模型就绪：{model_path}")
        return 0
    if not a.src:
        ap.error("要给视频或音频文件")
    src, manifest = resolve_source(Path(a.src).expanduser().resolve())
    out = Path(a.out).resolve() if a.out else src.parent

    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "audio.wav"
        extract_audio(src, wav)
        print(f"转录中（{engine}，模型 {a.model}）……", file=sys.stderr)
        if engine == "mlx":
            segs, meta = run_mlx(wav, model_path, a.prompt)
        else:
            segs, meta = run_faster(wav, model_path, a.prompt, a.device)
    meta["model"] = a.model
    n_doubt = write_outputs(out, src, segs, meta)
    print(f"✅ {len(segs)} 段，标「疑」{n_doubt} 段 → {out / '逐字稿.md'}")
    if manifest and json.loads(manifest.read_text(encoding="utf-8")).get("needs_frames"):
        print("保存的文件先留着：截完关键帧后由 frames.py 删除。")
    elif manifest and not a.keep_media:
        gone = delete_saved(manifest)
        if gone:
            print("已删除保存的媒体文件（要保留请加 --keep-media）：" + "、".join(gone))
    return 0


if __name__ == "__main__":
    sys.exit(main())
