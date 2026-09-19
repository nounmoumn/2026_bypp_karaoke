"""Suggest omitted sung repeats from periodicity in a suspicious vocal window.

The count is a review candidate, never a transcript edit. A sustained note or
rhythmic accompaniment can also be periodic, so the lyric/timing still needs
listening before a repeat override is used.
"""

from math import gcd

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, stft


def suggest_repeat(vocals, start: float, end: float) -> dict | None:
    window_start = max(0.0, start - 1.5)  # global alignment may start at repetition two
    with sf.SoundFile(vocals) as source:
        source.seek(int(window_start * source.samplerate))
        x = source.read(int((end - window_start) * source.samplerate), dtype="float32", always_2d=True).mean(axis=1)
        sr = source.samplerate
    if len(x) < 8 * sr or np.sqrt(np.mean(x * x)) < 0.001:
        return None
    if sr != 16000:
        divisor = gcd(sr, 16000)
        x = resample_poly(x, 16000 // divisor, sr // divisor)
        sr = 16000
    hop = max(1, round(0.04 * sr))
    _, _, spectrum = stft(x, sr, nperseg=1024, noverlap=1024 - hop)
    features = np.log1p(np.abs(spectrum[:200]) * 1000)
    features = (features - features.mean(axis=1, keepdims=True)) / (features.std(axis=1, keepdims=True) + 0.01)
    features /= np.linalg.norm(features, axis=0, keepdims=True) + 1e-6
    lag_min = round(1.0 * sr / hop)
    lag_max = min(round(5.0 * sr / hop), features.shape[1] // 2)
    if lag_max <= lag_min:
        return None
    scores = np.array([np.mean(np.sum(features[:, :-lag] * features[:, lag:], axis=0))
                       for lag in range(lag_min, lag_max)])
    best = int(scores.argmax())
    peak, typical, high = float(scores[best]), float(np.median(scores)), float(np.quantile(scores, 0.9))
    period = (lag_min + best) * hop / sr
    count = round((end - window_start) / period)
    if not (2.5 <= period <= 5.0 and 2 <= count <= 8 and peak - typical >= 0.15 and peak - high >= 0.05):
        return None
    return {"suggestedRepeatCount": count, "acousticPeriodSec": round(period, 2),
            "periodicityMargin": round(peak - typical, 2), "countStatus": "unverified_candidate"}
