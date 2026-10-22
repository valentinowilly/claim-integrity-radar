import { useEffect, useState } from "react";
import { Activity, ChevronDown, ClipboardCheck, FileSearch, Fingerprint, LayoutDashboard, LifeBuoy, Menu, Radar, ShieldCheck, SlidersHorizontal, X } from "lucide-react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { getHealth, type HealthResponse } from "./api/client";
import AnalysisPage from "./pages/AnalysisPage";
import CaseDetailPage from "./pages/CaseDetailPage";
import CasesPage from "./pages/CasesPage";
import EvaluationPage from "./pages/EvaluationPage";
import OverviewPage from "./pages/OverviewPage";

const navigation = [
  { label: "Overview", to: "/", icon: LayoutDashboard, end: true },
  { label: "Analisis Risiko", to: "/analysis", icon: Radar, end: true },
  { label: "Antrean Audit", to: "/cases", icon: ClipboardCheck, end: true },
  { label: "Detail Kasus", to: "/cases", icon: FileSearch, end: true },
  { label: "Evaluasi", to: "/evaluation", icon: Activity, end: true },
];

type ConnectionState = "loading" | "connected" | "disconnected";

export default function App() {
  const [connection, setConnection] = useState<ConnectionState>("loading");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
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
          {navigation.map(({ label, to, icon: Icon, end }) => (
            <NavLink key={label} to={to} end={end} className={({ isActive }) => {
              const detailActive = label === "Detail Kasus" && location.pathname.startsWith("/cases/");
              const queueActive = label === "Antrean Audit" && location.pathname === "/cases";
              return `nav-link${(detailActive || queueActive || isActive && label !== "Detail Kasus") ? " nav-link-active" : ""}`;
            }}>
              <Icon size={18} strokeWidth={1.8} /><span>{label}</span>
              {label === "Detail Kasus" && <span className="nav-context">pilih kasus</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-spacer" />
        <div className="privacy-note"><div className="privacy-icon"><Fingerprint size={17} /></div><div><strong>Privasi dan konteks</strong><p>Demo memakai data sintetis, bukan dataset BPJS.</p></div></div>
        <div className="help-link"><LifeBuoy size={17} strokeWidth={1.8} /><span>Decision support untuk auditor</span></div>
        <div className="sidebar-footer"><div className="user-avatar">A</div><div className="user-copy"><strong>Auditor</strong><span>Tinjauan manusia tetap utama</span></div><SlidersHorizontal size={17} className="user-settings" /></div>
      </aside>

      {menuOpen && <button className="mobile-scrim" aria-label="Tutup navigasi" onClick={() => setMenuOpen(false)} />}
      <main className="main-panel">
        <header className="topbar">
          <button className="icon-button mobile-menu-button" aria-label="Buka navigasi" onClick={() => setMenuOpen(true)}><Menu size={20} /></button>
          <div className="breadcrumb"><span>Workspace</span><span className="breadcrumb-separator">/</span><strong>{pageTitle(location.pathname)}</strong></div>
          <div className="topbar-right"><BackendStatus connection={connection} health={health} /><span className="topbar-divider" /><div className="topbar-user"><span className="topbar-avatar">A</span><ChevronDown size={14} /></div></div>
        </header>
        <div className="page-content">
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/analysis" element={<AnalysisPage />} />
            <Route path="/cases" element={<CasesPage />} />
            <Route path="/cases/:caseId" element={<CaseDetailPage />} />
            <Route path="/case-detail" element={<Navigate to="/cases" replace />} />
            <Route path="/evaluation" element={<EvaluationPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </div>
        <footer className="page-footer"><span>Claim Integrity Radar</span><span>Decision Support for Claims Audit</span><span>v0.1.0</span></footer>
      </main>
    </div>
  );
}

function pageTitle(path: string) {
  if (path === "/") return "Overview";
  if (path === "/analysis") return "Analisis Risiko";
  if (path === "/cases") return "Antrean Audit";
  if (path === "/case-detail" || path.startsWith("/cases/")) return "Detail Kasus";
  if (path === "/evaluation") return "Evaluasi";
  return "Halaman";
}

function BackendStatus({ connection, health }: { connection: ConnectionState; health: HealthResponse | null }) {
  const label = connection === "loading" ? "Memeriksa API" : connection === "connected" ? "API terhubung" : "API tidak terjangkau";
  return <div className={`backend-status status-${connection}`} role="status" aria-live="polite"><span className="status-dot" /><span>{label}</span>{health && <span className="status-version">v{health.version}</span>}</div>;
}

function NotFoundPage() {
  return <section className="empty-state-panel"><div className="empty-state-icon"><FileSearch size={23} /></div><span className="panel-kicker">HALAMAN TIDAK DITEMUKAN</span><h2>Alamat ini belum tersedia</h2><p>Gunakan navigasi utama untuk kembali ke halaman workspace.</p><Link className="text-link" to="/">Kembali ke overview</Link></section>;
}
