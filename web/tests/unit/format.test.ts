import { describe, it, expect } from "vitest";
import {
  byteMagnitudeTier,
  humanBytes,
  staleness,
  riskLabel,
  parseRecipeHint,
  timeAgo,
  formatAbsTime,
  formatMs,
} from "@/lib/format";

describe("humanBytes", () => {
  it("formats bytes", () => expect(humanBytes(0)).toBe("0B"));
  it("formats kilobytes", () => expect(humanBytes(1024)).toBe("1.0K"));
  it("formats gigabytes", () => expect(humanBytes(1_500_000_000)).toBe("1.4G"));
  it("formats negative", () => expect(humanBytes(-1024)).toBe("-1.0K"));
});

describe("byteMagnitudeTier", () => {
  it("classifies sub-MiB churn as trivial", () => {
    expect(byteMagnitudeTier(0)).toBe("trivial");
    expect(byteMagnitudeTier(14_700)).toBe("trivial");
    expect(byteMagnitudeTier(900_000)).toBe("trivial");
  });
  it("classifies 1 MiB through < 1 GiB as notable", () => {
    expect(byteMagnitudeTier(1024 * 1024)).toBe("notable");
    expect(byteMagnitudeTier(165_000_000)).toBe("notable");
    expect(byteMagnitudeTier(1024 * 1024 * 1024 - 1)).toBe("notable");
  });
  it("classifies ≥ 1 GiB as significant", () => {
    expect(byteMagnitudeTier(1024 * 1024 * 1024)).toBe("significant");
    expect(byteMagnitudeTier(17_600_000_000)).toBe("significant");
  });
  it("treats negative deltas by magnitude", () => {
    expect(byteMagnitudeTier(-14_700)).toBe("trivial");
    expect(byteMagnitudeTier(-2_000_000_000)).toBe("significant");
  });
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

describe("timeAgo", () => {
  const now = new Date("2026-04-20T15:00:00Z");
  it("formats seconds", () => {
    expect(timeAgo("2026-04-20T14:59:50Z", now)).toBe("10s ago");
  });
  it("treats near-zero as 'just now'", () => {
    expect(timeAgo("2026-04-20T14:59:58Z", now)).toBe("just now");
  });
  it("formats minutes", () => {
    expect(timeAgo("2026-04-20T14:45:00Z", now)).toBe("15 min ago");
  });
  it("formats hours", () => {
    expect(timeAgo("2026-04-20T13:00:00Z", now)).toBe("2h ago");
  });
  it("says yesterday", () => {
    expect(timeAgo("2026-04-19T15:00:00Z", now)).toBe("yesterday");
  });
  it("formats older dates", () => {
    // 10 days ago → fall through to locale short date
    const got = timeAgo("2026-04-10T15:00:00Z", now);
    expect(got).toMatch(/Apr/);
  });
});

describe("formatAbsTime", () => {
  it("includes month abbreviation", () => {
    expect(formatAbsTime("2026-04-20T14:48:00Z")).toMatch(/Apr/);
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

describe("formatMs", () => {
  it("sub-second values", () => {
    expect(formatMs(0)).toBe("0ms");
    expect(formatMs(45)).toBe("45ms");
    expect(formatMs(999)).toBe("999ms");
  });

  it("seconds", () => {
    expect(formatMs(1000)).toBe("1.0s");
    expect(formatMs(4821)).toBe("4.8s");
    expect(formatMs(59999)).toBe("60.0s");
  });

  it("minutes plus seconds", () => {
    expect(formatMs(60000)).toBe("1m 0s");
    expect(formatMs(75500)).toBe("1m 15s");
    expect(formatMs(3 * 60 * 1000)).toBe("3m 0s");
  });

  it("null / negative / NaN return a dash", () => {
    expect(formatMs(null)).toBe("—");
    expect(formatMs(-5)).toBe("—");
    expect(formatMs(Number.NaN)).toBe("—");
  });
});
