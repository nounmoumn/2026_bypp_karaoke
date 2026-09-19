"""Inspect CTC evidence for 1..N repetitions of a short refrain in an audio window."""

import argparse
import json
import math

import torch
import whisperx
from whisperx.alignment import get_trellis


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("text")
    ap.add_argument("start", type=float)
    ap.add_argument("end", type=float)
    ap.add_argument("--max-repeat", type=int, default=6)
    args = ap.parse_args()

    audio = whisperx.load_audio(args.audio)
    model, meta = whisperx.load_align_model(language_code="ja", device="cuda")
    vocab = meta["dictionary"]
    blank = vocab.get("<pad>", vocab.get("[pad]", 0))
    with torch.inference_mode():
        segment = torch.from_numpy(audio[int(args.start * 16000):int(args.end * 16000)]).unsqueeze(0).to("cuda")
        emission = model(segment).logits.log_softmax(dim=-1)[0].cpu()
    rows = []
    for n in range(1, args.max_repeat + 1):
        text = args.text * n
        tokens = [vocab.get(c.lower()) for c in text]
        if any(t is None for t in tokens):
            raise ValueError(f"unsupported text: {text}")
        score = float(get_trellis(emission, tokens, blank)[-1, -1])
        result = whisperx.align([{"start": args.start, "end": args.end, "text": text}],
                                model, meta, audio, "cuda", return_char_alignments=True)
        chars = [c for seg in result["segments"] for c in seg.get("chars", [])]
        spans = []
        for k in range(n):
            part = chars[k * len(args.text):(k + 1) * len(args.text)]
            timed = [c for c in part if "start" in c]
            spans.append([round(min(c["start"] for c in timed), 2), round(max(c["end"] for c in timed), 2)] if timed else None)
        rows.append({"repeat": n, "ctc_score": round(score, 2) if math.isfinite(score) else None,
                     "timed_chars": sum("start" in c for c in chars), "total_chars": len(chars), "spans": spans})
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
