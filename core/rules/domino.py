"""Illustrative crew workload scenario; no task assignment or fatigue model."""

def get_illustrative_domino_scenario(crew_id: str, status: str) -> dict | None:
    """Return a fixed display example for Ana's warning or critical state."""
    if status not in ["WARNING", "CRITICAL"]:
        return None

    if crew_id == "ana":
        receiver = "carlos"
        task = "extravehicular activity (EVA)"
        current_load = 40  # %
        added_load = 45    # %

        return {
            "source_crew": crew_id,
            "receiver_crew": receiver,
            "task": task,
            "current_load": current_load,
            "new_load": current_load + added_load,
            "message": (
                f"Illustrative scenario only: Ana is unavailable; Carlos is shown taking on {task}."
            ),
            "warning": (
                "Workload values are fixed examples. No crew schedule, task assignment, "
                "or fatigue model is evaluated."
            ),
        }
    return None