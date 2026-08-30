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
      JSON.stringify({
        scanTableHiddenColumns: ["stale"],
        scanTableColumnsCustomized: true,
      }),
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

  it("renders owner and perms cells when fields are populated and those columns are enabled", () => {
    // Owner and perms are hidden by default — opt them back in for this test.
    localStorage.setItem(
      "diskdoctor.settings.v1",
      JSON.stringify({
        scanTableHiddenColumns: [],
        scanTableColumnsCustomized: true,
      }),
    );
    __testReloadSettings();
    render(<CacheTable rows={rows} selected={new Set()} onToggle={() => {}} />);
    expect(screen.getByText("shamil")).toBeInTheDocument();
    expect(screen.getByText("drwxr-xr-x")).toBeInTheDocument();
  });

  it("renders — for owner/perms when those fields are null and the columns are enabled", () => {
    localStorage.setItem(
      "diskdoctor.settings.v1",
      JSON.stringify({
        scanTableHiddenColumns: [],
        scanTableColumnsCustomized: true,
      }),
    );
    __testReloadSettings();
    const nullRow = { ...rows[1], id: "null-row", owner: null, group: null, perms: null };
    const { container } = render(
      <CacheTable rows={[nullRow]} selected={new Set()} onToggle={() => {}} />,
    );
    const dashCount = Array.from(container.querySelectorAll("*")).filter(
      (el) => el.textContent === "—",
    ).length;
    expect(dashCount).toBeGreaterThanOrEqual(2);
  });

  it("hides owner and perms columns by default", () => {
    render(<CacheTable rows={rows} selected={new Set()} onToggle={() => {}} />);
    expect(screen.queryByText("shamil")).not.toBeInTheDocument();
    expect(screen.queryByText("drwxr-xr-x")).not.toBeInTheDocument();
  });

  it("virtualizes a large scan: only a windowed subset of rows is in the DOM", () => {
    const many: CacheTableRow[] = Array.from({ length: 1000 }, (_, i) => ({
      ...rows[1],
      id: `row-${i}`,
      label: `entry-${i}`,
      // Descending sizes so the default size-desc sort keeps row-0 at the top.
      size_bytes: 1_000_000_000 - i,
    }));
    render(<CacheTable rows={many} selected={new Set()} onToggle={() => {}} />);

    // A 1000-row scan must not build 1000 checkboxes/rows — only the visible
    // window (viewport height / row height + overscan) is mounted.
    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes.length).toBeGreaterThan(0);
    expect(checkboxes.length).toBeLessThan(100);
    // The topmost row of the size-desc sort is in the window; a deep row is not.
    expect(screen.getByText("entry-0")).toBeInTheDocument();
    expect(screen.queryByText("entry-900")).not.toBeInTheDocument();
  });

  it("selection and sorting keep working across the virtualized window", () => {
    const spy = vi.fn();
    const many: CacheTableRow[] = Array.from({ length: 1000 }, (_, i) => ({
      ...rows[1],
      id: `row-${i}`,
      provider: `prov-${String(i).padStart(4, "0")}`,
      label: `entry-${i}`,
      size_bytes: 1_000_000_000 - i,
    }));
    render(<CacheTable rows={many} selected={new Set()} onToggle={spy} />);

    // Selection: clicking a rendered checkbox reports the right row id, proving
    // per-row select still maps to the underlying (not just visual) row.
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    expect(spy).toHaveBeenCalledWith("row-0", true);

    // Sorting: provider-asc should surface prov-0000 at the top of the window.
    fireEvent.click(screen.getByRole("button", { name: /provider/i }));
    const providerCells = screen.getAllByText(/^prov-\d{4}$/);
    expect(providerCells[0].textContent).toBe("prov-0000");
  });

  it("renders blank (not —) for owner/perms on logical entries with no path (ollama-style)", () => {
    localStorage.setItem(
      "diskdoctor.settings.v1",
      JSON.stringify({
        scanTableHiddenColumns: [],
        scanTableColumnsCustomized: true,
      }),
    );
    __testReloadSettings();
    const ollamaRow: CacheTableRow = {
      id: "ollama-granite",
      provider: "ollama",
      label: "granite3.1-moe:1b",
      path: "—", // useScan replaces null with "—" for logical entries.
      size_bytes: 1_400_000_000,
      risk: "reclaimable",
      mtime: null,
      recipeHint: "ollama rm granite3.1-moe:1b",
      owner: null,
      group: null,
      perms: null,
    };
    const { container } = render(
      <CacheTable rows={[ollamaRow]} selected={new Set()} onToggle={() => {}} />,
    );
    // No "—" placeholders should appear on a logical row — they made these
    // rows look like broken stat-failed rows. Stale already renders empty
    // when mtime is null.
    const dashCount = Array.from(container.querySelectorAll("*")).filter(
      (el) => el.textContent === "—",
    ).length;
    expect(dashCount).toBe(0);
  });
});
