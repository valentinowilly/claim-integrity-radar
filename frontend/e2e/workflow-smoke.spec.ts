import { test, expect, type Page } from "@playwright/test";
import { randomBytes } from "node:crypto";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, rm, writeFile, access } from "node:fs/promises";
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
  "claim_id", "case_id", "facility_id", "participant_token", "service_date",
  "province_code", "municipality_code", "facility_ownership", "facility_type",
  "facility_class", "admission_diagnosis", "primary_diagnosis", "claim_group",
  "procedure_code", "billed_amount", "service_type", "service_units",
  "facility_daily_capacity", "supporting_evidence_required", "supporting_evidence_types",
  "supporting_evidence_present", "service_timestamp",
  "supporting_evidence_recording_status", "facility_daily_claim_count",
];

let tempRoot = "";
let apiUrl = "";
let uiUrl = "";
let apiProcess: ChildProcess | undefined;
let uiProcess: ChildProcess | undefined;
let operator = "";
let verifier = "";
let lead = "";
let operatorPassword = "";
let verifierPassword = "";
let leadPassword = "";
const output = new Map<ChildProcess, string[]>();

test.beforeAll(async () => {
  try { await access(python); } catch { throw new Error("Project virtualenv backend/.venv/Scripts/python.exe is unavailable."); }
  tempRoot = await mkdtemp(path.join(os.tmpdir(), tempPrefix));
  const suffix = randomBytes(6).toString("hex");
  operator = "e2e-operator-" + suffix;
  verifier = "e2e-verifier-" + suffix;
  lead = "e2e-lead-" + suffix;
  operatorPassword = randomBytes(24).toString("base64url");
  verifierPassword = randomBytes(24).toString("base64url");
  leadPassword = randomBytes(24).toString("base64url");

  const seedCode = [
    "import os",
    "from app.security.auth import AuthStore",
    "store = AuthStore(os.environ['CIR_E2E_AUTH_DB'])",
    "secret = os.environ['CIR_E2E_BOOTSTRAP_SECRET']",
    "admin = store.create_bootstrap_admin('e2e-bootstrap', os.environ['CIR_E2E_ADMIN_PASSWORD'], secret, secret)",
    "for name_key, password_key, role in [('CIR_E2E_OPERATOR','CIR_E2E_OPERATOR_PASSWORD','data_operator'), ('CIR_E2E_VERIFIER','CIR_E2E_VERIFIER_PASSWORD','verifikator'), ('CIR_E2E_LEAD','CIR_E2E_LEAD_PASSWORD','audit_lead')]:",
    "    store.create_user(os.environ[name_key], os.environ[password_key], role, admin['user_id'])",
  ].join("\n");
  const seed = spawnSync(python, ["-c", seedCode], {
    cwd: backendDir, encoding: "utf8", windowsHide: true,
    env: {
      ...process.env,
      CIR_E2E_AUTH_DB: path.join(tempRoot, "auth.sqlite3"),
      CIR_E2E_BOOTSTRAP_SECRET: randomBytes(32).toString("base64url"),
      CIR_E2E_ADMIN_PASSWORD: randomBytes(24).toString("base64url"),
      CIR_E2E_OPERATOR: operator, CIR_E2E_OPERATOR_PASSWORD: operatorPassword,
      CIR_E2E_VERIFIER: verifier, CIR_E2E_VERIFIER_PASSWORD: verifierPassword,
      CIR_E2E_LEAD: lead, CIR_E2E_LEAD_PASSWORD: leadPassword,
    },
  });
  if (seed.status !== 0) throw new Error("Disposable account provisioning failed (exit " + seed.status + "). " + tail(seed.stderr));

  const apiPort = await freePort();
  let uiPort = await freePort();
  while (uiPort === apiPort) uiPort = await freePort();
  apiUrl = "http://127.0.0.1:" + apiPort;
  uiUrl = "http://127.0.0.1:" + uiPort;
  apiProcess = start(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)], backendDir, {
    ...process.env,
    CIR_AUTH_DB_PATH: path.join(tempRoot, "auth.sqlite3"),
    CIR_BATCH_DB_PATH: path.join(tempRoot, "batch-run.sqlite3"),
    CIR_REVIEW_DB_PATH: path.join(tempRoot, "review.sqlite3"),
    CIR_COOKIE_SECURE: "false",
  });
  await waitFor(apiUrl + "/health", apiProcess, "FastAPI");

  const vite = path.join(frontendDir, "node_modules", "vite", "bin", "vite.js");
  uiProcess = start(process.execPath, [vite, "--host", "127.0.0.1", "--port", String(uiPort), "--strictPort"], frontendDir, {
    ...process.env, VITE_BACKEND_URL: apiUrl,
  });
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
  const csvPath = path.join(tempRoot, "synthetic-fixture.csv");
  await writeFile(csvPath, makeCsv(), { encoding: "utf8", flag: "wx" });
  await login(page, operator, operatorPassword);
  await page.goto(uiUrl + "/workflow");
  await expect(page.getByRole("heading", { name: "Batch dan AnalysisRun" })).toBeVisible();
  await expect(page.getByText("Synthetic only.")).toBeVisible();
  await page.getByLabel("File CSV sintetis").setInputFiles(csvPath);
  await page.getByLabel("Kunci batch").fill("synthetic-playwright-smoke");
  await page.getByRole("button", { name: "Validasi dan simpan batch" }).click();
  await expect(page.getByText("ready", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("synthetic-claims-v1").first()).toBeVisible();

  const createResponsePromise = page.waitForResponse(response =>
    response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/runs");
  await page.getByRole("button", { name: "Buat AnalysisRun dari batch terpilih" }).click();
  const createResponse = await createResponsePromise;
  expect(createResponse.status()).toBe(201);
  const created = await createResponse.json() as { run: { run_id: string; batch_id: string; batch_version: number } };
  const runId = created.run.run_id;
  expect(runId).toBeTruthy();
  expect(created.run.batch_version).toBeGreaterThan(0);
  await expect(page.getByText("Role ini dapat membuat run, tetapi tidak memiliki")).toBeVisible();

  await logout(page);
  await login(page, verifier, verifierPassword);
  await page.goto(uiUrl + "/workflow");
  await page.getByRole("button", { name: new RegExp(runId) }).click();
  await expect(page.getByText("HASIL PERSISTEN")).toBeVisible();
  await expect(page.getByText("Cakupan enam pemeriksaan")).toBeVisible();
  const resultBefore = await readResult(page, runId);
  const candidateLink = page.locator("a.result-case-link").first();
  await expect(candidateLink).toBeVisible();
  const href = await candidateLink.getAttribute("href");
  expect(href).toContain("/runs/" + encodeURIComponent(runId) + "/cases/");
  const caseId = decodeURIComponent(href!.split("/").at(-1)!);
  const detailUrl = uiUrl + href;
  await candidateLink.click();
  await expect(page).toHaveURL(detailUrl);
  await expect(page.getByRole("heading", { name: "Detail kandidat" })).toBeVisible();
  await expect(page.getByText("Sinyal untuk diperiksa auditor")).toBeVisible();

  await expect(page.getByRole("button", { name: "Simpan outcome" })).toBeDisabled();
  const csrf = await csrfToken(page);
  const deniedResponse = await submitOutcome(page, "/api/v1" + href! + "/review", csrf);
  expect(deniedResponse).toBe(403);

  await page.getByLabel("Status").selectOption("awaiting_evidence");
  await page.getByLabel("Catatan sintetis opsional").fill("Synthetic verifier smoke note; no real claim data.");
  await page.getByRole("button", { name: "Simpan status" }).click();
  await expect(page.getByText("Status dan riwayat dimuat ulang dari penyimpanan server.")).toBeVisible();
  await expect(page.getByText("Menunggu Bukti Tambahan").first()).toBeVisible();

  await logout(page);
  await login(page, lead, leadPassword);
  await page.goto(detailUrl);
  await expect(page.getByRole("button", { name: "Simpan outcome" })).toBeEnabled();
  await page.getByLabel("Outcome").selectOption("signal_supported");
  await page.getByLabel("Catatan sintetis opsional").fill("Synthetic audit lead outcome; no real claim data.");
  await page.getByRole("button", { name: "Simpan outcome" }).click();
  await expect(page.getByText("Outcome dan riwayat dimuat ulang dari penyimpanan server.")).toBeVisible();
  await expect(page.getByText("Sinyal didukung oleh tinjauan").first()).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { name: "Detail kandidat" })).toBeVisible();
  await expect(page.getByText("Menunggu Bukti Tambahan").first()).toBeVisible();
  await expect(page.getByText("Sinyal didukung oleh tinjauan").first()).toBeVisible();
  await expect(page.getByText("Synthetic verifier smoke note; no real claim data.")).toBeVisible();
  await expect(page.getByText("Synthetic audit lead outcome; no real claim data.")).toBeVisible();
  await expect(page.getByText("2 event")).toBeVisible();
  expect(await readResult(page, runId)).toEqual(resultBefore);
  expect(caseId).toBeTruthy();
});

async function login(page: Page, username: string, password: string) {
  await page.goto(uiUrl);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Masuk" }).click();
  await expect(page.getByRole("button", { name: "Keluar" })).toBeVisible();
}

async function logout(page: Page) {
  await page.getByRole("button", { name: "Keluar" }).click();
  await expect(page.getByRole("heading", { name: "Masuk ke workspace" })).toBeVisible();
}

async function readResult(page: Page, runId: string): Promise<unknown> {
  return page.evaluate(async id => {
    const response = await fetch("/api/v1/runs/" + encodeURIComponent(id), { credentials: "same-origin" });
    if (!response.ok) throw new Error("GET saved run returned HTTP " + response.status);
    return (await response.json() as { result: unknown }).result;
  }, runId);
}

async function csrfToken(page: Page): Promise<string> {
  // Authentication cookies are set by the same-origin Vite proxy response.
  const cookie = (await page.context().cookies(uiUrl + "/api/v1")).find(item => item.name === "cir_csrf");
  if (!cookie?.value) throw new Error("CSRF cookie missing in isolated E2E session.");
  return cookie.value;
}

async function submitOutcome(page: Page, path: string, csrf: string): Promise<number> {
  return page.evaluate(async input => {
    const response = await fetch(input.path + "/outcome", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": input.csrf },
      body: JSON.stringify({ review_outcome: "signal_supported", note: "Synthetic permission check." }),
    });
    return response.status;
  }, { path, csrf });
}

function makeCsv(): string {
  const shared: Record<string, string> = {
    facility_id: "syn-facility-e2e-01", participant_token: "syn-participant-e2e-01",
    service_date: "2024-03-05", province_code: "synthetic-province",
    municipality_code: "synthetic-municipality", facility_ownership: "synthetic",
    facility_type: "synthetic-clinic", facility_class: "synthetic-class",
    admission_diagnosis: "DX-SYN-E2E", primary_diagnosis: "DX-SYN-E2E",
    claim_group: "synthetic-group", procedure_code: "PROC-SYN-E2E", billed_amount: "125.00",
    service_type: "physiotherapy", service_units: "1", facility_daily_capacity: "100",
    supporting_evidence_required: "referral;session_record",
    supporting_evidence_types: "referral;session_record", supporting_evidence_present: "true",
    service_timestamp: "2024-03-05T09:00:00", supporting_evidence_recording_status: "recorded",
    facility_daily_claim_count: "2",
  };
  const rows = [1, 2].map(index => ({
    ...shared,
    claim_id: "syn-claim-e2e-" + String(index).padStart(3, "0"),
    case_id: "syn-claim-e2e-" + String(index).padStart(3, "0"),
  }));
  const quote = (value: string) => "\"" + value.replaceAll("\"", "\"\"") + "\"";
  return [columns.join(","), ...rows.map(row => columns.map(column => quote(row[column] ?? "")).join(","))].join("\n") + "\n";
}

async function freePort(): Promise<number> {
  const server = net.createServer();
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Could not allocate a temporary local port.");
  await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
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
    if (child.exitCode !== null) throw new Error(label + " exited before readiness (code " + child.exitCode + "). " + tail(output.get(child)?.join("")));
    try {
      if ((await fetch(url, { signal: AbortSignal.timeout(1500) })).ok) return;
    } catch { /* process is starting */ }
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  throw new Error(label + " did not become ready within 45 seconds. " + tail(output.get(child)?.join("")));
}

async function stop(child: ChildProcess | undefined): Promise<void> {
  if (!child || child.exitCode !== null) return;
  child.kill();
  await Promise.race([once(child, "exit"), new Promise(resolve => setTimeout(resolve, 5000))]);
  if (child.exitCode === null) child.kill("SIGKILL");
}

function tail(text?: string): string {
  return (text ?? "").split(/\r?\n/).slice(-8).join("\n").slice(-2500);
}
