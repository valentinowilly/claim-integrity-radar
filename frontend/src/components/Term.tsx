import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

/** Short definitions of the words a verifier meets on screen; the help page lists them all. */
export const GLOSSARY: Record<string, { term: string; text: string }> = {
  fkl47: { term: "FKL47 (tagihan rumah sakit)", text: "Kolom data klaim berisi biaya yang ditagihkan rumah sakit, sebelum diverifikasi BPJS. Dipakai untuk menunjukkan nilai yang dipertaruhkan, bukan nilai kerugian, dan tidak memengaruhi tingkat risiko." },
  "risiko-tinggi": { term: "Risiko tinggi", text: "Klaim yang ditandai beberapa pemeriksaan sekaligus, atau satu pemeriksaan yang dikuatkan AI pola klaim. Diperiksa lebih dulu; bukan bukti kecurangan." },
  "risiko-sedang": { term: "Risiko sedang", text: "Klaim dengan satu temuan yang perlu penjelasan faskes. Pembayaran tidak ditahan." },
  "ai-pola": { term: "AI pola klaim", text: "Membandingkan kombinasi data satu klaim (diagnosis, INA-CBG, lama rawat, biaya) dengan ribuan klaim lain. Klaim yang polanya jarang ditandai; jarang bukan berarti salah." },
  "ai-pembaca": { term: "AI pembaca dokumen", text: "Membaca catatan klinis dan berkas PDF, lalu menunjukkan bagian yang tidak sesuai dengan data klaim, lengkap dengan kutipan dan halamannya. Keputusan tetap pada verifikator." },
  "ina-cbg": { term: "INA-CBG", text: "Kode kelompok tarif klaim rawat inap. Angka romawi di akhir (I, II, III) menunjukkan tingkat keparahan." },
  sep: { term: "SEP", text: "Surat Eligibilitas Peserta: bukti peserta berhak dilayani pada kunjungan itu." },
  rme: { term: "RME / SATUSEHAT (FHIR)", text: "Rekam medis elektronik dalam format HL7 FHIR. Bila klaim ada di CSV E-Klaim dan di RME, data RME yang dipakai." },
  ocr: { term: "OCR", text: "Pembacaan teks dari berkas hasil pindai. Halaman yang terbaca kurang yakin diberi tanda agar dicek ke berkas asli." },
  "kelompok-faskes": { term: "Kelompok faskes", text: "Faskes dikelompokkan menurut kelas, kepemilikan, dan wilayah, karena data klaim tidak memuat kode rumah sakit yang unik. Kelompok kecil disembunyikan agar faskes tidak dapat dikenali." },
  "paket-bukti": { term: "Paket bukti", text: "Satu halaman berisi alasan dan daftar klaim sampel yang rekam medisnya perlu diminta dari satu kelompok faskes. Bisa dicetak atau disimpan sebagai PDF." },
  klarifikasi: { term: "Minta klarifikasi", text: "Tahap tinjauan saat verifikator meminta penjelasan atau berkas tambahan ke faskes." },
  "aturan-teks": { term: "Aturan teks", text: "Tanpa AI, catatan dibaca dengan pola kalimat tetap (lama rawat, tingkat keparahan, komplikasi). Isian formulir tetap dibaca lengkap." },
  "masa-simpan": { term: "Masa simpan berkas PDF", text: "10 tahun sejak paket diproses, sebagai bukti pendukung pembayaran klaim (UU 8/1997 Pasal 11). Paket yang dibatalkan dihapus setelah 30 hari (UU PDP). Berkas klaim yang sedang ditinjau, diminta klarifikasi, masuk audit, atau terbukti bermasalah tidak dihapus. Rekam medis aslinya tetap disimpan faskes." },
  audit: { term: "Masuk audit", text: "Tahap tinjauan saat klaim diserahkan ke tim audit untuk diperiksa lebih dalam." },
};

/** A word with a definition one tap away (works with touch and keyboard, not only on hover). */
export function Term({ id, children }: { id: keyof typeof GLOSSARY | string; children: ReactNode }) {
  const entry = GLOSSARY[id];
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  const panelId = useId();
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    const onClick = (event: MouseEvent) => { if (box.current && !box.current.contains(event.target as Node)) setOpen(false); };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("mousedown", onClick); };
  }, [open]);
  if (!entry) return <>{children}</>;
  return <span className="term" ref={box}>
    <button type="button" className="term-word" aria-expanded={open} aria-controls={panelId} onClick={event => { event.preventDefault(); event.stopPropagation(); setOpen(value => !value); }}>
      {children}</button>
    {open && <span className="term-panel" id={panelId} role="note">
      <strong>{entry.term}</strong>{entry.text}
      <Link to={`/bantuan#istilah-${id}`} onClick={() => setOpen(false)}>Semua istilah</Link>
    </span>}
  </span>;
}
