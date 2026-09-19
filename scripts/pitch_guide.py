"""Extract a lightweight melody guide (F0 contour) from the separated vocal stem.

Not the lead vocal audio itself -- just its pitch curve, sampled at a fixed
hop, so the karaoke page can play a synthesized guide tone that follows the
melody (the way a hardware karaoke machine's "guide melody" works), without
shipping a second vocal-bearing audio file.

Pure numpy/scipy autocorrelation pitch tracker (no librosa dependency, so
nothing new to install on the Runpod venv). Not lab-grade F0 estimation --
good enough for a guide tone, not for pitch-correction or scoring.
"""

import statistics

import numpy as np
import soundfile as sf
from scipy.signal import medfilt

FMIN, FMAX = 70.0, 900.0  # covers typical pop vocal range with headroom
GENDER_THRESHOLD_HZ = 200.0  # rough modal-register crossover; see classify_gender


def extract_pitch(path, hop_sec: float = 0.025, win_sec: float = 0.045) -> dict:
    x, sr = sf.read(path, always_2d=True)
    x = x.mean(axis=1).astype(np.float32)
    hop, win = int(sr * hop_sec), int(sr * win_sec)
    lag_min, lag_max = max(1, int(sr / FMAX)), min(win - 1, int(sr / FMIN))
    n = max(0, (len(x) - win) // hop)
    hz = np.zeros(n, dtype=np.float32)
    conf = np.zeros(n, dtype=np.float32)
    window = np.hanning(win).astype(np.float32)
    for i in range(n):
        frame = x[i * hop: i * hop + win]
        rms = np.sqrt(np.mean(frame * frame))
        if rms < 3e-4:
            continue
        f = (frame - frame.mean()) * window
        spec = np.fft.rfft(f, n=2 * win)
        ac = np.fft.irfft(spec * np.conj(spec))[:win]
        if ac[0] <= 0:
            continue
        ac /= ac[0]
        seg = ac[lag_min:lag_max]
        if len(seg) == 0:
            continue
        peak = int(np.argmax(seg))
        strength = float(seg[peak])
        if strength < 0.35:
            continue
        lag = lag_min + peak
        # parabolic interpolation across the peak for sub-sample lag precision
        if 0 < peak < len(seg) - 1:
            y0, y1, y2 = seg[peak - 1], seg[peak], seg[peak + 1]
            denom = (y0 - 2 * y1 + y2)
            if abs(denom) > 1e-9:
                lag = lag + 0.5 * (y0 - y2) / denom
        hz[i] = sr / lag
        conf[i] = strength

    # drop octave-jump outliers and smooth: median filter over voiced runs only
    voiced = hz > 0
    if voiced.any():
        smoothed = hz.copy()
        k = 5 if n >= 5 else (n if n % 2 == 1 else max(1, n - 1))
        if k >= 3:
            filtered = medfilt(np.where(voiced, hz, 0.0), kernel_size=k)
            smoothed = np.where(voiced, filtered, 0.0)
        # a voiced run shorter than 3 frames (~75ms) is almost always a spurious blip
        run_start = None
        for i in range(n + 1):
            v = i < n and smoothed[i] > 0
            if v and run_start is None:
                run_start = i
            if not v and run_start is not None:
                if i - run_start < 3:
                    smoothed[run_start:i] = 0.0
                run_start = None
        hz = smoothed

    return {"hopSec": hop_sec, "hz": [round(float(v), 1) for v in hz]}


def classify_gender(pitch: dict) -> str | None:
    """Rough guess at the lead vocal's register from the median voiced F0.

    Not a real singer-gender classifier -- modal male and female singing
    ranges overlap heavily, and this only ever sees the median pitch of a
    guide-tone contour, not timbre/formants. It exists to pick which
    direction "성별 전환" shifts by default (toward the other register);
    treat a wrong guess as expected on some songs, not a bug to chase.
    """
    voiced = [v for v in pitch.get("hz", []) if v > 0]
    if len(voiced) < 20:
        return None
    return "male" if statistics.median(voiced) < GENDER_THRESHOLD_HZ else "female"
