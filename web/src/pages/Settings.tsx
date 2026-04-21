import { useEffect, useState } from "react";
import {
  CADENCE_PRESETS,
  SIZE_PRESETS,
  useSettings,
  type CadenceId,
  type Density,
} from "@/hooks/useSettings";
import { humanBytes } from "@/lib/format";

const SAVED_MS = 1200;

export default function Settings() {
  const { settings, update, reset } = useSettings();
  const [customMb, setCustomMb] = useState<string>(
    settings.minSizeBytes && !SIZE_PRESETS.some((p) => p.bytes === settings.minSizeBytes)
      ? String(Math.round(settings.minSizeBytes / 1_000_000))
      : "",
  );
  const [savedFlash, setSavedFlash] = useState(false);

  useEffect(() => {
    if (!savedFlash) return;
    const t = setTimeout(() => setSavedFlash(false), SAVED_MS);
    return () => clearTimeout(t);
  }, [savedFlash]);

  function applyAndFlash(patch: Parameters<typeof update>[0]) {
    update(patch);
    setSavedFlash(true);
  }

  function setPreset(bytes: number) {
    setCustomMb("");
    applyAndFlash({ minSizeBytes: bytes });
  }

  function setCadence(id: CadenceId) {
    applyAndFlash({ cadence: id });
  }

  function setDensity(d: Density) {
    applyAndFlash({ density: d });
  }

  function setCustom(mbRaw: string) {
    setCustomMb(mbRaw);
    const mb = Number(mbRaw);
    if (!Number.isFinite(mb) || mb < 0) return;
    applyAndFlash({ minSizeBytes: Math.round(mb * 1_000_000) });
  }

  return (
    <div className="p-8 max-w-2xl font-mono">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-text text-[18px] font-medium">Settings</h1>
          <p className="text-text-dim text-[11px] mt-1">
            Stored locally in your browser.
          </p>
        </div>
        <div
          className={`text-[10.5px] transition-opacity ${
            savedFlash ? "opacity-100 text-risk-safe" : "opacity-0"
          }`}
        >
          ● saved
        </div>
      </header>

      <Section
        title="Minimum size cutoff"
        description="Hide tiny entries from the scan table. Items below the threshold are bucketed into a single 'small items' summary row so you can see the totals without the noise."
      >
        <div className="flex gap-2 flex-wrap">
          {SIZE_PRESETS.map((p) => (
            <Chip
              key={p.label}
              active={settings.minSizeBytes === p.bytes && !customMb}
              onClick={() => setPreset(p.bytes)}
            >
              {p.label}
            </Chip>
          ))}
        </div>
        <label className="flex items-center gap-2 mt-4 text-[11px]">
          <span className="text-text-dim">Custom (MB):</span>
          <input
            type="number"
            min={0}
            step={10}
            value={customMb}
            onChange={(e) => setCustom(e.target.value)}
            placeholder="e.g. 250"
            className="bg-bg-elev-1 border border-border rounded px-2 py-1 text-[11px] text-text w-24 focus:outline-none focus:border-risk-reclaim"
          />
          {settings.minSizeBytes > 0 && (
            <span className="text-text-muted text-[10.5px]">
              currently hiding entries &lt; {humanBytes(settings.minSizeBytes)}
            </span>
          )}
        </label>
      </Section>

      <Section
        title="Row density"
        description="Scan table row height. Dense collapses provider and label onto one line so more entries fit on screen without scrolling."
      >
        <div className="flex gap-2">
          <Chip active={settings.density === "sparse"} onClick={() => setDensity("sparse")}>
            sparse
          </Chip>
          <Chip active={settings.density === "dense"} onClick={() => setDensity("dense")}>
            dense
          </Chip>
        </div>
      </Section>

      <Section
        title="Rescan cadence"
        description="Controls how often the Scan page re-hits the backend during navigation. Reloading the browser always triggers a fresh scan — cadence only applies while moving between pages within an app session."
      >
        <div className="space-y-1.5">
          {CADENCE_PRESETS.map((c) => (
            <RadioRow
              key={c.id}
              checked={settings.cadence === c.id}
              onClick={() => setCadence(c.id)}
              label={c.label}
              caption={c.caption}
            />
          ))}
        </div>
      </Section>

      <div className="mt-8 pt-4 border-t border-border flex justify-between items-center">
        <button
          onClick={() => {
            reset();
            setCustomMb("");
            setSavedFlash(true);
          }}
          className="text-[11px] text-text-dim hover:text-text"
        >
          ↺ reset to defaults
        </button>
        <span className="text-text-muted text-[10px]">stored in localStorage</span>
      </div>
    </div>
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-8">
      <h2 className="text-text text-[13px] font-medium mb-1">{title}</h2>
      {description && (
        <p className="text-text-dim text-[11px] mb-3 leading-relaxed max-w-[60ch]">
          {description}
        </p>
      )}
      {children}
    </section>
  );
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1 rounded text-[11px] border transition-colors ${
        active
          ? "border-risk-reclaim bg-risk-reclaim/10 text-risk-reclaim"
          : "border-border text-text-dim hover:text-text hover:border-[#2a3441]"
      }`}
    >
      {children}
    </button>
  );
}

function RadioRow({
  checked,
  onClick,
  label,
  caption,
}: {
  checked: boolean;
  onClick: () => void;
  label: string;
  caption: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left flex items-center gap-3 px-3 py-2 rounded border transition-colors ${
        checked
          ? "border-risk-reclaim bg-risk-reclaim/5"
          : "border-border hover:bg-bg-elev-1"
      }`}
    >
      <span
        className={`w-3 h-3 rounded-full border-2 shrink-0 ${
          checked ? "border-risk-reclaim bg-risk-reclaim" : "border-text-muted"
        }`}
      />
      <div className="flex-1 min-w-0">
        <div className={`text-[11.5px] ${checked ? "text-text" : "text-text-dim"}`}>
          {label}
        </div>
        <div className="text-text-muted text-[10px] mt-0.5">{caption}</div>
      </div>
    </button>
  );
}
