import { test, expect, type Page } from "@playwright/test";
import { randomBytes } from "node:crypto";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, mkdir, rm, writeFile, access } from "node:fs/promises";
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
      CIR_AUTH_DB_PATH: path.join(tempRoot, "auth.sqlite3"),
      CIR_BATCH_DB_PATH: path.join(tempRoot, "batch-run.sqlite3"),
      CIR_REVIEW_DB_PATH: path.join(tempRoot, "review.sqlite3"),
      CIR_COOKIE_SECURE: "false",
    },
  );
  await waitFor(apiUrl + "/health", apiProcess, "FastAPI");

  const vite = path.join(frontendDir, "node_modules", "vite", "bin", "vite.js");
  uiProcess = start(
    process.execPath,
    [vite, "--host", "127.0.0.1", "--port", String(uiPort), "--strictPort"],
    frontendDir,
    {
      ...process.env,
      VITE_BACKEND_URL: apiUrl,
    },
  );
  await waitFor(uiUrl, uiProcess, "Vite");
}, 120_000);

test.afterAll(async () => {
  await stop(uiProcess);
  await stop(apiProcess);
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
  for (const linkName of ["Overview", "Analisis Risiko", "Antrean Audit", "Data Klaim", "Evaluasi"]) {
    await expect(page.getByRole("navigation", { name: "Navigasi utama" }).getByRole("link", { name: linkName })).toBeVisible();
  }
  await page.getByRole("button", { name: new RegExp(platformAdmin) }).click();
  await expect(page.getByRole("menu")).toBeVisible();
  await captureVisual(page, "profile-menu-desktop");
  await page.getByRole("button", { name: new RegExp(platformAdmin) }).click();
  await page.goto(uiUrl + "/workflow");
  await expect(page.getByRole("heading", { name: "Data Klaim" })).toBeVisible();
  await captureVisual(page, "workflow-desktop");
  await expect(page.getByText("Ruang kerja data sintetis.")).toBeVisible();
  await page.getByLabel("Berkas CSV sintetis").setInputFiles(rejectedCsv);
  await page.getByLabel("Nama batch").fill("synthetic-e2e-rejected");
  await page.getByRole("button", { name: "Validasi dan simpan" }).click();
  await expect(page.getByText("Ditolak", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Impor ditolak; batch tidak dapat digunakan untuk analisis.")).toBeVisible();

  await page.route("**/api/v1/batches/import", route => route.abort());
  await page.getByLabel("Berkas CSV sintetis").setInputFiles(csvPath);
  await page.getByLabel("Nama batch").fill("synthetic-e2e-request-failure");
  await page.getByRole("button", { name: "Validasi dan simpan" }).click();
  await expect(page.getByRole("alert").getByText("Permintaan gagal")).toBeVisible();
  await page.unroute("**/api/v1/batches/import");

  await page.getByLabel("Nama batch").fill("synthetic-playwright-smoke");
  await page.getByRole("button", { name: "Validasi dan simpan" }).click();
  await expect(page.getByText("Siap", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("synthetic-claims-v1").first()).toBeVisible();

  const createResponsePromise = page.waitForResponse(
    (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/runs",
  );
  await page.getByRole("button", { name: "Jalankan analisis" }).click();
  const createResponse = await createResponsePromise;
  expect(createResponse.status()).toBe(201);
  const created = (await createResponse.json()) as { run: { run_id: string; batch_id: string; batch_version: number } };
  const runId = created.run.run_id;
  smokeRunId = runId;
  expect(runId).toBeTruthy();
  expect(created.run.batch_version).toBeGreaterThan(0);
  await expect(page.getByText("HASIL PERSISTEN")).toBeVisible();
  await expect(page.getByText("Cakupan enam pemeriksaan")).toBeVisible();

  await page.goto(uiUrl + "/");
  await expect(page.getByRole("heading", { name: "Ringkasan pemeriksaan" })).toBeVisible();
  await expect(page.getByLabel("AnalysisRun tersimpan", { exact: true })).toHaveValue(runId);
  await expect(page.getByText(runId, { exact: true }).first()).toBeVisible();
  await captureVisual(page, "overview-desktop");
  await expect(page.getByTestId("overview-access-restricted")).toHaveCount(0);
  expect(legacyAnalyticsRequests).toBe(0);

  await page.goto(uiUrl + "/evaluation");
  await expect(page.getByRole("heading", { name: "Evaluasi" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Metrik belum tersedia" })).toBeVisible();
  await captureVisual(page, "evaluation-desktop");

  await page.goto(uiUrl + "/analysis");
  await expect(page.getByRole("heading", { name: "Cakupan dan sinyal" })).toBeVisible();
  await expect(page.getByLabel("AnalysisRun tersimpan", { exact: true })).toHaveValue(runId);
  expect(new URL(page.url()).searchParams.get("run_id")).toBe(runId);
  await captureVisual(page, "analysis-desktop");
  await page.goto(uiUrl + "/cases");
  await expect(page.getByRole("heading", { name: /kasus/ })).toBeVisible();
  await expect(page.getByLabel("AnalysisRun tersimpan", { exact: true })).toHaveValue(runId);
  expect(new URL(page.url()).searchParams.get("run_id")).toBe(runId);
  await captureVisual(page, "cases-desktop");
  const indicatorFilter = page.getByLabel("Filter indikator");
  expect(await indicatorFilter.locator("option").count()).toBeGreaterThan(1);
  const firstIndicator = await indicatorFilter.locator("option").nth(1).getAttribute("value");
  expect(firstIndicator).toBeTruthy();
  await indicatorFilter.selectOption(firstIndicator!);
  await expect(indicatorFilter).toHaveValue(firstIndicator!);
  await indicatorFilter.selectOption("");
  const queueCandidate = page.locator('a[href^="/runs/"][href*="/cases/"]').first();
  await expect(queueCandidate).toBeVisible();
  const href = await queueCandidate.getAttribute("href");
  expect(href).toContain("/runs/" + encodeURIComponent(runId) + "/cases/");
  const caseId = decodeURIComponent(href!.split("/").at(-1)!);
  smokeCaseId = caseId;
  const detailUrl = uiUrl + href;
  await queueCandidate.click();
  await expect(page).toHaveURL(detailUrl);
  await expect(page.getByRole("heading", { name: "Detail kandidat" })).toBeVisible();
  await expect(page.getByText("Sinyal untuk diperiksa auditor")).toBeVisible();
  await captureVisual(page, "case-review-desktop");

  await page.goto(uiUrl + "/workflow");
  const runDetailResponsePromise = page.waitForResponse(
    (response) => response.request().method() === "GET" && new URL(response.url()).pathname === "/api/v1/runs/" + runId,
  );
  await page.getByRole("button", { name: new RegExp(runId) }).click();
  const runDetailResponse = await runDetailResponsePromise;
  expect(runDetailResponse.status()).toBe(200);
  const runDetailPayload = (await runDetailResponse.json()) as {
    run: Record<string, unknown>;
    result: { execution_status: string; indicator_coverage: Array<{ status: string; search_truncated: boolean }> } | null;
  };
  await expect(page.getByText("HASIL PERSISTEN")).toBeVisible();
  await expect(page.getByText("Cakupan enam pemeriksaan")).toBeVisible();
  expect(runDetailPayload.result).not.toBeNull();
  expect(runDetailPayload.result!.indicator_coverage.some(item => item.status === "partial" || item.status === "unavailable" || item.search_truncated)).toBe(true);
  expect(runCreateRequests).toBe(1);
  const resultBefore = await readResult(page, runId);
  await page.goto(detailUrl);

  await expect(page.getByRole("button", { name: "Simpan outcome" })).toBeEnabled();

  await page.getByLabel("Status").selectOption("awaiting_evidence");
  await page.getByLabel("Catatan sintetis opsional").fill("Synthetic verifier smoke note; no real claim data.");
  await page.getByRole("button", { name: "Simpan status" }).click();
  await expect(page.getByText("Status dan riwayat dimuat ulang dari penyimpanan server.")).toBeVisible();
  await expect(page.getByText("Menunggu Bukti Tambahan").first()).toBeVisible();

  await page.getByLabel("Outcome").selectOption("signal_supported");
  await page.getByLabel("Catatan sintetis opsional").fill("Synthetic platform admin outcome; no real claim data.");
  await page.getByRole("button", { name: "Simpan outcome" }).click();
  await expect(page.getByText("Outcome dan riwayat dimuat ulang dari penyimpanan server.")).toBeVisible();
  await expect(page.getByText("Sinyal didukung oleh tinjauan").first()).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { name: "Detail kandidat" })).toBeVisible();
  await expect(page.getByText("Menunggu Bukti Tambahan").first()).toBeVisible();
  await expect(page.getByText("Sinyal didukung oleh tinjauan").first()).toBeVisible();
  await expect(page.locator(".history-note").filter({ hasText: "Synthetic verifier smoke note; no real claim data." })).toBeVisible();
  await expect(page.locator(".history-note").filter({ hasText: "Synthetic platform admin outcome; no real claim data." })).toBeVisible();
  await expect(page.getByText("2 event")).toBeVisible();
  expect(await readResult(page, runId)).toEqual(resultBefore);
  expect(await readResult(page, runId)).toEqual(resultBefore);
  expect(runCreateRequests).toBe(1);
  expect(legacyAnalyticsRequests).toBe(0);
  expect(caseId).toBeTruthy();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(uiUrl + "/");
  await expect(page.getByRole("heading", { name: "Ringkasan pemeriksaan" })).toBeVisible();
  await page.getByRole("button", { name: "Buka navigasi" }).click();
  await expect(page.getByRole("navigation", { name: "Navigasi utama" })).toBeVisible();
  await captureVisual(page, "navigation-mobile-open");
  for (const [name, route, heading] of [
    ["overview", "/", "Ringkasan pemeriksaan"],
    ["analysis", "/analysis?run_id=" + encodeURIComponent(runId), "Cakupan dan sinyal"],
    ["cases", "/cases?run_id=" + encodeURIComponent(runId), "Kasus"],
    ["case-review", href!, "Detail kandidat"],
    ["workflow", "/workflow", "Data Klaim"],
    ["evaluation", "/evaluation", "Evaluasi"],
  ]) {
    await page.goto(uiUrl + route);
    await expect(page.getByRole("heading", { name: new RegExp(heading, "i") })).toBeVisible();
    await captureVisual(page, name + "-mobile");
  }
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
  await expect(page.getByText("Belum ada AnalysisRun", { exact: true })).toBeVisible();
  await expect(page.getByTestId("overview-access-restricted")).toHaveCount(0);
  await expect(page.getByText("Klaim dipertimbangkan", { exact: true })).toHaveCount(0);

  await page.unroute("**/api/v1/runs?*");
  await page.route("**/api/v1/runs?*", route => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ detail: { code: "SYNTHETIC_TEST_UNAVAILABLE", message: "Synthetic service unavailable for test." } }),
  }));
  await page.reload();
  await expect(page.getByRole("alert").getByText("Data gagal dimuat")).toBeVisible();
  await expect(page.getByText("Belum ada AnalysisRun", { exact: true })).toHaveCount(0);
  await expect(page.getByTestId("overview-access-restricted")).toHaveCount(0);

  expect(smokeRunId).toBeTruthy();
  expect(smokeCaseId).toBeTruthy();
  const deniedOutcome = await submitOutcome(
    page,
    `/api/v1/runs/${encodeURIComponent(smokeRunId)}/cases/${encodeURIComponent(smokeCaseId)}/review`,
    await csrfToken(page),
  );
  expect(deniedOutcome).toBe(403);
});

async function login(page: Page, username: string, password: string) {
  await page.goto(uiUrl);
  await page.getByLabel("Nama pengguna").fill(username);
  await page.locator('input[autocomplete="current-password"]').fill(password);
  await page.getByRole("button", { name: "Masuk" }).click();
  await expect(page.getByRole("button", { name: new RegExp(username) })).toBeVisible();
}

async function captureVisual(page: Page, filename: string) {
  await expect(page.locator(".api-loading")).toHaveCount(0);
  await page.evaluate(() => Promise.all(document.getAnimations().map(animation => animation.finished.catch(() => undefined))));
  await page.evaluate(() => document.fonts.ready);
  const typography = await page.evaluate(() => {
    const style = getComputedStyle(document.body);
    const loadedBarlowFaces = [...document.fonts].filter(face => face.family.replaceAll('"', "") === "Barlow" && face.status === "loaded").length;
    return { family: style.fontFamily, size: style.fontSize, weight: style.fontWeight, lineHeight: style.lineHeight, loadedBarlowFaces };
  });
  expect(typography.family).toContain("Barlow");
  expect(typography.loadedBarlowFaces).toBeGreaterThan(0);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("DOM.enable");
  await cdp.send("CSS.enable");
  const { root } = await cdp.send("DOM.getDocument");
  const textSelector = await page.evaluate(() => document.querySelector("h1 span") ? "h1 span" : "h1");
  const { nodeId } = await cdp.send("DOM.querySelector", { nodeId: root.nodeId, selector: textSelector });
  const { fonts } = await cdp.send("CSS.getPlatformFontsForNode", { nodeId });
  const renderedFamilies = [...new Set(fonts.map((font: { familyName: string }) => font.familyName))];
  expect(renderedFamilies.some(family => family.startsWith("Barlow"))).toBe(true);
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
