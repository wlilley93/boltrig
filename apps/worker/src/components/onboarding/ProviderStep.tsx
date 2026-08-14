import type { UserProfile } from "@wlilley93/boltrig-web-sdk";

import { useProviderSetup } from "./useProviderSetup";

export function ProviderStep({ profile }: { profile: UserProfile }) {
  const setup = useProviderSetup(profile);
  const modelReady = Boolean(setup.readiness?.models?.default_available);
  const defaultName = setup.readiness?.models?.default_model_name
    ?? "the configured default model";

  return (
    <div className="onboarding-step provider-step">
      <div className="onboarding-heading onboarding-rise">
        <p className="onboarding-kicker">Connect intelligence</p>
        <h1>Bring the model you trust</h1>
        <p>Boltrig keeps provider credentials server-side and write-only. You can also use a model your workspace already provides.</p>
      </div>
      <ReadinessCard ready={modelReady} defaultName={defaultName} />
      {!setup.readiness
        ? <ProviderLoading />
        : setup.canAddKey
          ? <ProviderKeyForm setup={setup} />
          : <ManagedKeyNotice />}
      {setup.readiness?.keyCount ? (
        <p className="onboarding-status">
          {setup.readiness.keyCount} provider {setup.readiness.keyCount === 1 ? "key" : "keys"} already configured.
        </p>
      ) : null}
      {setup.message && <p className="onboarding-status" role="status">{setup.message}</p>}
    </div>
  );
}

function ReadinessCard({ ready, defaultName }: { ready: boolean; defaultName: string }) {
  return (
    <div className={`readiness-card onboarding-rise ${ready ? "ready" : "quiet"}`} style={{ "--onboarding-delay": "80ms" } as React.CSSProperties}>
      <span className="readiness-icon" aria-hidden="true">{ready ? "✓" : "◇"}</span>
      <span>
        <strong>{ready ? "Workspace AI is ready" : "No workspace model is ready yet"}</strong>
        <small>{ready
          ? `Automatic will use ${defaultName}.`
          : "You can continue. An administrator can connect a Bifrost model route later."}</small>
      </span>
    </div>
  );
}

function ProviderKeyForm({ setup }: { setup: ReturnType<typeof useProviderSetup> }) {
  return (
    <form className="onboarding-key-form onboarding-rise" onSubmit={(event) => void setup.saveKey(event)} style={{ "--onboarding-delay": "160ms" } as React.CSSProperties}>
      <div className="onboarding-form-intro"><strong>Add a direct provider key</strong><span>Optional · sealed before approval</span></div>
      <div className="onboarding-provider-row">
        <label><span>Provider</span><select value={setup.provider} onChange={(event) => setup.setProvider(event.target.value)}><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="google">Google</option><option value="xai">xAI</option><option value="openrouter">OpenRouter</option></select></label>
        <label><span>Exact model</span><input autoComplete="off" onChange={(event) => setup.setModel(event.target.value)} placeholder="provider/model-name" required value={setup.model} /></label>
      </div>
      <label><span>API key <em>write only</em></span><input aria-label="Provider API key" autoComplete="off" ref={setup.apiKeyInput} required type="password" /></label>
      <details>
        <summary>Custom API origin</summary>
        <label><span>Base URL</span><input inputMode="url" onChange={(event) => setup.setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" value={setup.baseUrl} /></label>
      </details>
      <button className="onboarding-secondary" disabled={setup.busy || !setup.model.trim()} type="submit">{setup.busy ? "Sealing…" : "Seal provider key"}</button>
      <p className="onboarding-key-note">A direct key does not configure Bifrost by itself. Voice providers are connected later in Settings → Models.</p>
    </form>
  );
}

function ManagedKeyNotice() {
  return (
    <div className="readiness-card quiet onboarding-rise" style={{ "--onboarding-delay": "160ms" } as React.CSSProperties}>
      <span className="readiness-icon" aria-hidden="true">↗</span>
      <span><strong>Your organisation manages provider keys</strong><small>Ask an administrator to allow personal keys or connect a workspace model route.</small></span>
    </div>
  );
}

function ProviderLoading() {
  return (
    <div className="readiness-card quiet onboarding-rise" aria-busy="true" style={{ "--onboarding-delay": "160ms" } as React.CSSProperties}>
      <span className="readiness-icon" aria-hidden="true">···</span>
      <span><strong>Checking key policy</strong><small>Boltrig is reading the workspace's safe configuration metadata.</small></span>
    </div>
  );
}
