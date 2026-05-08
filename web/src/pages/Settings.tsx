import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  CADENCE_PRESETS,
  SIZE_PRESETS,
  useSettings,
  type CadenceId,
  type Density,
  type LandingPage,
  type Theme,
  type ToolNavigation,
} from "@/hooks/useSettings";
import {
  useAppSettings,
  useUpdateAppSettings,
  type StorageBackend,
} from "@/hooks/useAppSettings";
import { DiskUsageBar } from "@/components/DiskUsageBar";
import { ResourceLabel } from "@/components/ResourceLabel";
import { humanBytes } from "@/lib/format";
import { DISK_LABEL, DISK_TITLE, MEMORY_LABEL, MEMORY_TITLE } from "@/lib/resourceLabels";

const SAVED_MS = 1200;

export default function Settings() {
  const { settings, update, reset } = useSettings();
  const appSettings = useAppSettings();
  const updateAppSettings = useUpdateAppSettings();
  const [customMb, setCustomMb] = useState<string>(
    settings.minSizeBytes && !SIZE_PRESETS.some((p) => p.bytes === settings.minSizeBytes)
      ? String(Math.round(settings.minSizeBytes / 1_000_000))
      : "",
  );
  const [sqlitePath, setSqlitePath] = useState("");
  const [savedFlash, setSavedFlash] = useState(false);

  useEffect(() => {
    if (!savedFlash) return;
    const t = setTimeout(() => setSavedFlash(false), SAVED_MS);
    return () => clearTimeout(t);
  }, [savedFlash]);

  useEffect(() => {
    if (appSettings.data?.sqlite_path) {
      setSqlitePath(appSettings.data.sqlite_path);
    }
  }, [appSettings.data?.sqlite_path]);

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

  function setTheme(t: Theme) {
    applyAndFlash({ theme: t });
  }

  function setToolNavigation(toolNavigation: ToolNavigation) {
    applyAndFlash({ toolNavigation });
  }

  function setLandingPage(landingPage: LandingPage) {
    applyAndFlash({ landingPage });
  }

  function setStorageBackend(storageBackend: StorageBackend) {
    updateAppSettings.mutate(
      { storage_backend: storageBackend },
      { onSuccess: () => setSavedFlash(true) },
    );
  }

  function saveSqlitePath() {
    const trimmed = sqlitePath.trim();
    if (!trimmed) return;
    updateAppSettings.mutate(
      { sqlite_path: trimmed },
      { onSuccess: () => setSavedFlash(true) },
    );
  }

  function setCustom(mbRaw: string) {
    setCustomMb(mbRaw);
    const mb = Number(mbRaw);
    if (!Number.isFinite(mb) || mb < 0) return;
    applyAndFlash({ minSizeBytes: Math.round(mb * 1_000_000) });
  }

  return (
    <div className="font-mono">
      <header className="px-4 py-3 border-b border-border flex items-center gap-4">
        <h1 className="text-text text-[14px] font-medium">Settings</h1>
        <span className="text-text-dim text-[11px]">
          Stored locally in your browser.
        </span>
        <div
          className={`ml-auto text-[10.5px] transition-opacity ${
            savedFlash ? "opacity-100 text-risk-safe" : "opacity-0"
          }`}
        >
          ● saved
        </div>
        <DiskUsageBar />
      </header>

      <div className="p-8 max-w-2xl">
        <Section
        title="Appearance"
        description="Light follows the Terminal Refined palette on a warm off-white background; dark is the default neon-on-black. System tracks your OS preference and flips live when you toggle macOS appearance."
      >
        <div className="flex gap-2">
          <Chip active={settings.theme === "light"} onClick={() => setTheme("light")}>
            ☀ light
          </Chip>
          <Chip active={settings.theme === "dark"} onClick={() => setTheme("dark")}>
            ☾ dark
          </Chip>
          <Chip active={settings.theme === "system"} onClick={() => setTheme("system")}>
            ⌘ system
          </Chip>
        </div>
      </Section>

      <Section
        title="Minimum size cutoff"
        description={`Hide tiny entries from the ${DISK_LABEL} table. Items below the threshold are bucketed into a single 'small items' summary row so you can see the totals without the noise.`}
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
        description={`${DISK_TITLE} table row height. Dense collapses provider and label onto one line so more entries fit on screen without scrolling.`}
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
        title="Tool navigation"
        description={`Controls whether ${DISK_LABEL} and ${MEMORY_LABEL} tools live in the left sidebar or in horizontal tabs inside each resource page.`}
      >
        <div className="space-y-1.5">
          <RadioRow
            checked={settings.toolNavigation === "sidebar"}
            onClick={() => setToolNavigation("sidebar")}
            label="Sidebar"
            caption={`Show ${DISK_LABEL} and ${MEMORY_LABEL} tools in the left navigation.`}
          />
          <RadioRow
            checked={settings.toolNavigation === "tabs"}
            onClick={() => setToolNavigation("tabs")}
            label="Page tabs"
            caption="Show only resource roots in the sidebar and put tools in each page header."
          />
        </div>
      </Section>

      <Section
        title="Landing page"
        description="Choose which resource opens when you visit DevDoctor without a specific path."
      >
        <div className="space-y-1.5">
          <RadioRow
            checked={settings.landingPage === "dashboard"}
            onClick={() => setLandingPage("dashboard")}
            label="Dashboard"
            caption={`Open the combined ${DISK_LABEL} and ${MEMORY_LABEL} overview by default.`}
          />
          <RadioRow
            checked={settings.landingPage === "disk"}
            onClick={() => setLandingPage("disk")}
            label={<ResourceLabel resource="disk" label={DISK_TITLE} />}
            caption={`Open the ${DISK_LABEL} scan by default.`}
          />
          <RadioRow
            checked={settings.landingPage === "memory"}
            onClick={() => setLandingPage("memory")}
            label={<ResourceLabel resource="memory" label={MEMORY_TITLE} />}
            caption={`Open the live ${MEMORY_LABEL} view by default.`}
          />
        </div>
      </Section>

      <Section
        title="Rescan cadence"
        description={`Controls how often the ${DISK_TITLE} page re-hits the backend during navigation. Reloading the browser always triggers a fresh scan — cadence only applies while moving between pages within an app session.`}
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

      <Section
        title="Storage backend"
        description={`Controls where DevDoctor stores server-side records such as ${DISK_LABEL} snapshots and cleanup history. Filesystem keeps the existing JSON files; SQLite stores records in one local database.`}
      >
        {appSettings.isLoading ? (
          <div className="text-text-muted text-[11px] animate-pulse">loading storage settings…</div>
        ) : appSettings.isError ? (
          <div className="text-risk-danger text-[11px]">
            Failed to load storage settings: {String(appSettings.error)}
          </div>
        ) : appSettings.data ? (
          <div className="space-y-3">
            <div className="flex gap-2">
              <Chip
                active={appSettings.data.storage_backend === "filesystem"}
                onClick={() => setStorageBackend("filesystem")}
              >
                filesystem
              </Chip>
              <Chip
                active={appSettings.data.storage_backend === "sqlite"}
                onClick={() => setStorageBackend("sqlite")}
              >
                sqlite
              </Chip>
            </div>
            <div className="grid gap-2 text-[10.5px] text-text-dim">
              <PathRow label="Data directory" value={appSettings.data.data_dir} />
              <label className="grid gap-1">
                <span>SQLite path</span>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={sqlitePath}
                    onChange={(e) => setSqlitePath(e.target.value)}
                    className="flex-1 bg-bg-elev-1 border border-border rounded px-2 py-1 text-[11px] text-text focus:outline-none focus:border-risk-reclaim"
                  />
                  <button
                    type="button"
                    onClick={saveSqlitePath}
                    disabled={updateAppSettings.isPending}
                    className="px-3 py-1 rounded border border-border text-text-dim hover:text-text disabled:opacity-50"
                  >
                    save
                  </button>
                </div>
              </label>
              {updateAppSettings.isError && (
                <div className="text-risk-danger">
                  Failed to save storage settings: {String(updateAppSettings.error)}
                </div>
              )}
            </div>
          </div>
        ) : null}
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
  children: ReactNode;
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

function PathRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1">
      <span>{label}</span>
      <code className="block bg-bg-elev-1 border border-border rounded px-2 py-1 text-text break-all">
        {value}
      </code>
    </div>
  );
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1 rounded text-[11px] border transition-colors ${
        active
          ? "border-risk-reclaim bg-risk-reclaim/10 text-risk-reclaim"
          : "border-border text-text-dim hover:text-text hover:border-border-strong"
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
  label: ReactNode;
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
