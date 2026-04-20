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
});
