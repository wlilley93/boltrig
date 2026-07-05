import { useEffect, useState } from "react";

import { api } from "@/api/client";
import type { MeSettingsResponse } from "@/api/types";
import { errText } from "@/panels/shared";
import type { Option } from "@/panels/ux";
import { useFetch, type FetchState } from "@/useFetch";

// Sensible defaults from the browser so locale / timezone are never blank
// free-text (SET-10). The Select always includes the detected value + any value
// the server already holds, so nothing the user has set is ever lost.
const BROWSER_TZ =
  Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const BROWSER_LOCALE =
  (typeof navigator !== "undefined" && navigator.language) || "en-US";

const COMMON_TIMEZONES: ReadonlyArray<string> = [
  "UTC",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
];

const COMMON_LOCALES: ReadonlyArray<string> = [
  "en-GB",
  "en-US",
  "fr-FR",
  "de-DE",
  "es-ES",
  "it-IT",
  "pt-BR",
  "nl-NL",
  "ja-JP",
  "zh-CN",
];

// Build Select options from a common list, guaranteeing the detected + current
// values are present and first (a stored value outside the list is never lost).
function withPreferred(
  list: ReadonlyArray<string>,
  ...preferred: string[]
): Option[] {
  const seen = new Set<string>();
  const out: Option[] = [];
  for (const v of [...preferred, ...list]) {
    if (!v || seen.has(v)) continue;
    seen.add(v);
    out.push({ value: v, label: v });
  }
  return out;
}

export interface AccountProfileState {
  settings: FetchState<MeSettingsResponse>;
  displayName: string;
  setDisplayName: (v: string) => void;
  locale: string;
  setLocale: (v: string) => void;
  timezone: string;
  setTimezone: (v: string) => void;
  localeOptions: Option[];
  timezoneOptions: Option[];
  busy: boolean;
  msg: string | null;
  error: string | null;
  save: () => Promise<void>;
}

export function useAccountProfile(): AccountProfileState {
  const settings = useFetch(() => api.meSettings(), []);

  const [displayName, setDisplayName] = useState("");
  const [locale, setLocale] = useState("");
  const [timezone, setTimezone] = useState("");
  const [seeded, setSeeded] = useState(false);

  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (settings.data && !seeded) {
      const s = settings.data.settings ?? {};
      setDisplayName(
        String(s["display_name"] ?? settings.data.profile.display_name ?? ""),
      );
      // Default locale / timezone from the browser when the server holds none.
      setLocale(String(s["locale"] ?? "") || BROWSER_LOCALE);
      setTimezone(String(s["timezone"] ?? "") || BROWSER_TZ);
      setSeeded(true);
    }
  }, [settings.data, seeded]);

  const localeOptions = withPreferred(COMMON_LOCALES, BROWSER_LOCALE, locale);
  const timezoneOptions = withPreferred(COMMON_TIMEZONES, BROWSER_TZ, timezone);

  async function save() {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      const res = await api.putMeSettings({
        settings: {
          display_name: displayName.trim(),
          locale: locale.trim(),
          timezone: timezone.trim(),
        },
      });
      if (res.status === "ok") {
        setMsg("Profile preferences saved.");
        settings.reload();
      } else {
        setError(res.reason ?? "save rejected");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return {
    settings, displayName, setDisplayName, locale, setLocale, timezone,
    setTimezone, localeOptions, timezoneOptions, busy, msg, error, save,
  };
}
