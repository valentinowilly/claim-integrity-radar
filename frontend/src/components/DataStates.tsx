import { AlertTriangle, LoaderCircle, RefreshCw, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import type { DataSource } from "../api/client";

export function PageHeading({ eyebrow, title, description, action }: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow"><span className="eyebrow-line" />{eyebrow}</div>
        <h1>{title}</h1>
        <p className="page-lede">{description}</p>
      </div>
      {action && <div className="heading-actions">{action}</div>}
    </div>
  );
}

export function SourceBadge({ source }: { source: DataSource }) {
  if (source.label === "synthetic_demo") {
    return <span className="source-badge source-synthetic"><span />Synthetic Demo Data</span>;
  }
  if (source.kind === "none") return <span className="source-badge source-muted">Sumber belum tersedia</span>;
  return <span className="source-badge source-muted">{source.label ?? "Sumber data"}</span>;
}

export function LoadingState({ label = "Memuat data dari API…" }: { label?: string }) {
  return <div className="api-state api-loading" role="status"><LoaderCircle size={19} className="spin" /><span>{label}</span></div>;
}

export function ErrorState({ message, httpStatus, onRetry }: {
  message: string;
  httpStatus: number | null;
  onRetry: () => void;
}) {
  return (
    <div className="api-state api-error" role="alert">
      <span className="state-icon"><AlertTriangle size={18} /></span>
      <div className="api-state-copy"><strong>Data gagal dimuat</strong><span>{message}</span>
        {httpStatus !== null && <small>HTTP {httpStatus}</small>}
      </div>
      <button className="button button-secondary" onClick={onRetry}><RefreshCw size={14} />Coba lagi</button>
    </div>
  );
}

export function EmptyState({ title, message }: { title: string; message: string }) {
  return (
    <div className="empty-data-state">
      <div className="empty-state-icon"><ShieldCheck size={20} /></div>
      <strong>{title}</strong><p>{message}</p>
    </div>
  );
}

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : new Intl.NumberFormat("id-ID").format(value);
}

export function indicatorLabel(code: string): string {
  if (code === "repeat_billing_candidate") return "Repeat billing candidate";
  if (code === "similar_claim_pattern_candidate") return "Similar claim-pattern candidate";
  if (code === "near_duplicate_claim_candidate") return "Near-duplicate claim candidate";
  if (code === "synthetic_capacity_candidate") return "Synthetic service capacity candidate";
  if (code === "temporal_pattern_candidate") return "Temporal pattern candidate";
  if (code === "supporting_evidence_completeness_candidate") return "Supporting evidence completeness candidate";
  return code.replace(/_/g, " ");
}
