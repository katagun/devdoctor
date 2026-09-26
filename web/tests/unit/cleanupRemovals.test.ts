import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CacheTableRow } from "@/components/CacheTable";
import { recordRemoval, removalFrom, removalsSince } from "@/lib/cleanupRemovals";

function row(id: string, path: string): CacheTableRow {
  return {
    id,
    provider: "p",
    label: id,
    path,
    size_bytes: 1,
    footprint_bytes: 1,
    reclaimable_bytes: 1,
    shared_bytes: 0,
    risk: "safe",
    mtime: null,
    recipeHint: "",
    owner: null,
    group: null,
    perms: null,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("removalFrom", () => {
  it("keeps only what the cleanup actually removed, with the paths it knows", () => {
    const removal = removalFrom(
      [
        { entry_id: "a", status: "ok", freed_bytes: 1 },
        { entry_id: "b", status: "error", freed_bytes: 0 },
        { entry_id: "c", status: "ok", freed_bytes: 1 },
      ],
      [row("a", "/x/a"), row("b", "/x/b"), row("c", "—")],
      42,
    );
    expect(removal).toEqual({ ids: ["a", "c"], paths: ["/x/a"], at: 42 });
  });

  it("is nothing when nothing was removed", () => {
    expect(removalFrom([{ entry_id: "a", status: "skipped", freed_bytes: 0 }], [], 1)).toBeNull();
  });
});

describe("removals in the query client", () => {
  it("returns the removals newer than a scan's start, or all when the start is unknown", () => {
    const client = new QueryClient();
    recordRemoval(client, { ids: ["old"], paths: [], at: Date.parse("2026-09-25T09:00:00Z") });
    recordRemoval(client, { ids: ["new"], paths: [], at: Date.parse("2026-09-25T11:00:00Z") });
    expect(removalsSince(client, "2026-09-25T10:00:00+00:00").map((r) => r.ids[0])).toEqual(["new"]);
    expect(removalsSince(client, null)).toHaveLength(2);
  });

  it("outlives the query client's garbage collection", () => {
    vi.useFakeTimers();
    const client = new QueryClient();
    recordRemoval(client, { ids: ["a"], paths: [], at: 1 });
    vi.advanceTimersByTime(60 * 60 * 1000);
    expect(removalsSince(client, null)).toHaveLength(1);
  });
});
