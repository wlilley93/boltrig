import { BrandMark } from "../BrandMark";
import { BrandWordmark } from "../BrandWordmark";

export function AuthSplash() {
  return (
    <main className="auth-surface">
      <div className="auth-splash" role="status">
        <span className="auth-spinner" />
        <span>Opening Boltrig Worker…</span>
      </div>
    </main>
  );
}

export function DesktopServerMissing() {
  return (
    <AuthCard
      title="No Boltrig server configured"
      lead="This desktop build was packaged without a Boltrig API origin."
    >
      <div className="auth-handoff">
        <p role="alert" className="auth-error">
          Rebuild the desktop app with VITE_API_BASE set to the Boltrig origin
          this install should use. Without it the app can only reach its own
          window, so sign-in, chat and voice have nothing to talk to.
        </p>
      </div>
    </AuthCard>
  );
}

export function AuthCard({
  title,
  lead,
  children,
}: {
  title: string;
  lead: string;
  children: React.ReactNode;
}) {
  return (
    <main className="auth-surface">
      <section className="auth-card">
        {/* Mark AND wordmark, on every auth surface. AuthCard is the single
            seam all of them pass through -- sign-in, the 2FA prompt and its
            setup, both password resets, invite acceptance, the desktop bridge
            -- so putting it here is what stops one of the nine growing a
            different header from the other eight.

            NOT BrandLockup, deliberately. That component's contract is the two
            ONBOARDING headers, which must stay identical to each other; widening
            it to a third surface with its own chrome is a design decision to
            take on its own, not a side effect of putting a logo on a login box.
            The sizing here is the lockup's, in em, so the two already match. */}
        <div className="auth-brand">
          <BrandMark className="auth-mark" />
          <BrandWordmark />
        </div>
        <p className="eyebrow">Your workspace</p>
        <h1>{title}</h1>
        <p className="auth-lead">{lead}</p>
        {children}
      </section>
    </main>
  );
}
