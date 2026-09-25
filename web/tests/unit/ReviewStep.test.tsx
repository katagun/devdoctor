import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import type { CacheTableRow } from "@/components/CacheTable";
import {
  CleanupWizardContext,
  type WizardState,
} from "@/components/CleanupWizard/CleanupWizardState";
import { ReviewStep } from "@/components/CleanupWizard/ReviewStep";
import { initial } from "@/hooks/useCleanupWizard";

const ROW: CacheTableRow = {
  id: "node-project-dependencies:/code/app/node_modules",
  provider: "node-project-dependencies",
  label: "app/node_modules",
  path: "/code/app/node_modules",
  size_bytes: 400_000_000,
  footprint_bytes: 400_000_000,
  reclaimable_bytes: 400_000_000,
  shared_bytes: 0,
  risk: "reclaimable",
  mtime: null,
  recipeHint: "rm -rf /code/app/node_modules",
  owner: null,
  group: null,
  perms: null,
};

function renderReview(patch: Partial<WizardState> = {}) {
  const api = {
    state: { ...initial([ROW]), ...patch },
    startJob: vi.fn(),
    answerPrompt: vi.fn(),
    confirm: vi.fn(),
    cancel: vi.fn(),
    toggleEnabled: vi.fn(),
    close: vi.fn(),
  };
  render(
    <CleanupWizardContext.Provider value={api}>
      <ReviewStep />
    </CleanupWizardContext.Provider>,
  );
  return api;
}

describe("ReviewStep", () => {
  it("offers execute while no start is under way", () => {
    renderReview();
    expect(screen.getByRole("button", { name: "execute" })).toBeEnabled();
  });

  // The server re-scans the selection before the job exists, for minutes on a large
  // disk. The step used to look exactly as before the click, so people clicked again.
  it("shows the check under way and takes no input until it ends", () => {
    renderReview({ starting: true });
    expect(screen.getByRole("button", { name: /checking/ })).toBeDisabled();
    // The selection is already on its way: toggling now would change the review
    // without changing the job.
    for (const button of screen.getAllByRole("button")) {
      expect(button).toBeDisabled();
    }
  });

  it("says why the last start failed", () => {
    renderReview({ startError: "Another cleanup is still running." });
    expect(screen.getByRole("alert")).toHaveTextContent("Another cleanup is still running.");
    expect(screen.getByRole("button", { name: "execute" })).toBeEnabled();
  });
});
