import { createContext, useContext } from "react";
import type { CacheTableRow } from "@/components/CacheTable";

export type Step = "review" | "execute" | "summary";

export interface ExecuteProgressEntry {
  entry_id: string;
  status: "pending" | "running" | "ok" | "error" | "skipped";
  freed_bytes: number;
  message?: string;
  consoleLines: string[];
}

export interface CleanupResult {
  entry_id: string;
  status: ExecuteProgressEntry["status"];
  freed_bytes: number;
  message?: string;
}

export interface WizardState {
  step: Step;
  entries: CacheTableRow[];
  enabled: Set<string>; // the user can toggle each off in Review
  jobId: string | null;
  awaitingConfirm: { summary: string } | null;
  pendingPrompts: { entry_id: string; recipe: string[] }[];
  progress: Record<string, ExecuteProgressEntry>;
  results: CleanupResult[] | null;
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
