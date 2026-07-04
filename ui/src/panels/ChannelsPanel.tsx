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

import { useState } from "react";

import { api } from "../api/client";
import type { ChannelBindingSummary, ChannelSummary } from "../api/types";
import { useFetch } from "../useFetch";
import { useIdentity } from "../identity";
import { apiReason, errText } from "./shared";
import { SegmentedV2 } from "./uxForm";
import { ArmConfirm, SecretOnce, Skeleton } from "./uxFlow";
import { EmptyState, Field, FetchError, PageIntro } from "./ux";
import { ADMIN_ROLES } from "./channels/options";
import { ConnectForm } from "./channels/ConnectForm";

const UNPAIRED_OPTIONS = [
  { value: "reject", label: "Reject" },
  { value: "ignore", label: "Ignore" },
  { value: "pair", label: "Pair" },
];

const ROLE_OPTIONS = [
  { value: "member", label: "Member" },
  { value: "admin", label: "Admin" },
  { value: "superadmin", label: "Superadmin" },
];

const ENABLED_OPTIONS = [
  { value: "true", label: "Enabled" },
  { value: "false", label: "Disabled" },
];

function BindingList({ channelId }: { channelId: string }) {
  const bindings = useFetch(() => api.channelBindings(channelId), [channelId]);

  const [ext, setExt] = useState("");
  const [subject, setSubject] = useState("");
  const [role, setRole] = useState("member");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function addBinding() {
    if (!ext.trim() || !subject.trim()) {
      setError("An external user id and a subject are required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.bindChannel(channelId, {
        external_user_id: ext.trim(),
        subject: subject.trim(),
        role,
      });
      if (res.status === "ok") {
        setExt("");
        setSubject("");
        bindings.reload();
      } else {
        setError(res.reason ?? "bind rejected");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function removeBinding(bindingId: string) {
    const res = await api.deleteChannelBinding(channelId, bindingId);
    if (res.status !== "ok") {
      throw new Error(res.reason ?? "remove rejected");
    }
    bindings.reload();
  }

  const denied =
    bindings.data && bindings.data.bindings === undefined
      ? bindings.data.reason ?? "not permitted"
      : null;
  const list: ChannelBindingSummary[] = bindings.data?.bindings ?? [];

  return (
    <div className="stack">
      <div className="list-card">
        <div className="list-card__head">
          <h3>Bindings</h3>
          <button className="btn" onClick={() => bindings.reload()}>
            Refresh
          </button>
        </div>
        <div className="list-card__body">
          {bindings.loading && !bindings.data && <Skeleton variant="rows" />}
          <FetchError
            error={bindings.error}
            status={bindings.errorStatus}
            onRetry={bindings.reload}
          />
          {denied && <p className="notice warn">denied: {denied}</p>}
          {!denied && bindings.data && list.length === 0 && (
            <EmptyState
              title="No bindings"
              body="Bind an external sender to an internal identity below, or issue a pairing code."
            />
          )}
          {list.map((b) => (
            <div className="row-line" key={b.id}>
              <div>
                <code>{b.external_user_id}</code>{" "}
                <span className="muted">-&gt; {b.subject}</span>
                <div className="muted">role: {b.role}</div>
              </div>
              <ArmConfirm
                label="Remove"
                armLabel={
                  <>
                    Remove the binding for <code>{b.external_user_id}</code>?
                    That sender stops resolving to <code>{b.subject}</code>.
                  </>
                }
                confirmLabel="Confirm remove"
                tone="danger"
                busyLabel="Removing..."
                onConfirm={() => removeBinding(b.id)}
              />
            </div>
          ))}
        </div>
      </div>

      <div className="form">
        <div className="form__title">Bind a sender directly</div>
        <p className="muted">
          Map a verified external sender id to an internal identity. You are
          vouching for the mapping (no pairing code is issued).
        </p>
        <div className="form__grid">
          <Field label="External user id">
            <input value={ext} onChange={(e) => setExt(e.target.value)} />
          </Field>
          <Field label="Subject (internal identity)">
            <input value={subject} onChange={(e) => setSubject(e.target.value)} />
          </Field>
          <Field label="Role">
            <SegmentedV2
              value={role}
              ariaLabel="Binding role"
              onChange={setRole}
              options={ROLE_OPTIONS}
            />
          </Field>
        </div>
        <div className="form__actions">
          <button className="btn" disabled={busy} onClick={() => void addBinding()}>
            {busy ? "Binding..." : "Add binding"}
          </button>
          {error && <span className="error">{error}</span>}
        </div>
      </div>
    </div>
  );
}

function PairForm({ channelId }: { channelId: string }) {
  const [ext, setExt] = useState("");
  const [subject, setSubject] = useState("");
  const [role, setRole] = useState("member");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [minted, setMinted] = useState<{ code: string; pairingId: string; role: string } | null>(
    null,
  );

  async function issue() {
    if (!ext.trim() || !subject.trim()) {
      setError("An external user id and a subject are required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.pairChannel(channelId, {
        external_user_id: ext.trim(),
        subject: subject.trim(),
        role,
      });
      if (res.status === "ok" && res.code) {
        setMinted({ code: res.code, pairingId: res.pairing_id ?? "", role });
        setExt("");
        setSubject("");
      } else {
        setError(res.reason ?? "pairing rejected");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  if (minted) {
    return (
      <SecretOnce
        secret={minted.code}
        title="Pairing code"
        body="Give this one-time code to the external user. It is shown only now and expires shortly."
        meta={
          <span className="muted">
            pairing <code>{minted.pairingId}</code> - role {minted.role}
          </span>
        }
        copyLabel="Copy code"
        onDone={() => setMinted(null)}
      />
    );
  }

  return (
    <div className="form">
      <div className="form__title">Issue a pairing code</div>
      <p className="muted">
        Issue a short one-time code an external user sends back to bind their
        sender id to an internal identity. Issuing the code is the human
        authorisation for the bind.
      </p>
      <div className="form__grid">
        <Field label="External user id">
          <input value={ext} onChange={(e) => setExt(e.target.value)} />
        </Field>
        <Field label="Subject (internal identity)">
          <input value={subject} onChange={(e) => setSubject(e.target.value)} />
        </Field>
        <Field label="Role">
          <SegmentedV2
            value={role}
            ariaLabel="Pairing role"
            onChange={setRole}
            options={ROLE_OPTIONS}
          />
        </Field>
      </div>
      <div className="form__actions">
        <button className="btn" disabled={busy} onClick={() => void issue()}>
          {busy ? "Issuing..." : "Issue code"}
        </button>
        {error && <span className="error">{error}</span>}
      </div>
    </div>
  );
}

function ChannelRow({
  channel,
  onChanged,
}: {
  channel: ChannelSummary;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(channel.name);
  const [unpaired, setUnpaired] = useState(channel.unpaired_behavior);
  const [enabled, setEnabled] = useState(channel.enabled ? "true" : "false");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function configure() {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const res = await api.configureChannel(channel.id, {
        name: name.trim() || channel.name,
        unpaired_behavior: unpaired,
        enabled: enabled === "true",
      });
      if (res.status === "ok") {
        setMsg("Saved.");
        onChanged();
      } else {
        setError(res.reason ?? "update rejected");
      }
    } catch (err) {
      setError(apiReason(err));
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    const res = await api.disconnectChannel(channel.id);
    if (res.status !== "ok") {
      throw new Error(res.reason ?? "disconnect rejected");
    }
    onChanged();
  }

  return (
    <div className="dir-row">
      <div className="row-line dir-row__top">
        <div>
          <code>{channel.name}</code>{" "}
          <span className="badge">{channel.platform}</span>{" "}
          <span className="badge">{channel.transport}</span>
          <div className="muted">
            unpaired: {channel.unpaired_behavior} - id <code>{channel.id}</code>
          </div>
        </div>
        <div className="kv">
          <span className={`badge ${channel.enabled ? "badge--ok" : "badge--down"}`}>
            {channel.enabled ? "enabled" : "disabled"}
          </span>
          <button className="btn" onClick={() => setOpen((o) => !o)}>
            {open ? "Close" : "Manage"}
          </button>
          <ArmConfirm
            label="Disconnect"
            armLabel={
              <>
                Disconnect <code>{channel.name}</code>? Its inbound webhook stops
                accepting messages immediately.
              </>
            }
            confirmLabel="Confirm disconnect"
            tone="danger"
            busyLabel="Disconnecting..."
            onConfirm={() => disconnect()}
          />
        </div>
      </div>

      {open && (
        <div className="stack">
          <div className="form">
            <div className="form__title">Configure</div>
            <div className="form__grid">
              <Field label="Name">
                <input value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
              <Field label="Unpaired sender behaviour">
                <SegmentedV2
                  value={unpaired}
                  ariaLabel="Unpaired sender behaviour"
                  onChange={setUnpaired}
                  options={UNPAIRED_OPTIONS}
                />
              </Field>
              <Field label="Status">
                <SegmentedV2
                  value={enabled}
                  ariaLabel="Status"
                  onChange={setEnabled}
                  options={ENABLED_OPTIONS}
                />
              </Field>
            </div>
            <div className="form__actions">
              <button
                className="btn btn--primary"
                disabled={busy}
                onClick={() => void configure()}
              >
                {busy ? "Saving..." : "Save"}
              </button>
              {msg && <span className="ok">{msg}</span>}
              {error && <span className="error">{error}</span>}
            </div>
          </div>

          <PairForm channelId={channel.id} />
          <BindingList channelId={channel.id} />
        </div>
      )}
    </div>
  );
}

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
