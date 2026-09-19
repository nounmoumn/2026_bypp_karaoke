"""Transcribe one bounded vocal window to inspect omitted lyric repetitions."""

import argparse
import json

import whisperx
from faster_whisper import WhisperModel


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("start", type=float)
    ap.add_argument("end", type=float)
    ap.add_argument("--model", default="small")
    args = ap.parse_args()
    audio = whisperx.load_audio(args.audio)
    clip = audio[int(args.start * 16000):int(args.end * 16000)]
    model = WhisperModel(args.model, device="cuda", compute_type="float16")
    segments, info = model.transcribe(clip, language="ja", beam_size=5, vad_filter=False,
                                      condition_on_previous_text=False)
    rows = [{"start": round(args.start + s.start, 2), "end": round(args.start + s.end, 2),
             "text": s.text.strip(), "avg_logprob": round(s.avg_logprob, 3)} for s in segments]
    print(json.dumps({"language": info.language, "segments": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
