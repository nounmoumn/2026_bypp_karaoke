"""Align a whole song's lyrics in one global pass, then score the lines that
have human-reviewed references.

Realistic condition for a new YouTube song: full-length vocal stem, full
lyric text from the web (may differ slightly from what is sung), no
hand-picked segment. A single global CTC Viterbi pass is monotonic by
construction, so it always reaches the last line; errors stay local instead
of drifting. Chars outside the model vocabulary (latin "Ah", "！", "ー",
spaces) are left unaligned and interpolated.

Usage:
    .venv-align/Scripts/python.exe scripts/align_full_song.py <song_dir> <full_vocals.wav> <prefix> <first_ref_index> <offset_sec> <reference_csv>
"""

import csv
import difflib
import gc
import json
import statistics
import sys
import time
import unicodedata
from pathlib import Path

import re

import numpy as np
import soundfile as sf
import torch
import whisperx

LATIN = [(re.compile(r"\b[Aa]h+\b"), "あ"), (re.compile(r"\b[Hh]a+\b"), "は"), (re.compile(r"\b[Oo]h+\b"), "お"),
         (re.compile(r"\b[Ll]a+\b"), "ら"), (re.compile(r"\b[Nn]a+\b"), "な")]
ENGLISH_KANA = {
    "in": "イン", "my": "マイ", "head": "ヘッド", "mind": "マインド",
    "hi": "ハイ", "speed": "スピード", "anarchy": "アナーキー",
    "weekend": "ウィークエンド", "slap": "スラップ", "on": "オン",
    "the": "ザ", "bass": "ベース",
}
DIGIT_KANA = {"0": "ゼロ", "1": "ワン", "2": "ツー", "3": "スリー", "4": "フォー", "5": "ファイブ",
              "6": "シックス", "7": "セブン", "8": "エイト", "9": "ナイン"}
ALIGNMENT_SCHEMA_VERSION = 2
KOREAN_ALIGNMENT_SCHEMA_VERSION = 15


def normalize(line: str) -> str:
    """Turn mixed Japanese/English lyric text into CTC-readable Japanese."""
    for pat, kana in LATIN:
        line = pat.sub(kana, line)
    line = re.sub(r"[A-Za-z]+", lambda m: ENGLISH_KANA.get(m.group().lower(), "ア"), line)
    line = re.sub(r"[0-9]", lambda m: DIGIT_KANA[m.group()], line)
    return re.sub(r"[^\u3040-\u30ff\u4e00-\u9fff]", "", line) or "あ"


def normalize_korean(line: str) -> str:
    """Keep original Hangul; WhisperX gives unknown syllables wildcard timing."""
    return "".join(ch for ch in line if "가" <= ch <= "힣")


def rebalance_short_korean_lines(lines: list[dict], windows: list[dict]) -> list[str]:
    """Prevent a CTC tie from squeezing a sung line into a fraction of a second.

    Project stanza boundaries onto a minimum-duration sequence, changing as
    little as possible. Character times are scaled inside adjusted lines.
    The floor is deliberately weak: it cannot establish a human reference.
    """
    notes = []
    for window in windows:
        block = lines[window["firstLine"]:window["lastLine"]]
        if len(block) < 2 or any(l["start"] is None or l["end"] is None for l in block):
            continue
        if any(b["start"] - a["end"] > 0.8 for a, b in zip(block, block[1:])):
            continue
        minimum = [max(0.7, min(3.0, 0.22 * len(l["aligned_text"]))) for l in block]
        if all(l["end"] - l["start"] >= floor for l, floor in zip(block, minimum)):
            continue
        boundaries = [l["start"] for l in block] + [block[-1]["end"]]
        available = boundaries[-1] - boundaries[0]
        if available <= 0:
            continue
        scale = min(1.0, available / sum(minimum))
        minimum = [x * scale for x in minimum]
        cumulative = [0.0]
        for x in minimum:
            cumulative.append(cumulative[-1] + x)
        targets = [t - floor for t, floor in zip(boundaries, cumulative)]
        weights = [1e9] + [1.0] * (len(targets) - 2) + [1e9]
        pools = []
        for i, (value, weight) in enumerate(zip(targets, weights)):
            pools.append([i, i, value * weight, weight])
            while len(pools) >= 2 and pools[-2][2] / pools[-2][3] > pools[-1][2] / pools[-1][3]:
                right = pools.pop()
                left = pools[-1]
                left[1] = right[1]
                left[2] += right[2]
                left[3] += right[3]
        projected = [0.0] * len(targets)
        for first, last, weighted_sum, weight in pools:
            projected[first:last + 1] = [weighted_sum / weight] * (last - first + 1)
        updated = [value + floor for value, floor in zip(projected, cumulative)]
        updated[0], updated[-1] = boundaries[0], boundaries[-1]
        for i, line in enumerate(block):
            old_start, old_end = line["start"], line["end"]
            new_start, new_end = updated[i], updated[i + 1]
            if abs(new_start - old_start) < 0.01 and abs(new_end - old_end) < 0.01:
                continue
            duration = max(0.001, old_end - old_start)
            for key in ("chars", "phonetic_chars"):
                for char in line.get(key, []):
                    if char["s"] is None:
                        continue
                    start_fraction = min(1.0, max(0.0, (char["s"] - old_start) / duration))
                    end_fraction = min(1.0, max(start_fraction, (char["e"] - old_start) / duration))
                    char["s"] = new_start + (new_end - new_start) * start_fraction
                    char["e"] = new_start + (new_end - new_start) * end_fraction
            line["start"], line["end"] = new_start, new_end
            notes.append(f"line {line['index'] + 1}: short-line floor adjusted {old_start:.2f}-{old_end:.2f}s to {new_start:.2f}-{new_end:.2f}s")
    return notes


def korean_section_windows(vocals: Path, lines: list[str], section_lengths: list[int],
                           device: str) -> list[dict]:
    """Anchor Korean lyric stanzas to rough ASR segments, skipping ad-libs."""
    if len(section_lengths) < 2 or sum(section_lengths) != len(lines):
        return []
    compute_type = "float16" if device == "cuda" else "int8"
    asr_model = whisperx.load_model("medium", device, compute_type=compute_type, language="ko")
    asr = asr_model.transcribe(whisperx.load_audio(str(vocals)), batch_size=8)["segments"]
    del asr_model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    if len(asr) < len(section_lengths):
        return []

    blocks, off = [], 0
    for n in section_lengths:
        blocks.append("".join(lines[off:off + n]))
        off += n
    clean = lambda s: re.sub(r"[^가-힣]", "", s)
    scores = []
    for block in blocks:
        expected = clean(block)
        row = []
        for segment in asr:
            heard = clean(segment["text"][:200])
            duration = segment["end"] - segment["start"]
            row.append(difflib.SequenceMatcher(None, expected, heard, autojunk=False).ratio()
                       if duration >= max(2.0, len(expected) * 0.14) else -1.0)
        scores.append(row)

    count, width = len(blocks), len(asr)
    dp = [[-1e9] * width for _ in range(count)]
    previous = [[-1] * width for _ in range(count)]
    for j in range(width):
        dp[0][j] = scores[0][j]
    for i in range(1, count):
        for j in range(i, width):
            k = max(range(i - 1, j), key=lambda x: dp[i - 1][x])
            dp[i][j] = dp[i - 1][k] + scores[i][j]
            previous[i][j] = k
    selected = [max(range(count - 1, width), key=lambda j: dp[-1][j])]
    for i in range(count - 1, 0, -1):
        selected.append(previous[i][selected[-1]])
    selected.reverse()
    if min(scores[i][j] for i, j in enumerate(selected)) < 0.10:
        return []
    windows, off = [], 0
    for i, (n, j) in enumerate(zip(section_lengths, selected)):
        segment = asr[j]
        start, end = segment["start"], segment["end"]
        if i == count - 1 and j < width - 1 and asr[-1]["end"] - end <= 12.0:
            end = asr[-1]["end"]
        windows.append({"firstLine": off, "lastLine": off + n, "start": start, "end": end,
                        "asrSegment": j, "match": round(scores[i][j], 2)})
        off += n
    return windows


def vocal_gaps(path: Path, min_gap: float = 1.5) -> list[tuple[float, float]]:
    x, sr = sf.read(path, always_2d=True)
    x = x.mean(1)
    h = int(sr * 0.02); n = len(x) // h
    db = 20 * np.log10(np.sqrt((x[:n * h].reshape(n, h) ** 2).mean(1)) + 1e-9)
    db = np.convolve(db, np.ones(5) / 5, "same")
    act = db > db.max() - 35
    gaps, s = [], None
    for i, a in enumerate(act):
        t = i * 0.02
        if not a and s is None: s = t
        if a and s is not None:
            if t - s >= min_gap: gaps.append((s, t))
            s = None
    if s is not None: gaps.append((s, n * 0.02))
    return gaps


def korean_phrase_windows(path: Path, stanza_windows: list[dict], lines: list[str],
                          preliminary: list[tuple[float | None, float | None]]) -> dict[int, tuple[float, float]]:
    """Split a stanza at clear vocal pauses near its rough CTC boundaries.

    Singing stretches vowels, which often makes speech-trained CTC assign the
    held tail to the next lyric line.  A complete set of acoustic pauses is
    required for a stanza; ambiguous stanzas stay on the original alignment.
    """
    audio, sr = sf.read(path, always_2d=True)
    mono = audio.mean(1)
    hop = max(1, round(sr * 0.02))
    count = len(mono) // hop
    db = 20 * np.log10(np.sqrt((mono[:count * hop].reshape(count, hop) ** 2).mean(1)) + 1e-9)
    db = np.convolve(db, np.ones(5) / 5, "same")
    inferred: dict[int, tuple[float, float]] = {}
    for stanza in stanza_windows:
        first, last = stanza["firstLine"], stanza["lastLine"]
        if last - first < 2:
            continue
        lo, hi = int(stanza["start"] / 0.02), min(len(db), int(stanza["end"] / 0.02))
        if hi - lo < 20:
            continue
        threshold = float(np.percentile(db[lo:hi], 70) - 12)
        quiet = db[lo:hi] < threshold
        gaps, begin = [], None
        for j, is_quiet in enumerate(quiet):
            if is_quiet and begin is None:
                begin = j
            elif not is_quiet and begin is not None:
                if j - begin >= 10:  # at least 200 ms
                    gaps.append(((lo + begin) * 0.02, (lo + j) * 0.02))
                begin = None
        if begin is not None and len(quiet) - begin >= 10:
            gaps.append(((lo + begin) * 0.02, hi * 0.02))
        merged = []
        for a, b in gaps:
            if merged and a - merged[-1][1] <= 0.16:
                merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        gaps = merged

        weights = [max(1, len(normalize_korean(line))) for line in lines[first:last]]
        total_weight = sum(weights)
        cumulative = 0
        chosen = []
        for boundary in range(first, last - 1):
            cumulative += weights[boundary - first]
            proportional = stanza["start"] + (stanza["end"] - stanza["start"]) * cumulative / total_weight
            left_end, right_start = preliminary[boundary][1], preliminary[boundary + 1][0]
            ctc = ((left_end + right_start) / 2 if left_end is not None and right_start is not None
                   else proportional)
            # Lyric line lengths provide a stable coarse position even when
            # CTC has already shifted a held vowel into the next line.
            target = proportional
            candidates = [(abs((a + b) / 2 - target), a, b) for a, b in gaps
                          if (not chosen or a > chosen[-1][1] + 0.4)]
            if not candidates:
                chosen = []
                break
            distance, a, b = min(candidates)
            if distance > 2.0:
                chosen = []
                break
            chosen.append((a, b))
        if len(chosen) != last - first - 1:
            continue
        starts = [stanza["start"]] + [b for _, b in chosen]
        ends = [a for a, _ in chosen] + [stanza["end"]]
        if any(end - start < 1.0 for start, end in zip(starts, ends)):
            continue
        for index, start, end in zip(range(first, last), starts, ends):
            inferred[index] = (round(start, 3), round(end, 3))
    return inferred


def display_chars(ln: str, nm: str, lc: list[dict], language: str = "ja") -> list[dict]:
    """Map each displayed character to its own aligned timing.

    Spaces and punctuation get no timing (the player fills them from the
    neighbours); a latin interjection word ("Ah") shares the timing of the one
    kana it was normalised to; every other character is matched one-to-one.
    """
    jamo_timing = False
    if language == "ko":
        out, p = [], 0
        for ch in ln:
            if "가" <= ch <= "힣" and p < len(lc):
                c = lc[p]
                out.append({"c": ch, "s": c.get("start"), "e": c.get("end")})
                p += 1
            else:
                out.append({"c": ch, "s": None, "e": None})
        return out
    out, p, i = [], 0, 0
    while i < len(ln):
        ch = ln[i]
        if p < len(nm) and ch == nm[p]:
            c = lc[p]; out.append({"c": ch, "s": c.get("start"), "e": c.get("end")}); p += 1; i += 1
            continue
        word = re.match(r"[A-Za-z]+|[0-9]+", ln[i:])
        if language == "ja" and word and p < len(nm) and nm.startswith(normalize(word.group(0)), p):
            w = word.group(0)
            mapped = lc[p:p + len(normalize(w))]
            timed = [c for c in mapped if c.get("start") is not None]
            s = min((c["start"] for c in timed), default=None)
            e = max((c["end"] for c in timed), default=None)
            for j, wc in enumerate(w):
                out.append({"c": wc, "s": None if s is None else s + (e - s) * j / len(w),
                            "e": None if s is None else s + (e - s) * (j + 1) / len(w)})
            p += len(normalize(w)); i += len(w)
            continue
        out.append({"c": ch, "s": None, "e": None}); i += 1
    return out


def align_lines(vocals: Path, lines: list[str], device: str = "auto", language: str = "ja",
                section_lengths: list[int] | None = None,
                line_windows: dict[int, tuple[float, float]] | None = None,
                alignment_audio: Path | None = None) -> dict:
    """Align lyrics globally, or use ASR stanza anchors for Korean lyrics."""
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested, but PyTorch cannot access a GPU")
    use_mixture = language == "ko" and alignment_audio and Path(alignment_audio).resolve() != Path(vocals).resolve()
    audio = whisperx.load_audio(str(alignment_audio if use_mixture else vocals))
    dur = len(audio) / 16000
    started = time.perf_counter()
    if language not in ("ja", "ko"):
        raise ValueError(f"Unsupported alignment language: {language}")
    windows = (korean_section_windows(vocals, lines, section_lengths, device)
               if language == "ko" and section_lengths else [])
    line_windows = line_windows or {}
    for index, (start, end) in line_windows.items():
        if language != "ko" or not 0 <= index < len(lines) or not 0 <= start < end <= dur:
            raise ValueError(f"Invalid Korean line window at index {index}: {start}-{end}")
    if line_windows and not windows:
        raise ValueError("Korean line windows require lyric stanzas separated by blank lines")
    for w in windows:
        covered = [i for i in range(w["firstLine"], w["lastLine"]) if i in line_windows]
        if covered and len(covered) != w["lastLine"] - w["firstLine"]:
            raise ValueError("Every line in a reviewed stanza must have its own window")
    reviewed = sorted(line_windows.items())
    if any(left[1][1] > right[1][0] for left, right in zip(reviewed, reviewed[1:])):
        raise ValueError("Korean line windows must not overlap")
    model, meta = whisperx.load_align_model(language_code=language, device=device)
    norm = [normalize(ln) if language == "ja" else normalize_korean(ln) for ln in lines]
    unsupported = [i + 1 for i, text in enumerate(norm) if not text]
    if unsupported:
        raise ValueError(f"정렬 가능한 {language} 가사가 없는 줄: {unsupported}. 해당 줄을 한글로 고치거나 제거해 주세요.")
    text = "".join(norm)
    align_text = norm
    stanza_transcript = ([{"start": w["start"], "end": w["end"],
                           "text": "".join(norm[w["firstLine"]:w["lastLine"]])} for w in windows]
                         if windows else [{"start": 0.0, "end": dur, "text": text}])
    def run_alignment(transcript: list[dict], samples) -> dict:
        if language != "ko" or len(transcript) == 1:
            return whisperx.align(transcript, model, meta, samples, device,
                                  return_char_alignments=True)
        # WhisperX can mix character offsets between multiple Korean segments.
        # Align each stanza or phrase independently, then preserve their order.
        segments = []
        for item in transcript:
            result = whisperx.align([item], model, meta, samples, device,
                                    return_char_alignments=True)
            segments.extend(result["segments"])
        return {"segments": segments}

    preliminary_res = run_alignment(stanza_transcript, audio)
    preliminary_chars = [c for segment in preliminary_res["segments"] for c in segment["chars"]
                         if language != "ko" or ("가" <= c.get("char", "") <= "힣")]
    assert len(preliminary_chars) == len(text), (len(preliminary_chars), len(text))
    alignment_sources = ["original mix" if use_mixture else "vocal stem"]
    if language == "ko" and windows and use_mixture:
        stem_audio = whisperx.load_audio(str(vocals))
        alternate_res = run_alignment(stanza_transcript, stem_audio)
        alternate_chars = [c for segment in alternate_res["segments"] for c in segment["chars"]
                           if "가" <= c.get("char", "") <= "힣"]
        if len(alternate_chars) == len(text):
            offsets = [0]
            for nm in norm:
                offsets.append(offsets[-1] + len(nm))
            selected = list(preliminary_chars)
            used_alternate = False
            for w in windows:
                start_off, end_off = offsets[w["firstLine"]], offsets[w["lastLine"]]
                choices = []
                for candidate in (preliminary_chars, alternate_chars):
                    timed = [c for c in candidate[start_off:end_off] if "start" in c]
                    score = (abs(min(c["start"] for c in timed) - w["start"])
                             + abs(max(c["end"] for c in timed) - w["end"])) if timed else 1e9
                    choices.append(score)
                alignment_sources.append(
                    f"stanza {w['firstLine'] + 1}-{w['lastLine']}: mix {choices[0]:.2f}, stem {choices[1]:.2f}")
                if choices[1] + 0.15 < choices[0]:
                    selected[start_off:end_off] = alternate_chars[start_off:end_off]
                    used_alternate = True
            preliminary_chars = selected
            if used_alternate:
                alignment_sources.append("vocal stem selected per stanza")
        else:
            alignment_sources.append(f"vocal stem rejected: {len(alternate_chars)}/{len(text)} syllables")

    # For ordinary Korean uploads, derive line windows from the vocal pauses.
    # Explicit windows remain an optional review override, not a prerequisite.
    preliminary_ranges, offset = [], 0
    for nm in norm:
        part = [c for c in preliminary_chars[offset:offset + len(nm)] if "start" in c]
        offset += len(nm)
        preliminary_ranges.append((min((c["start"] for c in part), default=None),
                                   max((c["end"] for c in part), default=None)))
    automatic_windows = False
    if language == "ko" and windows and not line_windows:
        line_windows = korean_phrase_windows(vocals, windows, lines, preliminary_ranges)
        automatic_windows = bool(line_windows)

    if line_windows:
        transcript = []
        for w in windows:
            if w["firstLine"] in line_windows:
                for index in range(w["firstLine"], w["lastLine"]):
                    start, end = line_windows[index]
                    transcript.append({"start": start, "end": end, "text": align_text[index]})
            else:
                transcript.append({"start": w["start"], "end": w["end"],
                                   "text": "".join(norm[w["firstLine"]:w["lastLine"]])})
        refined_res = run_alignment(transcript, audio)
        chars = [c for segment in refined_res["segments"] for c in segment["chars"]
                 if language != "ko" or ("가" <= c.get("char", "") <= "힣")]
    else:
        chars = preliminary_chars
    assert len(chars) == len(text), (len(chars), len(text))

    jamo_timing = False
    if language == "ko":
        # The default Korean aligner emits complete Hangul syllables and tends
        # to put an entire held vowel on a neighbouring syllable.  A compact
        # jamo CTC model gives consonant/vowel evidence like Japanese morae.
        jamo_model, jamo_meta = whisperx.load_align_model(
            language_code="ko", device=device,
            model_name="raniczan/wav2vec2-xls-r-300m-korean-english")
        jamo_lines = ["".join(unicodedata.normalize("NFD", c) for c in nm) for nm in norm]
        jamo_transcript = []
        for index, jamo in enumerate(jamo_lines):
            start, end = line_windows.get(index, preliminary_ranges[index])
            jamo_transcript.append({"start": start, "end": end, "text": jamo})
        jamo_segments = []
        for item in jamo_transcript:
            result = whisperx.align([item], jamo_model, jamo_meta, audio, device,
                                    return_char_alignments=True)
            jamo_segments.extend(result["segments"])
        raw_jamo = [c for segment in jamo_segments for c in segment["chars"]
                    if "\u1100" <= c.get("char", "") <= "\u11ff"]
        expected_jamo = sum(len(value) for value in jamo_lines)
        if len(raw_jamo) == expected_jamo:
            aggregate, position = [], 0
            for nm in norm:
                for syllable in nm:
                    width = len(unicodedata.normalize("NFD", syllable))
                    unit = raw_jamo[position:position + width]
                    position += width
                    timed = [c for c in unit if "start" in c]
                    aggregate.append({"char": syllable,
                                      "start": min((c["start"] for c in timed), default=None),
                                      "end": max((c["end"] for c in timed), default=None),
                                      "score": statistics.mean(c.get("score", 0) for c in timed) if timed else 0})
            chars = aggregate
            jamo_timing = True
            alignment_sources.append("jamo CTC final timing")
        else:
            alignment_sources.append(f"jamo CTC rejected: {len(raw_jamo)}/{expected_jamo} tokens")
        del jamo_model
    gaps = vocal_gaps(vocals)

    def clip(s, e):
        """A char never spans a long vocal silence: cut it where the silence starts."""
        for a, b in gaps:
            if s < a < e:
                return max(s + 0.05, a)
        return e

    out, off = [], 0
    for i, (ln, nm) in enumerate(zip(lines, norm)):
        lc = chars[off: off + len(nm)]
        preliminary_lc = preliminary_chars[off: off + len(nm)]
        off += len(nm)
        if not jamo_timing and line_windows and i not in line_windows:
            lc = preliminary_lc
        if not jamo_timing and automatic_windows and i in line_windows:
            prelim_timed = [c for c in preliminary_lc if "start" in c]
            if (prelim_timed and min(c["start"] for c in prelim_timed) >= line_windows[i][0] - 0.15
                    and max(c["end"] for c in prelim_timed) <= line_windows[i][1] + 0.15):
                # The global pass often has better within-line syllable timing;
                # retain it when it already lies inside the acoustic phrase.
                lc = preliminary_lc
        timed = [c for c in lc if "start" in c]
        for c in timed:
            c["end"] = clip(c["start"], c["end"])
        disp = display_chars(ln, nm, lc, language)
        phonetic = [{"c": ch, "s": c.get("start"), "e": c.get("end")} for ch, c in zip(nm, lc)]
        line_start = min((c["start"] for c in timed), default=None)
        line_end = max((c["end"] for c in timed), default=None)
        if i in line_windows and timed:
            # Keep the final syllable lit through the end of the vocal phrase
            # vocal phrase, even when CTC assigns a held vowel to a blank.
            line_end = line_windows[i][1]
            for seq in (disp, phonetic):
                aligned = [c for c in seq if c["s"] is not None]
                if not aligned:
                    continue
                if automatic_windows and aligned[0]["s"] - line_windows[i][0] > 0.35:
                    aligned[0]["s"] = line_windows[i][0]
                aligned[-1]["e"] = line_end
            line_start = min(c["s"] for c in disp if c["s"] is not None)
        for gap_start, gap_end in gaps:
            if line_start is not None and line_end is not None and line_start < gap_start < gap_end < line_end:
                line_end = gap_start
                for seq in (disp, phonetic):
                    for c in seq:
                        if c["s"] is not None:
                            c["s"] = min(c["s"], gap_start)
                            c["e"] = min(c["e"], gap_start)
                break
        out.append({"index": i, "text": ln, "aligned_text": nm,
                    "start": line_start, "end": line_end,
                    "chars": disp, "phonetic_chars": phonetic})
    duration_repairs = rebalance_short_korean_lines(out, windows) if language == "ko" and windows else []
    return {"method": (f"WhisperX {language} stanza-window CTC alignment" if windows else
                       f"WhisperX {language} global single-pass over full song") + " + long-silence char clipping",
            "schemaVersion": KOREAN_ALIGNMENT_SCHEMA_VERSION if language == "ko" else ALIGNMENT_SCHEMA_VERSION,
            "language": language,
            "sectionWindows": windows,
            "lineWindows": {str(i): [start, end] for i, (start, end) in line_windows.items()},
            "lineWindowSource": "vocal-pause inference" if automatic_windows else
                                ("review override" if line_windows else None),
            "alignmentSources": alignment_sources,
            "durationRepairs": duration_repairs,
            "device": device,
            "elapsedSec": round(time.perf_counter() - started, 1), "durationSec": round(dur, 2), "lines": out}


def main() -> None:
    root = Path(sys.argv[1])
    vocals = root / sys.argv[2]
    prefix, first, offset, ref_csv = sys.argv[3], int(sys.argv[4]), float(sys.argv[5]), sys.argv[6]
    lines = (root / "lyrics_full_ja.txt").read_text(encoding="utf-8").splitlines()
    data = align_lines(vocals, lines)
    (root / "alignment_full_song_global.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    out, dur, elapsed = data["lines"], data["durationSec"], data["elapsedSec"]

    # monotonic sanity for the whole song
    starts = [l["start"] for l in out if l["start"] is not None]
    backwards = sum(1 for a, b in zip(starts, starts[1:]) if b < a)
    print(f"{root.name}: {len(lines)} lines, {elapsed:.0f}s, unaligned lines={sum(l['start'] is None for l in out)}, backwards={backwards}, last line start={starts[-1]:.1f}s of {dur:.1f}s")

    refs = list(csv.DictReader((root / ref_csv).open(encoding="utf-8-sig")))
    se, ee = [], []
    for k, r in enumerate(refs):
        p = out[first + k]
        if p["start"] is None:
            se.append(99); ee.append(99); continue
        se.append(abs(p["start"] - offset - float(r["reference_start"])))
        ee.append(abs(p["end"] - offset - float(r["reference_end"])))
    n = len(refs)
    print(f"  start<=0.5 {sum(e<=.5 for e in se)}/{n}  end<=0.7 {sum(e<=.7 for e in ee)}/{n}  "
          f"gross(>1s start) {sum(e>1 for e in se)}/{n}  start med {statistics.median(se):.3f} max {max(se):.2f}  "
          f"end med {statistics.median(ee):.3f} max {max(ee):.2f}")
    print("  per-line start err:", " ".join(f"{e:.2f}" for e in se))


if __name__ == "__main__":
    main()
