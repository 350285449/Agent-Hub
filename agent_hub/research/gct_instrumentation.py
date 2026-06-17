from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable


LEDGER_VERSION = 1
GAR_SCHEMA_VERSION = 1
COMMITMENT_SCHEMA_VERSION = 1
LOCK_IN_THRESHOLD = 0.8


class GCTEventType(StrEnum):
    EVIDENCE_DISCOVERY = "evidence_discovery"
    EVIDENCE_RECOGNITION = "evidence_recognition"
    EVIDENCE_INTERPRETATION = "evidence_interpretation"
    JUSTIFICATION = "justification_event"
    BRANCH_CREATION = "branch_creation"
    BRANCH_SELECTION = "branch_selection"
    BRANCH_SWITCHING = "branch_switching"
    COMMITMENT = "commitment_event"
    UNCERTAINTY_ESTIMATE = "uncertainty_estimate"
    INTERVENTION = "intervention_event"
    OUTCOME = "outcome_event"
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"


PRE_COMMIT_EVENT_TYPES = {
    GCTEventType.EVIDENCE_DISCOVERY,
    GCTEventType.EVIDENCE_RECOGNITION,
    GCTEventType.EVIDENCE_INTERPRETATION,
    GCTEventType.JUSTIFICATION,
    GCTEventType.BRANCH_CREATION,
    GCTEventType.UNCERTAINTY_ESTIMATE,
    GCTEventType.INTERVENTION,
}

GROUNDABLE_ACTION_TYPES = {
    GCTEventType.EVIDENCE_RECOGNITION,
    GCTEventType.EVIDENCE_INTERPRETATION,
    GCTEventType.JUSTIFICATION,
    GCTEventType.BRANCH_CREATION,
    GCTEventType.BRANCH_SELECTION,
    GCTEventType.BRANCH_SWITCHING,
    GCTEventType.COMMITMENT,
}

EVIDENCE_TYPES = {
    GCTEventType.EVIDENCE_DISCOVERY,
    GCTEventType.EVIDENCE_RECOGNITION,
    GCTEventType.EVIDENCE_INTERPRETATION,
}


@dataclass(slots=True)
class GCTEvent:
    run_id: str
    row_id: str
    event_type: GCTEventType
    seq: int
    monotonic_ms: int
    event_id: str
    timestamp: str
    trial_id: str = ""
    phase: str = ""
    branch_id: str = ""
    selected_branch_id: str = ""
    previous_branch_id: str = ""
    evidence_unit: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    local_grounding: float | None = None
    uncertainty: float | None = None
    commitment_strength: float | None = None
    lock_in: bool | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "ledger_version": LEDGER_VERSION,
            "run_id": self.run_id,
            "trial_id": self.trial_id,
            "row_id": self.row_id,
            "seq": self.seq,
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "monotonic_ms": self.monotonic_ms,
            "event_type": self.event_type.value,
            "phase": self.phase,
            "branch_id": self.branch_id,
            "selected_branch_id": self.selected_branch_id,
            "previous_branch_id": self.previous_branch_id,
            "evidence_unit": self.evidence_unit,
            "evidence_refs": list(self.evidence_refs),
            "local_grounding": self.local_grounding,
            "uncertainty": self.uncertainty,
            "commitment_strength": self.commitment_strength,
            "lock_in": self.lock_in,
            "payload": dict(self.payload),
        }
        return {key: value for key, value in data.items() if value not in ("", [], {}, None)}


class JsonlLedger:
    """Append-only JSONL ledger with one event per line."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: GCTEvent) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")

    def read_events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                row["_line_number"] = line_number
                events.append(row)
        return events


class GCTRunRecorder:
    def __init__(self, ledger: JsonlLedger, *, run_id: str, row: dict[str, Any]) -> None:
        self.ledger = ledger
        self.run_id = run_id
        self.row = dict(row)
        self._seq = 0
        self._started = time.perf_counter()
        self._event_ids: set[str] = set()

    @property
    def committed(self) -> bool:
        return any(event.get("event_type") == GCTEventType.COMMITMENT.value for event in self.ledger.read_events() if event.get("run_id") == self.run_id)

    def record(
        self,
        event_type: GCTEventType | str,
        *,
        phase: str = "",
        branch_id: str = "",
        selected_branch_id: str = "",
        previous_branch_id: str = "",
        evidence_unit: str = "",
        evidence_refs: Iterable[str] | None = None,
        local_grounding: float | None = None,
        uncertainty: float | None = None,
        commitment_strength: float | None = None,
        lock_in: bool | None = None,
        payload: dict[str, Any] | None = None,
    ) -> GCTEvent:
        event_type = GCTEventType(event_type)
        self._seq += 1
        event_id = self._event_id(event_type, self._seq, branch_id, evidence_unit)
        event = GCTEvent(
            run_id=self.run_id,
            trial_id=str(self.row.get("trial_id") or ""),
            row_id=str(self.row.get("row_id") or ""),
            event_type=event_type,
            seq=self._seq,
            event_id=event_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            monotonic_ms=int(round((time.perf_counter() - self._started) * 1000)),
            phase=phase,
            branch_id=branch_id,
            selected_branch_id=selected_branch_id,
            previous_branch_id=previous_branch_id,
            evidence_unit=evidence_unit,
            evidence_refs=list(evidence_refs or []),
            local_grounding=_clamp01_or_none(local_grounding),
            uncertainty=_clamp01_or_none(uncertainty),
            commitment_strength=_clamp01_or_none(commitment_strength),
            lock_in=lock_in,
            payload=dict(payload or {}),
        )
        self.ledger.append(event)
        self._event_ids.add(event_id)
        return event

    def _event_id(self, event_type: GCTEventType, seq: int, branch_id: str, evidence_unit: str) -> str:
        seed = "|".join(
            (
                self.run_id,
                str(self.row.get("row_id") or ""),
                str(seq),
                event_type.value,
                branch_id,
                evidence_unit,
            )
        )
        return "gcte_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def calculate_gar(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted((dict(event) for event in events), key=lambda row: int(row.get("seq") or 0))
    evidence_ids: set[str] = set()
    local_grounding: dict[str, float] = {}
    first_commit_seq = _first_seq(ordered, GCTEventType.COMMITMENT)
    action_rows: list[dict[str, Any]] = []

    for event in ordered:
        event_type = GCTEventType(str(event.get("event_type")))
        event_id = str(event.get("event_id") or "")
        if event_type in EVIDENCE_TYPES and event_id:
            evidence_ids.add(event_id)
        if event_type in GROUNDABLE_ACTION_TYPES:
            grounding = _event_grounding(event, evidence_ids)
            local_grounding[event_id] = grounding
            row = dict(event)
            row["computed_local_grounding"] = grounding
            action_rows.append(row)

    pre = [event for event in action_rows if first_commit_seq is None or int(event.get("seq") or 0) < first_commit_seq]
    post = [event for event in action_rows if first_commit_seq is not None and int(event.get("seq") or 0) >= first_commit_seq]
    return {
        "gar_schema_version": GAR_SCHEMA_VERSION,
        "action_event_count": len(action_rows),
        "grounded_action_event_count": sum(1 for event in action_rows if event["computed_local_grounding"] >= 1.0),
        "local_grounding": local_grounding,
        "pre_commit_gar": _mean_grounding(pre),
        "post_commit_gar": _mean_grounding(post),
        "overall_gar": _mean_grounding(action_rows),
        "first_commit_seq": first_commit_seq,
        "invalid_reason": "" if action_rows else "no_groundable_action_events",
    }


def measure_commitment(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted((dict(event) for event in events), key=lambda row: int(row.get("seq") or 0))
    selections = [event for event in ordered if event.get("event_type") == GCTEventType.BRANCH_SELECTION.value]
    switches = [event for event in ordered if event.get("event_type") == GCTEventType.BRANCH_SWITCHING.value]
    commitments = [event for event in ordered if event.get("event_type") == GCTEventType.COMMITMENT.value]
    first_selection = selections[0] if selections else None
    onset = commitments[0] if commitments else None
    strength = _optional_float(onset.get("commitment_strength")) if onset else None
    explicit_lock = any(bool(event.get("lock_in")) for event in commitments)
    no_reversal_after_onset = not onset or not [
        event for event in switches if int(event.get("seq") or 0) > int(onset.get("seq") or 0)
    ]
    lock_in = bool(explicit_lock or (strength is not None and strength >= LOCK_IN_THRESHOLD and no_reversal_after_onset))
    return {
        "commitment_schema_version": COMMITMENT_SCHEMA_VERSION,
        "first_branch_choice": (first_selection or {}).get("selected_branch_id") or (first_selection or {}).get("branch_id") or "",
        "first_branch_choice_seq": int(first_selection.get("seq") or 0) if first_selection else None,
        "commitment_onset_seq": int(onset.get("seq") or 0) if onset else None,
        "commitment_strength": strength,
        "branch_reversals": len(switches),
        "branch_reversal_events": [event.get("event_id") for event in switches],
        "lock_in": lock_in,
        "invalid_reason": "" if first_selection and onset else "missing_branch_selection_or_commitment",
    }


def apply_pre_commit_intervention(
    recorder: GCTRunRecorder,
    *,
    intervention_id: str,
    prompt: str,
    evidence_refs: Iterable[str] | None = None,
) -> GCTEvent:
    if _has_commitment(recorder.ledger.read_events(), recorder.run_id):
        raise RuntimeError("GCT intervention attempted after commitment onset")
    return recorder.record(
        GCTEventType.INTERVENTION,
        phase="pre_commit_intervention",
        evidence_refs=list(evidence_refs or []),
        payload={"intervention_id": intervention_id, "prompt": prompt},
    )


def validate_pre_commit_interventions(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted((dict(event) for event in events), key=lambda row: int(row.get("seq") or 0))
    first_commit = _first_seq(ordered, GCTEventType.COMMITMENT)
    invalid = [
        event
        for event in ordered
        if event.get("event_type") == GCTEventType.INTERVENTION.value
        and first_commit is not None
        and int(event.get("seq") or 0) >= first_commit
    ]
    return {
        "valid": not invalid,
        "first_commit_seq": first_commit,
        "intervention_count": sum(1 for event in ordered if event.get("event_type") == GCTEventType.INTERVENTION.value),
        "invalid_intervention_event_ids": [event.get("event_id") for event in invalid],
    }


def events_for_run(path: str | Path, run_id: str) -> list[dict[str, Any]]:
    return [event for event in JsonlLedger(path).read_events() if event.get("run_id") == run_id]


def panel_run_id(trial_id: str, row_id: str, run_seed: int | str) -> str:
    digest = hashlib.sha256(f"{trial_id}|{row_id}|{run_seed}".encode("utf-8")).hexdigest()[:24]
    return f"gctrun_{digest}"


def _event_grounding(event: dict[str, Any], available_evidence_ids: set[str]) -> float:
    explicit = _optional_float(event.get("local_grounding"))
    refs = [str(ref) for ref in event.get("evidence_refs") or [] if str(ref)]
    if refs:
        linked = sum(1 for ref in refs if ref in available_evidence_ids)
        linked_grounding = linked / len(refs)
        if explicit is None:
            return linked_grounding
        return min(_clamp01(explicit), linked_grounding)
    if GCTEventType(str(event.get("event_type"))) in EVIDENCE_TYPES:
        return 1.0 if explicit is None else _clamp01(explicit)
    return 0.0 if explicit is None else min(_clamp01(explicit), 0.5)


def _mean_grounding(events: list[dict[str, Any]]) -> float | None:
    if not events:
        return None
    return round(sum(float(event["computed_local_grounding"]) for event in events) / len(events), 6)


def _first_seq(events: list[dict[str, Any]], event_type: GCTEventType) -> int | None:
    for event in events:
        if event.get("event_type") == event_type.value:
            return int(event.get("seq") or 0)
    return None


def _has_commitment(events: Iterable[dict[str, Any]], run_id: str) -> bool:
    return any(
        event.get("run_id") == run_id and event.get("event_type") == GCTEventType.COMMITMENT.value
        for event in events
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _clamp01_or_none(value: float | None) -> float | None:
    return None if value is None else _clamp01(value)


__all__ = [
    "GCTEvent",
    "GCTEventType",
    "GCTRunRecorder",
    "JsonlLedger",
    "apply_pre_commit_intervention",
    "calculate_gar",
    "events_for_run",
    "measure_commitment",
    "panel_run_id",
    "validate_pre_commit_interventions",
]
