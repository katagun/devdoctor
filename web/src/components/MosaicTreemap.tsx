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
    <div role="img" aria-label={ariaLabel} className="h-full min-h-[280px]">
      <ResponsiveContainer width="100%" height="100%">
        <Treemap
          data={items.map((item) => ({ ...item, name: item.label }))}
          dataKey="value"
          nameKey="label"
          aspectRatio={4 / 3}
          isAnimationActive={false}
          stroke="var(--bg)"
          content={<MosaicTile />}
        />
      </ResponsiveContainer>
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
  const textColor = tone === "other" || tone === "process"
    ? "var(--text-dim)"
    : "var(--text-on-accent)";

  return (
    <g>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        rx={3}
        ry={3}
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
        <text
          x={x + 8}
          y={y + 17}
          fill={textColor}
          fontSize={11}
          fontFamily="var(--font-mono)"
          fontWeight={600}
        >
          {truncate(label, Math.floor((width - 14) / 6.2))}
        </text>
      )}
      {showValue && (
        <text
          x={x + 8}
          y={y + 35}
          fill={textColor}
          opacity={0.82}
          fontSize={10}
          fontFamily="var(--font-mono)"
        >
          {humanBytes(value)}
        </text>
      )}
    </g>
  );
}

function truncate(value: string, maxChars: number): string {
  if (maxChars <= 1) return "";
  if (value.length <= maxChars) return value;
  return `${value.slice(0, Math.max(1, maxChars - 1))}…`;
}
