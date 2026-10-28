import { test, expect, type Page } from "@playwright/test";
import { randomBytes } from "node:crypto";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, mkdir, rm, writeFile, access } from "node:fs/promises";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const root = path.resolve(frontendDir, "..");
const backendDir = path.join(root, "backend");
const python = path.join(backendDir, ".venv", "Scripts", "python.exe");
const tempPrefix = "cir-playwright-e2e-";
const columns = [
  "claim_id",
  "case_id",
  "facility_id",
  "participant_token",
  "service_date",
  "province_code",
  "municipality_code",
  "facility_ownership",
  "facility_type",
  "facility_class",
  "admission_diagnosis",
  "primary_diagnosis",
  "claim_group",
  "procedure_code",
  "billed_amount",
  "service_type",
  "service_units",
  "facility_daily_capacity",
  "supporting_evidence_required",
  "supporting_evidence_types",
  "supporting_evidence_present",
  "service_timestamp",
  "supporting_evidence_recording_status",
  "facility_daily_claim_count",
];

let tempRoot = "";
// CIR_E2E_UI_MODE=production runs the suite against a production build (see playwright.production.config.ts).
const PRODUCTION_UI = process.env.CIR_E2E_UI_MODE === "production";
// CIR_E2E_DATABASE_URL (a PostgreSQL database whose name ends in _test) runs the API on PostgreSQL in a
// fresh, migrated schema that is dropped afterwards; without it the API uses temporary SQLite files.
const E2E_DATABASE_URL = (process.env.CIR_E2E_DATABASE_URL ?? "").trim();
let databaseEnv: Record<string, string> = { CIR_DATABASE_URL: "", CIR_DATABASE_SCHEMA: "" };
let e2eSchema = "";
let apiUrl = "";
let uiUrl = "";
let apiProcess: ChildProcess | undefined;
let uiProcess: ChildProcess | undefined;
let verifier = "";
let platformAdmin = "";
let platformAdminPassword = "";
let verifierPassword = "";
const output = new Map<ChildProcess, string[]>();
let smokeRunId = "";
let fkrtlFixturePath = "";
// Raw-looking values that exist only inside the generated fixture; none may reach the UI or API responses.
const FKRTL_RAW_VALUES = ["7777771", "7777772", "synvisit", "987654321"];
const FKRTL_FIXTURE_CODE = [
  "import os",
  "from datetime import datetime",
  "import pandas as pd",
  "base = dict(PSTV01=7777771, FKL02='synvisit-a1', FKL03=datetime(2024, 3, 4), FKL04=datetime(2024, 3, 6),",
  "            FKL05=11, FKL06=1101, FKL07=1, FKL08=2, FKL09=3, FKL13=3, FKL16='SYN01', FKL18='SYN02',",
  "            FKL19='SYN-CBG-1', FKL30='SYNPROC', FKL47=123456.0, FKL48=987654321.0)",
  "rows = [base, {**base, 'FKL02': 'synvisit-a2', 'FKL09': 1},",
  "        {**base, 'FKL02': 'synvisit-a3', 'FKL30': ''}, {**base, 'FKL02': 'synvisit-a4', 'FKL30': ''},",
  "        {**base, 'PSTV01': 7777772, 'FKL02': 'synvisit-b1', 'FKL18': 'SYN09'}]",
  "pd.DataFrame(rows).to_stata(os.environ['CIR_E2E_FKRTL_PATH'], write_index=False)",
].join("\n");
let smokeCaseId = "";
let visualRoot = "";

test.beforeAll(async () => {
  try {
    await access(python);
  } catch {
    throw new Error("Project virtualenv backend/.venv/Scripts/python.exe is unavailable.");
  }
  tempRoot = await mkdtemp(path.join(os.tmpdir(), tempPrefix));
  visualRoot = await mkdtemp(path.join(os.tmpdir(), "cir-stage24-visual-"));
  const suffix = randomBytes(6).toString("hex");
  verifier = "e2e-verifier-" + suffix;
  platformAdmin = "e2e-admin-" + suffix;
  platformAdminPassword = randomBytes(24).toString("base64url");
  verifierPassword = randomBytes(24).toString("base64url");

  if (E2E_DATABASE_URL) {
    if (!new URL(E2E_DATABASE_URL).pathname.replace(/^\//, "").endsWith("_test"))
      throw new Error("CIR_E2E_DATABASE_URL must name a database ending in _test.");
    e2eSchema = "e2e_" + randomBytes(8).toString("hex");
    databaseEnv = { CIR_DATABASE_URL: E2E_DATABASE_URL, CIR_DATABASE_SCHEMA: e2eSchema };
    const created = spawnSync(python, ["-c", "import os, psycopg\nwith psycopg.connect(os.environ['CIR_DATABASE_URL'], autocommit=True) as c: c.execute('CREATE SCHEMA ' + os.environ['CIR_DATABASE_SCHEMA'])"],
      { cwd: backendDir, encoding: "utf8", windowsHide: true, env: { ...process.env, ...databaseEnv } });
    if (created.status !== 0) throw new Error("PostgreSQL test schema could not be created.");
    const migrated = spawnSync(python, ["-m", "scripts.db_migrate"],
      { cwd: backendDir, encoding: "utf8", windowsHide: true, env: { ...process.env, ...databaseEnv } });
    if (migrated.status !== 0) throw new Error("PostgreSQL schema migration failed: " + tail(migrated.stdout));
  }
  const seedCode = [
    "import os",
    "from app.security.auth import AuthStore",
    "store = AuthStore(os.environ['CIR_E2E_AUTH_DB'])",
    "secret = os.environ['CIR_E2E_BOOTSTRAP_SECRET']",
    "admin = store.create_bootstrap_admin(os.environ['CIR_E2E_ADMIN_USERNAME'], os.environ['CIR_E2E_ADMIN_PASSWORD'], secret, secret)",
    "store.create_user(os.environ['CIR_E2E_VERIFIER'], os.environ['CIR_E2E_VERIFIER_PASSWORD'], 'verifikator', admin['user_id'])",
  ].join("\n");
  const seed = spawnSync(python, ["-c", seedCode], {
    cwd: backendDir,
    encoding: "utf8",
    windowsHide: true,
    env: {
      ...process.env,
      ...databaseEnv,
      CIR_E2E_AUTH_DB: path.join(tempRoot, "auth.sqlite3"),
      CIR_E2E_BOOTSTRAP_SECRET: randomBytes(32).toString("base64url"),
      CIR_E2E_ADMIN_USERNAME: platformAdmin,
      CIR_E2E_ADMIN_PASSWORD: platformAdminPassword,
      CIR_E2E_VERIFIER: verifier,
      CIR_E2E_VERIFIER_PASSWORD: verifierPassword,
    },
  });
  if (seed.status !== 0)
    throw new Error("Disposable account provisioning failed (exit " + seed.status + "). " + tail(seed.stderr));
  // Generated synthetic FKRTL-shaped .dta fixture (invented values). The API process is always pointed at it,
  // so an FKRTL path inherited from the developer's shell can never be read by this test run.
  fkrtlFixturePath = path.join(tempRoot, "synthetic-fkrtl-fixture.dta");
  const fixture = spawnSync(python, ["-c", FKRTL_FIXTURE_CODE], {
    cwd: backendDir, encoding: "utf8", windowsHide: true,
    env: { ...process.env, CIR_E2E_FKRTL_PATH: fkrtlFixturePath },
  });
  if (fixture.status !== 0)
    throw new Error("Synthetic FKRTL fixture generation failed (exit " + fixture.status + "). " + tail(fixture.stderr));

  const apiPort = await freePort();
  let uiPort = await freePort();
  while (uiPort === apiPort) uiPort = await freePort();
  apiUrl = "http://127.0.0.1:" + apiPort;
  uiUrl = "http://127.0.0.1:" + uiPort;
  apiProcess = start(
    python,
    ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)],
    backendDir,
    {
      ...process.env,
      ...databaseEnv,
      CIR_AUTH_DB_PATH: path.join(tempRoot, "auth.sqlite3"),
      CIR_BATCH_DB_PATH: path.join(tempRoot, "batch-run.sqlite3"),
      CIR_REVIEW_DB_PATH: path.join(tempRoot, "review.sqlite3"),
      CIR_COOKIE_SECURE: "false",
      BPJS_FKRTL_SAMPLE_PATH: fkrtlFixturePath,
      CIR_FKRTL_PSEUDONYM_KEY: randomBytes(32).toString("hex"),
      BPJS_FKRTL_DATE_FROM: "2024-03-01",
      BPJS_FKRTL_DATE_TO: "2024-03-31",
      BPJS_FKRTL_MAX_ROWS: "1000",
      // The stage 2 AI is never called from E2E: its answer is mocked in the browser.
      ANTHROPIC_API_KEY: "",
      ANTHROPIC_AUTH_TOKEN: "",
      // A local Ollama server may run on this computer: keep the model off so the fallback path is tested.
      CIR_CLINICAL_AI: "off",
    },
  );
  await waitFor(apiUrl + "/health", apiProcess, "FastAPI");

  const vite = path.join(frontendDir, "node_modules", "vite", "bin", "vite.js");
  const uiEnv = { ...process.env, VITE_BACKEND_URL: apiUrl };
  if (PRODUCTION_UI) {
    // Production runtime: a fresh production build served as static files, with /api and /health
    // proxied to the API on the same origin (the documented reverse-proxy topology).
    const outDir = path.join(tempRoot, "dist");
    const build = spawnSync(process.execPath, [vite, "build", "--outDir", outDir, "--emptyOutDir"],
      { cwd: frontendDir, env: uiEnv, encoding: "utf8", windowsHide: true });
    if (build.status !== 0) throw new Error("Production build failed: " + (build.stderr || build.stdout).slice(-500));
    uiProcess = start(process.execPath,
      [vite, "preview", "--outDir", outDir, "--host", "127.0.0.1", "--port", String(uiPort), "--strictPort"],
      frontendDir, uiEnv);
  } else {
    uiProcess = start(process.execPath, [vite, "--host", "127.0.0.1", "--port", String(uiPort), "--strictPort"],
      frontendDir, uiEnv);
  }
  await waitFor(uiUrl, uiProcess, PRODUCTION_UI ? "Vite preview (production build)" : "Vite");
}, 240_000);

test.afterAll(async () => {
  await stop(uiProcess);
  await stop(apiProcess);
  if (e2eSchema) {
    // Evidence that the run wrote to PostgreSQL (counts only), then drop the disposable schema.
    const evidence = spawnSync(python, ["-c", [
      "import os, json, psycopg",
      "with psycopg.connect(os.environ['CIR_DATABASE_URL'], autocommit=True) as c:",
      "    c.execute('SET search_path TO ' + os.environ['CIR_DATABASE_SCHEMA'])",
      "    counts = {t: c.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0] for t in ('analysis_runs', 'analysis_run_cases', 'run_case_reviews', 'fkrtl_validation_jobs', 'auth_users')}",
      "    c.execute('DROP SCHEMA ' + os.environ['CIR_DATABASE_SCHEMA'] + ' CASCADE')",
      "print(json.dumps(counts))",
    ].join("\n")], { cwd: backendDir, encoding: "utf8", windowsHide: true, env: { ...process.env, ...databaseEnv } });
    if (evidence.status !== 0) throw new Error("PostgreSQL evidence/cleanup failed.");
    const counts = JSON.parse(evidence.stdout.trim().split(/\r?\n/).pop() ?? "{}");
    console.log("PostgreSQL E2E row counts: " + JSON.stringify(counts));
    expect(counts.analysis_runs).toBeGreaterThan(0);
    expect(counts.run_case_reviews).toBeGreaterThan(0);
    expect(fs.existsSync(path.join(tempRoot, "batch-run.sqlite3"))).toBe(false);  // no SQLite fallback
  }
  if (!tempRoot) return;
  const target = path.resolve(tempRoot);
  const temp = path.resolve(os.tmpdir());
  if (!target.startsWith(temp + path.sep) || !path.basename(target).startsWith(tempPrefix)) {
    throw new Error("Refusing cleanup outside this test's temporary directory.");
  }
  await rm(target, { recursive: true, force: true });
});

test("synthetic import, persisted run, and run-scoped review permissions", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  let runCreateRequests = 0;
  let legacyAnalyticsRequests = 0;
  page.on("request", request => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/v1/runs") runCreateRequests += 1;
    if (["/api/v1/dashboard/summary", "/api/v1/analysis", "/api/v1/cases"].includes(new URL(request.url()).pathname)) legacyAnalyticsRequests += 1;
  });
  const rejectedCsv = path.join(tempRoot, "invalid-synthetic-fixture.csv");
  await writeFile(rejectedCsv, "unknown_column\nsynthetic\n", { encoding: "utf8", flag: "wx" });
  const csvPath = path.join(tempRoot, "synthetic-fixture.csv");
  await writeFile(csvPath, makeCsv(), { encoding: "utf8", flag: "wx" });
  // One authenticated platform_admin completes the primary demo workflow end to end.
  await page.goto(uiUrl);
  await captureVisual(page, "login-desktop");
  await login(page, platformAdmin, platformAdminPassword);
  for (const linkName of ["Beranda", "Faskes", "Antrean Tinjauan", "Data & Analisis"]) {
    await expect(page.getByRole("navigation", { name: "Navigasi utama" }).getByRole("link", { name: linkName })).toBeVisible();
  }
  await page.getByRole("button", { name: new RegExp(platformAdmin) }).click();
  await expect(page.getByRole("menu")).toBeVisible();
  await captureVisual(page, "profile-menu-desktop");
  await page.getByRole("button", { name: new RegExp(platformAdmin) }).click();
  await page.goto(uiUrl + "/workflow");
  await expect(page.getByRole("heading", { name: "Data & Analisis", exact: true })).toBeVisible();
  await captureVisual(page, "workflow-desktop");
  // Upload is one step: a valid file is checked and analysed right away.
  await expect(page.getByText(/Kebijakan data: nomor peserta harus anonim/)).toBeVisible();
  await expect(page.getByRole("region", { name: "Sambungan otomatis" }).getByText("Belum diatur", { exact: true })).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles(rejectedCsv);
  await page.getByLabel("Nama data").fill("synthetic-e2e-rejected");
  await page.getByRole("button", { name: "Unggah dan analisis" }).click();
  await expect(page.getByText("Ditolak", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("File ditolak; data ini tidak dapat dianalisis.")).toBeVisible();

  await page.route("**/api/v1/batches/import", route => route.abort());
  await page.locator('input[type="file"]').setInputFiles(csvPath);
  await page.getByLabel("Nama data").fill("synthetic-e2e-request-failure");
  await page.getByRole("button", { name: "Unggah dan analisis" }).click();
  await expect(page.getByRole("alert").getByText("Permintaan gagal")).toBeVisible();
  await page.unroute("**/api/v1/batches/import");

  await page.getByLabel("Nama data").fill("synthetic-playwright-smoke");
  const createResponsePromise = page.waitForResponse(
    (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/runs",
  );
  await page.getByRole("button", { name: "Unggah dan analisis" }).click();
  await expect(page.getByText("Siap dianalisis", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/playwright-smoke/).first()).toBeVisible();
  const createResponse = await createResponsePromise;
  expect(createResponse.status()).toBe(201);
  const created = (await createResponse.json()) as { run: { run_id: string; batch_id: string; batch_version: number } };
  const runId = created.run.run_id;
  smokeRunId = runId;
  expect(runId).toBeTruthy();
  expect(created.run.batch_version).toBeGreaterThan(0);
  await expect(page.getByText("Ringkasan analisis", { exact: true })).toBeVisible();
  await expect(page.locator('table[aria-label="Hasil pemeriksaan"]')).toHaveCount(1);
  await expectNoTechnicalLeaks(page);

  await page.goto(uiUrl + "/");
  await expect(page.getByRole("heading", { name: "Prioritas hari ini" })).toBeVisible();
  await expect(page.getByLabel("Pilih hasil analisis", { exact: true })).toHaveValue(runId);
  await expect(page.getByRole("heading", { name: /Faskes paling mendesak/ })).toBeVisible();
  for (const lane of ["red", "yellow", "green"]) await expect(page.getByTestId(`lane-card-${lane}`)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Status tinjauan" })).toBeVisible();
  await page.locator("details.tech-details").last().locator("summary").click();
  await expect(page.getByText(runId, { exact: true }).first()).toBeVisible();
  await page.locator("details.tech-details").last().locator("summary").click();
  await expectNoTechnicalLeaks(page);
  await captureVisual(page, "overview-desktop");
  expect(legacyAnalyticsRequests).toBe(0);

  await page.goto(uiUrl + "/facilities");
  await expect(page.getByRole("heading", { name: "Faskes", exact: true })).toBeVisible();
  await captureVisual(page, "facilities-desktop");

  await page.goto(uiUrl + "/analysis");
  await expect(page.getByRole("heading", { name: "Hasil setiap pemeriksaan" })).toBeVisible();
  await expect(page.getByLabel("Pilih hasil analisis", { exact: true })).toHaveValue(runId);
  expect(new URL(page.url()).searchParams.get("run_id")).toBe(runId);
  await expect(page.locator(".unassessed-reasons").first()).toBeVisible();
  await expectNoTechnicalLeaks(page);
  await captureVisual(page, "analysis-desktop");
  await page.goto(uiUrl + "/cases");
  await expect(page.getByRole("heading", { name: /^\d+ klaim$/ })).toBeVisible();
  await expect(page.getByLabel("Pilih hasil analisis", { exact: true })).toHaveValue(runId);
  expect(new URL(page.url()).searchParams.get("run_id")).toBe(runId);
  await expect(page.getByText("Pilih klaim di kiri")).toBeVisible();
  await captureVisual(page, "cases-desktop");
  const indicatorFilter = page.getByLabel("Saring jenis pemeriksaan");
  expect(await indicatorFilter.locator("option").count()).toBeGreaterThan(1);
  const firstIndicator = await indicatorFilter.locator("option").nth(1).getAttribute("value");
  expect(firstIndicator).toBeTruthy();
  await indicatorFilter.selectOption(firstIndicator!);
  await expect(indicatorFilter).toHaveValue(firstIndicator!);
  expect(new URL(page.url()).searchParams.get("check")).toBe(firstIndicator);
  await indicatorFilter.selectOption("");
  // Typing in the search box neither reloads the run nor queries per keystroke: one list request after the pause.
  const runPath = "/api/v1/runs/" + encodeURIComponent(runId);
  let runReloads = 0;
  const searchedTexts: string[] = [];
  const countSearchTraffic = (request: { method(): string; url(): string }) => {
    const pathname = new URL(request.url()).pathname;
    if (request.method() !== "GET") return;
    if (pathname === runPath) runReloads += 1;
    const searched = new URL(request.url()).searchParams.get("search");
    if (pathname === runPath + "/cases" && searched) searchedTexts.push(searched);
  };
  page.on("request", countSearchTraffic);
  const searchBox = page.getByLabel("Cari nomor referensi klaim");
  await expect(page.locator("a.queue-item").first()).toBeVisible();
  await searchBox.pressSequentially("syn-zz", { delay: 60 });
  await expect(searchBox).toHaveValue("syn-zz");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("syn-zz");
  await expect(page.getByText("Tidak ada klaim untuk saringan ini")).toBeVisible();
  expect(runReloads).toBe(0);
  expect(searchedTexts).toEqual(["syn-zz"]);
  await searchBox.fill("");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBeNull();
  page.off("request", countSearchTraffic);
  const queueCandidate = page.locator("a.queue-item").first();
  await expect(queueCandidate).toBeVisible();
  const href = await queueCandidate.getAttribute("href");
  expect(href).toContain("/runs/" + encodeURIComponent(runId) + "/cases/");
  const casePath = new URL(href!, uiUrl).pathname;
  const caseId = decodeURIComponent(casePath.split("/").at(-1)!);
  smokeCaseId = caseId;
  const detailUrl = uiUrl + href;
  await queueCandidate.click();
  await expect(page).toHaveURL(detailUrl);
  await expect(page.getByRole("region", { name: "Ringkasan klaim" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Mengapa klaim ini perlu diperiksa?" })).toBeVisible();
  // The list stays next to the selected claim and marks it.
  await expect(page.locator(`li[data-case-id="${caseId}"] a.queue-item`)).toHaveAttribute("aria-current", "true");
  await expectNoTechnicalLeaks(page);
  await captureVisual(page, "case-review-desktop");

  await page.goto(uiUrl + "/workflow");
  const runDetailResponsePromise = page.waitForResponse(
    (response) => response.request().method() === "GET" && new URL(response.url()).pathname === "/api/v1/runs/" + runId,
  );
  await page.locator(`[data-run-id="${runId}"]`).click();
  const runDetailResponse = await runDetailResponsePromise;
  expect(runDetailResponse.status()).toBe(200);
  const runDetailPayload = (await runDetailResponse.json()) as {
    run: Record<string, unknown>;
    result: { execution_status: string; indicator_coverage: Array<{ status: string; search_truncated: boolean }> } | null;
  };
  await expect(page.getByText("Ringkasan analisis", { exact: true })).toBeVisible();
  await expect(page.locator('table[aria-label="Hasil pemeriksaan"]')).toHaveCount(1);
  expect(runDetailPayload.result).not.toBeNull();
  expect(runDetailPayload.result!.indicator_coverage.some(item => item.status === "partial" || item.status === "unavailable" || item.search_truncated)).toBe(true);
  expect(runCreateRequests).toBe(1);
  const resultBefore = await readResult(page, runId);
  await page.goto(detailUrl);

  await expect(page.getByRole("button", { name: "Simpan keputusan" })).toBeEnabled();
  // Taking the claim tells other reviewers it is being handled.
  await expect(page.getByTestId("case-assignment")).toContainText("belum ada");
  await page.getByRole("button", { name: "Ambil klaim ini" }).click();
  await expect(page.getByTestId("case-assignment")).toContainText("Anda");
  await expect(page.getByRole("button", { name: "Lepaskan" })).toBeVisible();

  await page.getByRole("radio", { name: "Minta klarifikasi" }).check();
  await page.getByLabel("Catatan (opsional)", { exact: true }).fill("Synthetic verifier smoke note; no real claim data.");
  await page.getByRole("button", { name: "Simpan status" }).click();
  await expect(page.locator(".workflow-feedback")).toHaveText("Status tinjauan tersimpan.");
  await expect(page.getByTestId("toast").filter({ hasText: "Status tinjauan tersimpan" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Ringkasan klaim" }).getByText("Minta klarifikasi")).toBeVisible();

  await page.getByRole("radio", { name: "Benar, perlu ditindaklanjuti" }).check();
  await page.getByLabel("Catatan (opsional)", { exact: true }).fill("Synthetic platform admin outcome; no real claim data.");
  await page.getByRole("button", { name: "Simpan keputusan" }).click();
  await expect(page.locator(".workflow-feedback")).toHaveText("Keputusan tinjauan tersimpan.");
  await expect(page.getByText("Benar, perlu ditindaklanjuti").first()).toBeVisible();

  await page.reload();
  await expect(page.getByRole("region", { name: "Ringkasan klaim" })).toBeVisible();
  await expect(page.getByRole("radio", { name: "Minta klarifikasi" })).toBeChecked();
  await expect(page.getByRole("radio", { name: "Benar, perlu ditindaklanjuti" })).toBeChecked();
  await page.locator(".review-history-panel > summary").click();
  await expect(page.locator(".history-note").filter({ hasText: "Synthetic verifier smoke note; no real claim data." })).toBeVisible();
  await expect(page.locator(".history-note").filter({ hasText: "Synthetic platform admin outcome; no real claim data." })).toBeVisible();
  await expect(page.getByText("2 perubahan")).toBeVisible();
  expect(await readResult(page, runId)).toEqual(resultBefore);

  // An authorized audit result is recorded separately from the reviewer outcome and needs a reference.
  await expect(page.getByTestId("audit-result-status")).toHaveText("Belum ada hasil audit resmi");
  await page.getByText("Catat hasil audit resmi").click();
  await page.getByLabel("Nomor referensi audit").fill("AUD-2026/014");
  await page.getByRole("button", { name: "Simpan hasil audit" }).click();
  await expect(page.locator(".workflow-feedback")).toHaveText("Hasil audit resmi tersimpan.");
  await page.reload();
  await expect(page.getByTestId("audit-result-status")).toHaveText("Audit resmi: ada masalah");
  await expect(page.getByRole("radio", { name: "Benar, perlu ditindaklanjuti" })).toBeChecked();
  expect(await readResult(page, runId)).toEqual(resultBefore);
  expect(runCreateRequests).toBe(1);
  expect(legacyAnalyticsRequests).toBe(0);
  expect(caseId).toBeTruthy();

  // The queue shows the saved human review state next to the (unchanged) check results.
  await page.goto(uiUrl + "/cases?run_id=" + encodeURIComponent(runId));
  const reviewFilter = page.getByLabel("Saring status tinjauan");
  const reviewedRow = page.locator(`li[data-case-id="${caseId}"]`);
  await reviewFilter.selectOption("has_outcome");
  await expect(page.locator(".queue-items > li")).toHaveCount(1);
  await expect(reviewedRow.getByTestId("queue-review-cell")).toContainText("Minta klarifikasi");
  await expect(reviewedRow.getByTestId("queue-review-cell")).toContainText("Benar, perlu ditindaklanjuti");
  await expect(reviewedRow.getByTestId("queue-audit-result")).toHaveText("Audit resmi: ada masalah");
  await expect(page.getByTestId("queue-review-progress")).toContainText("1 dari");
  await reviewFilter.selectOption("not_started");
  await expect(reviewedRow).toHaveCount(0);
  await reviewFilter.selectOption("");
  await page.getByLabel("Urutkan").selectOption("review_updated");
  await expect(page.locator(".queue-items > li").first()).toHaveAttribute("data-case-id", caseId);
  expect(await readResult(page, runId)).toEqual(resultBefore);
  expect(runCreateRequests).toBe(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(uiUrl + "/");
  await expect(page.getByRole("heading", { name: "Prioritas hari ini" })).toBeVisible();
  await page.getByRole("button", { name: "Buka navigasi" }).click();
  await expect(page.getByRole("navigation", { name: "Navigasi utama" })).toBeVisible();
  await captureVisual(page, "navigation-mobile-open");
  for (const [name, route, heading] of [
    ["overview", "/", /^Prioritas hari ini$/],
    ["analysis", "/analysis?run_id=" + encodeURIComponent(runId), /^Rincian Analisis$/],
    ["cases", "/cases?run_id=" + encodeURIComponent(runId), /^Antrean Tinjauan$/],
    ["case-review", href!, /^Mengapa klaim ini perlu diperiksa\?$/],
    ["workflow", "/workflow", /^Data & Analisis$/],
    ["facilities", "/facilities", /^Faskes$/],
  ] as const) {
    await page.goto(uiUrl + route);
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    // Nothing on a phone may scroll sideways.
    const overflow = await page.evaluate(() => {
      const width = window.innerWidth;
      const wide = [...document.querySelectorAll("main *")].filter(el => el.getBoundingClientRect().right > width + 1
        && !el.closest(".table-scroll, .queue-tabs, pre"));
      return { scrollWidth: document.documentElement.scrollWidth, width,
        culprits: wide.slice(-3).map(el => `${el.tagName.toLowerCase()}.${[...el.classList].join(".")}`) };
    });
    expect(overflow.scrollWidth <= overflow.width + 1, `${name} scrolls sideways: ${JSON.stringify(overflow)}`).toBe(true);
    await captureVisual(page, name + "-mobile");
  }
  // On a phone the selected claim replaces the list; the back link returns to it.
  await page.goto(uiUrl + href!);
  await expect(page.locator(".queue-list-card")).toBeHidden();
  await page.getByRole("link", { name: "Kembali ke daftar" }).first().click();
  await expect(page.locator(".queue-list-card")).toBeVisible();
  const unauthenticated = await page.context().browser()?.newPage();
  if (unauthenticated) {
    await unauthenticated.setViewportSize({ width: 390, height: 844 });
    await unauthenticated.goto(uiUrl);
    await expect(unauthenticated.getByLabel("Nama pengguna")).toBeVisible();
    await captureVisual(unauthenticated, "login-mobile");
    await unauthenticated.close();
  }
});

test("Overview distinguishes empty readable runs from API failure", async ({ page }) => {
  await login(page, verifier, verifierPassword);
  await page.route("**/api/v1/runs?*", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ availability: "available", items: [], total_items: 0, limit: 50, offset: 0 }),
  }));
  await page.goto(uiUrl + "/");
  // An empty system shows the first-run guide (what to do first), never an error.
  await expect(page.getByTestId("first-run-guide")).toBeVisible();
  await expect(page.getByText("Klaim dianalisis", { exact: true })).toHaveCount(0);

  await page.unroute("**/api/v1/runs?*");
  await page.route("**/api/v1/runs?*", route => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ detail: { code: "SYNTHETIC_TEST_UNAVAILABLE", message: "Synthetic service unavailable for test." } }),
  }));
  await page.reload();
  await expect(page.getByRole("alert").getByText("Data tidak dapat dimuat")).toBeVisible();
  await expect(page.getByTestId("first-run-guide")).toHaveCount(0);

  expect(smokeRunId).toBeTruthy();
  expect(smokeCaseId).toBeTruthy();
  const verifierOutcome = await submitOutcome(
    page,
    `/api/v1/runs/${encodeURIComponent(smokeRunId)}/cases/${encodeURIComponent(smokeCaseId)}/review`,
    await csrfToken(page),
  );
  expect(verifierOutcome).toBe(200);

  // The single reviewer role sees the full authorized audit record and can fill every decision step.
  const reviewPath = `/api/v1/runs/${encodeURIComponent(smokeRunId)}/cases/${encodeURIComponent(smokeCaseId)}/review`;
  const reviewPayload = await page.evaluate(async (input) => (await fetch(input, { credentials: "same-origin" })).text(), reviewPath);
  expect(reviewPayload).toContain("confirmed_issue");
  expect(reviewPayload).toContain("AUD-2026/014");
  await page.unroute("**/api/v1/runs?*");
  await page.goto(uiUrl + `/runs/${encodeURIComponent(smokeRunId)}/cases/${encodeURIComponent(smokeCaseId)}`);
  await expect(page.getByTestId("audit-result-status")).toHaveText("Audit resmi: ada masalah");
  await expect(page.getByTestId("audit-details-restricted")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Simpan keputusan" })).toBeVisible();
});

test("a late duplicate load does not overwrite the reviewer's unsaved status choice", async ({ page }) => {
  // The duplicate load comes from React StrictMode, which only exists in the development build.
  test.skip(PRODUCTION_UI, "StrictMode double effects are a development-build behaviour");
  // Regression for a timing flake: React StrictMode (dev server) loads the case twice. When the
  // first load's response arrived after the form was shown, it reset the selected status.
  expect(smokeRunId).toBeTruthy();
  expect(smokeCaseId).toBeTruthy();
  await login(page, platformAdmin, platformAdminPassword);
  const casePath = `/api/v1/runs/${encodeURIComponent(smokeRunId)}/cases/${encodeURIComponent(smokeCaseId)}`;
  // Each load requests the case first; effects run in order, so the first case request is the
  // first (stale) load. Hold it until the reviewer has changed the form, then let it finish.
  let caseGets = 0;
  let releaseFirst: () => void = () => undefined;
  const firstHeld = new Promise<void>(resolve => { releaseFirst = resolve; });
  await page.route(`**${casePath}`, async route => {
    caseGets += 1;
    if (caseGets === 1) await firstHeld;
    await route.continue();
  });
  await page.goto(uiUrl + `/runs/${encodeURIComponent(smokeRunId)}/cases/${encodeURIComponent(smokeCaseId)}`);
  const checkedStatus = page.locator('input[name="review-status"]:checked');
  await expect(page.getByRole("radio", { name: "Sedang ditinjau" })).toBeEnabled();
  expect(caseGets).toBe(2);  // StrictMode issued a duplicate load and the second one rendered the form
  const saved = await checkedStatus.inputValue();
  const [changed, changedLabel] = saved === "escalated" ? ["in_review", "Sedang ditinjau"] : ["escalated", "Masuk antrean audit"];
  await page.getByRole("radio", { name: changedLabel }).check();
  // Release the stale load and wait for its case response (with the fix it then stops; without
  // it, it went on to fetch the review and reset the form to the saved status).
  const lateCase = page.waitForResponse(response => new URL(response.url()).pathname === casePath);
  releaseFirst();
  await lateCase;
  await page.waitForTimeout(1000);  // room for a follow-up review request and React to apply it
  await expect(checkedStatus).toHaveValue(changed);
  await page.unroute(`**${casePath}`);
});

test("selecting a batch refreshes in place and keeps the import form (and a chosen file) mounted", async ({ page }) => {
  // Regression: a selection change started a full reload that unmounted the import form; a file
  // chosen meanwhile was dropped and the previously chosen file was uploaded instead.
  await login(page, platformAdmin, platformAdminPassword);
  await page.goto(uiUrl + "/workflow");
  const batchButtons = page.getByRole("region", { name: "File tersimpan" }).locator("button.table-select");
  await expect(batchButtons.first()).toBeVisible();
  let releaseList: () => void = () => undefined;
  const held = new Promise<void>(resolve => { releaseList = resolve; });
  let heldLists = 0;
  await page.route("**/api/v1/batches?*", async route => { heldLists += 1; await held; await route.continue(); });
  await batchButtons.first().click();
  await expect.poll(() => heldLists).toBeGreaterThan(0);  // the reload after the selection is in flight
  await expect(page.locator('input[type="file"]')).toBeVisible();
  await expect(page.getByText("Memuat data klaim dan riwayat analisis…")).toHaveCount(0);
  const listed = page.waitForResponse(response => response.request().method() === "GET"
    && new URL(response.url()).pathname === "/api/v1/batches");
  releaseList();
  await listed;
  await page.unroute("**/api/v1/batches?*");
  await expect(page.locator('input[type="file"]')).toBeVisible();
});

test("another user's escalation pops up for the admin and links to the case", async ({ page, browser }) => {
  expect(smokeRunId).toBeTruthy();
  expect(smokeCaseId).toBeTruthy();
  await login(page, platformAdmin, platformAdminPassword);
  await page.goto(uiUrl + "/cases?run_id=" + encodeURIComponent(smokeRunId));
  await page.waitForTimeout(1_000);  // the admin's notification cursor starts now
  const other = await browser.newContext();
  const verifierPage = await other.newPage();
  await login(verifierPage, verifier, verifierPassword);
  const csrf = (await other.cookies()).find(cookie => cookie.name === "cir_csrf")?.value ?? "";
  const escalated = await verifierPage.request.patch(
    `${uiUrl}/api/v1/runs/${encodeURIComponent(smokeRunId)}/cases/${encodeURIComponent(smokeCaseId)}/review`,
    { headers: { "X-CSRF-Token": csrf }, data: { review_status: "escalated", note: null } });
  expect(escalated.status()).toBe(200);
  await other.close();
  const popup = page.getByTestId("toast").filter({ hasText: "Klaim masuk antrean audit" });
  await expect(popup).toBeVisible({ timeout: 40_000 });
  await expect(popup).not.toContainText("note");
  await popup.getByRole("link", { name: "Buka klaim" }).click();
  await expect(page).toHaveURL(new RegExp(`/runs/${smokeRunId}/cases/`));
  await expect(page.getByRole("region", { name: "Ringkasan klaim" })).toBeVisible();
});

test("queue shows loading and failure states, never an empty result, while a page is missing", async ({ page }) => {
  expect(smokeRunId).toBeTruthy();
  await login(page, platformAdmin, platformAdminPassword);
  const pagePath = `**/api/v1/runs/${encodeURIComponent(smokeRunId)}/cases?*`;
  let releasePage: () => void = () => undefined;
  const held = new Promise<void>(resolve => { releasePage = resolve; });
  await page.route(pagePath, async route => { await held; await route.fulfill({ status: 500, json: {
    error: { code: "RUN_STORAGE_UNAVAILABLE", message: "Penyimpanan AnalysisRun lokal tidak tersedia.", details: {} } } }); });
  await page.goto(uiUrl + "/cases?run_id=" + encodeURIComponent(smokeRunId));
  await expect(page.getByText("Memuat daftar klaim…")).toBeVisible();
  await expect(page.getByText("Tidak ada klaim untuk saringan ini")).toHaveCount(0);
  releasePage();
  await expect(page.getByText("Daftar klaim tidak dapat dimuat")).toBeVisible();
  await expect(page.getByText("Tidak ada klaim untuk saringan ini")).toHaveCount(0);
  await page.unroute(pagePath);
  // A case that is not part of the run is reported as such, not as an empty review.
  await page.goto(uiUrl + `/runs/${encodeURIComponent(smokeRunId)}/cases/case_not_in_this_run`);
  await expect(page.getByText("Klaim tidak ada di analisis ini")).toBeVisible();
});

test("FKRTL sample runs from Data & Analisis with repeat-service-v1, explicit coverage and no raw identifiers", async ({ page }) => {
  // Uses only the generated synthetic FKRTL-shaped fixture configured for the API process.
  await login(page, platformAdmin, platformAdminPassword);
  await page.goto(uiUrl + "/workflow");
  const card = page.getByRole("region", { name: "Proses data klaim" });
  await expect(card.getByText("Terhubung", { exact: true })).toBeVisible();
  // Source validation runs on the server and returns counts only.
  let fkrtlRunCreates = 0;
  page.on("request", request => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/v1/runs") fkrtlRunCreates += 1;
  });
  const summary = card.getByTestId("fkrtl-validation-state");
  await expect(summary).toContainText("Data periode ini belum diproses");
  // Re-analysis without a check is only offered after a current, passed check (the server enforces the same rule).
  await expect(card.getByRole("button", { name: "Analisis ulang tanpa pemeriksaan" })).toHaveCount(0);
  const validatedPromise = page.waitForResponse(response => response.request().method() === "POST"
    && new URL(response.url()).pathname === "/api/v1/sources/fkrtl-local/validation");
  const createdPromise = page.waitForResponse(response => response.request().method() === "POST"
    && new URL(response.url()).pathname === "/api/v1/runs", { timeout: 60_000 });
  await card.getByRole("button", { name: "Proses data klaim" }).click();
  const validated = await validatedPromise;
  // The scan runs as a background job: the POST answers 202 at once and the card polls the job.
  expect(validated.status()).toBe(202);
  const validationText = await validated.text();
  for (const raw of FKRTL_RAW_VALUES) expect(validationText).not.toContain(raw);
  expect(["pending", "running", "completed"]).toContain(JSON.parse(validationText).job.status);
  await expect(page.getByTestId("toast").filter({ hasText: "Data klaim sedang diproses" })).toBeVisible();
  const created = await createdPromise;
  expect(created.status()).toBe(201);
  const createdText = await created.text();
  const run = (JSON.parse(createdText) as { run: { run_id: string; source_type: string; configuration: { source: { repeat_signature_profile: string } } } }).run;
  await expect(summary).toContainText("Kualitas data baik, ada catatan");
  // The finished event comes from the server (polled every 15 s), not from the click.
  await expect(page.getByTestId("toast").filter({ hasText: "Pemeriksaan kualitas data selesai dengan catatan" }))
    .toBeVisible({ timeout: 40_000 });
  const finalState = await page.request.get(uiUrl + "/api/v1/sources/fkrtl-local/validation");
  for (const raw of FKRTL_RAW_VALUES) expect(await finalState.text()).not.toContain(raw);
  expect((await finalState.json()).job.status).toBe("completed");
  await expect(summary.getByText("Klaim pada periode")).toBeVisible();
  await expect(summary.getByText(/kode prosedur kosong/)).toBeVisible();
  await summary.getByText(/Kesiapan setiap pemeriksaan/).click();
  const readiness = summary.getByRole("table", { name: "Kesiapan pemeriksaan di rentang tanggal" });
  await expect(readiness).toContainText("Tidak berlaku untuk data ini");
  await expect(readiness.locator('tr[data-check="repeat_billing_candidate"]')).toContainText("3 dari 5");
  await expect(readiness.locator('tr[data-check="repeat_billing_candidate"]')).toContainText("2 prosedur kosong");
  // One blank attribute (the procedure) is allowed for similar-claim screening.
  await expect(readiness.locator('tr[data-check="near_duplicate_claim_candidate"]')).toContainText("5 dari 5");
  expect(run.source_type).toBe("bpjs_fkrtl_local");
  expect(run.configuration.source.repeat_signature_profile).toBe("repeat-service-v1");
  const detail = await page.request.get(uiUrl + "/api/v1/runs/" + encodeURIComponent(run.run_id));
  expect(detail.status()).toBe(200);
  const detailText = await detail.text();
  for (const raw of FKRTL_RAW_VALUES) {
    expect(createdText).not.toContain(raw);
    expect(detailText).not.toContain(raw);
  }

  await page.goto(uiUrl + "/analysis?run_id=" + encodeURIComponent(run.run_id));
  const repeatCard = page.locator(".analysis-indicator-card").filter({ has: page.getByRole("heading", { name: "Layanan berulang" }) });
  // The server marks repeat matches as patterns without billing evidence; the card says so.
  await expect(repeatCard.getByTestId("repeat-pattern-only")).toContainText("belum bukti tagihan ganda");
  await expect(repeatCard.getByRole("list", { name: /Alasan klaim tidak diperiksa/ })).toContainText("2 prosedur kosong");
  // Checks the source cannot support are grouped, not shown as empty results.
  const notApplicable = page.locator("details").filter({ has: page.getByText(/^Tidak berlaku untuk data ini \(\d+ pemeriksaan\)$/) });
  await notApplicable.locator("summary").click();
  await expect(notApplicable.locator('[data-indicator="supporting_evidence_completeness_candidate"]')).toContainText("Kelengkapan dokumen");
  await expectNoTechnicalLeaks(page);

  await page.goto(uiUrl + "/cases?run_id=" + encodeURIComponent(run.run_id));
  await page.getByLabel("Saring jenis pemeriksaan").selectOption("repeat_billing_candidate");
  await expect(page.getByRole("heading", { name: "2 klaim" })).toBeVisible();
  await expect(page.getByTestId("queue-review-cell").filter({ hasText: "Belum ditinjau" })).toHaveCount(2);
  const firstRow = page.locator(".queue-items > li").first();
  const reviewedCase = await firstRow.getAttribute("data-case-id");
  await firstRow.locator("a.queue-item").click();
  await expect(page.getByRole("region", { name: "Ringkasan klaim" })).toBeVisible();
  // The filter is kept in the URL, so the list next to the claim is still the filtered one.
  expect(new URL(page.url()).searchParams.get("check")).toBe("repeat_billing_candidate");
  const repeatReason = page.locator(".run-reason").filter({ hasText: "Layanan berulang" });
  await expect(repeatReason.getByTestId("repeat-pattern-only")).toContainText("status pembayaran tidak tersedia");
  // Too few checks apply for a rule index, so the light comes from the rule flag plus the AI signal.
  await expect(page.getByTestId("case-lane")).toContainText(/RISIKO (TINGGI|SEDANG|RENDAH)/);
  await expect(repeatReason.getByText("Atribut yang berbeda")).toBeVisible();
  await expect(repeatReason.getByText("kelas fasilitas", { exact: true })).toBeVisible();
  await expectNoTechnicalLeaks(page);
  await page.getByRole("radio", { name: "Sedang ditinjau" }).check();
  await page.getByLabel("Catatan (opsional)", { exact: true }).fill("Synthetic FKRTL fixture review; no real claim data.");
  await page.getByRole("button", { name: "Simpan status" }).click();
  await expect(page.locator(".workflow-feedback")).toHaveText("Status tinjauan tersimpan.");
  // The list next to the claim picks up the saved status without a reload.
  await expect(page.locator(`li[data-case-id="${reviewedCase}"]`).getByTestId("queue-review-cell")).toContainText("Sedang ditinjau");
  await page.getByRole("radio", { name: "Belum bisa disimpulkan" }).check();
  await page.getByRole("button", { name: "Simpan keputusan" }).click();
  await expect(page.locator(".workflow-feedback")).toHaveText("Keputusan tinjauan tersimpan.");

  await page.goto(uiUrl + "/cases?run_id=" + encodeURIComponent(run.run_id));
  await expect(page.locator(`li[data-case-id="${reviewedCase}"]`).getByTestId("queue-review-cell")).toContainText("Sedang ditinjau");
  await expect(page.locator(`li[data-case-id="${reviewedCase}"]`).getByTestId("queue-review-cell")).toContainText("Belum bisa disimpulkan");

  // Reopen the saved run from the analysis history: the stored result is read, never recomputed.
  await page.goto(uiUrl + "/workflow");
  const reopenedPromise = page.waitForResponse(response => response.request().method() === "GET"
    && new URL(response.url()).pathname === "/api/v1/runs/" + run.run_id);
  await page.locator(`[data-run-id="${run.run_id}"]`).click();
  const reopened = await reopenedPromise;
  expect(reopened.status()).toBe(200);
  // The page loads the summary view: no per-case objects, but the full flagged-claim count.
  expect(new URL(reopened.url()).searchParams.get("view")).toBe("summary");
  const reopenedResult = (await reopened.json()).result;
  const fullResult = JSON.parse(detailText).result;
  expect(reopenedResult.cases).toEqual({});
  expect(reopenedResult.result_view.case_count).toBe(Object.keys(fullResult.cases).length);
  expect(reopenedResult.indicator_coverage).toEqual(fullResult.indicator_coverage);
  await expect(page.getByText("Ringkasan analisis", { exact: true })).toBeVisible();
  expect(fkrtlRunCreates).toBe(1);
  const html = await page.content();
  for (const raw of FKRTL_RAW_VALUES) expect(html).not.toContain(raw);
  expect(await readResult(page, run.run_id)).toEqual(JSON.parse(detailText).result);
});

/** Visible page text must not show internal codes (snake_case identifiers) or broken values; collapsed technical details are exempt. */
async function expectNoTechnicalLeaks(page: Page) {
  await expect(page.locator(".api-loading")).toHaveCount(0);
  const text = await page.locator("main").innerText();
  const leaks = text.match(/\b[a-z]+(?:_[a-z0-9]+)+\b|\bundefined\b|\bNaN\b|\[object Object\]/g) ?? [];
  expect(leaks, "technical codes visible on the page").toEqual([]);
}

const CLONED_NOTE = "Laki-laki 54 tahun datang dengan keluhan nyeri dada sejak 2 hari. TD 150/90 mmHg, nadi 88 x/menit, "
  + "suhu 36.8 C. Kondisi ringan tanpa komplikasi. Dirawat 3 hari, pulang dengan kondisi membaik.";
function bpjsCsvWithNotes(): string {
  const header = "PSTV01,FKL02,FKL03,FKL04,FKL05,FKL06,FKL07,FKL08,FKL09,FKL13,FKL16,FKL18,FKL19,FKL30,FKL31,FKL32,FKL47,CATATAN_KLINIS";
  const lines = [header];
  for (let index = 0; index < 60; index += 1) {
    const day = `2024-03-${String(4 + (index % 5)).padStart(2, "0")}`;
    const note = index < 3 ? CLONED_NOTE
      : `Perempuan ${20 + index} tahun datang dengan keluhan demam sejak ${1 + (index % 9)} hari. TD ${100 + index}/${60 + (index % 30)} mmHg, nadi ${60 + index} x/menit, catatan ${index}.`;
    lines.push([`SYN${String(9000 + index).padStart(7, "0")}`, `SYNV${String(index).padStart(7, "0")}`, day, day, "31", "3171", "9", "1",
      "3", "3", `SYN-DX-${index % 4}`, `SYN-DX-${index % 4}`, `SYN-CBG-${index % 3}`, "", "1", "1", "250000", `"${note}"`].join(","));
  }
  return lines.join("\n") + "\n";
}

test("an uploaded BPJS-format file shows the clinical note, the cloned-note finding and the stage 2 AI reading", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await login(page, platformAdmin, platformAdminPassword);
  const csrf = (await page.context().cookies()).find(cookie => cookie.name === "cir_csrf")?.value ?? "";
  const imported = await page.request.post(uiUrl + "/api/v1/batches/import", { data: bpjsCsvWithNotes(), headers: {
    "Content-Type": "text/csv; charset=utf-8", "X-CSRF-Token": csrf, "X-Batch-Key": "synthetic-e2e-notes",
    "X-Synthetic-Schema-Version": "bpjs-fkrtl-csv-v1", "X-Synthetic-Mapping-Version": "bpjs-fkrtl-sample-map-v2",
    "X-Data-Classification": "synthetic_only" } });
  expect(imported.status(), await imported.text()).toBe(201);
  const batch = (await imported.json()).batch as { batch_id: string; status: string };
  expect(batch.status).toBe("ready");
  const created = await page.request.post(uiUrl + "/api/v1/runs", { data: { batch_id: batch.batch_id }, headers: { "X-CSRF-Token": csrf } });
  expect(created.status()).toBe(201);
  const runId = (await created.json()).run.run_id as string;
  const detail = await page.request.get(uiUrl + `/api/v1/runs/${encodeURIComponent(runId)}`);
  const detailText = await detail.text();
  // Note text is shown on request only; it never enters the stored run result.
  expect(detailText).not.toContain("nyeri dada");
  const cases = (await detail.json()).result.cases as Record<string, { indicators: string[] }>;
  const caseId = Object.keys(cases).find(id => cases[id].indicators.includes("cloned_clinical_note_candidate"));
  expect(caseId).toBeTruthy();

  const caseUrl = uiUrl + `/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId!)}`;
  await page.goto(caseUrl);
  const card = page.getByTestId("clinical-note");
  await expect(card).toContainText("nyeri dada sejak 2 hari");
  await expect(page.getByRole("heading", { name: "Catatan klinis kembar", level: 4 })).toBeVisible();
  await expect(page.getByTestId("clinical-claim-facts")).toBeVisible();
  // Without a language model the button still works: the server answers with its fallback reading.
  await expect(card).toContainText("Layanan AI sedang tidak aktif");
  await card.getByTestId("clinical-ai-ask").click();
  await expect(card.getByTestId("clinical-ai-engine")).toHaveText("Pembacaan otomatis");
  await expect(page.getByTestId("toast").filter({ hasText: "Catatan klinis selesai dibaca" })).toBeVisible();

  // With the local model switched on (mocked): one click shows the verdict, the facts it read and what to check.
  const notePath = `**/api/v1/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId!)}/clinical-note`;
  const analysisPath = `**/api/v1/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId!)}/clinical-analysis`;
  await page.route(notePath, async route => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), ai_configured: true } });
  });
  await page.route(analysisPath, route => route.fulfill({ status: 200, json: { run_id: runId, case_id: caseId, analysis: {
    created_at: "2026-10-27T08:00:00+00:00", model: "qwen3:4b", requested_by_user_id: "u1", requested_by: platformAdmin,
    engine: "llm", fallback_reason: null,
    fakta_catatan: { keparahan_menurut_catatan: "ringan", komplikasi_atau_komorbid: "tidak", lama_rawat_menurut_catatan_hari: 3,
      menyebut_lanjutan_perawatan_sebelumnya: false },
    verdict: "mencurigakan", ringkasan: "Catatan sama persis dengan pasien lain.", alasan: ["Angka tanda vital identik."],
    yang_perlu_diperiksa: ["Rekam medis asli kedua pasien."] } } }));
  await page.reload();
  await card.getByTestId("clinical-ai-ask").click();
  const verdict = card.getByTestId("clinical-ai-result");
  await expect(verdict).toContainText("Tidak sesuai tagihan");
  await expect(verdict).toContainText("Catatan sama persis dengan pasien lain.");
  await expect(verdict).toContainText("Rekam medis asli kedua pasien.");
  await expect(card.getByTestId("clinical-ai-engine")).toHaveText("Dibaca AI");
  await expect(card.getByTestId("clinical-ai-facts")).toContainText("Tidak ada");
  await expect(card.getByTestId("clinical-ai-facts")).toContainText("3 hari");
  await expect(page.getByTestId("toast").filter({ hasText: "Catatan klinis selesai dibaca" }).last()).toBeVisible();
  await captureVisual(page, "clinical-note-desktop");
  await page.unroute(notePath);
  await page.unroute(analysisPath);
});

async function login(page: Page, username: string, password: string) {
  await page.goto(uiUrl);
  await page.getByLabel("Nama pengguna").fill(username);
  await page.locator('input[autocomplete="current-password"]').fill(password);
  await page.getByRole("button", { name: "Masuk", exact: true }).click();
  await expect(page.getByRole("button", { name: new RegExp(username) })).toBeVisible();
}

async function captureVisual(page: Page, filename: string) {
  await expect(page.locator(".api-loading")).toHaveCount(0);
  await page.evaluate(() => Promise.all(document.getAnimations().map(animation => animation.finished.catch(() => undefined))));
  await page.evaluate(() => document.fonts.ready);
  const typography = await page.evaluate(() => {
    const style = getComputedStyle(document.body);
    const loadedFontFaces = [...document.fonts].filter(face => face.family.replaceAll('"', "") === "Plus Jakarta Sans" && face.status === "loaded").length;
    return { family: style.fontFamily, size: style.fontSize, weight: style.fontWeight, lineHeight: style.lineHeight, loadedFontFaces };
  });
  expect(typography.family).toContain("Plus Jakarta Sans");
  expect(typography.loadedFontFaces).toBeGreaterThan(0);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("DOM.enable");
  await cdp.send("CSS.enable");
  const { root } = await cdp.send("DOM.getDocument");
  const textSelector = await page.evaluate(() => document.querySelector("h1 span") ? "h1 span" : "h1");
  const { nodeId } = await cdp.send("DOM.querySelector", { nodeId: root.nodeId, selector: textSelector });
  const { fonts } = await cdp.send("CSS.getPlatformFontsForNode", { nodeId });
  const renderedFamilies = [...new Set(fonts.map((font: { familyName: string }) => font.familyName))];
  expect(renderedFamilies.some(family => family.startsWith("Plus Jakarta Sans"))).toBe(true);
  await cdp.detach();
  console.log("Visual QA " + filename + ": " + JSON.stringify(typography));
  await page.screenshot({ path: path.join(visualRoot, filename + ".png"), fullPage: true });
}

async function readResult(page: Page, runId: string): Promise<unknown> {
  return page.evaluate(async (id) => {
    const response = await fetch("/api/v1/runs/" + encodeURIComponent(id), { credentials: "same-origin" });
    if (!response.ok) throw new Error("GET saved run returned HTTP " + response.status);
    return ((await response.json()) as { result: unknown }).result;
  }, runId);
}

async function csrfToken(page: Page): Promise<string> {
  // Authentication cookies are set by the same-origin Vite proxy response.
  const cookie = (await page.context().cookies(uiUrl + "/api/v1")).find((item) => item.name === "cir_csrf");
  if (!cookie?.value) throw new Error("CSRF cookie missing in isolated E2E session.");
  return cookie.value;
}

async function submitOutcome(page: Page, path: string, csrf: string): Promise<number> {
  return page.evaluate(
    async (input) => {
      const response = await fetch(input.path + "/outcome", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": input.csrf },
        body: JSON.stringify({ review_outcome: "signal_supported", note: "Synthetic permission check." }),
      });
      return response.status;
    },
    { path, csrf },
  );
}

function makeCsv(): string {
  const shared: Record<string, string> = {
    facility_id: "syn-facility-e2e-01",
    participant_token: "syn-participant-e2e-01",
    service_date: "2024-03-05",
    province_code: "synthetic-province",
    municipality_code: "synthetic-municipality",
    facility_ownership: "synthetic",
    facility_type: "synthetic-clinic",
    facility_class: "synthetic-class",
    admission_diagnosis: "DX-SYN-E2E",
    primary_diagnosis: "DX-SYN-E2E",
    claim_group: "synthetic-group",
    procedure_code: "PROC-SYN-E2E",
    billed_amount: "125.00",
    service_type: "physiotherapy",
    service_units: "1",
    facility_daily_capacity: "100",
    supporting_evidence_required: "referral;session_record",
    supporting_evidence_types: "referral;session_record",
    supporting_evidence_present: "true",
    service_timestamp: "2024-03-05T09:00:00",
    supporting_evidence_recording_status: "recorded",
    facility_daily_claim_count: "2",
  };
  const rows = [1, 2].map((index) => ({
    ...shared,
    claim_id: "syn-claim-e2e-" + String(index).padStart(3, "0"),
    case_id: "syn-claim-e2e-" + String(index).padStart(3, "0"),
  }));
  const quote = (value: string) => '"' + value.replaceAll('"', '""') + '"';
  return (
    [columns.join(","), ...rows.map((row) => columns.map((column) => quote(row[column] ?? "")).join(","))].join("\n") +
    "\n"
  );
}

async function freePort(): Promise<number> {
  const server = net.createServer();
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Could not allocate a temporary local port.");
  await new Promise<void>((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
  return address.port;
}

function start(command: string, args: string[], cwd: string, env: NodeJS.ProcessEnv): ChildProcess {
  const child = spawn(command, args, { cwd, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  output.set(child, []);
  const capture = (chunk: Buffer) => {
    const lines = output.get(child)!;
    lines.push(chunk.toString("utf8"));
    if (lines.join("").length > 12_000) lines.splice(0, Math.max(1, lines.length - 8));
  };
  child.stdout?.on("data", capture);
  child.stderr?.on("data", capture);
  return child;
}

async function waitFor(url: string, child: ChildProcess, label: string): Promise<void> {
  const until = Date.now() + 45_000;
  while (Date.now() < until) {
    if (child.exitCode !== null)
      throw new Error(
        label + " exited before readiness (code " + child.exitCode + "). " + tail(output.get(child)?.join("")),
      );
    try {
      if ((await fetch(url, { signal: AbortSignal.timeout(1500) })).ok) return;
    } catch {
      /* process is starting */
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(label + " did not become ready within 45 seconds. " + tail(output.get(child)?.join("")));
}

async function stop(child: ChildProcess | undefined): Promise<void> {
  if (!child || child.exitCode !== null) return;
  child.kill();
  await Promise.race([once(child, "exit"), new Promise((resolve) => setTimeout(resolve, 5000))]);
  if (child.exitCode === null) child.kill("SIGKILL");
}

function tail(text?: string): string {
  return (text ?? "").split(/\r?\n/).slice(-8).join("\n").slice(-2500);
}
