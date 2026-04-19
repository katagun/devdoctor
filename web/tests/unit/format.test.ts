import { describe, it, expect } from "vitest";
import { humanBytes, staleness, riskLabel } from "@/lib/format";

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
