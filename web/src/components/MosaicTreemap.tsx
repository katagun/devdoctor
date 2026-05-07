import { ResponsiveContainer, Treemap } from "recharts";
import type { TreemapNode } from "recharts/types/util/types";
import type { MosaicDatum, MosaicTone } from "@/lib/dashboard";
import { humanBytes } from "@/lib/format";

const FILL_BY_TONE: Record<MosaicTone, string> = {
  safe: "var(--risk-safe)",
  reclaimable: "var(--risk-reclaim)",
  dangerous: "var(--risk-danger)",
  browser: "var(--risk-reclaim)",
  electron: "var(--text-accent)",
  docker: "var(--risk-safe)",
  llm: "var(--risk-danger)",
  app: "var(--accent)",
  process: "var(--border-strong)",
  other: "var(--bg-control-off)",
};

interface MosaicTreemapProps {
  items: MosaicDatum[];
  ariaLabel: string;
  emptyLabel: string;
}

export function MosaicTreemap({ items, ariaLabel, emptyLabel }: MosaicTreemapProps) {
  if (items.length === 0) {
    return (
      <div className="h-full min-h-[280px] flex items-center justify-center text-text-muted text-[11px] border border-border-subtle bg-bg-code">
        {emptyLabel}
      </div>
    );
  }

  return (
    <div role="img" aria-label={ariaLabel} className="h-full min-h-[280px] p-2">
      <div className="h-full min-h-[264px] rounded overflow-hidden bg-bg-elev-1 border border-border-subtle">
        <ResponsiveContainer width="100%" height="100%">
          <Treemap
            data={items.map((item) => ({ ...item, name: item.label }))}
            dataKey="value"
            nameKey="label"
            aspectRatio={1}
            isAnimationActive={false}
            stroke="var(--bg)"
            content={<MosaicTile />}
          />
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function MosaicTile(props: Partial<TreemapNode> & Partial<MosaicDatum>) {
  const x = props.x ?? 0;
  const y = props.y ?? 0;
  const width = Math.max(0, props.width ?? 0);
  const height = Math.max(0, props.height ?? 0);
  const value = typeof props.value === "number" ? props.value : 0;
  const label = props.label ?? props.name ?? "";
  const tone = props.tone ?? "other";
  const detail = props.detail;
  const showLabel = width >= 78 && height >= 36;
  const showValue = width >= 98 && height >= 54;
  const clipId = `mosaic-${String(props.id ?? props.index ?? label).replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  const textColor = tone === "other" || tone === "process"
    ? "var(--text-dim)"
    : "var(--text-on-accent)";

  return (
    <g>
      <clipPath id={clipId}>
        <rect
          x={x + 4}
          y={y + 4}
          width={Math.max(0, width - 8)}
          height={Math.max(0, height - 8)}
          rx={2}
          ry={2}
        />
      </clipPath>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        rx={2}
        ry={2}
        fill={FILL_BY_TONE[tone]}
        opacity={tone === "other" ? 0.62 : 0.9}
        stroke="var(--bg)"
        strokeWidth={2}
      />
      <title>
        {label} · {humanBytes(value)}
        {detail ? ` · ${detail}` : ""}
      </title>
      {showLabel && (
        <g clipPath={`url(#${clipId})`}>
          <text
            x={x + 8}
            y={y + 18}
            fill={textColor}
            fontSize={11}
            fontFamily="var(--font-mono)"
            fontWeight={600}
          >
            {truncate(label, Math.floor((width - 16) / 6.2))}
          </text>
        </g>
      )}
      {showValue && (
        <g clipPath={`url(#${clipId})`}>
          <text
            x={x + 8}
            y={y + 36}
            fill={textColor}
            opacity={0.82}
            fontSize={10}
            fontFamily="var(--font-mono)"
          >
            {humanBytes(value)}
          </text>
        </g>
      )}
    </g>
  );
}

function truncate(value: string, maxChars: number): string {
  if (maxChars <= 1) return "";
  if (value.length <= maxChars) return value;
  return `${value.slice(0, Math.max(1, maxChars - 1))}…`;
}
