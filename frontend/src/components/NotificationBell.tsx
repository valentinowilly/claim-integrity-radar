import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Bell, CheckCircle2, Info, XCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { useNotificationHistory } from "../notifications/NotificationCenter";

const ICONS = { info: Info, success: CheckCircle2, warning: AlertTriangle, danger: XCircle };
const WHEN = new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/** The notifications shown so far (popups disappear; this list keeps them), with the unread count on the bell. */
export function NotificationBell() {
  const { items, unread, markAllRead, clear } = useNotificationHistory();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    const onClick = (event: MouseEvent) => { if (box.current && !box.current.contains(event.target as Node)) setOpen(false); };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    // Read once the list is closed, so the new ones stay marked while it is open.
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("mousedown", onClick); markAllRead(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  return <div className="bell" ref={box}>
    <button type="button" className="theme-toggle bell-button" aria-expanded={open} aria-haspopup="dialog" data-testid="notification-bell"
      aria-label={unread ? `Notifikasi, ${unread} belum dibaca` : "Notifikasi"} onClick={() => setOpen(value => !value)}>
      <Bell size={17} aria-hidden="true" />
      {unread > 0 && <span className="bell-count" aria-hidden="true">{unread > 9 ? "9+" : unread}</span>}
    </button>
    {open && <div className="bell-panel" role="dialog" aria-label="Riwayat notifikasi">
      <div className="bell-head"><strong>Notifikasi</strong>
        {items.length > 0 && <button type="button" className="picked-clear" onClick={clear}>Hapus semua</button>}</div>
      {items.length === 0 ? <p className="bell-empty">Belum ada notifikasi. Hasil analisis baru dan klaim yang masuk antrean audit muncul di sini.</p>
        : <ul>{items.map(item => {
          const Icon = ICONS[item.tone];
          return <li key={item.id} className={`bell-item tone-${item.tone}${item.read ? "" : " is-unread"}`}>
            <Icon size={16} aria-hidden="true" />
            <div>
              <strong>{item.title}</strong>
              {item.message && <span>{item.message}</span>}
              <small>{WHEN.format(new Date(item.at))}</small>
              {item.link && <Link to={item.link.to} onClick={() => setOpen(false)}>{item.link.label}</Link>}
            </div>
          </li>;
        })}</ul>}
    </div>}
  </div>;
}
