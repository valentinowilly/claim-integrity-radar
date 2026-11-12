import { useEffect, useState } from "react";
import { ChevronDown, TriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { getRunMismatches, type RunMismatches } from "../api/client";
import { formatDocumentValue } from "./ClaimDocuments";
import { formatCount, shortRef } from "./Display";

/**
 * Claims whose facility documents disagree with the claim data. Shown above the queue because such a claim may
 * not be in the queue at all: a mismatch is a data-integrity matter and does not change a claim's risk lane.
 */
export function DocumentMismatches({ runId }: { runId: string }) {
  const [data, setData] = useState<RunMismatches | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    getRunMismatches(runId, controller.signal).then(setData).catch(() => undefined);
    return () => controller.abort();
  }, [runId]);
  if (!data || !data.claim_count) return null;
  return <section className="mismatch-banner" aria-label="Berkas tidak cocok dengan data klaim" data-testid="mismatch-banner">
    <button type="button" className="mismatch-banner-head" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      <TriangleAlert size={16} aria-hidden="true" />
      <span><strong>{formatCount(data.claim_count)} klaim memiliki berkas yang tidak cocok dengan data klaim.</strong>{" "}
        Sebagian bisa berada di luar antrean karena tidak ditandai pemeriksaan lain.</span>
      <ChevronDown size={16} aria-hidden="true" className={open ? "is-open" : undefined} />
    </button>
    {open && <ul className="mismatch-banner-list">{data.claims.map(claim => <li key={claim.case_id}>
      <Link to={`/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(claim.case_id)}#berkas-klaim`} data-testid="mismatch-claim">
        Ref. {shortRef(claim.case_id)}</Link>
      <span>{claim.mismatches.map(item => `${item.label}: data ${formatDocumentValue(item.field, item.data_value)}, berkas ${formatDocumentValue(item.field, item.document_value)} (${item.doc_type_label}, hal. ${item.page})`).join("; ")}</span>
    </li>)}</ul>}
  </section>;
}
