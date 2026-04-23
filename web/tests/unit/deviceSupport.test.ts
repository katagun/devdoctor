import { afterEach, describe, expect, it, vi } from "vitest";
import {
  evaluateDeviceSupport,
  useDeviceSupport,
} from "@/lib/deviceSupport";

// Representative UA strings. Keep this matrix visible so adding/editing
// rules stays easy to reason about.
const CASES: Array<[string, string, number, "supported" | string]> = [
  // [description, userAgent, maxTouchPoints, expected]
  [
    "macOS Chrome",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    0,
    "supported",
  ],
  [
    "macOS Safari",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    0,
    "supported",
  ],
  [
    "Ubuntu Firefox",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
    0,
    "supported",
  ],
  [
    "Fedora Chromium",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    0,
    "supported",
  ],
  [
    "Chrome OS",
    "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    0,
    "supported",
  ],
  [
    "Windows Chrome",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    0,
    "Windows",
  ],
  [
    "Windows Edge",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    0,
    "Windows",
  ],
  [
    "iPhone Safari",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    5,
    "iOS",
  ],
  [
    "iPad Safari (classic UA with iPad token)",
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    5,
    "iPadOS",
  ],
  [
    "iPad Safari (newer, reports Macintosh with touch)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    5,
    "iPadOS",
  ],
  [
    "Android Chrome",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    5,
    "Android",
  ],
  [
    "Unknown / exotic UA",
    "Mozilla/5.0 (compatible; SomeBotEmulator/1.0)",
    0,
    "unknown",
  ],
];

describe("evaluateDeviceSupport", () => {
  it.each(CASES)("%s → %s", (_desc, ua, mtp, expected) => {
    const result = evaluateDeviceSupport({ userAgent: ua, maxTouchPoints: mtp });
    if (expected === "supported") {
      expect(result).toEqual({ kind: "supported" });
    } else {
      expect(result).toEqual({ kind: "blocked", detected: expected });
    }
  });

  it("Mac desktop with maxTouchPoints=0 is supported even though the UA says Macintosh", () => {
    const result = evaluateDeviceSupport({
      userAgent:
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
      maxTouchPoints: 0,
    });
    expect(result).toEqual({ kind: "supported" });
  });

  it("iPadOS reporting as Macintosh with maxTouchPoints>1 is blocked", () => {
    const result = evaluateDeviceSupport({
      userAgent:
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
      maxTouchPoints: 5,
    });
    expect(result).toEqual({ kind: "blocked", detected: "iPadOS" });
  });

  it("falls through to 'unknown' when no rule matches", () => {
    const result = evaluateDeviceSupport({
      userAgent: "totally-made-up-no-os-here",
      maxTouchPoints: 0,
    });
    expect(result).toEqual({ kind: "blocked", detected: "unknown" });
  });

  it("Android UA containing 'Linux' is blocked as Android, not allowed as Linux", () => {
    const result = evaluateDeviceSupport({
      userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 8) Mobile Safari/537.36",
      maxTouchPoints: 5,
    });
    expect(result).toEqual({ kind: "blocked", detected: "Android" });
  });
});

describe("useDeviceSupport", () => {
  const originalUA = navigator.userAgent;
  const originalMTP = navigator.maxTouchPoints;

  afterEach(() => {
    Object.defineProperty(navigator, "userAgent", {
      value: originalUA,
      configurable: true,
    });
    Object.defineProperty(navigator, "maxTouchPoints", {
      value: originalMTP,
      configurable: true,
    });
    vi.restoreAllMocks();
  });

  it("reads live navigator signals", () => {
    Object.defineProperty(navigator, "userAgent", {
      value:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
      configurable: true,
    });
    Object.defineProperty(navigator, "maxTouchPoints", {
      value: 0,
      configurable: true,
    });
    expect(useDeviceSupport()).toEqual({ kind: "blocked", detected: "Windows" });
  });
});
