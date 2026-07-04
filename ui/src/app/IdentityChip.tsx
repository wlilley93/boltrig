import { useIdentity } from "@/identity";

interface IdentityChipProps {
  expanded: boolean;
  onToggle: () => void;
}

// The chip that stands in for an always-on dev form: it reads like an identity
// ("Signed in as ...") and expands the editable dev sign-in. In the collapsed
// rail only the avatar initial shows; the text is hidden by CSS.
export function IdentityChip({ expanded, onToggle }: IdentityChipProps) {
  const id = useIdentity();
  const initial = (id.subject || "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <button
      className={`identity-chip ${expanded ? "identity-chip--open" : ""}`}
      aria-expanded={expanded}
      title={`Acting as ${id.subject} (${id.role}) @ ${id.tenant}. Click to change the dev sign-in.`}
      onClick={onToggle}
    >
      <span className="identity-chip__avatar" aria-hidden="true">{initial}</span>
      <span className="identity-chip__who">
        <span className="identity-chip__line">
          <strong>{id.subject}</strong>
          <span className="identity-chip__dev" title="Dev sign-in - you can change who you are acting as">dev</span>
        </span>
        <span className="identity-chip__where">{id.role} @ {id.tenant}</span>
      </span>
    </button>
  );
}
