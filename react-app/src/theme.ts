/**
 * Theme handling — light/dark. The initial theme follows the OS
 * (prefers-color-scheme); an explicit toggle is persisted in localStorage
 * and wins over the OS. `index.html` has an inline copy of the boot logic
 * so the right `data-theme` is set before first paint (no flash).
 */

import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "pheme-theme";
const listeners = new Set<() => void>();

function systemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function storedTheme(): Theme | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

/** The active theme: the persisted override if any, else the OS setting. */
export function getTheme(): Theme {
  return storedTheme() ?? systemTheme();
}

function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

/**
 * Apply the theme once at startup and follow OS changes while the user has
 * no stored override. Called from main.tsx.
 */
export function initTheme(): void {
  applyTheme(getTheme());
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", (e) => {
      if (storedTheme() === null) applyTheme(e.matches ? "dark" : "light");
    });
}

/** Set the theme explicitly (persisted) and notify subscribers. */
export function setTheme(theme: Theme): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Storage unavailable (private mode) — the theme still applies now.
  }
  applyTheme(theme);
  for (const listener of listeners) listener();
}

export function toggleTheme(): void {
  setTheme(getTheme() === "dark" ? "light" : "dark");
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** React hook for the current theme — re-renders components on toggle. */
export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, getTheme, () => "light");
}
