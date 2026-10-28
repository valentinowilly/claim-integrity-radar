import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Database } from "lucide-react";
import type { DataSource, RunDetailResponse, RunManifest } from "../api/client";
import { EmptyState, ErrorState, LoadingState } from "./DataStates";
import { shortRunTitle, TechnicalDetails } from "./Display";
import type { PersistedRunState } from "../hooks/usePersistedRunSnapshot";

export function RunStateMessage({ state, retry }: { state: PersistedRunState; retry: () => void }) {
  if (state.status === "loading") return <LoadingState label="Memuat hasil analisis…" />;
  if (state.status === "forbidden") return <EmptyState title="Hasil analisis tidak tersedia untuk peran Anda" message="Hasil analisis hanya dapat dibuka oleh verifikator dan administrator." />;
  if (state.status === "empty") return (
    <div className="card">
      <EmptyState title="Belum ada analisis" message="Jalankan analisis pertama dari menu Data & Analisis. Hasilnya akan tampil di sini." />
      <div className="inline-actions" style={{ justifyContent: "center" }}>
        <Link className="button button-primary" to="/workflow"><Database size={15} />Buka Data & Analisis</Link>
      </div>
    </div>
  );
  if (state.status === "error") return <ErrorState message={state.message} httpStatus={state.httpStatus} onRetry={retry} />;
  return null;
}

/** One compact analysis picker for the page header (defaults to the latest analysis). */
export function RunSelector({ runs, detail, onChange }: {
  runs: RunManifest[]; detail: RunDetailResponse; onChange: (runId: string) => void;
}) {
  const listed = runs.some(run => run.run_id === detail.run.run_id);
  const options = listed ? runs : [detail.run, ...runs];
  return (
    <div className="run-picker" title="Angka di halaman ini berasal dari hasil analisis yang dipilih.">
      <label htmlFor="run-picker-select">Hasil analisis</label>
      <select id="run-picker-select" aria-label="Pilih hasil analisis" value={detail.run.run_id} onChange={event => onChange(event.target.value)}>
        {options.map(run => <option key={run.run_id} value={run.run_id}>{shortRunTitle(run)}{listed || run.run_id !== detail.run.run_id ? "" : " · diarsipkan"}</option>)}
      </select>
    </div>
  );
}

/** Which data the shown analysis came from, in plain words. */
export function SourcePill({ source }: { source: DataSource }) {
  const uploaded = source.kind === "synthetic" || source.label === "synthetic_demo" || source.label === "synthetic_data_batch"
    || source.label === "synthetic_fkrtl_fixture";
  return <span className={`source-pill${uploaded ? "" : " real"}`}>{uploaded ? "Berkas unggahan" : "Data klaim FKRTL"}</span>;
}

/** IDs and versions for administrators, collapsed at the bottom of a page. */
export function RunTechnicalDetails({ detail }: { detail: RunDetailResponse }) {
  return (
    <TechnicalDetails items={[
      { label: "ID analisis", value: detail.run.run_id, copy: true },
      { label: "ID data", value: `${detail.run.batch_id} (versi ${detail.run.batch_version})` },
      { label: "Jenis sumber data", value: detail.run.source_classification },
      { label: "Skema / pemetaan", value: `${detail.run.source_schema_version} / ${detail.run.source_mapping_version}` },
      { label: "Versi aturan pemeriksaan", value: [detail.run.detector_suite_version, detail.run.scoring_version, detail.run.priority_version, detail.run.action_policy_version].map(item => item ?? "—").join(" / ") },
    ]} />
  );
}

export function RunCandidateLink({ runId, caseId, children, className }: { runId: string; caseId: string; children: ReactNode; className?: string }) {
  return <Link className={className} to={`/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}`}>{children}</Link>;
}
