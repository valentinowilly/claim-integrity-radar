import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight, CheckCircle2, Clock3, CircleSlash, Database, Download, FileJson, FileScan, FileText, Files, Info, Loader2, Package, Plus, ScanText,
  TriangleAlert, X, XCircle,
} from "lucide-react";
import { Link } from "react-router-dom";
import {
  ApiClientError, addIntakeFile, cancelIntakePackage, createIntakePackage, getIntakePackage, getIntakePackages, getIntakeSamples,
  getIntakeStatus, intakeSampleUrl, processIntakePackage, type IntakeFailure, type IntakePackage, type IntakeSample, type IntakeStatus,
  type IntakeSummary,
} from "../api/client";
import { formatDocumentValue } from "./ClaimDocuments";
import { formatCount, formatDateTime, shortRef } from "./Display";
import { Term } from "./Term";
import { FileCheckBadge, FilePreviewDialog, PreviewButton, useFileChecks } from "./FilePreview";

const ACCEPT = ".csv,.json,.pdf,.zip,text/csv,application/json,application/pdf,application/zip";
/** Why a package failed, and what to do next. */
const FAILURES: Record<string, string> = {
  NO_CLAIM_DATA: "Paket tidak memuat data klaim yang dapat dibaca. Tambahkan CSV E-Klaim, JSON RME (Bundle FHIR), atau PDF berkas klaim yang mencantumkan nomor kunjungan, lalu unggah ulang.",
  PACKAGE_TOO_LARGE: "Ukuran atau jumlah berkas melewati batas satu paket. Bagi menjadi beberapa paket, lalu unggah satu per satu.",
  CSV_INVALID_ENCODING: "Berkas CSV bukan teks UTF-8. Simpan ulang dari Excel sebagai “CSV UTF-8”, lalu unggah ulang.",
  BATCH_IMPORT_FAILED: "Data klaim gabungan tidak dapat disimpan. Coba lagi; bila berulang, hubungi administrator.",
  ANALYSIS_RUN_FAILED: "Data tersimpan, tetapi analisis gagal dijalankan. Jalankan analisis ulang dari daftar data tersimpan di bawah.",
  PROCESS_INTERRUPTED: "Pemrosesan terhenti karena layanan dimulai ulang. Unggah ulang paketnya.",
  PROCESS_FAILED: "Pemrosesan gagal. Coba lagi; bila berulang, hubungi administrator.",
  "CLAIM_DATA_REJECTED:real_participant_not_allowed": "Ditolak demi perlindungan data: ada nomor peserta asli (belum disamarkan, harus diawali SYN). Samarkan nomor peserta di berkas itu, lalu unggah ulang.",
  "CLAIM_DATA_REJECTED:post_verification_amount_forbidden": "Ditolak: berkas memuat kolom biaya setelah verifikasi (FKL48). Hapus kolom itu, lalu unggah ulang.",
  "CLAIM_DATA_REJECTED:duplicate_visit": "Ditolak: ada nomor kunjungan yang tercatat dua kali. Perbaiki baris gandanya, lalu unggah ulang.",
  "CLAIM_DATA_REJECTED:missing_required_value": "Ditolak: ada klaim tanpa nomor peserta, nomor kunjungan, atau tanggal masuk. Lengkapi, lalu unggah ulang.",
};
/** Why one file was not used. */
const REASONS: Record<string, string> = {
  NO_VISIT_NUMBER: "nomor kunjungan tidak terbaca", CLAIM_DATA_INCOMPLETE: "data klaim di berkas tidak lengkap (tanggal masuk tidak ada)",
  NOT_A_CLAIM_DOCUMENT: "bukan berkas klaim (tidak ada data pasien atau kunjungan)",
  PARTICIPANT_MISMATCH: "nomor kunjungan cocok dengan klaim lain, tetapi nomor pesertanya berbeda; tidak ditautkan agar tidak salah orang",
  SINGLE_DOCUMENT_CLAIM: "klaim hanya muncul di satu berkas ini; perlu minimal dua berkas dengan identitas sama, atau datanya di CSV/JSON",
  PDF_UNREADABLE: "berkas rusak", PDF_ENCRYPTED: "berkas terkunci sandi", PDF_EMPTY: "berkas kosong",
  PDF_TOO_MANY_PAGES: "terlalu banyak halaman", PDF_TOO_LARGE: "ukuran terlalu besar",
  NOT_A_PDF: "bernama .pdf tetapi isinya bukan PDF (mungkin gambar)", EMPTY_FILE: "berkas kosong",
  JSON_NOT_FHIR: "JSON ini bukan data RME (bukan FHIR)", FHIR_INVALID_JSON: "JSON tidak dapat dibaca (format rusak)",
  FHIR_NOT_A_BUNDLE: "data FHIR, tetapi bukan Bundle (kumpulan data kunjungan)", FHIR_NO_ENCOUNTERS: "Bundle FHIR tanpa data kunjungan",
  CSV_NOT_CLAIM_DATA: "CSV tanpa kolom klaim BPJS (PSTV01, FKL02, ...)", CSV_INVALID_ENCODING: "CSV bukan teks UTF-8",
  ZIP_UNREADABLE: "ZIP tidak dapat dibuka", UNSUPPORTED_FILE: "jenis berkas tidak didukung",
};

function failureText(code: string | null): string {
  if (!code) return "Pemrosesan gagal. Coba lagi.";
  return FAILURES[code] ?? (code.startsWith("CLAIM_DATA_REJECTED") ? "Data klaim ditolak saat pemeriksaan isi berkas. Periksa berkas yang disebut di bawah, lalu unggah ulang." : "Pemrosesan gagal. Coba lagi.");
}

type Kind = "csv" | "fhir" | "pdf" | "zip" | "lain";
const KIND_LABEL: Record<Kind, string> = { csv: "CSV", fhir: "JSON", pdf: "PDF", zip: "ZIP", lain: "Tidak dikenal" };

function fileKind(file: File): Kind {
  const name = file.name.toLowerCase();
  return name.endsWith(".csv") ? "csv" : name.endsWith(".json") ? "fhir" : name.endsWith(".pdf") ? "pdf" : name.endsWith(".zip") ? "zip" : "lain";
}

function fileSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toLocaleString("id-ID", { maximumFractionDigits: 1 })} MB`
    : `${Math.max(1, Math.round(bytes / 1024)).toLocaleString("id-ID")} KB`;
}

/** What each example contains, as short labels (the full description stays in the tooltip). */
const SAMPLE_META: Record<string, { icon: "package" | "csv"; chips: string[]; time?: string }> = {
  "paket-ringkas": { icon: "package", chips: ["CSV", "JSON RME", "24 PDF"], time: "± 1 menit" },
  "paket-lengkap": { icon: "package", chips: ["CSV", "JSON RME", "240 PDF"], time: "± 5 menit" },
  "klaim-csv": { icon: "csv", chips: ["29.628 klaim", "40 RS", "CSV"] },
};

const fileKey = (file: File) => `${file.name}\u0000${file.size}\u0000${file.lastModified}`;

/** Upload a claim package (claim data as CSV and/or RME JSON, plus facility PDFs), watch it being read, see the result. */
export function PackageUpload({ canWrite, onDone }: { canWrite: boolean; onDone: () => void }) {
  const [status, setStatus] = useState<IntakeStatus | null>(null);
  const [samples, setSamples] = useState<IntakeSample[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [inputKey, setInputKey] = useState(0);
  const [uploading, setUploading] = useState<{ done: number; total: number; cancelling: boolean } | null>(null);
  const [current, setCurrent] = useState<IntakePackage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState<File | null>(null);
  const checks = useFileChecks(files, fileKey);
  const flagged = files.filter(file => checks[fileKey(file)] && !checks[fileKey(file)].ok).length;
  const cancelRequested = useRef(false);
  const done = useRef(onDone);
  done.current = onDone;

  useEffect(() => {
    const controller = new AbortController();
    getIntakeStatus(controller.signal).then(setStatus).catch(() => undefined);
    getIntakeSamples(controller.signal).then(response => setSamples(response.items)).catch(() => undefined);
    // A package still being read (e.g. after a page reload) keeps showing its progress; otherwise the latest result.
    getIntakePackages(controller.signal).then(response => {
      const latest = response.items.find(item => item.status === "processing") ?? response.items.find(item => item.status === "ready");
      if (latest) setCurrent(latest);
    }).catch(() => undefined);
    return () => controller.abort();
  }, []);

  const packageId = current?.package_id;
  const processing = current?.status === "processing";
  useEffect(() => {
    if (!packageId || !processing) return;
    let active = true;
    const timer = window.setInterval(() => {
      getIntakePackage(packageId).then(response => {
        if (!active) return;
        setCurrent(response.package);
        if (response.package.status !== "processing") done.current();
      }).catch(() => undefined);
    }, 1500);
    return () => { active = false; window.clearInterval(timer); };
  }, [packageId, processing]);

  const addFiles = (picked: File[]) => {
    setFiles(existing => {
      const known = new Set(existing.map(fileKey));
      return [...existing, ...picked.filter(file => !known.has(fileKey(file)))];
    });
    setInputKey(key => key + 1);
  };

  const submit = useCallback(async () => {
    if (!files.length) return;
    setError(null);
    setNotice(null);
    cancelRequested.current = false;
    setUploading({ done: 0, total: files.length, cancelling: false });
    let pkg: IntakePackage | null = null;
    try {
      const label = name.trim() || `Paket klaim ${new Date().toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" })}`;
      pkg = (await createIntakePackage(label)).package;
      for (let index = 0; index < files.length; index += 1) {
        if (cancelRequested.current) break;
        pkg = (await addIntakeFile(pkg.package_id, files[index])).package;
        setUploading(state => state && { ...state, done: index + 1 });
      }
      if (cancelRequested.current) {
        await cancelIntakePackage(pkg.package_id);
        setNotice("Unggahan dibatalkan. Berkas yang sudah terkirim dihapus dari server; daftar berkas Anda tetap ada di sini.");
        return;
      }
      pkg = (await processIntakePackage(pkg.package_id)).package;
      setCurrent(pkg);
      setFiles([]);
      setName("");
    } catch (problem) {
      if (problem instanceof ApiClientError && problem.status === 401) {
        setError("Sesi Anda berakhir saat mengunggah. Berkas yang sudah terkirim dibersihkan otomatis dalam 24 jam. Masuk lagi, lalu unggah ulang paketnya; daftar berkas Anda tetap ada di sini.");
      } else {
        setError(problem instanceof ApiClientError ? `${problem.message} Daftar berkas Anda tetap ada; coba unggah lagi.` : "Paket tidak dapat diunggah. Periksa koneksi, lalu coba lagi.");
        if (pkg && pkg.status === "uploading") void cancelIntakePackage(pkg.package_id).catch(() => undefined);
      }
    } finally {
      setUploading(null);
    }
  }, [files, name]);

  const cancelResult = async (pkg: IntakePackage) => {
    if (!window.confirm(`Batalkan paket “${pkg.name}”?\n\nHasil analisisnya dipindahkan ke Arsip dan berkas PDF-nya dilepas dari klaim. Keputusan tinjauan yang sudah tercatat tetap tersimpan.`)) return;
    setError(null);
    try {
      setCurrent((await cancelIntakePackage(pkg.package_id)).package);
      setNotice(`Paket “${pkg.name}” dibatalkan. Hasil analisisnya ada di Arsip pada Riwayat analisis.`);
      done.current();
    } catch (problem) {
      setError(problem instanceof ApiClientError ? problem.message : "Paket tidak dapat dibatalkan. Coba lagi.");
    }
  };

  const busy = Boolean(uploading) || processing;
  return <section className="card package-upload" aria-label="Unggah data klaim" id="unggah" data-testid="package-upload">
    <div className="card-head">
      <div><h2><Files size={17} className="head-icon" aria-hidden="true" />Unggah data klaim</h2>
        <p>Satu paket boleh berisi data klaim dan berkas faskes sekaligus, atau satu berkas CSV saja. Sistem membaca semuanya, menyatukannya per klaim, lalu menganalisis.</p></div>
    </div>
    <ul className="source-strip" aria-label="Sumber yang didukung">
      <li className="is-csv"><Database size={16} aria-hidden="true" /><span><strong>Data E-Klaim</strong><small>CSV, format kolom klaim FKRTL</small></span></li>
      <li className="is-json"><FileJson size={16} aria-hidden="true" /><span><strong>RME / SATUSEHAT</strong><small>JSON, Bundle HL7 FHIR</small></span></li>
      <li className="is-pdf"><FileText size={16} aria-hidden="true" /><span><strong>Berkas faskes (PDF digital)</strong><small>Teks dibaca langsung</small></span></li>
      <li className="is-scan"><ScanText size={16} aria-hidden="true" /><span><strong>Berkas faskes (PDF hasil pindai)</strong><small>Dibaca dengan OCR</small></span></li>
    </ul>
    {canWrite ? <div className="package-form">
      <label className={`upload-drop package-drop${dragging ? " is-dragging" : ""}`}
        onDragOver={event => { event.preventDefault(); if (!busy) setDragging(true); }} onDragLeave={() => setDragging(false)}
        onDrop={event => { event.preventDefault(); setDragging(false); if (!busy) addFiles(Array.from(event.dataTransfer.files)); }}>
        <span className="drop-art" aria-hidden="true"><i className="is-csv">CSV</i><i className="is-json">JSON</i><i className="is-pdf">PDF</i></span>
        <span><strong>{dragging ? "Lepaskan berkas di sini" : files.length ? "Tambah berkas lain" : "Seret berkas ke sini, atau klik untuk memilih"}</strong>
          <small>Boleh banyak sekaligus · CSV, JSON, PDF, atau ZIP</small></span>
        {files.length ? <Plus size={22} aria-hidden="true" /> : <Files size={22} aria-hidden="true" />}
        <input key={inputKey} type="file" multiple accept={ACCEPT} aria-label="Berkas paket klaim" disabled={busy}
          onChange={event => addFiles(Array.from(event.target.files ?? []))} />
      </label>
      {files.length > 0 && <div className="picked" data-testid="picked-files">
        <div className="picked-head"><strong>{formatCount(files.length)} berkas dipilih</strong>
          <span>{fileSize(files.reduce((sum, file) => sum + file.size, 0))}</span>
          {!busy && <button type="button" className="picked-clear" onClick={() => setFiles([])}>Kosongkan</button>}</div>
        <ul>{files.slice(0, 50).map(file => <li key={fileKey(file)} className={fileKind(file) === "lain" ? "is-unknown" : undefined}>
          <span className="picked-kind">{KIND_LABEL[fileKind(file)]}</span>
          <span className="picked-name" title={file.name}>{file.name}</span>
          <FileCheckBadge check={checks[fileKey(file)]} />
          <span className="picked-size">{fileSize(file.size)}</span>
          <PreviewButton name={file.name} onClick={() => setPreview(file)} />
          {!busy && <button type="button" className="picked-remove" aria-label={`Hapus ${file.name} dari daftar`}
            onClick={() => setFiles(list => list.filter(item => fileKey(item) !== fileKey(file)))}><X size={14} /></button>}
        </li>)}</ul>
        {files.length > 50 && <p className="fine-print">dan {formatCount(files.length - 50)} berkas lain.</p>}
        {flagged > 0 && <p className="picked-warn" role="status"><TriangleAlert size={14} aria-hidden="true" />
          {formatCount(flagged)} berkas tampaknya bukan data klaim dan akan diabaikan saat diproses. Tekan "Lihat" untuk memeriksa isinya, atau hapus dari daftar.</p>}
      </div>}
      <div className="package-form-row">
        <label className="upload-name">
          <span>Nama paket <small>(opsional)</small></span>
          <input value={name} maxLength={60} placeholder="mis. Klaim RS September, minggu 1" onChange={event => setName(event.target.value)} disabled={busy} />
        </label>
        <button className="button button-primary upload-submit" type="button" disabled={busy || !files.length} aria-busy={busy || undefined}
          onClick={() => void submit()} data-testid="package-submit">
          {busy ? <Loader2 size={15} className="spin" aria-hidden="true" /> : <Files size={15} aria-hidden="true" />}
          {uploading ? `Mengunggah ${formatCount(uploading.done)}/${formatCount(uploading.total)}…` : processing ? "Sedang dibaca…" : "Unggah, baca, dan analisis"}
        </button>
        {uploading && <button type="button" className="button button-secondary" disabled={uploading.cancelling} data-testid="package-cancel-upload"
          onClick={() => { cancelRequested.current = true; setUploading(state => state && { ...state, cancelling: true }); }}>
          <CircleSlash size={15} aria-hidden="true" />{uploading.cancelling ? "Membatalkan…" : "Batalkan unggahan"}</button>}
      </div>
    </div> : <p className="fine-print">Akun Anda tidak memiliki izin mengunggah data.</p>}
    {samples.length > 0 && <div className="sample-downloads" data-testid="sample-downloads">
      <span className="sample-downloads-label"><Download size={14} aria-hidden="true" />Belum punya berkas? Coba contoh data sintetis</span>
      <ul>{samples.map(sample => {
        const meta = SAMPLE_META[sample.sample_id];
        return <li key={sample.sample_id}>
          <a className="sample-card" href={intakeSampleUrl(sample.sample_id)} download={sample.file_name} title={sample.description}
            data-testid={`sample-${sample.sample_id}`}>
            <span className="sample-icon">{meta?.icon === "csv" ? <Database size={18} aria-hidden="true" /> : <Package size={18} aria-hidden="true" />}</span>
            <span className="sample-body"><strong>{sample.label}</strong>
              <span className="sample-chips">{(meta?.chips ?? []).map(chip => <i key={chip}>{chip}</i>)}</span></span>
            {meta?.time && <span className="sample-time"><Clock3 size={13} aria-hidden="true" />{meta.time}</span>}
            <Download className="sample-go" size={16} aria-hidden="true" />
          </a>
        </li>;
      })}</ul>
    </div>}
    {error && <div className="workflow-error" role="alert"><strong>Unggahan gagal</strong><span>{error}</span></div>}
    {notice && <div className="workflow-feedback" role="status">{notice}</div>}
    {status && <div className="intake-facts">
      <span className="intake-fact"><ScanText size={15} aria-hidden="true" />Catatan bebas dibaca:{" "}
        <Term id={status.model.configured ? "ai-pembaca" : "aturan-teks"}>{status.model.configured ? "AI pembaca dokumen" : "aturan teks"}</Term></span>
    </div>}
    {preview && <FilePreviewDialog file={preview} check={checks[fileKey(preview)]} onClose={() => setPreview(null)} />}
    {current && current.status === "processing" && <PackageProgress pkg={current} />}
    {current && current.status === "failed" && <PackageFailed pkg={current} />}
    {current && current.status === "ready" && current.summary && !("failure" in current.summary && current.summary.failure)
      && <PackageResult pkg={current} summary={current.summary as IntakeSummary} onCancel={() => void cancelResult(current)} />}
  </section>;
}

function PackageProgress({ pkg }: { pkg: IntakePackage }) {
  const share = pkg.progress_total ? Math.round(100 * pkg.progress_done / pkg.progress_total) : null;
  const waiting = pkg.stage === "Menunggu giliran";
  return <div className="package-progress" role="status" data-testid="package-progress">
    <div className="package-progress-head"><Loader2 size={15} className="spin" aria-hidden="true" />
      <strong>{pkg.stage ?? "Memproses"}</strong>
      {waiting && pkg.queue_position ? <span>urutan ke-{formatCount(pkg.queue_position)}; paket lain sedang dibaca</span> : null}
      {pkg.stage === "Membaca berkas PDF" && pkg.progress_total > 0 && <span>{formatCount(pkg.progress_done)} dari {formatCount(pkg.progress_total)} berkas</span>}
    </div>
    <div className="package-bar" aria-hidden="true"><i style={{ width: `${pkg.stage === "Membaca berkas PDF" && share !== null ? share : pkg.stage === "Membaca data klaim" ? 4 : 100}%` }}
      className={pkg.stage !== "Membaca berkas PDF" && pkg.stage !== "Membaca data klaim" ? "indeterminate" : undefined} /></div>
    <p className="fine-print">Anda boleh meninggalkan halaman ini; pemrosesan berjalan di server dan hasilnya muncul di sini.
      Pemrosesan tidak dapat dihentikan di tengah jalan, tetapi hasilnya bisa dibatalkan setelah selesai.</p>
  </div>;
}

function PackageFailed({ pkg }: { pkg: IntakePackage }) {
  const failure: IntakeFailure = pkg.summary && "failure" in pkg.summary && pkg.summary.failure ? pkg.summary.failure : {};
  return <div className="workflow-error" role="alert" data-testid="package-failed">
    <strong>Paket “{pkg.name}” tidak dapat diproses</strong>
    <span>{failureText(pkg.message_code)}</span>
    {failure.files && failure.files.length > 0 && <span data-testid="package-failed-files">Berkas: {failure.files.join(", ")}</span>}
    {failure.ignored_files && failure.ignored_files.length > 0 && <ul className="plain-list">{failure.ignored_files.slice(0, 8).map(item =>
      <li key={item.file_name}>{item.file_name}: {REASONS[item.reason] ?? "tidak dapat dipakai"}</li>)}</ul>}
  </div>;
}

function PackageResult({ pkg, summary, onCancel }: { pkg: IntakePackage; summary: IntakeSummary; onCancel: () => void }) {
  const { claims, documents, enrichment } = summary;
  const runQuery = pkg.run_id ? `?run_id=${encodeURIComponent(pkg.run_id)}` : "";
  const ignored = summary.ignored_files ?? [];
  const conflicts = summary.source_conflicts;
  return <div className="package-result" data-testid="package-result">
    <div className="package-result-head">
      <CheckCircle2 size={18} aria-hidden="true" />
      <div><strong>Paket “{pkg.name}” selesai dibaca dan dianalisis</strong>
        <span>{formatCount(claims.total)} klaim dari {formatCount(summary.files.csv + summary.files.fhir + summary.files.pdf)} berkas, dalam {formatCount(Math.round(summary.seconds))} detik</span></div>
      <div className="package-result-actions">
        <button type="button" className="button button-secondary" onClick={onCancel} data-testid="package-cancel">Batalkan paket</button>
        {pkg.run_id && <Link className="button button-primary" to={`/${runQuery}`} data-testid="package-open">Lihat hasil <ArrowRight size={14} aria-hidden="true" /></Link>}
      </div>
    </div>
    {summary.same_as && <p className="package-note" data-testid="package-same-as"><Info size={15} aria-hidden="true" />
      Isi paket ini sama persis dengan paket “{summary.same_as.name}”{summary.same_as.finished_at ? ` (${formatDateTime(summary.same_as.finished_at)})` : ""}.
      Bila tidak sengaja terkirim dua kali, batalkan paket ini.</p>}
    <div className="package-stats">
      <div><span>Dari data E-Klaim (CSV)</span><strong>{formatCount(claims.from_csv)}</strong><small>klaim</small></div>
      <div><span>Dari RME / SATUSEHAT (FHIR)</span><strong>{formatCount(claims.from_fhir)}</strong><small>klaim</small></div>
      <div><span>Hanya dari berkas PDF</span><strong>{formatCount(claims.from_pdf_only)}</strong><small>klaim dibentuk dari isi dokumen</small></div>
      <div><span>Berkas PDF dibaca</span><strong>{formatCount(documents.total)}</strong>
        <small>{formatCount(documents.scanned)} hasil pindai (OCR){documents.ocr_confidence !== null ? `, keyakinan ${(documents.ocr_confidence * 100).toLocaleString("id-ID", { maximumFractionDigits: 1 })}%` : ""}</small></div>
      <div><span>Klaim dilengkapi dari berkas</span><strong>{formatCount(enrichment.claims_with_documents)}</strong>
        <small>{formatCount(enrichment.notes_from_documents)} catatan klinis diambil dari resume medis</small></div>
      <div className={summary.mismatch_count ? "tone-danger" : undefined}><span>Berkas tidak cocok dengan data klaim</span><strong>{formatCount(summary.mismatch_count)}</strong>
        <small>{summary.mismatch_count ? "perlu dicek verifikator" : "tidak ada perbedaan"}</small></div>
    </div>
    {summary.mismatches.length > 0 && <div className="package-list">
      <h3><TriangleAlert size={15} aria-hidden="true" />Isi berkas berbeda dari data klaim</h3>
      <p className="fine-print">Analisis memakai nilai dari data klaim. Perbedaan dicatat agar verifikator mengecek ke berkas asli.</p>
      <div className="table-scroll"><table className="data-table"><thead><tr><th>Klaim</th><th>Yang berbeda</th><th>Data klaim</th><th>Di berkas</th><th>Berkas</th></tr></thead>
        <tbody>{summary.mismatches.map((item, index) => <tr key={index} data-testid="package-mismatch">
          <td>{pkg.run_id && item.case_id ? <Link to={`/runs/${encodeURIComponent(pkg.run_id)}/cases/${encodeURIComponent(item.case_id)}#berkas-klaim`}>{shortRef(item.case_id)}</Link> : "Tidak tertaut"}</td>
          <td>{item.label}</td><td>{formatDocumentValue(item.field, item.data_value)}</td><td><strong>{formatDocumentValue(item.field, item.document_value)}</strong></td>
          <td>{item.file_name} <small>hal. {item.page}</small></td>
        </tr>)}</tbody></table></div>
    </div>}
    {conflicts && conflicts.count > 0 && <div className="package-list" data-testid="package-source-conflicts">
      <h3><Info size={15} aria-hidden="true" />{formatCount(conflicts.count)} klaim ada di CSV dan RME dengan isi berbeda</h3>
      <p className="fine-print">Analisis memakai data RME (FHIR) karena berasal langsung dari rekam medis. Kolom yang berbeda:</p>
      <ul className="plain-list">{conflicts.items.slice(0, 8).map(item => <li key={item.case_id}>
        {pkg.run_id ? <Link to={`/runs/${encodeURIComponent(pkg.run_id)}/cases/${encodeURIComponent(item.case_id)}`}>Ref. {shortRef(item.case_id)}</Link> : `Ref. ${shortRef(item.case_id)}`}
        : {item.columns.join(", ")} <small>({item.csv_file} dan {item.fhir_file})</small></li>)}</ul>
    </div>}
    {(summary.problem_files.length > 0 || ignored.length > 0) && <div className="package-list" data-testid="package-problem-files">
      <h3><XCircle size={15} aria-hidden="true" />{formatCount(documents.unlinked + documents.unreadable + ignored.length)} berkas tidak dipakai</h3>
      <p className="fine-print">Paket tetap diproses tanpa berkas ini. Perbaiki bila perlu, lalu unggah dalam paket baru.</p>
      <ul className="plain-list">{[...ignored.map(item => ({ ...item, status: "ignored" })), ...summary.problem_files].slice(0, 12).map((item, index) => <li key={index}>
        <FileScan size={13} aria-hidden="true" /> <strong>{item.file_name}</strong>: {REASONS[item.reason ?? ""] ?? (item.status === "unlinked" ? "tidak dapat ditautkan ke klaim" : "tidak dapat dibaca")}
      </li>)}</ul>
    </div>}
    {(documents.low_confidence > 0 || summary.reader.model_errors > 0) && <p className="fine-print">
      {documents.low_confidence > 0 && `${formatCount(documents.low_confidence)} berkas hasil pindai terbaca kurang yakin; tandanya muncul di detail klaim. `}
      {summary.reader.model_errors > 0 && `AI pembaca dokumen tidak menjawab untuk ${formatCount(summary.reader.model_errors)} berkas; isian formulirnya tetap dibaca.`}
    </p>}
  </div>;
}
