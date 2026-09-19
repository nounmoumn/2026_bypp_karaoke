"""Find vocal-active regions that received no aligned characters (label-free)."""
import json, sys
import numpy as np, soundfile as sf
root, vocals = sys.argv[1], sys.argv[2]
x, sr = sf.read(f"{root}/{vocals}", always_2d=True); x = x.mean(1)
h = int(sr * 0.02); n = len(x) // h
db = 20 * np.log10(np.sqrt((x[:n*h].reshape(n, h) ** 2).mean(1)) + 1e-9)
db = np.convolve(db, np.ones(5) / 5, "same"); act = db > db.max() - 35
L = json.load(open(f"{root}/alignment_full_song_global.json", encoding="utf-8"))["lines"]
covered = np.zeros(n, bool)
for l in L:
    for c in l["chars"]:
        if c["s"] is not None:
            covered[int(c["s"]/0.02):int(max(c["e"], c["s"]+0.02)/0.02)+1] = True
orphan = act & ~covered
regs, s = [], None
for i, o in enumerate(orphan):
    if o and s is None: s = i
    if not o and s is not None:
        if (i - s) * 0.02 >= 1.0: regs.append((s*0.02, i*0.02))
        s = None
dens = [(l["index"], len(l.get("aligned_text", l["text"])) / max(0.1, l["end"]-l["start"])) for l in L if l["start"] is not None]
print(root.split('/')[-1], "orphan vocal regions >=1s:", [(round(a,1), round(b,1)) for a, b in regs] or "none")
print("  lines faster than 9 chars/s:", [(i, round(d,1)) for i, d in dens if d > 9] or "none")
