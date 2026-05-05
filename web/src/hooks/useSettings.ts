import { useCallback, useEffect, useSyncExternalStore } from "react";
import type { ColumnId } from "@/components/CacheTable/columns";
import { COLUMNS, DEFAULT_HIDDEN_COLUMNS } from "@/components/CacheTable/columns";
import type { LandingPage, ToolNavigation } from "@/lib/navigation";

const KEY = "diskdoctor.settings.v1";

// Sidebar width clamps. Min = icons-only state (matches the currently-shipped
// 48px collapsed width). Max = min(20% of viewport, 320px); recomputed from the
// live viewport on every read to keep stored values from exceeding the current
// display.
export const SIDEBAR_MIN_WIDTH = 48;
export const SIDEBAR_MAX_CAP = 320;
export const SIDEBAR_DEFAULT_WIDTH = 180;

export function sidebarMaxWidth(viewportWidth: number): number {
  return Math.min(Math.floor(viewportWidth * 0.2), SIDEBAR_MAX_CAP);
}

export function clampSidebarWidth(px: number, viewportWidth: number): number {
  const max = sidebarMaxWidth(viewportWidth);
  if (!Number.isFinite(px)) return SIDEBAR_DEFAULT_WIDTH;
  if (px < SIDEBAR_MIN_WIDTH) return SIDEBAR_MIN_WIDTH;
  if (px > max) return max;
  return Math.round(px);
}

// Cadence in milliseconds for TanStack Query's staleTime. `Infinity` disables
// automatic refetching — only manual "Rescan now" forces a refetch.
export const CADENCE_PRESETS = [
  { id: "live", label: "Live", staleMs: 0, caption: "Rescan every time you open the Disk page" },
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
export type { LandingPage, ToolNavigation };

export interface Settings {
  minSizeBytes: number;
  cadence: CadenceId;
  density: Density;
  theme: Theme;
  toolNavigation: ToolNavigation;
  landingPage: LandingPage;
  sidebarWidth: number;
  sidebarExpandedWidth: number;
  scanTableHiddenColumns: ColumnId[];
  /** True once the user has manually toggled a column via ColumnsPicker. While
   * false, the visible-column set is derived from viewport width so wide
   * displays auto-show OWNER/PERMS instead of leaking that width as empty
   * space inside the provider column. */
  scanTableColumnsCustomized: boolean;
}

/** Width threshold below which OWNER/PERMS auto-hide. ~1280px = MacBook 13"
 * + the typical workspace sidebar. Above this, the table has room for the
 * forensic columns; below, they'd push the provider path off-screen. */
export const COLUMN_AUTOSHOW_VIEWPORT = 1280;

export function defaultHiddenColumnsForViewport(width: number): ColumnId[] {
  return width < COLUMN_AUTOSHOW_VIEWPORT ? [...DEFAULT_HIDDEN_COLUMNS] : [];
}

const DEFAULTS: Settings = {
  minSizeBytes: 0,
  cadence: "live",
  density: "sparse",
  theme: "system",
  toolNavigation: "sidebar",
  landingPage: "dashboard",
  sidebarWidth: SIDEBAR_DEFAULT_WIDTH,
  sidebarExpandedWidth: SIDEBAR_DEFAULT_WIDTH,
  scanTableHiddenColumns: [...DEFAULT_HIDDEN_COLUMNS],
  scanTableColumnsCustomized: false,
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
    const toolNavigation: ToolNavigation =
      parsed.toolNavigation === "tabs" || parsed.toolNavigation === "sidebar"
        ? parsed.toolNavigation
        : DEFAULTS.toolNavigation;
    const landingPage: LandingPage =
      parsed.landingPage === "dashboard" ||
      parsed.landingPage === "memory" ||
      parsed.landingPage === "disk"
        ? parsed.landingPage
        : DEFAULTS.landingPage;
    // Sidebar width migration:
    //   * Prefer new fields when present and sensible.
    //   * Otherwise fall back to the old sidebarCollapsed boolean.
    //   * Otherwise default.
    const vw = typeof window === "undefined" ? 1024 : window.innerWidth;
    let sidebarWidth: number;
    let sidebarExpandedWidth: number;
    if (
      typeof parsed.sidebarWidth === "number" &&
      parsed.sidebarWidth >= SIDEBAR_MIN_WIDTH
    ) {
      sidebarWidth = clampSidebarWidth(parsed.sidebarWidth, vw);
      const parsedExpanded =
        typeof parsed.sidebarExpandedWidth === "number" &&
        parsed.sidebarExpandedWidth > SIDEBAR_MIN_WIDTH
          ? parsed.sidebarExpandedWidth
          : Math.max(sidebarWidth, SIDEBAR_DEFAULT_WIDTH);
      sidebarExpandedWidth = clampSidebarWidth(parsedExpanded, vw);
    } else if (typeof parsed.sidebarCollapsed === "boolean") {
      sidebarWidth = parsed.sidebarCollapsed
        ? SIDEBAR_MIN_WIDTH
        : SIDEBAR_DEFAULT_WIDTH;
      sidebarExpandedWidth = SIDEBAR_DEFAULT_WIDTH;
    } else {
      sidebarWidth = SIDEBAR_DEFAULT_WIDTH;
      sidebarExpandedWidth = SIDEBAR_DEFAULT_WIDTH;
    }

    const knownColumnIds = new Set<string>(COLUMNS.map((c) => c.id));
    const scanTableHiddenColumns: ColumnId[] =
      Array.isArray(parsed.scanTableHiddenColumns)
        ? parsed.scanTableHiddenColumns.filter(
            (v: unknown): v is ColumnId =>
              typeof v === "string" && knownColumnIds.has(v),
          )
        : DEFAULTS.scanTableHiddenColumns;
    const scanTableColumnsCustomized: boolean =
      typeof parsed.scanTableColumnsCustomized === "boolean"
        ? parsed.scanTableColumnsCustomized
        : DEFAULTS.scanTableColumnsCustomized;

    return {
      minSizeBytes,
      cadence,
      density,
      theme,
      toolNavigation,
      landingPage,
      sidebarWidth,
      sidebarExpandedWidth,
      scanTableHiddenColumns,
      scanTableColumnsCustomized,
    };
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

// Module-level store so every `useSettings()` caller shares the same state.
// With plain `useState`, each component's hook had its own copy — updating
// the Settings page didn't reach AppShell's useApplyTheme, so theme flips
// weren't taking effect live.
let currentSettings: Settings = read();
const listeners = new Set<() => void>();

function setStore(next: Settings): void {
  currentSettings = next;
  write(next);
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): Settings {
  return currentSettings;
}

export function useSettings() {
  const settings = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  // Cross-tab sync: fires only for changes in other tabs.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY) {
        currentSettings = read();
        listeners.forEach((l) => l());
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const update = useCallback((patch: Partial<Settings>) => {
    setStore({ ...currentSettings, ...patch });
  }, []);

  const reset = useCallback(() => {
    setStore(DEFAULTS);
  }, []);

  return { settings, update, reset };
}

export function cadenceMs(id: CadenceId): number {
  return CADENCE_PRESETS.find((c) => c.id === id)?.staleMs ?? 0;
}

// Test helper: reinitialize module state from localStorage
export function __testReloadSettings(): void {
  currentSettings = read();
}
