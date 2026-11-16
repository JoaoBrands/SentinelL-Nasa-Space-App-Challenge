"""Time-weighted rolling averages for simulated cabin CO2 readings."""
from collections import deque
from math import isfinite


class RollingCO2Window:
    def __init__(self, window_minutes: float = 60.0, max_sample_gap_minutes: float = 1.5):
        self.window_minutes = window_minutes
        self.max_sample_gap_minutes = max_sample_gap_minutes
        self._samples: deque[tuple[float, float]] = deque()

    def reset(self) -> None:
        self._samples.clear()

    def update(self, time_minutes: float, value_mmhg: float | None) -> tuple[float | None, float]:
        if isinstance(time_minutes, bool) or isinstance(value_mmhg, bool):
            self.reset()
            return None, 0.0
        try:
            time_minutes = float(time_minutes)
            value_mmhg = float(value_mmhg) if value_mmhg is not None else None
        except (OverflowError, TypeError, ValueError):
            self.reset()
            return None, 0.0

        if not isfinite(time_minutes) or value_mmhg is None or not isfinite(value_mmhg) or value_mmhg < 0:
            self.reset()
            return None, 0.0
        if self._samples and time_minutes < self._samples[-1][0]:
            self.reset()
        elif (
            self._samples
            and time_minutes - self._samples[-1][0] > self.max_sample_gap_minutes
        ):
            self.reset()

        if self._samples and time_minutes == self._samples[-1][0]:
            self._samples[-1] = (time_minutes, value_mmhg)
        else:
            self._samples.append((time_minutes, value_mmhg))

        cutoff = time_minutes - self.window_minutes
        while len(self._samples) > 2 and self._samples[1][0] <= cutoff:
            self._samples.popleft()

        return self.average(time_minutes)

    def average(self, time_minutes: float) -> tuple[float | None, float]:
        if not self._samples:
            return None, 0.0

        time_minutes = float(time_minutes)
        first_time = self._samples[0][0]
        covered_minutes = max(0.0, min(self.window_minutes, time_minutes - first_time))
        if covered_minutes + 1e-9 < self.window_minutes or len(self._samples) < 2:
            return None, covered_minutes

        cutoff = time_minutes - self.window_minutes
        points = list(self._samples)
        start_index = next(
            (index for index in range(len(points) - 1)
             if points[index][0] <= cutoff <= points[index + 1][0]),
            None,
        )
        if start_index is None:
            return None, covered_minutes

        left_time, left_value = points[start_index]
        right_time, right_value = points[start_index + 1]
        fraction = (cutoff - left_time) / (right_time - left_time)
        start_value = left_value + (right_value - left_value) * fraction
        previous_time = cutoff
        previous_value = start_value
        area = 0.0

        for sample_time, sample_value in points[start_index + 1:]:
            if sample_time > time_minutes:
                break
            area += (sample_time - previous_time) * (previous_value + sample_value) / 2
            previous_time = sample_time
            previous_value = sample_value

        if previous_time < time_minutes:
            area += (time_minutes - previous_time) * previous_value

        return area / self.window_minutes, covered_minutes