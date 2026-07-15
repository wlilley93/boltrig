import { useState } from "react";

import { Field } from "@/panels/ux";
import { SegmentedV2 } from "@/panels/uxForm";
import { PendingHumanCard } from "@/panels/uxFlow/pendingHumanCard";
import { outputRecord, useControlMutation } from "@/panels/uxFlow/useControlMutation";
import { ENABLED_OPTIONS, PLATFORM_OPTIONS, UNPAIRED_OPTIONS } from "./options";

export function useConnectForm(onConnected: () => void) {
  const [platform, setPlatform] = useState("webhook");
  const [name, setName] = useState("");
  const [unpaired, setUnpaired] = useState("reject");
  const [secret, setSecret] = useState("");
  const [enabled, setEnabled] = useState("true");
  const [inboundUrl, setInboundUrl] = useState<string | null>(null);
  const mutation = useControlMutation({
    verb: "control.channel.connect",
    onApplied(output) {
      const connected = outputRecord(output);
      setInboundUrl(typeof connected.inbound_url === "string" ? connected.inbound_url : null);
      setName("");
      setSecret("");
      onConnected();
    },
  });

  async function connect() {
    if (!name.trim()) {
      mutation.onPendingDenied("A channel name is required.");
      return;
    }
    setInboundUrl(null);
    const params: Record<string, unknown> = {
      platform,
      name: name.trim(),
      unpaired_behavior: unpaired,
      enabled: enabled === "true",
    };
    if (secret.trim()) params.signing_secret = secret.trim();
    await mutation.invoke(params);
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
    mutation,
    inboundUrl,
    connect,
  };
}

function InboundUrlNotice({ url }: { url: string }) {
  return (
    <p className="notice">
      Channel connected. Point the platform's webhook at <code>{url}</code>.
    </p>
  );
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
    mutation,
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
          <input
            aria-label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
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
            aria-label="Signing secret"
            value={secret}
            autoComplete="off"
            onChange={(e) => setSecret(e.target.value)}
          />
        </Field>
      </div>
      {mutation.pending && (
        <PendingHumanCard
          hitlRequestId={mutation.pending.id}
          noun="control"
          verb="control.channel.connect"
          sentParams={mutation.pending.params}
          onApplied={mutation.onPendingApplied}
          onDenied={mutation.onPendingDenied}
          onReset={mutation.resetPending}
        />
      )}
      <div className="form__actions">
        <button className="btn btn--primary" disabled={mutation.busy || mutation.pending !== null} onClick={() => void connect()}>
          {mutation.busy ? "Connecting..." : "Connect channel"}
        </button>
        {mutation.error && <span className="error">{mutation.error}</span>}
      </div>
      {inboundUrl && <InboundUrlNotice url={inboundUrl} />}
    </div>
  );
}
