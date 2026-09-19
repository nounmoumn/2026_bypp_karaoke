"""Render a real MR at ±5 semitones and measure envelope timing drift."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


def envelope(path: Path, bin_ms: int = 10) -> tuple[float, np.ndarray]:
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    bin_size = int(rate * bin_ms / 1000)
    audio = audio[: len(audio) // bin_size * bin_size]
    power = np.mean(audio.reshape(-1, bin_size, audio.shape[1]) ** 2, axis=(1, 2))
    return len(audio) / rate, np.sqrt(power)


def best_lag(reference: np.ndarray, target: np.ndarray, start: int, stop: int,
             max_lag_bins: int = 20) -> tuple[int, float]:
    first = reference[start:stop]
    best = (0, -1.0)
    for lag in range(-max_lag_bins, max_lag_bins + 1):
        shifted = target[start + lag:stop + lag]
        if len(shifted) != len(first):
            continue
        a, b = first - first.mean(), shifted - shifted.mean()
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        corr = float(np.dot(a, b) / denom) if denom else 0.0
        if corr > best[1]:
            best = (lag, corr)
    return best


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    args = parser.parse_args()
    if not args.ffmpeg:
        parser.error("FFmpeg was not found; pass --ffmpeg")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    base_duration, base = envelope(args.source)
    report = {"sourceDurationSec": base_duration, "renders": []}
    for semitones in (-5, 5):
        output = args.output_dir / f"mr_shift_{semitones:+d}.wav"
        ratio = 2 ** (semitones / 12)
        subprocess.run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(args.source),
                        "-af", f"rubberband=pitch={ratio:.12f}:tempo=1", "-c:a", "pcm_s16le", str(output)], check=True)
        duration, shifted = envelope(output)
        windows = []
        for start_sec in (1, 25, 48):
            lag, corr = best_lag(base, shifted, start_sec * 100, (start_sec + 8) * 100)
            windows.append({"startSec": start_sec, "lagMs": lag * 10,
                            "envelopeCorrelation": round(corr, 3)})
        report["renders"].append({"semitones": semitones, "durationSec": duration,
                                  "durationErrorMs": round((duration - base_duration) * 1000, 3),
                                  "windows": windows, "asset": str(output)})
    path = args.output_dir / "pitch_real_measurements.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
