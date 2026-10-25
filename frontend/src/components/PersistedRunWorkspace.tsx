import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { RunDetailResponse, RunManifest } from "../api/client";
import { EmptyState, ErrorState, LoadingState } from "./DataStates";
import type { PersistedRunState } from "../hooks/usePersistedRunSnapshot";

export function RunStateMessage({ state, retry }: { state: PersistedRunState; retry: () => void }) {
  if (state.status === "loading") return <LoadingState label="Memuat AnalysisRun tersimpan…" />;
  if (state.status === "forbidden") return <EmptyState title="Akses hasil dibatasi" message="Role ini tidak memiliki runs:results:read. Hasil run tidak diganti dengan ringkasan legacy." />;
  if (state.status === "empty") return <EmptyState title="Belum ada AnalysisRun" message="Buat run dari batch sintetis pada Data Klaim. Tidak ada snapshot analisis yang tersedia." />;
  if (state.status === "error") return <ErrorState message={state.message} httpStatus={state.httpStatus} onRetry={retry} />;
  return null;
}

export function RunSelector({ runs, detail, onChange }: {
  runs: RunManifest[]; detail: RunDetailResponse; onChange: (runId: string) => void;
}) {
  const options = runs.some(run => run.run_id === detail.run.run_id) ? runs : [detail.run, ...runs];
  return <section className="surface-panel section-block run-snapshot-context">
    <label className="review-field">Snapshot AnalysisRun
      <select aria-label="AnalysisRun tersimpan" value={detail.run.run_id} onChange={event => onChange(event.target.value)}>
        {options.map(run => <option key={run.run_id} value={run.run_id}>{run.run_id} · {run.execution_status} · {run.created_at}</option>)}
      </select>
    </label>
    <div className="analysis-facts">
      <span><strong>{detail.run.run_id}</strong> run</span>
      <span><strong>{detail.run.batch_id}</strong> batch · v{detail.run.batch_version}</span>
      <span><strong>{detail.run.execution_status}</strong> status</span>
      <span><strong>{detail.run.source_classification}</strong> klasifikasi sumber</span>
      <span><strong>{detail.run.source_schema_version}</strong> skema · <strong>{detail.run.source_mapping_version}</strong> mapping</span>
    </div>
    <p className="workflow-muted">
      Snapshot persisten dibaca dari server; halaman ini tidak menjalankan ulang analisis. Sinyal kandidat bukan bukti
      fraud. Klasifikasi synthetic-only berasal dari deklarasi saat impor, bukan verifikasi independen isi file.
    </p>
  </section>;
}

export function RunCandidateLink({ runId, caseId, children }: { runId: string; caseId: string; children: ReactNode }) {
  return <Link to={`/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}`}>{children}</Link>;
}
