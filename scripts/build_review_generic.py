"""Build auto-alignment candidates and a listening review page for any PoC song folder.

Usage (from the bypp root, with the align venv):
    .venv-align/Scripts/python.exe scripts/build_review_generic.py data/poc/moon_landing_plan

Reads manifest.json + segment lyric/reading files, then:
  1. Demucs two-stem separation of the segment (system `demucs` CLI) if missing
  2. faster-whisper small ASR on the separated vocals (rough, not ground truth)
  3. WhisperX character alignment of the given lyrics, two ways:
       - "whole": all lines as one transcript over the whole segment
       - "asr":   lines grouped to ASR segments by automatic character matching
  4. review_alignment.html (same workflow as the Bansanka review page)

Both candidates are automatic proposals only. References come from listening.
"""

import difflib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import whisperx
from faster_whisper import WhisperModel

DEMUCS = shutil.which("demucs") or r"C:\Users\User\AppData\Local\Programs\Python\Python312\Scripts\demucs.exe"


def separate(root: Path, seg: str) -> Path:
    out = root / "demucs_output/htdemucs" / Path(seg).stem
    if not (out / "vocals.wav").exists():
        subprocess.run([DEMUCS, "--two-stems=vocals", "-o", str(root / "demucs_output"), str(root / seg)], check=True)
    return out


def run_asr(root: Path, vocals: Path) -> list[dict]:
    path = root / "asr_small_vocals.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["segments"]
    started = time.perf_counter()
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(vocals), language="ja", beam_size=5, vad_filter=False)
    rows = [{"startSec": s.start, "endSec": s.end, "text": s.text} for s in segments]
    path.write_text(json.dumps({"model": "small", "language": info.language,
                                "elapsedSec": round(time.perf_counter() - started, 2), "segments": rows},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    return rows


def asr_groups(lines: list[str], asr: list[dict], dur: float) -> list[tuple[int, int, float, float]]:
    """Assign each lyric line to the ASR segment holding most of its matched characters."""
    lyric = "".join(lines)
    owner = []  # ASR segment index per ASR character
    text = ""
    for k, s in enumerate(asr):
        t = s["text"].replace(" ", "").replace("\u3000", "")
        text += t
        owner += [k] * len(t)
    votes = [dict() for _ in lines]
    starts, pos = [], 0
    for ln in lines:
        starts.append(pos)
        pos += len(ln)
    line_of = [i for i, ln in enumerate(lines) for _ in ln]
    for a, b, n in difflib.SequenceMatcher(None, lyric, text, autojunk=False).get_matching_blocks():
        for j in range(n):
            li, sk = line_of[a + j], owner[b + j]
            votes[li][sk] = votes[li].get(sk, 0) + 1
    spans = []
    for v in votes:
        if not v:
            spans.append(spans[-1] if spans else (0, 0))
            continue
        total = sum(v.values())
        keep = [k for k, c in v.items() if c >= 2 and c >= 0.2 * total] or [max(v, key=v.get)]
        spans.append((min(keep), max(keep)))
    for i in range(1, len(spans)):  # keep monotonic
        lo, hi = spans[i]
        lo = max(lo, spans[i - 1][0])
        spans[i] = (lo, max(hi, lo))
    groups, i = [], 0
    while i < len(lines):
        lo, hi = spans[i]
        j = i
        while j + 1 < len(lines) and spans[j + 1][0] <= hi:
            j += 1
            hi = max(hi, spans[j][1])
        groups.append((i, j + 1, max(0.0, asr[lo]["startSec"] - 0.25), min(dur, asr[hi]["endSec"] + 0.25)))
        i = j + 1
    fixed = []
    for n, (a, b, s, e) in enumerate(groups):
        if n > 0:
            s = min(s, fixed[-1][3])
        fixed.append((a, b, s, e))
    return fixed


def align(lines, groups, vocals, model, meta, prefix):
    transcript = [{"start": s, "end": e, "text": "".join(lines[a:b])} for a, b, s, e in groups]
    aligned = whisperx.align(transcript, model, meta, str(vocals), "cpu", return_char_alignments=True)
    out = []
    for (a, b, s, e), src, seg in zip(groups, transcript, aligned["segments"]):
        chars = seg.get("chars", [])
        if len(chars) != len(src["text"]):
            raise ValueError(f"char mismatch in group {a}:{b}")
        off = 0
        for i in range(a, b):
            lc = chars[off: off + len(lines[i])]
            off += len(lines[i])
            timed = [c for c in lc if "start" in c and "end" in c]
            out.append({"lineId": f"{prefix}{i:02d}", "jp": lines[i],
                        "startSec": min((c["start"] for c in timed), default=None),
                        "endSec": max((c["end"] for c in timed), default=None),
                        "windowStartSec": s, "windowEndSec": e,
                        "timedChars": len(timed), "totalChars": len(lc)})
    return out


def main() -> None:
    root = Path(sys.argv[1])
    m = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    seg, dur, sid = m["segment_file"], float(m["segment_duration_sec"]), m["sample_id"]
    sec = seg.split("_")[1]
    lines = (root / m["lyrics_file"]).read_text(encoding="utf-8").splitlines()
    ko = (root / m["reading_file"]).read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(ko) == m["lyric_lines"]

    stems = separate(root, seg)
    vocals = stems / "vocals.wav"
    asr = run_asr(root, vocals)

    model, meta = whisperx.load_align_model(language_code="ja", device="cpu")
    results = {}
    for name, groups in [("whole", [(0, len(lines), 0.0, dur)]), ("asr", asr_groups(lines, asr, dur))]:
        started = time.perf_counter()
        rows = align(lines, groups, vocals, model, meta, sec)
        (root / f"alignment_whisperx_{name}.json").write_text(json.dumps(
            {"model": "jonatasgrosman/wav2vec2-large-xlsr-53-japanese",
             "method": f"WhisperX sequential char alignment, {name} windows",
             "groups": groups, "elapsedSec": round(time.perf_counter() - started, 2), "lines": rows},
            ensure_ascii=False, indent=2), encoding="utf-8")
        results[name] = rows
        print(name, "groups:", [(a, b, round(s, 2), round(e, 2)) for a, b, s, e in groups])

    data = []
    for i, (w, a) in enumerate(zip(results["whole"], results["asr"])):
        data.append({"id": w["lineId"], "jp": lines[i], "ko": ko[i],
                     "c1s": w["startSec"], "c1e": w["endSec"], "c2s": a["startSec"], "c2e": a["endSec"]})
    tpl = (Path(__file__).parent / "review_template.html").read_text(encoding="utf-8")
    sources = [(seg, "원곡 구간"), (f"demucs_output/htdemucs/{Path(seg).stem}/vocals.wav", "분리 보컬"),
               (f"demucs_output/htdemucs/{Path(seg).stem}/no_vocals.wav", "반주 MR")]
    html = (tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c"))
               .replace("__TITLE__", f"{m['song']} 구간 {sec}")
               .replace("__OFFSET__", str(m["segment_offset_sec"]))
               .replace("__DUR__", f"{dur:.3f}")
               .replace("__SID__", sid)
               .replace("__SEC__", sec)
               .replace("__SOURCES__", "".join(f'<option value="{p}">{t}</option>' for p, t in sources))
               .replace("__FIRST__", seg))
    (root / "review_alignment.html").write_text(html, encoding="utf-8")
    print(root / "review_alignment.html")


if __name__ == "__main__":
    main()
