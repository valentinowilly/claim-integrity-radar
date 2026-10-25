import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiClientError, getRun, getRuns, type RunDetailResponse, type RunManifest } from "../api/client";
import { useAuth } from "../auth/AuthContext";

export type PersistedRunState =
  | { status: "loading" }
  | { status: "forbidden" }
  | { status: "empty" }
  | { status: "error"; message: string; httpStatus: number | null }
  | { status: "success"; runs: RunManifest[]; detail: RunDetailResponse };

export function usePersistedRunSnapshot() {
  const { state: auth } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedRunId = searchParams.get("run_id");
  const [state, setState] = useState<PersistedRunState>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  const permissions = "session" in auth ? auth.session?.permissions ?? [] : [];
  const canRead = permissions.includes("runs:read") && permissions.includes("runs:results:read");

  useEffect(() => {
    if (!canRead) { setState({ status: "forbidden" }); return; }
    const controller = new AbortController();
    setState({ status: "loading" });
    void (async () => {
      try {
        const response = await getRuns(50, 0, undefined, controller.signal);
        if (!response.items.length) { setState({ status: "empty" }); return; }
        const chosenId = selectedRunId ?? response.items[0].run_id;
        if (!selectedRunId) {
          const next = new URLSearchParams(searchParams);
          next.set("run_id", chosenId);
          setSearchParams(next, { replace: true });
          return;
        }
        const detail = await getRun(chosenId, controller.signal);
        setState({ status: "success", runs: response.items, detail });
      } catch (error) {
        if (controller.signal.aborted) return;
        const e = error instanceof Error ? error : new Error("Hasil AnalysisRun gagal dimuat.");
        const status = error instanceof ApiClientError ? error.status : null;
        setState(status === 403 ? { status: "forbidden" } : { status: "error", message: e.message, httpStatus: status });
      }
    })();
    return () => controller.abort();
  }, [canRead, selectedRunId, reloadKey, searchParams, setSearchParams]);

  const selectRun = useCallback((runId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("run_id", runId);
    setSearchParams(next);
  }, [searchParams, setSearchParams]);
  const reload = useCallback(() => setReloadKey(value => value + 1), []);
  return { state, selectRun, reload, canRead };
}
