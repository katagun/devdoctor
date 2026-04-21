import { useCallback, useEffect, useReducer, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { CacheTableRow } from "@/components/CacheTable";
import { apiFetch } from "@/api";
import type {
  CleanupResult,
  ExecuteProgressEntry,
  WizardState,
} from "@/components/CleanupWizard/CleanupWizardState";

type Action =
  | { type: "START"; jobId: string }
  | { type: "PROMPT"; entry_id: string; recipe: string[] }
  | { type: "PROMPT_ANSWERED"; entry_id: string }
  | { type: "CONFIRM_REQUIRED"; summary: string }
  | { type: "EXECUTE_START"; entry_id: string; cmd: string }
  | { type: "EXECUTE_PROGRESS"; entry_id: string; chunk: string }
  | {
      type: "EXECUTE_RESULT";
      entry_id: string;
      status: ExecuteProgressEntry["status"];
      freed_bytes: number;
      message?: string;
    }
  | { type: "DONE"; results: CleanupResult[] }
  | { type: "JOB_ERROR"; message: string }
  | { type: "TOGGLE_ENABLED"; id: string; next: boolean }
  | { type: "CLOSE" };

export function reducer(state: WizardState, action: Action): WizardState {
  switch (action.type) {
    case "START":
      return { ...state, jobId: action.jobId, step: "execute" };
    case "PROMPT":
      return {
        ...state,
        pendingPrompts: [
          ...state.pendingPrompts,
          { entry_id: action.entry_id, recipe: action.recipe },
        ],
      };
    case "PROMPT_ANSWERED":
      return {
        ...state,
        pendingPrompts: state.pendingPrompts.filter(
          (p) => p.entry_id !== action.entry_id,
        ),
      };
    case "CONFIRM_REQUIRED":
      return { ...state, awaitingConfirm: { summary: action.summary } };
    case "EXECUTE_START":
      return {
        ...state,
        awaitingConfirm: null,
        progress: {
          ...state.progress,
          [action.entry_id]: {
            entry_id: action.entry_id,
            status: "running",
            freed_bytes: 0,
            consoleLines: [`▸ ${action.cmd}`],
          },
        },
      };
    case "EXECUTE_PROGRESS": {
      const prev = state.progress[action.entry_id];
      if (!prev) return state;
      return {
        ...state,
        progress: {
          ...state.progress,
          [action.entry_id]: {
            ...prev,
            consoleLines: [...prev.consoleLines, action.chunk],
          },
        },
      };
    }
    case "EXECUTE_RESULT": {
      const prev = state.progress[action.entry_id];
      return {
        ...state,
        progress: {
          ...state.progress,
          [action.entry_id]: {
            entry_id: action.entry_id,
            status: action.status,
            freed_bytes: action.freed_bytes,
            message: action.message,
            consoleLines: prev?.consoleLines ?? [],
          },
        },
      };
    }
    case "DONE":
      return { ...state, step: "summary", results: action.results };
    case "JOB_ERROR":
      return { ...state, step: "summary", error: action.message };
    case "TOGGLE_ENABLED": {
      const copy = new Set(state.enabled);
      if (action.next) copy.add(action.id);
      else copy.delete(action.id);
      return { ...state, enabled: copy };
    }
    case "CLOSE":
      return {
        ...state,
        step: "review",
        jobId: null,
        results: null,
        progress: {},
        pendingPrompts: [],
        awaitingConfirm: null,
        error: null,
      };
  }
}

export function initial(entries: CacheTableRow[]): WizardState {
  return {
    step: "review",
    entries,
    enabled: new Set(
      entries.filter((e) => e.risk !== "dangerous").map((e) => e.id),
    ),
    jobId: null,
    awaitingConfirm: null,
    pendingPrompts: [],
    progress: {},
    results: null,
    error: null,
  };
}

function parseEvent(e: MessageEvent): Record<string, unknown> {
  try {
    return JSON.parse(e.data) as Record<string, unknown>;
  } catch {
    return {};
  }
}

export function useCleanupWizard({
  entries,
  onSuccess,
}: {
  entries: CacheTableRow[];
  onSuccess?: (results: CleanupResult[]) => void;
}) {
  const [state, dispatch] = useReducer(reducer, entries, initial);
  const esRef = useRef<EventSource | null>(null);
  const queryClient = useQueryClient();
  // Refs so startJob/answerPrompt/confirm keep stable identities across state
  // changes — switching to useCallback deps would reintroduce stale-closure bugs.
  const enabledRef = useRef(state.enabled);
  enabledRef.current = state.enabled;
  const jobIdRef = useRef<string | null>(state.jobId);
  jobIdRef.current = state.jobId;
  // Ref the callback so openStream's deps stay empty and the listener reads the
  // latest caller-supplied handler at dispatch time.
  const onSuccessRef = useRef(onSuccess);
  onSuccessRef.current = onSuccess;

  useEffect(() => {
    return () => {
      esRef.current?.close();
      esRef.current = null;
    };
  }, []);

  const openStream = useCallback((jobId: string) => {
    // Defensively close any prior stream so repeated startJob() calls don't leak.
    esRef.current?.close();
    const es = new EventSource(`/api/clean/jobs/${jobId}/events`);
    esRef.current = es;
    es.addEventListener("prompt", (e) => {
      const d = parseEvent(e as MessageEvent);
      dispatch({
        type: "PROMPT",
        entry_id: String(d.entry_id ?? ""),
        recipe: Array.isArray(d.recipe) ? (d.recipe as string[]) : [],
      });
    });
    es.addEventListener("awaiting_confirm", (e) => {
      const d = parseEvent(e as MessageEvent);
      dispatch({
        type: "CONFIRM_REQUIRED",
        summary: String(d.summary ?? ""),
      });
    });
    es.addEventListener("execute_start", (e) => {
      const d = parseEvent(e as MessageEvent);
      dispatch({
        type: "EXECUTE_START",
        entry_id: String(d.entry_id ?? ""),
        cmd: String(d.cmd ?? ""),
      });
    });
    es.addEventListener("execute_progress", (e) => {
      const d = parseEvent(e as MessageEvent);
      dispatch({
        type: "EXECUTE_PROGRESS",
        entry_id: String(d.entry_id ?? ""),
        chunk: String(d.chunk ?? ""),
      });
    });
    es.addEventListener("execute_result", (e) => {
      const d = parseEvent(e as MessageEvent);
      dispatch({
        type: "EXECUTE_RESULT",
        entry_id: String(d.entry_id ?? ""),
        status: (d.status as ExecuteProgressEntry["status"]) ?? "ok",
        freed_bytes: Number(d.freed_bytes ?? 0),
        message: d.message as string | undefined,
      });
    });
    es.addEventListener("done", (e) => {
      const d = parseEvent(e as MessageEvent);
      const results = Array.isArray(d.results) ? (d.results as CleanupResult[]) : [];
      dispatch({ type: "DONE", results });
      es.close();
      if (esRef.current === es) esRef.current = null;
      // Refresh any view sitting on stale post-cleanup data. Invalidate rather
      // than refetch: consumers that aren't mounted just get marked stale.
      queryClient.invalidateQueries({ queryKey: ["scan"] });
      queryClient.invalidateQueries({ queryKey: ["history"] });
      onSuccessRef.current?.(results);
    });
    es.addEventListener("job_error", (e) => {
      const d = parseEvent(e as MessageEvent);
      dispatch({
        type: "JOB_ERROR",
        message: String(d.message ?? "cleanup failed"),
      });
      es.close();
      if (esRef.current === es) esRef.current = null;
      // The job_error path also wrote an audit entry; refresh history.
      queryClient.invalidateQueries({ queryKey: ["history"] });
    });
  }, [queryClient]);

  const startJob = useCallback(async () => {
    const ids = Array.from(enabledRef.current);
    try {
      const res = await apiFetch<{ job_id: string }>("/clean/jobs", {
        method: "POST",
        body: JSON.stringify({ entry_ids: ids, allow_dangerous: false }),
      });
      dispatch({ type: "START", jobId: res.job_id });
      openStream(res.job_id);
    } catch (err) {
      console.error("Failed to start cleanup job:", err);
    }
  }, [openStream]);

  const answerPrompt = useCallback(
    async (entry_id: string, choice: "y" | "n" | "a" | "s" | "q") => {
      const jobId = jobIdRef.current;
      if (!jobId) return;
      await apiFetch(`/clean/jobs/${jobId}/answer`, {
        method: "POST",
        body: JSON.stringify({ entry_id, choice }),
      });
      dispatch({ type: "PROMPT_ANSWERED", entry_id });
    },
    [],
  );

  const confirm = useCallback(async () => {
    const jobId = jobIdRef.current;
    if (!jobId) return;
    await apiFetch(`/clean/jobs/${jobId}/confirm`, {
      method: "POST",
      body: JSON.stringify({ confirmed: true }),
    });
  }, []);

  const cancel = useCallback(async () => {
    const jobId = jobIdRef.current;
    if (!jobId) return;
    await apiFetch(`/clean/jobs/${jobId}/cancel`, { method: "POST" });
    esRef.current?.close();
    esRef.current = null;
  }, []);

  const toggleEnabled = useCallback((id: string, next: boolean) => {
    dispatch({ type: "TOGGLE_ENABLED", id, next });
  }, []);

  const close = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
    dispatch({ type: "CLOSE" });
  }, []);

  return { state, startJob, answerPrompt, confirm, cancel, toggleEnabled, close };
}
