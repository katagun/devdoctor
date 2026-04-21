import { useCallback, useEffect, useState } from "react";

const KEY = "diskdoctor.settings.v1";

// Cadence in milliseconds for TanStack Query's staleTime. `Infinity` disables
// automatic refetching — only manual "Rescan now" forces a refetch.
export const CADENCE_PRESETS = [
  { id: "live", label: "Live", staleMs: 0, caption: "Rescan every time you open the Scan page" },
  { id: "hourly", label: "Hourly", staleMs: 60 * 60 * 1000, caption: "Reuse last scan for up to 1 hour" },
  { id: "six_hours", label: "Every 6 hours", staleMs: 6 * 60 * 60 * 1000, caption: "Reuse last scan for up to 6 hours" },
  { id: "daily", label: "Daily", staleMs: 24 * 60 * 60 * 1000, caption: "Reuse last scan for up to 24 hours" },
  { id: "weekly", label: "Weekly", staleMs: 7 * 24 * 60 * 60 * 1000, caption: "Reuse last scan for up to 7 days" },
  { id: "manual", label: "Manual only", staleMs: Number.POSITIVE_INFINITY, caption: "Never auto-refetch — use Rescan now" },
] as const;

export type CadenceId = (typeof CADENCE_PRESETS)[number]["id"];

export const SIZE_PRESETS = [
  { label: "Off", bytes: 0 },
  { label: "10 MB", bytes: 10_000_000 },
  { label: "100 MB", bytes: 100_000_000 },
  { label: "500 MB", bytes: 500_000_000 },
  { label: "1 GB", bytes: 1_000_000_000 },
] as const;

export type Density = "sparse" | "dense";
export type Theme = "light" | "dark" | "system";

export interface Settings {
  minSizeBytes: number;
  cadence: CadenceId;
  density: Density;
  theme: Theme;
}

const DEFAULTS: Settings = {
  minSizeBytes: 0,
  cadence: "live",
  density: "sparse",
  theme: "system",
};

function read(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return DEFAULTS;
    const minSizeBytes =
      typeof parsed.minSizeBytes === "number" && parsed.minSizeBytes >= 0
        ? parsed.minSizeBytes
        : DEFAULTS.minSizeBytes;
    const cadence: CadenceId = CADENCE_PRESETS.some((c) => c.id === parsed.cadence)
      ? parsed.cadence
      : DEFAULTS.cadence;
    const density: Density = parsed.density === "dense" ? "dense" : DEFAULTS.density;
    const theme: Theme =
      parsed.theme === "light" || parsed.theme === "dark" || parsed.theme === "system"
        ? parsed.theme
        : DEFAULTS.theme;
    return { minSizeBytes, cadence, density, theme };
  } catch {
    return DEFAULTS;
  }
}

function write(s: Settings): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* ignore quota / private mode */
  }
}

export function useSettings() {
  const [settings, setSettings] = useState<Settings>(read);

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY) setSettings(read());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const update = useCallback((patch: Partial<Settings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch };
      write(next);
      return next;
    });
  }, []);

  const reset = useCallback(() => {
    setSettings(DEFAULTS);
    write(DEFAULTS);
  }, []);

  return { settings, update, reset };
}

export function cadenceMs(id: CadenceId): number {
  return CADENCE_PRESETS.find((c) => c.id === id)?.staleMs ?? 0;
}
