"""Check rubberband timing at two known tone-burst onsets."""

import argparse
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np


RATE = 48000
BURSTS = (0.5, 2.5)


def write_input(path: Path) -> None:
    samples = np.zeros(3 * RATE, dtype=np.float64)
    length = int(0.1 * RATE)
    shape = np.sin(np.pi * np.arange(length) / length) ** 2
    pulse = .55 * np.sin(2 * np.pi * 1000 * np.arange(length) / RATE) * shape
    for onset in BURSTS:
        start = int(onset * RATE)
        samples[start:start + length] = pulse
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes((samples * 32767).astype("<i2").tobytes())


def measure(path: Path) -> tuple[float, list[float]]:
    with wave.open(str(path), "rb") as stream:
        duration = stream.getnframes() / stream.getframerate()
        audio = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(float) / 32768
    # 5 ms RMS with a threshold relative to the burst's local maximum.
    window = int(.005 * RATE)
    rms = np.sqrt(np.convolve(audio * audio, np.ones(window) / window, mode="same"))
    found = []
    for expected in BURSTS:
        lo, hi = int((expected - .1) * RATE), int((expected + .2) * RATE)
        local = rms[lo:hi]
        threshold = max(.005, float(local.max()) * .08)
        indices = np.flatnonzero(local >= threshold)
        found.append((lo + int(indices[0])) / RATE if len(indices) else float("nan"))
    return duration, found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    args = parser.parse_args()
    if not args.ffmpeg:
        parser.error("FFmpeg was not found; pass --ffmpeg with its full path")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source.wav"
        write_input(source)
        baseline_duration, baseline = measure(source)
        print("semitones,duration_sec,onset1_error_ms,onset2_error_ms")
        for shift in (-5, 0, 5):
            target = root / f"shift_{shift}.wav"
            ratio = 2 ** (shift / 12)
            subprocess.run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                            "-af", f"rubberband=pitch={ratio:.12f}:tempo=1", "-c:a", "pcm_s16le", str(target)], check=True)
            duration, found = measure(target)
            print(f"{shift},{duration:.6f},{(found[0] - baseline[0]) * 1000:.1f},"
                  f"{(found[1] - baseline[1]) * 1000:.1f}")
        assert baseline_duration == 3.0


if __name__ == "__main__":
    main()
