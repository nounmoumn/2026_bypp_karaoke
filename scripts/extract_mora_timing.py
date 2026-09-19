"""Extract per-character (~mora) timestamps for a PoC segment and extend held
tail notes using the separated vocal stem's energy decay.

Speech-trained forced alignment (WhisperX/wav2vec2) reliably finds where a
character *starts*, but a sung, held vowel has no equivalent in speech
training data, so the model tends to end that character as soon as the vowel
is recognized rather than when it actually stops sounding (this is the same
mechanism behind T01's larger end-boundary error). This script keeps the
model's character starts as-is, then for each character whose modeled end
falls well short of the next character's modeled start (or the line's own
end), extends that character's end out to where the vocal stem's energy
actually decays below a floor -- capped so it never crosses into the next
character's own start.

Usage:
    .venv-align/Scripts/python.exe scripts/extract_mora_timing.py data/poc/bansanka \
        --vocals demucs_output/htdemucs/segment_A_0008.0-0067.0/vocals.wav \
        --lines segment_A_lyrics_ja.txt --prefix A --out mora_timing.json
"""

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf
import whisperx


def energy_decay_end(mono: np.ndarray, sr: int, model_end: float, ceiling: float,
                      floor_db: float = -30.0, hop_sec: float = 0.01) -> float:
    """Walk forward from model_end while the vocal stem is still audibly sounding."""
    hop = max(1, int(sr * hop_sec))
    start_i = max(0, int(model_end * sr))
    ceil_i = min(len(mono), int(ceiling * sr))
    if start_i >= ceil_i:
        return model_end
    window = mono[start_i:ceil_i]
    n = len(window) // hop
    if n < 1:
        return model_end
    frames = window[: n * hop].reshape(n, hop)
    rms = np.sqrt((frames ** 2).mean(axis=1)) + 1e-9
    ref = np.sqrt((mono[max(0, start_i - hop * 5):start_i] ** 2).mean()) + 1e-9 if start_i > 0 else rms[0]
    ref = max(ref, rms[0])
    thresh = ref * (10 ** (floor_db / 20))
    last_loud = 0
    for i, r in enumerate(rms):
        if r > thresh:
            last_loud = i
    return model_end + (last_loud + 1) * hop_sec


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--vocals", required=True)
    p.add_argument("--lines", required=True)
    p.add_argument("--prefix", required=True)
    p.add_argument("--windows", help="alignment_whisperx_asr.json to reuse existing group windows")
    p.add_argument("--out", default="mora_timing.json")
    args = p.parse_args()

    root = args.root
    lines = (root / args.lines).read_text(encoding="utf-8").splitlines()
    vocals_path = root / args.vocals
    mono, sr = sf.read(vocals_path, always_2d=True)
    mono = mono.mean(axis=1)

    if args.windows:
        groups_raw = json.loads((root / args.windows).read_text(encoding="utf-8"))["groups"]
        groups = [tuple(g) for g in groups_raw]
    else:
        groups = [(0, len(lines), 0.0, mono.shape[0] / sr)]

    model, meta = whisperx.load_align_model(language_code="ja", device="cpu")
    transcript = [{"start": s, "end": e, "text": "".join(lines[a:b])} for a, b, s, e in groups]
    aligned = whisperx.align(transcript, model, meta, str(vocals_path), "cpu", return_char_alignments=True)

    out_lines = []
    for (a, b, s, e), seg in zip(groups, aligned["segments"]):
        chars = seg.get("chars", [])
        off = 0
        for i in range(a, b):
            text = lines[i]
            lc = chars[off: off + len(text)]
            off += len(text)
            timed = [c for c in lc if "start" in c and "end" in c]
            moras = []
            for k, c in enumerate(lc):
                if "start" not in c or "end" not in c:
                    moras.append({"char": c.get("char", ""), "start": None, "end": None, "extended": False})
                    continue
                nxt = None
                for c2 in chars[off - len(text) + k + 1:]:  # look past this line's own slice too
                    if "start" in c2:
                        nxt = c2["start"]
                        break
                ceiling = min(nxt, e) if nxt is not None else min(c["end"] + 1.2, e)
                new_end = energy_decay_end(mono, sr, c["end"], ceiling)
                moras.append({"char": c["char"], "start": c["start"], "end": round(new_end, 3),
                             "modelEnd": round(c["end"], 3), "nextCharStart": nxt,
                             "extended": new_end > c["end"] + 0.02})
            out_lines.append({
                "lineId": f"{args.prefix}{i:02d}",
                "start": moras[0]["start"] if moras and moras[0]["start"] is not None else None,
                "end": moras[-1]["end"] if moras else None,
                "moras": moras,
                "timedChars": len(timed), "totalChars": len(lc),
            })

    (root / args.out).write_text(json.dumps({"lines": out_lines}, ensure_ascii=False, indent=2), encoding="utf-8")
    extended = sum(1 for ln in out_lines for m in ln["moras"] if m.get("extended"))
    print(f"Wrote {len(out_lines)} lines, {extended} mora ends extended, to {root / args.out}")


if __name__ == "__main__":
    main()
