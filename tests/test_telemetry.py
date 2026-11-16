import unittest

from cryptography.exceptions import InvalidTag

from core.telemetry import (
    BlackoutBuffer,
    create_telemetry_packet,
    decrypt_telemetry_packet,
)


class TelemetryPacketTests(unittest.TestCase):
    def test_blackout_buffer_collects_transitions_and_metric_ranges(self):
        buffer = BlackoutBuffer(2.0)
        state = {
            "t": 3.0,
            "metrics": {"module2_co2": 3.2, "ana_hr": 72},
            "symptoms": [{"crew": "ana", "symptom": "headache", "t": 3.0}],
        }
        evaluation = {
            "module_metrics": {
                "module2_co2_sample_mmhg": 3.2,
                "module2_co2_1h_avg_mmhg": 3.05,
                "module2_co2_coverage_minutes": 60.0,
                "module2_co2_window_minutes": 60.0,
            },
            "module_alerts": [{"rule_id": "module_co2_limit", "status": "WARNING"}],
            "crew": {
                "ana": {
                    "status": "WARNING",
                    "alerts": [{
                        "rule_id": "co2_warning_headache",
                        "status": "WARNING",
                        "text": "Synthetic test alert",
                        "source_ids": ["NASA-NTRS-20160012725"],
                    }],
                }
            }
        }

        buffer.record(state, evaluation)
        buffer.record_action("activate_bed_fan", 3.0)
        buffer.record_action(
            "protocol_reassessment",
            3.5,
            details={"local_co2_mmhg": 2.9, "symptoms": []},
        )
        payload = buffer.finish(4.0)

        self.assertEqual(payload["ticks"], 1)
        self.assertEqual(payload["ended_t"], 4.0)
        self.assertEqual(payload["metrics"]["module2_co2"], {"min": 3.2, "max": 3.2, "last": 3.2})
        self.assertEqual(payload["alerts"][0]["source_ids"], ["NASA-NTRS-20160012725"])
        self.assertEqual(payload["actions"][-2]["action"], "activate_bed_fan")
        self.assertEqual(
            payload["actions"][-1]["details"]["local_co2_mmhg"], 2.9
        )
        self.assertEqual(payload["co2_hourly"]["average_mmhg"], 3.05)
        self.assertEqual(payload["co2_hourly"]["coverage_minutes"], 60.0)
        self.assertTrue(payload["co2_hourly"]["alert_active"])

    def test_packet_roundtrip_compresses_and_authenticates(self):
        key = bytes(range(32))
        payload = {
            "ticks": 30,
            "alerts": [{"rule_id": "co2_pocket_inference", "text": "Repeated simulated alert"} for _ in range(30)],
        }

        packet, receipt = create_telemetry_packet(payload, key)

        self.assertEqual(packet["algorithm"], "AES-256-GCM")
        self.assertLess(packet["compressed_bytes"], packet["uncompressed_bytes"])
        self.assertEqual(receipt, payload)
        self.assertEqual(decrypt_telemetry_packet(packet, key), payload)

        packet["ciphertext"] = packet["ciphertext"][:-4] + "AAAA"
        with self.assertRaises(InvalidTag):
            decrypt_telemetry_packet(packet, key)


if __name__ == "__main__":
    unittest.main()