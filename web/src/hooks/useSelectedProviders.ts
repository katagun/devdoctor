import { useCallback, useEffect, useState } from "react";

// We persist the DISABLED set (not enabled) so newly-added providers default
// to on — matches the "all selected by default" contract.
const KEY = "diskdoctor.providers.disabled";

function read(): Set<string> {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return new Set();
    return new Set(arr.filter((v): v is string => typeof v === "string"));
  } catch {
    return new Set();
  }
}

function write(set: Set<string>): void {
  try {
    localStorage.setItem(KEY, JSON.stringify([...set]));
  } catch {
    /* ignore (private mode, quota) */
  }
}

export function useSelectedProviders() {
  const [disabled, setDisabled] = useState<Set<string>>(read);

  // Listen for cross-tab updates.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY) setDisabled(read());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setEnabled = useCallback((name: string, enabled: boolean) => {
    setDisabled((prev) => {
      const next = new Set(prev);
      if (enabled) next.delete(name);
      else next.add(name);
      write(next);
      return next;
    });
  }, []);

  const isEnabled = useCallback((name: string) => !disabled.has(name), [disabled]);

  return { disabled, isEnabled, setEnabled };
}
