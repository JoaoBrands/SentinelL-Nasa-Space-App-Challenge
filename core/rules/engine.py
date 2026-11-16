"""Layer 1 - Deterministic rules engine with AI cache integration."""
import math

from core.config import (
    CO2_GENERAL_LIMIT_1H_MMHG,
    SPO2_CRITICAL_PCT,
    HR_CRITICAL_BPM,
    IMMOBILITY_THRESHOLD_H,
    VENTILATION_LOW_PCT,
)
from core.rules.cascade import get_cascade
from core.rules.co2_window import RollingCO2Window
from core.ai.explainer import generate_explanation
from core.rules.domino import get_illustrative_domino_scenario

_STATUS_RANK = {"NORMAL": 0, "OBSERVE": 1, "WARNING": 2, "CRITICAL": 3}


def _is_finite_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _valid_spo2(value) -> bool:
    return _is_finite_number(value) and 0 <= value <= 100


def _valid_heart_rate(value) -> bool:
    return _is_finite_number(value) and value > 0


def _valid_local_co2(value) -> bool:
    return _is_finite_number(value) and value >= 0


def _vital_signal(metrics: dict, key: str, unit: str, validator) -> dict:
    if key not in metrics:
        return {"status": "NOT_MONITORED", "value": None, "unit": unit}

    value = metrics[key]
    if not validator(value):
        return {"status": "INVALID", "value": None, "unit": unit}

    return {"status": "SYNTHETIC", "value": round(value, 1), "unit": unit}


class RulesEngine:
    def __init__(self, profiles: dict, rule_evidence: dict | None = None):
        self.profiles = profiles
        self.rule_evidence = rule_evidence or {}
        self.module_co2_window = RollingCO2Window(window_minutes=60.0)
        # Cache to avoid calling Ollama every second and freezing the UI
        self._ai_memory = {}

    def _enrich_alert_with_ai(self, alert: dict) -> dict:
        rule_id = alert.get("rule_id")
        evidence = self.rule_evidence.get(rule_id, {})
        alert["evidence_classification"] = evidence.get(
            "classification", "Illustrative prototype rule"
        )
        alert["evidence_note"] = evidence.get(
            "note", "No NASA source is linked to this rule."
        )
        alert["source_ids"] = evidence.get("source_ids", [])

        if rule_id in self._ai_memory:
            alert.update(self._ai_memory[rule_id])
            return alert

        print(f"Calling local AI for rule: {rule_id}...")
        ai_data = generate_explanation(alert)
        self._ai_memory[rule_id] = ai_data
        alert.update(ai_data)

        return alert

    def reset(self) -> None:
        self.module_co2_window.reset()

    def evaluate(self, state: dict) -> dict:
        metrics = state.get("metrics", {})
        symptoms = state.get("symptoms", [])
        t = state.get("t", 0.0)

        raw_mod_co2 = metrics.get("module2_co2")
        try:
            mod_co2 = (
                float(raw_mod_co2)
                if isinstance(raw_mod_co2, (int, float)) and not isinstance(raw_mod_co2, bool)
                else None
            )
        except (OverflowError, TypeError, ValueError):
            mod_co2 = None
        if mod_co2 is not None and (not math.isfinite(mod_co2) or mod_co2 < 0):
            mod_co2 = None
        mod_co2_avg, mod_co2_coverage = self.module_co2_window.update(t, mod_co2)
        result = {
            "t": t,
            "crew": {},
            "module_alerts": [],
            "module_metrics": {
                "module2_co2_sample_mmhg": round(mod_co2, 2) if mod_co2 is not None else None,
                "module2_co2_1h_avg_mmhg": round(mod_co2_avg, 3) if mod_co2_avg is not None else None,
                "module2_co2_coverage_minutes": round(mod_co2_coverage, 1),
                "module2_co2_window_minutes": self.module_co2_window.window_minutes,
            },
        }

        if mod_co2_avg is not None and mod_co2_avg > CO2_GENERAL_LIMIT_1H_MMHG:
            alert = {
                "rule_id": "module_co2_limit",
                "status": "WARNING",
                "text": (
                    f"The rolling CO₂ average for Module 2 over the last hour is {mod_co2_avg:.2f} mmHg, "
                    f"above the NASA reference of {CO2_GENERAL_LIMIT_1H_MMHG:.1f} mmHg."
                ),
                "evidence": ["module2_co2_1h_avg_mmhg"],
            }
            result["module_alerts"].append(self._enrich_alert_with_ai(alert))

        for crew_id, profile in self.profiles.items():
            alerts = self._eval_crew(crew_id, profile, metrics, symptoms)
            max_status = "NORMAL"

            for a in alerts:
                self._enrich_alert_with_ai(a)
                if _STATUS_RANK[a["status"]] > _STATUS_RANK[max_status]:
                    max_status = a["status"]

            has_individual_input = (
                _valid_local_co2(metrics.get("ana_local_co2"))
                or _valid_spo2(metrics.get("ana_spo2"))
                or _valid_heart_rate(metrics.get("ana_hr"))
            )
            crew_status = (
                max_status
                if crew_id == "ana" and has_individual_input
                else "NOT_MONITORED"
            )
            cascade = get_cascade("co2_pocket") if crew_status in ["OBSERVE", "WARNING"] else []

            domino = get_illustrative_domino_scenario(crew_id, crew_status)

            result["crew"][crew_id] = {
                "status": crew_status,
                "alerts": alerts,
                "cascade": cascade,
                "domino": domino,
                "metrics": {
                    k: round(v, 2) for k, v in metrics.items()
                    if k.startswith(crew_id) and isinstance(v, (int, float))
                },
                "vital_signals": (
                    {
                        "heart_rate": _vital_signal(metrics, "ana_hr", "bpm", _valid_heart_rate),
                        "spo2": _vital_signal(metrics, "ana_spo2", "%", _valid_spo2),
                    }
                    if crew_id == "ana"
                    else {}
                ),
            }
        return result

    def _eval_crew(self, crew_id, profile, metrics, symptoms) -> list:
        alerts = []
        if crew_id == "ana":
            threshold = profile["personal_thresholds"]["co2_mmHg"]
            raw_local_co2 = metrics.get("ana_local_co2")
            local_co2 = raw_local_co2 if _valid_local_co2(raw_local_co2) else None
            immobile = metrics.get("ana_immobile_h", 0)
            local_vent = metrics.get("ana_local_ventilation", metrics.get("module2_ventilation", 100))
            spo2 = metrics.get("ana_spo2")
            hr = metrics.get("ana_hr")
            co2_context = {
                "ana_local_co2_mmhg": local_co2,
                "module2_co2_sample_mmhg": metrics.get("module2_co2"),
                "individual_threshold_mmhg": threshold,
            }

            if (local_co2 is not None and local_co2 >= threshold and
                immobile >= IMMOBILITY_THRESHOLD_H and local_vent < VENTILATION_LOW_PCT):
                alerts.append({
                    "rule_id": "co2_pocket_inference",
                    "status": "OBSERVE",
                    "text": f"Risk consistent with elevated local CO₂ exposure (local {local_co2:.2f}, threshold {threshold})",
                    "evidence": ["actigraphy", "local_co2", "ana_local_ventilation"],
                    "scenario_context": {
                        **co2_context,
                        "supporting_signals": [
                            f"immobility {immobile:.1f} h",
                            (
                                f"ventilation {local_vent:.0f}%"
                                + (" (module value used as a local proxy)" if "ana_local_ventilation" not in metrics else "")
                            ),
                        ],
                        "interpretation_note": (
                            "The rule uses the local threshold, immobility, and ventilation; "
                            "it does not require local CO₂ to exceed module CO₂."
                        ),
                    },
                })

            has_stuffy = any(s["symptom"] == "stuffy_nose" for s in symptoms)
            has_headache = any(s["symptom"] == "headache" for s in symptoms)

            if has_stuffy and local_co2 is not None and local_co2 >= threshold:
                alerts.append({
                    "rule_id": "co2_warning_congestion",
                    "status": "WARNING",
                    "text": "Congestion reported with elevated local CO₂",
                    "evidence": ["symptom", "local_co2"],
                    "scenario_context": {
                        **co2_context,
                        "supporting_signals": ["reported nasal congestion"],
                        "interpretation_note": (
                            "The symptom and synthetic CO₂ reading are time-aligned in this scenario; "
                            "this does not show that CO₂ caused the symptom."
                        ),
                    },
                })
            if has_headache and local_co2 is not None and local_co2 >= threshold:
                alerts.append({
                    "rule_id": "co2_warning_headache",
                    "status": "WARNING",
                    "text": "Headache reported with elevated local CO₂",
                    "evidence": ["symptom", "local_co2"],
                    "scenario_context": {
                        **co2_context,
                        "supporting_signals": ["reported headache"],
                        "interpretation_note": (
                            "The symptom and synthetic CO₂ reading are time-aligned in this scenario; "
                            "this does not show that CO₂ caused the symptom."
                        ),
                    },
                })

            if _valid_spo2(spo2) and spo2 < SPO2_CRITICAL_PCT:
                alerts.append({
                    "rule_id": "spo2_critical",
                    "status": "CRITICAL",
                    "text": "Synthetic SpO₂ input falls below the prototype trigger.",
                    "evidence": ["spo2"],
                    "vital_context": {
                        "metric": "SpO₂",
                        "value": spo2,
                        "unit": "%",
                        "operator": "<",
                        "threshold": SPO2_CRITICAL_PCT,
                        "interpretation_note": (
                            "This is a synthetic scenario input, not a live sensor reading or diagnosis. "
                            "The threshold is not NASA-validated."
                        ),
                    },
                })
            if _valid_heart_rate(hr) and hr > HR_CRITICAL_BPM:
                alerts.append({
                    "rule_id": "hr_critical",
                    "status": "CRITICAL",
                    "text": "Synthetic heart-rate input exceeds the prototype trigger.",
                    "evidence": ["hr"],
                    "vital_context": {
                        "metric": "Heart rate",
                        "value": hr,
                        "unit": "bpm",
                        "operator": ">",
                        "threshold": HR_CRITICAL_BPM,
                        "interpretation_note": (
                            "This is a synthetic scenario input, not an ECG-derived measurement or diagnosis. "
                            "The threshold is not NASA-validated."
                        ),
                    },
                })

        return alerts