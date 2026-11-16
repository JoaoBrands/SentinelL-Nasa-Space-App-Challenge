"""Timeline simulator - plays a scenario in real time."""
import asyncio
from typing import Callable, Optional

from core.config import (
    BED_FAN_LOCAL_CO2_TARGET_MMHG,
    BED_FAN_LOCAL_WASHOUT_MINUTES,
    DEFAULT_SPEED,
    MODULE_VENTILATION_CO2_TARGET_MMHG,
    MODULE_VENTILATION_RESPONSE_MINUTES,
    TICK_INTERVAL_SEC,
)
from core.sim.scenarios import load_scenario


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class SimulatorEngine:
    def __init__(self):
        self.scenario: Optional[dict] = None
        self.current_t: float = 0.0
        self.running: bool = False
        self.speed: float = DEFAULT_SPEED
        self._seen_symptoms: list[dict] = []
        self._fan_started_t: float | None = None
        self._fan_initial_local_co2: float | None = None
        self._module_vent_started_t: float | None = None
        self._module_vent_initial_co2: float | None = None

    def load(self, scenario_id: str) -> None:
        self.scenario = load_scenario(scenario_id)
        self.current_t = 0.0
        self._seen_symptoms = []
        self._fan_started_t = None
        self._fan_initial_local_co2 = None
        self._module_vent_started_t = None
        self._module_vent_initial_co2 = None

    def activate_fan(self) -> None:
        """Apply an illustrative local airflow intervention around Ana's sleep area."""
        if not self.scenario:
            return
        metrics = self._interpolated_metrics()
        local_co2 = metrics.get("ana_local_co2")
        if not isinstance(local_co2, (int, float)):
            return
        self._fan_started_t = self.current_t
        self._fan_initial_local_co2 = float(local_co2)

    def activate_module_ventilation(self) -> None:
        """Apply an illustrative module-level ventilation response."""
        if not self.scenario:
            return
        module_co2 = self._interpolated_metrics().get("module2_co2")
        if not isinstance(module_co2, (int, float)):
            return
        self._module_vent_started_t = self.current_t
        self._module_vent_initial_co2 = float(module_co2)

    def _interpolated_metrics(self) -> dict:
        if not self.scenario:
            return {}
        metrics: dict = {}
        for phase in self.scenario["phases"]:
            t0, t1 = phase["t0"], phase["t1"]
            if t0 <= self.current_t <= t1:
                frac = 0.0 if t1 == t0 else (self.current_t - t0) / (t1 - t0)
                for key, val in phase.items():
                    if key in ("t0", "t1"):
                        continue
                    if isinstance(val, list) and len(val) == 2:
                        metrics[key] = _lerp(val[0], val[1], frac)
                    else:
                        metrics[key] = val
                break

        if self._fan_started_t is not None:
            elapsed = max(0.0, self.current_t - self._fan_started_t)
            progress = min(1.0, elapsed / BED_FAN_LOCAL_WASHOUT_MINUTES)
            metrics["ana_local_ventilation"] = 100.0
            if self._fan_initial_local_co2 is not None:
                metrics["ana_local_co2"] = (
                    self._fan_initial_local_co2
                    + (BED_FAN_LOCAL_CO2_TARGET_MMHG - self._fan_initial_local_co2) * progress
                )
        if self._module_vent_started_t is not None:
            elapsed = max(0.0, self.current_t - self._module_vent_started_t)
            progress = min(1.0, elapsed / MODULE_VENTILATION_RESPONSE_MINUTES)
            metrics["module2_ventilation"] = 100.0
            if self._module_vent_initial_co2 is not None:
                metrics["module2_co2"] = (
                    self._module_vent_initial_co2
                    + (MODULE_VENTILATION_CO2_TARGET_MMHG - self._module_vent_initial_co2) * progress
                )
        return metrics

    def get_state(self) -> dict:
        metrics = self._interpolated_metrics()
        interventions = {"bed_fan": None, "module_ventilation": None}
        if self._fan_started_t is not None:
            elapsed = max(0.0, self.current_t - self._fan_started_t)
            progress = min(1.0, elapsed / BED_FAN_LOCAL_WASHOUT_MINUTES)
            interventions["bed_fan"] = {
                "active": True,
                "elapsed_minutes": round(elapsed, 2),
                "washout_duration_minutes": BED_FAN_LOCAL_WASHOUT_MINUTES,
                "progress_percent": round(progress * 100, 1),
                "model": "illustrative_linear_local_washout",
                "target_co2_mmhg": BED_FAN_LOCAL_CO2_TARGET_MMHG,
            }
        if self._module_vent_started_t is not None:
            elapsed = max(0.0, self.current_t - self._module_vent_started_t)
            progress = min(1.0, elapsed / MODULE_VENTILATION_RESPONSE_MINUTES)
            interventions["module_ventilation"] = {
                "active": True,
                "elapsed_minutes": round(elapsed, 2),
                "response_duration_minutes": MODULE_VENTILATION_RESPONSE_MINUTES,
                "progress_percent": round(progress * 100, 1),
                "model": "illustrative_linear_module_ventilation",
                "target_co2_mmhg": MODULE_VENTILATION_CO2_TARGET_MMHG,
            }
        for sym in self.scenario.get("symptoms", []) if self.scenario else []:
            if sym["t"] <= self.current_t and sym not in self._seen_symptoms:
                self._seen_symptoms.append(sym)
        return {
            "t": round(self.current_t, 2),
            "metrics": metrics,
            "symptoms": list(self._seen_symptoms),
            "interventions": interventions,
            "finished": False,
        }

    async def run(self, on_tick: Callable) -> None:
        if not self.scenario:
            return
        self.running = True
        duration = self.scenario["duration_minutes"]

        while self.running and self.current_t < duration:
            await on_tick(self.get_state())
            await asyncio.sleep(TICK_INTERVAL_SEC)
            self.current_t += TICK_INTERVAL_SEC * self.speed

        final = self.get_state()
        final["finished"] = True
        await on_tick(final)
        self.running = False

    def stop(self) -> None:
        self.running = False