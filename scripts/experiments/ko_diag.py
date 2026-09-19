"""Label-free timing diagnostics for an aligned song (read-only; writes nothing).

No human reference exists for the Korean songs, so this measures how each
line's start/end sit against the *vocal stem itself*:
  * dStart / dEnd   - line start/end vs the nearest vocal onset/offset when the
                      line follows/precedes a real pause (>= 0.25 s)
  * silentFrac      - share of the lit line span where the stem is silent
                      (a line highlighted while nobody sings)
  * missedSec       - seconds of singing between this line's end and the next
                      line's start (singing that no line is lit for)
Positive dStart = line starts LATE (끌림); negative = EARLY (밀림).
"""

import json
import statistics
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

HOP = 0.01


def envelope(path: Path):
    x, sr = sf.read(path, always_2d=True)
    x = x.mean(1)
    h = int(sr * HOP)
    n = len(x) // h
    db = 20 * np.log10(np.sqrt((x[:n * h].reshape(n, h) ** 2).mean(1)) + 1e-9)
    db = np.convolve(db, np.ones(5) / 5, "same")
    return db > db.max() - 33


def edges(active: np.ndarray, min_gap: float = 0.25):
    """(onsets, offsets) of vocal activity separated by >= min_gap silences."""
    gap = int(min_gap / HOP)
    on, off = [], []
    i, n = 0, len(active)
    last_end = None
    while i < n:
        if active[i]:
            j = i
            while j < n and active[j]:
                j += 1
            # merge across short silences
            k = j
            while k < n and not active[k]:
                k += 1
            if k < n and k - j < gap:
                # short hole: extend the run through the hole
                active[j:k] = True
                continue
            if last_end is None or (i - last_end) >= gap:
                on.append(i * HOP)
            off.append(j * HOP)
            last_end = j
            i = j
        else:
            i += 1
    return np.array(on), np.array(off)


def nearest(arr: np.ndarray, t: float, window: float):
    if len(arr) == 0:
        return None
    k = int(np.argmin(np.abs(arr - t)))
    return float(arr[k] - t) if abs(arr[k] - t) <= window else None


def diagnose(song_dir: Path, vocals: Path, quiet: bool = False, karaoke: Path | None = None):
    data = json.loads((karaoke or song_dir / "karaoke.json").read_text(encoding="utf-8"))
    L = data["lines"]
    active = envelope(vocals)
    on, off = edges(active.copy())
    rows, ds, de = [], [], []
    for i, l in enumerate(L):
        s, e = l.get("start"), l.get("end")
        if s is None or e is None:
            rows.append((i, None, None, None, None, None, None)); continue
        prev_end = L[i - 1]["end"] if i and L[i - 1].get("end") is not None else -9
        next_start = L[i + 1]["start"] if i + 1 < len(L) and L[i + 1].get("start") is not None else 1e9
        d_s = nearest(on, s, 1.5) if s - prev_end >= 0.25 else None
        d_e = nearest(off, e, 1.5) if next_start - e >= 0.25 else None
        if d_s is not None: ds.append(-d_s)   # line.start - onset
        if d_e is not None: de.append(-d_e)   # line.end - offset
        a, b = int(s / HOP), max(int(s / HOP) + 1, int(e / HOP))
        silent = 1 - active[a:b].mean() if b <= len(active) else 0
        c, d = int(e / HOP), int(min(next_start, len(active) * HOP) / HOP)
        # sung seconds after this line's end, before the next line starts (only meaningful for a real gap)
        missed = float(active[c:d].sum() * HOP) if d > c else 0.0
        rows.append((i, s, e, None if d_s is None else -d_s, None if d_e is None else -d_e, silent, missed))
    summary = {}
    for name, v in (("dStart", ds), ("dEnd", de)):
        if v:
            summary[name] = {"n": len(v), "median": round(statistics.median(v), 3),
                             "medianAbs": round(statistics.median(abs(x) for x in v), 3),
                             "p90Abs": round(float(np.percentile([abs(x) for x in v], 90)), 3),
                             "over0.5s": int(sum(abs(x) > 0.5 for x in v))}
    ok = [r for r in rows if r[1] is not None]
    summary["silentFracMean"] = round(float(np.mean([r[5] for r in ok])), 3)
    summary["missedSecTotal"] = round(float(sum(r[6] for r in ok)), 2)
    summary["linesSilentOver30pct"] = int(sum(r[5] > 0.30 for r in ok))
    summary["linesMissedOver0.4s"] = int(sum(r[6] > 0.4 for r in ok))
    if not quiet:
        print(f"{'ln':>3} {'start':>7} {'end':>7} {'dStart':>7} {'dEnd':>7} {'silent':>6} {'missS':>6}")
        for r in rows:
            if r[1] is None:
                print(f"{r[0]+1:3d} unaligned"); continue
            f = lambda v: "   -  " if v is None else f"{v:+6.2f}"
            flag = "  <<" if (r[3] is not None and abs(r[3]) > 0.5) or (r[4] is not None and abs(r[4]) > 0.5) or r[5] > 0.3 or r[6] > 0.4 else ""
            print(f"{r[0]+1:3d} {r[1]:7.2f} {r[2]:7.2f} {f(r[3])} {f(r[4])} {r[5]:6.2f} {r[6]:6.2f}{flag}")
    return summary, rows


if __name__ == "__main__":
    song = Path(sys.argv[1])
    vocals = Path(sys.argv[2]) if len(sys.argv) > 2 else song / "stems" / "htdemucs" / "original" / "vocals.wav"
    kj = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    summary, _ = diagnose(song, vocals, karaoke=kj)
    print(json.dumps(summary, indent=1))


def coverage(vocals: Path, data: dict, trim_edges: bool = True) -> dict:
    """Label-free overlap between lit line spans and sung frames.

    precision = share of lit time that is actually sung; recall = share of
    sung time (between the first and last lit line) that is lit; f1 combines
    them. Sung frames before the first / after the last line are ignored so
    intros, outros and ad-libs outside the lyric do not count as misses.
    """
    active = envelope(vocals)
    n = len(active)
    lit = np.zeros(n, bool)
    starts, ends = [], []
    for l in data["lines"]:
        s, e = l.get("start"), l.get("end")
        if s is None or e is None:
            continue
        a, b = int(s / HOP), min(n, int(e / HOP))
        lit[a:b] = True
        starts.append(a); ends.append(b)
    lo, hi = (min(starts), max(ends)) if trim_edges and starts else (0, n)
    lit, act = lit[lo:hi], active[lo:hi]
    both = float((lit & act).sum())
    p = both / max(1.0, float(lit.sum()))
    r = both / max(1.0, float(act.sum()))
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / max(1e-9, p + r), 3)}
