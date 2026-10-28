"""Context of one claim inside its uploaded file: claims with the same clinical note, and the participant's other visits.

Uploaded files are immutable, so each file's index is built once per process (small LRU). The answers name
claims only by their pseudonymous case id and carry dates, codes and notes of uploaded example data; the
participant token stays inside this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Any

from app.analytics.note_similarity import note_fingerprint
from app.services.batches import BatchStore

MAX_NOTE_MATCHES = 12
MAX_VISITS = 30
# Numbers as written in notes: 120/80, 36,8, 12.4, 98.
_NUMBER = re.compile(r"\d+(?:[.,/]\d+)*")


@dataclass
class _BatchIndex:
    by_note: dict[str, list[str]] = field(default_factory=dict)
    by_participant: dict[str, list[str]] = field(default_factory=dict)
    participant_of: dict[str, str] = field(default_factory=dict)
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)


@lru_cache(maxsize=2)
def _index(db_path: str, batch_id: str) -> _BatchIndex:
    index = _BatchIndex()
    for record in BatchStore(db_path).batch_records(batch_id):
        case_id = record.get("case_id")
        if not case_id:
            continue
        note = record.get("clinical_note") or ""
        index.facts[case_id] = {key: record.get(key) for key in
                                ("service_date", "discharge_date", "claim_group", "primary_diagnosis")} | {"clinical_note": note}
        fingerprint = note_fingerprint(note) if note else None
        if fingerprint:
            index.by_note.setdefault(fingerprint, []).append(case_id)
        token = record.get("participant_token")
        if token:
            index.by_participant.setdefault(token, []).append(case_id)
            index.participant_of[case_id] = token
    return index


def note_numbers(note: str) -> list[str]:
    """The numbers in a note (vital signs, lab values), in order and without repeats."""
    return list(dict.fromkeys(_NUMBER.findall(note)))


def note_matches(db_path: str, batch_id: str, case_id: str) -> dict[str, Any]:
    """Other claims of the file whose note is identical word for word (numbers included)."""
    index = _index(db_path, batch_id)
    note = index.facts.get(case_id, {}).get("clinical_note") or ""
    fingerprint = note_fingerprint(note) if note else None
    members = index.by_note.get(fingerprint, []) if fingerprint else []
    others = [member for member in members if member != case_id]
    participants = {index.participant_of.get(member) for member in members} - {None}
    return {
        "total_claims": len(members) if others else 0,
        "distinct_participants": len(participants) if others else 0,
        "numbers": note_numbers(note) if others else [],
        "matches": [{"case_id": member, **{key: index.facts[member][key] for key in
                                          ("service_date", "discharge_date", "claim_group", "primary_diagnosis")}}
                    for member in sorted(others, key=lambda item: (index.facts[item]["service_date"] or "", item))[:MAX_NOTE_MATCHES]],
        "matches_truncated": len(others) > MAX_NOTE_MATCHES,
    }


def participant_visits(db_path: str, batch_id: str, case_id: str) -> dict[str, Any]:
    """The participant's claims in the same file, oldest first (the nearest ones when there are many)."""
    index = _index(db_path, batch_id)
    token = index.participant_of.get(case_id)
    members = index.by_participant.get(token, [case_id]) if token else [case_id]
    current = index.facts.get(case_id, {}).get("service_date") or ""
    if len(members) > MAX_VISITS:
        # Keep the visits closest in time to this claim.
        members = sorted(members, key=lambda item: abs(_day(index.facts[item]["service_date"]) - _day(current)))[:MAX_VISITS]
    visits = sorted(members, key=lambda item: (index.facts[item]["service_date"] or "", index.facts[item]["discharge_date"] or "", item))
    return {
        "total_visits": len(index.by_participant.get(token, [case_id])) if token else 1,
        "visits": [{"case_id": member, "current": member == case_id,
                    "inpatient": bool(index.facts[member]["discharge_date"]) and index.facts[member]["discharge_date"] != index.facts[member]["service_date"],
                    **{key: index.facts[member][key] for key in ("service_date", "discharge_date", "claim_group", "primary_diagnosis")}}
                   for member in visits],
    }


def _day(value: str | None) -> int:
    try:
        return date.fromisoformat(value or "").toordinal()
    except ValueError:
        return 0
