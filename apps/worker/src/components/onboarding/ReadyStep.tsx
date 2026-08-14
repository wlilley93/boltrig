import type { CharacterId } from "../../character";

export function ReadyStep({ character, userName }: { character: CharacterId; userName: string }) {
  const name = character === "jarvis" ? "Jarvis" : "Familiar";
  return (
    <div className="onboarding-step ready-step">
      <div className="ready-mark onboarding-rise" aria-hidden="true"><span>✓</span></div>
      <div className="onboarding-heading onboarding-rise" style={{ "--onboarding-delay": "80ms" } as React.CSSProperties}>
        <p className="onboarding-kicker">You are ready</p>
        <h1>You’re ready, {userName}. Meet {name}.</h1>
        <p>Your companion is selected and your workspace checks are complete. Models, voice and provider routes remain editable in Settings.</p>
      </div>
      <div className="ready-list onboarding-rise" style={{ "--onboarding-delay": "160ms" } as React.CSSProperties}>
        <span><i>1</i><b>{name}</b><small>Selected companion</small></span>
        <span><i>2</i><b>Governed by default</b><small>Approvals stay under workspace policy</small></span>
        <span><i>3</i><b>Private credentials</b><small>Provider keys remain server-side and write-only</small></span>
      </div>
    </div>
  );
}
