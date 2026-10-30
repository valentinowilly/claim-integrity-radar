// Visual tour on synthetic data only: boots the API and the dev UI on throwaway SQLite files,
// imports a synthetic CSV, runs one analysis and screenshots the main pages.
// Several files make several analyses, so the overview comparisons and trend lines have data.
// Every page is captured in the light and the dark theme.
// Usage: node e2e/visual-tour.mjs <synthetic.csv> [more.csv ...] <output-dir>
import { chromium } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdtemp, mkdir, rm } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const args = process.argv.slice(2);
const outDir = args.pop();
const csvPaths = args;
if (!csvPaths.length || !outDir) throw new Error("Usage: node e2e/visual-tour.mjs <synthetic.csv> [more.csv ...] <output-dir>");
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
  // 1.8 s: after the 1.1 s count-up of headline numbers.
  const shot = async name => { await page.waitForTimeout(1800); await page.screenshot({ path: path.join(outDir, name + ".png"), fullPage: true }); };
  await page.goto(base);
  await page.getByLabel("Nama pengguna").fill(admin);
  await page.locator('input[autocomplete="current-password"]').fill(password);
  await page.getByRole("button", { name: "Masuk", exact: true }).click();
  await page.getByRole("button", { name: new RegExp(admin) }).waitFor().catch(async error => {
    await page.screenshot({ path: path.join(outDir, "login-failed.png") });
    throw error;
  });
  for (const [index, csvPath] of csvPaths.entries()) {
    await page.goto(base + "/workflow");
    await page.locator('input[type="file"]').waitFor({ state: "attached", timeout: 10_000 }).catch(async error => {
      await page.screenshot({ path: path.join(outDir, "upload-failed.png"), fullPage: true });
      throw error;
    });
    await page.locator('input[type="file"]').setInputFiles(csvPath);
    await page.getByLabel("Nama data").fill(`synthetic-demo-tour-${index + 1}`);
    await page.getByRole("button", { name: "Unggah dan analisis" }).click();
    await page.getByText("Ringkasan analisis", { exact: true }).waitFor({ timeout: 300_000 });
  }
  // A few verifier decisions, so the accuracy chart on the Tren page has data.
  await page.goto(base + "/cases");
  for (const [index, label] of [[0, "Benar, perlu ditindaklanjuti"], [1, "Benar, perlu ditindaklanjuti"], [2, "Ternyata wajar"], [3, "Benar, perlu ditindaklanjuti"]]) {
    await page.locator("a.queue-item").nth(index).click();
    await page.getByRole("region", { name: "Ringkasan klaim" }).waitFor();
    await page.getByRole("radio", { name: label }).check();
    await page.getByRole("button", { name: "Simpan keputusan" }).click();
    await page.getByText("Keputusan tinjauan tersimpan.").waitFor({ timeout: 15_000 }).catch(() => console.log("decision not saved", index));
  }
  for (const theme of ["light", "dark"]) {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.evaluate(value => localStorage.setItem("cir:theme", value), theme);
    const suffix = "-" + theme;
    await page.goto(base + "/workflow");
    await page.getByText("Ringkasan analisis", { exact: true }).waitFor({ timeout: 60_000 }).catch(() => undefined);
    await shot("4-data-analisis" + suffix);
    await page.goto(base + "/");
    await page.getByRole("heading", { name: "Prioritas hari ini" }).waitFor();
    await shot("1-beranda" + suffix);
    await page.goto(base + "/facilities");
    await shot("2-faskes" + suffix);
    const firstGroup = page.locator("tr[data-group-id] a").first();
    if (await firstGroup.count()) { await firstGroup.click(); await shot("2b-faskes-rincian" + suffix); }
    await page.goto(base + "/cases");
    await page.locator("a.queue-item").first().waitFor();
    await page.locator("section.queue-list-card").screenshot({ path: path.join(outDir, "3a-daftar-antrean" + suffix + ".png") });
    await page.locator("button.queue-filter-toggle").click();
    await page.locator("section.queue-list-card").screenshot({ path: path.join(outDir, "3a2-daftar-saring" + suffix + ".png") });
    await page.locator("button.queue-filter-toggle").click();
    await page.locator("a.queue-item").first().click();
    await page.getByRole("region", { name: "Ringkasan klaim" }).waitFor();
    await shot("3-antrean-klaim" + suffix);
    // Phase 3: one claim per kind of explanation, capturing only the relevant cards.
    for (const [name, check, selector] of [
      ["3b-catatan-identik", "cloned_clinical_note_candidate", '[data-testid="clinical-note"]'],
      ["3c-sorotan-lama-rawat", "length_of_stay_extreme_candidate", '[data-testid="clinical-note"]'],
      ["3d-kunjungan", "rapid_readmission_candidate", '[data-testid="visit-timeline"]'],
      ["3e-halaman-klaim", "rapid_readmission_candidate", "main"],
    ]) {
      await page.goto(base + "/cases?check=" + check);
      const item = page.locator("a.queue-item").first();
      if (!(await item.waitFor({ timeout: 15_000 }).then(() => true).catch(() => false))) { console.log(name + suffix, "no claim"); continue; }
      await item.click();
      await page.getByRole("region", { name: "Ringkasan klaim" }).waitFor();
      const card = page.locator(selector).first();
      await card.waitFor({ timeout: 8_000 }).catch(() => undefined);
      await page.waitForTimeout(700);
      if (await card.count()) await card.screenshot({ path: path.join(outDir, name + suffix + ".png") });
      else console.log(name + suffix, "card not shown");
    }
    await page.goto(base + "/analysis");
    await shot("8-analisis" + suffix);
    await page.goto(base + "/trend");
    await page.getByRole("heading", { name: "Tren", exact: true }).waitFor();
    await shot("10-tren" + suffix);
    // Ctrl+K: search a claim reference, then the shortcut list in the queue.
    await page.keyboard.press("Control+k");
    await page.getByLabel("Cari", { exact: true }).fill("case");
    await page.locator(".palette-item").nth(3).waitFor({ timeout: 10_000 }).catch(() => undefined);
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(outDir, "11-cari-ctrl-k" + suffix + ".png") });
    await page.keyboard.press("Escape");
    await page.goto(base + "/cases");
    await page.locator("a.queue-item").first().waitFor();
    await page.keyboard.press("j");
    await page.getByRole("region", { name: "Ringkasan klaim" }).waitFor();
    await page.keyboard.press("?");
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(outDir, "12-pintasan" + suffix + ".png") });
    await page.keyboard.press("Escape");
    await page.goto(base + "/map");
    await page.getByRole("heading", { name: "Peta Risiko" }).waitFor();
    await shot("9-peta" + suffix);
    const province = page.locator("path.risk-map-province.step-4, path.risk-map-province.step-3").first();
    if (await province.count()) {
      await province.hover();
      await page.waitForTimeout(400);
      console.log("map tooltip" + suffix + ":", await page.locator(".risk-map-tip").count(), await page.locator(".risk-map-tip strong").first().textContent().catch(() => ""));
      await page.screenshot({ path: path.join(outDir, "9b-peta-hover" + suffix + ".png") });
      await province.click();
      await shot("9c-peta-provinsi" + suffix);
    }
    await page.getByRole("button", { name: "Petak" }).click();
    await shot("9d-petak" + suffix);
    await page.setViewportSize({ width: 390, height: 844 });
    for (const [name, route] of [["5-beranda-mobile", "/"], ["6-antrean-mobile", "/cases"], ["7-faskes-mobile", "/facilities"]]) {
      await page.goto(base + route);
      await page.waitForTimeout(1200);
      const wide = await page.evaluate(() => [...document.querySelectorAll("body *")]
        .filter(el => el.getBoundingClientRect().right > window.innerWidth + 1 && !el.closest(".table-scroll"))
        .slice(0, 6).map(el => `${el.tagName.toLowerCase()}.${[...el.classList].join(".")} → ${Math.round(el.getBoundingClientRect().right)}`));
      console.log(name + suffix, "overflow:", JSON.stringify(wide));
      await shot(name + suffix);
    }
  }
  // The login page in both themes (after signing out).
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.context().clearCookies();
  for (const theme of ["light", "dark"]) {
    await page.evaluate(value => localStorage.setItem("cir:theme", value), theme);
    await page.goto(base);
    await page.getByLabel("Nama pengguna").waitFor();
    await shot("0-login-" + theme);
  }
  await browser.close();
  console.log("screenshots in " + outDir);
} finally {
  api.kill(); ui.kill();
  await new Promise(r => setTimeout(r, 1500));
  await rm(temp, { recursive: true, force: true }).catch(() => undefined);
}
