"""One command: song audio + lyric text in, synced karaoke candidate out.

    .venv-align/Scripts/python.exe scripts/process_song.py \
        --audio "path/to/song.mp3" --lyrics "path/to/lyrics.txt" --out data/songs/<name> --title "..."

Stages
  1. lyrics  - detects Japanese lines plus optional Korean readings, or direct
               Korean lyric lines. --language can override automatic detection.
  2. demucs  - two-stem separation of the full song (vocals / accompaniment).
  3. align   - one global WhisperX pass with the matching language model over
               the full vocal stem; chars are clipped at long vocal silences.
  4. repair  - vocalise / orphan-vocal rules (repair_orphans.repair).
  5. QA      - label-free checks: no backwards lines, no line starting inside
               a long vocal silence, each interlude followed by a line start.
  6. pitch   - melody-guide F0 contour extracted from the vocal stem
               (pitch_guide.py), also used for the default register preset.
  7. key     - MR rendered at original + opposite register by default;
               --full-key-range renders -6..+6 (FFmpeg rubberband).
  8. page    - karaoke.html with the data inlined (works from file://), a
               rolling two-line wipe display, original/MR + key-shift audio
               switch, and the guide-melody toggle.

--from-alignment reuses an existing aligned JSON (skips stages 2-4).
--skip-lines drops lines from the page by index (e.g. wordless intro vocalise).
Every stage after the first run is cached in --out and skipped on rerun.
"""

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from align_full_song import ALIGNMENT_SCHEMA_VERSION, KOREAN_ALIGNMENT_SCHEMA_VERSION, ENGLISH_KANA, align_lines, vocal_gaps  # noqa: E402
from repair_orphans import repair, tidy  # noqa: E402
from readings import align_reading, auto_reading  # noqa: E402
from repeat_detection import suggest_repeat  # noqa: E402
from pitch_guide import classify_gender, extract_pitch  # noqa: E402

DEMUCS = shutil.which("demucs")
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
KEY_SHIFT_SEMITONES = list(range(-6, 7))  # -6..+6, one option per semitone
JP = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
HANGUL = re.compile(r"[\uac00-\ud7a3]")
LATIN_ONLY = re.compile(r"^[A-Za-z ,.!?'~-]+$")
REPEAT = re.compile(r"([\u4e00-\u9fff][\u3040-\u309f]{1,3})\[(\d+)회\]")


def clean_lyric(line: str) -> str:
    """Expand Japanese verb repeat counts used in lyric blog transcriptions."""
    line = REPEAT.sub(lambda m: m.group(1) * min(int(m.group(2)), 12), line)
    return re.sub(r"\[\d+회\]", "", line)


def parse_lyrics(path: Path, language: str = "auto", title: str | None = None) -> tuple[list[str], list[str], str]:
    raw = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()]
    if title and raw and raw[0] == title.strip():
        raw = raw[1:]
    if len(raw) >= 4 and raw[0] == raw[2] and not raw[1] and not raw[3]:
        raw = raw[2:]  # duplicated title immediately before the first lyric line
    raw = [l for l in raw if l and not l.startswith(("출처", "http", "[", "("))]
    if language == "auto":
        language = "ja" if any(JP.search(line) for line in raw) else "ko" if any(HANGUL.search(line) for line in raw) else "ja"
    if language == "ko":
        lines = [line for line in raw if HANGUL.search(line) or LATIN_ONLY.match(line)]
        if not lines:
            raise ValueError("한국어 가사 줄을 찾지 못했습니다.")
        english_only = [i + 1 for i, line in enumerate(lines) if not HANGUL.search(line)]
        if english_only:
            raise ValueError(f"영어만 있는 가사 줄은 한국어 모델로 정렬할 수 없습니다: {english_only}. 해당 줄을 한글 독음으로 바꿔 주세요.")
        return lines, [], language
    lines, readings, i = [], [], 0
    while i < len(raw):
        l = raw[i]
        if JP.search(l) or LATIN_ONLY.match(l):
            nxt = raw[i + 1] if i + 1 < len(raw) else ""
            has_reading = bool(HANGUL.search(nxt)) and not JP.search(nxt)
            lines.append(clean_lyric(l))
            readings.append(nxt if has_reading else "")
            i += 2 if has_reading else 1
        else:
            i += 1
    if readings and all(r == "" for r in readings):
        readings = []
    if not lines:
        raise ValueError("일본어 가사 줄을 찾지 못했습니다.")
    return lines, readings, language


def korean_section_lengths(path: Path, title: str | None, lines: list[str]) -> list[int]:
    """Use blank lines between Korean lyric stanzas as optional ASR anchors."""
    raw = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    if title and raw and raw[0] == title.strip():
        raw = raw[1:]
    blocks, current = [], []
    for line in raw + [""]:
        if not line:
            if current:
                blocks.append(current)
                current = []
        elif not line.startswith(("출처", "http", "[", "(")) and (HANGUL.search(line) or LATIN_ONLY.match(line)):
            current.append(line)
    if [line for block in blocks for line in block] != lines:
        return []
    return [len(block) for block in blocks] if len(blocks) >= 2 else []


def qa_report(data: dict, vocals: Path) -> str:
    L = data["lines"]
    starts = [l["start"] for l in L]
    back = [i for i in range(1, len(L)) if starts[i] is not None and starts[i - 1] is not None and starts[i] < starts[i - 1]]
    gaps = vocal_gaps(vocals)
    inside = [l["index"] for l in L if l["start"] is not None and any(a + 0.3 < l["start"] < b - 0.3 for a, b in gaps)]
    rows = [f"lines: {len(L)}, aligned: {sum(s is not None for s in starts)}, backwards: {back or 'none'}, "
            f"starting inside a vocal silence: {inside or 'none'}"]
    for a, b in gaps:
        nxt = next((l for l in L if l["start"] is not None and l["start"] >= a), None)
        if nxt:
            rows.append(f"silence {a:6.1f}-{b:6.1f}s -> line {nxt['index'] + 1} starts {nxt['start']:6.1f}s ({nxt['start'] - b:+.2f}s)")
    rows += data.get("repairs", [])
    return "\n".join(rows)


def add_readings(data: dict, readings: list[str]) -> str:
    """Timed Korean reading per line: align the provided one, or generate it from kana."""
    n_prov = n_auto = 0
    for i, l in enumerate(data["lines"]):
        r = readings[i].strip() if i < len(readings) else ""
        source_chars = l.get("phonetic_chars", l["chars"])
        if r:
            l["ko"], l["ko_source"] = align_reading(source_chars, r), "provided"; n_prov += 1
        else:
            l["ko"], l["ko_source"] = auto_reading(source_chars), "auto"; n_auto += 1
        if l["start"] is not None and l["end"] is not None:
            for c in l["ko"]:
                if c["s"] is not None:
                    c["s"] = min(max(c["s"], l["start"]), l["end"])
                    c["e"] = min(max(c["e"], c["s"]), l["end"])
    return f"korean reading: {n_prov} lines aligned from the given reading, {n_auto} generated from kana"


def quality_flags(data: dict, vocals: Path | None = None) -> list[dict]:
    """Mark text/audio mismatches that require listening, without guessing new lyrics."""
    flags = []
    rates = [(l["end"] - l["start"]) / len(l["aligned_text"])
             for l in data["lines"] if l.get("start") is not None and l.get("end") is not None
             and len(l["aligned_text"]) >= 5 and l["end"] > l["start"]]
    typical_rate = statistics.median(rates) if rates else 0.4
    for line in data["lines"]:
        start, end = line.get("start"), line.get("end")
        if start is None or end is None:
            flags.append({"code": "unaligned", "line": line["index"], "text": line["text"]})
            continue
        char_count = len(line["aligned_text"])
        sec_per_char = (end - start) / max(char_count, 1)
        if char_count <= 12 and end - start >= 6.0 and sec_per_char >= max(0.9, 2.5 * typical_rate):
            flag = {"code": "possible_omitted_repeat_or_hold", "line": line["index"],
                    "text": line["text"], "start": start, "end": end,
                    "secondsPerCharacter": round(sec_per_char, 2),
                    "songMedianSecondsPerCharacter": round(typical_rate, 2)}
            if vocals and Path(vocals).exists():
                flag.update(suggest_repeat(vocals, start, end) or {})
            flags.append(flag)
        if data.get("language") == "ko":
            unsupported = sorted({c["c"] for c in line["chars"]
                                  if "가" <= c["c"] <= "힣" and c["s"] is None})
            if unsupported:
                flags.append({"code": "korean_syllable_unaligned", "line": line["index"],
                              "text": line["text"], "syllables": unsupported})
            english = re.findall(r"[A-Za-z]+", line["text"])
            if english:
                flags.append({"code": "english_in_korean_line_unaligned", "line": line["index"],
                              "text": line["text"], "words": english})
        else:
            unknown = sorted({word.lower() for word in re.findall(r"[A-Za-z]+", line["text"])
                              if word.lower() not in ENGLISH_KANA and word.lower() not in {"ah", "ha", "oh", "la", "na"}})
            if unknown:
                flags.append({"code": "english_pronunciation_unknown", "line": line["index"],
                              "text": line["text"], "words": unknown})
    for note in data.get("repairs", []):
        if note.startswith("orphan ") and "left as is" in note:
            flags.append({"code": "unmatched_vocal_activity", "detail": note})
    for source_line, count in data.get("repeatOverrides", {}).items():
        flags.append({"code": "repeat_override_requires_review", "sourceLine": int(source_line),
                      "count": count, "detail": "Check repeated syllables and neighboring line boundaries by ear."})
    return flags


def render_key_shifts(mr: Path, out_dir: Path, semitones: list[int] = KEY_SHIFT_SEMITONES) -> list[dict]:
    """Pre-render the backing track at each requested semitone.

    A real-time browser pitch shifter would need a custom Web Audio transport
    (losing the native seek bar / play button) and its DSP quality cannot be
    checked by ear here, so this ships the proven offline approach instead:
    FFmpeg's rubberband filter, already validated in this project's own PoC.
    0 semitones is the existing mr.wav itself (no re-encode). Cached: reruns
    skip any file that already exists. `semitones` defaults to the full
    -6..+6 range; process_song.py's own CLI narrows this to just the
    gender-opposite preset unless --full-key-range is passed, since each
    extra step costs ~10s of FFmpeg rubberband processing.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    shifts = []
    for n in semitones:
        if n == 0:
            shifts.append({"semitone": 0, "file": "mr.wav"})
            continue
        name = f"mr_shift_{'+' if n > 0 else ''}{n}.mp3"
        dest = out_dir / name
        if not dest.exists():
            subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(mr),
                            "-af", f"rubberband=pitch=2^({n}/12)", "-b:a", "128k", str(dest)], check=True)
        shifts.append({"semitone": n, "file": name})
    return shifts


def build_pitch_guide(vocals: Path, out_dir: Path) -> dict | None:
    """Cache the melody-guide F0 contour extracted from the vocal stem."""
    cache = out_dir / "pitch_guide.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    if not vocals or not Path(vocals).exists():
        return None
    pitch = extract_pitch(vocals)
    cache.write_text(json.dumps(pitch), encoding="utf-8")
    return pitch


def build_page(out: Path, title: str, data: dict, orig: tuple[str, str], mr_shifts: list[dict],
               pitch: dict | None, origin_gender: str | None, skip: set[int]):
    keep = [i for i in range(len(data["lines"])) if i not in skip]
    lines = [{"text": data["lines"][i]["text"], "start": data["lines"][i]["start"], "end": data["lines"][i]["end"],
              "chars": [{"c": c["c"], "s": c["s"], "e": c["e"]} for c in data["lines"][i]["chars"]],
              "ko": data["lines"][i].get("ko", [])} for i in keep]
    payload = {"durationSec": data["durationSec"], "lines": lines, "qa": data.get("qa", ""),
               "language": data.get("language", "ja"),
               "orig": {"file": orig[0], "label": orig[1]}, "mrShifts": mr_shifts, "pitch": pitch,
               "originGender": origin_gender}
    tpl = (Path(__file__).parent / "karaoke_template.html").read_text(encoding="utf-8")
    html = (tpl.replace("__DATA__", json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c"))
               .replace("__TITLE__", title))
    (out / "karaoke.html").write_text(html, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--audio", type=Path)
    source.add_argument("--url", help="single YouTube video URL")
    ap.add_argument("--lyrics", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--title", default=None)
    ap.add_argument("--from-alignment", type=Path, help="reuse an aligned JSON instead of stages 2-4")
    ap.add_argument("--vocals", type=Path, help="existing full-song vocal stem (with --from-alignment)")
    ap.add_argument("--mr", type=Path, help="existing full-song accompaniment stem")
    ap.add_argument("--readings", type=Path, help="optional Korean readings, one per lyric line (overrides parsed ones)")
    ap.add_argument("--repeat-overrides", type=Path, help="JSON map of 0-based source line index to sung repeat count")
    ap.add_argument("--skip-lines", default="", help="comma-separated 0-based line indices to leave off the page")
    ap.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    ap.add_argument("--language", choices=("auto", "ja", "ko"), default="auto",
                    help="lyric alignment language; auto chooses Japanese if kana/kanji appears, otherwise Korean")
    ap.add_argument("--line-windows", type=Path,
                    help="optional JSON map of 0-based Korean line indices to [start, end] vocal windows")
    ap.add_argument("--full-key-range", action="store_true",
                    help="render all 13 semitones (-6..+6) instead of just the male/female preset "
                         "(0 and the gender-opposite shift). Each extra semitone costs ~10s.")
    ap.add_argument("--ko-engine", choices=("v2", "v3"), default=os.environ.get("BYPP_KO_ENGINE", "v2"),
                    help="Korean alignment engine: v2 = align_full_song as deployed (default); "
                         "v3 = korean_engine wrapper (mix/stem auto-select + vocal-stem boundary fixes). "
                         "Korean only; the Japanese path ignores it.")
    args = ap.parse_args()

    out = args.out; out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    lines, readings, language = parse_lyrics(args.lyrics, args.language, args.title)
    line_windows_path = args.line_windows or out / "line_windows.json"
    line_windows = ({int(i): tuple(float(t) for t in span)
                    for i, span in json.loads(line_windows_path.read_text(encoding="utf-8")).items()}
                    if line_windows_path.exists() else {})
    if any(len(span) != 2 for span in line_windows.values()):
        raise ValueError("line windows must be [start, end] pairs")
    sections = korean_section_lengths(args.lyrics, args.title, lines) if language == "ko" else []
    if args.readings and language == "ko":
        raise ValueError("한국어 노래에는 별도 한글 독음 파일이 필요하지 않습니다.")
    if args.readings:
        readings = args.readings.read_text(encoding="utf-8").splitlines()
        assert len(readings) == len(lines), (len(readings), len(lines))
    overrides = {}
    if args.repeat_overrides:
        overrides = {int(k): int(v) for k, v in json.loads(args.repeat_overrides.read_text(encoding="utf-8")).items()}
        if any(i < 0 or i >= len(lines) or n < 1 or n > 12 for i, n in overrides.items()):
            raise ValueError("repeat overrides must use existing 0-based line indices and counts from 1 to 12")
        expanded_lines, expanded_readings = [], []
        if sections:
            source_index = 0
            expanded_sections = []
            for n in sections:
                expanded_sections.append(sum(overrides.get(i, 1) for i in range(source_index, source_index + n)))
                source_index += n
            sections = expanded_sections
        for i, line in enumerate(lines):
            count = overrides.get(i, 1)
            expanded_lines.extend([line] * count)
            if readings:
                expanded_readings.extend([readings[i]] * count)
        lines, readings = expanded_lines, expanded_readings
    (out / f"lyrics_{language}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[1/6] lyrics: {len(lines)} lines, language: {language}, readings: {'yes' if readings else 'no'}")

    if args.url:
        audio_name = "original.wav"
        if not (out / audio_name).exists():
            print("[download] extracting audio from URL ...", flush=True)
            subprocess.run([sys.executable, "-m", "yt_dlp", "--no-playlist", "-x", "--audio-format", "wav",
                            "-o", str(out / "original.%(ext)s"), args.url], check=True)
    else:
        audio_name = "original" + args.audio.suffix
        if not (out / audio_name).exists():
            shutil.copyfile(args.audio, out / audio_name)
    if not (out / audio_name).exists():
        raise FileNotFoundError(out / audio_name)

    if args.from_alignment:
        data = json.loads(args.from_alignment.read_text(encoding="utf-8"))
        assert [l["text"] for l in data["lines"]] == lines, "aligned JSON does not match the lyric file"
        vocals = args.vocals
        mr = args.mr
        print("[2-4/6] reused existing alignment")
    else:
        stem_dir = out / "stems" / "htdemucs" / "original"
        if not (stem_dir / "vocals.wav").exists():
            print("[2/6] demucs two-stem separation ...", flush=True)
            demucs = [DEMUCS] if DEMUCS else [sys.executable, "-m", "demucs"]
            subprocess.run([*demucs, "--two-stems=vocals", "-o", str(out / "stems"), str(out / audio_name)],
                           check=True, capture_output=True)
        vocals, mr = stem_dir / "vocals.wav", stem_dir / "no_vocals.wav"
        raw = out / "alignment_raw.json"
        cached = json.loads(raw.read_text(encoding="utf-8")) if raw.exists() else None
        expected_schema = KOREAN_ALIGNMENT_SCHEMA_VERSION if language == "ko" else ALIGNMENT_SCHEMA_VERSION
        expected_windows = {str(i): list(span) for i, span in line_windows.items()}
        if (cached and cached.get("schemaVersion") == expected_schema
                and cached.get("language", "ja") == language
                and [l["text"] for l in cached["lines"]] == lines
                and (cached.get("koEngineVersion") == 3) == (language == "ko" and args.ko_engine == "v3")
                and (not line_windows or cached.get("lineWindows", {}) == expected_windows)):
            data = cached
            print("[3/6] global alignment: reused alignment_raw.json")
        else:
            print("[3/6] global alignment ...", flush=True)
            if language == "ko" and args.ko_engine == "v3":
                from korean_engine import align_lines_v3
                data = align_lines_v3(vocals, lines, device=args.device, section_lengths=sections,
                                      line_windows=line_windows, alignment_audio=out / audio_name)
            else:
                data = align_lines(vocals, lines, device=args.device, language=language,
                                   section_lengths=sections, line_windows=line_windows,
                                   alignment_audio=(out / audio_name if language == "ko" else None))
            raw.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"      {data['elapsedSec']:.0f}s")
        # The Japanese cleanup heuristics assume kana vocalise timing. Korean
        # stanza windows already constrain line positions; leave their CTC
        # character times intact and report suspicious spans for review.
        fixes = repair(data, vocals) + tidy(data) if language == "ja" else data.get("durationRepairs", [])
        data["repairs"] = fixes
        print("[4/6] repair:", *(fixes or ["nothing to repair"]), sep="\n      ")

    ko_note = add_readings(data, readings) if language == "ja" else "Korean lyrics aligned directly"
    data["language"] = language
    data["repeatOverrides"] = overrides
    data["qualityFlags"] = quality_flags(data, vocals)
    data["qa"] = qa_report(data, vocals) + "\n" + ko_note + f"\nquality flags: {len(data['qualityFlags'])}"
    (out / "karaoke.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "quality_flags.json").write_text(json.dumps(data["qualityFlags"], ensure_ascii=False, indent=2), encoding="utf-8")
    print("[5/6] QA:\n      " + data["qa"].replace("\n", "\n      "))

    # pitch/gender must be known before deciding which key shifts to render by default
    pitch = build_pitch_guide(vocals, out) if vocals else None
    origin_gender = classify_gender(pitch) if pitch else None
    print(f"[6/8] pitch guide: {'extracted' if pitch else 'skipped (no vocal stem)'}"
          f", guessed register: {origin_gender or 'unknown'} (rough median-F0 heuristic, verify by ear)")

    mr_shifts = []
    if mr and Path(mr).exists():
        local_mr = out / "mr.wav"
        if Path(mr).resolve() != local_mr.resolve():
            shutil.copyfile(mr, local_mr)
        if args.full_key_range:
            wanted = KEY_SHIFT_SEMITONES
            print("[7/8] key-shift MR renders (-6..+6 semitones, full range requested) ...", flush=True)
        else:
            wanted = sorted({0, 4 if origin_gender == "male" else -4})
            print(f"[7/8] key-shift MR renders ({wanted}, gender-only default) ...", flush=True)
        mr_shifts = render_key_shifts(local_mr, out, wanted)

    skip = {int(x) for x in args.skip_lines.split(",") if x.strip()}
    title = args.title or (args.audio.stem if args.audio else out.name)
    build_page(out, title, data, (audio_name, "원곡"), mr_shifts, pitch, origin_gender, skip)
    # a small manifest so a remote retrieval step (process_url_runpod.py) and the backend
    # song library (library.py) know which extra assets this song has, without re-parsing
    # the full page or karaoke.json
    (out / "assets.json").write_text(json.dumps(
        {"origFile": audio_name, "mrShifts": mr_shifts, "hasPitchGuide": pitch is not None,
         "originGender": origin_gender, "title": title, "language": language}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[8/8] page: {out / 'karaoke.html'}  (total {time.perf_counter() - t0:.0f}s)")


if __name__ == "__main__":
    main()
