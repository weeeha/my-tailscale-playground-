"""Breathing-rate extraction — the bedside node's edge DSP.

Design doc §5: a respiration waveform (a CSI-derived 1-D signal where chest
motion modulates the channel) → detrend → window → spectral peak in the
0.1–0.5 Hz band → breaths/min + confidence.

Pure-Python (a windowed band DFT) so it runs on an ESP32-class gateway with no
numpy; swap in numpy/scipy later for speed without changing the interface. The
key idea: breathing is *periodic*, so integrating over a minute concentrates it
into one sharp spectral peak while noise spreads across the band — which is why
a mm-scale chest motion is recoverable even though absolute localization isn't.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

# physiological band: 0.1 Hz (6/min) … 0.5 Hz (30/min)
FMIN_HZ = 0.1
FMAX_HZ = 0.5
MIN_WINDOW_S = 15.0     # need at least this much signal to trust a rate


@dataclass(slots=True)
class BreathEstimate:
    bpm: float
    confidence: float    # 0..1, from spectral peak prominence
    ok: bool             # False ⇒ no reliable rhythm (absent / too noisy / moving)


def _detrend(x: Sequence[float]) -> list[float]:
    """Remove the linear trend (slow drift in the channel)."""
    n = len(x)
    xs = sum(range(n))
    xss = sum(i * i for i in range(n))
    ys = sum(x)
    xys = sum(i * x[i] for i in range(n))
    denom = n * xss - xs * xs
    if denom == 0:
        mean = ys / n
        return [v - mean for v in x]
    slope = (n * xys - xs * ys) / denom
    intercept = (ys - slope * xs) / n
    return [x[i] - (slope * i + intercept) for i in range(n)]


def estimate_rate(
    samples: Sequence[float],
    fs: float,
    fmin: float = FMIN_HZ,
    fmax: float = FMAX_HZ,
    step_hz: float = 1.0 / 300.0,
) -> BreathEstimate:
    """Estimate breaths/min from a respiration waveform sampled at ``fs`` Hz."""
    n = len(samples)
    if n < fs * MIN_WINDOW_S:
        return BreathEstimate(0.0, 0.0, False)

    x = _detrend(samples)

    # near-flat signal ⇒ nobody / no chest motion
    energy = sum(v * v for v in x) / n
    if energy < 1e-9:
        return BreathEstimate(0.0, 0.0, False)

    # Hann window to cut spectral leakage
    win = [0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)) for i in range(n)]
    xw = [x[i] * win[i] for i in range(n)]

    freqs: list[float] = []
    powers: list[float] = []
    f = fmin
    while f <= fmax + 1e-12:
        re = im = 0.0
        two_pi_f_over_fs = 2 * math.pi * f / fs
        for i in range(n):
            ang = two_pi_f_over_fs * i
            re += xw[i] * math.cos(ang)
            im += xw[i] * math.sin(ang)
        powers.append(re * re + im * im)
        freqs.append(f)
        f += step_hz

    peak_i = max(range(len(powers)), key=powers.__getitem__)
    peak = powers[peak_i]
    total = sum(powers) or 1e-12

    # A true breathing rhythm concentrates energy into one sharp peak; broadband
    # noise spreads it across the whole band. The peak's *share of total band
    # energy* separates the two far more robustly than peak-vs-median (which a
    # low-frequency noise bump at the band edge can fool).
    peak_fraction = peak / total
    confidence = max(0.0, min(1.0, (peak_fraction - 0.06) / 0.20))
    bpm = freqs[peak_i] * 60.0
    return BreathEstimate(round(bpm, 1), round(confidence, 2), confidence >= 0.3)


class BreathingAgent:
    """Bedside edge node: turn a CSI respiration window into a breathing event.

    In production ``samples`` come from Nexmon-CSI / ESP32-CSI amplitude on a
    stable subcarrier; here the same code runs on synthesized or real input.
    Returns None when there's no trustworthy rhythm (empty bed, restless, awake).
    """

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id

    def analyze(self, samples: Sequence[float], fs: float, now: float):
        from .model import KIND_BREATHING, SensorEvent

        est = estimate_rate(samples, fs)
        if not est.ok:
            return None
        return SensorEvent(
            now, self.node_id, KIND_BREATHING,
            {"bpm": est.bpm, "confidence": est.confidence},
        )
