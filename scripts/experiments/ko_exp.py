"""Run Korean alignment variants on a song WITHOUT touching production data.

Imports the deployed engine read-only, writes only under --out (default
/root/ko_dev/out). Each variant is a dict of align_lines() keyword overrides
plus optional engine monkey-patches, scored with ko_diag.

    python ko_exp.py <song> <variant> [<variant> ...]
"""

import json
import sys
from pathlib import Path

ENGINE = Path("/workspace/bypp/scripts")
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(ENGINE))

import align_full_song as engine  # noqa: E402
from ko_diag import diagnose  # noqa: E402

PIPE = Path("/workspace/bypp/data/pipeline")
OUT = Path("/root/ko_dev/out")


def load_song(song: str):
    d = PIPE / song
    lines = (d / "lyrics_ko.txt").read_text(encoding="utf-8").splitlines()
    prod = json.loads((d / "karaoke.json").read_text(encoding="utf-8"))
    sections = [w["lastLine"] - w["firstLine"] for w in prod.get("sectionWindows", [])]
    audio = next(d.glob("original.*"))
    return d, lines, sections, audio, d / "stems" / "htdemucs" / "original" / "vocals.wav"


VARIANTS = {
    "base": lambda a: dict(alignment_audio=a["audio"], section_lengths=a["sections"]),
    "stem": lambda a: dict(alignment_audio=None, section_lengths=a["sections"]),
}


def run(song: str, variant: str):
    d, lines, sections, audio, vocals = load_song(song)
    args = {"audio": audio, "sections": sections}
    if variant == "v3":
        import korean_engine
        data = korean_engine.align_lines_v3(vocals, lines, device="cuda", section_lengths=sections,
                                            alignment_audio=audio)
    else:
        kw = VARIANTS[variant](args)
        data = engine.align_lines(vocals, lines, device="cuda", language="ko", **kw)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{song}__{variant}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    summary, _ = diagnose(d, vocals, quiet=True, karaoke=path)
    return summary, data


if __name__ == "__main__":
    song = sys.argv[1]
    for variant in sys.argv[2:]:
        summary, data = run(song, variant)
        print(f"## {song} / {variant}  ({data['elapsedSec']}s)  src={data['alignmentSources']}")
        print(json.dumps(summary, separators=(",", ":")))
