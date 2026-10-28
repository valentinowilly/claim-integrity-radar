import { useEffect, useRef, useState } from "react";
import { CalendarRange } from "lucide-react";
import { getVisits, type VisitsResponse } from "../api/client";
import { LANES, formatCount, formatDate, shortRef } from "./Display";
import { RunCandidateLink } from "./PersistedRunWorkspace";

const DAY = 86_400_000;
const SHORT = new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "short", timeZone: "UTC" });
const short = (value: string | null) => (value ? SHORT.format(new Date(`${value}T00:00:00Z`)) : "—");
const toDay = (value: string | null) => (value ? Math.round(Date.parse(`${value}T00:00:00Z`) / DAY) : NaN);

/** The participant's claims in the same file on one time axis: stays as bars, outpatient visits as dots. */
/** Open when a finding of this claim is about repeated visits; otherwise folded, as context only. */
export function VisitTimeline({ runId, caseId, relevant, onLoaded }: {
  runId: string; caseId: string; relevant: boolean; onLoaded?: (visits: number) => void;
}) {
  const [data, setData] = useState<VisitsResponse | null>(null);
  const reported = useRef(onLoaded);
  reported.current = onLoaded;
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    getVisits(runId, caseId, controller.signal)
      .then(fresh => { setData(fresh); reported.current?.(fresh.available ? fresh.visits.length : 0); })
      .catch(() => { if (!controller.signal.aborted) reported.current?.(0); });
    return () => controller.abort();
  }, [runId, caseId]);
  if (!data?.available || data.visits.length < 2) return null;

  const visits = data.visits.map(visit => {
    const start = toDay(visit.service_date);
    const end = Number.isNaN(toDay(visit.discharge_date)) ? start : toDay(visit.discharge_date);
    return { ...visit, start, end: Math.max(start, end) };
  }).filter(visit => !Number.isNaN(visit.start));
  if (visits.length < 2) return null;
  const first = Math.min(...visits.map(visit => visit.start));
  const last = Math.max(...visits.map(visit => visit.end));
  const span = Math.max(1, last - first);
  const position = (day: number) => `${((day - first) / span) * 100}%`;
  const inpatient = visits.filter(visit => visit.inpatient).length;

  return <details className="card run-case-reasons visit-timeline" aria-label="Riwayat kunjungan peserta" data-testid="visit-timeline"
    open={relevant || undefined}>
    <summary className="visit-timeline-summary">
      <span><CalendarRange size={16} className="head-icon" aria-hidden="true" />Kunjungan peserta yang sama
        <span className="visit-count">{formatCount(data.total_visits)} klaim</span></span>
      <small>{relevant ? "Bukti untuk temuan kunjungan berulang" : "Konteks: tidak terkait temuan klaim ini"}</small>
    </summary>
    <p className="fine-print visit-timeline-intro">{formatCount(data.total_visits)} klaim peserta ini di berkas yang sama ({formatCount(inpatient)} rawat inap). Jarak antarkunjungan membantu menilai tagihan ganda atau rawat inap yang dipecah.</p>
    <div className="timeline-axis" aria-hidden="true">
      <span>{formatDate(visits.find(visit => visit.start === first)?.service_date ?? null)}</span>
      <span>{span} hari</span>
      <span>{formatDate(new Date(last * DAY).toISOString().slice(0, 10))}</span>
    </div>
    <ol className="timeline-rows">
      {visits.map((visit, index) => {
        const previous = index > 0 ? visits[index - 1] : null;
        const gap = previous ? visit.start - previous.end : null;
        const label = <>
          <span className="timeline-ref">{visit.current ? "Klaim ini" : `Ref. ${shortRef(visit.case_id)}`}</span>
          <span className="timeline-meta">{short(visit.service_date)}{visit.inpatient ? ` – ${short(visit.discharge_date)}` : " · rawat jalan"}
            {visit.claim_group ? ` · ${visit.claim_group}` : ""}</span>
        </>;
        return <li key={visit.case_id} className={`timeline-row tl-${visit.lane}${visit.current ? " is-current" : ""}`}>
          <div className="timeline-label">
            {visit.current ? <div>{label}</div> : <RunCandidateLink runId={runId} caseId={visit.case_id} className="timeline-link">{label}</RunCandidateLink>}
          </div>
          <div className="timeline-track">
            {visit.inpatient
              ? <span className="timeline-bar" style={{ left: position(visit.start), width: `max(10px, ${((visit.end - visit.start) / span) * 100}%)` }}
                title={`${LANES[visit.lane].name}: rawat inap ${visit.end - visit.start} hari`} />
              : <span className="timeline-dot" style={{ left: position(visit.start) }} title={`${LANES[visit.lane].name}: rawat jalan`} />}
          </div>
          <div className="timeline-gap">{gap === null ? "" : gap < 0 ? "tumpang tindih" : gap === 0 ? "hari yang sama" : `+${gap} hari`}
            {gap !== null && previous?.inpatient && visit.inpatient && gap >= 0 && gap <= 7 && <span className="timeline-flag">masuk lagi {gap} hari setelah pulang</span>}</div>
        </li>;
      })}
    </ol>
    <div className="timeline-legend" aria-hidden="true">
      <span><i className="timeline-bar sample" />Rawat inap</span><span><i className="timeline-dot sample" />Rawat jalan</span>
      {(["red", "yellow", "green"] as const).map(lane => <span key={lane} className={`tl-${lane}`}><i className="timeline-dot sample" />{LANES[lane].name}</span>)}
    </div>
  </details>;
}
