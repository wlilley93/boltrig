import type { StatusAck } from "../../api/types";

// Shared rendering of a {status, reason} acknowledgement.
export function AckLine({ ack }: { ack: StatusAck | null }) {
  if (!ack) return null;
  if (ack.status === "ok") {
    const parts = [ack.id, ack.version ? `v${ack.version}` : null].filter(
      Boolean,
    );
    return <p className="ok">Saved {parts.join(" ") || "ok"}.</p>;
  }
  return (
    <p className="error">
      {ack.status}: {ack.reason ?? "request rejected"}
    </p>
  );
}
