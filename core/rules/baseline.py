"""Standalone baseline utility using up to 14 SQI-filtered samples.

This utility is not connected to the runtime monitoring rules.
"""
from collections import deque
import numpy as np
from core.config import SQI_MIN


class BaselineStore:
    def __init__(self, window_size: int = 14):
        self.window_size = window_size
        self._data: dict = {}

    def update(self, crew_id: str, metric: str, value: float, sqi: float = 1.0) -> None:
        # Do not update the baseline when signal quality is below the minimum.
        if sqi < SQI_MIN:
            return

        key = f"{crew_id}_{metric}"
        if key not in self._data:
            self._data[key] = deque(maxlen=self.window_size)
        
        self._data[key].append(value)

    def get_robust_baseline(self, crew_id: str, metric: str) -> tuple[float | None, float | None]:
        """Return the median and MAD for the available samples."""
        key = f"{crew_id}_{metric}"
        vals = list(self._data.get(key, []))
        
        if len(vals) < 2:
            return None, None
        
        arr = np.array(vals)
        median = np.median(arr)
        
        # Median absolute deviation is robust to outliers in noisy signals.
        mad = np.median(np.abs(arr - median))
        
        return float(median), float(mad)