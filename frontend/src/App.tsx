import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Activity, ChevronDown, ClipboardCheck, Database, FileSearch, Fingerprint, LayoutDashboard, LifeBuoy, LogOut, Menu, Radar, ShieldCheck, X } from "lucide-react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { getHealth, type HealthResponse } from "./api/client";
import AnalysisPage from "./pages/AnalysisPage";
import CaseDetailPage from "./pages/CaseDetailPage";
import CasesPage from "./pages/CasesPage";
import EvaluationPage from "./pages/EvaluationPage";
import OverviewPage from "./pages/OverviewPage";
import WorkflowPage from "./pages/WorkflowPage";
import RunCaseReviewPage from "./pages/RunCaseReviewPage";
import { useAuth } from "./auth/AuthContext";
import { ApiClientError } from "./api/client";

const navigation = [
  { label: "Overview", to: "/", icon: LayoutDashboard, end: true, permission: "dashboard:read" },
  { label: "Analisis Risiko", to: "/analysis", icon: Radar, end: true, permission: "analytics:read" },
  { label: "Antrean Audit", to: "/cases", icon: ClipboardCheck, end: true, permission: "cases:read" },
  { label: "Batch dan AnalysisRun", to: "/workflow", icon: Database, end: true, permission: "workflow" },
  { label: "Evaluasi", to: "/evaluation", icon: Activity, end: true, permission: "analytics:read" },
];

type ConnectionState = "loading" | "connected" | "disconnected";

export default function App() {
  const { state: auth, signIn, signOut } = useAuth();
  const [connection, setConnection] = useState<ConnectionState>("loading");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  const location = useLocation();

  useEffect(() => {
    let active = true;
    const check = async () => {
      try {
        const result = await getHealth();
        if (active) {
          setHealth(result);
          setConnection("connected");
        }
      } catch {
        if (active) {
          setHealth(null);
          setConnection("disconnected");
        }
      }
    };
    void check();
    const interval = window.setInterval(() => void check(), 15000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => setMenuOpen(false), [location.pathname]);
  async function handleLogout() {
    setLogoutError("");
    try { await signOut(); }
    catch { setLogoutError("Sesi belum berhasil dicabut. Coba keluar lagi saat backend tersedia."); }
  }

  if (auth.loading) return <div className="auth-loading" role="status">Memulihkan sesi yang tersimpan…</div>;
  if (!auth.session) return <LoginPage onLogin={signIn} issue={auth.issue} />;
  const permissions = new Set(auth.session.permissions);
  const visibleNavigation = navigation.filter(item => item.permission === "dashboard:read"
    || item.permission === "workflow" && (permissions.has("batches:read") || permissions.has("runs:read"))
    || permissions.has(item.permission));

  return (
    <div className="app-shell">
      <aside className={`sidebar ${menuOpen ? "sidebar-open" : ""}`}>
        <div className="brand-lockup">
          <div className="brand-mark"><ShieldCheck size={20} strokeWidth={2.1} /></div>
          <div className="brand-copy"><span className="brand-name">Claim Integrity</span><span className="brand-subname">RADAR</span></div>
          <button className="icon-button sidebar-close" aria-label="Tutup navigasi" onClick={() => setMenuOpen(false)}><X size={18} /></button>
        </div>
        <div className="workspace-switcher"><div className="workspace-avatar">CI</div><div className="workspace-copy"><span>Ruang kerja</span><strong>Audit FKRTL</strong></div><ChevronDown className="workspace-chevron" size={15} /></div>
        <div className="nav-label">MENU UTAMA</div>
        <nav className="primary-nav" aria-label="Navigasi utama">
          {visibleNavigation.map(({ label, to, icon: Icon, end }) => (
            <NavLink key={label} to={to} end={end} className={({ isActive }) => {
              const queueActive = label === "Antrean Audit" && location.pathname === "/cases";
              const workflowActive = label === "Batch dan AnalysisRun" && (location.pathname === "/workflow" || location.pathname.startsWith("/runs/"));
              return `nav-link${(queueActive || workflowActive || isActive) ? " nav-link-active" : ""}`;
            }}>
              <Icon size={18} strokeWidth={1.8} /><span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-spacer" />
        <div className="privacy-note"><div className="privacy-icon"><Fingerprint size={17} /></div><div><strong>Privasi dan konteks</strong><p>Demo memakai data sintetis, bukan dataset BPJS.</p></div></div>
        <div className="help-link"><LifeBuoy size={17} strokeWidth={1.8} /><span>Decision support untuk auditor</span></div>
        <div className="sidebar-footer"><div className="user-avatar">{auth.session.user.username.slice(0, 1).toUpperCase()}</div><div className="user-copy"><strong>{auth.session.user.username}</strong><span>{auth.session.user.role}</span></div><button className="logout-button" onClick={() => void handleLogout()} aria-label="Keluar"><LogOut size={16} /></button></div>
        {logoutError && <div className="logout-error" role="alert">{logoutError}</div>}
      </aside>

      {menuOpen && <button className="mobile-scrim" aria-label="Tutup navigasi" onClick={() => setMenuOpen(false)} />}
      <main className="main-panel">
        <header className="topbar">
          <button className="icon-button mobile-menu-button" aria-label="Buka navigasi" onClick={() => setMenuOpen(true)}><Menu size={20} /></button>
          <div className="breadcrumb"><span>Workspace</span><span className="breadcrumb-separator">/</span><strong>{pageTitle(location.pathname)}</strong></div>
          <div className="topbar-right"><BackendStatus connection={connection} health={health} /><span className="topbar-divider" /><div className="topbar-user"><span className="topbar-avatar">{auth.session.user.username.slice(0, 1).toUpperCase()}</span><span className="topbar-username">{auth.session.user.username}</span></div></div>
        </header>
        <div className="page-content">
          <Routes>
            <Route path="/" element={<Protected permission="dashboard:read"><OverviewPage /></Protected>} />
            <Route path="/analysis" element={<Protected permission="analytics:read"><AnalysisPage /></Protected>} />
            <Route path="/cases" element={<Protected permission="cases:read"><CasesPage /></Protected>} />
            <Route path="/cases/:caseId" element={<Protected permission="cases:read"><CaseDetailPage /></Protected>} />
            <Route path="/case-detail" element={<Navigate to="/cases" replace />} />
            <Route path="/evaluation" element={<Protected permission="analytics:read"><EvaluationPage /></Protected>} />
            <Route path="/workflow" element={<ProtectedAny permissions={["batches:read", "runs:read"]}><WorkflowPage /></ProtectedAny>} />
            <Route path="/runs/:runId/cases/:caseId" element={<Protected permission="review:read"><RunCaseReviewPage /></Protected>} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </div>
        <footer className="page-footer"><span>Claim Integrity Radar</span><span>Decision Support for Claims Audit</span><span>v0.1.0</span></footer>
      </main>
    </div>
  );
}

function Protected({ permission, children }: { permission: string; children: ReactNode }) {
  const { state } = useAuth();
  if (state.loading || !state.session) return null;
  return state.session.permissions.includes(permission) ? <>{children}</> : <section className="empty-state-panel"><span className="panel-kicker">AKSES DIBATASI</span><h2>Halaman tidak tersedia untuk role ini</h2><p>Jika akses diperlukan, hubungi administrator workspace.</p></section>;
}

function ProtectedAny({ permissions, children }: { permissions: string[]; children: ReactNode }) {
  const { state } = useAuth();
  if (state.loading || !state.session) return null;
  return permissions.some(permission => state.session!.permissions.includes(permission))
    ? <>{children}</>
    : <section className="empty-state-panel"><span className="panel-kicker">AKSES DIBATASI</span><h2>Halaman tidak tersedia untuk role ini</h2><p>Akun ini tidak memiliki permission membaca batch atau AnalysisRun.</p></section>;
}

function LoginPage({ onLogin, issue }: { onLogin: (username: string, password: string) => Promise<void>; issue?: "expired" | "network" }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setBusy(true);
    try { await onLogin(username, password); }
    catch (reason) { setError(reason instanceof ApiClientError ? reason.message : "Login gagal. Periksa koneksi dan coba lagi."); }
    finally { setBusy(false); }
  }
  return <main className="login-shell"><form className="login-card" onSubmit={submit}>
    <div className="brand-mark"><ShieldCheck size={20} /></div><span className="panel-kicker">CLAIM INTEGRITY RADAR</span>
    <h1>Masuk ke workspace</h1><p>Gunakan akun yang telah dibuat administrator. Pendaftaran publik tidak tersedia.</p>
    {issue === "expired" && <div className="login-error" role="status">Sesi berakhir atau dicabut. Masuk kembali untuk melanjutkan.</div>}
    {issue === "network" && <div className="login-error" role="alert">Status sesi tidak dapat dipastikan karena backend tidak terjangkau. Periksa koneksi lalu coba masuk.</div>}
    <label>Username<input autoComplete="username" required maxLength={80} value={username} onChange={event => setUsername(event.target.value)} /></label>
    <label>Password<input type="password" autoComplete="current-password" required maxLength={1024} value={password} onChange={event => setPassword(event.target.value)} /></label>
    {error && <div className="login-error" role="alert">{error}</div>}
    <button className="login-submit" type="submit" disabled={busy}>{busy ? "Memeriksa akun…" : "Masuk"}</button>
    <small>Demo menggunakan data sintetis. Jangan masukkan data peserta atau klaim nyata.</small>
  </form></main>;
}

function pageTitle(path: string) {
  if (path === "/") return "Overview";
  if (path === "/analysis") return "Analisis Risiko";
  if (path === "/cases") return "Antrean Audit";
  if (path === "/case-detail" || path.startsWith("/cases/")) return "Detail Kasus";
  if (path === "/evaluation") return "Evaluasi";
  if (path === "/workflow") return "Batch dan AnalysisRun";
  if (path.startsWith("/runs/")) return "Review kasus dalam run";
  return "Halaman";
}

function BackendStatus({ connection, health }: { connection: ConnectionState; health: HealthResponse | null }) {
  const label = connection === "loading" ? "Memeriksa API" : connection === "connected" ? "API terhubung" : "API tidak terjangkau";
  return <div className={`backend-status status-${connection}`} role="status" aria-live="polite"><span className="status-dot" /><span>{label}</span>{health && <span className="status-version">v{health.version}</span>}</div>;
}

function NotFoundPage() {
  return <section className="empty-state-panel"><div className="empty-state-icon"><FileSearch size={23} /></div><span className="panel-kicker">HALAMAN TIDAK DITEMUKAN</span><h2>Alamat ini belum tersedia</h2><p>Gunakan navigasi utama untuk kembali ke halaman workspace.</p><Link className="text-link" to="/">Kembali ke overview</Link></section>;
}
