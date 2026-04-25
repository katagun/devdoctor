import type { ProviderRow } from "@/hooks/useProviders";
import type { ProviderTimingMeta } from "@/hooks/useSnapshots";
import { humanBytes, formatMs } from "@/lib/format";

interface Props {
  provider: ProviderRow;
  lastAuto: ProviderTimingMeta | null;
}

export function ProviderDetailsPanel({ provider, lastAuto }: Props) {
  return (
    <div
      role="region"
      aria-label={`${provider.name} details`}
      className="bg-surface-muted px-4 py-3 space-y-3"
    >
      <PathsSection provider={provider} />
      {provider.recipe_template && <RecipeSection lines={provider.recipe_template} />}
      {lastAuto && <LastScanSection stats={lastAuto} />}
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[9.5px] uppercase tracking-widest text-text-dim mb-1">
      {children}
    </div>
  );
}

function PathsSection({ provider }: { provider: ProviderRow }) {
  if (provider.raw_paths && provider.raw_paths.length > 0) {
    return (
      <div>
        <SectionHeading>paths</SectionHeading>
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-x-4 gap-y-1">
          {provider.raw_paths.map((raw) => {
            const matched = (provider.resolved_paths ?? []).filter((rp) =>
              matchesRaw(raw, rp),
            );
            return (
              <RowPair
                key={raw}
                raw={raw}
                resolved={matched.length > 0 ? matched : null}
              />
            );
          })}
        </div>
      </div>
    );
  }
  if (provider.details) {
    return (
      <div>
        <SectionHeading>paths</SectionHeading>
        <p className="text-text-muted text-[11px] leading-relaxed">{provider.details}</p>
      </div>
    );
  }
  return (
    <div>
      <SectionHeading>paths</SectionHeading>
      <p className="text-text-dim text-[11px]">No path information available.</p>
    </div>
  );
}

function RowPair({ raw, resolved }: { raw: string; resolved: string[] | null }) {
  return (
    <>
      <div className="font-mono text-text-muted truncate" title={raw}>
        {raw}
      </div>
      <div className="font-mono text-text-dim">
        {resolved === null ? (
          <span className="text-text-dim italic">(no match)</span>
        ) : (
          resolved.map((r) => (
            <div key={r} className="truncate" title={r}>
              {r}
            </div>
          ))
        )}
      </div>
    </>
  );
}

function matchesRaw(raw: string, resolved: string): boolean {
  // Cheap heuristic: strip leading "~" or "$VAR" segment from raw, then
  // see if the resolved path ends with the remaining tail. Good enough for
  // display; the backend has the exact mapping.
  const tail = raw.replace(/^[~$][^/]*\/?/, "");
  return resolved.endsWith(tail) || resolved === raw;
}

function RecipeSection({ lines }: { lines: string[] }) {
  return (
    <div>
      <SectionHeading>cleanup recipe</SectionHeading>
      <p className="text-text-dim text-[10px] mb-1">
        Runs once per matched path, with <code>{"{path}"}</code> replaced by the resolved path.
      </p>
      <pre
        data-testid="recipe-block"
        className="bg-surface-sunken font-mono text-[11px] p-2 rounded overflow-x-auto"
      >
        <code>{lines.join("\n")}</code>
      </pre>
    </div>
  );
}

function LastScanSection({ stats }: { stats: ProviderTimingMeta }) {
  return (
    <div>
      <SectionHeading>last scan</SectionHeading>
      <div className="text-text-muted text-[11px] flex gap-4">
        <span>entries: {stats.entries}</span>
        <span>total: {humanBytes(stats.bytes)}</span>
        <span>duration: {formatMs(stats.duration_ms)}</span>
      </div>
    </div>
  );
}
