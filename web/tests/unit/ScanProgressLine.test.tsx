import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScanProgressLine } from "@/components/ScanProgressLine";
import type { ScanProgressSnapshot } from "@/lib/scanProgress";

function snap(over: Partial<ScanProgressSnapshot> = {}): ScanProgressSnapshot {
  return {
    scan_id: 1,
    status: "running",
    started_at: null,
    total: 22,
    done: 12,
    running: ["xcode-development-data", "docker"],
    entries: 340,
    bytes: 45_200_000_000,
    providers: [],
    ...over,
  };
}

describe("ScanProgressLine", () => {
  it("shows only the countdown before the first snapshot", () => {
    const { container } = render(<ScanProgressLine progress={null} remainingMs={80_000} />);
    expect(container.textContent).toBe(" · ~1m 20s left, from past scans");
  });

  it("renders the progress parts, then the countdown", () => {
    const { container } = render(<ScanProgressLine progress={snap()} remainingMs={80_000} />);
    expect(container.textContent).toBe(
      " · 12/22 providers · 42.1G found · running: xcode-development-data, docker · ~1m 20s left, from past scans",
    );
  });

  it("says finishing once every provider is done", () => {
    render(<ScanProgressLine progress={snap({ status: "done", done: 22, running: [] })} remainingMs={0} />);
    expect(screen.getByText(/22\/22 providers · 42.1G found · finishing…/)).toBeInTheDocument();
  });

  it("renders a labelled bar when asked", () => {
    render(<ScanProgressLine progress={snap()} remainingMs={null} bar />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "12");
    expect(bar).toHaveAttribute("aria-valuemax", "22");
  });

  it("renders no bar without a snapshot", () => {
    render(<ScanProgressLine progress={null} remainingMs={null} bar />);
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("renders no bar for a scan with no providers", () => {
    render(<ScanProgressLine progress={snap({ total: 0, done: 0, running: [] })} remainingMs={null} bar />);
    expect(screen.queryByRole("progressbar")).toBeNull();
  });
});
