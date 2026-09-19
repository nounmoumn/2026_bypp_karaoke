"""Plot vocal energy and reviewed line boundaries for sync inspection."""

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf


ROOT = Path("data/poc/bansanka")
VOCALS = ROOT / "demucs_output/htdemucs/segment_A_0008.0-0067.0/vocals.wav"
REFERENCE = ROOT / "segment_A_reference_reviewed.csv"
OUTPUT = ROOT / "sync_diagnostic.png"


def main() -> None:
    audio, rate = sf.read(VOCALS, dtype="float32", always_2d=True)
    width = round(rate * 0.02)
    audio = audio[: len(audio) // width * width]
    rms = np.sqrt(np.mean(audio.reshape(-1, width, 2) ** 2, axis=(1, 2)))
    times = np.arange(len(rms)) * width / rate
    with REFERENCE.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))

    figure, axes = plt.subplots(4, 1, figsize=(16, 10), sharey=True, layout="constrained")
    for axis, (left, right) in zip(axes, [(0, 15), (15, 30), (30, 45), (45, 59)]):
        axis.plot(times, rms, color="#435b85", linewidth=0.8)
        axis.set_xlim(left, right)
        axis.set_ylabel("Vocal RMS")
        axis.grid(alpha=0.2)
        for row in rows:
            start, end = float(row["reference_start"]), float(row["reference_end"])
            if end < left or start > right:
                continue
            axis.axvspan(start, end, color="#f1ba67", alpha=0.16)
            axis.axvline(start, color="#268568", linewidth=0.8)
            axis.axvline(end, color="#ae645f", linewidth=0.8)
            axis.text(max(left, start), axis.get_ylim()[1] * 0.85, row["line_id"], fontsize=8)
        axis.set_xlabel("Seconds from 59s segment start")
    figure.suptitle("Bansanka A: reviewed line bounds vs separated vocal energy")
    figure.savefig(OUTPUT, dpi=150)
    print(OUTPUT)


if __name__ == "__main__":
    main()
