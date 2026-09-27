import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { CacheTableRow } from "@/components/CacheTable";
import {
  CleanupWizardContext,
  type WizardState,
} from "@/components/CleanupWizard/CleanupWizardState";
import { SummaryStep } from "@/components/CleanupWizard/SummaryStep";
import { initial } from "@/hooks/useCleanupWizard";

const ROW: CacheTableRow = {
  id: "node-project-dependencies:/code/app/node_modules",
  provider: "node-project-dependencies",
  label: "app/node_modules",
  path: "/code/app/node_modules",
  size_bytes: 18_100_000_000,
  footprint_bytes: 18_100_000_000,
  reclaimable_bytes: 18_100_000_000,
  shared_bytes: 0,
  risk: "reclaimable",
  mtime: null,
  recipeHint: "rm -rf /code/app/node_modules",
  owner: null,
  group: null,
  perms: null,
};

const DONE: Partial<WizardState> = {
  step: "summary",
  results: [{ entry_id: ROW.id, status: "ok", freed_bytes: 18_100_000_000 }],
  estimatedReclaimedBytes: 18_100_000_000,
};

function renderSummary(patch: Partial<WizardState>) {
  const api = {
    state: { ...initial([ROW]), ...DONE, ...patch },
    startJob: vi.fn(),
    answerPrompt: vi.fn(),
    confirm: vi.fn(),
    cancel: vi.fn(),
    toggleEnabled: vi.fn(),
    close: vi.fn(),
  };
  render(
    <MemoryRouter>
      <CleanupWizardContext.Provider value={api}>
        <SummaryStep />
      </CleanupWizardContext.Provider>
    </MemoryRouter>,
  );
  return api;
}

describe("SummaryStep", () => {
  // The summary used to show only the estimate. On a disk with local Time Machine
  // snapshots, 18 GB of deletions released nothing, and nothing said so.
  it("shows how much free space actually changed", () => {
    renderSummary({
      freeBeforeBytes: 35_800_000_000,
      freeAfterBytes: 35_700_000_000,
      freeSpaceLagged: true,
    });
    const line = screen.getByText(/free space/i);
    expect(line).toHaveTextContent("33.3G");
    expect(line).toHaveTextContent("33.2G");
    expect(line).toHaveTextContent("-95.4M");
  });

  it("warns that snapshots may hold the space, and links to them", () => {
    renderSummary({
      freeBeforeBytes: 35_800_000_000,
      freeAfterBytes: 35_700_000_000,
      freeSpaceLagged: true,
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/local snapshots/i);
    const link = screen.getByRole("link", { name: /time machine/i });
    expect(link).toHaveAttribute("href", "/disk?provider=time-machine-local-snapshots");
  });

  it("closes the wizard when the snapshot link is followed", () => {
    const api = renderSummary({
      freeBeforeBytes: 35_800_000_000,
      freeAfterBytes: 35_700_000_000,
      freeSpaceLagged: true,
    });
    screen.getByRole("link", { name: /time machine/i }).click();
    expect(api.close).toHaveBeenCalled();
  });

  it("does not warn when the disk released the space", () => {
    renderSummary({
      freeBeforeBytes: 35_800_000_000,
      freeAfterBytes: 53_900_000_000,
      freeSpaceLagged: false,
    });
    expect(screen.getByText(/free space/i)).toHaveTextContent("+16.9G");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says nothing about free space when the server could not measure it", () => {
    renderSummary({ freeBeforeBytes: null, freeAfterBytes: null, freeSpaceLagged: false });
    expect(screen.queryByText(/free space/i)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
