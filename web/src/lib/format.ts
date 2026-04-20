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

export function staleness(mtime: number | null): string {
  if (mtime === null) return "—";
  const ageDays = (Date.now() / 1000 - mtime) / 86400;
  if (ageDays < 1) return "today";
  if (ageDays < 30) return `${Math.floor(ageDays)}d`;
  if (ageDays < 365) return `${Math.floor(ageDays / 30)}mo`;
  return `${(ageDays / 365).toFixed(1)}y`;
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
