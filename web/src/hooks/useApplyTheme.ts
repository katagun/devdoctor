import { useEffect } from "react";
import { useSettings, type Theme } from "@/hooks/useSettings";

const DARK_ATTR = "terminal-refined";
const LIGHT_ATTR = "terminal-refined-light";

function resolve(theme: Theme): "dark" | "light" {
  if (theme === "dark") return "dark";
  if (theme === "light") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

// Applies `data-theme` on <html> based on the user setting. Listens for OS
// changes only while the setting is "system" so the UI flips live if the
// user toggles macOS appearance from the menu bar.
export function useApplyTheme() {
  const { settings } = useSettings();
  useEffect(() => {
    const apply = () => {
      const mode = resolve(settings.theme);
      document.documentElement.setAttribute(
        "data-theme",
        mode === "dark" ? DARK_ATTR : LIGHT_ATTR,
      );
    };
    apply();
    if (settings.theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [settings.theme]);
}
