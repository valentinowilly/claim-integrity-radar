"""Synthetic benchmark for the four proposal modes on one shared data contract.

Modes: Repeat Billing, Cloning, Phantom Billing and fictitious drug/medical-device
claims. Run from ``backend/``::

    python -m scripts.mode_benchmark --seeds 1-10 --aggregate-only

Data contract:

* Every record has exactly the canonical feature fields
  (``app.data_sources.providers.CANONICAL_FEATURE_FIELDS``) and passes
  ``canonicalize_feature_dataset``. Fields the FKRTL adapter maps keep the FKRTL
  shape (no amount; FKL48 does not exist here).
* ``SYNTHETIC_ONLY_FIELDS`` are canonical fields the FKRTL adapter always sets to
  ``None`` (facility identity, service type, evidence inventory, ...). They are
  populated here for simulation only; the real sample does not have them.
* Item lines, dispensing lines and execution-log dates are not canonical at all.
  They live in a separate synthetic ``sidecar`` that only the naive baselines read.
* Ground truth (scenario per record, positive/control) is returned in ``truth``
  and never enters records, the sidecar, or any detector.

Shared statistics: the only real-data input is an aggregate rate, the FKL30
blank rate of the whole FKRTL file (708,359 of 1,699,219 rows), applied at the
same rate to every scenario so missingness never marks a class. Code tables,
facility pools and scenario sizes are synthetic assumptions.

Detectors are the existing ones with their current settings (no new detector,
no tuning). Results describe synthetic behaviour of this configuration and are
not fraud accuracy on BPJS data.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, timedelta
import json
from pathlib import Path
import random
from typing import Any, Mapping, Sequence

from app.analytics.evidence_completeness import DEFAULT_REQUIRED_EVIDENCE, detect_evidence_completeness
from app.analytics.ml_anomaly import build_ml_anomaly_ranking
from app.analytics.near_duplicate_claims import NearDuplicateConfig, detect_near_duplicate_claims
from app.analytics.repeat_billing import REPEAT_SERVICE_PROFILE, SIGNATURE_PROFILES, detect_repeat_billing_candidates
from app.analytics.similar_claim_pattern import detect_similar_claim_patterns
from app.data_sources.bpjs_fkrtl_adapter import CANONICAL_MAPPING
from app.data_sources.providers import CANONICAL_FEATURE_FIELDS, FeatureDataset, canonicalize_feature_dataset
from scripts.detection_benchmark import DEFAULT_SEEDS, WINDOW_START, _code_tables, _opaque, _parse_seeds, _stats

MODE_BENCHMARK_VERSION = "cir-synthetic-four-mode-benchmark-v1"
LABEL = "SYNTHETIC BENCHMARK - simulated scenarios, not fraud accuracy on BPJS data"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "benchmarks"
WINDOW_DAYS = 14
AGGREGATE_BASIS = {
    "procedure_code_blank_rate": round(708_359 / 1_699_219, 4),
    "source": "whole-file FKRTL aggregate (FKL30 blank rows / all rows); no rows or identifiers copied",
}
# Synthetic assumption, applied to every evidence-bearing claim regardless of label.
SYNC_PENDING_RATE = 0.12
FKRTL_MAPPED_FIELDS = frozenset({"case_id", "participant_token", "provider_billed_amount_unverified", *CANONICAL_MAPPING})
SYNTHETIC_ONLY_FIELDS = tuple(
    field for field in CANONICAL_FEATURE_FIELDS if field not in FKRTL_MAPPED_FIELDS and field != "billed_amount"
)
MODES = ("repeat_billing", "cloning", "phantom_billing", "drug_device_fictitious")
GENERAL_SERVICE = "general_inpatient"  # no evidence rule: evidence check not applicable
DRUG_SERVICE = "synthetic_drug_device"
# Scenario rule set: the existing defaults plus the simulated dispensing requirement.
SCENARIO_EVIDENCE_RULES = {**DEFAULT_REQUIRED_EVIDENCE, DRUG_SERVICE: ("dispensing_record",)}
EXECUTION_EVIDENCE = {"physiotherapy": "therapy_session_log", "synthetic_supported_action": "procedure_order"}
RECORDING_VARIANT = {"therapy_session_log": "therapy_session_note", "procedure_order": "procedure_order_scan"}
ITEM_CATALOG = (("DRG-A", "tablet"), ("DRG-B", "vial"), ("DRG-C", "tablet"), ("DEV-A", "unit"), ("DEV-B", "unit"))
ALLOWED_SUBSTITUTES = {"DRG-A": "DRG-A-GENERIC", "DRG-C": "DRG-C-GENERIC"}
SERVICE_MIX = ((GENERAL_SERVICE, 0.55), ("physiotherapy", 0.15), ("synthetic_supported_action", 0.15), (DRUG_SERVICE, 0.15))

# Scenario contract: mode, positive or legitimate control, and meaning.
SCENARIOS: dict[str, dict[str, str]] = {
    "background": {"mode": "background", "role": "control", "meaning": "Routine claim."},
    "repeat_exact": {"mode": "repeat_billing", "role": "positive",
                     "meaning": "Same episode submitted twice; every field identical."},
    "repeat_context_variation": {"mode": "repeat_billing", "role": "positive",
                                 "meaning": "Same episode resubmitted with a re-recorded facility category or admission diagnosis."},
    "repeat_control_different_procedure": {"mode": "repeat_billing", "role": "control",
                                           "meaning": "Same participant and day, different procedure: separate service."},
    "repeat_control_next_day": {"mode": "repeat_billing", "role": "control",
                                "meaning": "New episode on the next day with the same codes."},
    "repeat_control_referral_same_day": {"mode": "repeat_billing", "role": "control",
                                         "meaning": "Legitimate same-day referral to another facility with a different category profile; same codes."},
    "clone_variation_admission": {"mode": "cloning", "role": "positive",
                                  "meaning": "Claim copied to another participant, same synthetic facility, admission diagnosis changed."},
    "clone_variation_care_class": {"mode": "cloning", "role": "positive",
                                   "meaning": "Copied to another participant, care class changed."},
    "clone_variation_procedure": {"mode": "cloning", "role": "positive",
                                  "meaning": "Copied to another participant, procedure changed within the INA-CBG."},
    "clone_variation_date": {"mode": "cloning", "role": "positive",
                             "meaning": "Copied to another participant, admission and discharge shifted by one day."},
    "clone_control_routine_same_facility": {"mode": "cloning", "role": "control",
                                            "meaning": "Different participants, same facility and day, common codes, independent stay."},
    "clone_control_other_facility_same_categories": {"mode": "cloning", "role": "control",
                                                     "meaning": "As routine, but at another facility sharing every FKRTL-style category."},
    "phantom_no_execution_record": {"mode": "phantom_billing", "role": "positive",
                                    "meaning": "Inventory recorded; the required execution record is absent."},
    "phantom_log_not_matching": {"mode": "phantom_billing", "role": "positive",
                                 "meaning": "Execution record present but for another day (sidecar only)."},
    "phantom_control_sync_pending": {"mode": "phantom_billing", "role": "control",
                                     "meaning": "Service performed; evidence inventory not yet synchronised."},
    "phantom_control_recording_variant": {"mode": "phantom_billing", "role": "control",
                                          "meaning": "Service performed; execution record filed under another document type."},
    "drug_no_dispensing_all_items": {"mode": "drug_device_fictitious", "role": "positive",
                                     "meaning": "Items billed; no dispensing record for any item."},
    "drug_one_item_undispensed": {"mode": "drug_device_fictitious", "role": "positive",
                                  "meaning": "Several items billed; one has no dispensing record."},
    "drug_control_late_dispensing": {"mode": "drug_device_fictitious", "role": "control",
                                     "meaning": "Dispensed; record arrives after the snapshot."},
    "drug_control_unit_difference": {"mode": "drug_device_fictitious", "role": "control",
                                      "meaning": "Billed per box, dispensed in tablets (same quantity of medicine)."},
    "drug_control_allowed_substitution": {"mode": "drug_device_fictitious", "role": "control",
                                          "meaning": "Dispensed an allowed generic substitute."},
}
DETECTORS = (
    "repeat_service_v1", "repeat_eleven_field", "similar_claim_pattern", "near_duplicate",
    "evidence_default_rules", "evidence_scenario_rules", "ml_ranking_top_k",
)
BASELINE_FOR_MODE = {
    "repeat_billing": "naive_same_participant_same_day",
    "cloning": "naive_same_synthetic_facility_template",
    "phantom_billing": "naive_execution_record_linkage",
    "drug_device_fictitious": "naive_item_exact_dispensing",
}


def _facilities(rng: random.Random) -> list[dict[str, Any]]:
    """Every FKRTL-style category tuple is shared by two synthetic facilities.

    Pool sizes are synthetic assumptions (60 tuples over 30 districts in 10 provinces, 120
    facilities). A first draft with 5 districts made most background claims
    near-duplicates of each other, an artefact of the tiny code space.
    """
    facilities = []
    for tuple_index in range(60):
        municipality = f"M{tuple_index % 30:02d}"
        categories = {
            "province_code": f"P{tuple_index % 30 // 3}",
            "municipality_code": municipality, "facility_ownership": str(1 + tuple_index % 2),
            "facility_type": "2", "facility_class": "ABC"[tuple_index % 3],
        }
        for copy in range(2):
            facilities.append({"facility_id": f"synfac-{tuple_index:02d}{copy}", **categories})
    rng.shuffle(facilities)
    return facilities


class _World:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        self.tables = _code_tables(self.rng)
        self.facilities = _facilities(self.rng)
        self.records: list[dict[str, Any]] = []
        self.sidecar: dict[str, dict[str, Any]] = {}
        self.labels: dict[str, str] = {}
        self._counter = 0

    def ids(self) -> tuple[str, str]:
        self._counter += 1
        return (f"case_{_opaque(self.seed, 'mode-case', self._counter)}",
                f"participant_{_opaque(self.seed, 'mode-person', self._counter)}")

    def common_service(self) -> tuple[str, str, str]:
        dx = self.rng.choice(self.tables["diagnoses"][:5])
        cbg = self.tables["cbg_for"][dx]
        return dx, cbg, self.rng.choice(self.tables["procedures"][cbg])

    def claim(self, *, participant: str | None = None, facility: Mapping[str, Any] | None = None,
              day: int | None = None, service_type: str | None = None, dx: str | None = None,
              cbg: str | None = None, procedure: str | None = None, stay: int | None = None) -> dict[str, Any]:
        rng, tables = self.rng, self.tables
        case_id, person = self.ids()
        facility = facility or rng.choice(self.facilities)
        dx = dx or rng.choices(tables["diagnoses"], tables["weights"])[0]
        cbg = cbg or tables["cbg_for"][dx]
        day = rng.randrange(WINDOW_DAYS) if day is None else day
        stay = rng.randint(0, 3) if stay is None else stay
        admitted = WINDOW_START + timedelta(days=day)
        row = {field: None for field in CANONICAL_FEATURE_FIELDS}
        row.update({
            "case_id": case_id, "participant_token": participant or person,
            "service_date": admitted.isoformat(), "discharge_date": (admitted + timedelta(days=stay)).isoformat(),
            **{key: facility[key] for key in ("province_code", "municipality_code", "facility_ownership",
                                               "facility_type", "facility_class")},
            "care_class": rng.choice(["1", "2", "3"]),
            "admission_diagnosis": dx if rng.random() < 0.85 else rng.choice(tables["diagnoses"]),
            "primary_diagnosis": dx, "claim_group": cbg,
            "procedure_code": procedure or rng.choice(tables["procedures"][cbg]),
            "facility_id": facility["facility_id"],
            "service_type": service_type or rng.choices([s for s, _ in SERVICE_MIX], [w for _, w in SERVICE_MIX])[0],
        })
        self._complete_evidence(row)
        return row

    def _complete_evidence(self, row: dict[str, Any]) -> None:
        service = row["service_type"]
        rule = SCENARIO_EVIDENCE_RULES.get(service)
        if rule is None:
            return
        row["supporting_evidence_required"] = list(rule)
        row["supporting_evidence_types"] = list(rule)
        row["supporting_evidence_present"] = True
        row["supporting_evidence_recording_status"] = "recorded"
        if service == DRUG_SERVICE:
            items = self.items(self.rng.randint(1, 3))
            self.sidecar[row["case_id"]] = {"items": items, "dispensing": [{**item, "on_time": True} for item in items]}
        else:
            self.sidecar[row["case_id"]] = {"execution_log_matches_service_day": True}

    def items(self, count: int) -> list[dict[str, Any]]:
        """Distinct catalogue items, so one missing dispensing line is always observable."""
        return [{"item": code, "quantity": self.rng.randint(1, 10), "unit": unit}
                for code, unit in self.rng.sample(ITEM_CATALOG, count)]

    def add(self, scenario: str, *rows: dict[str, Any]) -> None:
        for row in rows:
            self.records.append(row)
            self.labels[row["case_id"]] = scenario

    def copy(self, row: Mapping[str, Any], **changes: Any) -> dict[str, Any]:
        case_id, _person = self.ids()
        copied = {**row, "case_id": case_id, **changes}
        for key in ("supporting_evidence_required", "supporting_evidence_types"):
            if isinstance(copied.get(key), list):
                copied[key] = list(copied[key])
        if row["case_id"] in self.sidecar:
            self.sidecar[case_id] = json.loads(json.dumps(self.sidecar[row["case_id"]]))
        return copied


def _blank_procedure(world: _World, rows: Sequence[dict[str, Any]]) -> None:
    """Aggregate FKL30 blank rate, decided once per episode group for every scenario alike."""
    if world.rng.random() < AGGREGATE_BASIS["procedure_code_blank_rate"]:
        for row in rows:
            row["procedure_code"] = None


def _maybe_sync_pending(world: _World, row: dict[str, Any]) -> None:
    if row.get("supporting_evidence_recording_status") == "recorded" and world.rng.random() < SYNC_PENDING_RATE:
        _set_pending(row)


def _set_pending(row: dict[str, Any]) -> None:
    row["supporting_evidence_recording_status"] = "not_recorded"
    row["supporting_evidence_types"] = None
    row["supporting_evidence_present"] = None


def _other(values: Sequence[str], current: str, rng: random.Random) -> str:
    return rng.choice([value for value in values if value != current])


def generate_mode_benchmark(seed: int = 7, background: int = 1500, planted: int = 12
                            ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    """Return (records, sidecar, truth). Labels exist only in ``truth``."""
    world = _World(seed)
    rng, tables = world.rng, world.tables

    for _ in range(background):
        row = world.claim()
        _blank_procedure(world, [row])
        _maybe_sync_pending(world, row)
        world.add("background", row)
    # Some background participants visit again on another day (legitimate).
    for row in rng.sample(world.records, background // 10):
        again = world.claim(participant=row["participant_token"], day=rng.randrange(WINDOW_DAYS))
        if again["service_date"] != row["service_date"]:
            _blank_procedure(world, [again])
            _maybe_sync_pending(world, again)
            world.add("background", again)

    for _ in range(planted):
        # Repeat Billing: pairs of the same participant.
        dx, cbg, proc = world.common_service()
        first = world.claim(dx=dx, cbg=cbg, procedure=proc, service_type=GENERAL_SERVICE)
        pair = [first, world.copy(first)]
        _blank_procedure(world, pair)
        world.add("repeat_exact", *pair)

        dx, cbg, proc = world.common_service()
        first = world.claim(dx=dx, cbg=cbg, procedure=proc, service_type=GENERAL_SERVICE)
        field = rng.choice(["facility_class", "admission_diagnosis", "facility_ownership"])
        changed = {
            "facility_class": lambda: _other("ABC", first["facility_class"], rng),
            "admission_diagnosis": lambda: _other(tables["diagnoses"][:10], first["admission_diagnosis"], rng),
            "facility_ownership": lambda: _other("12", first["facility_ownership"], rng),
        }[field]()
        pair = [first, world.copy(first, **{field: changed})]
        _blank_procedure(world, pair)
        world.add("repeat_context_variation", *pair)

        dx, cbg, proc = world.common_service()
        first = world.claim(dx=dx, cbg=cbg, procedure=proc, service_type=GENERAL_SERVICE)
        pair = [first, world.copy(first, procedure_code=_other(tables["procedures"][cbg], proc, rng))]
        _blank_procedure(world, pair)  # both blank: the pair becomes unassessed, as in the real file
        world.add("repeat_control_different_procedure", *pair)

        dx, cbg, proc = world.common_service()
        start = rng.randrange(WINDOW_DAYS - 1)
        first = world.claim(dx=dx, cbg=cbg, procedure=proc, day=start, service_type=GENERAL_SERVICE)
        second = world.claim(participant=first["participant_token"], day=start + 1, dx=dx, cbg=cbg, procedure=proc,
                             service_type=GENERAL_SERVICE)
        pair = [first, second]
        _blank_procedure(world, pair)
        world.add("repeat_control_next_day", *pair)

        dx, cbg, proc = world.common_service()
        origin = rng.choice(world.facilities)
        first = world.claim(facility=origin, dx=dx, cbg=cbg, procedure=proc, service_type=GENERAL_SERVICE)
        elsewhere = rng.choice([f for f in world.facilities
                                if (f["facility_class"], f["municipality_code"]) != (origin["facility_class"], origin["municipality_code"])])
        second = world.claim(participant=first["participant_token"], facility=elsewhere, dx=dx, cbg=cbg, procedure=proc,
                             service_type=GENERAL_SERVICE)
        second["service_date"] = first["service_date"]
        second["discharge_date"] = first["discharge_date"]
        pair = [first, second]
        _blank_procedure(world, pair)
        world.add("repeat_control_referral_same_day", *pair)

        # Cloning: a copy to another participant in the same synthetic facility.
        for scenario in ("clone_variation_admission", "clone_variation_care_class",
                         "clone_variation_procedure", "clone_variation_date"):
            dx, cbg, proc = world.common_service()
            template = world.claim(dx=dx, cbg=cbg, procedure=proc)
            _case, other_person = world.ids()
            if scenario == "clone_variation_admission":
                changes = {"admission_diagnosis": _other(tables["diagnoses"][:5], template["admission_diagnosis"], rng)}
            elif scenario == "clone_variation_care_class":
                changes = {"care_class": _other("123", template["care_class"], rng)}
            elif scenario == "clone_variation_procedure":
                changes = {"procedure_code": _other(tables["procedures"][cbg], proc, rng)}
            else:
                shift = timedelta(days=1)
                changes = {key: (date.fromisoformat(template[key]) + shift).isoformat()
                           for key in ("service_date", "discharge_date")}
            clone = world.copy(template, participant_token=other_person, **changes)
            pair = [template, clone]
            _blank_procedure(world, pair)
            for row in pair:
                _maybe_sync_pending(world, row)
            world.add(scenario, *pair)

        for scenario in ("clone_control_routine_same_facility", "clone_control_other_facility_same_categories"):
            dx, cbg, proc = world.common_service()
            facility = rng.choice(world.facilities)
            first = world.claim(facility=facility, dx=dx, cbg=cbg, procedure=proc)
            if scenario == "clone_control_routine_same_facility":
                target = facility
            else:
                target = next(f for f in world.facilities if f["facility_id"] != facility["facility_id"]
                              and all(f[key] == facility[key] for key in ("province_code", "municipality_code",
                                                                           "facility_ownership", "facility_type",
                                                                           "facility_class")))
            second = world.claim(facility=target, dx=dx, cbg=cbg, procedure=proc)
            second["service_date"] = first["service_date"]
            second["discharge_date"] = (date.fromisoformat(first["service_date"])
                                        + timedelta(days=rng.randint(0, 3))).isoformat()
            pair = [first, second]
            _blank_procedure(world, pair)
            for row in pair:
                _maybe_sync_pending(world, row)
            world.add(scenario, *pair)

        # Phantom Billing: execution evidence (synthetic-only).
        for scenario in ("phantom_no_execution_record", "phantom_log_not_matching",
                         "phantom_control_sync_pending", "phantom_control_recording_variant"):
            row = world.claim(service_type=rng.choice(list(EXECUTION_EVIDENCE)))
            execution = EXECUTION_EVIDENCE[row["service_type"]]
            if scenario == "phantom_no_execution_record":
                row["supporting_evidence_types"] = [item for item in row["supporting_evidence_types"] if item != execution]
                row["supporting_evidence_present"] = bool(row["supporting_evidence_types"])
                world.sidecar[row["case_id"]]["execution_log_matches_service_day"] = None
            elif scenario == "phantom_log_not_matching":
                world.sidecar[row["case_id"]]["execution_log_matches_service_day"] = False
            elif scenario == "phantom_control_recording_variant":
                row["supporting_evidence_types"] = [RECORDING_VARIANT.get(item, item)
                                                    for item in row["supporting_evidence_types"]]
            if scenario == "phantom_control_sync_pending":
                _set_pending(row)
            else:
                _maybe_sync_pending(world, row)
            _blank_procedure(world, [row])
            world.add(scenario, row)

        # Fictitious drug/device items (item and dispensing lines are sidecar-only).
        for scenario in ("drug_no_dispensing_all_items", "drug_one_item_undispensed", "drug_control_late_dispensing",
                         "drug_control_unit_difference", "drug_control_allowed_substitution"):
            row = world.claim(service_type=DRUG_SERVICE)
            side = world.sidecar[row["case_id"]]
            if scenario == "drug_one_item_undispensed":
                side["items"] = world.items(rng.randint(2, 4))
            else:
                side["items"] = world.items(rng.randint(1, 3))
            if scenario in {"drug_control_unit_difference", "drug_control_allowed_substitution"}:
                side["items"][0] = {"item": rng.choice(list(ALLOWED_SUBSTITUTES)), "quantity": 1, "unit": "box"}
            side["dispensing"] = [{**item, "on_time": True} for item in side["items"]]
            if scenario == "drug_no_dispensing_all_items":
                side["dispensing"] = []
                row["supporting_evidence_types"] = []
                row["supporting_evidence_present"] = False
            elif scenario == "drug_one_item_undispensed":
                side["dispensing"].pop(rng.randrange(len(side["dispensing"])))
            elif scenario == "drug_control_late_dispensing":
                side["dispensing"] = [{**item, "on_time": False} for item in side["items"]]
                _set_pending(row)
            elif scenario == "drug_control_unit_difference":
                side["dispensing"][0] = {**side["dispensing"][0], "quantity": 10, "unit": "tablet"}
            elif scenario == "drug_control_allowed_substitution":
                first_item = side["dispensing"][0]
                side["dispensing"][0] = {**first_item, "item": ALLOWED_SUBSTITUTES[first_item["item"]], "unit": "box"}
            if scenario != "drug_control_late_dispensing":
                _maybe_sync_pending(world, row)
            _blank_procedure(world, [row])
            world.add(scenario, row)

    # Shuffle so position carries no label information.
    order = list(range(len(world.records)))
    rng.shuffle(order)
    records = [world.records[index] for index in order]
    canonical = canonicalize_feature_dataset(FeatureDataset(records=records, facilities=(), source_metadata={}))
    truth = {
        "labels": dict(world.labels),
        "role": {case: SCENARIOS[scenario]["role"] for case, scenario in world.labels.items()},
        "mode": {case: SCENARIOS[scenario]["mode"] for case, scenario in world.labels.items()},
    }
    return list(canonical.records), world.sidecar, truth


# --- Methods. Detectors receive canonical records only; baselines may read the sidecar. ---
#
# Coverage states per method (disjoint, together every record of the dataset):
# * assessed       - the method evaluated the record (flagged or not);
# * unassessed     - the method applies but a required field or value is missing/invalid,
#                    the evidence inventory is not synchronised, or a bounded search did not
#                    reach the record (the detector's ineligible/unassessed outputs);
# * not_applicable - the method has no rule for the record (evidence check without a rule
#                    for the service type; naive phantom/drug baselines outside their service).
# Candidate units differ by method and are reported separately from flagged records.

def _case_ids(result: Mapping[str, Any], *keys: str) -> set[str]:
    out: set[str] = set()
    for key in keys:
        for item in result.get(key, []) or []:
            out.add(item["case_id"] if isinstance(item, Mapping) else item)
    return out


def run_detectors(records: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Flagged, unassessed and not-applicable case sets per existing detector; no labels here."""
    out: dict[str, dict[str, Any]] = {}
    for name, profile in (("repeat_service_v1", REPEAT_SERVICE_PROFILE),
                          ("repeat_eleven_field", "repeat-visit-exact-no-amount-v1")):
        result = detect_repeat_billing_candidates(records, SIGNATURE_PROFILES[profile])
        groups = [frozenset(group["case_ids"]) for group in result["candidate_groups"]]
        out[name] = {"flagged": set().union(*groups) if groups else set(), "unit": "group", "units": groups,
                     "unassessed": _case_ids(result, "ineligible_cases"), "not_applicable": set()}
    similar = detect_similar_claim_patterns(records)
    groups = [frozenset(group["case_ids"]) for group in similar["candidate_groups"]]
    # Ineligible here means a missing base attribute (no amount in this FKRTL-shaped data);
    # the FKRTL runtime provider declares this check not applicable instead.
    out["similar_claim_pattern"] = {"flagged": set().union(*groups) if groups else set(), "unit": "group",
                                    "units": groups, "unassessed": _case_ids(similar, "ineligible_cases"),
                                    "not_applicable": set()}
    near = detect_near_duplicate_claims(records, NearDuplicateConfig())
    pairs = [frozenset(candidate["case_ids"]) for candidate in near["candidates"]]
    out["near_duplicate"] = {
        "flagged": set().union(*pairs) if pairs else set(), "unit": "pair", "units": pairs,
        "unassessed": set(near["unassessed_case_ids"]) | _case_ids(near, "ineligible_cases"),
        "not_applicable": set(), "search_truncated": near["search_truncated"],
    }
    for name, rules in (("evidence_default_rules", None), ("evidence_scenario_rules", SCENARIO_EVIDENCE_RULES)):
        result = detect_evidence_completeness(records, rules)
        flagged = {item["case_id"] for item in result["candidates"]}
        out[name] = {
            "flagged": flagged, "unit": "record", "units": [frozenset({case}) for case in flagged],
            "unassessed": _case_ids(result, "unassessed_cases", "ineligible_cases"),
            "not_applicable": _case_ids(result, "not_applicable_cases"),
            "state_counts": {
                "evidence_absent_flagged": len(result["candidates"]),
                "inventory_not_synchronised_unassessed": len(result["unassessed_cases"]),
                "invalid_inventory_unassessed": len(result["ineligible_cases"]),
                "no_rule_not_applicable": len(result["not_applicable_cases"]),
            },
        }
    summary, ranks = build_ml_anomaly_ranking(records)
    out["ml_ranking_top_k"] = {"ranks": ranks, "unit": "record (top K by competition rank, ties included)",
                               "unassessed": {row["case_id"] for row in records} - set(ranks),
                               "not_applicable": set(), "status": summary["status"]}
    return out


def run_baselines(records: Sequence[Mapping[str, Any]], sidecar: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Simple rules, one per mode. The cloning, phantom and drug baselines read synthetic-only data."""
    by_day: dict[tuple, list[str]] = defaultdict(list)
    template: dict[tuple, list[tuple[str, str]]] = defaultdict(list)
    for row in records:
        by_day[(row["participant_token"], row["service_date"])].append(row["case_id"])
        template[(row["facility_id"], row["service_date"], row["primary_diagnosis"], row["claim_group"])].append(
            (row["case_id"], row["participant_token"]))
    same_day = [frozenset(group) for group in by_day.values() if len(group) > 1]
    clone = [frozenset(case for case, _p in members) for members in template.values()
             if len({p for _c, p in members}) > 1]

    phantom_flagged, phantom_scope, drug_flagged, drug_scope = set(), set(), set(), set()
    for row in records:
        case, service = row["case_id"], row["service_type"]
        if service in EXECUTION_EVIDENCE:
            phantom_scope.add(case)
            present = row["supporting_evidence_types"] or []
            if (row["supporting_evidence_recording_status"] != "recorded" or EXECUTION_EVIDENCE[service] not in present
                    or sidecar[case]["execution_log_matches_service_day"] is not True):
                phantom_flagged.add(case)
        elif service == DRUG_SERVICE:
            drug_scope.add(case)
            side = sidecar[case]
            exact = {(d["item"], d["quantity"], d["unit"]) for d in side["dispensing"] if d["on_time"]}
            if any((item["item"], item["quantity"], item["unit"]) not in exact for item in side["items"]):
                drug_flagged.add(case)
    all_ids = {row["case_id"] for row in records}

    def groups(units: list[frozenset]) -> dict[str, Any]:
        return {"flagged": set().union(*units) if units else set(), "unit": "group", "units": units,
                "unassessed": set(), "not_applicable": set()}

    def per_record(flagged: set[str], scope: set[str]) -> dict[str, Any]:
        return {"flagged": flagged, "unit": "record", "units": [frozenset({case}) for case in flagged],
                "unassessed": set(), "not_applicable": all_ids - scope}

    return {
        "naive_same_participant_same_day": groups(same_day),
        "naive_same_synthetic_facility_template": groups(clone),
        "naive_execution_record_linkage": per_record(phantom_flagged, phantom_scope),
        "naive_item_exact_dispensing": per_record(drug_flagged, drug_scope),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


COUNT_KEYS = (
    "dataset_records", "cohort_records", "excluded_other_mode_records",
    "positives", "assessed_positives", "unassessed_positives", "not_applicable_positives",
    "negatives", "assessed_negatives", "unassessed_negatives", "not_applicable_negatives",
    "tp", "fp", "fn", "tn",
    "flagged_records_in_dataset", "flagged_records_in_cohort",
    "candidate_units_in_dataset", "candidate_units_within_cohort",
)
METRIC_DENOMINATORS = {
    "precision": "tp / (tp + fp)",
    "recall_on_assessed": "tp / (tp + fn) = tp / assessed_positives",
    "recall_on_all_positives": "tp / positives (unassessed and not-applicable positives count as missed)",
    "false_positive_rate": "fp / (fp + tn) = fp / assessed_negatives",
    "flagged_per_1000_cohort_records": "1000 * flagged_records_in_cohort / cohort_records",
    "flagged_per_1000_assessed_records": "1000 * flagged_records_in_cohort / (assessed_positives + assessed_negatives)",
    "cohort_prevalence": "positives / cohort_records (all labelled positives of the mode)",
    "assessed_prevalence": "assessed_positives / assessed records = expected precision of random flagging among assessed records",
}


def metrics(counts: Mapping[str, int]) -> dict[str, float | None]:
    """Every metric from reconciled counts only, so per-seed and pooled values use the same formulas."""
    assessed = counts["assessed_positives"] + counts["assessed_negatives"]
    return {
        "precision": _rate(counts["tp"], counts["tp"] + counts["fp"]),
        "recall_on_assessed": _rate(counts["tp"], counts["tp"] + counts["fn"]),
        "recall_on_all_positives": _rate(counts["tp"], counts["positives"]),
        "false_positive_rate": _rate(counts["fp"], counts["fp"] + counts["tn"]),
        "flagged_per_1000_cohort_records": round(1000 * counts["flagged_records_in_cohort"] / counts["cohort_records"], 2)
        if counts["cohort_records"] else None,
        "flagged_per_1000_assessed_records": round(1000 * counts["flagged_records_in_cohort"] / assessed, 2)
        if assessed else None,
        "cohort_prevalence": _rate(counts["positives"], counts["cohort_records"]),
        "assessed_prevalence": _rate(counts["assessed_positives"], assessed),
    }


class CountReconciliationError(ValueError):
    """A partition or confusion count does not add up."""


def reconcile(counts: Mapping[str, int]) -> None:
    """Raise unless every count partition adds up exactly."""
    checks = {
        "tp + fn = assessed_positives": counts["tp"] + counts["fn"] == counts["assessed_positives"],
        "fp + tn = assessed_negatives": counts["fp"] + counts["tn"] == counts["assessed_negatives"],
        "positives = assessed + unassessed + not_applicable": counts["positives"] == (
            counts["assessed_positives"] + counts["unassessed_positives"] + counts["not_applicable_positives"]),
        "negatives = assessed + unassessed + not_applicable": counts["negatives"] == (
            counts["assessed_negatives"] + counts["unassessed_negatives"] + counts["not_applicable_negatives"]),
        "positives + negatives = cohort_records": counts["positives"] + counts["negatives"] == counts["cohort_records"],
        "cohort + excluded = dataset_records": (
            counts["cohort_records"] + counts["excluded_other_mode_records"] == counts["dataset_records"]),
        "tp + fp = flagged_records_in_cohort": counts["tp"] + counts["fp"] == counts["flagged_records_in_cohort"],
        "flagged in cohort <= flagged in dataset": counts["flagged_records_in_cohort"] <= counts["flagged_records_in_dataset"],
        "units within cohort <= units in dataset": counts["candidate_units_within_cohort"] <= counts["candidate_units_in_dataset"],
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise CountReconciliationError(f"Count reconciliation failed: {', '.join(failed)}")


def confusion(flagged: set[str], states: Mapping[str, set[str]], positives: set[str], negatives: set[str],
              dataset: set[str], units: Sequence[frozenset] = ()) -> dict[str, int]:
    """Record-level counts for one cohort. ``states`` maps assessed/unassessed/not_applicable to disjoint sets."""
    assessed, unassessed, not_applicable = states["assessed"], states["unassessed"], states["not_applicable"]
    if (assessed & unassessed) or (assessed & not_applicable) or (unassessed & not_applicable) or (
            assessed | unassessed | not_applicable) != dataset:
        raise CountReconciliationError("Coverage states must be disjoint and cover every dataset record.")
    if flagged - assessed:
        raise CountReconciliationError("A method flagged a record it did not assess.")
    cohort = positives | negatives
    if positives & negatives or not cohort <= dataset:
        raise CountReconciliationError("Positives and negatives must be disjoint dataset records.")
    counts = {
        "dataset_records": len(dataset), "cohort_records": len(cohort), "excluded_other_mode_records": len(dataset - cohort),
        "tp": len(flagged & positives), "fp": len(flagged & negatives),
        "fn": len((positives & assessed) - flagged), "tn": len((negatives & assessed) - flagged),
        "flagged_records_in_dataset": len(flagged), "flagged_records_in_cohort": len(flagged & cohort),
        "candidate_units_in_dataset": len(units), "candidate_units_within_cohort": sum(1 for unit in units if unit <= cohort),
    }
    for label, cases in (("positives", positives), ("negatives", negatives)):
        counts[label] = len(cases)
        counts[f"assessed_{label}"] = len(cases & assessed)
        counts[f"unassessed_{label}"] = len(cases & unassessed)
        counts[f"not_applicable_{label}"] = len(cases & not_applicable)
    counts = {key: counts[key] for key in COUNT_KEYS}
    reconcile(counts)
    return counts


def _by_scenario(flagged: set[str], states: Mapping[str, set[str]], cases: set[str], labels: Mapping[str, str]) -> dict[str, Any]:
    """Per scenario: records, flag rate on assessed records, and unassessed / not-applicable counts."""
    out = {}
    for scenario in sorted({labels[case] for case in cases}):
        members = {case for case in cases if labels[case] == scenario}
        assessed = members & states["assessed"]
        out[scenario] = {"records": len(members), "assessed": len(assessed), "flagged": len(flagged & assessed),
                         "unassessed": len(members & states["unassessed"]),
                         "not_applicable": len(members & states["not_applicable"]),
                         "rate_on_assessed": _rate(len(flagged & assessed), len(assessed))}
    return out


def evaluate_mode_benchmark(records: Sequence[Mapping[str, Any]], sidecar: Mapping[str, Mapping[str, Any]],
                            truth: Mapping[str, Any]) -> dict[str, Any]:
    if any(set(row) - set(CANONICAL_FEATURE_FIELDS) for row in records):
        raise ValueError("Records must hold canonical feature fields only.")
    detectors = run_detectors(records)  # before any label is read
    baselines = run_baselines(records, sidecar)
    labels, roles, modes = truth["labels"], truth["role"], truth["mode"]
    dataset = {row["case_id"] for row in records}
    if set(labels) != dataset:
        raise CountReconciliationError("Every dataset record needs exactly one label.")
    background = {case for case, mode in modes.items() if mode == "background"}
    by_case = {row["case_id"]: row for row in records}

    def share(cases: set[str], field: str, value: Any) -> float | None:
        return _rate(sum(1 for case in cases if by_case[case][field] == value), len(cases))
    report: dict[str, Any] = {"record_count": len(records), "scenario_counts": dict(sorted(Counter(labels.values()).items())),
                              "modes": {}}
    for mode in MODES:
        mode_cases = {case for case, value in modes.items() if value == mode}
        positives = {case for case in mode_cases if roles[case] == "positive"}
        negatives = (mode_cases - positives) | background
        other_modes = dataset - mode_cases - background
        methods: dict[str, Any] = {}
        for name in (*DETECTORS, BASELINE_FOR_MODE[mode]):
            method = detectors.get(name) or baselines[name]
            states = {"unassessed": method["unassessed"], "not_applicable": method["not_applicable"]}
            states["assessed"] = dataset - states["unassessed"] - states["not_applicable"]
            if name == "ml_ranking_top_k":
                k = len(positives)
                flagged = {case for case, item in method["ranks"].items() if item["rank"] <= k}
                units = [frozenset({case}) for case in flagged]
            else:
                flagged, units = method["flagged"], method["units"]
            counts = confusion(flagged, states, positives, negatives, dataset, units)
            entry: dict[str, Any] = {
                "counts": counts, "metrics": metrics(counts), "candidate_unit": method["unit"],
                "positives_by_scenario": _by_scenario(flagged, states, positives, labels),
                "controls_by_scenario": _by_scenario(flagged, states, mode_cases - positives, labels),
                "flagged_other_mode_records": len(flagged & other_modes),
            }
            if name == "ml_ranking_top_k":
                entry["k"] = k
            if "search_truncated" in method:
                entry["search_truncated"] = method["search_truncated"]
            methods[name] = entry
        report["modes"][mode] = {
            "cohort": "mode positives + mode controls + background; other modes' records excluded",
            "balance": {
                "procedure_blank_rate_positives": share(positives, "procedure_code", None),
                "procedure_blank_rate_negatives": share(negatives, "procedure_code", None),
                "evidence_unsynchronised_rate_positives": share(positives, "supporting_evidence_recording_status", "not_recorded"),
                "evidence_unsynchronised_rate_mode_controls": share(mode_cases - positives, "supporting_evidence_recording_status", "not_recorded"),
            },
            "methods": methods,
        }
    report["evidence_states"] = {name: detectors[name]["state_counts"] for name in ("evidence_default_rules", "evidence_scenario_rules")}
    report["ml_status"] = detectors["ml_ranking_top_k"]["status"]
    return report


def _sum_scenarios(entries: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    out = {}
    for scenario in entries[0][key]:
        totals = {field: sum(entry[key][scenario][field] for entry in entries)
                  for field in ("records", "assessed", "flagged", "unassessed", "not_applicable")}
        out[scenario] = {**totals, "rate_on_assessed": _rate(totals["flagged"], totals["assessed"]),
                         "per_seed_rate_on_assessed": _stats([entry[key][scenario]["rate_on_assessed"] for entry in entries])}
    return out


def run_mode_seeds(seeds: Sequence[int] = DEFAULT_SEEDS, background: int = 1500, planted: int = 12) -> dict[str, Any]:
    per_seed = {seed: evaluate_mode_benchmark(*generate_mode_benchmark(seed, background, planted)) for seed in seeds}
    reports = list(per_seed.values())
    aggregate: dict[str, Any] = {"seeds": list(seeds)}
    for mode in MODES:
        aggregate[mode] = {"methods": {}}
        for name in reports[0]["modes"][mode]["methods"]:
            entries = [report["modes"][mode]["methods"][name] for report in reports]
            pooled = {key: sum(entry["counts"][key] for entry in entries) for key in COUNT_KEYS}
            reconcile(pooled)
            aggregate[mode]["methods"][name] = {
                "candidate_unit": entries[0]["candidate_unit"],
                "pooled_counts": pooled,
                "pooled_metrics": metrics(pooled),
                "per_seed_metrics": {metric: _stats([entry["metrics"][metric] for entry in entries])
                                     for metric in entries[0]["metrics"]},
                "positives_by_scenario": _sum_scenarios(entries, "positives_by_scenario"),
                "controls_by_scenario": _sum_scenarios(entries, "controls_by_scenario"),
                "flagged_other_mode_records": sum(entry["flagged_other_mode_records"] for entry in entries),
                **({"truncated_runs": sum(entry["search_truncated"] for entry in entries)}
                   if "search_truncated" in entries[0] else {}),
            }
        aggregate[mode]["balance"] = {
            key: _stats([report["modes"][mode]["balance"][key] for report in reports])
            for key in reports[0]["modes"][mode]["balance"]}
    return {
        "benchmark_version": MODE_BENCHMARK_VERSION,
        "label": LABEL,
        "aggregate_basis": AGGREGATE_BASIS,
        "synthetic_only_fields": list(SYNTHETIC_ONLY_FIELDS),
        "synthetic_only_sidecar": ["item lines", "dispensing lines", "execution-log day match"],
        "parameters": {"background": background, "planted_per_scenario": planted, "window_days": WINDOW_DAYS,
                       "sync_pending_rate": SYNC_PENDING_RATE},
        "unit_of_evaluation": "record (claim); candidate units (group, pair, record) are counted separately",
        "coverage_states": {
            "assessed": "the method evaluated the record",
            "unassessed": "the method applies but required data is missing/invalid, evidence is not synchronised, or a bounded search did not reach the record",
            "not_applicable": "the method has no rule for the record",
        },
        "metric_denominators": METRIC_DENOMINATORS,
        "aggregate": aggregate,
        "per_seed": per_seed,
        "limitations": [
            "Scenario labels define this simulation's contracts only; they are not fraud labels.",
            "Facility identity, service type, evidence inventory, item and dispensing lines are synthetic-only; the FKRTL sample does not contain them.",
            "Detectors run with their current settings; nothing was tuned on these seeds.",
            "Repeat definitions are compared under one assumed scenario mix; their relative precision depends on how often legitimate same-key referrals occur, which the real data cannot tell.",
            "Results do not transfer to real FKRTL data, which has no ground truth.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", default="1-10", help="e.g. 1-10 or 3,5,8")
    parser.add_argument("--aggregate-only", action="store_true")
    parser.add_argument("--save", action="store_true", help="also write outputs/benchmarks/four_mode_benchmark.json (ignored by Git)")
    args = parser.parse_args()
    report = run_mode_seeds(_parse_seeds(args.seeds))
    if args.aggregate_only:
        report.pop("per_seed")
    text = json.dumps(report, indent=2)
    if args.save:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "four_mode_benchmark.json").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
