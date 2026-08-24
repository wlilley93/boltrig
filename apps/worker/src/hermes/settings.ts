import type {
  ChatConfigResponse,
  ChatModelChoicesResponse,
  MeSettingsResponse,
  PutSettingsRequest,
  PutSettingsResponse,
} from "@wlilley93/boltrig-web-sdk";

import { ONBOARDING_SETTING_KEY, ONBOARDING_VERSION } from "../onboarding";
import { cellJson, planeJson, planePost } from "./http";

/** Identity and preferences, which live on the CONTROL PLANE, not in the cell.
 *
 *  AuthGate gates the whole application on `meSettings()` returning 200, so
 *  everything here is on the path that decides whether anything renders at all.
 */

interface MeResponse {
  user?: { id?: string; email?: string; display_name?: string };
  tenant_gateway_id?: string | null;
  gateways?: { gateway_id?: string; character?: string | null }[];
}

export async function meSettings(): Promise<MeSettingsResponse> {
  const [me, stored] = await Promise.all([
    planeJson<MeResponse>("/api/me"),
    // Settings are a convenience, not a precondition: a control plane that has
    // not grown the endpoint yet, or a user with nothing stored, must still be
    // able to sign in. Failing closed here would lock everyone out over a
    // preference.
    planeJson<{ settings?: Record<string, unknown> }>("/api/settings")
      .catch(() => ({ settings: {} as Record<string, unknown> })),
  ]);

  return {
    profile: {
      id: me.user?.id ?? "",
      email: me.user?.email ?? null,
      display_name: me.user?.display_name ?? null,
    },
    settings: {
      ...(stored.settings ?? {}),
      // ONBOARDING IS ALREADY DONE. The control plane ran its own wizard before
      // this bundle was ever served - it is what created the workspace and the
      // cell. Without this key OnboardingGate puts every signed-in person back
      // through v1's six-step provider wizard, which would configure nothing
      // and could not be completed.
      [ONBOARDING_SETTING_KEY]: ONBOARDING_VERSION,
    },
  };
}

export async function putMeSettings(body: PutSettingsRequest): Promise<PutSettingsResponse> {
  // The SDK sends either a whole `settings` map or a single `key`/`value`.
  // Normalised here so the server has one shape to store and one to bound.
  const settings = body.settings
    ?? (body.key ? { [body.key]: body.value } : {});
  const result = await planePost<{ settings?: Record<string, unknown> }>(
    "/api/settings", { settings },
  );
  return { status: "ok", keys: Object.keys(result.settings ?? settings) };
}

/** AuthGate rotates on an interval and on tab focus, and treats 401 as signed
 *  out. The control plane's cookie renews itself, so there is nothing to
 *  rotate - but a no-op that always resolves would report a DEAD session as
 *  live, and the person would sit in a shell whose every call 401s.
 *
 *  So this actually asks. `/api/me` is the cheapest authenticated read there
 *  is; a 401 propagates and AuthGate does the right thing with it. */
export async function refreshSession(): Promise<{ status: string; csrf_token?: string }> {
  await planeJson<unknown>("/api/me");
  return { status: "ok" };
}

export async function chatModelChoices(): Promise<ChatModelChoicesResponse> {
  try {
    const options = await cellJson<{ models?: { id?: string; name?: string }[] }>(
      "/api/model/options",
    );
    const choices = (options.models ?? []).map((model, index) => ({
      id: String(model.id ?? model.name ?? ""),
      model_name: String(model.name ?? model.id ?? ""),
      available: true,
      // Hermes serves one configured model; the first entry is the default
      // rather than nothing being default, which renders as an empty picker.
      is_default: index === 0,
      modalities: ["text"],
    }));
    return { status: "ok", reason: null, choices };
  } catch (error) {
    // The shape has a status field for exactly this, and the surface renders
    // the reason. Throwing would take out the composer over a model list.
    return {
      status: "unavailable",
      reason: error instanceof Error ? error.message : "model options unavailable",
      choices: [],
    };
  }
}

export async function capabilities(): Promise<unknown> {
  return cellJson("/v1/capabilities");
}

/** The cell's own health, which IS reachable: `/health/detailed` is on the
 *  proxy allowlist. Worth implementing rather than hiding - it is the one
 *  surface that can answer "is my agent actually up" without sending a turn. */
export async function health(): Promise<unknown> {
  return cellJson("/health/detailed");
}

/** Read-only build surfaces, both allowlisted. */
export async function skills(): Promise<unknown> {
  return cellJson("/v1/skills");
}

export async function toolsets(): Promise<unknown> {
  return cellJson("/v1/toolsets");
}

/** Attachment limits for the composer. Hermes exposes none, and the honest
 *  answer is zero rather than a number copied from the kernel: the cell proxy
 *  caps a request body at 64KB and refuses uploads outright, so an attachment
 *  offered here could not be delivered. */
export async function chatConfig(): Promise<ChatConfigResponse> {
  return {
    attachments: { max_files: 0, max_bytes: 0, accepted: [] },
  } as unknown as ChatConfigResponse;
}
