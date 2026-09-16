import { describe, expect, it } from "vitest";
import type { CacheTableRow } from "@/components/CacheTable";
import { filterByRisk, partitionByMinSize } from "@/lib/scanRows";

function row(
  id: string,
  size: number,
  footprint: number | null = size,
  risk: CacheTableRow["risk"] = "safe",
): CacheTableRow {
  return {
    id,
    provider: "p",
    label: id,
    path: `/x/${id}`,
    size_bytes: size,
    footprint_bytes: footprint,
    reclaimable_bytes: footprint,
    shared_bytes: 0,
    risk,
    mtime: null,
    recipeHint: "",
    owner: null,
    group: null,
    perms: null,
  };
}

describe("partitionByMinSize", () => {
  it("shows everything when there is no threshold", () => {
    const rows = [row("a", 10), row("b", 0, null)];
    const result = partitionByMinSize(rows, 0);
    expect(result.visibleRows.map((r) => r.id)).toEqual(["a", "b"]);
    expect(result.hiddenRows).toEqual([]);
    expect(result.visibleBytes).toBe(10);
  });

  it("hides measured rows below the threshold and totals them", () => {
    const result = partitionByMinSize([row("big", 500), row("small", 20)], 100);
    expect(result.visibleRows.map((r) => r.id)).toEqual(["big"]);
    expect(result.hiddenRows.map((r) => r.id)).toEqual(["small"]);
    expect(result.hiddenBytes).toBe(20);
    expect(result.visibleBytes).toBe(500);
  });

  it("never hides an unmeasured row as small", () => {
    const result = partitionByMinSize([row("worktree", 0, null), row("small", 20)], 100);
    expect(result.visibleRows.map((r) => r.id)).toEqual(["worktree"]);
    expect(result.hiddenRows.map((r) => r.id)).toEqual(["small"]);
    expect(result.visibleBytes).toBe(0);
  });
});

describe("filterByRisk", () => {
  const rows = [row("s", 1, 1, "safe"), row("r", 2, 2, "reclaimable"), row("d", 3, 3, "dangerous")];

  it("returns every row when no risks are selected", () => {
    expect(filterByRisk(rows, [])).toBe(rows);
  });

  it("keeps only rows whose risk is selected", () => {
    expect(filterByRisk(rows, ["dangerous"]).map((r) => r.id)).toEqual(["d"]);
    expect(filterByRisk(rows, ["safe", "reclaimable"]).map((r) => r.id)).toEqual(["s", "r"]);
  });
});
