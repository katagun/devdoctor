/** Magnitude tier for a byte count, used to dim/de-emphasize trivial deltas
 * in the snapshots list so a 14 KB churn doesn't read as visually equal to a
 * 700 MB cleanup. Thresholds match the units in `humanBytes` (1024-based). */
export type ByteMagnitude = "trivial" | "notable" | "significant";

const ONE_MIB = 1024 * 1024;
const ONE_GIB = 1024 * 1024 * 1024;

export function byteMagnitudeTier(bytes: number): ByteMagnitude {
  const abs = Math.abs(bytes);
  if (abs < ONE_MIB) return "trivial";
  if (abs < ONE_GIB) return "notable";
  return "significant";
}

export function humanBytes(n: number): string {
  const sign = n < 0 ? "-" : "";
  let v = Math.abs(n);
  const units = ["B", "K", "M", "G", "T", "P"];
  for (let i = 0; i < units.length; i++) {
    if (v < 1024 || i === units.length - 1) {
      if (units[i] === "B") return `${sign}${Math.round(v)}B`;
      return `${sign}${v.toFixed(1)}${units[i]}`;
    }
    v /= 1024;
  }
  return `${sign}${v.toFixed(1)}P`;
}

export function formatMs(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const totalSecs = Math.floor(ms / 1000);
  const m = Math.floor(totalSecs / 60);
  const s = totalSecs % 60;
  return `${m}m ${s}s`;
}

export function staleness(mtime: number | null): string {
  if (mtime === null) return "—";
  const ageDays = (Date.now() / 1000 - mtime) / 86400;
  if (ageDays < 1) return "today";
  if (ageDays < 30) return `${Math.floor(ageDays)}d`;
  if (ageDays < 365) return `${Math.floor(ageDays / 30)}mo`;
  return `${(ageDays / 365).toFixed(1)}y`;
}

// Compact relative time ("5 min ago", "yesterday", "Apr 20") for display.
export function timeAgo(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const secs = Math.floor((now.getTime() - d.getTime()) / 1000);
  if (secs < 5) return "just now";
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  // Same year: drop year; else include it.
  const sameYear = d.getFullYear() === now.getFullYear();
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: sameYear ? undefined : "numeric",
  });
}

// Absolute local date-time for the secondary line, e.g. "Apr 20, 2:48 PM".
export function formatAbsTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export type RiskValue = "safe" | "reclaimable" | "dangerous";
export function riskLabel(risk: RiskValue): string {
  return { safe: "safe", reclaimable: "reclaim", dangerous: "DANGER" }[risk];
}

export interface RecipeHint {
  kind: "advice" | "command";
  text: string;
  sentences: string[];
}

// Classify a recipe line into advice (`echo '...'`, rendered as bullets) or a
// raw shell command (rendered as-is). Sentence splitting for advice uses
// ". " before an uppercase letter or digit to avoid breaking abbreviations.
export function parseRecipeHint(line: string): RecipeHint {
  const m = /^echo\s+'([\s\S]+)'$/.exec(line.trim());
  if (!m) return { kind: "command", text: line, sentences: [line] };
  const msg = m[1];
  const sentences = msg
    .split(/(?<=\.)\s+(?=[A-Z0-9])/g)
    .map((s) => s.trim())
    .filter(Boolean);
  return { kind: "advice", text: msg, sentences: sentences.length ? sentences : [msg] };
}
