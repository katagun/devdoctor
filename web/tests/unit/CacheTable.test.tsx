import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { CacheTable, CacheTableRow } from "@/components/CacheTable";

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
  },
];

describe("CacheTable", () => {
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
});
