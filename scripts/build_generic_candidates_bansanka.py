"""One-off: produce the same 'whole' / 'asr' automatic candidates for Bansanka A
that build_review_generic.py produces for the other two songs, so all three
songs can be compared under one identical automatic method for the T01 gate.

Bansanka predates the generic script and has a slightly different manifest
shape (no reading_file, demucs/asr already computed), so this reuses the
shared functions directly instead of forcing manifest compatibility.
"""

import json
import time
from pathlib import Path

import whisperx
from build_review_generic import align, asr_groups

root = Path("data/poc/bansanka")
lines = (root / "segment_A_lyrics_ja.txt").read_text(encoding="utf-8").splitlines()
asr = json.loads((root / "asr_small_vocals.json").read_text(encoding="utf-8"))["segments"]
vocals = root / "demucs_output/htdemucs/segment_A_0008.0-0067.0/vocals.wav"
dur = 59.0

model, meta = whisperx.load_align_model(language_code="ja", device="cpu")
for name, groups in [("whole", [(0, len(lines), 0.0, dur)]), ("asr", asr_groups(lines, asr, dur))]:
    started = time.perf_counter()
    rows = align(lines, groups, vocals, model, meta, "A")
    (root / f"alignment_whisperx_{name}.json").write_text(json.dumps(
        {"model": "jonatasgrosman/wav2vec2-large-xlsr-53-japanese",
         "method": f"WhisperX sequential char alignment, {name} windows (generic method, for T01 cross-song comparison)",
         "groups": groups, "elapsedSec": round(time.perf_counter() - started, 2), "lines": rows},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(name, "groups:", [(a, b, round(s, 2), round(e, 2)) for a, b, s, e in groups])
