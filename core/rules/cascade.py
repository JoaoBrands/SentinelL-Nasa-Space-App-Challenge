"""Illustrative scenario sequence; not a validated clinical progression model."""

CASCADES = {
    "co2_pocket": {
        "trigger": "co2_pocket_inference",
        "nodes": [
            {"id": "congestion", "label": "Possible nasal congestion", "simulation_hour": 0.5},
            {"id": "headache", "label": "Possible headache", "simulation_hour": 2},
            {"id": "sleep_frag", "label": "Potential sleep disruption", "simulation_hour": 12},
            {"id": "hrv_drop", "label": "Potential HRV change", "simulation_hour": 24},
            {"id": "cv_risk", "label": "Potential cardiovascular concern", "simulation_hour": 48}
        ]
    }
}

def get_cascade(trigger_id: str) -> list[dict]:
    cascade = CASCADES.get(trigger_id)
    return cascade["nodes"] if cascade else []