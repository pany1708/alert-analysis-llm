"""Policy evaluation utilities."""
from __future__ import annotations

import operator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml

from services.common.models import Event, PolicyDecision, RCAResponse


OPERATORS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}


def _resolve_path(event: Event, path: str) -> Any:
    node: Any = event.dict()
    for part in path.split('.'):
        node = node.get(part)
        if node is None:
            return None
    return node


@dataclass
class PolicyRepository:
    path: Path

    def load(self) -> Dict[str, Any]:
        with self.path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}


class PolicyEngine:
    def __init__(self, repository: PolicyRepository):
        self.repository = repository
        self._policies = self.repository.load()

    def refresh(self) -> None:
        self._policies = self.repository.load()

    def evaluate(self, event: Event, rca: RCAResponse) -> PolicyDecision:
        policy = self._policies.get(event.alert.lower())
        if not policy:
            return PolicyDecision(
                event=event,
                rca=rca,
                approved=False,
                actions_to_execute={},
                notes="No policy found",
            )
        notes = []
        for rule in policy.get("diagnosis_rules", []):
            condition = rule.get("when", "")
            if not condition:
                continue
            lhs, op_symbol, rhs = self._parse_condition(condition)
            lhs_value = _resolve_path(event, lhs)
            rhs_value = self._coerce(rhs)
            if op_symbol(lhs_value, rhs_value):
                notes.append(rule.get("then"))
        requires_approval = policy.get("actions", {}).get("risky", {}).get("approval_required", False)
        approved = not requires_approval
        actions = {
            "safe": policy.get("actions", {}).get("safe", []),
        }
        if approved:
            actions["risky"] = policy.get("actions", {}).get("risky", {}).get("steps", [])
        return PolicyDecision(
            event=event,
            rca=rca,
            approved=approved,
            actions_to_execute=actions,
            notes="; ".join(filter(None, notes)) or None,
        )

    def _parse_condition(self, condition: str):
        for symbol, op in OPERATORS.items():
            if symbol in condition:
                lhs, rhs = condition.split(symbol, 1)
                return lhs.strip(), op, rhs.strip().strip('"')
        raise ValueError(f"Unsupported condition: {condition}")

    def _coerce(self, value: str):
        try:
            return int(value)
        except ValueError:
            pass
        return value
