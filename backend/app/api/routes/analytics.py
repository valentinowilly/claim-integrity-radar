"""Versioned dashboard, analysis, case, and evaluation API routes."""

from datetime import date, datetime, timezone
from math import ceil

from fastapi import APIRouter, Request

from app.api.errors import ApiError
from app.schemas.analytics import (
    AnalysisResponse,
    CaseDetailResponse,
    CasesResponse,
    DashboardSummaryResponse,
    EvaluationResponse,
)
from app.services.analytics import (
    DATA_SOURCE,
    INDICATOR_DEFINITIONS,
    PLANNED_INDICATORS,
    build_analytics_snapshot,
)
from app.services.reviews import (
    INITIAL_STATUS,
    ReviewStorageError,
    ReviewStore,
    STATUS_LABELS,
)


router = APIRouter(prefix="/api/v1")
INDICATOR_CODES = {item["code"] for item in INDICATOR_DEFINITIONS}
RISK_LEVELS = {"high", "medium", "low"}
CASE_STATUSES = {"pending", "in_review", "resolved"}
REVIEW_STATUSES = set(STATUS_LABELS)
SORT_FIELDS = {"risk_score", "detected_at"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(value: str | None, parameter: str) -> date | None:
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ApiError(
            400, "INVALID_FILTER", f"Parameter {parameter} harus berupa tanggal YYYY-MM-DD.",
            {"parameter": parameter},
        ) from exc
    if parsed.isoformat() != value:
        raise ApiError(
            400, "INVALID_FILTER", f"Parameter {parameter} harus berupa tanggal YYYY-MM-DD.",
            {"parameter": parameter},
        )
    return parsed


def _period(period_from: str | None, period_to: str | None) -> tuple[date | None, date | None]:
    start = _parse_date(period_from, "period_from")
    end = _parse_date(period_to, "period_to")
    if start is not None and end is not None and start > end:
        raise ApiError(400, "INVALID_FILTER", "period_from tidak boleh setelah period_to.", {})
    return start, end


def _integer(value: str, parameter: str, minimum: int, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ApiError(400, "INVALID_FILTER", f"Parameter {parameter} harus berupa bilangan bulat.",
                       {"parameter": parameter}) from exc
    if str(parsed) != value or parsed < minimum or (maximum is not None and parsed > maximum):
        raise ApiError(400, "INVALID_FILTER", f"Nilai parameter {parameter} di luar rentang.",
                       {"parameter": parameter})
    return parsed


@router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(period_from: str | None = None, period_to: str | None = None):
    start, end = _period(period_from, period_to)
    snapshot = build_analytics_snapshot(period_from=start, period_to=end)
    counts = [
        {
            "indicator": indicator["code"],
            "candidate_groups": indicator["candidate_group_count"],
            "candidate_records": indicator["candidate_count"],
            "status": indicator["status"],
        }
        for indicator in snapshot["indicators"]
    ]
    return {
        "availability": snapshot["availability"],
        "data_source": snapshot["data_source"],
        "generated_at": _now(),
        "period": {"from": period_from, "to": period_to},
        "summary": {
            "claims_reviewed": snapshot["records_considered"],
            "cases_in_queue": len(snapshot["cases"]),
            "risk_level_counts": {"high": None, "medium": None, "low": None},
            "indicator_counts": counts,
        },
        "notice": (
            "Seluruh angka dihitung dari data sintetis untuk demo; bukan hasil analisis "
            "dataset BPJS. Level risiko belum ditetapkan."
        ),
    }


@router.get("/analysis", response_model=AnalysisResponse)
def analysis(period_from: str | None = None, period_to: str | None = None,
             indicator: str | None = None):
    start, end = _period(period_from, period_to)
    if indicator is not None and indicator not in INDICATOR_CODES:
        raise ApiError(400, "INVALID_FILTER", "Kode indikator tidak dikenal.", {"parameter": "indicator"})
    snapshot = build_analytics_snapshot(period_from=start, period_to=end)
    active = snapshot["indicators"]
    if indicator is not None:
        active = [entry for entry in active if entry["code"] == indicator]
    return {
        "availability": snapshot["availability"],
        "data_source": snapshot["data_source"],
        "generated_at": _now(),
        "filters": {"period_from": period_from, "period_to": period_to, "indicator": indicator},
        "coverage": {
            "records_considered": snapshot["records_considered"],
            "records_eligible": snapshot["records_eligible"],
        },
        "indicators": active,
        "planned_indicators": PLANNED_INDICATORS,
        "indicator_coverage": snapshot["indicator_coverage"],
        "risk_scoring": snapshot["risk_scoring"],
        "audit_priority": snapshot["audit_priority"],
        "limitations": [
            "Hasil hanya berasal dari fixture sintetis deterministik dan tidak mewakili klaim BPJS.",
            "Kandidat membutuhkan tinjauan auditor; tidak ada skor atau level risiko tervalidasi.",
        ],
    }


@router.get("/cases", response_model=CasesResponse)
def list_cases(request: Request, page: str = "1", page_size: str = "25", risk_level: str | None = None,
               indicator: str | None = None, status: str | None = None,
               review_status: str | None = None,
               sort_by: str = "risk_score", sort_order: str = "desc"):
    page_number = _integer(page, "page", 1)
    size = _integer(page_size, "page_size", 1, 100)
    if risk_level is not None and risk_level not in RISK_LEVELS:
        raise ApiError(400, "INVALID_FILTER", "Parameter risk_level tidak dikenal.", {"parameter": "risk_level"})
    if indicator is not None and indicator not in INDICATOR_CODES:
        raise ApiError(400, "INVALID_FILTER", "Kode indikator tidak dikenal.", {"parameter": "indicator"})
    if status is not None and status not in CASE_STATUSES:
        raise ApiError(400, "INVALID_FILTER", "Parameter status tidak dikenal.", {"parameter": "status"})
    if review_status is not None and review_status not in REVIEW_STATUSES:
        raise ApiError(400, "INVALID_FILTER", "Parameter review_status tidak dikenal.", {"parameter": "review_status"})
    if sort_by not in SORT_FIELDS:
        raise ApiError(400, "INVALID_FILTER", "Parameter sort_by tidak dikenal.", {"parameter": "sort_by"})
    if sort_order not in {"asc", "desc"}:
        raise ApiError(400, "INVALID_FILTER", "Parameter sort_order tidak dikenal.", {"parameter": "sort_order"})

    snapshot = build_analytics_snapshot()
    items = list(snapshot["cases"].values())
    try:
        statuses = ReviewStore(request.app.state.review_db_path).get_statuses(
            [item["case_id"] for item in items]
        )
    except ReviewStorageError as exc:
        raise ApiError(503, "REVIEW_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    for item in items:
        item["review_status"] = statuses.get(item["case_id"], INITIAL_STATUS)
    if risk_level is not None:
        items = [item for item in items if item["risk_level"] == risk_level]
    if indicator is not None:
        items = [item for item in items if indicator in item["indicators"]]
    if status is not None:
        items = [item for item in items if item["status"] == status]
    if review_status is not None:
        items = [item for item in items if item["review_status"] == review_status]

    # Scores are the existing provisional rule index. Null scores stay at the
    # end; stable case IDs break ties. Risk levels remain undefined.
    if sort_by == "risk_score":
        items.sort(
            key=lambda item: (
                item["risk_score"] is None,
                -(item["risk_score"] or 0) if sort_order == "desc" else (item["risk_score"] or 0),
                item["case_id"],
            )
        )
    else:
        direction = 1 if sort_order == "asc" else -1
        items.sort(key=lambda item: (
            item["detected_at"] is None,
            item["detected_at"].timestamp() * direction if item["detected_at"] is not None else 0,
            item["case_id"],
        ))
    total = len(items)
    total_pages = ceil(total / size) if total else 0
    offset = (page_number - 1) * size
    return {
        "availability": "available",
        "data_source": DATA_SOURCE,
        "items": items[offset:offset + size],
        "pagination": {
            "page": page_number, "page_size": size, "total_items": total,
            "total_pages": total_pages,
        },
        "applied_filters": {
            "risk_level": risk_level, "indicator": indicator, "status": status,
            "review_status": review_status,
            "sort_by": sort_by, "sort_order": sort_order,
        },
        "notice": (
            "Antrean berisi kandidat tinjauan dari data sintetis. Skor adalah indeks aturan "
            "provisional, bukan probabilitas fraud atau level risiko tervalidasi."
        ),
    }


@router.get("/cases/{case_id}", response_model=CaseDetailResponse)
def case_detail(case_id: str):
    snapshot = build_analytics_snapshot()
    case = snapshot["cases"].get(case_id)
    if case is None:
        raise ApiError(404, "CASE_NOT_FOUND", "Kasus tidak ditemukan.", {})
    return {
        "availability": snapshot["availability"],
        "data_source": snapshot["data_source"],
        "case": case,
        "notice": "Detail memuat alasan kandidat dari data sintetis; bukan keputusan fraud.",
    }


@router.get("/evaluation", response_model=EvaluationResponse)
def evaluation(period_from: str | None = None, period_to: str | None = None,
               evaluation_version: str | None = None):
    _period(period_from, period_to)
    return {
        "availability": "insufficient_data",
        "data_source": DATA_SOURCE,
        "generated_at": _now(),
        "evaluation": None,
        "requirements_missing": [
            "Label acuan yang tervalidasi belum tersedia.",
            "Protokol evaluasi dan versi evaluasi belum ditetapkan.",
        ],
        "notice": "Metrik evaluasi belum dihitung; fixture sintetis bukan ground truth.",
    }
