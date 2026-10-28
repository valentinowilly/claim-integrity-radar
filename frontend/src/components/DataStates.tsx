import { AlertTriangle, LoaderCircle, RefreshCw, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import type { DataSource } from "../api/client";
import { formatCount } from "./Display";

export function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && (
          <div className="eyebrow">
            <span className="eyebrow-line" />
            {eyebrow}
          </div>
        )}
        <h1>{title}</h1>
        <p className="page-lede">{description}</p>
      </div>
      {action && <div className="heading-actions">{action}</div>}
    </div>
  );
}

export function SourceBadge({ source }: { source: DataSource }) {
  if (source.kind === "synthetic" || source.label === "synthetic_demo" || source.label === "synthetic_data_batch") {
    return (
      <span className="source-badge source-synthetic">
        <span />
        Berkas unggahan
      </span>
    );
  }
  if (source.label === "bpjs_sample") return <span className="source-badge source-muted">Data klaim FKRTL</span>;
  if (source.kind === "none") return <span className="source-badge source-muted">Belum ada sumber data</span>;
  return <span className="source-badge source-muted">{source.label ?? "Sumber data"}</span>;
}

export function LoadingState({ label = "Memuat data…" }: { label?: string }) {
  return (
    <div className="api-state api-loading" role="status">
      <span className="skeleton-lines" aria-hidden="true"><i /><i /><i /></span>
      <span className="loading-label"><LoaderCircle size={15} className="spin" />{label}</span>
    </div>
  );
}

export function ErrorState({
  message,
  httpStatus,
  onRetry,
}: {
  message: string;
  httpStatus: number | null;
  onRetry: () => void;
}) {
  return (
    <div className="api-state api-error" role="alert">
      <span className="state-icon">
        <AlertTriangle size={18} />
      </span>
      <div className="api-state-copy">
        <strong>Data tidak dapat dimuat</strong>
        <span>{message}</span>
        {httpStatus !== null && <small>HTTP {httpStatus}</small>}
      </div>
      <button className="button button-secondary" onClick={onRetry}>
        <RefreshCw size={14} />
        Coba lagi
      </button>
    </div>
  );
}

export function EmptyState({ title, message }: { title: string; message: string }) {
  return (
    <div className="empty-data-state">
      <div className="empty-state-icon">
        <ShieldCheck size={20} />
      </div>
      <strong>{title}</strong>
      <p>{message}</p>
    </div>
  );
}

export function formatNumber(value: number | null | undefined): string {
  return formatCount(value);
}

export { indicatorLabel } from "./Display";
