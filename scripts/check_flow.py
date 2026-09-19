"""Label-free whole-song flow check: compare aligned line starts with vocal-stem silences.

Every long vocal silence (>= MIN_GAP s) should be followed by a line start near
its end, and no line should start inside one. Uses only the vocal stem.
"""
import json, sys
import numpy as np, soundfile as sf

MIN_GAP = 1.5
root, vocals = sys.argv[1], sys.argv[2]
x, sr = sf.read(f"{root}/{vocals}", always_2d=True); x = x.mean(1)
h = int(sr * 0.02); n = len(x) // h
db = 20 * np.log10(np.sqrt((x[:n*h].reshape(n, h) ** 2).mean(1)) + 1e-9)
db = np.convolve(db, np.ones(5) / 5, "same")
act = db > db.max() - 35
gaps, s = [], None
for i, a in enumerate(act):
    t = i * 0.02
    if not a and s is None: s = t
    if a and s is not None:
        if t - s >= MIN_GAP: gaps.append((s, t))
        s = None
if s is not None and n * 0.02 - s >= MIN_GAP: gaps.append((s, n * 0.02))
lines = json.load(open(f"{root}/alignment_full_song_global.json", encoding="utf-8"))["lines"]
starts = [(l["index"], l["start"]) for l in lines]
inside = [(i, st) for i, st in starts if any(a + 0.3 < st < b - 0.3 for a, b in gaps)]
print(f"{root.split('/')[-1]}: vocal gaps >= {MIN_GAP}s:")
for a, b in gaps:
    after = [(i, st) for i, st in starts if st >= a]
    nxt = after[0] if after else None
    tail = "" if not nxt else f"-> next line {nxt[0]:2d} starts {nxt[1]:7.2f} ({nxt[1]-b:+.2f}s vs gap end)"
    print(f"  gap {a:7.2f}-{b:7.2f} ({b-a:5.1f}s) {tail}")
print(f"  lines starting inside a gap: {inside if inside else 'none'}")
