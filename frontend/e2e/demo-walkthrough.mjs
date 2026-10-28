// Demo rehearsal on the synthetic demo files only: boots the API and the dev UI on throwaway SQLite files,
// uploads each demo CSV through the UI like an operator, times import and analysis, and captures the pages
// shown in the video (including the evidence pack in print mode and as PDF).
// Usage: node e2e/demo-walkthrough.mjs <output-dir>
import { chromium } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdtemp, mkdir, rm } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const [outDir] = process.argv.slice(2);
if (!outDir) throw new Error("Usage: node e2e/demo-walkthrough.mjs <output-dir>");
const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const root = path.join(frontendDir, "..");
const backendDir = path.join(root, "backend");
const demoDir = path.join(root, "demo-data");
const python = path.join(backendDir, ".venv", "Scripts", "python.exe");
const temp = await mkdtemp(path.join(os.tmpdir(), "cir-demo-walkthrough-"));
await mkdir(outDir, { recursive: true });
const port = () => new Promise(resolve => { const s = net.createServer().listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolve(p)); }); });
const [apiPort, uiPort] = [await port(), await port()];
const admin = "demo-admin", password = randomBytes(18).toString("base64url");
const dbEnv = { CIR_DATABASE_URL: "", CIR_AUTH_DB_PATH: path.join(temp, "auth.sqlite3"), CIR_BATCH_DB_PATH: path.join(temp, "batch.sqlite3"),
  CIR_REVIEW_DB_PATH: path.join(temp, "review.sqlite3"), CIR_COOKIE_SECURE: "false", BPJS_FKRTL_SAMPLE_PATH: "" };
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
const timings = [];
try {
  await ready(`http://127.0.0.1:${apiPort}/health`);
  await ready(base);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(30_000);
  const shot = async name => { await page.waitForTimeout(1000); await page.screenshot({ path: path.join(outDir, name + ".png"), fullPage: true }); };
  await page.goto(base);
  await page.getByLabel("Nama pengguna").fill(admin);
  await page.locator('input[autocomplete="current-password"]').fill(password);
  await page.getByRole("button", { name: "Masuk", exact: true }).click();
  await page.getByRole("button", { name: new RegExp(admin) }).waitFor();

  for (const name of ["demo-1-faskes-jujur", "demo-2-kasus-kpk", "demo-3-operasional"]) {
    await page.goto(base + "/workflow");
    await page.locator('input[type="file"]').setInputFiles(path.join(demoDir, `${name}.csv`));
    await page.getByLabel("Nama data").fill(`synthetic-${name}`);
    let started = Date.now();
    const created = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/runs", { timeout: 600_000 });
    await page.getByRole("button", { name: "Unggah dan analisis" }).click();
    await page.getByRole("region", { name: "File tersimpan" }).locator("tr", { hasText: name })
      .getByText("Siap dianalisis", { exact: true }).waitFor({ timeout: 300_000 });
    const importSeconds = (Date.now() - started) / 1000;
    started = Date.now();
    const response = await created;
    await page.getByText("Ringkasan analisis", { exact: true }).waitFor({ timeout: 120_000 });
    timings.push({ name, importSeconds, analysisSeconds: (Date.now() - started) / 1000, status: response.status() });
    console.log(JSON.stringify(timings.at(-1)));
  }
  await shot("0-data-analisis");

  // The run picker lists the three analyses by file name.
  await page.goto(base + "/");
  await page.getByRole("heading", { name: "Prioritas hari ini" }).waitFor();
  await page.getByLabel("Pilih hasil analisis").waitFor();
  const options = await page.getByLabel("Pilih hasil analisis").locator("option").allTextContents();
  console.log("run picker:", JSON.stringify(options));
  for (const [index, name] of ["demo-3", "demo-2", "demo-1"].entries()) {
    await page.getByLabel("Pilih hasil analisis").selectOption({ index });
    await page.getByRole("heading", { name: "Prioritas hari ini" }).waitFor();
    await shot(`1-beranda-${name}`);
  }
  // demo-2: the KPK-like hospital in Faskes, its detail and its evidence pack.
  await page.getByLabel("Pilih hasil analisis").selectOption({ index: 1 });
  await page.goto(page.url().replace(/\/(\?|$)/, "/facilities$1"));
  await page.locator("tr[data-group-id]").first().waitFor();
  await shot("2-faskes-demo-2");
  await page.locator("tr[data-group-id] a").first().click();
  await page.getByTestId("facility-verdict").waitFor();
  await shot("3-faskes-rincian-demo-2");
  await page.getByRole("link", { name: /Buat paket bukti/ }).click();
  await page.getByRole("table", { name: "Daftar klaim sampel" }).waitFor();
  await page.waitForFunction(() => !document.body.innerText.includes("Memuat…"), null, { timeout: 60_000 });
  await shot("4-paket-bukti-layar");
  await page.emulateMedia({ media: "print" });
  await shot("5-paket-bukti-cetak");
  await page.pdf({ path: path.join(outDir, "paket-bukti-demo-2.pdf"), format: "A4", printBackground: true });
  await page.emulateMedia({ media: "screen" });
  // Queue and one claim.
  await page.goto(base + "/cases");
  await page.locator("a.queue-item").first().click();
  await page.getByRole("region", { name: "Ringkasan klaim" }).waitFor();
  await shot("6-antrean-klaim");
  await browser.close();
  console.log("timings:", JSON.stringify(timings));
} finally {
  api.kill(); ui.kill();
  await new Promise(r => setTimeout(r, 1500));
  await rm(temp, { recursive: true, force: true }).catch(() => undefined);
}
