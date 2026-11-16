"""Central configuration - all thresholds in one place."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PROFILES_DIR = DATA_DIR / "profiles"
SCENARIOS_DIR = DATA_DIR / "scenarios"

# --- Prototype thresholds; NASA provenance and limitations are documented per rule ---
CO2_GENERAL_LIMIT_1H_MMHG = 3.0   # 1h average module limit
CO2_7D_LIMIT_MMHG = 2.5           # 7d average for headache risk < 1%
SPO2_CRITICAL_PCT = 90
HR_CRITICAL_BPM = 160
SQI_MIN = 0.6
IMMOBILITY_THRESHOLD_H = 3.0
VENTILATION_LOW_PCT = 50
BED_FAN_LOCAL_CO2_TARGET_MMHG = 1.8
BED_FAN_LOCAL_WASHOUT_MINUTES = 5.0
MODULE_VENTILATION_CO2_TARGET_MMHG = 2.4
MODULE_VENTILATION_RESPONSE_MINUTES = 10.0

# --- Simulator ---
DEFAULT_SPEED = 1.0               # 1 real second = 1 sim minute
TICK_INTERVAL_SEC = 1.0
OLLAMA_REQUEST_TIMEOUT_SECONDS = 3.0  # Keep the simulation responsive; slow calls use cached text.