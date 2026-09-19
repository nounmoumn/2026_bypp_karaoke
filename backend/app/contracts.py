"""The small result contract shared with the fixture player."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PlaybackPreferences(BaseModel):
    keySemitones: int = Field(default=0, ge=-5, le=5)
    keyPreset: Literal["male", "original", "female", "custom"] = "original"
    outputMode: Literal["original", "phone"] = "original"
    lyricsMode: Literal["ko", "jp_ko", "jp"] = "ko"


class KeyPresets(BaseModel):
    male: int = Field(default=-5, ge=-5, le=5)
    original: Literal[0] = 0
    female: int = Field(default=5, ge=-5, le=5)


class Assets(BaseModel):
    instrumental: str
    original: str
    guide: str | None = None


class PipelineInfo(BaseModel):
    version: str
    separationModel: str
    alignmentModel: str


class LyricLine(BaseModel):
    id: str
    jp: str
    reading: str | None = None
    ko: str
    startSec: float | None
    endSec: float | None
    timingLevel: Literal["line"] = "line"
    timingSource: Literal["manual", "model", "unavailable"]
    reviewStatus: Literal["confirmed", "needs_review"]
    warnings: list[str] = Field(default_factory=list)
    displayGroups: list = Field(default_factory=list)

    @model_validator(mode="after")
    def check_bounds(self):
        if (self.startSec is None) != (self.endSec is None):
            raise ValueError("startSec and endSec must both be null or both set")
        if self.startSec is None:
            if self.timingSource != "unavailable" or self.reviewStatus != "needs_review":
                raise ValueError("untimed lines must be unavailable and need review")
        elif not 0 <= self.startSec < self.endSec:
            raise ValueError("invalid line bounds")
        return self


class KaraokeResult(BaseModel):
    schemaVersion: Literal["1.1"] = "1.1"
    jobId: str
    revision: int = Field(ge=1)
    title: str
    artist: str = ""
    durationSec: float = Field(gt=0)
    displayOffsetSec: float = 0
    playbackPreferences: PlaybackPreferences = Field(default_factory=PlaybackPreferences)
    keyPresets: KeyPresets = Field(default_factory=KeyPresets)
    assets: Assets
    pipeline: PipelineInfo
    lines: list[LyricLine]

    @model_validator(mode="after")
    def check_lines(self):
        ids = [line.id for line in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate line ID")
        previous_end = 0.0
        for line in self.lines:
            if line.startSec is None:
                continue
            if line.endSec > self.durationSec:
                raise ValueError(f"{line.id} exceeds audio duration")
            if line.startSec < previous_end:
                raise ValueError(f"{line.id} overlaps the previous line")
            previous_end = line.endSec
        return self
