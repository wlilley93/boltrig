// Channels management (decision 0003, Beat 5 retrofit): the admin surface for
// the webhook / request-response channel class. The backend has full CRUD and
// had zero UI - this is that UI. Every call is admin-gated server-side (a 403
// renders as a denial); the register primitives carry the interaction:
//   - SecretOnce for the minted one-time pairing code (shown once, never again).
//   - ArmConfirm for disconnect and for removing a binding (destructive).
//   - SegmentedV2 for the small closed choices (platform, unpaired behaviour,
//     channel role tier).
// The signing secret and pairing code are the only secret material; the secret
// is write-only (kernel-side, SEC-05) and the code is show-once.

import { api } from "../api/client";
import type { ChannelSummary } from "../api/types";
import { useFetch } from "../useFetch";
import { useIdentity } from "../identity";
import { Skeleton } from "./uxFlow";
import { EmptyState, FetchError, PageIntro } from "./ux";
import { ADMIN_ROLES } from "./channels/options";
import { ChannelRow } from "./channels/ChannelRow";
import { ConnectForm } from "./channels/ConnectForm";

export function ChannelsPanel() {
  const identity = useIdentity();
  const isAdmin = ADMIN_ROLES.has(identity.role);
  const channels = useFetch(() => api.channels(), []);

  const denied =
    channels.data && channels.data.channels === undefined
      ? channels.data.reason ?? "channel administration not permitted"
      : null;
  const list: ChannelSummary[] = channels.data?.channels ?? [];

  return (
    <section className="panel">
      <PageIntro
        title="Channels"
        lead="Connect signed inbound message channels and manage who they map to."
        how="A channel turns a signed webhook into governed work. Connect one, bind or pair its senders to internal identities, and disconnect it when it is no longer needed."
        actions={
          <button className="btn" onClick={() => channels.reload()}>
            Refresh
          </button>
        }
      />

      {!isAdmin && (
        <p className="notice warn">
          Channel administration is intended for org-admin. This identity (role:{" "}
          <code>{identity.role}</code>) may be rejected by the server with 403.
        </p>
      )}

      <div className="list-card">
        <div className="list-card__head">
          <h3>Channels</h3>
        </div>
        <div className="list-card__body">
          {channels.loading && !channels.data && <Skeleton variant="rows" />}
          <FetchError
            error={channels.error}
            status={channels.errorStatus}
            onRetry={channels.reload}
          />
          {denied && <p className="notice warn">denied: {denied}</p>}
          {!denied && channels.data && list.length === 0 && (
            <EmptyState
              title="No channels"
              body="Connect a webhook channel below to start accepting signed inbound messages."
            />
          )}
          {list.map((c) => (
            <ChannelRow key={c.id} channel={c} onChanged={() => channels.reload()} />
          ))}
        </div>
      </div>

      <ConnectForm onConnected={() => channels.reload()} />
    </section>
  );
}
