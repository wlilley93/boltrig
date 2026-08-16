import { useEffect, useState } from "react";
import type { MeSettingsResponse } from "@wlilley93/boltrig-web-sdk";

import { configuredApiOrigin } from "../apiOrigin";
import { characterFromSettings, saveCharacterLocal } from "../character";
import { client, rememberSessionCsrf } from "../client";
import { isDesktop } from "../desktop";
import {
  ChallengeScreen,
  EnrollmentRequiredScreen,
  PasswordChangeScreen,
} from "./auth/AccountRequirementScreens";
import { AcceptInviteScreen } from "./auth/AcceptInviteScreen";
import { AuthSplash, DesktopServerMissing } from "./auth/AuthShell";
import { DesktopAccountBridge } from "./auth/DesktopAccountBridge";
import { LoginScreen } from "./auth/LoginScreen";
import { OnboardingGate } from "./onboarding/OnboardingGate";
import { RequestPasswordResetScreen, ResetPasswordScreen } from "./auth/RecoveryScreens";
import {
  acceptingInviteFromHash,
  detailOf,
  recoveryFlowFromHash,
} from "./auth/routing";
import type { GateState, RecoveryFlow } from "./auth/types";
import { BoltrigApiError } from "@wlilley93/boltrig-web-sdk";

function useAuthRoute() {
  const [recoveryFlow, setRecoveryFlow] = useState<RecoveryFlow>(recoveryFlowFromHash);
  const [acceptingInvite, setAcceptingInvite] = useState(acceptingInviteFromHash);

  useEffect(() => {
    const onHashChange = () => {
      setRecoveryFlow(recoveryFlowFromHash());
      setAcceptingInvite(acceptingInviteFromHash());
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return { acceptingInvite, recoveryFlow, setAcceptingInvite, setRecoveryFlow };
}

function useAuthenticatedSession(acceptingInvite: boolean, recoveryFlow: RecoveryFlow) {
  const [state, setState] = useState<GateState>("checking");
  const [account, setAccount] = useState<MeSettingsResponse | null>(null);

  useEffect(() => {
    if (acceptingInvite || recoveryFlow !== "none") return;
    void client.meSettings()
      .then(async (result) => {
        if (isDesktop) {
          const csrf = await client.sessionCsrf();
          if (!csrf.csrf_token) throw new Error("desktop_session_csrf_unavailable");
          rememberSessionCsrf(csrf.csrf_token);
        }
        // Apply the authoritative character before private UI can mount.
        saveCharacterLocal(characterFromSettings(result.settings));
        setAccount(result);
        setState("authenticated");
      })
      .catch(async (reason) => {
        if (reason instanceof BoltrigApiError && reason.status === 403) {
          const detail = detailOf(reason.body);
          if (
            isDesktop
            && (detail === "password_change_required"
              || detail === "two_factor_enrollment_required")
          ) {
            try {
              const csrf = await client.sessionCsrf();
              if (!csrf.csrf_token) throw new Error("desktop_session_csrf_unavailable");
              rememberSessionCsrf(csrf.csrf_token);
            } catch {
              setState("unauthenticated");
              return;
            }
          }
          if (detail === "password_change_required") return setState("password_change_required");
          if (detail === "two_factor_enrollment_required") return setState("enrollment_required");
        }
        setState("unauthenticated");
      });
  }, [acceptingInvite, recoveryFlow]);

  useEffect(() => {
    if (state !== "authenticated") return;
    let active = true;
    const rotate = () => {
      void client.refreshSession()
        .then((result) => {
          if (result.csrf_token) rememberSessionCsrf(result.csrf_token);
        })
        .catch((reason) => {
          if (active && reason instanceof BoltrigApiError && reason.status === 401) {
            // Re-resolve after a possible shared-cookie rotation in another tab.
            void client.meSettings().catch((check) => {
              if (active && check instanceof BoltrigApiError && check.status === 401) {
                setState("unauthenticated");
              }
            });
          }
        });
    };
    const timer = window.setInterval(rotate, 4 * 60 * 60 * 1000);
    const onVisibility = () => {
      if (document.visibilityState === "visible") rotate();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [state]);

  return { account, state, setState };
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const route = useAuthRoute();
  const { account, state, setState } = useAuthenticatedSession(
    route.acceptingInvite,
    route.recoveryFlow,
  );
  const [challenge, setChallenge] = useState<string | null>(null);
  const [recoveryEmail, setRecoveryEmail] = useState("");

  const backToSignIn = () => {
    window.location.hash = "#/chat";
    route.setRecoveryFlow("none");
    route.setAcceptingInvite(false);
    setState("unauthenticated");
  };

  // A desktop without an API origin must fail closed before offering sign-in.
  if (isDesktop && !configuredApiOrigin()) return <DesktopServerMissing />;
  if (route.acceptingInvite) return <AcceptInviteScreen onDone={backToSignIn} />;
  if (route.recoveryFlow === "request") {
    return <RequestPasswordResetScreen initialEmail={recoveryEmail} onDone={backToSignIn} />;
  }
  if (route.recoveryFlow === "confirm") return <ResetPasswordScreen onDone={backToSignIn} />;
  if (state === "checking") return <AuthSplash />;
  if (state === "password_change_required") {
    return <PasswordChangeScreen onDone={() => setState("authenticated")} />;
  }
  if (state === "enrollment_required") {
    return <EnrollmentRequiredScreen onDone={() => setState("authenticated")} />;
  }
  if (state === "unauthenticated") {
    return challenge
      ? <ChallengeScreen
          token={challenge}
          onBack={() => setChallenge(null)}
          onDone={() => setState("authenticated")}
        />
      : <LoginScreen
          onChallenge={setChallenge}
          onState={setState}
          onForgot={(email) => {
            setRecoveryEmail(email);
            window.location.hash = "#/forgot-password";
            route.setRecoveryFlow("request");
          }}
        />;
  }
  return (
    <OnboardingGate initialAccount={account}>
      <DesktopAccountBridge>{children}</DesktopAccountBridge>
    </OnboardingGate>
  );
}
