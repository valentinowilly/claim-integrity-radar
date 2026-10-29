import { memo, useEffect, useMemo, useRef, useState } from "react";
import { Clock3, MousePointerClick, Search, SlidersHorizontal, X } from "lucide-react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { EmptyState } from "../components/DataStates";
import { LANES, LaneDot, formatCount, indicatorLabel, mlFeatureLabel, mlLevel, shortRef } from "../components/Display";
import { RunSelector, RunStateMessage, SourcePill } from "../components/PersistedRunWorkspace";
import { usePersistedRunSnapshot } from "../hooks/usePersistedRunSnapshot";
import { useAuth } from "../auth/AuthContext";
import { CaseReviewPanel } from "./RunCaseReviewPage";
import { ageText, ageTone, analysisAgeDays } from "../components/TodayBrief";
import { ReviewShortcuts } from "../components/ReviewShortcuts";
import {
  auditResultLabels, getRunAssignments, type CaseAssignment, getRunCases, getRunReviews, reviewOutcomeLabels, ruleFlaggedListedIds, runReviewStatusLabels,
  type Lane, type MlAnomaly, type RunCaseListResponse, type RunCaseQuery, type RunCaseSort, type RunReviewStatus, type RunReviewSummaryItem,
} from "../api/client";

type SortKey = Exclude<RunCaseSort, "stored">;
const SORTS: Record<SortKey, string> = {
  ml_rank: "Skor AI tertinggi",
  rule_index: "Skor temuan tertinggi",
  checks: "Paling banyak pemeriksaan",
  similarity_rarity: "Paling mirip dengan klaim lain",
  review_updated: "Terakhir ditinjau",
  case_ref: "Nomor referensi",
};
type ReviewFilter = "" | "not_started" | RunReviewStatus | "has_outcome";
const REVIEW_FILTERS: Array<[ReviewFilter, string]> = [
  ["", "Semua status"], ["not_started", "Belum ditinjau"], ["in_review", "Sedang ditinjau"],
  ["awaiting_evidence", "Minta klarifikasi"], ["escalated", "Masuk antrean audit"], ["closed", "Selesai"],
  ["has_outcome", "Sudah diputuskan"],
];
type LaneTab = Lane | "all" | "ai";
// Short tab names (the dot carries the colour; the full name is in the tooltip and the accessible name).
const LANE_SHORT: Record<Lane, string> = { red: "Tinggi", yellow: "Sedang", green: "Rendah" };
const LIST_PARAMS = ["lane", "q", "check", "state", "sort", "page"];

// The review workspace: the flagged claims of one analysis on the left, the selected claim on the right.
// Filters live in the URL so selecting a claim (a route change) keeps the list exactly as it was.
// Order and filters are applied by the server on the stored result, so only one page is downloaded.
export default function CasesPage() {
  const { runId: routeRunId, caseId: routeCaseId } = useParams();
  const navigate = useNavigate();
  const { state, selectRun, reload } = usePersistedRunSnapshot(routeRunId);
  const [params, setParams] = useSearchParams();
  const { state: auth } = useAuth();
  const permissions = "session" in auth ? auth.session?.permissions ?? [] : [];
  const canReadReviews = permissions.includes("review:read");
  const search = params.get("q") ?? "";
  const indicator = params.get("check") ?? "";
  const reviewFilter = (params.get("state") ?? "") as ReviewFilter;
  const assignedParam = params.get("who");
  const assigned = assignedParam === "me" || assignedParam === "none" ? assignedParam : undefined;
  const sortParam = params.get("sort") as SortKey | null;
  const page = Math.max(1, Number(params.get("page")) || 1);
  const [reviews, setReviews] = useState<{ runId: string; items: Map<string, RunReviewSummaryItem> } | { runId: string; error: true } | null>(null);
  const [reviewVersion, setReviewVersion] = useState(0);
  const pageSize = 10;
  const result = state.status === "success" ? state.detail.result : null;
  const runId = state.status === "success" ? state.detail.run.run_id : "";
  const reviewable = Boolean(result && result.availability === "available");
  const mlAvailable = result?.ml_anomaly?.status === "available";
  const sort: SortKey = sortParam && sortParam in SORTS ? sortParam : mlAvailable ? "ml_rank" : "rule_index";
  const laneCounts = result?.action_policy.lane_counts ?? {};
  const laneParam = params.get("lane") as LaneTab | null;
  const laneTab: LaneTab = laneParam && ["red", "yellow", "green", "all", "ai"].includes(laneParam) ? laneParam
    : (laneCounts.red ?? 0) > 0 ? "red" : "all";
  // Computed once per analysis, not on every render (the result can hold thousands of claims).
  const aiOnly = useMemo(() => {
    if (!result || !mlAvailable) return [];
    const flaggedIds = ruleFlaggedListedIds(result);
    return (result.ml_anomaly?.items ?? []).filter(item => !flaggedIds.has(item.case_id));
  }, [result, mlAvailable]);

  // Router navigation may not have re-rendered between two quick filter changes, so each change
  // builds on the last parameters written, not on the possibly stale ones of this render.
  const [filtersOpen, setFiltersOpen] = useState(false);
  const pendingParams = useRef<URLSearchParams | null>(null);
  useEffect(() => { pendingParams.current = null; }, [params]);
  function updateList(changes: Record<string, string>) {
    const next = new URLSearchParams(pendingParams.current ?? params);
    for (const [key, value] of Object.entries(changes)) { if (value) next.set(key, value); else next.delete(key); }
    if (!("page" in changes)) next.delete("page");
    pendingParams.current = next;
    setParams(next, { replace: true });
  }

  // Review state is human metadata stored separately from the immutable run result; reading it never reruns analysis.
  useEffect(() => {
    if (!runId || !reviewable || !canReadReviews) return;
    const controller = new AbortController();
    getRunReviews(runId, controller.signal)
      .then(response => setReviews({ runId, items: new Map(response.items.map(item => [item.case_id, item])) }))
      .catch(() => { if (!controller.signal.aborted) setReviews({ runId, error: true }); });
    return () => controller.abort();
  }, [runId, reviewable, canReadReviews, reviewVersion]);
  const reviewMap = reviews && reviews.runId === runId && "items" in reviews ? reviews.items : null;
  // Who holds which claim; reloaded with the reviews (taking a claim counts as a review change).
  const [holders, setHolders] = useState<{ runId: string; items: Record<string, CaseAssignment> } | null>(null);
  useEffect(() => {
    if (!runId || !reviewable || !canReadReviews) return;
    const controller = new AbortController();
    getRunAssignments(runId, controller.signal)
      .then(response => setHolders({ runId, items: response.items }))
      .catch(() => { if (!controller.signal.aborted) setHolders(null); });
    return () => controller.abort();
  }, [runId, reviewable, canReadReviews, reviewVersion]);
  const holderMap = holders && holders.runId === runId ? holders.items : null;
  const reviewsFailed = Boolean(reviews && reviews.runId === runId && "error" in reviews);

  const query: RunCaseQuery = {
    offset: (page - 1) * pageSize, limit: pageSize, sort,
    indicator: indicator || undefined, search: search.trim() || undefined,
    review_filter: reviewFilter && reviewMap ? reviewFilter : undefined,
    assigned: reviewMap ? assigned : undefined,
    lane: laneTab === "red" || laneTab === "yellow" || laneTab === "green" ? laneTab : undefined,
  };
  const queryKey = JSON.stringify([runId, query]);
  const activeFilters = [
    ...(indicator ? [{ key: "check", label: `Pemeriksaan: ${indicatorLabel(indicator)}` }] : []),
    ...(reviewFilter && reviewMap ? [{ key: "state", label: `Status: ${REVIEW_FILTERS.find(([value]) => value === reviewFilter)?.[1] ?? reviewFilter}` }] : []),
    ...(assigned && reviewMap ? [{ key: "who", label: assigned === "me" ? "Klaim saya" : "Belum diambil" }] : []),
  ];
  const [casePage, setCasePage] = useState<{ key: string; data: RunCaseListResponse } | { key: string; error: string } | null>(null);
  useEffect(() => {
    if (!runId || !reviewable || laneTab === "ai") return;
    const controller = new AbortController();
    const key = queryKey;
    getRunCases(runId, JSON.parse(key)[1] as RunCaseQuery, controller.signal)
      .then(data => setCasePage({ key, data }))
      .catch(reason => { if (!controller.signal.aborted) setCasePage({ key, error: reason instanceof Error ? reason.message : "Daftar klaim tidak dapat dimuat." }); });
    return () => controller.abort();
  }, [runId, reviewable, queryKey, reviewVersion, laneTab]);
  // A page that has not arrived yet is "loading", never "no flagged claims".
  const current = casePage && casePage.key === queryKey ? casePage : null;
  // While the next page is on its way the previous list stays visible (dimmed) instead of blanking out.
  const refreshing = !current && Boolean(casePage && "data" in casePage && casePage.key.startsWith(JSON.stringify([runId]).slice(0, -1)));
  const pageData = current && "data" in current ? current.data : refreshing && casePage && "data" in casePage ? casePage.data : null;
  const pageError = current && "error" in current ? current.error : null;
  const visible = pageData?.items ?? [];
  const pageCount = Math.max(1, Math.ceil((pageData?.total_matching ?? 0) / pageSize));
  const reviewedCount = reviewMap ? pageData?.reviewed_case_count ?? null : null;

  // The list's query string (run and filters) travels with every link so the list survives navigation.
  const listQuery = new URLSearchParams();
  if (runId) listQuery.set("run_id", runId);
  for (const key of LIST_PARAMS) { const value = params.get(key); if (value) listQuery.set(key, value); }
  const listSearch = `?${listQuery.toString()}`;
  const caseHref = (caseId: string) => `/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}${listSearch}`;
  const selected = Boolean(routeRunId && routeCaseId);

  return <>
    <header className="page-head">
      <div>
        <h1>Antrean <span className="muted">Tinjauan</span></h1>
        <p>Mulai dari risiko tinggi. Pilih klaim, baca alasannya, lalu catat tindak lanjutnya.</p>
      </div>
      {state.status === "success" && <div className="page-head-actions">
        {result && <SourcePill source={result.data_source} />}
        <RunSelector runs={state.runs} detail={state.detail} onChange={id => routeRunId ? navigate(`/cases?run_id=${encodeURIComponent(id)}`) : selectRun(id)} />
      </div>}
    </header>
    {state.status !== "success" && <RunStateMessage state={state} retry={reload} />}
    {state.status === "success" && (!result ? <EmptyState title="Hasil analisis tidak tersedia" message="Analisis yang dipilih belum memiliki hasil tersimpan." />
      : result.availability !== "available" ? <EmptyState title="Antrean belum tersedia" message="Hasil analisis ini belum siap. Tidak ada klaim yang ditampilkan dari hasil yang belum lengkap." />
      : <>
        <div className={`queue-layout${selected ? " has-detail" : ""}`}>
          <section className="card queue-list-card" aria-label="Daftar klaim">
            <div className="queue-head">
              <h2>{laneTab === "ai" ? `${formatCount(aiOnly.length)} klaim` : pageData ? `${formatCount(pageData.total_matching)} klaim` : "Klaim ditandai"}</h2>
              {reviewedCount !== null && <span className="queue-head-meta" data-testid="queue-review-progress"
                title={`${formatCount(reviewedCount)} dari ${formatCount(pageData?.total_cases ?? 0)} klaim sudah ditinjau`}>
                {formatCount(reviewedCount)}/{formatCount(pageData?.total_cases ?? 0)} ditinjau</span>}
              {reviewedCount !== null && <QueueAge createdAt={state.detail.run.created_at} unreviewed={(pageData?.total_cases ?? 0) - reviewedCount} />}
            </div>
            {reviewsFailed && <p className="fine-print">Status tinjauan tidak dapat dimuat; daftar klaim tetap ditampilkan.</p>}
            <div className="queue-tabs" role="group" aria-label="Saring tingkat risiko">
              <button type="button" className="queue-tab" aria-pressed={laneTab === "all"} onClick={() => updateList({ lane: "all" })}>Semua <span className="tab-count">{formatCount((laneCounts.red ?? 0) + (laneCounts.yellow ?? 0) + (laneCounts.green ?? 0))}</span></button>
              {(["red", "yellow", "green"] as const).map(lane => <button key={lane} type="button" className="queue-tab lane-tab" aria-pressed={laneTab === lane}
                onClick={() => updateList({ lane })} title={LANES[lane].name} aria-label={`${LANES[lane].name} ${formatCount(laneCounts[lane] ?? 0)}`}>
                <LaneDot lane={lane} />{LANE_SHORT[lane]}<span className="tab-count">{formatCount(laneCounts[lane] ?? 0)}</span></button>)}
              {mlAvailable && <button type="button" className="queue-tab" aria-pressed={laneTab === "ai"} onClick={() => updateList({ lane: "ai" })}
                title="Klaim yang lolos pemeriksaan aturan, tetapi dinilai tidak biasa oleh AI" aria-label={`Temuan tambahan AI ${formatCount(aiOnly.length)}`}>
                Tambahan AI <span className="tab-count">{formatCount(aiOnly.length)}{result.ml_anomaly?.items_truncated ? "+" : ""}</span></button>}
            </div>
            {laneTab === "ai" ? <AiOnlyList items={aiOnly} runId={runId} routeCaseId={routeCaseId} listSearch={listSearch} /> : <>
            <div className="queue-filters">
              <div className="queue-search-row">
                <QueueSearch value={search} onSearch={text => updateList({ q: text })} />
                <button type="button" className={`queue-filter-toggle${activeFilters.length ? " has-active" : ""}`} aria-expanded={filtersOpen}
                  aria-controls="queue-filter-panel" onClick={() => setFiltersOpen(open => !open)}>
                  <SlidersHorizontal size={15} aria-hidden="true" />Filter{activeFilters.length > 0 && <span className="filter-count">{activeFilters.length}</span>}
                </button>
              </div>
              <div id="queue-filter-panel" className="queue-filter-panel" hidden={!filtersOpen}>
                <label><span>Pemeriksaan</span>
                  <select aria-label="Filter jenis pemeriksaan" value={indicator} onChange={event => updateList({ check: event.target.value })}>
                    <option value="">Semua pemeriksaan</option>
                    {result.indicators.map(item => <option key={item.code} value={item.code}>{indicatorLabel(item.code)}</option>)}
                  </select></label>
                <label><span>Urutan</span>
                  <select aria-label="Urutkan" value={sort} onChange={event => updateList({ sort: event.target.value })}>
                    {(Object.keys(SORTS) as SortKey[])
                      .filter(key => (key !== "review_updated" || reviewMap) && (key !== "ml_rank" || mlAvailable))
                      .map(key => <option key={key} value={key}>{SORTS[key]}</option>)}
                  </select></label>
                {reviewMap && <label><span>Status</span>
                  <select aria-label="Filter status tinjauan" value={reviewFilter} onChange={event => updateList({ state: event.target.value })}>
                    {REVIEW_FILTERS.map(([value, label]) => <option key={value || "all"} value={value}>{label}</option>)}
                  </select></label>}
                {reviewMap && <label><span>Penanggung jawab</span>
                  <select aria-label="Filter penanggung jawab" value={assigned ?? ""} onChange={event => updateList({ who: event.target.value })}>
                    <option value="">Semua petugas</option>
                    <option value="me">Klaim saya</option>
                    <option value="none">Belum diambil</option>
                  </select></label>}
              </div>
              {activeFilters.length > 0 && <div className="queue-active-filters" aria-label="Filter aktif">
                {activeFilters.map(item => <span key={item.key} className="filter-chip">{item.label}
                  <button type="button" onClick={() => updateList({ [item.key]: "" })} aria-label={`Hapus saringan ${item.label}`}><X size={12} /></button></span>)}
              </div>}
            </div>
            {pageError ? <EmptyState title="Daftar klaim tidak dapat dimuat" message={pageError} />
              : !pageData ? <p className="fine-print" role="status">Memuat daftar klaim…</p>
              : visible.length === 0 ? <EmptyState title="Tidak ada klaim untuk saringan ini" message="Coba saringan lain." />
              : <ul className={`queue-items${refreshing ? " is-refreshing" : ""}`} aria-busy={refreshing || undefined}>
                {visible.map(({ case: item, lane }) => {
                  const review = reviewMap?.get(item.case_id);
                  const percentile = item.ml_anomaly ? item.ml_anomaly.reference_percentile ?? item.ml_anomaly.anomaly_percentile : null;
                  const level = percentile !== null ? mlLevel(percentile) : null;
                  return <li key={item.case_id} data-case-id={item.case_id}>
                    <Link className="queue-item" to={caseHref(item.case_id)} aria-current={item.case_id === routeCaseId ? "true" : undefined}>
                      <LaneDot lane={lane?.lane ?? "none"} />
                      <span className="queue-item-body">
                        <strong>{item.indicators.map(indicatorLabel).join(" + ") || "Klaim ditandai"}</strong>
                        <small>Ref. {shortRef(item.case_id)}{lane && lane.lane in LANES ? ` · ${LANES[lane.lane as Lane].name}` : ""}</small>
                        {review?.audit_result && <small data-testid="queue-audit-result">{auditResultLabels[review.audit_result]}</small>}
                      </span>
                      <span className="queue-item-side">
                        {reviewMap && <span data-testid="queue-review-cell" className="queue-review-cell">
                          <span className={`status-pill status-${review?.review_status ?? "pending_review"}`}>{review ? runReviewStatusLabels[review.review_status] : "Belum ditinjau"}</span>
                          {review?.review_outcome && <small>{reviewOutcomeLabels[review.review_outcome]}</small>}
                        </span>}
                        {level && <span className={`status-pill tone-${level.tone}`}>AI: {level.label}</span>}
                        {holderMap?.[item.case_id] && <small className="queue-assignee" data-testid="queue-assignee">
                          {holderMap[item.case_id].is_me ? "Ditangani Anda" : `Ditangani ${holderMap[item.case_id].username}`}</small>}
                      </span>
                    </Link>
                  </li>;
                })}
              </ul>}
            {pageData && pageData.total_matching > 0 && <div className="pager">
              <span>Halaman {page} dari {pageCount}</span>
              <div>
                <button className="button button-secondary button-compact" disabled={page <= 1} onClick={() => updateList({ page: String(page - 1) })}>Sebelumnya</button>
                <button className="button button-secondary button-compact" disabled={page >= pageCount} onClick={() => updateList({ page: String(page + 1) })}>Berikutnya</button>
                <ReviewShortcuts />
              </div>
            </div>}
            </>}
          </section>
          <div className="queue-detail">
            {selected && routeRunId && routeCaseId
              ? <CaseReviewPanel key={`${routeRunId}/${routeCaseId}`} runId={routeRunId} caseId={routeCaseId} backTo={`/cases${listSearch}`} onSaved={() => setReviewVersion(value => value + 1)} />
              : <section className="card detail-placeholder">
                <MousePointerClick size={30} color="var(--brand-ink)" style={{ justifySelf: "center" }} />
                <strong>Pilih klaim di kiri</strong>
                <span>Rincian alasan dan formulir tinjauan akan tampil di sini.</span>
              </section>}
          </div>
        </div>
      </>)}
  </>;
}

/** Claims the ML ranking found unusual that no rule check flagged (stored top list, paged locally). */
function AiOnlyList({ items, runId, routeCaseId, listSearch }: {
  items: MlAnomaly["items"]; runId: string; routeCaseId?: string; listSearch: string;
}) {
  const [page, setPage] = useState(1);
  const pageSize = 10;
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const visible = items.slice((page - 1) * pageSize, page * pageSize);
  if (items.length === 0) return <EmptyState title="Tidak ada klaim tambahan dari AI" message="Semua klaim yang dinilai tidak biasa oleh AI sudah ditandai pemeriksaan aturan." />;
  return <>
    <p className="fine-print">Klaim yang lolos pemeriksaan aturan, tetapi dinilai tidak biasa oleh AI.</p>
    <ul className="queue-items">{visible.map(item => {
      const level = mlLevel(item.reference_percentile ?? item.anomaly_percentile);
      return <li key={item.case_id} data-case-id={item.case_id}>
        <Link className="queue-item" to={`/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(item.case_id)}${listSearch}`} aria-current={item.case_id === routeCaseId ? "true" : undefined}>
          <span className="avatar-ref">#{item.rank}</span>
          <span className="queue-item-body">
            <strong>Ref. {shortRef(item.case_id)}</strong>
            <small>{item.top_deviations.slice(0, 2).map(d => mlFeatureLabel(d.feature, d.description)).join(" · ") || "Gabungan beberapa data yang tidak biasa"}</small>
          </span>
          <span className="queue-item-side"><span className={`status-pill tone-${level.tone}`}>AI: {level.label}</span></span>
        </Link>
      </li>;
    })}</ul>
    {pageCount > 1 && <div className="pager"><span>Halaman {page} dari {pageCount}</span><div>
      <button className="button button-secondary button-compact" disabled={page <= 1} onClick={() => setPage(page - 1)}>Sebelumnya</button>
      <button className="button button-secondary button-compact" disabled={page >= pageCount} onClick={() => setPage(page + 1)}>Berikutnya</button>
    </div></div>}
  </>;
}

/** The search box keeps its own text: typing re-renders only this box, and the list is asked once typing pauses. */
const QueueSearch = memo(function QueueSearch({ value, onSearch }: { value: string; onSearch: (text: string) => void }) {
  const [draft, setDraft] = useState(value);
  const latest = useRef(onSearch);
  latest.current = onSearch;
  useEffect(() => { setDraft(current => current.trim() === value ? current : value); }, [value]);
  useEffect(() => {
    if (draft.trim() === value) return;
    const timer = window.setTimeout(() => latest.current(draft.trim()), 350);
    return () => window.clearTimeout(timer);
  }, [draft, value]);
  return <label className="queue-search"><Search size={15} aria-hidden="true" />
    <input aria-label="Cari nomor referensi klaim" type="search" value={draft} onChange={event => setDraft(event.target.value)}
      placeholder="Cari nomor referensi klaim" autoComplete="off" spellCheck={false} />
  </label>;
});

/** How long this analysis's claims have waited: amber after a week, red after two weeks while claims are still unreviewed. */
function QueueAge({ createdAt, unreviewed }: { createdAt: string; unreviewed: number }) {
  const days = analysisAgeDays(createdAt);
  const tone = ageTone(days, unreviewed);
  return <span className={`queue-age tone-${tone}`} data-testid="queue-age" title={`Antrean dibuat ${ageText(days)}; klaim masuk antrean saat analisis dibuat.`}>
    <Clock3 size={12} aria-hidden="true" />{ageText(days)}{unreviewed > 0 && days > 7 ? ` · ${formatCount(unreviewed)} belum` : ""}
  </span>;
}
