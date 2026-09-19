"""Process one YouTube URL or local song on a Runpod GPU, retrieve the page.

Requires local yt-dlp + FFmpeg and a provisioned Pod with scripts/requirements-pipeline.txt.
The local download avoids YouTube's bot challenge on some datacenter IPs.
"""

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path


SCRIPT_NAMES = (
    "process_song.py",
    "align_full_song.py",
    "repair_orphans.py",
    "repeat_detection.py",
    "readings.py",
    "pitch_guide.py",
    "karaoke_template.html",
)


def run(args: list[str]) -> None:
    print("+", " ".join(shlex.quote(str(x)) for x in args), flush=True)
    subprocess.run(args, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="one YouTube video URL")
    source.add_argument("--audio", type=Path, help="existing local audio file")
    ap.add_argument("--lyrics", type=Path, required=True, help="UTF-8 Japanese lyrics file")
    ap.add_argument("--readings", type=Path, help="optional UTF-8 Korean readings, one per lyric line")
    ap.add_argument("--repeat-overrides", type=Path, help="optional JSON map of 0-based lyric line index to sung repeat count")
    ap.add_argument("--out", type=Path, required=True, help="local result directory; folder name is the song ID")
    ap.add_argument("--host", required=True, help="Runpod Direct TCP SSH host or IP")
    ap.add_argument("--port", type=int, required=True, help="Runpod Direct TCP SSH port")
    ap.add_argument("--key", type=Path, default=Path.home() / ".ssh" / "id_ed25519")
    ap.add_argument("--remote-root", default="/root/bypp")
    ap.add_argument("--remote-python", default="/root/bypp-venv/bin/python")
    ap.add_argument("--title")
    ap.add_argument("--language", choices=("auto", "ja", "ko"), default="auto")
    ap.add_argument("--full-key-range", action="store_true",
                    help="render all 13 key-shift semitones instead of just the male/female preset")
    args = ap.parse_args()

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    song_id = out.name
    if not song_id or not all(c.isalnum() or c in "-_" for c in song_id):
        ap.error("--out folder name must contain only letters, numbers, - or _")
    for input_path in (args.audio, args.lyrics, args.readings, args.repeat_overrides, args.key):
        if input_path is not None and not input_path.is_file():
            ap.error(f"file not found: {input_path}")
    if shutil.which("ffmpeg") is None:
        ap.error("FFmpeg must be installed locally")

    stage_times = {}
    started = time.perf_counter()
    source_id = out / "source_id.txt"
    if args.url:
        identity = "url:" + args.url
        audio = out / "original.mp3"
    else:
        with args.audio.open("rb") as source_file:
            digest = hashlib.file_digest(source_file, "sha256").hexdigest()
        identity = "sha256:" + digest
        audio = out / ("original" + args.audio.suffix.lower())
    if source_id.exists() and source_id.read_text(encoding="utf-8").strip() != identity:
        ap.error("this output directory already belongs to a different audio source")
    legacy_url = out / "source_url.txt"
    if args.url and legacy_url.exists() and legacy_url.read_text(encoding="utf-8").strip() != args.url:
        ap.error("this output directory already belongs to a different URL")
    if args.url and not audio.exists():
        run([sys.executable, "-m", "yt_dlp", "--no-playlist", "-x", "--audio-format", "mp3",
             "-o", str(out / "original.%(ext)s"), args.url])
    if args.audio and not audio.exists():
        shutil.copyfile(args.audio, audio)
    if not audio.is_file():
        raise RuntimeError(f"download did not produce {audio}")
    source_id.write_text(identity + "\n", encoding="utf-8")
    stage_times["prepareInputSec"] = round(time.perf_counter() - started, 1)

    lyrics = out / "lyrics.txt"
    if args.lyrics.resolve() != lyrics:
        shutil.copyfile(args.lyrics, lyrics)
    readings = out / "readings.txt" if args.readings else None
    if args.readings and args.readings.resolve() != readings:
        shutil.copyfile(args.readings, readings)
    repeat_overrides = out / "repeat_overrides.json" if args.repeat_overrides else None
    if args.repeat_overrides and args.repeat_overrides.resolve() != repeat_overrides:
        shutil.copyfile(args.repeat_overrides, repeat_overrides)

    target = f"root@{args.host}"
    # SSH connection reuse (ControlMaster) was tried here to cut the ~3.8s handshake this
    # Pod's SSH endpoint takes per call (this run makes 5+ calls) -- it fails immediately
    # ("Connection reset by peer") even with a plain path, on both a Windows OpenSSH client
    # and a bare /tmp ControlPath, so the endpoint itself does not allow multiplexed
    # sessions on one connection. Not attempted further; each call pays the handshake.
    ssh_common = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
                  "-i", str(args.key.resolve())]
    ssh = ["ssh", *ssh_common, "-p", str(args.port), target]
    scp = ["scp", *ssh_common, "-P", str(args.port)]
    remote_input = f"{args.remote_root}/input/{song_id}"
    remote_output = f"{args.remote_root}/output/{song_id}"
    remote_scripts = f"{args.remote_root}/scripts"
    run([*ssh, "mkdir -p " + " ".join(map(shlex.quote, (remote_input, remote_output, remote_scripts)))])

    script_dir = Path(__file__).resolve().parent
    run([*scp, *(str(script_dir / name) for name in SCRIPT_NAMES), f"{target}:{remote_scripts}/"])
    upload = [audio, lyrics] + ([readings] if readings else []) + ([repeat_overrides] if repeat_overrides else [])
    run([*scp, *(str(path) for path in upload), f"{target}:{remote_input}/"])
    stage_times["uploadSec"] = round(time.perf_counter() - started - stage_times["prepareInputSec"], 1)

    command = [args.remote_python, f"{remote_scripts}/process_song.py",
               "--audio", f"{remote_input}/{audio.name}", "--lyrics", f"{remote_input}/lyrics.txt",
               "--out", remote_output, "--title", args.title or song_id, "--device", "cuda",
               "--language", args.language]
    if args.full_key_range:
        command.append("--full-key-range")
    if readings:
        command += ["--readings", f"{remote_input}/readings.txt"]
    if repeat_overrides:
        command += ["--repeat-overrides", f"{remote_input}/repeat_overrides.json"]
    run([*ssh, "HF_HUB_ENABLE_HF_TRANSFER=0 " + shlex.join(command)])
    stage_times["gpuProcessSec"] = round(time.perf_counter() - started - sum(stage_times.values()), 1)

    results = ["karaoke.json", "karaoke.html", "quality_flags.json", "assets.json"]
    if not (out / "mr.wav").exists():
        results.append("mr.wav")
    run([*scp, *(f"{target}:{remote_output}/{name}" for name in results), str(out)])

    assets = json.loads((out / "assets.json").read_text(encoding="utf-8"))
    extra = [s["file"] for s in assets.get("mrShifts", []) if s["file"] != "mr.wav" and not (out / s["file"]).exists()]
    if assets.get("hasPitchGuide") and not (out / "pitch_guide.json").exists():
        extra.append("pitch_guide.json")
    if extra:
        run([*scp, *(f"{target}:{remote_output}/{name}" for name in extra), str(out)])
    stage_times["downloadResultSec"] = round(time.perf_counter() - started - sum(stage_times.values()), 1)
    stage_times["totalSec"] = round(time.perf_counter() - started, 1)
    (out / "pipeline_timing.json").write_text(json.dumps(stage_times, indent=2), encoding="utf-8")
    data = json.loads((out / "karaoke.json").read_text(encoding="utf-8"))
    lines = data["lines"]
    starts = [line["start"] for line in lines]
    backwards = sum(b < a for a, b in zip(starts, starts[1:]) if a is not None and b is not None)
    print(f"RESULT {out / 'karaoke.html'}: {len(lines)} lines, device={data.get('device')}, "
          f"unaligned={sum(start is None for start in starts)}, backwards={backwards}, "
          f"quality_flags={len(data.get('qualityFlags', []))}")
    print("TIMING", stage_times)


if __name__ == "__main__":
    main()
