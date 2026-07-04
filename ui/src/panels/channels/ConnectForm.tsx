import { useState } from "react";

import { api } from "@/api/client";
import { errText } from "@/panels/shared";
import { Field } from "@/panels/ux";
import { SegmentedV2 } from "@/panels/uxForm";
import { ENABLED_OPTIONS, PLATFORM_OPTIONS, UNPAIRED_OPTIONS } from "./options";

export function useConnectForm(onConnected: () => void) {
  const [platform, setPlatform] = useState("webhook");
  const [name, setName] = useState("");
  const [unpaired, setUnpaired] = useState("reject");
  const [secret, setSecret] = useState("");
  const [enabled, setEnabled] = useState("true");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inboundUrl, setInboundUrl] = useState<string | null>(null);

  async function connect() {
    if (!name.trim()) {
      setError("A channel name is required.");
      return;
    }
    setBusy(true);
    setError(null);
    setInboundUrl(null);
    try {
      const res = await api.connectChannel({
        platform,
        name: name.trim(),
        unpaired_behavior: unpaired,
        enabled: enabled === "true",
        signing_secret: secret.trim() || undefined,
      });
      if (res.status === "ok") {
        setInboundUrl(res.inbound_url ?? null);
        setName("");
        setSecret("");
        onConnected();
      } else {
        setError(res.reason ?? "connect rejected");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return {
    platform,
    setPlatform,
    name,
    setName,
    unpaired,
    setUnpaired,
    secret,
    setSecret,
    enabled,
    setEnabled,
    busy,
    error,
    inboundUrl,
    connect,
  };
}

export function ConnectForm({ onConnected }: { onConnected: () => void }) {
  const {
    platform,
    setPlatform,
    name,
    setName,
    unpaired,
    setUnpaired,
    secret,
    setSecret,
    enabled,
    setEnabled,
    busy,
    error,
    inboundUrl,
    connect,
  } = useConnectForm(onConnected);

  return (
    <div className="form">
      <div className="form__title">Connect a channel</div>
      <p className="muted">
        A channel accepts signed inbound messages and turns them into governed
        work items. The signing secret is stored server-side and never shown
        again; leave it blank to add it later.
      </p>
      <div className="form__grid">
        <Field label="Platform">
          <SegmentedV2
            value={platform}
            ariaLabel="Platform"
            onChange={setPlatform}
            options={PLATFORM_OPTIONS}
          />
        </Field>
        <Field label="Name">
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field
          label="Unpaired sender behaviour"
          hint="What happens when a message arrives from a sender who is not yet bound to an identity."
        >
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
        <Field
          label="Signing secret (optional)"
          hint="An HMAC secret used to verify inbound signatures. Write-only."
          wide
        >
          <input
            type="password"
            value={secret}
            autoComplete="off"
            onChange={(e) => setSecret(e.target.value)}
          />
        </Field>
      </div>
      <div className="form__actions">
        <button className="btn btn--primary" disabled={busy} onClick={() => void connect()}>
          {busy ? "Connecting..." : "Connect channel"}
        </button>
        {error && <span className="error">{error}</span>}
      </div>
      {inboundUrl && (
        <p className="notice">
          Channel connected. Point the platform's webhook at{" "}
          <code>{inboundUrl}</code>.
        </p>
      )}
    </div>
  );
}
