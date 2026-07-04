import type { ReactNode } from "react";

import { InfoCallout } from "./InfoCallout";

// --- Error / denied: show the server's reason faithfully, offer a retry ----
export function ErrorState({
  reason,
  onRetry,
}: {
  reason: ReactNode;
  onRetry?: () => void;
}) {
  return (
    <div className="ux-error" role="alert">
      <span className="ux-error__msg">{reason}</span>
      {onRetry && (
        <button type="button" className="btn btn--sm" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

// A failure from useFetch, rendered by KIND: a 403 reads as a calm "you don't
// have access" notice, a network failure as "can't reach the server" with a
// retry, and only a real server bug as a red alert. Returns null when there is
// no error, so a panel can drop it straight in.
export function FetchError({
  error,
  status,
  onRetry,
}: {
  error: string | null;
  status?: number | null;
  onRetry?: () => void;
}) {
  if (!error) return null;
  if (status === 403) {
    return <InfoCallout tone="warn">{error} Ask an admin to widen your access.</InfoCallout>;
  }
  if (status === 0) {
    return (
      <div className="ux-error" role="alert">
        <span className="ux-error__msg">{error}</span>
        {onRetry && (
          <button type="button" className="btn btn--sm" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    );
  }
  return (
    <div className="ux-error" role="alert">
      <span className="ux-error__msg">{error}</span>
      {onRetry && (
        <button type="button" className="btn btn--sm" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
