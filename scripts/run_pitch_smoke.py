"""Measure FFmpeg rubberband pitch and duration on a generated 440 Hz tone."""

import argparse
import math
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np


def write_tone(path: Path, seconds: float = 3.0, rate: int = 48000) -> None:
    samples = (0.3 * np.sin(2 * np.pi * 440 * np.arange(int(seconds * rate)) / rate))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes((samples * 32767).astype("<i2").tobytes())


def measure(path: Path) -> tuple[float, float]:
    with wave.open(str(path), "rb") as source:
        rate = source.getframerate()
        frames = source.getnframes()
        signal = np.frombuffer(source.readframes(frames), dtype="<i2").astype(float)
    middle = signal[rate : 2 * rate]
    spectrum = np.abs(np.fft.rfft(middle * np.hanning(len(middle))))
    frequency = np.fft.rfftfreq(len(middle), 1 / rate)[np.argmax(spectrum)]
    return frames / rate, frequency


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    args = parser.parse_args()
    if not args.ffmpeg:
        parser.error("FFmpeg was not found; pass --ffmpeg with its full path")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        original = root / "original.wav"
        write_tone(original)
        print("semitones,expected_hz,measured_hz,duration_sec,frequency_error_hz,duration_error_ms")
        for semitones in (-5, 0, 5):
            output = root / f"shift_{semitones}.wav"
            ratio = 2 ** (semitones / 12)
            subprocess.run(
                [args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(original),
                 "-af", f"rubberband=pitch={ratio:.12f}:tempo=1", "-c:a", "pcm_s16le", str(output)],
                check=True,
            )
            duration, frequency = measure(output)
            expected = 440 * ratio
            print(f"{semitones},{expected:.3f},{frequency:.3f},{duration:.6f},"
                  f"{frequency - expected:.3f},{(duration - 3.0) * 1000:.1f}")


if __name__ == "__main__":
    main()
