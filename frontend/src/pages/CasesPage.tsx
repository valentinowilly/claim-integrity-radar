import { useCallback, useState } from "react";
import { ArrowDownUp, ChevronLeft, ChevronRight, Filter, Search } from "lucide-react";
import { Link } from "react-router-dom";
import { getCases, reviewStatusLabels, type IndicatorCode, type ReviewStatus, type RiskLevel } from "../api/client";
import {
  EmptyState,
  ErrorState,
  formatNumber,
  indicatorLabel,
  LoadingState,
  PageHeading,
  SourceBadge,
} from "../components/DataStates";
import { useApiResource } from "../hooks/useApiResource";

export default function CasesPage() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(5);
  const [riskLevel, setRiskLevel] = useState<Exclude<RiskLevel, null> | "">("");
  const [indicator, setIndicator] = useState<IndicatorCode | "">("");
  const [reviewStatus, setReviewStatus] = useState<ReviewStatus | "">("");
  const [sortBy, setSortBy] = useState<"risk_score" | "detected_at">("risk_score");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const load = useCallback(
    (signal: AbortSignal) =>
      getCases(
        {
          page,
          page_size: pageSize,
          risk_level: riskLevel || undefined,
          indicator: indicator || undefined,
          review_status: reviewStatus || undefined,
          sort_by: sortBy,
          sort_order: sortOrder,
        },
        signal,
      ),
    [page, pageSize, riskLevel, indicator, reviewStatus, sortBy, sortOrder],
  );
  const { state, reload } = useApiResource(load);

  function changeIndicator(value: string) {
    setIndicator(value as IndicatorCode | "");
    setPage(1);
  }

  function changeReviewStatus(value: string) {
    setReviewStatus(value as ReviewStatus | "");
    setPage(1);
  }

  return (
    <>
      <PageHeading
        eyebrow="TINDAK LANJUT"
        title="Antrean Audit"
        description="Daftar kandidat yang perlu ditinjau. Indeks aturan bersifat provisional, bukan probabilitas fraud atau level risiko tervalidasi."
        action={state.status === "success" ? <SourceBadge source={state.data.data_source} /> : undefined}
      />
      <section className="queue-toolbar surface-panel">
        <div className="queue-toolbar-title">
          <span className="toolbar-icon">
            <Filter size={16} />
          </span>
          <div>
            <strong>Filter dan urutan</strong>
            <small>Parameter diteruskan ke API</small>
          </div>
        </div>
        <div className="filter-controls">
          <label>
            Level risiko (belum ditetapkan)
            <select
              value={riskLevel}
              onChange={(event) => {
                setRiskLevel(event.target.value as Exclude<RiskLevel, null> | "");
                setPage(1);
              }}
            >
              <option value="">Semua level</option>
              <option value="high">Tinggi (belum tersedia)</option>
              <option value="medium">Sedang (belum tersedia)</option>
              <option value="low">Rendah (belum tersedia)</option>
            </select>
          </label>
          <label>
            Indikator
            <select value={indicator} onChange={(event) => changeIndicator(event.target.value)}>
              <option value="">Semua indikator</option>
              <option value="repeat_billing_candidate">Pola penagihan berulang</option>
              <option value="similar_claim_pattern_candidate">Pola klaim serupa</option>
              <option value="near_duplicate_claim_candidate">Klaim hampir duplikat</option>
              <option value="synthetic_capacity_candidate">Kapasitas layanan</option>
              <option value="temporal_pattern_candidate">Pola berdasarkan waktu</option>
              <option value="supporting_evidence_completeness_candidate">Kelengkapan bukti</option>
            </select>
          </label>
          <label>
            Status tinjauan
            <select value={reviewStatus} onChange={(event) => changeReviewStatus(event.target.value)}>
              <option value="">Semua status tinjauan</option>
              {(Object.keys(reviewStatusLabels) as ReviewStatus[]).map((value) => (
                <option value={value} key={value}>
                  {reviewStatusLabels[value]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Kolom urutan
            <select
              value={sortBy}
              onChange={(event) => {
                setSortBy(event.target.value as "risk_score" | "detected_at");
                setPage(1);
              }}
            >
              <option value="risk_score">Indeks aturan provisional</option>
              <option value="detected_at">Waktu deteksi (belum tersedia)</option>
            </select>
          </label>
          <label>
            Arah
            <select
              value={sortOrder}
              onChange={(event) => {
                setSortOrder(event.target.value as "asc" | "desc");
                setPage(1);
              }}
            >
              <option value="desc">Menurun</option>
              <option value="asc">Menaik</option>
            </select>
          </label>
          <label>
            Baris per halaman
            <select
              value={pageSize}
              onChange={(event) => {
                setPageSize(Number(event.target.value));
                setPage(1);
              }}
            >
              <option value={5}>5</option>
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </label>
        </div>
      </section>

      {state.status === "loading" && <LoadingState label="Mengambil antrean kandidat…" />}
      {state.status === "error" && (
        <ErrorState message={state.message} httpStatus={state.httpStatus} onRetry={reload} />
      )}
      {state.status === "success" && state.data.availability !== "available" && (
        <EmptyState title="Antrean belum tersedia" message="API belum menyediakan sumber kasus untuk ditampilkan." />
      )}
      {state.status === "success" && state.data.availability === "available" && (
        <section className="surface-panel queue-panel">
          <div className="queue-header">
            <div>
              <span className="eyebrow muted-eyebrow">KANDIDAT TINJAUAN</span>
              <h2>{formatNumber(state.data.pagination.total_items)} kasus</h2>
            </div>
            <div className="queue-header-note">
              <ArrowDownUp size={14} />
              <span>{state.data.notice}</span>
            </div>
          </div>
          {state.data.items.length === 0 ? (
            <EmptyState
              title="Tidak ada kandidat untuk filter ini"
              message="Ubah indikator atau status untuk melihat kandidat yang tersedia. Daftar kosong adalah hasil filter yang sah."
            />
          ) : (
            <>
              <div className="table-scroll">
                <table className="case-table">
                  <thead>
                    <tr>
                      <th>ID kasus</th>
                      <th>Indikator pemicu</th>
                      <th>Alasan ringkas</th>
                      <th>Status tinjauan</th>
                      <th aria-label="Buka detail" />
                    </tr>
                  </thead>
                  <tbody>
                    {state.data.items.map((item) => (
                      <tr key={item.case_id}>
                        <td>
                          <Link className="case-id-link" to={`/cases/${encodeURIComponent(item.case_id)}`}>
                            {item.case_id}
                            <Search size={13} />
                          </Link>
                        </td>
                        <td>
                          <div className="table-badges">
                            {item.indicators.map((code) => (
                              <span className="indicator-pill" key={code}>
                                {indicatorLabel(code)}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="reason-cell">
                          {item.reasons[0]?.summary ?? "Alasan tidak disertakan oleh API."}
                        </td>
                        <td>
                          <span className={`status-pill status-review-${item.review_status}`}>
                            {reviewStatusLabels[item.review_status]}
                          </span>
                        </td>
                        <td>
                          <Link
                            className="row-action"
                            aria-label={`Lihat detail ${item.case_id}`}
                            to={`/cases/${encodeURIComponent(item.case_id)}`}
                          >
                            <ChevronRight size={17} />
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="pagination-row">
                <span>
                  Halaman {state.data.pagination.page} dari {state.data.pagination.total_pages}
                </span>
                <div>
                  <button
                    className="button button-secondary"
                    disabled={page <= 1}
                    onClick={() => setPage((value) => Math.max(1, value - 1))}
                  >
                    <ChevronLeft size={15} />
                    Sebelumnya
                  </button>
                  <button
                    className="button button-secondary"
                    disabled={page >= state.data.pagination.total_pages}
                    onClick={() => setPage((value) => value + 1)}
                  >
                    Berikutnya
                    <ChevronRight size={15} />
                  </button>
                </div>
              </div>
            </>
          )}
        </section>
      )}
    </>
  );
}
