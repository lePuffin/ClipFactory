import { useEffect, useRef, useState } from "react";

import { apiGet } from "../api/client";

export type Resource<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; data: T };

export type RefreshOptions<T> = {
  intervalMs: number;
  /** Polling stops once this returns false for the latest data. */
  while?: (data: T) => boolean;
};

export function useResource<T>(
  path: string | null,
  refresh?: RefreshOptions<T>,
): [Resource<T>, () => void] {
  const [resource, setResource] = useState<Resource<T>>({ status: "loading" });
  const [revision, setRevision] = useState(0);
  const intervalMs = refresh?.intervalMs;
  const keepPolling = useRef(refresh?.while);
  keepPolling.current = refresh?.while;

  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let loaded = false;
    let active = true;
    setResource({ status: "loading" });
    const load = () => {
      void apiGet<T>(path, controller.signal).then(
        (data) => {
          loaded = true;
          active = keepPolling.current?.(data) ?? true;
          setResource({ status: "success", data });
        },
        (error: unknown) => {
          if (controller.signal.aborted) return;
          // Background refreshes keep the last good data instead of flashing an error.
          if (!loaded) setResource({ status: "error", message: error instanceof Error ? error.message : "Request failed" });
        },
      ).finally(() => {
        if (intervalMs && active && !controller.signal.aborted) timer = setTimeout(load, intervalMs);
      });
    };
    load();
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [path, revision, intervalMs]);

  return [resource, () => setRevision((value) => value + 1)];
}