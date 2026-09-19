"""Preliminary line alignment on Bansanka A using ASR group windows.

The window mapping is manually assigned from rough ASR groups. It is not a
reference annotation or an accuracy measurement.
"""

import json
import time
from pathlib import Path

import whisperx


ROOT = Path("data/poc/bansanka")
AUDIO = ROOT / "demucs_output/htdemucs/segment_A_0008.0-0067.0/vocals.wav"
LYRICS = ROOT / "segment_A_lyrics_ja.txt"
OUTPUT = ROOT / "alignment_whisperx_preliminary.json"

# Index ranges of lyric lines corresponding to each rough ASR segment.
GROUP_LINES = [(0, 2), (2, 4), (4, 6), (6, 8), (8, 9), (9, 11),
               (11, 13), (13, 15), (15, 16), (16, 18)]
GROUP_ASR = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6),
             (6, 7), (7, 8), (8, 9), (9, 11)]


def main() -> None:
    lines = LYRICS.read_text(encoding="utf-8").splitlines()
    asr = json.loads((ROOT / "asr_small_vocals.json").read_text(encoding="utf-8"))["segments"]
    assert len(lines) == 18 and len(asr) == 11
    transcript = []
    for (line_start, line_end), (asr_start, asr_end) in zip(GROUP_LINES, GROUP_ASR):
        start = max(0.0, asr[asr_start]["startSec"] - 0.25)
        end = min(59.0, asr[asr_end - 1]["endSec"] + 0.25)
        for line in lines[line_start:line_end]:
            transcript.append({"start": start, "end": end, "text": line})

    started = time.perf_counter()
    model, metadata = whisperx.load_align_model(language_code="ja", device="cpu")
    result = whisperx.align(transcript, model, metadata, str(AUDIO), "cpu",
                            return_char_alignments=True)
    rows = []
    for index, segment in enumerate(result["segments"]):
        rows.append({"lineId": f"A{index:02d}", "jp": lines[index],
                     "windowStartSec": transcript[index]["start"],
                     "windowEndSec": transcript[index]["end"],
                     "startSec": segment.get("start"), "endSec": segment.get("end"),
                     "chars": segment.get("chars", [])})
    OUTPUT.write_text(json.dumps({"model": "jonatasgrosman/wav2vec2-large-xlsr-53-japanese",
                                  "method": "WhisperX forced alignment in ASR group windows",
                                  "elapsedSec": round(time.perf_counter() - started, 2),
                                  "lines": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(rows)} preliminary aligned lines to {OUTPUT}")


if __name__ == "__main__":
    main()
