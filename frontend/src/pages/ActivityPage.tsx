import { useCallback, useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { ApiClientError, getActivity, type ActivityCategory, type ActivityItem, type ActivityResponse } from "../api/client";
import { EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import { formatCount, formatDateTime, shortRef } from "../components/Display";

const CATEGORIES: Array<[ActivityCategory | null, string]> = [
  [null, "Semua"], ["akun", "Akun"], ["data", "Data"], ["analisis", "Analisis"], ["tinjauan", "Tinjauan"],
];
const EVENT_LABELS: Record<string, string> = {
  admin_bootstrap_completed: "Membuat akun administrator pertama",
  login_failed: "Gagal masuk",
  login_succeeded: "Masuk",
  logout_session_revoked: "Keluar",
  session_expired: "Sesi berakhir",
  session_revoked_inactive_account: "Sesi diakhiri karena akun dinonaktifkan",
  user_created: "Membuat akun baru",
  user_updated: "Mengubah akun",
  batch_imported: "Mengunggah file data",
  batch_import_rejected: "File data ditolak",
  batch_import_reused: "Mengunggah file yang sudah ada",
  local_source_registered: "Mendaftarkan sumber data server",
  local_source_reused: "Memakai ulang sumber data server",
  batch_removed_from_list: "Menyembunyikan file dari daftar",
  batch_restored_to_list: "Menampilkan lagi file data",
  analysis_run_created: "Menjalankan analisis",
  analysis_run_retry_created: "Menjalankan ulang analisis",
  analysis_run_completed: "Analisis selesai",
  analysis_run_partial: "Analisis selesai sebagian",
  analysis_run_failed: "Analisis gagal",
  run_archived: "Mengarsipkan analisis",
  run_restored: "Menampilkan lagi analisis",
  run_superseded: "Analisis lama diarsipkan karena ada yang lebih baru",
  run_archived_auto: "Analisis diarsipkan otomatis",
  review_updated: "Mengubah tinjauan",
  run_review_status_changed: "Mengubah status tinjauan",
  run_review_outcome_changed: "Memberi keputusan tinjauan",
  run_audit_confirmation_recorded: "Mencatat hasil audit resmi",
  run_review_carried_over: "Tinjauan dibawa ke analisis baru",
  case_taken: "Mengambil klaim",
  case_released: "Melepas klaim",
};
const TARGETS: Record<string, string> = { claim: "Klaim", analysis: "Analisis", data_file: "File data", user: "Akun" };

function targetText(item: ActivityItem): string {
  const kind = item.target_type ? TARGETS[item.target_type] : undefined;
  return kind && item.target_id ? `${kind} ${shortRef(item.target_id)}` : "—";
}

/** Who did what and when, from the append-only logs of sign-in, data, analyses and reviews (administrators only). */
export default function ActivityPage() {
  const [category, setCategory] = useState<ActivityCategory | null>(null);
  const [state, setState] = useState<{ status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: ActivityResponse }>({ status: "loading" });
  const load = useCallback((signal?: AbortSignal) => {
    setState({ status: "loading" });
    getActivity(category, signal).then(data => setState({ status: "ready", data })).catch(reason => {
      if (signal?.aborted) return;
      setState({ status: "error", message: reason instanceof ApiClientError ? reason.message : "Riwayat aktivitas tidak dapat dimuat." });
    });
  }, [category]);
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);
  const counts = state.status === "ready" ? state.data.counts : null;

  return <>
    <header className="page-head">
      <div><h1>Riwayat Aktivitas</h1><p>Siapa melakukan apa dan kapan: masuk akun, data, analisis, dan tinjauan klaim.</p></div>
    </header>
    <section className="card" aria-label="Daftar aktivitas" data-testid="activity-log">
      <div className="card-head activity-head">
        <div className="segmented-pill" role="group" aria-label="Jenis aktivitas">
          {CATEGORIES.map(([value, label]) => <button key={label} type="button" aria-pressed={category === value} onClick={() => setCategory(value)}>
            {label}{value && counts ? ` (${formatCount(counts[value])})` : ""}
          </button>)}
        </div>
        <span className="fine-print activity-note"><ShieldCheck size={14} aria-hidden="true" />Catatan hanya dapat dibaca; tidak ada yang dapat mengubah atau menghapusnya dari aplikasi.</span>
      </div>
      {state.status === "loading" ? <LoadingState label="Memuat riwayat aktivitas…" />
        : state.status === "error" ? <ErrorState message={state.message} httpStatus={null} onRetry={() => load()} />
        : state.data.items.length === 0 ? <EmptyState title="Belum ada aktivitas" message="Aktivitas muncul setelah petugas masuk, mengunggah data, atau meninjau klaim." />
        : <>
          <div className="table-scroll"><table className="data-table activity-table">
            <thead><tr><th>Waktu</th><th>Pengguna</th><th>Aktivitas</th><th>Objek</th></tr></thead>
            <tbody>{state.data.items.map(item => <tr key={item.event_id} className={item.event_type === "login_failed" ? "activity-alert" : undefined}>
              <td className="activity-time">{formatDateTime(item.occurred_at)}</td>
              <td>{item.actor_kind === "user" ? <strong>{item.actor_name}</strong> : <span className="fine-print">{item.actor_name}</span>}</td>
              <td>{EVENT_LABELS[item.event_type] ?? item.event_type}</td>
              <td className="activity-target">{targetText(item)}</td>
            </tr>)}</tbody>
          </table></div>
          <p className="fine-print" style={{ marginTop: 12 }}>Menampilkan {formatCount(state.data.items.length)} aktivitas terbaru (paling banyak {formatCount(state.data.limit)}).</p>
        </>}
    </section>
  </>;
}
