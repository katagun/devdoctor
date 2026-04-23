import { useCallback, useEffect, useId, useRef, useState } from "react";
import { COLUMNS } from "@/components/CacheTable/columns";
import { useHiddenColumns } from "@/hooks/useHiddenColumns";

export function ColumnsPicker() {
  const { isVisible, setHidden } = useHiddenColumns();
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const panelId = useId();

  const close = useCallback(() => {
    setOpen(false);
    buttonRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close]);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      const target = e.target as Node;
      if (buttonRef.current?.contains(target)) return;
      if (panelRef.current?.contains(target)) return;
      setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        className="px-3 py-1 rounded text-[11px] border border-border text-text-dim hover:text-text hover:border-border-strong transition-colors"
      >
        columns ▾
      </button>
      {open && (
        <div
          ref={panelRef}
          id={panelId}
          role="menu"
          aria-label="Toggle columns"
          className="absolute right-0 top-full mt-1 min-w-[180px] bg-bg-elev-1 border border-border rounded shadow-lg z-10 py-1"
        >
          <div className="text-text-muted text-[9.5px] uppercase tracking-widest px-3 py-1.5">
            show columns
          </div>
          {COLUMNS.map((col) => {
            const checked = isVisible(col.id);
            const disabled = !col.hideable;
            return (
              <button
                key={col.id}
                type="button"
                role="menuitemcheckbox"
                aria-checked={checked}
                aria-disabled={disabled || undefined}
                onClick={() => {
                  if (disabled) return;
                  setHidden(col.id, checked);
                }}
                className={`w-full text-left flex items-center gap-2 px-3 py-1.5 text-[11px] ${
                  disabled ? "text-text-muted cursor-not-allowed" : "text-text hover:bg-bg-elev-2"
                }`}
              >
                <span aria-hidden="true" className="inline-block w-3 text-[10px]">
                  {checked ? "☑" : "☐"}
                </span>
                <span>{col.label}</span>
                {disabled && (
                  <span className="text-text-muted text-[9px] ml-auto">locked</span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
