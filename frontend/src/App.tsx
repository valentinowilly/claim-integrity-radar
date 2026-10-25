import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  Activity,
  ChevronDown,
  ClipboardCheck,
  Database,
  Eye,
  EyeOff,
  FileSearch,
  LayoutDashboard,
  ListFilter,
  LogOut,
  MessageSquareText,
  Menu,
  Radar,
  ScanSearch,
  X,
} from "lucide-react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
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
  { label: "Data Klaim", to: "/workflow", icon: Database, end: true, permission: "workflow" },
  { label: "Evaluasi", to: "/evaluation", icon: Activity, end: true, permission: "analytics:read" },
];

export default function App() {
  const { state: auth, signIn, signOut } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  const location = useLocation();

  useEffect(() => {
    setMenuOpen(false);
    setProfileOpen(false);
  }, [location.pathname]);
  useEffect(() => {
    const closeProfile = (event: KeyboardEvent) => {
      if (event.key === "Escape") setProfileOpen(false);
    };
    window.addEventListener("keydown", closeProfile);
    return () => window.removeEventListener("keydown", closeProfile);
  }, []);
  async function handleLogout() {
    setLogoutError("");
    try {
      await signOut();
    } catch {
      setLogoutError("Sesi belum berhasil dicabut. Coba keluar lagi saat backend tersedia.");
    }
  }

  if (auth.loading)
    return (
      <div className="auth-loading" role="status">
        Memulihkan sesi yang tersimpan…
      </div>
    );
  if (!auth.session) return <LoginPage onLogin={signIn} issue={auth.issue} />;
  const permissions = new Set(auth.session.permissions);
  const visibleNavigation = navigation.filter(
    (item) =>
      item.permission === "dashboard:read" ||
      (item.permission === "workflow" && (permissions.has("batches:read") || permissions.has("runs:read"))) ||
      permissions.has(item.permission),
  );

  return (
    <div className="app-shell">
      <aside className={`sidebar ${menuOpen ? "sidebar-open" : ""}`}>
        <div className="brand-lockup">
          <div className="sidebar-logo-surface">
            <img className="sidebar-brand-logo" src="/assets/brand/bpjs-kesehatan.svg" alt="BPJS Kesehatan" />
          </div>
          <div className="brand-copy">
            <strong>Claim Integrity Radar</strong>
            <span>Ruang kerja audit</span>
          </div>
          <button className="icon-button sidebar-close" aria-label="Tutup navigasi" onClick={() => setMenuOpen(false)}>
            <X size={18} />
          </button>
        </div>
        <div className="workspace-switcher">
          <div className="workspace-copy">
            <span>Ruang kerja audit</span>
            <strong>Audit Klaim Fasilitas Kesehatan</strong>
          </div>
        </div>
        <div className="nav-label">NAVIGASI AUDIT</div>
        <nav className="primary-nav" aria-label="Navigasi utama">
          {visibleNavigation.map(({ label, to, icon: Icon, end }) => (
            <NavLink
              key={label}
              to={`${to}${location.search}`}
              end={end}
              className={({ isActive }) => {
                const queueActive = label === "Antrean Audit" && location.pathname === "/cases";
                const workflowActive =
                  label === "Data Klaim" &&
                  (location.pathname === "/workflow" || location.pathname.startsWith("/runs/"));
                return `nav-link${queueActive || workflowActive || isActive ? " nav-link-active" : ""}`;
              }}
            >
              <Icon size={18} strokeWidth={1.8} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>

      {menuOpen && <button className="mobile-scrim" aria-label="Tutup navigasi" onClick={() => setMenuOpen(false)} />}
      <main className="main-panel">
        <header className="topbar">
          <button
            className="icon-button mobile-menu-button"
            aria-label="Buka navigasi"
            onClick={() => setMenuOpen(true)}
          >
            <Menu size={20} />
          </button>
          <div className="breadcrumb">
            <span>Ruang kerja</span>
            <span className="breadcrumb-separator">/</span>
            <strong>{pageTitle(location.pathname)}</strong>
          </div>
          <div className="topbar-right">
            <div className="topbar-user-menu">
              <button
                className="profile-trigger"
                aria-expanded={profileOpen}
                aria-haspopup="menu"
                onClick={() => setProfileOpen((open) => !open)}
              >
                <span className="topbar-avatar">{auth.session.user.username.slice(0, 1).toUpperCase()}</span>
                <span className="topbar-user-copy">
                  <strong>{displayUsername(auth.session.user.username)}</strong>
                  <span>{displayRole(auth.session.user.role)}</span>
                </span>
                <ChevronDown className="profile-chevron" aria-hidden="true" size={15} />
              </button>
              {profileOpen && (
                <div className="profile-menu" role="menu">
                  <div className="profile-menu-heading">
                    <strong>{displayUsername(auth.session.user.username)}</strong>
                    <span>{displayRole(auth.session.user.role)}</span>
                  </div>
                  <button className="profile-menu-action" role="menuitem" onClick={() => void handleLogout()}>
                    <LogOut size={16} />
                    Keluar
                  </button>
                  {logoutError && (
                    <div className="profile-menu-error" role="alert">
                      {logoutError}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </header>
        <div className="page-content">
          <Routes>
            <Route
              path="/"
              element={
                <Protected permission="dashboard:read">
                  <OverviewPage />
                </Protected>
              }
            />
            <Route
              path="/analysis"
              element={
                <Protected permission="analytics:read">
                  <AnalysisPage />
                </Protected>
              }
            />
            <Route
              path="/cases"
              element={
                <Protected permission="cases:read">
                  <CasesPage />
                </Protected>
              }
            />
            <Route
              path="/cases/:caseId"
              element={
                <Protected permission="cases:read">
                  <CaseDetailPage />
                </Protected>
              }
            />
            <Route path="/case-detail" element={<Navigate to="/cases" replace />} />
            <Route
              path="/evaluation"
              element={
                <Protected permission="analytics:read">
                  <EvaluationPage />
                </Protected>
              }
            />
            <Route
              path="/workflow"
              element={
                <ProtectedAny permissions={["batches:read", "runs:read"]}>
                  <WorkflowPage />
                </ProtectedAny>
              }
            />
            <Route
              path="/runs/:runId/cases/:caseId"
              element={
                <Protected permission="review:read">
                  <RunCaseReviewPage />
                </Protected>
              }
            />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}

function Protected({ permission, children }: { permission: string; children: ReactNode }) {
  const { state } = useAuth();
  if (state.loading || !state.session) return null;
  return state.session.permissions.includes(permission) ? (
    <>{children}</>
  ) : (
    <section className="empty-state-panel">
      <span className="panel-kicker">AKSES DIBATASI</span>
      <h2>Halaman tidak tersedia untuk role ini</h2>
      <p>Jika akses diperlukan, hubungi administrator workspace.</p>
    </section>
  );
}

function ProtectedAny({ permissions, children }: { permissions: string[]; children: ReactNode }) {
  const { state } = useAuth();
  if (state.loading || !state.session) return null;
  return permissions.some((permission) => state.session!.permissions.includes(permission)) ? (
    <>{children}</>
  ) : (
    <section className="empty-state-panel">
      <span className="panel-kicker">AKSES DIBATASI</span>
      <h2>Halaman tidak tersedia untuk role ini</h2>
      <p>Akun ini tidak memiliki permission membaca batch atau AnalysisRun.</p>
    </section>
  );
}

function LoginPage({
  onLogin,
  issue,
}: {
  onLogin: (username: string, password: string) => Promise<void>;
  issue?: "expired" | "network";
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await onLogin(username, password);
    } catch (reason) {
      setError(
        reason instanceof ApiClientError
          ? reason.message
          : "Proses masuk belum berhasil. Periksa koneksi dan coba lagi.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-shell">
      <section className="login-intro" aria-labelledby="login-intro-title">
        <div className="login-product-lockup">
          <strong>
            Claim Integrity <span>Radar</span>
          </strong>
        </div>
        <div className="login-intro-copy">
          <h1 id="login-intro-title">
            <span>Periksa yang paling penting dulu.</span>
            <span>Lindungi yang jujur.</span>
          </h1>
          <p>Bantu verifikator memahami indikasi risiko dan memprioritaskan klaim yang perlu diperiksa lebih dahulu.</p>
        </div>
        <div className="login-flow" aria-label="Alur pemeriksaan klaim">
          <div className="login-flow-track" />
          <div className="login-flow-item">
            <span>
              <ScanSearch aria-hidden="true" size={20} />
            </span>
            <strong>Deteksi</strong>
          </div>
          <div className="login-flow-item">
            <span>
              <MessageSquareText aria-hidden="true" size={20} />
            </span>
            <strong>Jelaskan</strong>
          </div>
          <div className="login-flow-item">
            <span>
              <ListFilter aria-hidden="true" size={20} />
            </span>
            <strong>Prioritaskan</strong>
          </div>
        </div>
      </section>

      <section className="login-panel">
        <div className="login-institution">
          <img src="/assets/brand/bpjs-kesehatan.svg" alt="BPJS Kesehatan" />
        </div>
        <form className="login-card" onSubmit={submit}>
          <div className="login-brand-header">
            <h2>Masuk ke akun Anda</h2>
            <p>Lanjutkan analisis dan tinjau klaim yang memerlukan perhatian.</p>
          </div>
          {issue === "expired" && (
            <div className="login-error" role="status">
              Sesi Anda telah berakhir. Silakan masuk kembali untuk melanjutkan.
            </div>
          )}
          {issue === "network" && (
            <div className="login-error" role="alert">
              Layanan sedang tidak dapat dijangkau. Periksa koneksi lalu coba masuk kembali.
            </div>
          )}
          <label>
            Nama pengguna
            <input
              autoComplete="username"
              required
              maxLength={80}
              placeholder="Masukkan nama pengguna"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              disabled={busy}
            />
          </label>
          <label>
            Kata sandi
            <span className="login-password-field">
              <input
                type={passwordVisible ? "text" : "password"}
                autoComplete="current-password"
                required
                maxLength={1024}
                placeholder="Masukkan kata sandi"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                disabled={busy}
              />
              <button
                className="password-toggle"
                type="button"
                onClick={() => setPasswordVisible((value) => !value)}
                aria-label={passwordVisible ? "Sembunyikan kata sandi" : "Tampilkan kata sandi"}
                aria-pressed={passwordVisible}
                disabled={busy}
              >
                {passwordVisible ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </span>
          </label>
          {error && (
            <div className="login-error" role="alert">
              {error}
            </div>
          )}
          <button className="login-submit" type="submit" disabled={busy}>
            {busy ? "Memverifikasi akun…" : "Masuk"}
          </button>
        </form>
      </section>
    </main>
  );
}

function pageTitle(path: string) {
  if (path === "/") return "Ringkasan pemeriksaan";
  if (path === "/analysis") return "Analisis Risiko";
  if (path === "/cases") return "Antrean Audit";
  if (path === "/case-detail" || path.startsWith("/cases/")) return "Detail Kasus";
  if (path === "/evaluation") return "Evaluasi";
  if (path === "/workflow") return "Data Klaim";
  if (path.startsWith("/runs/")) return "Review kasus dalam run";
  return "Halaman";
}

function displayUsername(username: string) {
  return username.toLowerCase() === "admin" ? "Admin" : username;
}

function displayRole(role: string) {
  const labels: Record<string, string> = {
    platform_admin: "Administrator",
    data_operator: "Operator data",
    verifikator: "Verifikator",
    audit_lead: "Pimpinan audit",
  };
  return labels[role] ?? "Pengguna workspace";
}

function NotFoundPage() {
  return (
    <section className="empty-state-panel">
      <div className="empty-state-icon">
        <FileSearch size={23} />
      </div>
      <span className="panel-kicker">HALAMAN TIDAK DITEMUKAN</span>
      <h2>Alamat ini belum tersedia</h2>
      <p>Gunakan navigasi utama untuk kembali ke halaman workspace.</p>
      <Link className="text-link" to="/">
        Kembali ke overview
      </Link>
    </section>
  );
}
