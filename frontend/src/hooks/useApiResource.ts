import { useCallback, useEffect, useState } from "react";

export type ApiState<T> =
  | { status: "loading" }
  | { status: "error"; message: string; httpStatus: number | null }
  | { status: "success"; data: T };

export function useApiResource<T>(loader: (signal: AbortSignal) => Promise<T>) {
  const [state, setState] = useState<ApiState<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => setAttempt(value => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    void loader(controller.signal).then(
      data => setState({ status: "success", data }),
      error => {
        if (controller.signal.aborted) return;
        const value = error instanceof Error ? error : new Error("Terjadi kesalahan yang tidak diketahui.");
        const httpStatus = "status" in value && typeof value.status === "number" ? value.status : null;
        setState({ status: "error", message: value.message, httpStatus });
      },
    );
    return () => controller.abort();
  }, [loader, attempt]);

  return { state, reload };
}
