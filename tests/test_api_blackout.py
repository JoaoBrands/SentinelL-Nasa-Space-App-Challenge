import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import main as api_main


class ControlledRulesEngine:
    def __init__(self, profiles, rule_evidence=None):
        self.profiles = profiles

    def reset(self):
        pass

    def evaluate(self, state):
        has_co2 = "module2_co2" in state.get("metrics", {})
        return {
            "t": state.get("t", 0.0),
            "crew": {
                crew_id: {"status": "NORMAL", "alerts": []}
                for crew_id in self.profiles
            },
            "module_alerts": ([{
                "rule_id": "module_co2_limit",
                "status": "WARNING",
                "text": "Rolling one-hour mean above limit",
            }] if has_co2 else []),
            "module_metrics": {
                "module2_co2_sample_mmhg": 3.2 if has_co2 else None,
                "module2_co2_1h_avg_mmhg": 3.05 if has_co2 else None,
                "module2_co2_coverage_minutes": 60.0 if has_co2 else 0.0,
                "module2_co2_window_minutes": 60.0,
            },
        }


class ControlledSimulator:
    instance = None

    def __init__(self):
        type(self).instance = self
        self.current_t = 0.0
        self.running = False
        self.fan_activated = False
        self.fan_progress_percent = 0.0
        self.local_co2 = 3.15
        self.module_ventilation_activated = False

    def load(self, scenario_id):
        self.current_t = 65.0
        self.fan_activated = False
        self.fan_progress_percent = 0.0

    def stop(self):
        self.running = False

    def activate_fan(self):
        self.fan_activated = True

    def activate_module_ventilation(self):
        self.module_ventilation_activated = True

    def get_state(self):
        return {
            "t": self.current_t,
            "metrics": {"ana_local_co2": self.local_co2},
            "symptoms": [{"crew": "ana", "symptom": "headache", "t": 65.0}],
            "interventions": {
                "bed_fan": {
                    "active": self.fan_activated,
                    "elapsed_minutes": self.fan_progress_percent * 0.05,
                    "washout_duration_minutes": 5.0,
                    "progress_percent": self.fan_progress_percent,
                } if self.fan_activated else None,
            },
        }

    async def run(self, on_tick):
        self.running = True
        await on_tick({
            "t": self.current_t,
            "metrics": {"module2_co2": 3.2},
            "symptoms": [],
            "finished": False,
        })
        self.running = False


class BlackoutWebSocketIntegrationTests(unittest.TestCase):
    def test_blackout_buffers_reassessment_snapshot_and_hourly_co2_summary(self):
        key = bytes(range(32))
        with (
            patch.object(api_main, "SimulatorEngine", ControlledSimulator),
            patch.object(api_main, "RulesEngine", ControlledRulesEngine),
            patch.object(api_main, "load_telemetry_key", return_value=(key, "configured")),
            TestClient(api_main.app) as client,
        ):
            with client.websocket_connect("/ws") as websocket:
                initial = websocket.receive_json()
                self.assertEqual(initial["type"], "tick")
                self.assertIn("provenance", initial)

                websocket.send_json({"action": "cut_comms"})
                link_status = websocket.receive_json()
                self.assertEqual(link_status["type"], "link_status")
                self.assertEqual(link_status["status"], "blackout")

                websocket.send_json({"action": "start_scenario", "id": "test"})
                onboard_tick = websocket.receive_json()
                self.assertEqual(onboard_tick["type"], "onboard_tick")
                self.assertEqual(onboard_tick["evaluation"]["module_metrics"]["module2_co2_1h_avg_mmhg"], 3.05)

                websocket.send_json({"action": "protocol_step", "step": []})
                invalid_step = websocket.receive_json()
                self.assertEqual(invalid_step["type"], "protocol_error")
                self.assertEqual(invalid_step["message"], "Unknown protocol step.")

                websocket.send_json({"action": "protocol_step", "step": "airflow_check"})
                fan_required = websocket.receive_json()
                self.assertEqual(fan_required["type"], "protocol_error")

                websocket.send_json({"action": "activate_fan"})
                websocket.send_json({"action": "protocol_step", "step": "reassessment"})
                airflow_required = websocket.receive_json()
                self.assertEqual(airflow_required["type"], "protocol_error")

                websocket.send_json({"action": "protocol_step", "step": "airflow_check"})
                airflow_ack = websocket.receive_json()
                self.assertEqual(airflow_ack["type"], "protocol_ack")
                self.assertEqual(airflow_ack["step"], "airflow_check")

                websocket.send_json({"action": "protocol_step", "step": "reassessment"})
                ramp_required = websocket.receive_json()
                self.assertEqual(ramp_required["type"], "protocol_error")

                ControlledSimulator.instance.fan_progress_percent = 100.0
                ControlledSimulator.instance.local_co2 = None
                websocket.send_json({"action": "protocol_step", "step": "reassessment"})
                reading_required = websocket.receive_json()
                self.assertEqual(reading_required["type"], "protocol_error")

                ControlledSimulator.instance.local_co2 = 3.15
                websocket.send_json({"action": "protocol_step", "step": "reassessment"})
                reassessment_ack = websocket.receive_json()
                self.assertEqual(reassessment_ack["type"], "protocol_ack")
                self.assertEqual(reassessment_ack["local_co2_mmhg"], 3.15)
                self.assertEqual(reassessment_ack["symptoms"][0]["symptom"], "headache")

                websocket.send_json({"action": "start_scenario", "id": "test"})
                websocket.receive_json()
                websocket.send_json({"action": "activate_fan"})
                websocket.send_json({"action": "protocol_step", "step": "reassessment"})
                reset_error = websocket.receive_json()
                self.assertEqual(reset_error["type"], "protocol_error")
                self.assertEqual(
                    reset_error["message"],
                    "Confirm the airflow-path check before reassessment.",
                )

                websocket.send_json({"action": "activate_module_ventilation"})
                websocket.send_json({"action": "restore_comms"})
                restored = websocket.receive_json()

                self.assertEqual(restored["type"], "telemetry_packet")
                self.assertTrue(restored["receiver_verified"])
                self.assertEqual(restored["packet"]["algorithm"], "AES-256-GCM")
                self.assertEqual(restored["packet"]["compression"], "zlib")
                self.assertEqual(restored["key_mode"], "configured")

                co2_hourly = restored["receipt"]["co2_hourly"]
                self.assertEqual(co2_hourly["average_mmhg"], 3.05)
                self.assertEqual(co2_hourly["coverage_minutes"], 60.0)
                self.assertEqual(co2_hourly["latest_sample_mmhg"], 3.2)
                self.assertTrue(co2_hourly["alert_active"])
                self.assertTrue(any(
                    action["action"] == "activate_bed_fan"
                    for action in restored["receipt"]["actions"]
                ))
                self.assertTrue(any(
                    action["action"] == "activate_module_ventilation"
                    for action in restored["receipt"]["actions"]
                ))
                self.assertTrue(any(
                    action["action"] == "protocol_airflow_check"
                    for action in restored["receipt"]["actions"]
                ))
                reassessment = next(
                    action
                    for action in restored["receipt"]["actions"]
                    if action["action"] == "protocol_reassessment"
                )
                self.assertEqual(reassessment["details"]["local_co2_mmhg"], 3.15)
                self.assertEqual(
                    reassessment["details"]["symptoms"][0]["symptom"], "headache"
                )


if __name__ == "__main__":
    unittest.main()