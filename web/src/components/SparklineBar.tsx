// A tiny pure-CSS sparkline — no runtime chart dep for the header.
export function SparklineBar({ heights }: { heights: number[] }) {
  return (
    <div className="flex gap-0.5 items-end h-[18px]">
      {heights.map((h, i) => (
        <div
          key={i}
          className="w-[3px] rounded-sm"
          style={{
            height: `${Math.max(4, h)}%`,
            background: "linear-gradient(180deg, var(--risk-safe), #2a7f55)",
          }}
        />
      ))}
    </div>
  );
}
