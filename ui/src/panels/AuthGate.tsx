// The first-party auth gate (COUNTY 7). When auth_mode=session and there is no
// session, this stands in front of the whole console: it is the sole
// internet-facing gate that replaces Cloudflare Access. Under the dev header
// resolver (and the e2e smoke) the probe resolves to a principal, so the gate
// never appears and the children render straight through - see auth.ts for the
// deliberate 401-only guard.
//
// Two public pages live here (neither needs a session): the login form, and the
// accept-invite page reached by an invite link carrying a single-use token
// (#/accept-invite?token=...). Everything else is gated behind a live session.

import { useEffect } from "react";
import type { ReactNode } from "react";

import { probeSession, useAuth } from "@/auth";
import { AcceptInvitePage } from "@/panels/AuthGate/AcceptInvitePage";
import { EnrollFlow } from "@/panels/AuthGate/EnrollFlow";
import { LoginPage } from "@/panels/AuthGate/LoginPage";
import { useRoute } from "@/router";

// Wrap the app. Renders the public accept-invite page for its route, the login
// gate when session auth is active and unauthenticated, or the console.
export function AuthGate({ children }: { children: ReactNode }) {
  const route = useRoute();
  const { status } = useAuth();

  // The accept-invite page is public (the token is the bearer of authority) and
  // must render whether or not a session exists, so it is handled before the
  // session probe.
  const isAcceptInvite = route.tab === "accept-invite";

  useEffect(() => {
    if (!isAcceptInvite && status === "checking") void probeSession();
  }, [isAcceptInvite, status]);

  if (isAcceptInvite) return <AcceptInvitePage />;
  if (status === "checking") {
    return (
      <div className="auth-gate">
        <div className="auth-splash" role="status" aria-live="polite">
          <span className="auth-splash__spinner" aria-hidden="true" />
          <span className="auth-splash__text">Loading...</span>
        </div>
      </div>
    );
  }
  if (status === "unauthenticated") return <LoginPage />;
  if (status === "enroll_required") return <EnrollFlow />;
  return <>{children}</>;
}
