import { createPortal } from "react-dom";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { KeyRound, LogIn, LogOut, ShieldAlert, ShieldCheck, UserCheck, UserCog, UserPlus, UserRoundX, Users, X, type LucideIcon } from "lucide-react";
import {
  ApiClientError, createUser, getSecurityEvents, getUsers, resetUserPassword, updateUser,
  type ManagedUser, type SecurityEventsPage,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, LoadingState } from "../components/DataStates";
import { formatCount, formatDateTime } from "../components/Display";
import { useNotify } from "../notifications/NotificationCenter";

/** The roles an administrator assigns (decision after coaching: verifiers do the work, administrators also manage). */
const ASSIGNABLE: Array<[string, string]> = [["verifikator", "Verifikator"], ["platform_admin", "Administrator"]];
const ROLE_LABELS: Record<string, string> = {
  platform_admin: "Administrator", verifikator: "Verifikator", audit_lead: "Verifikator senior", data_operator: "Operator data", demo_tester: "Penguji demo",
};
const EVENT_LABELS: Record<string, string> = {
  login_succeeded: "Masuk berhasil", login_failed: "Gagal masuk", logout_session_revoked: "Keluar",
  session_expired: "Sesi berakhir", session_revoked_inactive_account: "Sesi diakhiri (akun dinonaktifkan)",
  user_created: "Akun dibuat", user_updated: "Akun diubah", password_reset_by_admin: "Kata sandi diatur ulang admin",
  admin_bootstrap_completed: "Administrator pertama dibuat", review_updated: "Status tinjauan klaim diubah",
};
const PAGE = 50;
const EVENT_LOOK: Record<string, { icon: LucideIcon; tone: "good" | "bad" | "brand" | "warn" | "neutral" }> = {
  login_succeeded: { icon: LogIn, tone: "good" }, login_failed: { icon: ShieldAlert, tone: "bad" }, logout_session_revoked: { icon: LogOut, tone: "neutral" },
  session_expired: { icon: LogOut, tone: "neutral" }, session_revoked_inactive_account: { icon: UserRoundX, tone: "warn" },
  user_created: { icon: UserPlus, tone: "brand" }, user_updated: { icon: UserCog, tone: "brand" }, password_reset_by_admin: { icon: KeyRound, tone: "warn" },
  admin_bootstrap_completed: { icon: UserCog, tone: "brand" },
};

/** "5 menit lalu", "kemarin", or the date for older moments. */
function ago(value: string): string {
  const minutes = Math.round((Date.now() - Date.parse(value)) / 60000);
  if (Number.isNaN(minutes)) return value;
  if (minutes < 1) return "baru saja";
  if (minutes < 60) return `${minutes} menit lalu`;
  if (minutes < 24 * 60) return `${Math.round(minutes / 60)} jam lalu`;
  if (minutes < 48 * 60) return "kemarin";
  if (minutes < 7 * 24 * 60) return `${Math.round(minutes / 1440)} hari lalu`;
  return formatDateTime(value);
}

function problemText(problem: unknown, fallback: string): string {
  return problem instanceof ApiClientError ? problem.message : fallback;
}

/** A password suggestion the administrator can hand over: 16 characters from an unambiguous alphabet. */
function suggestPassword(): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789";
  const values = new Uint32Array(16);
  crypto.getRandomValues(values);
  return Array.from(values, value => alphabet[value % alphabet.length]).join("").replace(/(.{4})(?!$)/g, "$1-");
}

/** Administrator: accounts (add, role, active, password) and the security log. */
export default function AdminPage() {
  const [tab, setTab] = useState<"accounts" | "log">("accounts");
  const [users, setUsers] = useState<ManagedUser[] | null>(null);
  const [failed, setFailed] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    getUsers().then(response => { setUsers(response.items); setError(null); })
      .catch(problem => setError(problemText(problem, "Daftar akun tidak dapat dimuat. Muat ulang halaman.")));
    getSecurityEvents({ limit: 200, offset: 0, eventType: "login_failed" }).then(page => {
      const since = Date.now() - 24 * 3600 * 1000;
      setFailed(page.items.filter(item => Date.parse(item.occurred_at) >= since).length);
    }).catch(() => setFailed(null));
  }, []);
  useEffect(load, [load]);
  const list = users ?? [];
  const stats: Array<{ icon: LucideIcon; label: string; value: string; tone?: string }> = [
    { icon: UserCheck, label: "Akun aktif", value: users ? `${formatCount(list.filter(user => user.is_active).length)} / ${formatCount(list.length)}` : "…" },
    { icon: UserCog, label: "Administrator", value: users ? formatCount(list.filter(user => user.role === "platform_admin" && user.is_active).length) : "…" },
    { icon: LogIn, label: "Belum pernah masuk", value: users ? formatCount(list.filter(user => !user.last_login_at).length) : "…" },
    { icon: ShieldAlert, label: "Gagal masuk 24 jam", value: failed === null ? "…" : formatCount(failed), tone: failed ? "warn" : undefined },
  ];
  return <>
    <header className="page-head"><div><h1>Kelola akun</h1><p>Akun petugas dan log keamanan.</p></div></header>
    <section className="admin-stats" aria-label="Ringkasan akun">{stats.map(stat => <div key={stat.label} className={`admin-stat${stat.tone ? ` tone-${stat.tone}` : ""}`}>
      <span className="admin-stat-icon"><stat.icon size={18} aria-hidden="true" /></span>
      <span className="admin-stat-label">{stat.label}</span><strong>{stat.value}</strong></div>)}</section>
    {error && <div className="workflow-error" role="alert"><strong>Permintaan gagal</strong><span>{error}</span></div>}
    <div className="segmented-pill admin-tabs" role="tablist" aria-label="Bagian kelola akun">
      <button type="button" role="tab" aria-selected={tab === "accounts"} aria-pressed={tab === "accounts"} onClick={() => setTab("accounts")}>
        <Users size={14} aria-hidden="true" />Akun</button>
      <button type="button" role="tab" aria-selected={tab === "log"} aria-pressed={tab === "log"} onClick={() => setTab("log")}>
        <ShieldCheck size={14} aria-hidden="true" />Log keamanan</button>
    </div>
    {tab === "accounts" ? <Accounts users={users} reload={load} /> : <SecurityLog />}
  </>;
}

function Accounts({ users, reload: load }: { users: ManagedUser[] | null; reload: () => void }) {
  const notify = useNotify();
  const { state: auth } = useAuth();
  const myId = "session" in auth ? auth.session?.user.user_id ?? "" : "";
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [resetFor, setResetFor] = useState<ManagedUser | null>(null);

  const change = async (user: ManagedUser, update: { role?: string; is_active?: boolean }, question: string, done: string) => {
    if (!window.confirm(question)) return;
    setBusy(true);
    try { await updateUser(user.user_id, update); notify({ tone: "success", title: done }); load(); }
    catch (problem) { setError(problemText(problem, "Perubahan tidak tersimpan. Coba lagi.")); }
    finally { setBusy(false); }
  };

  return <div className="stack" style={{ gap: 18 }}>
    {error && <div className="workflow-error" role="alert"><strong>Permintaan gagal</strong><span>{error}</span></div>}
    {adding && <AddAccount onAdded={() => { setAdding(false); load(); }} onClose={() => setAdding(false)} />}
    <section className="card" aria-labelledby="accounts-title">
      <div className="card-head"><div><h2 id="accounts-title">Akun</h2><p>Akun nonaktif tidak bisa masuk.</p></div>
        {!adding && <button type="button" className="button button-primary" onClick={() => setAdding(true)}><UserPlus size={15} aria-hidden="true" />Tambah akun</button>}</div>
      {!users ? <LoadingState label="Memuat daftar akun…" /> : users.length === 0 ? <EmptyState title="Belum ada akun" message="Tambahkan akun petugas di atas." />
        : <div className="table-scroll"><table className="data-table admin-table">
          <thead><tr><th>Nama pengguna</th><th>Peran</th><th>Status</th><th>Terakhir masuk</th><th><span className="sr-only">Tindakan</span></th></tr></thead>
          <tbody>{users.map(user => <tr key={user.user_id} className={user.is_active ? undefined : "is-inactive"}>
            <td><span className="admin-user"><span className={`admin-avatar role-${user.role}`} aria-hidden="true">{user.username.slice(0, 2).toUpperCase()}</span>
              <span><strong>{user.username}</strong>{user.user_id === myId && <small className="admin-you">akun Anda</small>}</span></span></td>
            <td><select aria-label={`Peran ${user.username}`} value={user.role} disabled={busy || user.user_id === myId}
              onChange={event => void change(user, { role: event.target.value },
                `Ubah peran ${user.username} menjadi ${ROLE_LABELS[event.target.value]}?`, `Peran ${user.username} diubah`)}>
              {ASSIGNABLE.some(([value]) => value === user.role) ? null : <option value={user.role}>{ROLE_LABELS[user.role] ?? user.role}</option>}
              {ASSIGNABLE.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select></td>
            <td><span className={`admin-status${user.is_active ? " is-on" : ""}`}><i aria-hidden="true" />{user.is_active ? "Aktif" : "Nonaktif"}</span></td>
            <td title={user.last_login_at ? formatDateTime(user.last_login_at) : undefined}>{user.last_login_at ? ago(user.last_login_at) : "Belum pernah"}</td>
            <td><div className="admin-actions">
              <button type="button" className="button button-secondary row-button" disabled={busy} onClick={() => setResetFor(user)}>
                <KeyRound size={14} aria-hidden="true" />Atur ulang kata sandi</button>
              {user.user_id !== myId && <button type="button" className={`button button-secondary row-button${user.is_active ? " button-quiet-danger" : ""}`}
                disabled={busy} onClick={() => void change(user, { is_active: !user.is_active },
                  user.is_active ? `Nonaktifkan ${user.username}?\n\nAkun tidak bisa masuk lagi dan sesinya langsung diakhiri. Riwayat tinjauannya tetap tersimpan.`
                    : `Aktifkan kembali ${user.username}?`, user.is_active ? `${user.username} dinonaktifkan` : `${user.username} diaktifkan`)}>
                {user.is_active ? "Nonaktifkan" : "Aktifkan"}</button>}
            </div></td>
          </tr>)}</tbody>
        </table></div>}
    </section>
    {resetFor && <ResetPassword user={resetFor} onClose={() => setResetFor(null)} />}
  </div>;
}

function AddAccount({ onAdded, onClose }: { onAdded: () => void; onClose: () => void }) {
  const notify = useNotify();
  const [username, setUsername] = useState("");
  const [role, setRole] = useState("verifikator");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (password.length < 12) { setError("Kata sandi minimal 12 karakter."); return; }
    setBusy(true); setError(null);
    try {
      await createUser(username.trim(), password, role);
      notify({ tone: "success", title: `Akun ${username.trim()} dibuat`, message: "Sampaikan kata sandinya langsung ke petugas, bukan lewat grup." });
      setUsername(""); setPassword(""); onAdded();
    } catch (problem) { setError(problemText(problem, "Akun tidak dapat dibuat. Coba lagi.")); }
    finally { setBusy(false); }
  };
  return <section className="card" aria-labelledby="add-account-title">
    <div className="card-head"><div><h2 id="add-account-title"><UserPlus size={16} className="head-icon" aria-hidden="true" />Tambah akun</h2>
      <p>Verifikator: semua tugas pemeriksaan. Administrator: ditambah kelola akun.</p></div>
      <button type="button" className="icon-close" onClick={onClose} aria-label="Tutup formulir"><X size={16} /></button></div>
    <form className="admin-form" onSubmit={event => void submit(event)}>
      <label><span>Nama pengguna</span><input value={username} onChange={event => setUsername(event.target.value)} required minLength={3} maxLength={80}
        autoComplete="off" placeholder="mis. verif.jaksel1" disabled={busy} /></label>
      <label><span>Peran</span><select value={role} onChange={event => setRole(event.target.value)} disabled={busy}>
        {ASSIGNABLE.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label><span>Kata sandi awal <small>(minimal 12 karakter)</small></span>
        <span className="admin-password"><input value={password} onChange={event => setPassword(event.target.value)} required minLength={12}
          autoComplete="new-password" disabled={busy} />
          <button type="button" className="button button-secondary" onClick={() => setPassword(suggestPassword())} disabled={busy}>Buatkan</button></span></label>
      <button type="submit" className="button button-primary" disabled={busy || !username.trim() || !password}>{busy ? "Menyimpan…" : "Tambah akun"}</button>
    </form>
    {error && <p className="fine-print doc-warning" role="alert">{error}</p>}
  </section>;
}

function ResetPassword({ user, onClose }: { user: ManagedUser; onClose: () => void }) {
  const notify = useNotify();
  const [password, setPassword] = useState(suggestPassword);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true); setError(null);
    try {
      await resetUserPassword(user.user_id, password);
      notify({ tone: "success", title: `Kata sandi ${user.username} diatur ulang`, message: "Sesi lamanya diakhiri. Sampaikan kata sandi baru langsung ke petugas." });
      onClose();
    } catch (problem) { setError(problemText(problem, "Kata sandi tidak tersimpan. Coba lagi.")); setBusy(false); }
  };
  return createPortal(<div className="palette-scrim" onMouseDown={onClose}>
    <form className="breakdown admin-dialog" role="dialog" aria-modal="true" aria-labelledby="reset-title" onMouseDown={event => event.stopPropagation()}
      onSubmit={event => void submit(event)}>
      <div className="breakdown-head"><h2 id="reset-title">Atur ulang kata sandi {user.username}</h2>
        <button type="button" className="icon-close" onClick={onClose} aria-label="Tutup"><X size={16} /></button></div>
      <p className="fine-print">Kata sandi lama langsung tidak berlaku dan sesi yang terbuka diakhiri. Salin kata sandi baru sebelum menyimpan.</p>
      <label className="admin-form-field"><span>Kata sandi baru</span>
        <span className="admin-password"><input value={password} onChange={event => setPassword(event.target.value)} minLength={12} required autoFocus
          autoComplete="new-password" disabled={busy} />
          <button type="button" className="button button-secondary" onClick={() => setPassword(suggestPassword())} disabled={busy}>Buat lagi</button></span></label>
      {error && <p className="fine-print doc-warning" role="alert">{error}</p>}
      <div className="breakdown-actions">
        <button type="button" className="button button-secondary" onClick={onClose} disabled={busy}>Batal</button>
        <button type="submit" className="button button-primary" disabled={busy || password.length < 12}>{busy ? "Menyimpan…" : "Simpan kata sandi"}</button>
      </div>
    </form>
  </div>, document.body);
}

function SecurityLog() {
  const [eventType, setEventType] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<SecurityEventsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getSecurityEvents({ limit: PAGE, offset, eventType: eventType || undefined }, controller.signal)
      .then(response => { setPage(response); setError(null); })
      .catch(problem => { if (!controller.signal.aborted) setError(problemText(problem, "Log keamanan tidak dapat dimuat.")); });
    return () => controller.abort();
  }, [eventType, offset]);
  const failed = page?.items.filter(item => item.event_type === "login_failed").length ?? 0;
  return <section className="card" aria-labelledby="log-title">
    <div className="card-head">
      <div><h2 id="log-title">Log keamanan</h2>
        <p>Catatan masuk, gagal masuk, dan perubahan akun. Kata sandi, token, dan catatan tinjauan tidak pernah dicatat di sini.</p></div>
      <label className="admin-filter"><span>Jenis kejadian</span>
        <select value={eventType} onChange={event => { setEventType(event.target.value); setOffset(0); }}>
          <option value="">Semua kejadian</option>
          {(page?.event_types ?? []).map(type => <option key={type} value={type}>{EVENT_LABELS[type] ?? type}</option>)}
        </select></label>
    </div>
    {error && <div className="workflow-error" role="alert"><strong>Permintaan gagal</strong><span>{error}</span></div>}
    {!page ? <LoadingState label="Memuat log keamanan…" /> : page.items.length === 0 ? <EmptyState title="Belum ada kejadian" message="Kejadian keamanan akan tercatat di sini." /> : <>
      {!eventType && failed >= 5 && <p className="package-note"><ShieldCheck size={15} aria-hidden="true" />
        {formatCount(failed)} percobaan masuk gagal di halaman ini. Bila banyak dari waktu yang berdekatan, periksa apakah ada yang menebak kata sandi.</p>}
      <div className="table-scroll"><table className="data-table admin-table">
        <thead><tr><th>Kejadian</th><th>Waktu</th><th>Oleh</th><th>Akun sasaran</th></tr></thead>
        <tbody>{page.items.map(item => {
          const look = EVENT_LOOK[item.event_type] ?? { icon: ShieldCheck, tone: "neutral" };
          return <tr key={item.event_id} className={item.event_type === "login_failed" ? "is-warning" : undefined}>
          <td><span className="admin-event"><span className={`admin-event-icon tone-${look.tone}`}><look.icon size={14} aria-hidden="true" /></span>
            {EVENT_LABELS[item.event_type] ?? item.event_type}</span></td>
          <td title={formatDateTime(item.occurred_at)}>{ago(item.occurred_at)}</td>
          <td>{item.actor_username ?? (item.actor_user_id ? "akun terhapus" : "tidak dikenal")}</td>
          <td>{item.target_username ?? (item.target_type === "user" ? "akun terhapus" : "tidak ada")}</td>
        </tr>; })}</tbody>
      </table></div>
      <div className="pager"><span>{formatCount(offset + 1)} sampai {formatCount(Math.min(offset + PAGE, page.total))} dari {formatCount(page.total)}</span><div>
        <button type="button" className="button button-secondary button-compact" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Sebelumnya</button>
        <button type="button" className="button button-secondary button-compact" disabled={offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>Berikutnya</button>
      </div></div>
    </>}
  </section>;
}
