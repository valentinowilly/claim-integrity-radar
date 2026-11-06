import { useCallback, useEffect, useState } from "react";
import { HelpCircle, Lightbulb, MessageSquareHeart, ThumbsDown, ThumbsUp, Users } from "lucide-react";
import { Link } from "react-router-dom";
import { ApiClientError, getFeedbackSummary, type FeedbackMessage, type FeedbackSummary } from "../api/client";
import { EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import { displayRole, formatCount, formatDateTime, shortRef } from "../components/Display";
import { formatPercent } from "../components/RiskMap";

const PERIODS = [7, 30, 90] as const;

/** How helpful users find the system's explanations, per role, and the questions and suggestions they sent. */
export default function FeedbackPage() {
  const [days, setDays] = useState<number>(30);
  const [state, setState] = useState<{ status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: FeedbackSummary }>({ status: "loading" });
  const load = useCallback((signal?: AbortSignal) => {
    setState({ status: "loading" });
    getFeedbackSummary(days, signal).then(data => setState({ status: "ready", data })).catch(reason => {
      if (signal?.aborted) return;
      setState({ status: "error", message: reason instanceof ApiClientError ? reason.message : "Masukan pengguna tidak dapat dimuat." });
    });
  }, [days]);
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  return <>
    <header className="page-head">
      <div><h1>Masukan Pengguna</h1><p>Seberapa membantu penjelasan sistem menurut petugas, serta pertanyaan dan saran dari halaman Bantuan.</p></div>
      <div className="page-head-actions">
        <div className="segmented-pill" role="group" aria-label="Periode">
          {PERIODS.map(value => <button key={value} type="button" aria-pressed={days === value} onClick={() => setDays(value)}>{value} hari</button>)}
        </div>
      </div>
    </header>
    {state.status === "loading" ? <div className="card"><LoadingState label="Memuat masukan pengguna…" /></div>
      : state.status === "error" ? <div className="card"><ErrorState message={state.message} httpStatus={null} onRetry={() => load()} /></div>
      : <FeedbackWorkspace data={state.data} />}
  </>;
}

function FeedbackWorkspace({ data }: { data: FeedbackSummary }) {
  if (!data.votes && !data.recent_messages.length) return <div className="card"><EmptyState title={`Belum ada masukan dalam ${data.period_days} hari terakhir`}
    message="Masukan muncul setelah petugas menilai penjelasan di halaman klaim, atau mengirim pertanyaan dan saran dari halaman Bantuan." /></div>;
  const share = data.helpful_share;
  return <>
    <div className="stat-tiles" data-testid="feedback-summary">
      <div className="card stat-tile highlight">
        <span className="stat-tile-label"><MessageSquareHeart size={16} aria-hidden="true" />Penjelasan dinilai membantu</span>
        <strong>{share === null ? "—" : formatPercent(share)}</strong>
        <small>{share === null ? "Belum ada penilaian." : `${formatCount(data.helpful)} dari ${formatCount(data.votes)} penilaian`}</small>
      </div>
      <div className="card stat-tile">
        <span className="stat-tile-label"><Users size={16} aria-hidden="true" />Petugas yang memberi masukan</span>
        <strong>{formatCount(data.people)}</strong><small>dalam {data.period_days} hari terakhir</small>
      </div>
      <div className="card stat-tile">
        <span className="stat-tile-label"><HelpCircle size={16} aria-hidden="true" />Pertanyaan</span>
        <strong>{formatCount(data.questions)}</strong><small>dari halaman Bantuan</small>
      </div>
      <div className="card stat-tile">
        <span className="stat-tile-label"><Lightbulb size={16} aria-hidden="true" />Saran</span>
        <strong>{formatCount(data.suggestions)}</strong><small>dari halaman Bantuan</small>
      </div>
    </div>

    {data.by_role.length > 0 && <section className="card" aria-label="Penilaian per peran">
      <div className="card-head"><div><h2>Penilaian per peran</h2>
        <p>Penilaian “apakah penjelasan klaim ini membantu?” dari halaman klaim. Satu petugas memberi satu penilaian per klaim.</p></div></div>
      <div className="table-scroll"><table className="data-table" aria-label="Penilaian per peran">
        <thead><tr><th>Peran</th><th className="numeric">Penilaian</th><th className="numeric">Membantu</th><th className="numeric">Kurang membantu</th><th>Persentase membantu</th></tr></thead>
        <tbody>{data.by_role.map(row => <tr key={row.role}>
          <td>{displayRole(row.role)}</td>
          <td className="numeric">{formatCount(row.votes)}</td>
          <td className="numeric">{formatCount(row.helpful)}</td>
          <td className="numeric">{formatCount(row.votes - row.helpful)}</td>
          <td><span className="share-bar" aria-hidden="true"><span style={{ width: `${(row.helpful / row.votes) * 100}%` }} /></span>
            <span className="share-value">{formatPercent(row.helpful / row.votes)}</span></td>
        </tr>)}</tbody>
      </table></div>
    </section>}

    <section className="card" aria-label="Pesan terbaru">
      <div className="card-head"><div><h2>Pesan terbaru</h2>
        <p>Pertanyaan, saran, dan komentar pada penilaian klaim. Gunakan untuk memperbaiki panduan dan penjelasan sistem.</p></div></div>
      {data.recent_messages.length === 0 ? <p className="fine-print">Belum ada pesan tertulis pada periode ini.</p>
        : <ul className="feedback-messages">{data.recent_messages.map(item => <MessageItem key={item.feedback_id} item={item} />)}</ul>}
    </section>
  </>;
}

function MessageItem({ item }: { item: FeedbackMessage }) {
  const kind = item.context === "help_question" ? "Pertanyaan" : item.context === "general" ? "Saran" : "Penilaian klaim";
  return <li className="feedback-message">
    <div className="feedback-message-head">
      <span className={`status-pill ${item.context === "claim_explanation" ? (item.helpful ? "tone-good" : "tone-warn") : "tone-neutral"}`}>
        {item.context === "claim_explanation" && (item.helpful ? <ThumbsUp size={12} aria-hidden="true" /> : <ThumbsDown size={12} aria-hidden="true" />)}
        {item.context === "claim_explanation" ? (item.helpful ? "Membantu" : "Kurang membantu") : kind}
      </span>
      <strong>{item.author}</strong><span className="fine-print">{displayRole(item.role)} · {formatDateTime(item.updated_at)}</span>
      {item.run_id && item.case_id && <Link className="text-link feedback-claim-link"
        to={`/runs/${encodeURIComponent(item.run_id)}/cases/${encodeURIComponent(item.case_id)}`}>Klaim {shortRef(item.case_id)}</Link>}
    </div>
    <p>{item.message}</p>
  </li>;
}
