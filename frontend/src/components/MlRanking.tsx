import { useEffect, useState } from "react";
import { ArrowRight, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import type { MlAnomaly } from "../api/client";
import { EmptyState } from "./DataStates";
import {
  Callout, MoreInfo, mlQualification, StatusPill, TechnicalDetails, formatCount, mlFeatureLabel, mlLevel, mlRankText,
  mlTechnicalItems, shortRef,
} from "./Display";

/** AI ranking of unusual claims. Per claim only, never a facility ranking. */
export function MlRankingSection({ runId, ml, ruleCaseIds }: { runId: string; ml: MlAnomaly; ruleCaseIds: Set<string> }) {
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<"all" | "rules" | "ml_only">("all");
  const pageSize = 10;
  const items = ml.items.filter(item =>
    filter === "all" || (filter === "rules" ? ruleCaseIds.has(item.case_id) : !ruleCaseIds.has(item.case_id)));
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const visible = items.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  useEffect(() => setPage(1), [runId, filter]);
  return (
    <section className="card ml-ranking">
      <div className="card-head">
        <div>
          <h2><Sparkles size={16} style={{ verticalAlign: "-2px", color: "var(--brand-ink)" }} /> Urutan klaim paling tidak biasa menurut AI</h2>
          <p>
            {ml.records_scored > 0
              ? `AI mengurutkan ${formatCount(ml.records_scored)} klaim dari yang paling tidak biasa sampai yang paling wajar.`
              : "AI dapat mengurutkan klaim dari yang paling tidak biasa sampai yang paling wajar."}{" "}
            Yang dinilai adalah klaim per kunjungan, bukan rumah sakit. Identitas, nominal biaya, dan kode faskes tidak dipakai.
          </p>
        </div>
        <StatusPill value={ml.status} />
      </div>
      <Callout tone="info" title="Cara membaca peringkat ini">
        <p>{mlQualification(ml)}</p>
      </Callout>
      {ml.items.length === 0 ? (
        <EmptyState title="Peringkat belum tersedia" message={ml.status === "insufficient_data"
          ? "Klaim terlalu sedikit untuk diurutkan."
          : "AI tidak menilai analisis ini. Hasil pemeriksaan aturan tetap berlaku."} />
      ) : (
        <>
          <div className="queue-tabs" role="group" aria-label="Saring klaim berperingkat" style={{ marginTop: 12 }}>
            {([["all", "Semua"], ["rules", "Juga ditandai aturan"], ["ml_only", "Temuan tambahan AI"]] as const).map(([value, label]) => (
              <button key={value} type="button" className="queue-tab" aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>
            ))}
          </div>
          <ol className="row-list ranked-list">
            {visible.map(item => {
              const alsoRules = ruleCaseIds.has(item.case_id);
              const level = mlLevel(item.anomaly_percentile);
              const tied = item.tie_count !== undefined && item.tie_count > 1;
              return (
                <li key={item.case_id}>
                  <Link className="row-item interactive-row" to={`/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(item.case_id)}`}>
                    <span className="avatar-ref" title={tied ? "Nilainya sama dengan klaim lain" : undefined}>#{formatCount(item.rank)}{tied ? "=" : ""}</span>
                    <span className="row-main">
                      <strong>{mlRankText(item.rank, ml.records_scored, item.tie_count)} · Ref. {shortRef(item.case_id)}</strong>
                      <span>
                        {item.top_deviations.length
                          ? item.top_deviations.map(d => mlFeatureLabel(d.feature, d.description)).join(" · ")
                          : "Gabungan beberapa data yang tidak biasa"}
                      </span>
                    </span>
                    <span className={`status-pill tone-${level.tone}`}>{level.label}</span>
                    <span className={`status-pill tone-${alsoRules ? "warn" : "info"}`}>{alsoRules ? "Juga ditandai aturan" : "Temuan tambahan AI"}</span>
                    <span className="row-action">Tinjau <ArrowRight size={14} /></span>
                  </Link>
                </li>
              );
            })}
          </ol>
          {items.length === 0 && <EmptyState title="Tidak ada klaim untuk saringan ini" message="Coba saringan lain." />}
          <div className="pager" style={{ marginTop: 10 }}>
            <span>{formatCount(items.length)} klaim{ml.items_truncated ? ` (${formatCount(ml.items.length)} teratas dari ${formatCount(ml.records_scored)})` : ""} · halaman {currentPage} dari {pageCount}</span>
            <div>
              <button className="button button-secondary button-compact" disabled={currentPage <= 1} onClick={() => setPage(currentPage - 1)}>Sebelumnya</button>
              <button className="button button-secondary button-compact" disabled={currentPage >= pageCount} onClick={() => setPage(currentPage + 1)}>Berikutnya</button>
            </div>
          </div>
        </>
      )}
      <MoreInfo title="Keterbatasan peringkat AI" items={ml.limitations} />
      <TechnicalDetails items={mlTechnicalItems(ml)}>
        {ml.excluded_fields && <p className="tech-note">Tidak dipakai sebagai masukan AI: {ml.excluded_fields.join("; ")}.</p>}
        {ml.features && <p className="tech-note">Masukan AI: {ml.features.map(f => mlFeatureLabel(f.name, f.name)).join(", ")}.</p>}
      </TechnicalDetails>
    </section>
  );
}
