"""Score data/songs/*/karaoke.json on the human-reviewed PoC lines (lines only; the page itself is untouched)."""
import csv, json, statistics
SONGS = [("bansanka", "bansanka/segment_A_reference_reviewed.csv", 0, 8.0),
         ("moon_landing_plan", "moon_landing_plan/segment_B_reference_reviewed.csv", 6, 41.9),
         ("hoshimachi_no_eki", "hoshimachi_no_eki/segment_A_reference_reviewed.csv", 3, 27.24)]
S, E = [], []
for name, ref, first, off in SONGS:
    L = json.load(open(f"data/songs/{name}/karaoke.json", encoding="utf-8"))["lines"]
    refs = list(csv.DictReader(open(f"data/poc/{ref}", encoding="utf-8-sig")))
    se = [abs(L[first + k]["start"] - off - float(r["reference_start"])) for k, r in enumerate(refs)]
    ee = [abs(L[first + k]["end"] - off - float(r["reference_end"])) for k, r in enumerate(refs)]
    S += se; E += ee; n = len(refs)
    print(f"{name:18s} start<=0.5 {sum(e<=.5 for e in se):2d}/{n}  start>1s {sum(e>1 for e in se)}  "
          f"end<=0.7 {sum(e<=.7 for e in ee):2d}/{n}  start med {statistics.median(se):.3f}  end med {statistics.median(ee):.3f}")
n = len(S)
print(f"{'POOLED':18s} start<=0.5 {sum(e<=.5 for e in S)}/{n}  start>1s {sum(e>1 for e in S)}  end<=0.7 {sum(e<=.7 for e in E)}/{n}")
