"""Load the manually reviewed Bansanka A local fixture."""

import csv
from pathlib import Path

from .contracts import Assets, KaraokeResult, LyricLine, PipelineInfo


JOB_ID = "demo-bansanka-a"
ROOT = Path(__file__).resolve().parents[2]
POC = ROOT / "data" / "poc" / "bansanka"
STEMS = POC / "demucs_output" / "htdemucs" / "segment_A_0008.0-0067.0"
ASSET_PATHS = {
    "instrumental": STEMS / "no_vocals.wav",
    "original": POC / "segment_A_0008.0-0067.0.wav",
}


def load_result() -> KaraokeResult:
    source = POC / "segment_A_reference_reviewed.csv"
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    readings = (POC / "segment_A_lyrics_ko_reading.txt").read_text(encoding="utf-8").splitlines()
    if len(rows) != len(readings):
        raise ValueError("fixture lyric and Korean reading counts differ")
    lines = []
    for row, ko in zip(rows, readings):
        if row["timing_source"] != "manual_reviewed":
            raise ValueError(f"fixture line {row['line_id']} is not reviewed")
        lines.append(LyricLine(id=row["line_id"], jp=row["lyrics"], ko=ko,
                               startSec=float(row["reference_start"]),
                               endSec=float(row["reference_end"]),
                               timingSource="manual", reviewStatus="confirmed",
                               warnings=["kana_reading_not_generated"]))
    return KaraokeResult(
        jobId=JOB_ID, revision=1, title="晩餐歌 — PoC 구간 A", artist="tuki.",
        durationSec=59.0,
        assets=Assets(instrumental=f"/api/jobs/{JOB_ID}/assets/instrumental",
                      original=f"/api/jobs/{JOB_ID}/assets/original"),
        pipeline=PipelineInfo(version="poc-fixture-v1", separationModel="htdemucs-4.1.0",
                              alignmentModel="manual-reviewed-line-timing"),
        lines=lines,
    )
