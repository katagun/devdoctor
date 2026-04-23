import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { CacheTable, CacheTableRow } from "@/components/CacheTable";
import { __testReloadSettings } from "@/hooks/useSettings";

const rows: CacheTableRow[] = [
  {
    id: "1",
    provider: "docker",
    label: "vm-disk",
    path: "/Library/Containers/com.docker.docker/Data/vms",
    size_bytes: 80_000_000_000,
    risk: "reclaimable",
    mtime: null,
    recipeHint: "echo 'use docker desktop'",
    owner: "shamil",
    group: "staff",
    perms: "drwxr-xr-x",
  },
  {
    id: "2",
    provider: "uv-cache",
    label: "~/.cache/uv",
    path: "/Users/x/.cache/uv",
    size_bytes: 1_500_000_000,
    risk: "safe",
    mtime: null,
    recipeHint: "uv cache clean",
    owner: null,
    group: null,
    perms: null,
  },
];

describe("CacheTable", () => {
  beforeEach(() => {
    localStorage.clear();
    __testReloadSettings();
  });

  it("renders rows and totals", () => {
    render(<CacheTable rows={rows} selected={new Set()} onToggle={() => {}} />);
    expect(screen.getByText(/^docker$/)).toBeInTheDocument();
    expect(screen.getByText(/uv-cache/)).toBeInTheDocument();
  });

  it("calls onToggle when a checkbox is clicked", () => {
    const spy = vi.fn();
    render(<CacheTable rows={rows} selected={new Set()} onToggle={spy} />);
    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[0]);
    expect(spy).toHaveBeenCalledWith("1", true);
  });

  it("empty state renders a hint", () => {
    render(<CacheTable rows={[]} selected={new Set()} onToggle={() => {}} />);
    expect(screen.getByText(/no entries/i)).toBeInTheDocument();
  });

  it("defaults to sorting by size descending", () => {
    render(<CacheTable rows={rows} selected={new Set()} onToggle={() => {}} />);
    const providerCells = screen.getAllByText(/^(docker|uv-cache)$/);
    // 80 GB docker row should come before the 1.5 GB uv-cache row.
    expect(providerCells[0].textContent).toBe("docker");
    expect(providerCells[1].textContent).toBe("uv-cache");
  });

  it("clicking a header reverses sort direction on the second click", () => {
    render(<CacheTable rows={rows} selected={new Set()} onToggle={() => {}} />);
    const sizeHeader = screen.getByRole("button", { name: /size/i });
    // First click on the already-active 'size' header flips asc → now smallest first.
    fireEvent.click(sizeHeader);
    const providerCells = screen.getAllByText(/^(docker|uv-cache)$/);
    expect(providerCells[0].textContent).toBe("uv-cache");
    expect(providerCells[1].textContent).toBe("docker");
  });

  it("sorts alphabetically when the provider header is clicked", () => {
    render(<CacheTable rows={rows} selected={new Set()} onToggle={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /provider/i }));
    const providerCells = screen.getAllByText(/^(docker|uv-cache)$/);
    expect(providerCells[0].textContent).toBe("docker");
    expect(providerCells[1].textContent).toBe("uv-cache");
  });

  it("renders a decorative icon next to each provider slug", () => {
    const { container } = render(
      <CacheTable rows={rows} selected={new Set()} onToggle={() => {}} />,
    );
    const icons = container.querySelectorAll('svg[aria-hidden="true"]');
    // One icon per row (2 rows). The Checkbox doesn't contribute an
    // aria-hidden svg today, but if that ever changes this assertion
    // documents the intent clearly.
    expect(icons.length).toBeGreaterThanOrEqual(rows.length);
  });

  it("hides the stale column when it's in hiddenColumns", () => {
    localStorage.setItem(
      "diskdoctor.settings.v1",
      JSON.stringify({ scanTableHiddenColumns: ["stale"] }),
    );
    __testReloadSettings();
    const { container } = render(
      <CacheTable rows={rows} selected={new Set()} onToggle={() => {}} />,
    );
    // The stale column header has uppercase text "STALE" or "stale"; check
    // that the word "stale" (case-insensitive, word-bounded) isn't present
    // in the rendered table.
    const headers = container.querySelectorAll("button[aria-sort]");
    const headerLabels = Array.from(headers).map((h) => h.textContent?.toLowerCase() ?? "");
    expect(headerLabels.some((l) => /stale/.test(l))).toBe(false);
  });

  it("renders owner and perms cells when fields are populated", () => {
    render(<CacheTable rows={rows} selected={new Set()} onToggle={() => {}} />);
    expect(screen.getByText("shamil")).toBeInTheDocument();
    expect(screen.getByText("drwxr-xr-x")).toBeInTheDocument();
  });

  it("renders — for owner/perms when those fields are null", () => {
    // Build a row whose owner/perms/group are null.
    const nullRow = { ...rows[1], id: "null-row", owner: null, group: null, perms: null };
    const { container } = render(
      <CacheTable rows={[nullRow]} selected={new Set()} onToggle={() => {}} />,
    );
    const dashCount = Array.from(container.querySelectorAll("*")).filter(
      (el) => el.textContent === "—",
    ).length;
    // Owner cell and perms cell both render —.
    expect(dashCount).toBeGreaterThanOrEqual(2);
  });
});
