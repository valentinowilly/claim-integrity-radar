// Layout audit on synthetic demo data only: boots the API and the dev UI on throwaway SQLite files,
// uploads two demo files, then visits every page at desktop, tablet and phone widths. For each page it
// saves a screenshot and lists elements that stick out of the viewport or clip their text.
// Usage: node e2e/ui-audit.mjs <output-dir>
import { chromium } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const [outDir] = process.argv.slice(2);
if (!outDir) throw new Error("Usage: node e2e/ui-audit.mjs <output-dir>");
const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const backendDir = path.join(frontendDir, "..", "backend");
const demoDir = path.join(frontendDir, "..", "demo-data");
const python = path.join(backendDir, ".venv", "Scripts", "python.exe");
const temp = await mkdtemp(path.join(os.tmpdir(), "cir-ui-audit-"));
await mkdir(outDir, { recursive: true });
const port = () => new Promise(resolve => { const s = net.createServer().listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolve(p)); }); });
const [apiPort, uiPort] = [await port(), await port()];
const admin = "demo-admin", password = randomBytes(18).toString("base64url");
const dbEnv = { CIR_DATABASE_URL: "", CIR_AUTH_DB_PATH: path.join(temp, "auth.sqlite3"), CIR_BATCH_DB_PATH: path.join(temp, "batch.sqlite3"),
  CIR_REVIEW_DB_PATH: path.join(temp, "review.sqlite3"), CIR_COOKIE_SECURE: "false", BPJS_FKRTL_SAMPLE_PATH: "", CIR_INBOX_DIR: "" };
const seed = spawnSync(python, ["-c", [
  "import os", "from app.security.auth import AuthStore",
  "s = AuthStore(os.environ['CIR_AUTH_DB_PATH']); k = os.environ['K']",
  "s.create_bootstrap_admin(os.environ['U'], os.environ['P'], k, k)"].join("\n")],
  { cwd: backendDir, env: { ...process.env, ...dbEnv, U: admin, P: password, K: randomBytes(32).toString("base64url") }, encoding: "utf8" });
if (seed.status !== 0) throw new Error("seed failed: " + seed.stderr.slice(-400));
const api = spawn(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)], { cwd: backendDir, env: { ...process.env, ...dbEnv }, stdio: "ignore" });
const ui = spawn(process.execPath, [path.join(frontendDir, "node_modules", "vite", "bin", "vite.js"), "--host", "127.0.0.1", "--port", String(uiPort), "--strictPort"],
  { cwd: frontendDir, env: { ...process.env, VITE_BACKEND_URL: `http://127.0.0.1:${apiPort}` }, stdio: "ignore" });
const ready = async url => { for (let i = 0; i < 150; i++) { try { if ((await fetch(url)).ok) return; } catch { /* starting */ } await new Promise(r => setTimeout(r, 300)); } throw new Error("not ready: " + url); };
const base = `http://127.0.0.1:${uiPort}`;
const report = [];

// Elements wider than the viewport, and text cut off by its own box (ellipsis or hidden overflow).
const inspect = () => {
  const width = document.documentElement.clientWidth;
  const label = el => `${el.tagName.toLowerCase()}${el.className && typeof el.className === "string" ? "." + el.className.trim().split(/\s+/).slice(0, 2).join(".") : ""}`;
  const out = [], clipped = [];
  for (const el of document.querySelectorAll("body *")) {
    const box = el.getBoundingClientRect();
    if (!box.width || !box.height || getComputedStyle(el).position === "fixed") continue;
    if (box.right > width + 2 && !el.closest(".table-scroll"))
      out.push(`${label(el)} "${(el.textContent || "").trim().slice(0, 30)}" kanan=${Math.round(box.right)} induk=${label(el.parentElement)}`);
    const style = getComputedStyle(el);
    if (el.children.length === 0 && el.textContent.trim() && el.scrollWidth > el.clientWidth + 2
        && (style.textOverflow === "ellipsis" || style.overflow === "hidden") && !el.closest(".table-scroll") && !el.closest(".sr-only"))
      clipped.push(`${label(el)}: "${el.textContent.trim().slice(0, 60)}"`);
  }
  // The outermost elements wider than the viewport, with their CSS display, show where the width comes from.
  const wide = [];
  for (const el of document.querySelectorAll("body *")) {
    const box = el.getBoundingClientRect();
    if (box.width > width + 2 && getComputedStyle(el).position !== "fixed" && !(el.parentElement && el.parentElement.getBoundingClientRect().width > width + 2))
      wide.push(`${label(el)} [${getComputedStyle(el).display}; ${getComputedStyle(el).gridTemplateColumns?.slice(0, 40) ?? ""}] lebar=${Math.round(box.width)} induk=${label(el.parentElement)}`);
  }
  return { pageWidth: document.documentElement.scrollWidth, viewport: width, out: [...new Set(out)].slice(0, 12),
    clipped: [...new Set(clipped)].slice(0, 12), wide: wide.slice(0, 6) };
};

try {
  await ready(`http://127.0.0.1:${apiPort}/health`);
  await ready(base);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(30_000);
  await page.goto(base);
  await page.getByLabel("Nama pengguna").fill(admin);
  await page.locator('input[autocomplete="current-password"]').fill(password);
  await page.getByRole("button", { name: "Masuk", exact: true }).click();
  await page.getByRole("button", { name: new RegExp(admin) }).waitFor();
  // Empty state first: what a brand-new user sees.
  await page.goto(base + "/");
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(outDir, "00-beranda-kosong-desktop.png"), fullPage: true });
  for (const name of ["demo-2-kasus-kpk", "demo-3-operasional"]) {
    await page.goto(base + "/workflow");
    await page.locator('input[type="file"]').setInputFiles(path.join(demoDir, `${name}.csv`));
    await page.getByLabel("Nama data").fill(name);
    const created = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/runs", { timeout: 600_000 });
    await page.getByRole("button", { name: /Unggah dan analisis/ }).click();
    await created;
    await page.getByText("Ringkasan analisis", { exact: true }).waitFor({ timeout: 120_000 });
  }
  await page.goto(base + "/cases");
  await page.locator("a.queue-item").first().click();
  await page.getByRole("region", { name: "Ringkasan klaim" }).waitFor();
  const caseUrl = page.url();
  await page.goto(base + "/facilities");
  await page.locator("tr[data-group-id] a").first().click();
  await page.getByTestId("facility-verdict").waitFor();
  const facilityUrl = page.url();
  const pages = [["beranda", "/"], ["antrean", "/cases"], ["klaim", caseUrl.replace(base, "")], ["faskes", "/facilities"],
    ["faskes-rincian", facilityUrl.replace(base, "")], ["data", "/workflow"], ["rincian-analisis", "/analysis"]];
  for (const [width, height, tag] of [[1440, 900, "desktop"], [1024, 768, "tablet"], [390, 844, "ponsel"]]) {
    await page.setViewportSize({ width, height });
    for (const [name, url] of pages) {
      await page.goto(base + url);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1200);
      const result = await page.evaluate(inspect);
      report.push({ tag, name, ...result });
      await page.screenshot({ path: path.join(outDir, `${tag}-${name}.png`), fullPage: true });
    }
  }
  await browser.close();
  await writeFile(path.join(outDir, "audit.json"), JSON.stringify(report, null, 1));
  for (const item of report) {
    const flag = item.pageWidth > item.viewport + 2 || item.out.length || item.clipped.length;
    console.log(`${flag ? "!!" : "ok"} ${item.tag} ${item.name}: lebar halaman ${item.pageWidth}/${item.viewport}`
      + (item.out.length ? `\n   keluar layar: ${item.out.join(" | ")}` : "") + (item.clipped.length ? `\n   terpotong: ${item.clipped.join(" | ")}` : "")
      + (item.wide?.length ? `\n   pelebar: ${item.wide.join("\n            ")}` : ""));
  }
} finally {
  api.kill(); ui.kill();
  await new Promise(r => setTimeout(r, 1500));
  await rm(temp, { recursive: true, force: true }).catch(() => undefined);
}
