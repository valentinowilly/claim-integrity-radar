import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { CornerDownLeft, FileSearch, Moon, Search, Upload, type LucideIcon } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { getRunCases, getRuns, type Lane } from "../api/client";
import { toggleTheme } from "../theme/theme";
import { LANES, LaneDot, indicatorLabel, shortRef } from "./Display";

export type PaletteLink = { label: string; to: string; icon: LucideIcon };
type Item = { id: string; group: string; label: string; hint?: string; icon?: LucideIcon; lane?: Lane; run: () => void };

/** The analysis the user is looking at: the claim page's run, the ?run_id of a page, or null (the latest is used). */
function currentRunId(pathname: string, search: string): string | null {
  const fromPath = /^\/runs\/([^/]+)\//.exec(pathname)?.[1];
  return fromPath ? decodeURIComponent(fromPath) : new URLSearchParams(search).get("run_id");
}

/** Ctrl+K (or ⌘K): jump to a page, run an action, or open a claim by its reference. */
export function CommandPalette({ pages, canUpload, canSearchClaims }: { pages: PaletteLink[]; canUpload: boolean; canSearchClaims: boolean }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [claims, setClaims] = useState<{ runId: string; items: Array<{ caseId: string; lane: Lane; finding: string }> } | null>(null);
  const [searching, setSearching] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setOpen(value => !value); }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("cir:open-palette", onOpen);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("cir:open-palette", onOpen); };
  }, []);
  useEffect(() => { if (open) { setQuery(""); setActive(0); setClaims(null); window.setTimeout(() => input.current?.focus(), 0); } }, [open]);

  // Claim references: searched on the server in the analysis being viewed (or the latest one), after a short pause.
  const term = query.trim();
  useEffect(() => {
    if (!open || !canSearchClaims || term.length < 3) { setClaims(null); setSearching(false); return; }
    const controller = new AbortController();
    setSearching(true);
    const timer = window.setTimeout(async () => {
      try {
        const runId = currentRunId(location.pathname, location.search) ?? (await getRuns(1, 0, undefined, controller.signal)).items[0]?.run_id;
        if (!runId) { setClaims(null); return; }
        const page = await getRunCases(runId, { offset: 0, limit: 6, sort: "rule_index", search: term }, controller.signal);
        setClaims({ runId, items: page.items.map(item => ({ caseId: item.case.case_id, lane: (item.lane?.lane ?? "green") as Lane,
          finding: item.case.indicators.map(indicatorLabel).join(", ") })) });
      } catch { if (!controller.signal.aborted) setClaims(null); } finally { if (!controller.signal.aborted) setSearching(false); }
    }, 250);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [open, term, canSearchClaims, location.pathname, location.search]);

  const items = useMemo<Item[]>(() => {
    const go = (to: string) => () => { setOpen(false); navigate(to); };
    const lower = term.toLowerCase();
    const matches = (text: string) => !lower || text.toLowerCase().includes(lower);
    const list: Item[] = pages.filter(page => matches(page.label))
      .map(page => ({ id: `page:${page.to}`, group: "Halaman", label: page.label, icon: page.icon, run: go(page.to) }));
    for (const claim of claims?.items ?? []) list.push({
      id: `claim:${claim.caseId}`, group: "Klaim", label: `Ref. ${shortRef(claim.caseId)}`, hint: claim.finding || LANES[claim.lane].name,
      lane: claim.lane, run: go(`/runs/${encodeURIComponent(claims!.runId)}/cases/${encodeURIComponent(claim.caseId)}`),
    });
    const actions: Item[] = [
      ...(canUpload ? [{ id: "action:upload", group: "Tindakan", label: "Unggah data klaim", icon: Upload, run: go("/workflow?unggah=1") }] : []),
      { id: "action:theme", group: "Tindakan", label: "Ganti tema terang/gelap", icon: Moon, run: () => { setOpen(false); toggleTheme(); } },
    ];
    return [...list, ...actions.filter(action => matches(action.label))];
  }, [pages, claims, term, canUpload, navigate]);

  useEffect(() => { setActive(index => Math.min(index, Math.max(0, items.length - 1))); }, [items.length]);
  if (!open) return null;

  const onKeyDown = (event: ReactKeyboardEvent) => {
    if (event.key === "Escape") { event.preventDefault(); setOpen(false); }
    else if (event.key === "ArrowDown") { event.preventDefault(); setActive(index => (index + 1) % Math.max(1, items.length)); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setActive(index => (index - 1 + items.length) % Math.max(1, items.length)); }
    else if (event.key === "Enter") { event.preventDefault(); items[active]?.run(); }
  };
  let lastGroup = "";
  return <div className="palette-scrim" onMouseDown={() => setOpen(false)}>
    <div className="palette" role="dialog" aria-modal="true" aria-label="Cari halaman, klaim, atau tindakan" onMouseDown={event => event.stopPropagation()}>
      <div className="palette-input">
        <Search size={17} aria-hidden="true" />
        <input ref={input} value={query} onChange={event => { setQuery(event.target.value); setActive(0); }} onKeyDown={onKeyDown}
          placeholder="Cari halaman, nomor referensi klaim, atau tindakan…" aria-label="Cari" role="combobox" aria-expanded="true"
          aria-controls="palette-list" aria-activedescendant={items[active] ? `palette-${active}` : undefined} autoComplete="off" spellCheck={false} />
        <kbd>Esc</kbd>
      </div>
      <ul className="palette-list" id="palette-list" role="listbox">
        {items.map((item, index) => {
          const header = item.group !== lastGroup ? item.group : null;
          lastGroup = item.group;
          const Icon = item.icon ?? FileSearch;
          return [header && <li key={`h-${header}`} className="palette-group" role="presentation">{header}</li>,
            <li key={item.id} id={`palette-${index}`} role="option" aria-selected={index === active}
              className={`palette-item${index === active ? " active" : ""}`} onMouseEnter={() => setActive(index)} onClick={item.run}>
              {item.lane ? <LaneDot lane={item.lane} /> : <Icon size={16} aria-hidden="true" />}
              <span className="palette-label">{item.label}</span>
              {item.hint && <span className="palette-hint">{item.hint}</span>}
              {index === active && <CornerDownLeft size={14} className="palette-enter" aria-hidden="true" />}
            </li>];
        })}
        {searching && <li className="palette-note" role="presentation">Mencari klaim…</li>}
        {!searching && canSearchClaims && term.length >= 3 && claims && !claims.items.length && <li className="palette-note" role="presentation">Tidak ada klaim dengan nomor referensi itu.</li>}
        {canSearchClaims && term.length > 0 && term.length < 3 && <li className="palette-note" role="presentation">Ketik minimal 3 karakter untuk mencari nomor referensi klaim.</li>}
      </ul>
      <div className="palette-foot"><span><kbd>↑</kbd><kbd>↓</kbd> pilih</span><span><kbd>Enter</kbd> buka</span><span><kbd>Ctrl</kbd><kbd>K</kbd> buka/tutup</span></div>
    </div>
  </div>;
}

/** The top-bar button that opens the palette (the shortcut is shown so people learn it). */
export function PaletteButton() {
  return <button type="button" className="palette-trigger" onClick={() => window.dispatchEvent(new Event("cir:open-palette"))}
    aria-label="Cari (Ctrl+K)"><Search size={15} aria-hidden="true" /><span>Cari…</span><kbd>Ctrl K</kbd></button>;
}
