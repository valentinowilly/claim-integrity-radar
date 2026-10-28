import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { getNotifications, type NotificationItem } from "../api/client";
import { shortRef } from "../components/Display";

export type ToastTone = "info" | "success" | "warning" | "danger";
export interface ToastInput { tone: ToastTone; title: string; message?: string; link?: { to: string; label: string } }
interface Toast extends ToastInput { id: string }

const POLL_MS = 15_000;
const MAX_POPUPS_PER_UPDATE = 3;
const DISMISS_MS: Record<ToastTone, number> = { info: 8_000, success: 6_000, warning: 14_000, danger: 20_000 };
const ICONS = { info: Info, success: CheckCircle2, warning: AlertTriangle, danger: XCircle };

const NotifyContext = createContext<(toast: ToastInput) => void>(() => undefined);

/** Shows a popup from anywhere in the signed-in app (e.g. "Status tinjauan tersimpan"). */
export function useNotify() {
  return useContext(NotifyContext);
}

// Per-user cursor so the next sign-in shows what happened meanwhile; storage may be unavailable.
function readCursor(userId: string): string | null {
  try { return window.localStorage.getItem(`cir:notifications:since:${userId}`); } catch { return null; }
}
function writeCursor(userId: string, value: string) {
  try { window.localStorage.setItem(`cir:notifications:since:${userId}`, value); } catch { /* per-session only */ }
}

const RUN_STATUS: Record<string, string> = { completed: "selesai", partial: "selesai", failed: "gagal" };
const VALIDATION_STATUS: Record<string, [ToastTone, string]> = {
  passed: ["success", "selesai"], passed_with_warnings: ["warning", "selesai dengan catatan"], failed: ["danger", "menemukan masalah"],
  job_failed: ["danger", "tidak selesai"],
};
const OUTCOME: Record<string, string> = {
  signal_supported: "indikasi terbukti", signal_not_supported: "ternyata wajar", inconclusive: "belum bisa disimpulkan",
};
const AUDIT: Record<string, string> = { confirmed_issue: "Ada masalah", confirmed_no_issue: "Tidak ada masalah" };

/** Text for a server event; values are structured codes, never notes or source data. */
export function describe(item: NotificationItem): ToastInput {
  const caseLink = item.run_id && item.case_id
    ? { to: `/runs/${encodeURIComponent(item.run_id)}/cases/${encodeURIComponent(item.case_id)}`, label: "Buka klaim" } : undefined;
  const caseRef = item.case_id ? ` · klaim ${shortRef(item.case_id)}` : "";
  switch (item.kind) {
    case "validation_finished": {
      const [tone, label] = VALIDATION_STATUS[item.status ?? ""] ?? ["info", "selesai"];
      return { tone, title: `Pemeriksaan kualitas data ${label}`,
        message: tone === "danger" ? "Analisis belum dapat dijalankan sampai masalah data diperbaiki." : "Analisis sekarang dapat dijalankan untuk data ini.",
        link: { to: "/workflow", label: "Buka Data & Analisis" } };
    }
    case "run_finished":
      // "partial" is normal for claim data (e.g. blank procedure codes leave some claims unassessed by one check).
      return { tone: item.status === "failed" ? "danger" : "success",
        title: `Analisis ${RUN_STATUS[item.status ?? ""] ?? "selesai"}`,
        message: `${item.source_type === "bpjs_fkrtl_local" ? "Data klaim FKRTL" : "Berkas unggahan"}${item.status === "partial"
          ? " · sebagian klaim datanya tidak lengkap untuk beberapa pemeriksaan" : ""}`,
        link: item.run_id ? { to: `/?run_id=${encodeURIComponent(item.run_id)}`, label: "Lihat hasil" } : undefined };
    case "case_escalated":
      return { tone: "warning", title: "Klaim masuk antrean audit", message: `Perlu keputusan audit${caseRef}.`, link: caseLink };
    case "outcome_recorded":
      return { tone: "info", title: "Keputusan tinjauan dicatat", message: `Hasil: ${OUTCOME[item.status ?? ""] ?? "dicatat"}${caseRef}.`, link: caseLink };
    case "audit_result_recorded":
      return { tone: "info", title: "Hasil audit resmi dicatat", message: `${AUDIT[item.status ?? ""] ?? "Dicatat"}${caseRef}.`, link: caseLink };
  }
}

export function NotificationCenter({ userId, children }: { userId: string; children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seen = useRef(new Set<string>());
  const timers = useRef(new Map<string, number>());

  const dismiss = useCallback((id: string) => {
    setToasts(current => current.filter(toast => toast.id !== id));
    const timer = timers.current.get(id);
    if (timer) window.clearTimeout(timer);
    timers.current.delete(id);
  }, []);
  const notify = useCallback((input: ToastInput) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setToasts(current => [...current.slice(-2), { ...input, id }]);
    timers.current.set(id, window.setTimeout(() => dismiss(id), DISMISS_MS[input.tone]));
  }, [dismiss]);

  // Poll for server events while the tab is visible; a failed poll is retried on the next tick.
  useEffect(() => {
    let cancelled = false;
    let cursor = readCursor(userId);
    let timer = 0;
    const poll = async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const response = await getNotifications(cursor);
        if (cancelled) return;
        const fresh = response.items.filter(item => !seen.current.has(item.id));
        fresh.forEach(item => seen.current.add(item.id));
        // Several analyses finishing together are one message, not a stack of identical toasts.
        const finished = fresh.filter(item => item.kind === "run_finished" && item.status !== "failed");
        const rest = finished.length > 1 ? fresh.filter(item => !finished.includes(item)) : fresh;
        if (finished.length > 1)
          notify({ tone: "success", title: `${finished.length} analisis selesai`, message: "Hasilnya dapat dipilih di Beranda.", link: { to: "/workflow", label: "Lihat riwayat" } });
        // Oldest first, so the newest ends on top of the stack.
        rest.slice(0, MAX_POPUPS_PER_UPDATE).reverse().forEach(item => notify(describe(item)));
        if (rest.length > MAX_POPUPS_PER_UPDATE)
          notify({ tone: "info", title: `${rest.length - MAX_POPUPS_PER_UPDATE} pembaruan lainnya`, message: "Buka Antrean Tinjauan atau Data & Analisis untuk melihat semuanya." });
        cursor = response.next_since;
        writeCursor(userId, cursor);
      } catch { /* backend unavailable: try again later */ }
    };
    const schedule = () => { timer = window.setTimeout(async () => { await poll(); if (!cancelled) schedule(); }, POLL_MS); };
    const onVisible = () => { if (document.visibilityState === "visible") void poll(); };
    void poll();
    schedule();
    document.addEventListener("visibilitychange", onVisible);
    return () => { cancelled = true; window.clearTimeout(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [userId, notify]);
  useEffect(() => () => { timers.current.forEach(timer => window.clearTimeout(timer)); }, []);

  const value = useMemo(() => notify, [notify]);
  return (
    <NotifyContext.Provider value={value}>
      {children}
      <div className="toast-region" aria-live="polite" aria-label="Notifikasi">
        {toasts.map(toast => {
          const Icon = ICONS[toast.tone];
          return (
            <div key={toast.id} className={`toast toast-${toast.tone}`} role={toast.tone === "danger" ? "alert" : "status"} data-testid="toast">
              <Icon className="toast-icon" size={18} aria-hidden="true" />
              <div className="toast-body">
                <strong>{toast.title}</strong>
                {toast.message && <span>{toast.message}</span>}
                {toast.link && <Link className="toast-link" to={toast.link.to} onClick={() => dismiss(toast.id)}>{toast.link.label}</Link>}
              </div>
              <button className="toast-close" aria-label="Tutup notifikasi" onClick={() => dismiss(toast.id)}><X size={15} /></button>
            </div>
          );
        })}
      </div>
    </NotifyContext.Provider>
  );
}

