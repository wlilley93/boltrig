// Appearance + accessibility preferences (theme, density, font scale, reduced
// motion, high contrast). These persist server-side as per-user settings, but we
// also mirror them to localStorage so the choice is applied instantly on load
// (no server round-trip, no flash of the wrong theme). applyAppearance writes
// data-* attributes / a CSS variable / a class onto <html> that styles.css keys
// off. The server-setting keys match the kernel (SET-*): "theme", "density",
// "font_scale", "a11y.reduced_motion", "a11y.high_contrast".

export interface Appearance {
  theme: string; // "light" | "dark" | "system"
  density: string; // "comfortable" | "compact"
  fontScale: string; // "0.9" | "1" | "1.1" | "1.25" (string so it binds to a <select>)
  reducedMotion: boolean;
  highContrast: boolean;
}

// The per-user setting keys that back each field.
export const APPEARANCE_KEYS = {
  theme: "theme",
  density: "density",
  fontScale: "font_scale",
  reducedMotion: "a11y.reduced_motion",
  highContrast: "a11y.high_contrast",
} as const;

export const DEFAULT_APPEARANCE: Appearance = {
  theme: "dark",
  density: "comfortable",
  fontScale: "1",
  reducedMotion: false,
  highContrast: false,
};

const STORAGE_KEY = "boltrig.appearance";

function asBool(value: unknown, fallback: boolean): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "string") return value === "true" || value === "1";
  return fallback;
}

function asStr(value: unknown, fallback: string): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

// Build an Appearance from a server settings map (tolerant of missing keys).
export function appearanceFromSettings(
  settings: Record<string, unknown> | undefined,
): Appearance {
  const s = settings ?? {};
  return {
    theme: asStr(s[APPEARANCE_KEYS.theme], DEFAULT_APPEARANCE.theme),
    density: asStr(s[APPEARANCE_KEYS.density], DEFAULT_APPEARANCE.density),
    fontScale: asStr(s[APPEARANCE_KEYS.fontScale], DEFAULT_APPEARANCE.fontScale),
    reducedMotion: asBool(
      s[APPEARANCE_KEYS.reducedMotion],
      DEFAULT_APPEARANCE.reducedMotion,
    ),
    highContrast: asBool(
      s[APPEARANCE_KEYS.highContrast],
      DEFAULT_APPEARANCE.highContrast,
    ),
  };
}

// The settings payload for PUT /v1/me/settings (so server + UI agree).
export function appearanceToSettings(a: Appearance): Record<string, unknown> {
  return {
    [APPEARANCE_KEYS.theme]: a.theme,
    [APPEARANCE_KEYS.density]: a.density,
    [APPEARANCE_KEYS.fontScale]: a.fontScale,
    [APPEARANCE_KEYS.reducedMotion]: a.reducedMotion,
    [APPEARANCE_KEYS.highContrast]: a.highContrast,
  };
}

export function loadAppearance(): Appearance {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_APPEARANCE };
    const parsed = JSON.parse(raw) as Partial<Appearance>;
    return { ...DEFAULT_APPEARANCE, ...parsed };
  } catch {
    return { ...DEFAULT_APPEARANCE };
  }
}

// Write the data-* attributes / variable / class the stylesheet reacts to.
export function applyAppearance(a: Appearance): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.dataset.theme = a.theme;
  root.dataset.density = a.density;
  root.dataset.contrast = a.highContrast ? "high" : "normal";
  root.style.setProperty("--font-scale", a.fontScale || "1");
  root.classList.toggle("reduce-motion", a.reducedMotion);
}

// Persist to localStorage (the instant-apply mirror) and apply immediately.
export function saveAppearanceLocal(a: Appearance): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(a));
  } catch {
    // ignore persistence failures (private mode, quota, etc.)
  }
  applyAppearance(a);
}
