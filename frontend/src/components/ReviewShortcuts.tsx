import { useEffect, useState } from "react";
import { Keyboard, X } from "lucide-react";

const SHORTCUTS: Array<[string[], string]> = [
  [["J"], "Klaim berikutnya di antrean"],
  [["K"], "Klaim sebelumnya"],
  [["1", "–", "5"], "Pilih status: belum, sedang ditinjau, minta klarifikasi, antrean audit, selesai"],
  [["S"], "Simpan status"],
  [["A"], "Ambil klaim ini"],
  [["Ctrl", "K"], "Cari halaman, klaim, atau tindakan"],
  [["?"], "Tampilkan atau tutup daftar ini"],
];

function typing(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  return Boolean(element && (element.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName)));
}

function clickQueueItem(step: 1 | -1) {
  const items = [...document.querySelectorAll<HTMLAnchorElement>("ul.queue-items a.queue-item")];
  if (!items.length) return;
  const current = items.findIndex(item => item.getAttribute("aria-current") === "true");
  const next = current < 0 ? 0 : Math.min(items.length - 1, Math.max(0, current + step));
  if (next !== current) { items[next].click(); items[next].scrollIntoView({ block: "nearest" }); }
}

function clickButton(startsWith: string) {
  const button = [...document.querySelectorAll<HTMLButtonElement>("main button")]
    .find(item => item.textContent?.trim().startsWith(startsWith) && !item.disabled);
  button?.click();
}

/** Keyboard work in the review queue: move between claims, choose and save a status, take a claim. */
export function ReviewShortcuts() {
  const [help, setHelp] = useState(false);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.metaKey || event.altKey || typing(event.target) || document.querySelector(".palette")) return;
      const key = event.key.toLowerCase();
      if (event.key === "?") { event.preventDefault(); setHelp(value => !value); return; }
      if (event.key === "Escape") { setHelp(false); return; }
      if (key === "j" || key === "k") { event.preventDefault(); clickQueueItem(key === "j" ? 1 : -1); return; }
      if (/^[1-5]$/.test(key)) {
        const radios = document.querySelectorAll<HTMLInputElement>('input[name="review-status"]:not(:disabled)');
        const radio = radios[Number(key) - 1];
        if (radio) { event.preventDefault(); radio.click(); radio.focus(); }
        return;
      }
      if (key === "s") {
        const form = document.querySelector<HTMLInputElement>('input[name="review-status"]')?.form;
        const submit = form?.querySelector<HTMLButtonElement>('button[type="submit"]:not(:disabled)');
        if (submit) { event.preventDefault(); submit.click(); }
        return;
      }
      if (key === "a") { event.preventDefault(); clickButton("Ambil klaim"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return <>
    <button type="button" className="shortcut-hint" onClick={() => setHelp(true)} aria-label="Pintasan keyboard"
      title="Pintasan keyboard: J/K pindah klaim, 1–5 pilih status, S simpan, ? daftar lengkap">
      <Keyboard size={14} aria-hidden="true" />
    </button>
    {help && <div className="palette-scrim" onMouseDown={() => setHelp(false)}>
      <div className="shortcut-help" role="dialog" aria-modal="true" aria-label="Pintasan keyboard" onMouseDown={event => event.stopPropagation()}>
        <div className="shortcut-help-head"><h2><Keyboard size={17} className="head-icon" aria-hidden="true" />Pintasan keyboard</h2>
          <button type="button" className="icon-close" onClick={() => setHelp(false)} aria-label="Tutup"><X size={16} /></button></div>
        <dl>{SHORTCUTS.map(([keys, text]) => <div key={text}>
          <dt>{keys.map(key => key === "–" ? <span key={key}>–</span> : <kbd key={key}>{key}</kbd>)}</dt><dd>{text}</dd>
        </div>)}</dl>
        <p className="fine-print">Pintasan tidak aktif saat Anda sedang mengetik di kolom isian.</p>
      </div>
    </div>}
  </>;
}
