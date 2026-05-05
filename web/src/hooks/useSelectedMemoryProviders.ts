import { useCallback, useEffect, useState } from "react";

// Persist the disabled set so newly-added memory providers default to enabled.
const KEY = "devdoctor.memory.providers.disabled";

function read(): Set<string> {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return new Set();
    return new Set(arr.filter((value): value is string => typeof value === "string"));
  } catch {
    return new Set();
  }
}

function write(set: Set<string>): void {
  try {
    localStorage.setItem(KEY, JSON.stringify([...set]));
  } catch {
    /* ignore private-mode/quota errors */
  }
}

export function useSelectedMemoryProviders() {
  const [disabled, setDisabled] = useState<Set<string>>(read);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === KEY) setDisabled(read());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setEnabled = useCallback((id: string, enabled: boolean) => {
    setDisabled((prev) => {
      const next = new Set(prev);
      if (enabled) next.delete(id);
      else next.add(id);
      write(next);
      return next;
    });
  }, []);

  const setMany = useCallback((ids: string[], enabled: boolean) => {
    setDisabled((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (enabled) next.delete(id);
        else next.add(id);
      }
      write(next);
      return next;
    });
  }, []);

  const isEnabled = useCallback((id: string) => !disabled.has(id), [disabled]);

  return { disabled, isEnabled, setEnabled, setMany };
}
