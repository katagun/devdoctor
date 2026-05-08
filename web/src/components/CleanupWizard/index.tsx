import { CleanupWizardContext } from "./CleanupWizardState";
import type { CleanupResult } from "./CleanupWizardState";
import { useCleanupWizard } from "@/hooks/useCleanupWizard";
import type { CacheTableRow } from "@/components/CacheTable";
import { ReviewStep } from "./ReviewStep";
import { ExecuteStep } from "./ExecuteStep";
import { SummaryStep } from "./SummaryStep";
import { APP_NAME } from "@/lib/brand";
import { DISK_LABEL } from "@/lib/resourceLabels";

export function CleanupWizard({
  entries,
  onClose,
  onSuccess,
}: {
  entries: CacheTableRow[];
  onClose: () => void;
  onSuccess?: (results: CleanupResult[]) => void;
}) {
  const wizard = useCleanupWizard({ entries, onSuccess });
  const step = wizard.state.step;

  return (
    <CleanupWizardContext.Provider value={{ ...wizard, close: onClose }}>
      <div className="fixed inset-0 bg-bg/95 flex items-stretch z-50 backdrop-blur-sm">
        <div className="flex-1 bg-bg-elev-1 border-l border-border flex flex-col">
          <header className="px-4 py-3 bg-gradient-to-b from-bg-header-from to-bg-header-to border-b border-border flex items-center justify-between">
            <div className="font-mono font-semibold flex items-center gap-2">
              <span className="w-[7px] h-[7px] rounded-full bg-risk-reclaim" style={{boxShadow:"0 0 10px var(--risk-reclaim)"}} />
              {APP_NAME} <span className="text-text-muted font-normal">/ {DISK_LABEL} clean</span>
            </div>
            <div className="flex gap-2 text-[10px]">
              {(["review", "execute", "summary"] as const).map((s, i) => (
                <span
                  key={s}
                  className={`px-2.5 py-[3px] rounded border ${
                    step === s
                      ? "bg-bg-elev-2 text-text border-border-strong"
                      : step === "summary" || (step === "execute" && i === 0)
                        ? "text-risk-safe border-btn-primary-bd"
                        : "text-text-muted border-border"
                  }`}
                >
                  {i + 1} · {s}
                </span>
              ))}
            </div>
            <button onClick={onClose} className="text-text-muted hover:text-text text-[11px]">✕</button>
          </header>
          <div className="flex-1 overflow-auto">
            {step === "review" && <ReviewStep />}
            {step === "execute" && <ExecuteStep />}
            {step === "summary" && <SummaryStep />}
          </div>
        </div>
      </div>
    </CleanupWizardContext.Provider>
  );
}
