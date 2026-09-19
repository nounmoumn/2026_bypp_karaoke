"""Mora/character-level timing with a properly bounded tail extension.

v1 (extract_mora_timing.py) extended each line's last character toward
vocal-stem energy decay, but capped only at the *next character within the
same WhisperX transcript group* -- and groups can end mid-song, so on a
group boundary the code fell back to an arbitrary +1.2s cap and sometimes
extended straight into the *next line's own singing* (confirmed: several
lines' extended end landed past the next line's own reviewed start).

v2 bounds every extension by the next LINE's own modeled start time
(alignment_whisperx_asr.json's per-line startSec), which is available
across group boundaries and -- per the T01 gate -- is independently
reliable (median error ~0s). This never needs a human label at inference
time: it only uses the automatic pipeline's own other output as the cap.
Within [model_end, next_line_start] it still walks the vocal stem's energy
decay to find a plausible release point; if nothing decays (bleed / real
continued singing / last line of the clip) it stops at the cap itself
rather than overshooting further.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf
import whisperx


def energy_decay_end(mono, sr, model_end, ceiling, floor_db=-20.0, hop_sec=0.01, min_hold_sec=0.06):
    hop = max(1, int(sr * hop_sec))
    start_i, ceil_i = max(0, int(model_end * sr)), min(len(mono), int(ceiling * sr))
    if start_i >= ceil_i:
        return model_end
    window = mono[start_i:ceil_i]
    n = len(window) // hop
    if n < 1:
        return model_end
    frames = window[: n * hop].reshape(n, hop)
    rms = np.sqrt((frames ** 2).mean(axis=1)) + 1e-9
    ref = max(rms[0], np.sqrt((mono[max(0, start_i - hop * 5):start_i] ** 2).mean()) + 1e-9 if start_i > 0 else rms[0])
    thresh = ref * (10 ** (floor_db / 20))
    need = max(1, int(min_hold_sec / hop_sec))
    below_run = 0
    for i, r in enumerate(rms):
        if r < thresh:
            below_run += 1
            if below_run >= need:
                return model_end + max(0, i - need + 1) * hop_sec
        else:
            below_run = 0
    return model_end + n * hop_sec  # never dipped -> stop at the cap


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--vocals", required=True)
    ap.add_argument("--lines", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--windows", required=True, help="alignment_whisperx_asr.json (source of per-line model starts)")
    ap.add_argument("--out", default="mora_timing_v2.json")
    args = ap.parse_args()

    root = args.root
    lines = (root / args.lines).read_text(encoding="utf-8").splitlines()
    mono, sr = sf.read(root / args.vocals, always_2d=True)
    mono = mono.mean(axis=1)
    model_lines = json.loads((root / args.windows).read_text(encoding="utf-8"))["lines"]
    model_start = {ln["lineId"]: ln["startSec"] for ln in model_lines}
    groups = [tuple(g) for g in json.loads((root / args.windows).read_text(encoding="utf-8"))["groups"]]

    model, meta = whisperx.load_align_model(language_code="ja", device="cpu")
    transcript = [{"start": s, "end": e, "text": "".join(lines[a:b])} for a, b, s, e in groups]
    aligned = whisperx.align(transcript, model, meta, str(root / args.vocals), "cpu", return_char_alignments=True)

    out_lines = []
    for (a, b, s, e), seg in zip(groups, aligned["segments"]):
        chars = seg.get("chars", [])
        off = 0
        for i in range(a, b):
            text = lines[i]
            lc = chars[off: off + len(text)]
            off += len(text)
            next_id = f"{args.prefix}{i+1:02d}"
            line_cap = model_start.get(next_id, min(lc[-1].get("end", e) + 1.2 if lc else e, e))
            moras = []
            for k, c in enumerate(lc):
                if "start" not in c or "end" not in c:
                    moras.append({"char": c.get("char", ""), "start": None, "end": None, "extended": False})
                    continue
                is_last = k == len(lc) - 1
                nxt = None
                for c2 in lc[k + 1:]:
                    if "start" in c2:
                        nxt = c2["start"]
                        break
                ceiling = nxt if nxt is not None else max(c["end"], line_cap)
                new_end = c["end"] if not is_last else energy_decay_end(mono, sr, c["end"], ceiling)
                new_end = min(new_end, ceiling)
                moras.append({"char": c["char"], "start": c["start"], "end": round(new_end, 3),
                             "modelEnd": round(c["end"], 3), "cap": round(ceiling, 3),
                             "extended": new_end > c["end"] + 0.02})
            out_lines.append({"lineId": f"{args.prefix}{i:02d}",
                              "start": moras[0]["start"] if moras and moras[0]["start"] is not None else None,
                              "end": moras[-1]["end"] if moras else None, "moras": moras})

    (root / args.out).write_text(json.dumps({"lines": out_lines}, ensure_ascii=False, indent=2), encoding="utf-8")
    ext = sum(1 for ln in out_lines for m in ln["moras"] if m.get("extended"))
    print(f"Wrote {len(out_lines)} lines, {ext} tail extensions, capped by next line's own model start, to {root/args.out}")


if __name__ == "__main__":
    main()
