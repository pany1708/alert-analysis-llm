"""Pydantic models shared across services."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, root_validator


class AlertLabels(BaseModel):
    cluster: Optional[str]
    namespace: Optional[str]
    workload: Optional[str]
    component: Optional[str]
    environment: Optional[str] = None


class AlertMetrics(BaseModel):
    times: int = Field(..., ge=0)
    first_occur: Optional[datetime]


class RawEventMetadata(BaseModel):
    mail_subject: Optional[str]
    mail_id: Optional[str]
    source: Optional[str]
    payload: Optional[Dict[str, Any]]


class Event(BaseModel):
    alert: str
    severity: str
    labels: AlertLabels
    metrics: AlertMetrics
    raw: RawEventMetadata = Field(default_factory=RawEventMetadata)

    @root_validator
    def normalize_alert_name(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        alert = values.get("alert")
        if alert:
            values["alert"] = alert.strip()
        severity = values.get("severity")
        if severity:
            values["severity"] = severity.upper()
        return values


class RCAResponse(BaseModel):
    evidence_plan: Any
    diagnosis: Any
    actions: Any
    rollback: Any
    raw_response: Dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    event: Event
    rca: RCAResponse
    approved: bool
    actions_to_execute: Dict[str, Any]
    notes: Optional[str]
