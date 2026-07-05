// Settings / Account & Profile: identity (read-only, from the IdP) plus the
// caller's own display name / locale / timezone preferences (SET-10).
// AccountProfile is now a thin orchestrator: the state lives in
// useAccountProfile and the identity card + preferences form each render
// through their own sub-component in accountSlide/.

import { PageIntro } from "../ux";
import { IdentityCard } from "./accountSlide/IdentityCard";
import { PreferencesForm } from "./accountSlide/PreferencesForm";
import { useAccountProfile } from "./accountSlide/useAccountProfile";

function AccountProfile() {
  const s = useAccountProfile();

  return (
    <div className="cols">
      <IdentityCard s={s} />
      <PreferencesForm s={s} />
    </div>
  );
}

export function AccountSlide() {
  return (
    <section className="panel">
      <PageIntro title="Account & Profile" lead="Name, locale and timezone." />
      <AccountProfile />
    </section>
  );
}
