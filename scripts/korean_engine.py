"""Korean alignment engine v3 -- a wrapper around align_full_song.align_lines.

Why a separate module: the Japanese pipeline and the current Korean engine
(align_full_song.py, schema 15) stay byte-for-byte untouched. This file only
adds two label-free, stem-based safeguards on top of them, and is used only
when explicitly enabled (process_song.py --ko-engine v3 / BYPP_KO_ENGINE=v3).

The two failure modes it targets (found on the three Korean demo songs):

1. Wrong alignment audio.  The engine aligns on the original *mix*.  On songs
   with loud accompaniment and no stanza breaks that puts lit lines on
   stretches where nobody sings (12 of 28 lines on one song).  Aligning on the
   separated vocal stem fixes that song but is worse on others.  So both are
   run and the one whose lit lines overlap the sung frames best is kept
   ("coverage F1" -- needs no human reference).

2. Line boundaries that lag or lead a real pause.  Speech-trained CTC gives a
   held vowel to a neighbouring line.  Where a line borders a clear vocal pause
   (>= 0.25 s), its start/end are snapped to the vocal onset/offset in the
   stem, never crossing a neighbour and never by more than SNAP_WINDOW.

Everything is decided from the audio; nothing here can create a human
reference, and every decision is written into alignmentSources for review.
"""

import numpy as np
import soundfile as sf

import align_full_song as engine

HOP = 0.01
SNAP_WINDOW = 1.2      # never move a boundary further than this
SNAP_MIN_SHIFT = 0.12  # ignore shifts smaller than this
PAUSE = 0.25           # a "real" pause between phrases
ACTIVE_DB = 33.0       # sung frame = within this many dB of the stem peak
KO_ENGINE_VERSION = 3


def _active_mask(vocals) -> np.ndarray:
    x, sr = sf.read(vocals, always_2d=True)
    x = x.mean(1)
    h = int(sr * HOP)
    n = len(x) // h
    db = 20 * np.log10(np.sqrt((x[:n * h].reshape(n, h) ** 2).mean(1)) + 1e-9)
    db = np.convolve(db, np.ones(5) / 5, "same")
    return db > db.max() - ACTIVE_DB


def _edges(active: np.ndarray):
    """Onsets/offsets of sung runs separated by pauses >= PAUSE (short holes merged)."""
    a = active.copy()
    gap = int(PAUSE / HOP)
    on, off, n, i, last_end = [], [], len(a), 0, None
    while i < n:
        if not a[i]:
            i += 1
            continue
        j = i
        while j < n and a[j]:
            j += 1
        k = j
        while k < n and not a[k]:
            k += 1
        if k < n and k - j < gap:
            a[j:k] = True
            continue
        if last_end is None or (i - last_end) >= gap:
            on.append(i * HOP)
        off.append(j * HOP)
        last_end, i = j, j
    return np.array(on), np.array(off)


def coverage_f1(active: np.ndarray, data: dict) -> dict:
    """Lit-line vs sung-frame overlap between the first and last lit line."""
    n = len(active)
    lit = np.zeros(n, bool)
    lo, hi = n, 0
    for line in data["lines"]:
        s, e = line.get("start"), line.get("end")
        if s is None or e is None:
            continue
        a, b = int(s / HOP), min(n, int(e / HOP))
        lit[a:b] = True
        lo, hi = min(lo, a), max(hi, b)
    if hi <= lo:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    lit, act = lit[lo:hi], active[lo:hi]
    both = float((lit & act).sum())
    p, r = both / max(1.0, float(lit.sum())), both / max(1.0, float(act.sum()))
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / max(1e-9, p + r), 3)}


def _rescale(line: dict, new_start: float, new_end: float) -> None:
    old_start, old_end = line["start"], line["end"]
    span = max(1e-3, old_end - old_start)
    for key in ("chars", "phonetic_chars"):
        for c in line.get(key, []):
            if c["s"] is None:
                continue
            fs = min(1.0, max(0.0, (c["s"] - old_start) / span))
            fe = min(1.0, max(fs, (c["e"] - old_start) / span))
            c["s"] = new_start + (new_end - new_start) * fs
            c["e"] = new_start + (new_end - new_start) * fe
    line["start"], line["end"] = new_start, new_end


def snap_to_pauses(data: dict, active: np.ndarray) -> list[str]:
    """Snap line starts/ends that border a clear pause to the stem's onset/offset."""
    on, off = _edges(active)
    L, notes = data["lines"], []
    for i, line in enumerate(L):
        s, e = line.get("start"), line.get("end")
        if s is None or e is None:
            continue
        prev_end = L[i - 1]["end"] if i and L[i - 1].get("end") is not None else -9.0
        next_start = L[i + 1]["start"] if i + 1 < len(L) and L[i + 1].get("start") is not None else 1e9
        new_s, new_e = s, e
        if len(on) and s - prev_end >= PAUSE:
            cand = on[(np.abs(on - s) <= SNAP_WINDOW) & (on > prev_end - 0.05) & (on < e - 0.3)]
            if len(cand):
                t = float(cand[np.argmin(np.abs(cand - s))])
                if abs(t - s) >= SNAP_MIN_SHIFT:
                    new_s = t
        if len(off) and next_start - e >= PAUSE:
            cand = off[(np.abs(off - e) <= SNAP_WINDOW) & (off > new_s + 0.3) & (off < next_start + 0.05)]
            if len(cand):
                t = float(cand[np.argmin(np.abs(cand - e))])
                if abs(t - e) >= SNAP_MIN_SHIFT:
                    new_e = t
        if new_s != s or new_e != e:
            _rescale(line, new_s, new_e)
            notes.append(f"line {i + 1}: snapped {s:.2f}-{e:.2f}s to vocal pause edges {new_s:.2f}-{new_e:.2f}s")
    return notes


TOUCH = 0.15       # a sung run this close to a line edge continues that line
MIN_RUN = 0.5      # ignore shorter blips (breaths, stem bleed)
MAX_EXTEND = 4.0   # never stretch a line by more than this


def _runs(active: np.ndarray, lo: float, hi: float) -> list[tuple[float, float]]:
    """Sung runs inside [lo, hi] seconds, holes < PAUSE bridged."""
    a, b = int(lo / HOP), min(len(active), int(hi / HOP))
    seg, gap, runs, j = active[a:b], int(PAUSE / HOP), [], 0
    while j < len(seg):
        if not seg[j]:
            j += 1
            continue
        m = j
        while m < len(seg):
            if seg[m]:
                m += 1
                continue
            k = m
            while k < len(seg) and not seg[k]:
                k += 1
            if k < len(seg) and k - m < gap:
                m = k
            else:
                break
        runs.append((lo + j * HOP, lo + m * HOP))
        j = m
    return runs


def absorb_adjacent_singing(data: dict, active: np.ndarray) -> list[str]:
    """Light a line for singing that runs straight on from it.

    Speech-trained CTC cuts a held tail short (line ends while the voice
    continues) or starts a line after its real onset. A sung run that touches
    a line's end -- or the next line's start -- is that line's own singing:
    extend the end / pull the start back over it. Isolated runs in the middle
    of a gap are left alone (unknown text), only reported by unlit_singing().
    """
    L, notes = data["lines"], []
    for i, line in enumerate(L):
        if line.get("start") is None or line.get("end") is None or i + 1 >= len(L):
            continue
        nxt = L[i + 1]
        if nxt.get("start") is None:
            continue
        e, s_next = line["end"], nxt["start"]
        if s_next - e < 0.3:
            continue
        for rs, re_ in _runs(active, e - TOUCH, s_next + TOUCH):
            if re_ - rs < MIN_RUN:
                continue
            if abs(rs - e) <= TOUCH and re_ - e <= MAX_EXTEND:
                new_e = min(re_, s_next - 0.05)
                _rescale(line, line["start"], new_e)
                notes.append(f"line {i + 1}: end extended {e:.2f}->{new_e:.2f}s over continuing singing")
                e = new_e
            elif abs(re_ - s_next) <= TOUCH + 0.1 and s_next - rs <= MAX_EXTEND and rs > e + 0.05:
                _rescale(nxt, rs, nxt["end"])
                notes.append(f"line {i + 2}: start pulled {s_next:.2f}->{rs:.2f}s to the preceding singing")
                s_next = rs
    return notes


def unlit_singing(active: np.ndarray, data: dict, min_len: float = 2.5) -> list[dict]:
    """Sung stretches inside the lyric span that no line is lit for.

    Long ones usually mean the submitted text omits something that is sung
    (a repeated chorus, an ad-lib). They are reported, never "fixed" -- the
    engine cannot know the missing words.
    """
    n = len(active)
    lit = np.zeros(n, bool)
    lo, hi = n, 0
    for line in data["lines"]:
        s, e = line.get("start"), line.get("end")
        if s is None or e is None:
            continue
        a, b = int(s / HOP), min(n, int(e / HOP))
        lit[a:b] = True
        lo, hi = min(lo, a), max(hi, b)
    out, i = [], lo
    while i < hi:
        if active[i] and not lit[i]:
            j = i
            while j < hi and active[j] and not lit[j]:
                j += 1
            # tolerate tiny lit/quiet interruptions so one stretch is one report
            if (j - i) * HOP >= min_len:
                out.append({"start": round(i * HOP, 2), "end": round(j * HOP, 2),
                            "seconds": round((j - i) * HOP, 2)})
            i = j
        else:
            i += 1
    return out


def align_lines_v3(vocals, lines, device="auto", section_lengths=None, line_windows=None,
                   alignment_audio=None) -> dict:
    """Korean alignment: pick mix vs stem by coverage, then snap to pauses."""
    active = _active_mask(vocals)
    candidates = []
    plans = [("original mix", alignment_audio)] if alignment_audio else []
    plans.append(("vocal stem", None))
    for name, audio in plans:
        data = engine.align_lines(vocals, lines, device=device, language="ko",
                                  section_lengths=section_lengths, line_windows=line_windows,
                                  alignment_audio=audio)
        candidates.append((name, data, coverage_f1(active, data)))
    best_name, best, best_cov = max(candidates, key=lambda c: c[2]["f1"])
    summary = ", ".join(f"{n} f1 {c['f1']:.3f}" for n, _, c in candidates)
    notes = [f"ko-engine v{KO_ENGINE_VERSION}: alignment audio candidates: {summary} -> {best_name}"]
    snapped = snap_to_pauses(best, active)
    snapped += absorb_adjacent_singing(best, active)
    after = coverage_f1(active, best)
    notes.append(f"ko-engine v{KO_ENGINE_VERSION}: {len(snapped)} line boundaries snapped to vocal pauses "
                 f"(f1 {best_cov['f1']:.3f} -> {after['f1']:.3f})")
    unlit = unlit_singing(active, best)
    if unlit:
        notes.append(f"ko-engine v{KO_ENGINE_VERSION}: {len(unlit)} sung stretches (>=2.5s) have no lit line "
                     f"(total {sum(u['seconds'] for u in unlit):.1f}s) -- the text may omit sung repeats/ad-libs")
    best["unlitSinging"] = unlit
    best["alignmentSources"] = list(best.get("alignmentSources", [])) + notes
    best["koEngineVersion"] = KO_ENGINE_VERSION
    best["durationRepairs"] = list(best.get("durationRepairs", [])) + snapped
    best["coverage"] = {"before": best_cov, "after": after}
    return best
