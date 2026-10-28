"""Cloned clinical notes: the same note text on claims of different participants.

Copy-paste cloning of medical records leaves the same note text on different patients. Notes are compared
word for word, numbers included (blood pressure, pulse, laboratory values differ between real patients),
after lowering case and dropping punctuation and spacing; two or more notes of different participants
that are then identical form one candidate group. Short notes (fewer than ``MIN_WORDS`` words, e.g. "kontrol rutin, tidak ada keluhan") are not
assessed, because legitimate routine notes can be that brief and alike.

Only claims that carry a note (the optional ``CATATAN_KLINIS`` column of an uploaded file) are assessed;
the BPJS sample has no notes, so the check is not applicable there. Note text is never copied into the
result: candidates name the claims and the number of participants only.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
import hashlib
import re
from typing import Any

from app.analytics.detector_utils import text_value, valid_records

INDICATOR = "cloned_clinical_note_candidate"
VERSION = "note-clone-v1"
MIN_WORDS = 12
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def note_fingerprint(note: str) -> str | None:
    """Digest of the note's words and numbers (lower case, no punctuation); None for short notes."""
    words = _WORD.findall(note.lower())
    if len(words) < MIN_WORDS:
        return None
    return hashlib.sha256(" ".join(words).encode("utf-8")).hexdigest()


def detect_cloned_notes(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = valid_records(records)
    groups: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    not_applicable, unassessed = [], []
    for case_id, row in rows:
        note = text_value(row.get("clinical_note"))
        if note is None:
            not_applicable.append(case_id)
            continue
        fingerprint = note_fingerprint(note)
        if fingerprint is None:
            unassessed.append(case_id)
            continue
        groups[fingerprint].append((case_id, text_value(row.get("participant_token"))))
    candidates = []
    for number, members in enumerate(sorted(groups.values(), key=lambda items: items[0][0]), start=1):
        participants = {token for _case, token in members if token}
        if len(members) < 2 or len(participants) < 2:
            continue
        candidates.append({
            "group_id": f"note-clone-{number:04d}",
            "case_ids": sorted(case for case, _token in members),
            "candidate_record_count": len(members),
            "distinct_participant_count": len(participants),
            "reason": (f"Catatan klinis {len(members)} klaim dari {len(participants)} peserta berbeda identik kata demi kata, "
                       "termasuk angka pemeriksaannya. Periksa apakah rekam medis disalin antar pasien."),
        })
    return {
        "indicator": INDICATOR,
        "status": "not_applicable" if len(not_applicable) == len(rows) and rows else "complete",
        "version": VERSION,
        "input_record_count": len(rows),
        "assessed_count": len(rows) - len(not_applicable) - len(unassessed),
        "candidate_count": sum(len(item["case_ids"]) for item in candidates),
        "candidate_groups": candidates,
        "unassessed_case_ids": unassessed,
        "not_applicable_cases": [{"case_id": case_id} for case_id in not_applicable],
        "search_truncated": False,
        "limitations": [
            "Hanya mendeteksi salinan yang identik kata demi kata (tanda baca diabaikan); parafrase tidak tertangkap.",
            "Catatan rutin yang sangat pendek tidak dinilai.",
        ],
    }
