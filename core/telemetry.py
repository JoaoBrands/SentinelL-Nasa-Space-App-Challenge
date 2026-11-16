"""Bounded blackout summaries and authenticated telemetry packet helpers."""
import base64
import json
import os
import secrets
import zlib

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_AAD = b"nasa-sentinel-telemetry-v1"
_MAX_EVENTS = 50
_MAX_ACTIONS = 20
_METRIC_KEYS = (
    "module2_co2",
    "module2_ventilation",
    "ana_local_co2",
    "ana_hr",
    "ana_spo2",
)


def load_telemetry_key() -> tuple[bytes, str]:
    configured_key = os.getenv("SENTINEL_TELEMETRY_KEY")
    if configured_key is None:
        return secrets.token_bytes(32), "ephemeral_demo"

    try:
        key = bytes.fromhex(configured_key)
    except ValueError as exc:
        raise ValueError("SENTINEL_TELEMETRY_KEY must be 64 hexadecimal characters") from exc

    if len(key) != 32:
        raise ValueError("SENTINEL_TELEMETRY_KEY must decode to exactly 32 bytes")
    return key, "configured"


class BlackoutBuffer:
    def __init__(self, started_t: float):
        self.payload = {
            "version": 1,
            "started_t": round(started_t, 2),
            "ended_t": None,
            "ticks": 0,
            "crew_status_changes": [],
            "alerts": [],
            "symptoms": [],
            "actions": [{"action": "comms_lost", "t": round(started_t, 2)}],
            "metrics": {},
            "co2_hourly": {
                "window_minutes": 60.0,
                "coverage_minutes": 0.0,
                "average_mmhg": None,
                "latest_sample_mmhg": None,
                "alert_active": False,
            },
        }
        self._last_statuses: dict[str, str] = {}
        self._alert_indexes: dict[tuple[str, str], int] = {}
        self._symptoms_seen: set[tuple[str, str, float]] = set()

    def record(self, state: dict, evaluation: dict) -> None:
        sim_t = round(float(state.get("t", 0.0)), 2)
        self.payload["ticks"] += 1
        self.payload["ended_t"] = sim_t

        module_metrics = evaluation.get("module_metrics", {})
        self.payload["co2_hourly"] = {
            "window_minutes": module_metrics.get("module2_co2_window_minutes", 60.0),
            "coverage_minutes": module_metrics.get("module2_co2_coverage_minutes", 0.0),
            "average_mmhg": module_metrics.get("module2_co2_1h_avg_mmhg"),
            "latest_sample_mmhg": module_metrics.get("module2_co2_sample_mmhg"),
            "alert_active": any(
                alert.get("rule_id") == "module_co2_limit"
                for alert in evaluation.get("module_alerts", [])
            ),
        }

        crew_status_changes = self.payload["crew_status_changes"]
        for crew_id, crew_data in evaluation.get("crew", {}).items():
            status = crew_data.get("status", "UNKNOWN")
            if self._last_statuses.get(crew_id) != status and len(crew_status_changes) < _MAX_EVENTS:
                crew_status_changes.append({"crew": crew_id, "status": status, "t": sim_t})
            self._last_statuses[crew_id] = status

            for alert in crew_data.get("alerts", []):
                self._record_alert(crew_id, alert, sim_t)

        for alert in evaluation.get("module_alerts", []):
            self._record_alert("module", alert, sim_t)

        for symptom in state.get("symptoms", []):
            key = (
                symptom.get("crew", "unknown"),
                symptom.get("symptom", "unknown"),
                round(float(symptom.get("t", sim_t)), 2),
            )
            symptoms = self.payload["symptoms"]
            if key not in self._symptoms_seen and len(symptoms) < _MAX_EVENTS:
                self._symptoms_seen.add(key)
                symptoms.append({"crew": key[0], "symptom": key[1], "t": key[2]})

        metrics = state.get("metrics", {})
        for metric in _METRIC_KEYS:
            value = metrics.get(metric)
            if not isinstance(value, (int, float)):
                continue
            rounded_value = round(float(value), 2)
            summary = self.payload["metrics"].setdefault(
                metric,
                {"min": rounded_value, "max": rounded_value, "last": rounded_value},
            )
            summary["min"] = min(summary["min"], rounded_value)
            summary["max"] = max(summary["max"], rounded_value)
            summary["last"] = rounded_value

    def _record_alert(self, crew_id: str, alert: dict, sim_t: float) -> None:
        alerts = self.payload["alerts"]
        key = (crew_id, alert.get("rule_id", "unknown"))
        if key in self._alert_indexes:
            alerts[self._alert_indexes[key]]["last_seen_t"] = sim_t
        elif len(alerts) < _MAX_EVENTS:
            self._alert_indexes[key] = len(alerts)
            alerts.append({
                "crew": crew_id,
                "rule_id": key[1],
                "status": alert.get("status", "INFO"),
                "text": alert.get("text", ""),
                "source_ids": alert.get("source_ids", []),
                "first_seen_t": sim_t,
                "last_seen_t": sim_t,
            })

    def record_action(self, action: str, sim_t: float, details: dict | None = None) -> None:
        actions = self.payload["actions"]
        if len(actions) < _MAX_ACTIONS:
            entry = {"action": action, "t": round(sim_t, 2)}
            if details is not None:
                entry["details"] = details
            actions.append(entry)

    def finish(self, sim_t: float) -> dict:
        self.payload["ended_t"] = round(sim_t, 2)
        return self.payload


def decrypt_telemetry_packet(packet: dict, key: bytes) -> dict:
    nonce = base64.b64decode(packet["nonce"])
    ciphertext = base64.b64decode(packet["ciphertext"])
    compressed = AESGCM(key).decrypt(nonce, ciphertext, _AAD)
    return json.loads(zlib.decompress(compressed).decode("utf-8"))


def create_telemetry_packet(payload: dict, key: bytes) -> tuple[dict, dict]:
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    compressed = zlib.compress(serialized, level=9)
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(nonce, compressed, _AAD)
    packet = {
        "packet_id": secrets.token_hex(8),
        "algorithm": "AES-256-GCM",
        "compression": "zlib",
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "uncompressed_bytes": len(serialized),
        "compressed_bytes": len(compressed),
        "encrypted_payload_bytes": len(nonce) + len(ciphertext),
    }
    receipt = decrypt_telemetry_packet(packet, key)
    return packet, receipt