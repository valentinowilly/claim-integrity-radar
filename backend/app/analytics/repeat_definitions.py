"""Single explicit definition of same-participant repeat-pattern grouping.

One function (:func:`group_repeat_patterns`) decides which records share a
repeat key. The repeat-billing detector and the aggregate FKRTL summaries both
use it, so every reported count states which definition produced it.

Definitions (all keys include the participant: these are *same-participant*
repeat patterns, never cross-participant similarity):

* ``repeat_service_v1`` - participant + admission date + primary diagnosis +
  INA-CBG + procedure. Records with any missing key field are ineligible
  (unknown is not a matching value). Optional same-amount subset on the
  unverified provider-billed amount (FKL47); missing amounts are excluded.
* ``legacy_script_repeat_service`` - the same key as the exploratory script
  ``run_fkrtl_real_detection.py`` (archived outside the repo): missing values are matched as a literal
  value and a missing/invalid FKL47 counts as 0. Kept only to reconcile the
  earlier 81-group / 20-group report; it is not used by the application.
* ``repeat-service-v2`` (uploaded BPJS-format files) - the ``repeat_service_v1`` key, but a blank procedure
  means "no procedure": two claims that both carry none still match on the other key fields.
* ``repeat-service-v1`` (FKRTL), ``repeat-billing-exact-v1`` (synthetic) and
  the former ``repeat-visit-exact-no-amount-v1`` - the detector profiles (see
  ``repeat_billing.py``). ``repeat-service-v1`` uses the ``repeat_service_v1``
  key and reports the other attributes as context only.

A repeat pattern is a review signal. It does not show that a service was
billed or paid twice.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.analytics.normalization import normalize_amount, normalize_date, normalize_text
from app.analytics.records import validate_case_records

MISSING = "<MISSING>"
NONE_RECORDED = "<NONE>"
DATE_FIELDS = frozenset({"service_date", "discharge_date"})
AMOUNT_FIELDS = frozenset({"billed_amount", "provider_billed_amount_unverified"})


@dataclass(frozen=True)
class RepeatDefinition:
    name: str
    key_fields: tuple[str, ...]
    # "ineligible": a record with a missing key field is not assessed.
    # "match_as_value": missing is treated as a literal value (legacy script only).
    missing_policy: str = "ineligible"
    # When set, a same-amount subset is reported in addition to the key groups.
    amount_field: str | None = None
    # "exclude": records without a valid amount are left out of the subset.
    # "zero": missing/invalid amounts count as 0 (legacy script only).
    amount_missing_policy: str = "exclude"
    # Key fields whose blank value is itself a value ("none recorded"), matched like any other value.
    none_value_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if "participant_token" not in self.key_fields:
            raise ValueError("A repeat definition must compare the same participant.")
        if self.missing_policy not in {"ineligible", "match_as_value"}:
            raise ValueError("Unknown missing-value policy.")
        if self.amount_missing_policy not in {"exclude", "zero"}:
            raise ValueError("Unknown amount missing-value policy.")
        if self.amount_field is not None and self.amount_field in self.key_fields:
            raise ValueError("The subset amount must not also be a key field.")


REPEAT_SERVICE_KEY = ("participant_token", "service_date", "primary_diagnosis", "claim_group", "procedure_code")
REPEAT_SERVICE_V1 = RepeatDefinition(
    "repeat_service_v1", REPEAT_SERVICE_KEY, amount_field="provider_billed_amount_unverified",
)
LEGACY_SCRIPT_REPEAT_SERVICE = RepeatDefinition(
    "legacy_script_repeat_service", REPEAT_SERVICE_KEY, missing_policy="match_as_value",
    amount_field="provider_billed_amount_unverified", amount_missing_policy="zero",
)


def normalize_value(field: str, value: Any) -> Any:
    if field in DATE_FIELDS:
        return normalize_date(value)
    if field in AMOUNT_FIELDS:
        return normalize_amount(value)
    return normalize_text(value)


@dataclass(frozen=True)
class RepeatGrouping:
    groups: list[list[str]]                   # case IDs per key with >= 2 records, sorted
    ineligible: list[tuple[str, list[str]]]   # (case_id, missing key fields), sorted by case_id
    input_rows: int


def missing_key_fields(record: Mapping[str, Any], definition: RepeatDefinition) -> list[str]:
    """Key fields a record lacks; with the ``ineligible`` policy any of them leaves it unassessed."""
    return [field for field in definition.key_fields if normalize_value(field, record.get(field)) is None]


def group_repeat_patterns(records: Sequence[Mapping[str, Any]], definition: RepeatDefinition) -> RepeatGrouping:
    """Group records sharing the definition's key; order of input rows does not matter."""
    validated = validate_case_records(records)
    keyed: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    ineligible: list[tuple[str, list[str]]] = []
    for case_id, record in validated:
        values = tuple(NONE_RECORDED if value is None and field in definition.none_value_fields else value
                       for field, value in ((field, normalize_value(field, record.get(field))) for field in definition.key_fields))
        missing = [field for field, value in zip(definition.key_fields, values) if value is None]
        if missing and definition.missing_policy == "ineligible":
            ineligible.append((case_id, missing))
            continue
        keyed[tuple(MISSING if value is None else value for value in values)].append(case_id)
    groups = sorted(sorted(case_ids) for case_ids in keyed.values() if len(case_ids) >= 2)
    return RepeatGrouping(groups=groups, ineligible=sorted(ineligible), input_rows=len(validated))


def summarize_repeat_patterns(records: Sequence[Mapping[str, Any]], definition: RepeatDefinition) -> dict[str, Any]:
    """Aggregate-only counts for one definition; no identifiers or key values are returned.

    Units: a *group* is a set of >= 2 records sharing the key; *rows_in_groups* counts
    its members; *extra_rows* = rows_in_groups - groups (records beyond the first).
    """
    grouping = group_repeat_patterns(records, definition)
    rows_in_groups = sum(len(group) for group in grouping.groups)
    summary: dict[str, Any] = {
        "definition": definition.name,
        "key_fields": list(definition.key_fields),
        "missing_policy": definition.missing_policy,
        "input_rows": grouping.input_rows,
        "eligible_rows": grouping.input_rows - len(grouping.ineligible),
        "ineligible_rows": len(grouping.ineligible),
        "ineligible_rows_by_missing_field": dict(sorted(Counter(
            field for _case_id, fields in grouping.ineligible for field in fields
        ).items())),
        "groups": len(grouping.groups),
        "rows_in_groups": rows_in_groups,
        "extra_rows": rows_in_groups - len(grouping.groups),
        "group_size_distribution": dict(sorted(Counter(len(group) for group in grouping.groups).items())),
    }
    if definition.amount_field is None:
        return summary
    amounts_by_case = {
        case_id: normalize_value(definition.amount_field, record.get(definition.amount_field))
        for case_id, record in validate_case_records(records)
    }
    if definition.amount_missing_policy == "zero":
        amounts_by_case = {case_id: Decimal(0) if amount is None else amount for case_id, amount in amounts_by_case.items()}
    subset_groups = subset_rows = differing = without_amount = 0
    for group in grouping.groups:
        amounts = [amounts_by_case[case_id] for case_id in group]
        valid = [amount for amount in amounts if amount is not None]
        without_amount += len(amounts) - len(valid)
        if len(set(valid)) > 1:
            differing += 1
        for count in Counter(valid).values():
            if count >= 2:
                subset_groups += 1
                subset_rows += count
    summary["same_amount_subset"] = {
        "amount_field": definition.amount_field,
        "amount_missing_policy": definition.amount_missing_policy,
        "groups": subset_groups,
        "rows_in_groups": subset_rows,
        "extra_rows": subset_rows - subset_groups,
        "key_groups_with_differing_amounts": differing,
        "rows_in_key_groups_without_valid_amount": without_amount,
        "note": "Subset of the key groups; equal amounts do not show a claim was paid twice.",
    }
    return summary
