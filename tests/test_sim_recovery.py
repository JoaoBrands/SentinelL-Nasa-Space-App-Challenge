import json
import unittest
from pathlib import Path
from unittest.mock import patch

from core.config import (
    BED_FAN_LOCAL_CO2_TARGET_MMHG,
    BED_FAN_LOCAL_WASHOUT_MINUTES,
    MODULE_VENTILATION_CO2_TARGET_MMHG,
)
from core.rules.engine import RulesEngine
from core.sim.engine import SimulatorEngine


class BedFanRecoveryTests(unittest.TestCase):
    def test_bed_fan_recovers_local_crew_alert_but_not_module_co2_alert(self):
        project_root = Path(__file__).resolve().parents[1]
        profiles = {}
        for profile_path in (project_root / "data" / "profiles").glob("*.json"):
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profiles[profile["id"]] = profile

        simulator = SimulatorEngine()
        simulator.load("co2_failure_ana")
        rules = RulesEngine(profiles)

        with patch("core.rules.engine.generate_explanation", return_value={
            "ai_explanation": "test",
            "ai_action": "test",
            "ai_citations": [],
            "ai_source": "TEST",
        }):
            for minute in range(71):
                simulator.current_t = float(minute)
                state = simulator.get_state()
                evaluation = rules.evaluate(state)

            before_fan = state["metrics"]
            self.assertEqual(evaluation["crew"]["ana"]["status"], "WARNING")
            self.assertEqual(evaluation["module_alerts"][0]["rule_id"], "module_co2_limit")

            simulator.activate_fan()
            fan_start_state = simulator.get_state()
            fan_start_evaluation = rules.evaluate(fan_start_state)
            for minute in (71, 72):
                simulator.current_t = float(minute)
                rules.evaluate(simulator.get_state())
            simulator.current_t = 72.5
            midpoint_state = simulator.get_state()
            rules.evaluate(midpoint_state)
            for minute in (73, 74):
                simulator.current_t = float(minute)
                rules.evaluate(simulator.get_state())
            simulator.current_t = 70.0 + BED_FAN_LOCAL_WASHOUT_MINUTES
            recovered_state = simulator.get_state()
            recovered_evaluation = rules.evaluate(recovered_state)

        self.assertEqual(fan_start_state["metrics"]["ana_local_co2"], before_fan["ana_local_co2"])
        self.assertEqual(fan_start_state["interventions"]["bed_fan"]["progress_percent"], 0.0)
        self.assertEqual(fan_start_evaluation["crew"]["ana"]["status"], "WARNING")
        self.assertAlmostEqual(
            midpoint_state["metrics"]["ana_local_co2"],
            (before_fan["ana_local_co2"] + BED_FAN_LOCAL_CO2_TARGET_MMHG) / 2,
        )
        self.assertEqual(midpoint_state["interventions"]["bed_fan"]["progress_percent"], 50.0)
        self.assertEqual(recovered_state["metrics"]["ana_local_co2"], BED_FAN_LOCAL_CO2_TARGET_MMHG)
        self.assertEqual(recovered_state["interventions"]["bed_fan"]["progress_percent"], 100.0)
        self.assertEqual(recovered_state["metrics"]["module2_co2"], before_fan["module2_co2"])
        self.assertEqual(recovered_state["metrics"]["module2_ventilation"], before_fan["module2_ventilation"])
        self.assertEqual(recovered_state["metrics"]["ana_hr"], before_fan["ana_hr"])
        self.assertTrue(any(symptom["symptom"] == "headache" for symptom in recovered_state["symptoms"]))
        self.assertEqual(recovered_evaluation["crew"]["ana"]["status"], "NORMAL")
        self.assertEqual(recovered_evaluation["crew"]["ana"]["alerts"], [])
        self.assertEqual(recovered_evaluation["module_alerts"][0]["rule_id"], "module_co2_limit")
        self.assertGreater(recovered_evaluation["module_metrics"]["module2_co2_1h_avg_mmhg"], 3.0)


class ModuleVentilationRecoveryTests(unittest.TestCase):
    def test_module_action_has_separate_ramp_and_alert_clears_only_after_hourly_mean(self):
        project_root = Path(__file__).resolve().parents[1]
        profiles = {}
        for profile_path in (project_root / "data" / "profiles").glob("*.json"):
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profiles[profile["id"]] = profile

        simulator = SimulatorEngine()
        simulator.load("co2_failure_ana")
        rules = RulesEngine(profiles)
        no_explanation = {
            "ai_explanation": "test",
            "ai_action": "test",
            "ai_citations": [],
            "ai_source": "TEST",
        }

        with patch("core.rules.engine.generate_explanation", return_value=no_explanation):
            for minute in range(71):
                simulator.current_t = float(minute)
                evaluation = rules.evaluate(simulator.get_state())
            self.assertEqual(evaluation["module_alerts"][0]["rule_id"], "module_co2_limit")
            ana_local_before = simulator.get_state()["metrics"]["ana_local_co2"]

            simulator.activate_module_ventilation()
            for minute in range(71, 76):
                simulator.current_t = float(minute)
                midpoint = simulator.get_state()
                midpoint_evaluation = rules.evaluate(midpoint)
            simulator.current_t = 75.0
            midpoint = simulator.get_state()
            midpoint_evaluation = rules.evaluate(midpoint)
            for minute in range(76, 80):
                simulator.current_t = float(minute)
                response_complete = simulator.get_state()
                complete_evaluation = rules.evaluate(response_complete)
            simulator.current_t = 80.0
            response_complete = simulator.get_state()
            complete_evaluation = rules.evaluate(response_complete)
            self.assertEqual(complete_evaluation["module_alerts"][0]["rule_id"], "module_co2_limit")

            first_clear_minute = None
            clear_evaluation = None
            for minute in range(81, 101):
                simulator.current_t = float(minute)
                clear_evaluation = rules.evaluate(simulator.get_state())
                if not clear_evaluation["module_alerts"]:
                    first_clear_minute = minute
                    break

        self.assertAlmostEqual(midpoint["metrics"]["module2_co2"], 2.85)
        self.assertEqual(midpoint["interventions"]["module_ventilation"]["progress_percent"], 50.0)
        self.assertAlmostEqual(response_complete["metrics"]["module2_co2"], MODULE_VENTILATION_CO2_TARGET_MMHG)
        self.assertEqual(response_complete["interventions"]["module_ventilation"]["progress_percent"], 100.0)
        self.assertEqual(response_complete["metrics"]["ana_local_co2"], ana_local_before)
        self.assertEqual(first_clear_minute, 95)
        self.assertLessEqual(clear_evaluation["module_metrics"]["module2_co2_1h_avg_mmhg"], 3.0)


if __name__ == "__main__":
    unittest.main()