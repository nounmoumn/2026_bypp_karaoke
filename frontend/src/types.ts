export type LyricsMode = "ko" | "jp_ko" | "jp";

export interface LyricLine {
  id: string;
  jp: string;
  reading: string | null;
  ko: string;
  startSec: number | null;
  endSec: number | null;
  timingSource: "manual" | "model" | "unavailable";
  reviewStatus: "confirmed" | "needs_review";
}

export interface KaraokeResult {
  schemaVersion: "1.1";
  jobId: string;
  title: string;
  artist: string;
  durationSec: number;
  displayOffsetSec: number;
  playbackPreferences: { lyricsMode: LyricsMode };
  assets: { instrumental: string; original: string };
  lines: LyricLine[];
}
