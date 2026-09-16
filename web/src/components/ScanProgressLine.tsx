import { formatMs } from "@/lib/format";
import { formatScanProgress, type ScanProgressSnapshot } from "@/lib/scanProgress";

/**
 * One line of scan progress for the Disk page: provider count, bytes found,
 * running providers, then the countdown from past scans. Without a snapshot
 * it shows only the countdown, exactly what the page showed before #117.
 */
export function ScanProgressLine({
  progress,
  remainingMs,
  bar = false,
}: {
  progress: ScanProgressSnapshot | null;
  remainingMs: number | null;
  bar?: boolean;
}) {
  const parts = progress ? formatScanProgress(progress) : null;
  const words: string[] = [];
  if (parts) {
    words.push(parts.providers);
    if (parts.found) words.push(parts.found);
    if (parts.finishing) words.push("finishing…");
    else if (parts.running) words.push(parts.running);
  }
  if (remainingMs !== null) {
    words.push(remainingMs <= 0 ? "longer than past scans" : `~${formatMs(remainingMs)} left, from past scans`);
  }
  return (
    <>
      {words.map((word) => ` · ${word}`).join("")}
      {bar && progress && progress.total > 0 && (
        <div
          role="progressbar"
          aria-label="scan progress"
          aria-valuemin={0}
          aria-valuemax={progress.total}
          aria-valuenow={progress.done}
          className="mt-2 h-1 w-64 rounded bg-bg-elev-2 overflow-hidden"
        >
          <div
            className="h-full bg-risk-safe transition-[width]"
            style={{ width: progress.total > 0 ? `${(100 * progress.done) / progress.total}%` : "0%" }}
          />
        </div>
      )}
    </>
  );
}
