import { Fragment, useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  Building2,
  ChevronDown,
  ClipboardCheck,
  Database,
  Eye,
  EyeOff,
  FileSearch,
  LayoutDashboard,
  ListFilter,
  LogOut,
  Menu,
  MessageSquareText,
  ScanSearch,
  X,
  Upload,
} from "lucide-react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import AnalysisPage from "./pages/AnalysisPage";
import CasesPage from "./pages/CasesPage";
import FacilitiesPage, { EvidencePackPage, FacilityDetailPage } from "./pages/FacilitiesPage";
import OverviewPage from "./pages/OverviewPage";
import WorkflowPage from "./pages/WorkflowPage";
import { useAuth } from "./auth/AuthContext";
import { ApiClientError } from "./api/client";
import { NotificationCenter } from "./notifications/NotificationCenter";

type NavItem = { label: string; to: string; icon: typeof LayoutDashboard; group: string; allowed: (permissions: Set<string>) => boolean };
// Two groups: daily review work first, then where data comes in (upload, automatic intake, history).
const navigation: NavItem[] = [
  { label: "Beranda", to: "/", icon: LayoutDashboard, group: "Pemeriksaan", allowed: p => p.has("runs:results:read") },
  { label: "Antrean Tinjauan", to: "/cases", icon: ClipboardCheck, group: "Pemeriksaan", allowed: p => p.has("cases:read") && p.has("runs:results:read") },
  { label: "Faskes", to: "/facilities", icon: Building2, group: "Pemeriksaan", allowed: p => p.has("runs:results:read") },
  { label: "Data & Analisis", to: "/workflow", icon: Database, group: "Data klaim", allowed: p => p.has("batches:read") || p.has("runs:read") },
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
      setLogoutError("Sesi belum dapat diakhiri. Coba keluar lagi saat server tersedia.");
    }
  }

  if (auth.loading)
    return (
      <div className="auth-loading" role="status">
        Memulihkan sesi Anda…
      </div>
    );
  if (!auth.session) return <LoginPage onLogin={signIn} issue={auth.issue} />;
  const permissions = new Set(auth.session.permissions);
  const visibleNavigation = navigation.filter(item => item.allowed(permissions));
  const canReadResults = permissions.has("runs:results:read");

  return (
    <NotificationCenter userId={auth.session.user.user_id}>
      <div className="app-shell green-shell">
        <aside className={`side-nav${menuOpen ? " open" : ""}`}>
          <div className="side-brand">
            <span className="side-logo"><img src="/assets/brand/bpjs-kesehatan.svg" alt="BPJS Kesehatan" /></span>
            <strong>Claim Integrity Radar</strong>
            <span>Prioritas pemeriksaan klaim</span>
          </div>
          <nav className="side-links" aria-label="Navigasi utama">
            {visibleNavigation.map(({ label, to, icon: Icon, group }, index) => (<Fragment key={label}>
              {(index === 0 || visibleNavigation[index - 1].group !== group) && <span className="side-group">{group}</span>}
              <NavLink
                key={label}
                to={`${to}${location.search}`}
                end={to === "/"}
                onClick={() => setMenuOpen(false)}
                className={({ isActive }) => {
                  const reviewActive = label === "Antrean Tinjauan" && location.pathname.startsWith("/runs/");
                  return `side-link${isActive || reviewActive ? " active" : ""}`;
                }}
              >
                <Icon size={18} strokeWidth={2} />
                <span>{label}</span>
              </NavLink>
            </Fragment>))}
          </nav>
          <div className="side-foot">Hasil sistem adalah petunjuk pemeriksaan. Keputusan tetap di tangan petugas.</div>
        </aside>
        {menuOpen && <button className="side-scrim" aria-label="Tutup navigasi" onClick={() => setMenuOpen(false)} />}
        <header className="side-topbar">
          <button className="icon-button mobile-menu-button" aria-label={menuOpen ? "Tutup navigasi" : "Buka navigasi"} aria-expanded={menuOpen}
            onClick={() => setMenuOpen(open => !open)}>
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          {permissions.has("batches:write") && (
            <Link className="button button-primary topbar-upload" to="/workflow?unggah=1">
              <Upload size={15} aria-hidden="true" /><span>Unggah data</span>
            </Link>
          )}
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
        </header>
        <main className="main-panel">
          {/* Keyed by section, so moving between claims of the queue (/runs/…/cases/…) never remounts it. */}
          <div className="page-content page-enter" key={location.pathname.startsWith("/runs/") ? "cases" : location.pathname.split("/")[1] || "home"}>
            <Routes>
              {/* Each role starts where it works: operators cannot read results, so they start at Data & Analisis. */}
              <Route path="/" element={canReadResults ? <OverviewPage /> : <Navigate to={`/workflow${location.search}`} replace />} />
              <Route path="/analysis" element={<Protected permission="analytics:read"><AnalysisPage /></Protected>} />
              <Route path="/cases" element={<Protected permission="cases:read"><CasesPage /></Protected>} />
              <Route path="/cases/:caseId" element={<Navigate to="/cases" replace />} />
              <Route path="/case-detail" element={<Navigate to="/cases" replace />} />
              <Route path="/performance" element={<Navigate to="/" replace />} />
              <Route path="/facilities" element={<Protected permission="runs:results:read"><FacilitiesPage /></Protected>} />
              <Route path="/facilities/:groupId" element={<Protected permission="runs:results:read"><FacilityDetailPage /></Protected>} />
              <Route path="/facilities/:groupId/paket" element={<Protected permission="runs:results:read"><EvidencePackPage /></Protected>} />
              <Route path="/workflow" element={<ProtectedAny permissions={["batches:read", "runs:read"]}><WorkflowPage /></ProtectedAny>} />
              <Route path="/runs/:runId/cases/:caseId" element={<Protected permission="review:read"><CasesPage /></Protected>} />
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
          </div>
        </main>
      </div>
    </NotificationCenter>
  );
}

function RestrictedPanel() {
  return (
    <section className="empty-state-panel">
      <span className="panel-kicker">AKSES TERBATAS</span>
      <h2>Halaman ini tidak tersedia untuk peran Anda</h2>
      <p>Bila Anda memerlukan akses, hubungi administrator.</p>
    </section>
  );
}

function Protected({ permission, children }: { permission: string; children: ReactNode }) {
  const { state } = useAuth();
  if (state.loading || !state.session) return null;
  return state.session.permissions.includes(permission) ? <>{children}</> : <RestrictedPanel />;
}

function ProtectedAny({ permissions, children }: { permissions: string[]; children: ReactNode }) {
  const { state } = useAuth();
  if (state.loading || !state.session) return null;
  return permissions.some((permission) => state.session!.permissions.includes(permission)) ? <>{children}</> : <RestrictedPanel />;
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
      setError(reason instanceof ApiClientError ? reason.message : "Gagal masuk. Periksa koneksi lalu coba lagi.");
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
            <span>Tinjau yang paling penting lebih dulu.</span>
            <span>Lindungi klaim yang jujur.</span>
          </h1>
          <p>Membantu petugas menentukan klaim dan faskes yang perlu diperiksa lebih dulu, lengkap dengan alasannya.</p>
        </div>
        <div className="login-flow" aria-label="Alur tinjauan klaim">
          <div className="login-flow-track" />
          <div className="login-flow-item">
            <span><ScanSearch aria-hidden="true" size={20} /></span>
            <strong>Deteksi</strong>
          </div>
          <div className="login-flow-item">
            <span><MessageSquareText aria-hidden="true" size={20} /></span>
            <strong>Jelaskan</strong>
          </div>
          <div className="login-flow-item">
            <span><ListFilter aria-hidden="true" size={20} /></span>
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
            <p>Lanjutkan analisis dan tinjau klaim yang perlu perhatian.</p>
          </div>
          {issue === "expired" && (
            <div className="login-error" role="status">
              Sesi Anda telah berakhir. Silakan masuk kembali.
            </div>
          )}
          {issue === "network" && (
            <div className="login-error" role="alert">
              Server tidak dapat dihubungi. Periksa koneksi lalu coba lagi.
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
            {busy ? "Sedang masuk…" : "Masuk"}
          </button>
        </form>
      </section>
    </main>
  );
}


function displayUsername(username: string) {
  return username.toLowerCase() === "admin" ? "Admin" : username;
}

export function displayRole(role: string) {
  const labels: Record<string, string> = {
    platform_admin: "Administrator",
    data_operator: "Operator data",
    verifikator: "Verifikator",
    audit_lead: "Verifikator senior",
  };
  return labels[role] ?? "Pengguna";
}

function NotFoundPage() {
  return (
    <section className="empty-state-panel">
      <div className="empty-state-icon">
        <FileSearch size={23} />
      </div>
      <span className="panel-kicker">HALAMAN TIDAK DITEMUKAN</span>
      <h2>Alamat ini tidak tersedia</h2>
      <p>Gunakan menu di samping untuk kembali.</p>
      <Link className="text-link" to="/">
        Kembali ke Beranda
      </Link>
    </section>
  );
}
