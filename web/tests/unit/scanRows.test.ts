import { describe, expect, it } from "vitest";
import type { CacheTableRow } from "@/components/CacheTable";
import { filterByAge, filterByRisk, formatCoverage, partitionByMinSize } from "@/lib/scanRows";

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

describe("filterByAge", () => {
  const DAY = 86_400;
  const now = 1_800_000_000;
  const aged = (id: string, days: number | null) => ({
    ...row(id, 1),
    mtime: days === null ? null : now - days * DAY,
  });
  const rows = [aged("fresh", 3), aged("stale", 120), aged("ancient", 400), aged("unknown", null)];

  it("returns the same array when no minimum age is set", () => {
    expect(filterByAge(rows, 0, now)).toBe(rows);
  });

  it("keeps rows untouched for at least the minimum, oldest included", () => {
    expect(filterByAge(rows, 90, now).map((r) => r.id)).toEqual(["stale", "ancient"]);
    expect(filterByAge(rows, 365, now).map((r) => r.id)).toEqual(["ancient"]);
  });

  it("leaves rows of unknown age out, as the CLI's --older-than does", () => {
    expect(filterByAge(rows, 1, now).map((r) => r.id)).not.toContain("unknown");
  });

  it("treats exactly the minimum as old enough", () => {
    expect(filterByAge([aged("edge", 30)], 30, now).map((r) => r.id)).toEqual(["edge"]);
  });
});

describe("formatCoverage", () => {
  it("states what the scan accounts for against the volume's used space", () => {
    expect(
      formatCoverage({ usedBytes: 400 * 2 ** 30, classifiedBytes: 128 * 2 ** 30, ratio: 0.32 }),
    ).toBe("accounts for 128.0G of 400.0G used · 32%");
  });

  it("is empty without a ratio", () => {
    expect(formatCoverage(null)).toBeNull();
    expect(formatCoverage({ usedBytes: 0, classifiedBytes: 0, ratio: null })).toBeNull();
  });
});
