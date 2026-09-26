import { useCallback, useEffect, useReducer, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { CacheTableRow } from "@/components/CacheTable";
import { apiFetch, ApiError } from "@/api";
import type {
  CleanupResult,
  ExecuteProgressEntry,
  WizardState,
} from "@/components/CleanupWizard/CleanupWizardState";

type Action =
  | { type: "START_REQUESTED" }
  | { type: "START"; jobId: string }
  | { type: "START_FAILED"; message: string }
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
      bytes_verified?: boolean;
      message?: string;
    }
  | {
      type: "DONE";
      results: CleanupResult[];
      estimatedReclaimedBytes: number;
      bytesVerified: boolean;
    }
  | { type: "JOB_ERROR"; message: string }
  | { type: "TOGGLE_ENABLED"; id: string; next: boolean }
  | { type: "CLOSE" };

// Only the tail of the console is ever rendered (ExecuteStep shows the last
// line), but a verbose command can stream thousands of chunks. Cap the buffer
// so a long-running cleanup doesn't grow state without bound.
const MAX_CONSOLE_LINES = 200;

export function reducer(state: WizardState, action: Action): WizardState {
  switch (action.type) {
    case "START_REQUESTED":
      return { ...state, starting: true, startError: null };
    case "START":
      return { ...state, starting: false, jobId: action.jobId, step: "execute" };
    case "START_FAILED":
      return { ...state, starting: false, startError: action.message };
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
            consoleLines: [...prev.consoleLines, action.chunk].slice(-MAX_CONSOLE_LINES),
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
            bytes_verified: action.bytes_verified,
            message: action.message,
            consoleLines: prev?.consoleLines ?? [],
          },
        },
      };
    }
    case "DONE":
      return {
        ...state,
        step: "summary",
        results: action.results,
        estimatedReclaimedBytes: action.estimatedReclaimedBytes,
        bytesVerified: action.bytesVerified,
      };
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
        starting: false,
        startError: null,
        jobId: null,
        results: null,
        estimatedReclaimedBytes: null,
        bytesVerified: false,
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
    starting: false,
    startError: null,
    jobId: null,
    awaitingConfirm: null,
    pendingPrompts: [],
    progress: {},
    results: null,
    estimatedReclaimedBytes: null,
    bytesVerified: false,
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

function startErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.code === "job_in_progress") {
    return "Another cleanup is still running. Try again when it has finished.";
  }
  if (err instanceof ApiError && err.code === "unknown_entry") {
    return "Some of these entries are no longer on disk. Close this and rescan.";
  }
  return `Could not start the cleanup: ${err instanceof Error ? err.message : String(err)}`;
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
  const entriesRef = useRef(state.entries);
  entriesRef.current = state.entries;
  const jobIdRef = useRef<string | null>(state.jobId);
  jobIdRef.current = state.jobId;
  // Ref the callback so openStream's deps stay empty and the listener reads the
  // latest caller-supplied handler at dispatch time.
  const onSuccessRef = useRef(onSuccess);
  onSuccessRef.current = onSuccess;
  // Set synchronously, unlike state.starting, so a second click in the same frame
  // cannot send a second start.
  const startingRef = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
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
        bytes_verified: Boolean(d.bytes_verified),
        message: d.message as string | undefined,
      });
    });
    es.addEventListener("done", (e) => {
      const d = parseEvent(e as MessageEvent);
      const results = Array.isArray(d.results) ? (d.results as CleanupResult[]) : [];
      dispatch({
        type: "DONE",
        results,
        estimatedReclaimedBytes: Number(
          d.estimated_reclaimed_bytes ??
            results.reduce((sum, result) => sum + (result.freed_bytes || 0), 0),
        ),
        bytesVerified: Boolean(d.bytes_verified),
      });
      es.close();
      if (esRef.current === es) esRef.current = null;
      // Refresh any view sitting on stale post-cleanup data. Invalidate rather
      // than refetch: consumers that aren't mounted just get marked stale.
      queryClient.invalidateQueries({ queryKey: ["scan"] });
      queryClient.invalidateQueries({ queryKey: ["history"] });
      queryClient.invalidateQueries({ queryKey: ["disk-usage"] });
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
    // One start at a time: the server re-scans the selection before it answers,
    // and a second start would only be refused once that re-scan was done.
    if (startingRef.current) return;
    startingRef.current = true;
    dispatch({ type: "START_REQUESTED" });
    const ids = Array.from(enabledRef.current);
    // Dangerous entries start disabled. If the user explicitly enables one in
    // the review step, carry that consent to the backend instead of silently
    // asking the cleanup core to skip the selected entry.
    const allowDangerous = entriesRef.current.some(
      (entry) => entry.risk === "dangerous" && enabledRef.current.has(entry.id),
    );
    try {
      const res = await apiFetch<{ job_id: string }>("/clean/jobs", {
        method: "POST",
        body: JSON.stringify({
          entry_ids: ids,
          allow_dangerous: allowDangerous,
        }),
      });
      if (!mountedRef.current) {
        // The wizard closed during the re-scan. Nobody would answer this job's
        // prompts, and it would hold the only job slot until the app restarted.
        await apiFetch(`/clean/jobs/${res.job_id}/cancel`, { method: "POST" });
        return;
      }
      dispatch({ type: "START", jobId: res.job_id });
      openStream(res.job_id);
    } catch (err) {
      dispatch({ type: "START_FAILED", message: startErrorMessage(err) });
    } finally {
      startingRef.current = false;
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
