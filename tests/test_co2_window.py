import asyncio
import json
import math
import unittest
from unittest.mock import patch

from core.sim import engine as simulator_module
from core.sim.engine import SimulatorEngine
from core.config import PROFILES_DIR
from core.rules.co2_window import RollingCO2Window
from core.rules.engine import RulesEngine


class RollingCO2WindowTests(unittest.TestCase):
    def test_requires_full_window_before_returning_average(self):
        window = RollingCO2Window(window_minutes=60)

        for minute in range(60):
            average, covered = window.update(minute, 3.2)

        self.assertIsNone(average)
        self.assertEqual(covered, 59)

        average, covered = window.update(60, 3.2)
        self.assertAlmostEqual(average, 3.2)
        self.assertEqual(covered, 60)

    def test_uses_time_weighted_trapezoid_average(self):
        window = RollingCO2Window(window_minutes=60)
        for minute in range(61):
            average, _ = window.update(minute, float(minute))

        self.assertAlmostEqual(average, 30.0)

    def test_duplicate_timestamp_replaces_sample_and_time_rewind_resets(self):
        window = RollingCO2Window(window_minutes=2)
        window.update(0, 1.0)
        window.update(1, 2.0)
        average, _ = window.update(1, 4.0)
        self.assertIsNone(average)

        average, covered = window.update(2, 4.0)
        self.assertAlmostEqual(average, 3.25)
        self.assertEqual(covered, 2)

        average, covered = window.update(0, 5.0)
        self.assertIsNone(average)
        self.assertEqual(covered, 0)

    def test_missing_reading_discards_window_coverage(self):
        window = RollingCO2Window(window_minutes=2)
        window.update(0, 3.1)
        window.update(1, 3.1)

        average, covered = window.update(2, None)

        self.assertIsNone(average)
        self.assertEqual(covered, 0)

    def test_non_finite_negative_and_malformed_readings_reset_window(self):
        for invalid_value in (math.nan, math.inf, -math.inf, -0.1, "not-a-number", 10**1000, True):
            with self.subTest(invalid_value=invalid_value):
                window = RollingCO2Window(window_minutes=2)
                window.update(0, 3.2)
                window.update(1, 3.2)

                average, covered = window.update(2, invalid_value)

                self.assertIsNone(average)
                self.assertEqual(covered, 0)

    def test_long_sampling_gap_resets_coverage_until_new_full_window(self):
        window = RollingCO2Window(window_minutes=2, max_sample_gap_minutes=1.5)
        window.update(0, 3.2)
        window.update(1, 3.2)

        average, covered = window.update(4, 3.2)
        self.assertIsNone(average)
        self.assertEqual(covered, 0)

        window.update(5, 3.2)
        average, covered = window.update(6, 3.2)
        self.assertAlmostEqual(average, 3.2)
        self.assertEqual(covered, 2)

    def test_nominal_sampling_jitter_within_gap_limit_keeps_coverage(self):
        window = RollingCO2Window(window_minutes=2, max_sample_gap_minutes=1.5)
        window.update(0, 3.0)
        window.update(1.5, 3.0)

        average, covered = window.update(2.5, 3.0)

        self.assertAlmostEqual(average, 3.0)
        self.assertEqual(covered, 2)


class ModuleCO2RuleTests(unittest.TestCase):
    def setUp(self):
        self.engine = RulesEngine({})
        self.explanation_patch = patch(
            "core.rules.engine.generate_explanation",
            return_value={"ai_explanation": "test", "ai_action": "test", "ai_citations": [], "ai_source": "TEST"},
        )
        self.explanation_patch.start()
        self.addCleanup(self.explanation_patch.stop)

    def evaluate_co2(self, minute, value):
        return self.engine.evaluate({"t": minute, "metrics": {"module2_co2": value}})

    def test_crew_without_individual_rules_is_not_reported_as_normal(self):
        engine = RulesEngine({"carlos": {"name_display": "Carlos"}})

        result = engine.evaluate({"t": 0.0, "metrics": {}})

        self.assertEqual(result["crew"]["carlos"]["status"], "NOT_MONITORED")
        self.assertEqual(result["crew"]["carlos"]["alerts"], [])

    def test_invalid_module_reading_is_json_null_and_invalidates_rule_window(self):
        for minute in range(61):
            result = self.evaluate_co2(minute, 3.2)
        self.assertEqual(result["module_alerts"][0]["rule_id"], "module_co2_limit")

        for invalid_value in (math.nan, math.inf, -1.0, "bad-value", 10**1000, True):
            with self.subTest(invalid_value=invalid_value):
                result = self.evaluate_co2(62, invalid_value)
                self.assertIsNone(result["module_metrics"]["module2_co2_sample_mmhg"])
                self.assertIsNone(result["module_metrics"]["module2_co2_1h_avg_mmhg"])
                self.assertEqual(result["module_metrics"]["module2_co2_coverage_minutes"], 0.0)
                self.assertEqual(result["module_alerts"], [])
                json.dumps(result, allow_nan=False)

    def test_module_alert_requires_complete_hour_and_mean_above_limit(self):
        for minute in range(60):
            result = self.evaluate_co2(minute, 3.2)
            self.assertEqual(result["module_alerts"], [])
        self.assertIsNone(result["module_metrics"]["module2_co2_1h_avg_mmhg"])

        result = self.evaluate_co2(60, 3.2)
        self.assertAlmostEqual(result["module_metrics"]["module2_co2_1h_avg_mmhg"], 3.2)
        self.assertEqual(result["module_alerts"][0]["rule_id"], "module_co2_limit")
        self.assertIn("rolling CO₂ average", result["module_alerts"][0]["text"])

    def test_isolated_high_sample_does_not_trigger_hourly_alert(self):
        for minute in range(59):
            result = self.evaluate_co2(minute, 2.8)
        peak_result = self.evaluate_co2(59, 5.0)
        result = self.evaluate_co2(60, 2.8)

        self.assertGreater(peak_result["module_metrics"]["module2_co2_sample_mmhg"], 3.0)
        self.assertLess(result["module_metrics"]["module2_co2_1h_avg_mmhg"], 3.0)
        self.assertEqual(result["module_alerts"], [])

    def test_exact_limit_is_not_a_violation_of_no_more_than_requirement(self):
        for minute in range(61):
            result = self.evaluate_co2(minute, 3.0)

        self.assertAlmostEqual(result["module_metrics"]["module2_co2_1h_avg_mmhg"], 3.0)
        self.assertEqual(result["module_alerts"], [])

    def test_long_telemetry_gap_clears_alert_until_new_full_window(self):
        for minute in range(61):
            result = self.evaluate_co2(minute, 3.2)
        self.assertEqual(result["module_alerts"][0]["rule_id"], "module_co2_limit")

        after_gap = self.evaluate_co2(63, 2.0)
        self.assertIsNone(after_gap["module_metrics"]["module2_co2_1h_avg_mmhg"])
        self.assertEqual(after_gap["module_metrics"]["module2_co2_coverage_minutes"], 0.0)
        self.assertEqual(after_gap["module_alerts"], [])

        for minute in range(64, 123):
            result = self.evaluate_co2(minute, 2.0)
            self.assertEqual(result["module_alerts"], [])
        self.assertIsNone(result["module_metrics"]["module2_co2_1h_avg_mmhg"])

        recovered_window = self.evaluate_co2(123, 2.0)
        self.assertAlmostEqual(recovered_window["module_metrics"]["module2_co2_1h_avg_mmhg"], 2.0)
        self.assertEqual(recovered_window["module_alerts"], [])


class CO2ScenarioRegressionTests(unittest.TestCase):
    def test_scenario_reaches_full_window_then_alerts_on_hourly_mean(self):
        simulator = SimulatorEngine()
        simulator.load("co2_failure_ana")
        with open(PROFILES_DIR / "ana.json", "r", encoding="utf-8") as profile_file:
            ana_profile = json.load(profile_file)
        rules = RulesEngine({"ana": ana_profile})
        samples = []

        async def no_wait(_seconds):
            return None

        async def collect(state):
            result = rules.evaluate(state)
            metrics = result["module_metrics"]
            samples.append({
                "t": state["t"],
                "coverage": metrics["module2_co2_coverage_minutes"],
                "average": metrics["module2_co2_1h_avg_mmhg"],
                "alert": bool(result["module_alerts"]),
                "local_alert": any(
                    alert["rule_id"] == "co2_pocket_inference"
                    for alert in result["crew"]["ana"]["alerts"]
                ),
                "local_alert_context": next(
                    (
                        alert.get("scenario_context")
                        for alert in result["crew"]["ana"]["alerts"]
                        if alert["rule_id"] == "co2_pocket_inference"
                    ),
                    None,
                ),
                "local_co2": state["metrics"]["ana_local_co2"],
                "module_co2": state["metrics"]["module2_co2"],
                "vital_signals": result["crew"]["ana"]["vital_signals"],
                "symptom_contexts": {
                    alert["rule_id"]: alert.get("scenario_context")
                    for alert in result["crew"]["ana"]["alerts"]
                    if alert["rule_id"] in {"co2_warning_congestion", "co2_warning_headache"}
                },
            })

        with (
            patch("core.rules.engine.generate_explanation", return_value={
                "ai_explanation": "test",
                "ai_action": "test",
                "ai_citations": [],
                "ai_source": "TEST",
            }),
            patch.object(simulator_module.asyncio, "sleep", no_wait),
        ):
            asyncio.run(simulator.run(collect))

        complete_windows = [sample for sample in samples if sample["average"] is not None]
        alerts = [sample for sample in samples if sample["alert"]]

        self.assertEqual(complete_windows[0]["t"], 60.0)
        self.assertEqual(complete_windows[0]["coverage"], 60.0)
        self.assertFalse(any(sample["alert"] for sample in samples if sample["t"] < 70.0))
        self.assertEqual(alerts[0]["t"], 70.0)
        self.assertAlmostEqual(alerts[0]["average"], 3.007, places=3)

        local_alerts = [sample for sample in samples if sample["local_alert"]]
        self.assertEqual(local_alerts[0]["t"], 26.0)
        divergence = next(sample for sample in samples if sample["local_co2"] > sample["module_co2"])
        self.assertEqual(divergence["t"], 32.0)
        self.assertTrue(divergence["local_alert"])
        self.assertFalse(divergence["alert"])
        self.assertLess(local_alerts[0]["t"], alerts[0]["t"])
        self.assertAlmostEqual(divergence["local_alert_context"]["ana_local_co2_mmhg"], 3.15)
        self.assertAlmostEqual(divergence["local_alert_context"]["module2_co2_sample_mmhg"], 3.025)
        self.assertEqual(divergence["local_alert_context"]["individual_threshold_mmhg"], 2.1)
        self.assertEqual(
            divergence["local_alert_context"]["supporting_signals"],
            ["immobility 3.5 h", "ventilation 30% (module value used as a local proxy)"],
        )

        congestion_context = next(
            sample["symptom_contexts"]["co2_warning_congestion"]
            for sample in samples
            if "co2_warning_congestion" in sample["symptom_contexts"]
        )
        self.assertEqual(congestion_context["supporting_signals"], ["reported nasal congestion"])
        self.assertIn("does not show that CO₂ caused", congestion_context["interpretation_note"])
        headache_context = next(
            sample["symptom_contexts"]["co2_warning_headache"]
            for sample in samples
            if "co2_warning_headache" in sample["symptom_contexts"]
        )
        self.assertEqual(headache_context["supporting_signals"], ["reported headache"])
        self.assertIn("does not show that CO₂ caused", headache_context["interpretation_note"])
        self.assertEqual(samples[0]["vital_signals"]["heart_rate"], {
            "status": "SYNTHETIC",
            "value": 62,
            "unit": "bpm",
        })
        self.assertEqual(samples[0]["vital_signals"]["spo2"], {
            "status": "SYNTHETIC",
            "value": 98,
            "unit": "%",
        })


class VitalAlertContextTests(unittest.TestCase):
    def setUp(self):
        with open(PROFILES_DIR / "ana.json", "r", encoding="utf-8") as profile_file:
            ana_profile = json.load(profile_file)
        self.engine = RulesEngine({"ana": ana_profile})
        self.explanation_patch = patch(
            "core.rules.engine.generate_explanation",
            return_value={
                "ai_explanation": "test",
                "ai_action": "test",
                "ai_citations": [],
                "ai_source": "TEST",
            },
        )
        self.explanation_patch.start()
        self.addCleanup(self.explanation_patch.stop)

    def evaluate_vitals(self, spo2, heart_rate):
        return self.engine.evaluate({
            "t": 0.0,
            "metrics": {
                "ana_local_co2": 1.0,
                "ana_immobile_h": 0.0,
                "ana_local_ventilation": 100.0,
                "ana_spo2": spo2,
                "ana_hr": heart_rate,
            },
        })["crew"]["ana"]["alerts"]

    def test_exact_vital_thresholds_do_not_trigger(self):
        alerts = self.evaluate_vitals(spo2=90, heart_rate=160)

        self.assertFalse(any(alert["rule_id"] in {"spo2_critical", "hr_critical"} for alert in alerts))

    def test_missing_vitals_are_not_replaced_with_normal_defaults(self):
        result = self.engine.evaluate({
            "t": 0.0,
            "metrics": {},
        })
        ana = result["crew"]["ana"]
        vital_alerts = [
            alert for alert in ana["alerts"]
            if alert["rule_id"] in {"spo2_critical", "hr_critical"}
        ]

        self.assertEqual(vital_alerts, [])
        self.assertEqual(ana["status"], "NOT_MONITORED")
        self.assertEqual(ana["vital_signals"]["spo2"]["status"], "NOT_MONITORED")
        self.assertIsNone(ana["vital_signals"]["spo2"]["value"])
        self.assertEqual(ana["vital_signals"]["heart_rate"]["status"], "NOT_MONITORED")
        self.assertIsNone(ana["vital_signals"]["heart_rate"]["value"])

    def test_invalid_vitals_are_not_used_for_alerts(self):
        result = self.engine.evaluate({
            "t": 0.0,
            "metrics": {
                "ana_spo2": 101,
                "ana_hr": 0,
            },
        })
        by_rule = {
            alert["rule_id"]: alert for alert in result["crew"]["ana"]["alerts"]
        }

        self.assertNotIn("spo2_critical", by_rule)
        self.assertNotIn("hr_critical", by_rule)
        self.assertEqual(result["crew"]["ana"]["vital_signals"]["spo2"]["status"], "INVALID")
        self.assertEqual(result["crew"]["ana"]["vital_signals"]["heart_rate"]["status"], "INVALID")

    def test_vital_alerts_disclose_synthetic_values_and_prototype_thresholds(self):
        alerts = self.evaluate_vitals(spo2=89, heart_rate=161)
        by_rule = {alert["rule_id"]: alert for alert in alerts}

        spo2_alert = by_rule["spo2_critical"]
        self.assertEqual(spo2_alert["vital_context"]["value"], 89)
        self.assertEqual(spo2_alert["vital_context"]["threshold"], 90)
        self.assertIn("synthetic", spo2_alert["text"].lower())
        self.assertIn("not NASA-validated", spo2_alert["vital_context"]["interpretation_note"])

        heart_rate_alert = by_rule["hr_critical"]
        self.assertEqual(heart_rate_alert["vital_context"]["value"], 161)
        self.assertEqual(heart_rate_alert["vital_context"]["threshold"], 160)
        self.assertIn("synthetic", heart_rate_alert["text"].lower())
        self.assertIn("ECG-derived", heart_rate_alert["vital_context"]["interpretation_note"])


if __name__ == "__main__":
    unittest.main()