import type { LyricLine } from "./types";

export function lineAtTime(lines: LyricLine[], audioTime: number, offset: number): LyricLine | null {
  return (
    lines.find(
      (line) =>
        line.startSec !== null &&
        line.endSec !== null &&
        audioTime >= line.startSec + offset &&
        audioTime < line.endSec + offset,
    ) ?? null
  );
}

export function nextLine(lines: LyricLine[], audioTime: number, offset: number): LyricLine | null {
  return lines.find((line) => line.startSec !== null && line.startSec + offset > audioTime) ?? null;
}

export function clock(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}
