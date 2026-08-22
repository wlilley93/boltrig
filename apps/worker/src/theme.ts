// Appearance + accessibility preferences are persisted by the kernel and
// mirrored locally so every axis can be applied before React paints. The
// server-setting keys are the documented Settings contract; the older theme
// key remains as a compatibility mirror for existing installs.

export type WorkerTheme = "light" | "dark";
export type ThemePreference = WorkerTheme | "system";
export type AppearanceDensity = "comfortable" | "compact";
export type FontScale = "0.9" | "1" | "1.1" | "1.25";

// NOTE: the Stage character deliberately does not live here. It has its own
// persistence and change event in src/character.ts.


export interface Appearance {
  theme: ThemePreference;
  density: AppearanceDensity;
  fontScale: FontScale;
  reducedMotion: boolean;
  highContrast: boolean;
}

export const APPEARANCE_KEYS = {
  theme: "theme",
  density: "density",
  fontScale: "font_scale",
  reducedMotion: "a11y.reduced_motion",
  highContrast: "a11y.high_contrast",
} as const;

export const DEFAULT_APPEARANCE: Appearance = {
  // DARK, not "system". Boltrig is a dark product - every surface, the brand
  // mark's ground and the captured design targets are all built dark - so
  // following the OS meant a first-run visitor on a light Mac got the light
  // palette as their introduction to it. "system" remains a choice a person can
  // make in Settings; it is no longer what they get without choosing.
  theme: "dark",
  density: "comfortable",
  fontScale: "1",
  reducedMotion: false,
  highContrast: false,
};

export const APPEARANCE_CHANGE_EVENT = "boltrig:appearance-change";

const APPEARANCE_STORAGE_KEY = "boltrig.appearance";
const LEGACY_THEME_KEY = "boltrig-worker-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

let currentAppearance: Appearance | null = null;
let systemThemeQuery: MediaQueryList | null = null;

// ── Page modes (URL-carried, per-load, never persisted) ─────────────────────
// An embedding host (the Opbox Agents panel) opens the worker with
// `?theme=light&embed=1`. Both are read from the real search string - the app
// is a hash router, so the search part survives every hash navigation - and
// both are re-read per call rather than cached: the parse is trivial and a
// test can then drive them through location alone. They deliberately touch
// NEITHER localStorage nor the kernel settings: the person's saved preference
// is what they chose; a host forcing light for one pane is not a choice.

/** The `?theme=` override for this page load, or null when absent/invalid. */
export function forcedThemeOverride(): WorkerTheme | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = new URLSearchParams(window.location.search).get("theme");
    return raw === "light" || raw === "dark" ? raw : null;
  } catch {
    return null;
  }
}

/** True when the page was opened with `?embed=1` (host supplies the chrome). */
export function isEmbedMode(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return new URLSearchParams(window.location.search).get("embed") === "1";
  } catch {
    return false;
  }
}

function oneOf<T extends string>(value: unknown, options: readonly T[], fallback: T): T {
  return typeof value === "string" && options.includes(value as T) ? value as T : fallback;
}

function asBool(value: unknown, fallback: boolean): boolean {
  if (typeof value === "boolean") return value;
  if (value === "true" || value === "1") return true;
  if (value === "false" || value === "0") return false;
  return fallback;
}

function normaliseAppearance(value: Partial<Appearance> | undefined): Appearance {
  return {
    theme: oneOf(value?.theme, ["system", "dark", "light"], DEFAULT_APPEARANCE.theme),
    density: oneOf(
      value?.density,
      ["comfortable", "compact"],
      DEFAULT_APPEARANCE.density,
    ),
    fontScale: oneOf(
      value?.fontScale,
      ["0.9", "1", "1.1", "1.25"],
      DEFAULT_APPEARANCE.fontScale,
    ),
    reducedMotion: asBool(value?.reducedMotion, DEFAULT_APPEARANCE.reducedMotion),
    highContrast: asBool(value?.highContrast, DEFAULT_APPEARANCE.highContrast),
  };
}

export function appearanceFromSettings(
  settings: Record<string, unknown> | undefined,
): Appearance {
  const source = settings ?? {};
  return normaliseAppearance({
    theme: source[APPEARANCE_KEYS.theme] as ThemePreference,
    density: source[APPEARANCE_KEYS.density] as AppearanceDensity,
    fontScale: source[APPEARANCE_KEYS.fontScale] as FontScale,
    reducedMotion: asBool(
      source[APPEARANCE_KEYS.reducedMotion],
      DEFAULT_APPEARANCE.reducedMotion,
    ),
    highContrast: asBool(
      source[APPEARANCE_KEYS.highContrast],
      DEFAULT_APPEARANCE.highContrast,
    ),
  });
}

export function appearanceToSettings(appearance: Appearance): Record<string, unknown> {
  const value = normaliseAppearance(appearance);
  return {
    [APPEARANCE_KEYS.theme]: value.theme,
    [APPEARANCE_KEYS.density]: value.density,
    [APPEARANCE_KEYS.fontScale]: value.fontScale,
    [APPEARANCE_KEYS.reducedMotion]: value.reducedMotion,
    [APPEARANCE_KEYS.highContrast]: value.highContrast,
  };
}

export function loadAppearance(): Appearance {
  try {
    const stored = localStorage.getItem(APPEARANCE_STORAGE_KEY);
    if (stored) return normaliseAppearance(JSON.parse(stored) as Partial<Appearance>);
    const legacyTheme = localStorage.getItem(LEGACY_THEME_KEY);
    return normaliseAppearance({ theme: legacyTheme as ThemePreference });
  } catch {
    return { ...DEFAULT_APPEARANCE };
  }
}

function resolvedTheme(preference: ThemePreference): WorkerTheme {
  if (preference !== "system") return preference;
  try {
    return matchMedia(DARK_QUERY).matches ? "dark" : "light";
  } catch {
    // matchMedia is unavailable, so "follow the system" has no system to
    // follow. Fall back to the product default rather than a second hardcoded
    // "light" that would quietly disagree with it.
    return DEFAULT_APPEARANCE.theme === "light" ? "light" : "dark";
  }
}

function installSystemThemeListener(): void {
  if (systemThemeQuery || typeof matchMedia !== "function") return;
  systemThemeQuery = matchMedia(DARK_QUERY);
  const update = () => {
    const appearance = currentAppearance ?? loadAppearance();
    if (appearance.theme === "system") applyAppearance(appearance);
  };
  if (typeof systemThemeQuery.addEventListener === "function") {
    systemThemeQuery.addEventListener("change", update);
  } else {
    systemThemeQuery.addListener?.(update);
  }
}

// Apply every supported axis to <html>. data-theme carries the effective
// light/dark palette because the current console token layer is resolved;
// data-theme-preference retains whether that palette follows the system.
// A `?theme=` page override clamps ONLY the effective palette here - the
// preference attr, localStorage and the kernel settings all keep the saved
// value, so the override survives the server-settings re-apply and the
// system-theme listener without touching either persistence path.
export function applyAppearance(appearance: Appearance): Appearance {
  const value = normaliseAppearance(appearance);
  currentAppearance = value;
  if (typeof document === "undefined") return value;
  const root = document.documentElement;
  root.dataset.theme = forcedThemeOverride() ?? resolvedTheme(value.theme);
  root.dataset.themePreference = value.theme;
  if (isEmbedMode()) root.dataset.embed = "";
  else delete root.dataset.embed;
  root.dataset.density = value.density;
  root.dataset.contrast = value.highContrast ? "high" : "normal";
  root.style.setProperty("--font-scale", value.fontScale);
  root.classList.toggle("reduce-motion", value.reducedMotion);
  document.dispatchEvent(new CustomEvent(APPEARANCE_CHANGE_EVENT, { detail: value }));
  return value;
}

export function saveAppearanceLocal(appearance: Appearance): Appearance {
  const value = normaliseAppearance(appearance);
  try {
    localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify(value));
    localStorage.setItem(LEGACY_THEME_KEY, value.theme);
  } catch {
    // Storage can be unavailable in hardened contexts. Applying the setting
    // for this session is still useful, and the kernel remains authoritative.
  }
  installSystemThemeListener();
  return applyAppearance(value);
}

export function bootstrapAppearance(): Appearance {
  installSystemThemeListener();
  return applyAppearance(loadAppearance());
}

export function setThemePreference(theme: ThemePreference): WorkerTheme {
  saveAppearanceLocal({ ...loadAppearance(), theme });
  return appliedTheme();
}

export function appliedTheme(): WorkerTheme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function toggleTheme(): WorkerTheme {
  return setThemePreference(appliedTheme() === "dark" ? "light" : "dark");
}
