// Visual tour on synthetic data only: boots the API and the dev UI on throwaway SQLite files,
// imports a synthetic CSV, runs one analysis and screenshots the main pages.
// Usage: node e2e/visual-tour.mjs <synthetic.csv> <output-dir>
import { chromium } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdtemp, mkdir, rm } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const [csvPath, outDir] = process.argv.slice(2);
if (!csvPath || !outDir) throw new Error("Usage: node e2e/visual-tour.mjs <synthetic.csv> <output-dir>");
const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const backendDir = path.join(frontendDir, "..", "backend");
const python = path.join(backendDir, ".venv", "Scripts", "python.exe");
const temp = await mkdtemp(path.join(os.tmpdir(), "cir-visual-tour-"));
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
try {
  await ready(`http://127.0.0.1:${apiPort}/health`);
  await ready(base);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const shot = async name => { await page.waitForTimeout(900); await page.screenshot({ path: path.join(outDir, name + ".png"), fullPage: true }); };
  await page.goto(base);
  await page.getByLabel("Nama pengguna").fill(admin);
  await page.locator('input[autocomplete="current-password"]').fill(password);
  await page.getByRole("button", { name: "Masuk", exact: true }).click();
  await page.getByRole("button", { name: new RegExp(admin) }).waitFor().catch(async error => {
    await page.screenshot({ path: path.join(outDir, "login-failed.png") });
    throw error;
  });
  await page.goto(base + "/workflow");
  await page.locator("summary.upload-summary").click();
  await page.locator('input[type="file"]').waitFor({ state: "attached", timeout: 10_000 }).catch(async error => {
    await page.screenshot({ path: path.join(outDir, "upload-failed.png"), fullPage: true });
    throw error;
  });
  await page.locator('input[type="file"]').setInputFiles(csvPath);
  await page.getByLabel("Nama data").fill("synthetic-demo-tour");
  await page.getByRole("button", { name: "Unggah dan analisis" }).click();
  await page.getByText("Ringkasan analisis", { exact: true }).waitFor({ timeout: 120_000 });
  await shot("4-data-analisis");
  await page.goto(base + "/");
  await page.getByRole("heading", { name: "Prioritas hari ini" }).waitFor();
  await shot("1-beranda");
  await page.goto(base + "/facilities");
  await shot("2-faskes");
  const firstGroup = page.locator("tr[data-group-id] a").first();
  if (await firstGroup.count()) { await firstGroup.click(); await shot("2b-faskes-rincian"); }
  await page.goto(base + "/cases");
  await page.locator("a.queue-item").first().click();
  await page.getByRole("region", { name: "Ringkasan klaim" }).waitFor();
  await shot("3-antrean-klaim");
  await page.setViewportSize({ width: 390, height: 844 });
  for (const [name, route] of [["5-beranda-mobile", "/"], ["6-antrean-mobile", "/cases"], ["7-faskes-mobile", "/facilities"]]) {
    await page.goto(base + route);
    await page.waitForTimeout(1200);
    const wide = await page.evaluate(() => [...document.querySelectorAll("body *")]
      .filter(el => el.getBoundingClientRect().right > window.innerWidth + 1 && !el.closest(".table-scroll"))
      .slice(0, 6).map(el => `${el.tagName.toLowerCase()}.${[...el.classList].join(".")} → ${Math.round(el.getBoundingClientRect().right)}`));
    console.log(name, "overflow:", JSON.stringify(wide));
    await shot(name);
  }
  await browser.close();
  console.log("screenshots in " + outDir);
} finally {
  api.kill(); ui.kill();
  await new Promise(r => setTimeout(r, 1500));
  await rm(temp, { recursive: true, force: true }).catch(() => undefined);
}
