import { Field, Select } from "@/panels/ux";

import type { AccountProfileState } from "./useAccountProfile";

export function PreferencesForm({ s }: { s: AccountProfileState }) {
  return (
    <div className="form">
      <div className="form__title">Preferences</div>
      <p className="muted">
        A preferred display name and your locale / timezone. These are your own
        per-user settings (SET-10).
      </p>
      <Field label="Display name" hint="A preferred name shown in the app.">
        <input
          value={s.displayName}
          onChange={(e) => s.setDisplayName(e.target.value)}
        />
      </Field>
      <div className="form__grid">
        <Field label="Locale" hint="Defaults from your browser.">
          <Select
            value={s.locale}
            ariaLabel="Locale"
            onChange={s.setLocale}
            options={s.localeOptions}
          />
        </Field>
        <Field label="Timezone" hint="Defaults from your browser.">
          <Select
            value={s.timezone}
            ariaLabel="Timezone"
            onChange={s.setTimezone}
            options={s.timezoneOptions}
          />
        </Field>
      </div>
      <div className="form__actions">
        <button className="btn btn--primary" disabled={s.busy} onClick={s.save}>
          {s.busy ? "..." : "Save preferences"}
        </button>
        {s.msg && <span className="ok">{s.msg}</span>}
        {s.error && <span className="error">{s.error}</span>}
      </div>
    </div>
  );
}
