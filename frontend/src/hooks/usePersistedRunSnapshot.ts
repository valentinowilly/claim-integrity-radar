import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiClientError, getRun, getRuns, type RunDetailResponse, type RunManifest } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useNotify } from "../notifications/NotificationCenter";

export type PersistedRunState =
  | { status: "loading" }
  | { status: "forbidden" }
  | { status: "empty" }
  | { status: "error"; message: string; httpStatus: number | null }
  | { status: "success"; runs: RunManifest[]; detail: RunDetailResponse; notice?: string };

/** `pinnedRunId` (from a case URL) overrides the `run_id` query parameter and is never rewritten. */
export function usePersistedRunSnapshot(pinnedRunId?: string) {
  const { state: auth } = useAuth();
  const notify = useNotify();
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedRunId = pinnedRunId || searchParams.get("run_id");
  // The latest parameters, read when the effect needs them: the analysis is reloaded only when the chosen
  // analysis changes, not when a page filter or the search text changes the address.
  // react-router gives setSearchParams a new identity on every address change, so it is read through a ref too.
  const paramsRef = useRef(searchParams);
  paramsRef.current = searchParams;
  const setParamsRef = useRef(setSearchParams);
  setParamsRef.current = setSearchParams;
  const [state, setState] = useState<PersistedRunState>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  // Set when the address named an analysis that is no longer listed (archived or replaced by a newer one).
  const replacedArchived = useRef(false);
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
        const listed = !selectedRunId || response.items.some(run => run.run_id === selectedRunId);
        if (selectedRunId && !listed && !pinnedRunId) {
          // Pages show only analyses that are still listed; a link to an archived one opens the latest.
          replacedArchived.current = true;
          const next = new URLSearchParams(paramsRef.current);
          next.set("run_id", response.items[0].run_id);
          setParamsRef.current(next, { replace: true });
          return;
        }
        const chosenId = selectedRunId ?? response.items[0].run_id;
        if (!selectedRunId) {
          const next = new URLSearchParams(paramsRef.current);
          next.set("run_id", chosenId);
          setParamsRef.current(next, { replace: true });
          return;
        }
        const detail = await getRun(chosenId, controller.signal);
        const notice = replacedArchived.current
          ? "Analisis yang dibuka sudah diarsipkan atau digantikan analisis yang lebih baru; yang ditampilkan analisis terbaru."
          : undefined;
        replacedArchived.current = false;
        if (notice) notify({ tone: "info", title: "Menampilkan analisis terbaru", message: notice });
        setState({ status: "success", runs: response.items, detail, notice });
      } catch (error) {
        if (controller.signal.aborted) return;
        const e = error instanceof Error ? error : new Error("Hasil analisis tidak dapat dimuat.");
        const status = error instanceof ApiClientError ? error.status : null;
        setState(status === 403 ? { status: "forbidden" } : { status: "error", message: e.message, httpStatus: status });
      }
    })();
    return () => controller.abort();
  }, [canRead, selectedRunId, pinnedRunId, reloadKey, notify]);

  const selectRun = useCallback((runId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("run_id", runId);
    setSearchParams(next);
  }, [searchParams, setSearchParams]);
  const reload = useCallback(() => setReloadKey(value => value + 1), []);
  return { state, selectRun, reload, canRead };
}
