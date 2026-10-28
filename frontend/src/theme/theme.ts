import { useMemo, useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

// index.html applies the same rule before the first paint, so the page never flashes the wrong theme.
const STORAGE_KEY = "cir:theme";
const THEME_COLORS: Record<Theme, string> = { light: "#f1f4f2", dark: "#0b1311" };
const listeners = new Set<() => void>();

function storedTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function systemTheme(): Theme {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function apply(theme: Theme, animate: boolean) {
  const root = document.documentElement;
  if (animate) {
    root.classList.add("theme-switching");
    window.setTimeout(() => root.classList.remove("theme-switching"), 220);
  }
  root.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLORS[theme]);
  listeners.forEach(listener => listener());
}

/** The user's choice is remembered on this device; without one the device setting is followed. */
export function setTheme(theme: Theme) {
  try { window.localStorage.setItem(STORAGE_KEY, theme); } catch { /* this visit only */ }
  apply(theme, true);
}

export function toggleTheme() {
  setTheme(currentTheme() === "dark" ? "light" : "dark");
}

if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
  if (!document.documentElement.dataset.theme) apply(storedTheme() ?? systemTheme(), false);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
    if (!storedTheme()) apply(systemTheme(), true);
  });
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, currentTheme, () => "light");
}

/** Resolved values of CSS colour tokens, for libraries (charts) that need plain colours; refreshed on theme change. */
export function useThemeColors<T extends Record<string, string>>(tokens: T): { [K in keyof T]: string } {
  const theme = useTheme();
  return useMemo(() => {
    const style = getComputedStyle(document.documentElement);
    const resolved = {} as { [K in keyof T]: string };
    for (const key of Object.keys(tokens) as Array<keyof T>) {
      resolved[key] = style.getPropertyValue(tokens[key]).trim() || "currentColor";
    }
    return resolved;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);
}
