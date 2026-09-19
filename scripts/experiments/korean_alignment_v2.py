"""Offline Korean alignment experiments; never writes production song data."""

import argparse
import difflib
import json
import math
import re
import statistics
import unicodedata
from pathlib import Path

import torch
import whisperx


def transcribe(vocals: Path, output: Path, device: str) -> None:
    model = whisperx.load_model(
        "medium", device, compute_type="float16" if device == "cuda" else "int8",
        language="ko",
    )
    result = model.transcribe(whisperx.load_audio(str(vocals)), batch_size=8)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def comparison_text(text: str) -> str:
    return re.sub(r"[^가-힣a-z0-9]", "", text.lower())


def alignment_units(text: str) -> tuple[str, list[tuple[str, int]]]:
    """Return jamo/Latin CTC text and display characters with token widths."""
    target, display = [], []
    for char in text:
        if "가" <= char <= "힣":
            tokens = unicodedata.normalize("NFD", char)
        elif char.isascii() and char.isalnum():
            tokens = char.lower()
        else:
            continue
        target.append(tokens)
        display.append((char, len(tokens)))
    return "".join(target), display


def redistribute_display_timing(text: str, chars: list[dict]) -> list[str]:
    """Repair grapheme stalls without changing the line's acoustic window."""
    notes = []
    text_to_timing, timing_index = {}, 0
    for text_index, char in enumerate(text):
        if ("가" <= char <= "힣") or (char.isascii() and char.isalnum()):
            text_to_timing[text_index] = timing_index
            timing_index += 1

    def spread(indices: list[int], label: str) -> None:
        timed = [chars[index] for index in indices if chars[index]["s"] is not None]
        if len(timed) < 2:
            return
        start, end = timed[0]["s"], timed[-1]["e"]
        if end <= start:
            return
        step = (end - start) / len(indices)
        for offset, index in enumerate(indices):
            chars[index]["s"] = start + step * offset
            chars[index]["e"] = start + step * (offset + 1)
        notes.append(label)

    # Latin spelling is not phonemic. CTC often gives most of an English
    # phrase to its first one or two letters, so distribute its visible wipe.
    for match in re.finditer(r"[A-Za-z]+(?:\s+[A-Za-z]+)*", text):
        indices = [text_to_timing[index] for index in range(match.start(), match.end())
                   if index in text_to_timing]
        spread(indices, f"latin phrase redistributed: {match.group()}")

    # Preserve normal Korean timing. Only repair a word when one non-final
    # syllable monopolises the word and makes the karaoke wipe visibly stall.
    for match in re.finditer(r"[가-힣]+", text):
        indices = [text_to_timing[index] for index in range(match.start(), match.end())]
        if len(indices) < 2:
            continue
        durations = [max(0.0, chars[index]["e"] - chars[index]["s"]) for index in indices]
        longest_position = max(range(max(1, len(durations) - 1)), key=durations.__getitem__)
        longest = durations[longest_position]
        typical = statistics.median(duration for position, duration in enumerate(durations)
                                    if position != longest_position)
        if longest > 1.2 and longest > 4 * max(typical, 0.05):
            spread(indices, f"Korean word stall redistributed: {match.group()}")
    return notes


def partition_lines(lines: list[str], segments: list[dict]) -> list[dict]:
    """Assign every lyric line to one ASR segment without trusting blank lines."""
    n, m, impossible = len(lines), len(segments), -1e9
    if not m or n < m:
        raise ValueError(f"cannot partition {n} lyric lines over {m} ASR segments")
    dp = [[impossible] * (n + 1) for _ in range(m + 1)]
    previous = [[None] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = 0.0
    max_group = max(10, math.ceil(n / m) + 5)
    for segment_index, segment in enumerate(segments):
        heard = comparison_text(segment["text"])
        duration = segment["end"] - segment["start"]
        for first_line in range(n + 1):
            if dp[segment_index][first_line] <= impossible / 2:
                continue
            remaining_segments = m - segment_index - 1
            largest = min(max_group, n - first_line - remaining_segments)
            for count in range(1, largest + 1):
                expected = comparison_text("".join(lines[first_line:first_line + count]))
                similarity = difflib.SequenceMatcher(None, expected, heard, autojunk=False).ratio()
                length_penalty = abs(math.log((len(expected) + 1) / (len(heard) + 1)))
                seconds_per_char = duration / max(len(expected), 1)
                rate_penalty = max(0.0, 0.12 - seconds_per_char) + max(0.0, seconds_per_char - 0.75)
                score = 2.5 * similarity - 0.35 * length_penalty - 1.5 * rate_penalty
                last_line = first_line + count
                candidate = dp[segment_index][first_line] + score
                if candidate > dp[segment_index + 1][last_line]:
                    dp[segment_index + 1][last_line] = candidate
                    previous[segment_index + 1][last_line] = (
                        first_line, count, similarity, seconds_per_char,
                    )
    if previous[m][n] is None:
        raise ValueError("no monotonic lyric/ASR partition found")
    groups, cursor = [], n
    for segment_index in range(m, 0, -1):
        first, count, similarity, rate = previous[segment_index][cursor]
        segment = segments[segment_index - 1]
        groups.append({
            "firstLine": first,
            "lastLine": first + count,
            "start": segment["start"],
            "end": segment["end"],
            "asrText": segment["text"],
            "match": round(similarity, 3),
            "secondsPerCharacter": round(rate, 3),
        })
        cursor = first
    return list(reversed(groups))


def align_candidate(audio_path: Path, lyrics_json: Path, asr_path: Path,
                    output: Path, device: str) -> None:
    source = json.loads(lyrics_json.read_text(encoding="utf-8"))
    lines = [line["text"] for line in source["lines"]]
    segments = json.loads(asr_path.read_text(encoding="utf-8"))["segments"]
    groups = partition_lines(lines, segments)
    model, metadata = whisperx.load_align_model(
        language_code="ko", device=device,
        model_name="raniczan/wav2vec2-xls-r-300m-korean-english",
    )
    audio = whisperx.load_audio(str(audio_path))
    aligned_lines = []
    for group_index, group in enumerate(groups):
        selected = lines[group["firstLine"]:group["lastLine"]]
        encoded = [alignment_units(line) for line in selected]
        target = "".join(item[0] for item in encoded)
        result = whisperx.align(
            [{"start": group["start"], "end": group["end"], "text": target}],
            model, metadata, audio, device, return_char_alignments=True,
        )
        chars = [char for segment in result["segments"] for char in segment["chars"]
                 if ("\u1100" <= char.get("char", "") <= "\u11ff")
                 or (char.get("char", "").isascii() and char.get("char", "").isalnum())]
        expected_count = sum(len(item[0]) for item in encoded)
        if len(chars) != expected_count:
            raise RuntimeError(f"CTC token mismatch in lines {group['firstLine'] + 1}-"
                               f"{group['lastLine']}: {len(chars)}/{expected_count}")
        position = 0
        for line_index, (line, (_, display)) in enumerate(zip(selected, encoded), group["firstLine"]):
            timing_by_char = []
            for visible, width in display:
                unit = chars[position:position + width]
                position += width
                timed = [char for char in unit if "start" in char]
                timing_by_char.append({
                    "c": visible,
                    "s": min((char["start"] for char in timed), default=None),
                    "e": max((char["end"] for char in timed), default=None),
                    "score": round(statistics.mean(char.get("score", 0) for char in timed), 3)
                             if timed else 0,
                })
            repairs = redistribute_display_timing(line, timing_by_char)
            timed = [char for char in timing_by_char if char["s"] is not None]
            aligned_lines.append({
                "index": line_index,
                "text": line,
                "start": min((char["s"] for char in timed), default=None),
                "end": max((char["e"] for char in timed), default=None),
                "chars": timing_by_char,
                "group": group_index,
                "repairs": repairs,
            })
    aligned_lines.sort(key=lambda line: line["index"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "method": "Korean V2: ASR monotonic line partition + local jamo/Latin CTC",
        "sourceUnmodified": True,
        "groups": groups,
        "lines": aligned_lines,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vocals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--align-audio", type=Path)
    parser.add_argument("--lyrics-json", type=Path)
    parser.add_argument("--asr", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    args = parser.parse_args()
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    if args.align_audio and args.lyrics_json and args.asr:
        align_candidate(args.align_audio, args.lyrics_json, args.asr, args.output, args.device)
    else:
        transcribe(args.vocals, args.output, args.device)


if __name__ == "__main__":
    main()
