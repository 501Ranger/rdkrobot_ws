import numpy as np
from typing import List, Tuple


class VadCalibrator:
    """Helper class to collect VAD ambient noise measurements and compute thresholds."""

    def __init__(self, calibration_chunks: int, noise_threshold: float, vad_threshold_scale: float) -> None:
        self.calibration_chunks = max(4, calibration_chunks)
        self.noise_threshold = noise_threshold
        self.vad_threshold_scale = vad_threshold_scale

    def compute_threshold(self, calibration_rms: List[float]) -> Tuple[float, float, float]:
        """Compute the noise threshold based on collected ambient noise RMS values."""
        values = sorted(float(item) for item in calibration_rms if item >= 0.0)
        if not values:
            return float(self.noise_threshold), 0.0, 1.0

        # Filter out transient spikes by taking the median of the bottom 70% of chunks
        lower_count = max(1, int(len(values) * 0.7))
        stable_floor = values[:lower_count]
        ambient_rms = float(np.median(stable_floor))
        threshold = max(ambient_rms * self.vad_threshold_scale, float(self.noise_threshold))
        spread = values[-1] / max(ambient_rms, 1.0)
        return threshold, ambient_rms, spread
