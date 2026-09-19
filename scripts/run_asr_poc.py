"""Run rough Japanese ASR on a PoC vocal stem; output is not lyric alignment."""

import argparse
import json
import time
from pathlib import Path

from faster_whisper import WhisperModel


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", default="small")
    args = parser.parse_args()

    started = time.perf_counter()
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(args.audio), language="ja", beam_size=5, vad_filter=False)
    rows = [
        {"startSec": segment.start, "endSec": segment.end, "text": segment.text}
        for segment in segments
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"model": args.model, "language": info.language,
                    "elapsedSec": round(time.perf_counter() - started, 2),
                    "segments": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved {len(rows)} rough ASR segments to {args.output}")


if __name__ == "__main__":
    main()
