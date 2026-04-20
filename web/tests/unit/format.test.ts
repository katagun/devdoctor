import { describe, it, expect } from "vitest";
import { humanBytes, staleness, riskLabel, parseRecipeHint } from "@/lib/format";

describe("humanBytes", () => {
  it("formats bytes", () => expect(humanBytes(0)).toBe("0B"));
  it("formats kilobytes", () => expect(humanBytes(1024)).toBe("1.0K"));
  it("formats gigabytes", () => expect(humanBytes(1_500_000_000)).toBe("1.4G"));
  it("formats negative", () => expect(humanBytes(-1024)).toBe("-1.0K"));
});

describe("staleness", () => {
  it("null → em dash", () => expect(staleness(null)).toBe("—"));
  it("very recent → today", () => {
    expect(staleness(Date.now() / 1000 - 3600)).toBe("today");
  });
  it("weeks ago → Nd", () => {
    const ts = Date.now() / 1000 - 5 * 86400;
    expect(staleness(ts)).toBe("5d");
  });
});

describe("riskLabel", () => {
  it("maps risks", () => {
    expect(riskLabel("safe")).toBe("safe");
    expect(riskLabel("reclaimable")).toBe("reclaim");
    expect(riskLabel("dangerous")).toBe("DANGER");
  });
});

describe("parseRecipeHint", () => {
  it("treats raw commands as commands", () => {
    const h = parseRecipeHint("rm -rf /tmp/foo");
    expect(h.kind).toBe("command");
    expect(h.text).toBe("rm -rf /tmp/foo");
  });

  it("extracts echo'd advice into a single sentence list", () => {
    const h = parseRecipeHint("echo 'Clean the cache.'");
    expect(h.kind).toBe("advice");
    expect(h.text).toBe("Clean the cache.");
    expect(h.sentences).toEqual(["Clean the cache."]);
  });

  it("splits multi-sentence advice at sentence boundaries", () => {
    const h = parseRecipeHint(
      "echo 'First sentence. Second one starts with capital. Third one too.'",
    );
    expect(h.kind).toBe("advice");
    expect(h.sentences).toEqual([
      "First sentence.",
      "Second one starts with capital.",
      "Third one too.",
    ]);
  });

  it("does not split on abbreviations like 'e.g.'", () => {
    const h = parseRecipeHint("echo 'Use e.g. docker prune to clean. Then retry.'");
    expect(h.sentences).toEqual(["Use e.g. docker prune to clean.", "Then retry."]);
  });
});
