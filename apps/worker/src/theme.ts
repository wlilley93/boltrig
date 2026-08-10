// One place that flips the console theme. The same storage key and
// document dataset are read by the pre-render bootstrap in main.tsx and by
// the Account appearance preference, so every writer stays in agreement.
const THEME_KEY = "boltrig-worker-theme";

export type WorkerTheme = "light" | "dark";

export function appliedTheme(): WorkerTheme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function toggleTheme(): WorkerTheme {
  const next: WorkerTheme = appliedTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch {
    // Storage can be unavailable in hardened browser contexts; the toggle
    // still applies for this session.
  }
  return next;
}
