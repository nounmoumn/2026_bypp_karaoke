"""Label-free repair of the one failure mode found in full-song global alignment.

A speech-trained CTC model will not put wordless vocalise ("Ah", "ああ…") on
humming-like audio: it treats that audio as blank, squeezes the vocalise
lines next to the following real lyric, and shifts that lyric late. The
signature is visible without any human label: a vocal-active region that
received no aligned characters ("orphan"), next to lines whose text is only
vowels / interjections.

Rule:
  * leading case  - vocalise lines that come right after an orphan cluster
    are moved onto that cluster's vocal pieces, and the next few real lines
    are re-aligned in a local window that starts after the cluster;
  * trailing case - vocalise lines that end right before an orphan cluster
    are stretched over their own span plus the cluster.
Everything else is left exactly as the global pass placed it.

Usage:
    .venv-align/Scripts/python.exe scripts/repair_orphans.py <song_dir> <full_vocals.wav> <first_ref_index> <offset_sec> <reference_csv>
"""

import csv
import json
import statistics
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import whisperx

VOCALISE = set("あいうえおぁぃぅぇぉーはらなんっ")
HOP = 0.02


def activity(path: Path):
    x, sr = sf.read(path, always_2d=True)
    x = x.mean(1)
    h = int(sr * HOP); n = len(x) // h
    db = 20 * np.log10(np.sqrt((x[:n * h].reshape(n, h) ** 2).mean(1)) + 1e-9)
    db = np.convolve(db, np.ones(5) / 5, "same")
    return db > db.max() - 35


def runs(mask, min_len):
    out, s = [], None
    for i, m in enumerate(mask):
        if m and s is None: s = i
        if not m and s is not None:
            if (i - s) * HOP >= min_len: out.append((s * HOP, i * HOP))
            s = None
    if s is not None and (len(mask) - s) * HOP >= min_len: out.append((s * HOP, len(mask) * HOP))
    return out


def is_vocalise(line):
    t = line.get("aligned_text", line["text"])
    return bool(t) and all(c in VOCALISE for c in t)


def spread(chars, pieces):
    """Give each char an equal share of the voiced time inside `pieces`, in order."""
    total = sum(b - a for a, b in pieces)
    if total <= 0 or not chars: return
    step, k, acc = total / len(chars), 0, 0.0
    bounds = []
    for a, b in pieces:
        bounds.append((acc, acc + (b - a), a)); acc += b - a

    def at(u):
        for lo, hi, a in bounds:
            if u <= hi: return a + (u - lo)
        return pieces[-1][1]
    for j, c in enumerate(chars):
        c["s"], c["e"] = round(at(j * step + 1e-6), 3), round(at((j + 1) * step), 3)


def tidy(data: dict) -> list[str]:
    """Per-line sanity on char durations (label-free).

    Leading chars far longer than the line's typical char are sitting on an
    interlude the stem did not render as silence: pull their starts back
    toward the sung part. A final char may hold, but not absurdly long.
    """
    log = []
    for line_index, l in enumerate(data["lines"]):
        if l.get("repaired"):
            continue
        cs = [c for c in l["chars"] if c["s"] is not None and c["e"] is not None]
        if len(cs) < 3:
            continue
        durs = sorted(c["e"] - c["s"] for c in cs)
        m = max(0.08, durs[len(durs) // 2])
        moved = 0
        for k in range(len(cs) - 1):  # leading chars only, stop at the first normal one
            c = cs[k]
            if c["e"] - c["s"] > max(1.0, 4 * m):
                moved += 1
            else:
                break
        next_start = data["lines"][line_index + 1]["start"] if line_index + 1 < len(data["lines"]) else None
        if next_start is not None and l["end"] is not None and next_start - l["end"] > 8.0:
            moved = 0  # do not pull speech toward the next verse across an interlude
        if moved:
            anchor_s = cs[moved]["s"]
            for k in range(moved - 1, -1, -1):
                cs[k]["e"] = anchor_s
                cs[k]["s"] = anchor_s - 1.5 * m
                anchor_s = cs[k]["s"]
            log.append(f"line {l['index'] + 1}: {moved} leading char(s) pulled off an interlude, start -> {cs[0]['s']:.2f}s")
        last = cs[-1]
        cap = max(2.5, 6 * m)
        if last["e"] - last["s"] > cap:
            last["e"] = last["s"] + cap
            log.append(f"line {l['index'] + 1}: final char hold capped at {cap:.1f}s")
        l["start"], l["end"] = cs[0]["s"], max(c["e"] for c in cs)
    for current, following in zip(data["lines"], data["lines"][1:]):
        boundary = following.get("start")
        if boundary is None or current.get("end") is None or current["end"] <= boundary:
            continue
        current["end"] = boundary
        for key in ("chars", "phonetic_chars"):
            for c in current.get(key, []):
                if c["s"] is not None:
                    c["s"] = min(c["s"], boundary)
                    c["e"] = min(c["e"], boundary)
        log.append(f"line {current['index'] + 1}: end capped at next line start {boundary:.2f}s")
    return log


def repair(data: dict, vocals: Path) -> list[str]:
    """Apply the vocalise/orphan rules in place; returns a log of what changed."""
    L = data["lines"]
    act = activity(vocals)
    log = []
    i = 0
    while i < len(L):  # runs of >=2 consecutive vocalise lines share their combined span
        j = i
        while j < len(L) and is_vocalise(L[j]): j += 1
        if j - i >= 2:
            s0, e0 = L[i]["start"], L[j - 1]["end"]
            span = [(max(x, s0), min(y, e0)) for x, y in runs(act, 0.2) if y > s0 and x < e0]
            spread([c for k in range(i, j) for c in L[k]["chars"]], span)
            for k in range(i, j):
                L[k]["start"], L[k]["end"] = L[k]["chars"][0]["s"], L[k]["chars"][-1]["e"]
                L[k]["repaired"] = True
            log.append(f"vocalise run {list(range(i, j))}: spread over voiced pieces in [{s0:.1f}, {e0:.1f}]")
        i = max(j, i + 1)
    covered = np.zeros(len(act), bool)
    for l in L:
        for c in l["chars"]:
            if c["s"] is not None:
                covered[int(c["s"] / HOP):int(max(c["e"], c["s"] + HOP) / HOP) + 1] = True
    pieces = runs(act & ~covered, 0.5)
    clusters = []
    for a, b in pieces:  # merge pieces separated by < 3 s
        if clusters and a - clusters[-1][-1][1] < 3.0: clusters[-1].append((a, b))
        else: clusters.append([(a, b)])
    clusters = [c for c in clusters if sum(b - a for a, b in c) >= 2.0]

    model = meta = audio = None
    for cl in clusters:
        a, b = cl[0][0], cl[-1][1]
        after = [i for i, l in enumerate(L) if l["start"] is not None and l["start"] >= a]
        j = after[0] if after else None
        block = []
        while j is not None and j < len(L) and is_vocalise(L[j]):
            block.append(j); j += 1
        if block:  # leading case
            chars = [c for i in block for c in L[i]["chars"]]
            spread(chars, cl)
            for i in block:
                L[i]["start"], L[i]["end"] = L[i]["chars"][0]["s"], L[i]["chars"][-1]["e"]
                L[i]["repaired"] = True
            k, m = j, min(j + 3, len(L))
            win_end = L[m]["start"] if m < len(L) else data["durationSec"]
            if model is None:
                model, meta = whisperx.load_align_model(language_code="ja", device="cpu")
                audio = whisperx.load_audio(str(vocals))
            text = "".join(L[i]["aligned_text"] for i in range(k, m))
            res = whisperx.align([{"start": b, "end": win_end, "text": text}], model, meta, audio, "cpu",
                                 return_char_alignments=True)
            ch, off = res["segments"][0]["chars"], 0
            for i in range(k, m):
                n = len(L[i]["aligned_text"]); lc = ch[off:off + n]; off += n
                t = [c for c in lc if "start" in c]
                if t and L[i]["aligned_text"] == L[i]["text"]:
                    L[i]["chars"] = [{"c": c["char"], "s": c.get("start"), "e": c.get("end")} for c in lc]
                if t:
                    L[i]["start"], L[i]["end"] = min(c["start"] for c in t), max(c["end"] for c in t)
            log.append(f"leading orphan {a:.1f}-{b:.1f}s: moved vocalise lines {block}, re-aligned {list(range(k, m))} in [{b:.1f}, {win_end:.1f}]")
            continue
        before = [i for i, l in enumerate(L) if l["end"] is not None and l["end"] <= a + 0.5]
        p = before[-1] if before else None
        block = []
        while p is not None and p >= 0 and is_vocalise(L[p]):
            block.insert(0, p); p -= 1
        tail = []
        if p is not None and p >= 0 and a - L[p]["end"] <= 2.0:  # nearby vocalise tail only
            for c in reversed(L[p]["chars"]):  # skip punctuation/spaces; latin "ha, ah" counts as vocalise
                if c["c"] in " ,.!?！？、。・～~　":
                    continue
                if c["s"] is not None and (c["c"] in VOCALISE or c["c"].lower() in "aho"):
                    tail.insert(0, c)
                else:
                    break
            if not any(c["c"] in VOCALISE or c["c"].lower() in "aho" for c in tail):
                tail = []
        chars = tail + [c for i in block for c in L[i]["chars"]]
        if chars:  # trailing case
            s0 = chars[0]["s"]
            span = [(max(x, s0), min(y, b)) for x, y in runs(act, 0.2) if y > s0 and x < b]
            spread(chars, span)
            for i in block + ([p] if tail else []):
                ts = [c for c in L[i]["chars"] if c["s"] is not None]
                L[i]["start"], L[i]["end"] = ts[0]["s"], max(c["e"] for c in ts)
                L[i]["repaired"] = True
            log.append(f"trailing orphan {a:.1f}-{b:.1f}s: stretched vocalise lines {block} + {len(tail)} tail chars of line {p} to {b:.1f}s")
        else:
            log.append(f"orphan {a:.1f}-{b:.1f}s: no adjacent vocalise text, left as is")

    data["method"] += " + orphan-vocalise repair"
    data["repairs"] = log
    return log


def main():
    root = Path(sys.argv[1]); vocals = root / sys.argv[2]
    first, offset, ref_csv = int(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
    data = json.loads((root / "alignment_full_song_global.json").read_text(encoding="utf-8"))
    log = repair(data, vocals)
    log += tidy(data)
    L = data["lines"]
    (root / "alignment_full_song_repaired.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(root.name, *log, sep="\n  ")

    refs = list(csv.DictReader((root / ref_csv).open(encoding="utf-8-sig")))
    se, ee = [], []
    for k, r in enumerate(refs):
        l = L[first + k]
        se.append(abs(l["start"] - offset - float(r["reference_start"])))
        ee.append(abs(l["end"] - offset - float(r["reference_end"])))
    n = len(refs)
    print(f"  reviewed lines: start<=0.5 {sum(e<=.5 for e in se)}/{n}  end<=0.7 {sum(e<=.7 for e in ee)}/{n}  "
          f"start>1s {sum(e>1 for e in se)}/{n}  start max {max(se):.2f}  end max {max(ee):.2f}")
    starts = [l["start"] for l in L]
    print(f"  backwards starts: {sum(1 for x, y in zip(starts, starts[1:]) if y < x)}")


if __name__ == "__main__":
    main()
