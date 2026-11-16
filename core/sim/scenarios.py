"""Scenario loader."""
import json
from core.config import SCENARIOS_DIR


def load_scenario(scenario_id: str) -> dict:
    path = SCENARIOS_DIR / f"{scenario_id}.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_scenarios() -> list[str]:
    return [p.stem for p in SCENARIOS_DIR.glob("*.json")]