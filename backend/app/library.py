"""Discover processed songs (scripts/process_song.py output directories) and
serve their data/audio through the API instead of a standalone HTML file.

A song directory is anything under one of LIBRARY_ROOTS that has both
karaoke.json and assets.json (written by process_song.py's last stage).
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LIBRARY_ROOTS = [REPO_ROOT / "data" / "songs", REPO_ROOT / "data" / "pipeline"]
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.+-]+$")  # no path separators, no ".."


class SongNotFound(Exception):
    pass


def _song_dir(song_id: str) -> Path:
    if not SAFE_NAME.match(song_id):
        raise SongNotFound(song_id)
    for root in LIBRARY_ROOTS:
        d = root / song_id
        if (d / "karaoke.json").is_file() and (d / "assets.json").is_file():
            return d
    raise SongNotFound(song_id)


def list_songs() -> list[dict]:
    out = []
    seen = set()
    for root in LIBRARY_ROOTS:
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            if d.name in seen or not (d / "karaoke.json").is_file() or not (d / "assets.json").is_file():
                continue
            try:
                data = json.loads((d / "karaoke.json").read_text(encoding="utf-8"))
                assets = json.loads((d / "assets.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            seen.add(d.name)
            out.append({"id": d.name, "title": assets.get("title") or d.name,
                       "durationSec": data.get("durationSec"), "lines": len(data.get("lines", []))})
    return out


def load_song(song_id: str) -> dict:
    """The same payload shape karaoke_template.html expects, with audio file
    names rewritten to this API's streaming URLs."""
    d = _song_dir(song_id)
    data = json.loads((d / "karaoke.json").read_text(encoding="utf-8"))
    assets = json.loads((d / "assets.json").read_text(encoding="utf-8"))
    pitch = None
    if assets.get("hasPitchGuide") and (d / "pitch_guide.json").is_file():
        pitch = json.loads((d / "pitch_guide.json").read_text(encoding="utf-8"))

    def audio_url(filename: str) -> str:
        return f"/api/songs/{song_id}/audio/{filename}"

    lines = [{"text": l["text"], "start": l["start"], "end": l["end"],
              "chars": [{"c": c["c"], "s": c["s"], "e": c["e"]} for c in l["chars"]],
              "ko": l.get("ko", [])} for l in data["lines"]]
    return {
        "id": song_id,
        "title": assets.get("title") or song_id,
        "language": assets.get("language", data.get("language", "ja")),
        "durationSec": data["durationSec"],
        "lines": lines,
        "qa": data.get("qa", ""),
        "orig": {"file": audio_url(assets["origFile"]), "label": "원곡"},
        "mrShifts": [{"semitone": s["semitone"], "file": audio_url(s["file"])} for s in assets.get("mrShifts", [])],
        "pitch": pitch,
        "originGender": assets.get("originGender"),
    }


def audio_path(song_id: str, filename: str) -> Path:
    d = _song_dir(song_id)
    assets = json.loads((d / "assets.json").read_text(encoding="utf-8"))
    allowed = {assets["origFile"]} | {s["file"] for s in assets.get("mrShifts", [])}
    if filename not in allowed:
        raise SongNotFound(f"{song_id}/{filename}")
    path = d / filename
    if not path.is_file():
        raise SongNotFound(f"{song_id}/{filename}")
    return path
