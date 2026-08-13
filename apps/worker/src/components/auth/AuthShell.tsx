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
        <div className="auth-brand">
          <span className="bolt-mark">ϟ</span>
          <span>Boltrig Worker</span>
        </div>
        <p className="eyebrow">Governed workspace</p>
        <h1>{title}</h1>
        <p className="auth-lead">{lead}</p>
        {children}
      </section>
    </main>
  );
}
