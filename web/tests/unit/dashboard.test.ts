import { describe, expect, it } from "vitest";
import {
  buildDiskMosaicItems,
  buildMemoryMosaicItems,
  diskProviderTotals,
  topMemoryConsumers,
} from "@/lib/dashboard";

describe("dashboard data shaping", () => {
  it("builds a disk mosaic from reclaimable and safe entries with an aggregate tail", () => {
    const items = buildDiskMosaicItems(
      [
        row("docker", "images", 90, "reclaimable"),
        row("ollama", "models", 70, "reclaimable"),
        row("xcode", "archives", 50, "safe"),
        row("danger", "keychain", 40, "dangerous"),
        row("browser", "cache", 30, "safe"),
      ],
      3,
    );

    expect(items).toEqual([
      expect.objectContaining({ id: "docker:images", label: "images", value: 90, tone: "reclaimable" }),
      expect.objectContaining({ id: "ollama:models", label: "models", value: 70, tone: "reclaimable" }),
      expect.objectContaining({ id: "disk-other", label: "other disk entries", value: 80, tone: "other" }),
    ]);
  });

  it("builds memory mosaic items from selected provider totals", () => {
    const items = buildMemoryMosaicItems(
      [
        memory("browsers", "Browsers", "browser", 120, true),
        memory("docker", "Docker", "docker", 80, true),
        memory("apps", "Apps", "app", 30, false),
      ],
      4,
    );

    expect(items.map((item) => item.id)).toEqual(["browsers", "docker"]);
    expect(items[0]).toMatchObject({ label: "Browsers", value: 120, tone: "browser" });
  });

  it("summarizes disk totals by provider", () => {
    expect(
      diskProviderTotals([
        row("docker", "a", 90, "reclaimable"),
        row("docker", "b", 10, "safe"),
        row("ollama", "c", 70, "dangerous"),
      ]),
    ).toEqual([
      { provider: "docker", bytes: 100, count: 2 },
      { provider: "ollama", bytes: 70, count: 1 },
    ]);
  });

  it("returns top memory consumers in descending RSS order", () => {
    expect(
      topMemoryConsumers(
        [
          { id: "a", name: "Slack", kind: "electron", rss_bytes: 30 },
          { id: "b", name: "Firefox", kind: "browser", rss_bytes: 90 },
          { id: "c", name: "Docker", kind: "docker", rss_bytes: 60 },
        ],
        2,
      ),
    ).toEqual([
      { id: "b", name: "Firefox", kind: "browser", rss_bytes: 90 },
      { id: "c", name: "Docker", kind: "docker", rss_bytes: 60 },
    ]);
  });
});

function row(
  provider: string,
  label: string,
  sizeBytes: number,
  risk: "safe" | "reclaimable" | "dangerous",
) {
  return {
    id: `${provider}:${label}`,
    provider,
    label,
    size_bytes: sizeBytes,
    risk,
  };
}

function memory(
  id: string,
  name: string,
  kind: "browser" | "electron" | "docker" | "llm" | "app" | "process",
  rssBytes: number,
  selected: boolean,
) {
  return {
    id,
    name,
    kind,
    selected,
    rss_bytes: rssBytes,
    consumer_count: 1,
  };
}
