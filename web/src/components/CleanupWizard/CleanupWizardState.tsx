import { createContext, useContext } from "react";
import type { CacheTableRow } from "@/components/CacheTable";

export type Step = "review" | "execute" | "summary";

export interface ExecuteProgressEntry {
  entry_id: string;
  status: "pending" | "running" | "ok" | "error" | "skipped";
  freed_bytes: number;
  bytes_verified?: boolean;
  message?: string;
  consoleLines: string[];
}

export interface CleanupResult {
  entry_id: string;
  status: ExecuteProgressEntry["status"];
  freed_bytes: number;
  bytes_verified?: boolean;
  message?: string;
}

export interface WizardState {
  step: Step;
  entries: CacheTableRow[];
  enabled: Set<string>; // the user can toggle each off in Review
  // The start request is in flight: the server re-scans the selection before the
  // job exists, which takes minutes for node_modules on a large disk.
  starting: boolean;
  // Why the last start failed, for the review step to show.
  startError: string | null;
  jobId: string | null;
  awaitingConfirm: { summary: string } | null;
  pendingPrompts: { entry_id: string; recipe: string[] }[];
  progress: Record<string, ExecuteProgressEntry>;
  results: CleanupResult[] | null;
  estimatedReclaimedBytes: number | null;
  bytesVerified: boolean;
  // What the disk actually released, read before and after the job; null when
  // the server could not read the volume.
  freeBeforeBytes: number | null;
  freeAfterBytes: number | null;
  // The disk released under half of what was deleted: a local snapshot is
  // probably holding the blocks. The rule lives on the server, shared with the CLI.
  freeSpaceLagged: boolean;
  error: string | null;
}

export interface CleanupWizardApi {
  state: WizardState;
  startJob(): void;
  answerPrompt(entryId: string, choice: "y" | "n" | "a" | "s" | "q"): void;
  confirm(): void;
  cancel(): void;
  toggleEnabled(id: string, next: boolean): void;
  close(): void;
}

export const CleanupWizardContext = createContext<CleanupWizardApi | null>(null);

export function useWizardContext(): CleanupWizardApi {
  const ctx = useContext(CleanupWizardContext);
  if (!ctx) throw new Error("CleanupWizardContext not provided");
  return ctx;
}
