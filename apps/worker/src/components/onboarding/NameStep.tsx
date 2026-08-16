export function NameStep({
  name,
  onName,
}: {
  name: string;
  onName: (value: string) => void;
}) {
  return (
    <div className="onboarding-step name-step">
      <div className="onboarding-heading onboarding-rise">
        <p className="onboarding-kicker">First things first</p>
        <h1>What should Boltrig call you?</h1>
        <p>We’ll use this to make Boltrig feel personal.</p>
      </div>
      <label
        className="onboarding-name onboarding-rise"
        style={{ "--onboarding-delay": "90ms" } as React.CSSProperties}
      >
        <span>Your name</span>
        <input
          autoComplete="name"
          autoFocus
          maxLength={80}
          onChange={(event) => onName(event.target.value)}
          placeholder="Your name"
          required
          value={name}
        />
      </label>
    </div>
  );
}
