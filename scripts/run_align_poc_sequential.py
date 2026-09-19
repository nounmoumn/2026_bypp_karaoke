"""Align lyric groups once, then split ordered character times into lines.

This prevents two neighboring lines from independently claiming the same audio.
ASR group windows are still provisional and require listening against the song.
"""

import argparse
import csv
import json
import time
from pathlib import Path

import whisperx

from run_align_poc import AUDIO, GROUP_ASR, GROUP_LINES, LYRICS, ROOT


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window-source", choices=("asr", "musicxml"), default="asr")
    args = parser.parse_args()
    output_path = (ROOT / "alignment_whisperx_sequential.json" if args.window_source == "asr"
                   else ROOT / "alignment_whisperx_sequential_musicxml.json")
    lines = LYRICS.read_text(encoding="utf-8").splitlines()
    asr = json.loads((ROOT / "asr_small_vocals.json").read_text(encoding="utf-8"))["segments"]
    candidates = list(csv.DictReader((ROOT / "segment_A_reference_DRAFT.csv").open(encoding="utf-8-sig", newline="")))
    groups = []
    transcript = []
    for (first, stop), (asr_first, asr_stop) in zip(GROUP_LINES, GROUP_ASR):
        if args.window_source == "asr":
            start = max(0.0, asr[asr_first]["startSec"] - 0.25)
            end = min(59.0, asr[asr_stop - 1]["endSec"] + 0.25)
        else:
            start = max(0.0, float(candidates[first]["cand_musicxml_abs_start"]) - 8.0 - 0.8)
            end = min(59.0, float(candidates[stop - 1]["cand_musicxml_abs_end"]) - 8.0 + 0.8)
        text = "".join(lines[first:stop])
        transcript.append({"start": start, "end": end, "text": text})
        groups.append((first, stop))

    started = time.perf_counter()
    model, metadata = whisperx.load_align_model(language_code="ja", device="cpu")
    aligned = whisperx.align(transcript, model, metadata, str(AUDIO), "cpu",
                             return_char_alignments=True)
    output = []
    for (first, stop), source, segment in zip(groups, transcript, aligned["segments"]):
        chars = segment.get("chars", [])
        if len(chars) != len(source["text"]):
            raise ValueError(f"Character mapping mismatch in group {first}:{stop}: "
                             f"{len(chars)} versus {len(source['text'])}")
        offset = 0
        for index in range(first, stop):
            line_chars = chars[offset: offset + len(lines[index])]
            offset += len(lines[index])
            timed = [item for item in line_chars if "start" in item and "end" in item]
            output.append({"lineId": f"A{index:02d}", "jp": lines[index],
                           "startSec": min((c["start"] for c in timed), default=None),
                           "endSec": max((c["end"] for c in timed), default=None),
                           "windowStartSec": source["start"],
                           "windowEndSec": source["end"],
                           "timedChars": len(timed), "totalChars": len(line_chars)})
    output_path.write_text(json.dumps({"model": "jonatasgrosman/wav2vec2-large-xlsr-53-japanese",
                                  "method": f"WhisperX grouped text alignment in {args.window_source} windows",
                                  "elapsedSec": round(time.perf_counter() - started, 2),
                                  "lines": output}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(output)} sequential line candidates to {output_path}")


if __name__ == "__main__":
    main()
