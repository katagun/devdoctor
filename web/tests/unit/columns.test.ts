import { describe, expect, it } from "vitest";
import { COLUMNS, type ColumnId } from "@/components/CacheTable/columns";

describe("COLUMNS registry", () => {
  it("contains every declared ColumnId exactly once", () => {
    const ids: ColumnId[] = ["provider", "size", "risk", "stale", "owner", "perms"];
    const declared = COLUMNS.map((c) => c.id).sort();
    expect(declared).toEqual([...ids].sort());
  });

  it("provider is the only non-hideable column", () => {
    const nonHideable = COLUMNS.filter((c) => !c.hideable).map((c) => c.id);
    expect(nonHideable).toEqual(["provider"]);
  });

  it("every column defaults to visible", () => {
    for (const col of COLUMNS) {
      expect(col.defaultVisible).toBe(true);
    }
  });

  it("only provider/size/risk/stale are sortable (new columns are not)", () => {
    const sortable = COLUMNS.filter((c) => c.sortable).map((c) => c.id).sort();
    expect(sortable).toEqual(["provider", "risk", "size", "stale"]);
  });
});
