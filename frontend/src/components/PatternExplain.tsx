import type { ReactNode } from "react";
import { FRAUD_PATTERNS, PatternTags } from "./Display";

/** Plain-language guide to each proposal pattern: what it is, when the system flags it, which columns show it,
 * who usually plays a part, and what to request. "Who" names roles seen in documented cases, never a person. */
export const PATTERN_GUIDE: Record<string, { what: string; when: string[]; data: string; who: string; request: string }> = {
  phantom_billing: {
    what: "Faskes menagih layanan yang sebenarnya tidak pernah diberikan kepada pasien (tagihan \"hantu\").",
    when: [
      "Jumlah layanan yang ditagih dalam sehari melebihi kemampuan unit faskes (kapasitas harian).",
      "Layanan tidak punya bukti pelaksanaan, misalnya catatan sesi terapi.",
      "Banyak layanan dicatat pada menit yang sama, seperti dimasukkan sekaligus.",
    ],
    data: "Kapasitas harian faskes, jumlah layanan, jam layanan, dan daftar bukti yang tercatat.",
    who: "Biasanya bagian penagihan atau manajemen faskes. Dokter atau terapis dapat terlibat bila namanya dipakai untuk sesi yang tidak ada.",
    request: "Jadwal dan daftar hadir terapis, catatan sesi, dan tanda tangan pasien.",
  },
  cloning: {
    what: "Catatan klinis seorang pasien disalin ke klaim pasien lain, sehingga klaim tampak lengkap padahal isinya tiruan.",
    when: ["Catatan klinis klaim ini sama kata demi kata dengan catatan pasien lain, termasuk tanda vital dan hasil lab. Hal ini hampir mustahil terjadi secara alami."],
    data: "Catatan klinis (resume medis) klaim ini dan klaim pasangannya.",
    who: "Penulis rekam medis, yaitu dokter atau petugas rekam medis; sering didorong kebiasaan atau kebijakan di faskes.",
    request: "Rekam medis asli kedua pasien beserta tanggal dan jam pemeriksaan.",
  },
  repeat_billing: {
    what: "Layanan yang sama ditagihkan lebih dari sekali, atau satu masa perawatan dipecah menjadi beberapa klaim agar dibayar berkali-kali.",
    when: [
      "Ada dua klaim atau lebih untuk peserta yang sama, pada tanggal masuk yang sama, dengan diagnosis dan INA-CBG yang sama.",
      "Pasien tercatat pulang lalu dirawat lagi dengan diagnosis yang sama dalam beberapa hari.",
    ],
    data: "Nomor peserta (disamarkan), tanggal masuk dan pulang, diagnosis, INA-CBG, dan tindakan.",
    who: "Biasanya bagian klaim atau administrasi faskes (pengajuan ganda). Pada pemecahan masa rawat, keputusan pulang dan masuk lagi melibatkan dokter.",
    request: "Bukti pembayaran klaim sebelumnya dan resume medis setiap masa rawat.",
  },
  fictitious_claim: {
    what: "Obat atau alat kesehatan khusus (misalnya obat kronis atau prostesis) ditagihkan padahal tidak diberikan, atau tidak sesuai dengan perawatannya.",
    when: [
      "Obat atau alat khusus ditagihkan bersama kode INA-CBG yang di data acuan hampir tidak pernah mendapatkannya.",
      "Tidak ada bukti pemberian, misalnya resep atau catatan penyerahan farmasi.",
    ],
    data: "Kode tambahan khusus (obat, prostesis, alat, pemeriksaan) dan daftar bukti yang tercatat.",
    who: "Biasanya bagian farmasi atau penagihan faskes. Dokter dapat terlibat bila resep dibuat tanpa obat benar-benar diberikan.",
    request: "Resep, catatan penyerahan farmasi, dan faktur atau bukti pemasangan alat.",
  },
  upcoding_stay: {
    what: "Klaim dibuat tampak lebih berat dari sebenarnya agar tarifnya lebih tinggi: tingkat keparahan dinaikkan atau lama rawat diperpanjang.",
    when: [
      "Tingkat keparahan INA-CBG tinggi tanpa diagnosis sekunder yang mendukungnya.",
      "Tingkat keparahan itu jarang dipakai untuk diagnosis yang sama.",
      "Lama rawat jauh di atas klaim sejenis.",
    ],
    data: "Kode INA-CBG (digit keparahan), diagnosis sekunder, serta tanggal masuk dan pulang.",
    who: "Biasanya petugas pengkodean klinis (koder) faskes. Dokter berperan lewat penulisan diagnosis dan keputusan lama rawat.",
    request: "Resume medis dan hasil penunjang yang membuktikan penyakit penyerta.",
  },
};

type Reason = { indicator: string; supporting_values?: Record<string, unknown> };
const BY_INDICATOR: Record<string, string> = {
  synthetic_capacity_candidate: "phantom_billing", temporal_pattern_candidate: "phantom_billing",
  cloned_clinical_note_candidate: "cloning",
  repeat_billing_candidate: "repeat_billing", rapid_readmission_candidate: "repeat_billing",
  unusual_special_topup_candidate: "fictitious_claim",
  length_of_stay_extreme_candidate: "upcoding_stay", unusual_severity_candidate: "upcoding_stay",
  severity_without_secondary_candidate: "upcoding_stay",
};

/** The pattern one finding belongs to (same mapping as the server's fraud_patterns). */
export function patternOfReason(reason: Reason): string | null {
  if (reason.indicator === "supporting_evidence_completeness_candidate") {
    const rule = reason.supporting_values?.rule as { service_type?: unknown } | undefined;
    return rule?.service_type === "special_drug" || rule?.service_type === "special_device" ? "fictitious_claim" : "phantom_billing";
  }
  return BY_INDICATOR[reason.indicator] ?? null;
}

/** Findings grouped under their pattern, each group opening with what the pattern means. */
export function PatternGroups<R extends Reason>({ reasons, render }: { reasons: R[]; render: (reason: R, index: number) => ReactNode }) {
  const groups = new Map<string, Array<[R, number]>>();
  reasons.forEach((reason, index) => {
    const key = patternOfReason(reason) ?? "other";
    groups.set(key, [...(groups.get(key) ?? []), [reason, index]]);
  });
  const order = [...Object.keys(PATTERN_GUIDE), "other"].filter(key => groups.has(key))
    .sort((a, b) => (groups.get(b)!.length - groups.get(a)!.length));
  return <div className="stack">{order.map(key => {
    const guide = PATTERN_GUIDE[key];
    return <section key={key} className={`pattern-group pattern-group-${key}`} data-pattern={key}>
      {guide ? <>
        <header className="pattern-group-head">
          <PatternTags patterns={[key]} />
          <p className="pattern-what">{guide.what}</p>
        </header>
        <details className="pattern-guide">
          <summary>Kapan disebut {FRAUD_PATTERNS[key]?.label}, dan siapa yang biasanya berperan?</summary>
          <dl>
            <div><dt>Sistem menandai bila</dt><dd><ul>{guide.when.map(item => <li key={item}>{item}</li>)}</ul></dd></div>
            <div><dt>Bagian data yang dilihat</dt><dd>{guide.data}</dd></div>
            <div><dt>Siapa yang biasanya berperan</dt><dd>{guide.who}</dd></div>
            <div><dt>Berkas yang diminta saat audit</dt><dd>{guide.request}</dd></div>
          </dl>
          <small>Peran di atas berasal dari pola kasus yang pernah terungkap, bukan tuduhan kepada orang tertentu.</small>
        </details>
      </> : <header className="pattern-group-head"><strong>Petunjuk tambahan</strong>
        <p className="pattern-what">Temuan yang belum cukup untuk menyebut modus tertentu.</p></header>}
      <p className="pattern-found">Yang ditemukan pada klaim ini:</p>
      <div className="stack">{groups.get(key)!.map(([reason, index]) => render(reason, index))}</div>
    </section>;
  })}</div>;
}
