import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CheckCircle2, Eye, TriangleAlert, X } from "lucide-react";
import { formatCount } from "./Display";

/**
 * A first look at a chosen file, read in this browser only (nothing is sent): whether it looks like claim data,
 * and what is inside. The server still checks every file when the package is processed; this catches the obvious
 * mistakes (a spreadsheet without claim columns, a JSON that is not an RME bundle, a picture named .pdf) earlier.
 */
export interface FileCheck {
  ok: boolean;
  label: string;
  csv?: { header: string[]; rows: string[][]; rowCount: number };
  fhir?: { types: Array<[string, number]> };
}

const TEXT_LIMIT = 60 * 1024 * 1024;

/** Split one CSV line, honouring double quotes. */
function splitCsv(line: string): string[] {
  const cells: string[] = [];
  let cell = "", quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"') { if (quoted && line[index + 1] === '"') { cell += '"'; index += 1; } else quoted = !quoted; }
    else if (char === "," && !quoted) { cells.push(cell); cell = ""; }
    else cell += char;
  }
  cells.push(cell);
  return cells.map(value => value.trim());
}

export async function inspectFile(file: File): Promise<FileCheck> {
  const name = file.name.toLowerCase();
  const head = new Uint8Array(await file.slice(0, 8).arrayBuffer());
  const startsWith = (text: string) => text.split("").every((char, index) => head[index] === char.charCodeAt(0));
  if (name.endsWith(".pdf")) return startsWith("%PDF") ? { ok: true, label: "PDF" } : { ok: false, label: "Bukan PDF (mungkin gambar)" };
  if (name.endsWith(".zip")) return startsWith("PK") ? { ok: true, label: "ZIP, isinya dibaca saat diproses" } : { ok: false, label: "ZIP rusak" };
  if (name.endsWith(".csv")) {
    const text = (await file.slice(0, Math.min(file.size, TEXT_LIMIT)).text()).replace(/^﻿/, "");
    const lines = text.split(/\r?\n/).filter(line => line.trim());
    const header = splitCsv(lines[0] ?? "");
    const rowCount = Math.max(0, lines.length - 1);
    const csv = { header, rows: lines.slice(1, 6).map(splitCsv), rowCount };
    return header.includes("PSTV01") && header.includes("FKL02")
      ? { ok: true, label: `Data klaim · ${formatCount(rowCount)} baris`, csv }
      : { ok: false, label: "CSV tanpa kolom klaim (PSTV01, FKL02)", csv };
  }
  if (name.endsWith(".json")) {
    if (file.size > TEXT_LIMIT) return { ok: true, label: "JSON besar, diperiksa saat diproses" };
    try {
      const data = JSON.parse(await file.text()) as { resourceType?: string; entry?: Array<{ resource?: { resourceType?: string } }> };
      if (data.resourceType !== "Bundle") return { ok: false, label: data.resourceType ? `FHIR ${data.resourceType}, bukan Bundle` : "JSON ini bukan data RME" };
      const counts = new Map<string, number>();
      for (const entry of data.entry ?? []) {
        const type = entry.resource?.resourceType ?? "lainnya";
        counts.set(type, (counts.get(type) ?? 0) + 1);
      }
      const visits = counts.get("Encounter") ?? 0;
      const fhir = { types: [...counts.entries()].sort((a, b) => b[1] - a[1]) };
      return visits ? { ok: true, label: `RME · ${formatCount(visits)} kunjungan`, fhir } : { ok: false, label: "Bundle FHIR tanpa kunjungan", fhir };
    } catch {
      return { ok: false, label: "JSON rusak" };
    }
  }
  return { ok: false, label: "Jenis berkas tidak didukung" };
}

/** Checks of the chosen files, computed once per file (the first 300; more are checked by the server only). */
export function useFileChecks(files: File[], keyOf: (file: File) => string) {
  const [checks, setChecks] = useState<Record<string, FileCheck>>({});
  const pending = useRef(new Set<string>());
  useEffect(() => {
    for (const file of files.slice(0, 300)) {
      const key = keyOf(file);
      if (checks[key] || pending.current.has(key)) continue;
      pending.current.add(key);
      void inspectFile(file).then(check => setChecks(current => ({ ...current, [key]: check })))
        .finally(() => pending.current.delete(key));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files]);
  return checks;
}

/** The little status next to a chosen file: a tick and what it is, or a warning and why. */
export function FileCheckBadge({ check }: { check?: FileCheck }) {
  if (!check) return <span className="file-check is-pending">Memeriksa…</span>;
  return <span className={`file-check${check.ok ? " is-ok" : " is-bad"}`}>
    {check.ok ? <CheckCircle2 size={13} aria-hidden="true" /> : <TriangleAlert size={13} aria-hidden="true" />}{check.label}</span>;
}

export function PreviewButton({ onClick, name }: { onClick: () => void; name: string }) {
  return <button type="button" className="picked-preview" onClick={onClick} aria-label={`Lihat isi ${name}`}><Eye size={15} aria-hidden="true" />Lihat</button>;
}

/** A window with the file's content: the first rows of a CSV, the resources of an RME bundle, or the PDF itself. */
export function FilePreviewDialog({ file, check, onClose }: { file: File; check?: FileCheck; onClose: () => void }) {
  const isPdf = file.name.toLowerCase().endsWith(".pdf") && check?.ok;
  const url = useMemo(() => (isPdf ? URL.createObjectURL(file) : null), [file, isPdf]);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const columns = check?.csv?.header.slice(0, 8) ?? [];
  return createPortal(<div className="palette-scrim" onMouseDown={onClose}>
    <div className="breakdown file-preview" role="dialog" aria-modal="true" aria-labelledby="file-preview-title" onMouseDown={event => event.stopPropagation()}>
      <div className="breakdown-head">
        <div><span className="breakdown-kicker"><Eye size={15} aria-hidden="true" />Pratinjau, belum diunggah</span>
          <h2 id="file-preview-title">{file.name}</h2></div>
        <button ref={closeRef} type="button" className="icon-close" onClick={onClose} aria-label="Tutup pratinjau"><X size={16} /></button>
      </div>
      <FileCheckBadge check={check} />
      {check?.csv && <>
        <p className="fine-print">{formatCount(check.csv.rowCount)} baris, {formatCount(check.csv.header.length)} kolom. Lima baris pertama
          {check.csv.header.length > 8 ? `, 8 kolom pertama dari ${formatCount(check.csv.header.length)}` : ""}:</p>
        <div className="table-scroll"><table className="data-table file-preview-table">
          <thead><tr>{columns.map(column => <th key={column}>{column}</th>)}</tr></thead>
          <tbody>{check.csv.rows.map((row, index) => <tr key={index}>{columns.map((_column, cell) => <td key={cell}>{row[cell] || "kosong"}</td>)}</tr>)}</tbody>
        </table></div>
      </>}
      {check?.fhir && <ul className="file-preview-types">{check.fhir.types.map(([type, count]) =>
        <li key={type}><b>{formatCount(count)}</b>{type}</li>)}</ul>}
      {url && <>
        <iframe className="file-preview-pdf" src={`${url}#view=FitH`} title={`Isi ${file.name}`} />
        <a className="fine-print" href={url} target="_blank" rel="noopener noreferrer">PDF tidak tampil? Buka di tab baru</a>
      </>}
      {!check?.csv && !check?.fhir && !url && <p className="fine-print">Isi berkas ini tidak dapat ditampilkan di sini. {check?.ok ? "Berkas tetap bisa diunggah." : "Berkas akan diabaikan saat diproses."}</p>}
    </div>
  </div>, document.body);
}
