import { SparklineBar } from "./SparklineBar";
import { humanBytes } from "@/lib/format";

export function TopStats({
  reclaimable,
  cacheCount,
  diskUsedPct,
}: {
  reclaimable: number;
  cacheCount: number;
  diskUsedPct: number | null;
}) {
  return (
    <div className="px-4 py-3 border-b border-border flex gap-5 items-center text-[10px] text-text-dim font-mono">
      <span>
        <b className="text-text">{humanBytes(reclaimable)}</b> reclaimable
      </span>
      <SparklineBar heights={[20, 35, 45, 58, 70, 82, 92, 85]} />
      <span>
        <b className="text-text">{cacheCount}</b> caches
      </span>
      {diskUsedPct !== null && (
        <span>
          <b className="text-text">{diskUsedPct}%</b> disk used
        </span>
      )}
    </div>
  );
}
