import { useState, type FormEvent, type ReactNode } from "react";
import { BookOpenCheck, ChevronDown, CircleHelp, Keyboard, Send, Signpost } from "lucide-react";
import { Link } from "react-router-dom";
import { ApiClientError, sendFeedbackMessage, type AppRole } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { LANES, LaneDot, displayRole } from "../components/Display";

const MAX = 500;

type Guide = { title: string; roles: AppRole[]; intro: string; steps: ReactNode[]; link: { to: string; label: string } };
const GUIDES: Guide[] = [
  {
    title: "Operator data", roles: ["data_operator"],
    intro: "Memasukkan data klaim harian agar dapat diperiksa.",
    steps: [
      <>Buka <strong>Data &amp; Analisis</strong>.</>,
      <>Unggah file CSV berformat kolom klaim BPJS, atau tekan <strong>Ambil sekarang</strong> untuk mengambil file dari folder kiriman (otomatis setiap hari pukul 06.00).</>,
      <>Periksa hasil pemeriksaan file. Baris yang ditolak disertai alasannya; perbaiki lalu unggah ulang.</>,
      <>Analisis berjalan sendiri; hasilnya langsung masuk ke antrean verifikator.</>,
    ],
    link: { to: "/workflow", label: "Buka Data & Analisis" },
  },
  {
    title: "Verifikator", roles: ["verifikator", "demo_tester"],
    intro: "Meninjau klaim yang ditandai, dari yang paling berisiko.",
    steps: [
      <>Buka <strong>Antrean Tinjauan</strong> dan mulai dari jalur merah.</>,
      <>Tekan <strong>Ambil klaim ini</strong> agar petugas lain tahu klaim sedang Anda tangani.</>,
      <>Baca alasan per modus, skor AI Pola Klaim, dan catatan klinis. Minta AI Pembaca Catatan bila perlu.</>,
      <>Simpan status, lalu beri keputusan: <em>Benar, perlu ditindaklanjuti</em>, <em>Ternyata wajar</em>, atau <em>Belum bisa disimpulkan</em>.</>,
    ],
    link: { to: "/cases", label: "Buka Antrean Tinjauan" },
  },
  {
    title: "Verifikator senior dan administrator", roles: ["audit_lead", "platform_admin", "demo_tester"],
    intro: "Merencanakan audit faskes dan menjaga mutu layanan sistem.",
    steps: [
      <>Lihat <strong>Beranda</strong>, <strong>Tren</strong>, dan <strong>Peta Risiko</strong> untuk gambaran umum.</>,
      <>Buka <strong>Faskes</strong> untuk urutan prioritas audit dan cetak paket bukti per faskes.</>,
      <>Pantau <strong>Masukan Pengguna</strong>: seberapa membantu penjelasan sistem dan pertanyaan dari petugas.</>,
      <>Administrator memeriksa <strong>Riwayat Aktivitas</strong> untuk melihat siapa melakukan apa dan kapan.</>,
    ],
    link: { to: "/facilities", label: "Buka Faskes" },
  },
];

const FAQ: Array<{ q: string; a: ReactNode }> = [
  {
    q: "Apakah jalur merah berarti faskes melakukan kecurangan?",
    a: <>Tidak. Jalur hanya menunjukkan urutan pemeriksaan. Klaim di jalur merah punya temuan paling kuat sehingga diperiksa lebih dulu,
      tetapi keputusan ada di tangan petugas setelah melihat bukti.</>,
  },
  {
    q: "Bagaimana sistem menentukan jalur merah, kuning, dan hijau?",
    a: <><p><strong>Merah:</strong> dua pemeriksaan aturan atau lebih menemukan kejanggalan, atau satu pemeriksaan menemukan kejanggalan
      dan AI Pola Klaim menilai polanya lebih jarang dari 95% klaim acuan.</p>
      <p><strong>Kuning:</strong> satu pemeriksaan aturan menemukan kejanggalan.</p>
      <p><strong>Hijau:</strong> klaim hanya mirip klaim lain tanpa temuan aturan yang spesifik. Kemiripan saja tidak cukup untuk masuk antrean.</p></>,
  },
  {
    q: "Apa arti skor AI Pola Klaim?",
    a: <>Skor 0–100 menunjukkan seberapa jarang pola klaim dibanding klaim acuan. Skor 99 berarti lebih jarang dari 99% klaim.
      Label: 99 ke atas <em>pola sangat jarang</em>, 95 ke atas <em>pola jarang</em>, 80 ke atas <em>pola agak jarang</em>.
      Pola yang jarang belum tentu salah; skor ini membantu urutan pemeriksaan, bukan bukti.</>,
  },
  {
    q: "Apa yang dilakukan AI Pembaca Catatan?",
    a: <>AI membaca catatan klinis klaim lalu membandingkannya dengan tagihan: diagnosis, tingkat keparahan, dan lama rawat.
      Hasilnya <em>Sesuai tagihan</em>, <em>Perlu dicek</em>, atau <em>Tidak sesuai tagihan</em>, beserta hal yang perlu diperiksa di rekam medis.
      AI berjalan di server sendiri, sehingga catatan tidak dikirim ke luar.</>,
  },
  {
    q: "Bagaimana bila AI tidak berjalan?",
    a: <>Sistem tetap bekerja. Bila AI Pola Klaim tidak tersedia, jalur ditentukan dari pemeriksaan aturan saja dan hal ini dicatat di klaim.
      Bila AI Pembaca Catatan mati atau terlalu lama menjawab, sistem memakai <em>pembacaan cadangan</em> berbasis aturan teks yang diberi label jelas.
      Bila analisis gagal seluruhnya, sistem tidak memberi saran sama sekali dan analisis dapat dijalankan ulang.</>,
  },
  {
    q: "Bagaimana identitas peserta dilindungi?",
    a: <>Nomor peserta dan ID kunjungan disamarkan sebelum disimpan, hanya kolom yang perlu yang diolah, dan biaya setelah verifikasi (FKL48)
      tidak dipakai sama sekali. Setiap halaman hanya terbuka untuk peran yang berhak, dan setiap keputusan tercatat.
      Jangan menulis data peserta di kolom catatan atau masukan.</>,
  },
  {
    q: "Klaim yang ingin saya tinjau sudah diambil petugas lain. Apa yang harus dilakukan?",
    a: <>Klaim yang diambil hanya dapat dilepas oleh petugas yang mengambilnya, agar satu klaim tidak ditinjau dua kali. Hubungi petugas tersebut
      atau pilih klaim lain di antrean.</>,
  },
  {
    q: "Ke mana analisis lama?",
    a: <>Analisis yang lebih lama dari masa aktif (bawaan 30 hari) diarsipkan otomatis. Arsip tidak menghapus apa pun: hasil, tinjauan, dan
      catatan audit tetap tersimpan dan dapat ditampilkan lagi dari Data &amp; Analisis.</>,
  },
];

/** How to use the system: a guide per role, the meaning of the lanes, answers to common questions, and a form to ask. */
export default function HelpPage() {
  const { state } = useAuth();
  const session = "session" in state ? state.session : null;
  const role = session?.user.role;
  return <>
    <header className="page-head">
      <div><h1>Bantuan</h1><p>Panduan memakai Claim Integrity Radar, jawaban pertanyaan umum, dan tempat bertanya kepada tim pengelola.</p></div>
    </header>

    <section className="help-section" aria-labelledby="help-guides">
      <h2 id="help-guides" className="help-title"><Signpost size={17} aria-hidden="true" />Mulai dari peran Anda</h2>
      <div className="help-guides">
        {GUIDES.map(guide => {
          const mine = role !== undefined && guide.roles.includes(role);
          return <article key={guide.title} className={`card help-guide${mine ? " mine" : ""}`}>
            <div className="help-guide-head"><h3>{guide.title}</h3>{mine && <span className="status-pill tone-good">Peran Anda</span>}</div>
            <p>{guide.intro}</p>
            <ol>{guide.steps.map((step, index) => <li key={index}>{step}</li>)}</ol>
            <Link className="text-link" to={guide.link.to}>{guide.link.label}</Link>
          </article>;
        })}
      </div>
    </section>

    <section className="card help-section" aria-labelledby="help-lanes">
      <div className="card-head"><div><h2 id="help-lanes"><BookOpenCheck size={16} className="head-icon" aria-hidden="true" />Arti jalur pemeriksaan</h2>
        <p>Setiap klaim yang ditandai masuk salah satu jalur. Jalur adalah saran tindakan, bukan putusan.</p></div></div>
      <ul className="help-lanes">
        {(["red", "yellow", "green"] as const).map(lane => <li key={lane}>
          <LaneDot lane={lane} />
          <div><strong>{LANES[lane].name} · {LANES[lane].meaning}</strong><span>{LANES[lane].action}.</span></div>
        </li>)}
      </ul>
    </section>

    <section className="card help-section" aria-labelledby="help-faq">
      <div className="card-head"><div><h2 id="help-faq"><CircleHelp size={16} className="head-icon" aria-hidden="true" />Pertanyaan umum</h2>
        <p>Klik pertanyaan untuk melihat jawabannya.</p></div></div>
      <div className="help-faq">
        {FAQ.map(item => <details key={item.q}>
          <summary><span>{item.q}</span><ChevronDown size={16} aria-hidden="true" /></summary>
          <div className="help-answer">{item.a}</div>
        </details>)}
      </div>
    </section>

    <div className="help-columns">
      <section className="card help-section" aria-labelledby="help-keys">
        <div className="card-head"><div><h2 id="help-keys"><Keyboard size={16} className="head-icon" aria-hidden="true" />Pintasan</h2>
          <p>Bekerja lebih cepat tanpa berpindah menu.</p></div></div>
        <ul className="help-keys">
          <li><kbd>Ctrl</kbd> + <kbd>K</kbd><span>Cari halaman atau buka klaim dengan nomor referensinya.</span></li>
          <li><kbd>Esc</kbd><span>Tutup jendela pencarian atau menu profil.</span></li>
          <li><span className="help-key-text">Ikon bulan/matahari</span><span>Ganti tampilan terang atau gelap.</span></li>
        </ul>
      </section>
      {session?.permissions.includes("feedback:write") && <AskForm roleLabel={role ? displayRole(role) : "Pengguna"} />}
    </div>
  </>;
}

function AskForm({ roleLabel }: { roleLabel: string }) {
  const [kind, setKind] = useState<"help_question" | "general">("help_question");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError(""); setSent(false);
    try {
      await sendFeedbackMessage(kind, message.trim());
      setMessage(""); setSent(true);
    } catch (reason) {
      setError(reason instanceof ApiClientError ? reason.message : "Pesan belum terkirim. Coba lagi.");
    } finally {
      setBusy(false);
    }
  }
  return <section className="card help-section" aria-labelledby="help-ask" data-testid="help-ask">
    <div className="card-head"><div><h2 id="help-ask"><Send size={16} className="head-icon" aria-hidden="true" />Ajukan pertanyaan atau masukan</h2>
      <p>Dibaca oleh verifikator senior dan administrator. Pesan Anda tercatat sebagai {roleLabel.toLowerCase()}.</p></div></div>
    <form className="help-form" onSubmit={submit}>
      <div className="segmented-pill" role="group" aria-label="Jenis pesan">
        <button type="button" aria-pressed={kind === "help_question"} onClick={() => setKind("help_question")}>Pertanyaan</button>
        <button type="button" aria-pressed={kind === "general"} onClick={() => setKind("general")}>Saran</button>
      </div>
      <label htmlFor="help-message">{kind === "help_question" ? "Pertanyaan Anda" : "Saran Anda"}</label>
      <textarea id="help-message" value={message} maxLength={MAX} rows={4} disabled={busy} required
        placeholder="Tulis singkat. Jangan menulis data peserta atau informasi sensitif lain."
        onChange={event => { setMessage(event.target.value); setSent(false); }} />
      <div className="form-actions">
        <span className="character-count">{message.length}/{MAX}</span>
        {sent && <span className="feedback-sent" role="status">Terkirim. Terima kasih.</span>}
        <button className="button button-primary" type="submit" disabled={busy || !message.trim()}><Send size={14} />{busy ? "Mengirim…" : "Kirim"}</button>
      </div>
      {error && <p className="feedback-error" role="alert">{error}</p>}
    </form>
  </section>;
}
