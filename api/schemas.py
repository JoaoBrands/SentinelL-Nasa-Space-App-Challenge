"""Pydantic schemas - placeholder for Batch 1.
Will normalize simulator state + official NASA datasets in future batches.
"""
from pydantic import BaseModel


class CrewStatus(BaseModel):
    crew_id: str
    status: str
    alerts: list[dict]
    metrics: dict