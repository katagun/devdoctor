import { describe, expect, it } from "vitest";
import {
  buildDiskMosaicItems,
  buildMemoryMosaicItems,
  diskProviderHref,
  diskProviderTotals,
  memoryProviderHref,
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
      expect.objectContaining({
        id: "docker:images",
        label: "docker",
        value: 90,
        tone: "reclaimable",
        href: "/disk?provider=docker",
      }),
      expect.objectContaining({
        id: "ollama:models",
        label: "ollama",
        value: 70,
        tone: "reclaimable",
        href: "/disk?provider=ollama",
      }),
      expect.objectContaining({ id: "disk-other", label: "other 💽 disk entries", value: 80, tone: "other" }),
    ]);
  });

  it("builds memory mosaic items from top consumers", () => {
    const items = buildMemoryMosaicItems(
      [
        memory("firefox", "Firefox", "browser", 120),
        memory("docker", "Docker Desktop", "docker", 80),
        memory("slack", "Slack", "electron", 30),
      ],
      2,
    );

    expect(items).toEqual([
      expect.objectContaining({
        id: "firefox",
        label: "Firefox",
        value: 120,
        tone: "browser",
        href: "/memory?provider=browsers",
      }),
      expect.objectContaining({ id: "memory-other", label: "other 🧠 memory consumers", value: 110, tone: "other" }),
    ]);
  });

  it("compacts bundle identifiers for memory mosaic labels", () => {
    const items = buildMemoryMosaicItems(
      [memory("vm", "com.apple.Virtualization.VirtualMachine", "other", 120)],
      2,
    );

    expect(items[0]).toMatchObject({
      id: "vm",
      label: "Virtual Machine",
      detail: "com.apple.Virtualization.VirtualMachine · other",
      tone: "process",
    });
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

  it("builds encoded drill-down hrefs", () => {
    expect(diskProviderHref("docker vm")).toBe("/disk?provider=docker%20vm");
    expect(memoryProviderHref("browser")).toBe("/memory?provider=browsers");
    expect(memoryProviderHref("other")).toBe("/memory?provider=other-processes");
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
  kind: "browser" | "electron" | "docker" | "llm" | "app" | "process" | "other",
  rssBytes: number,
) {
  return {
    id,
    name,
    kind,
    rss_bytes: rssBytes,
  };
}
