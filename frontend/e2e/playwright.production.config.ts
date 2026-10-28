import base from "./playwright.config";

// Same suite, but the UI is a fresh production build served by `vite preview` (static files with
// /api and /health proxied to the API on one origin), not the Vite development server.
process.env.CIR_E2E_UI_MODE = "production";

export default base;
