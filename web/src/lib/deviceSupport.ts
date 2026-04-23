export type SupportStatus =
  | { kind: "supported" }
  | { kind: "blocked"; detected: string };

export interface DeviceSignals {
  userAgent: string;
  maxTouchPoints: number;
}

export function evaluateDeviceSupport(sig: DeviceSignals): SupportStatus {
  const ua = sig.userAgent;
  // Order matters: Android UAs contain "Linux", iPadOS may report as Macintosh.
  if (/Android/i.test(ua)) return { kind: "blocked", detected: "Android" };
  if (/iPhone|iPod/.test(ua)) return { kind: "blocked", detected: "iOS" };
  if (/iPad/.test(ua) || (/Macintosh/.test(ua) && sig.maxTouchPoints > 1)) {
    return { kind: "blocked", detected: "iPadOS" };
  }
  if (/Windows/i.test(ua)) return { kind: "blocked", detected: "Windows" };
  if (/Mac/.test(ua)) return { kind: "supported" };
  if (/CrOS|Linux/i.test(ua)) return { kind: "supported" };
  return { kind: "blocked", detected: "unknown" };
}

export function useDeviceSupport(): SupportStatus {
  return evaluateDeviceSupport({
    userAgent: typeof navigator === "undefined" ? "" : navigator.userAgent,
    maxTouchPoints: typeof navigator === "undefined" ? 0 : navigator.maxTouchPoints,
  });
}
