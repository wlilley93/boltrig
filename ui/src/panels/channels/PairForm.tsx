import { useState } from "react";

import { Field } from "@/panels/ux";
import { SegmentedV2 } from "@/panels/uxForm";
import { SecretOnce } from "@/panels/uxFlow";
import { PendingHumanCard } from "@/panels/uxFlow/pendingHumanCard";
import { outputRecord, useControlMutation } from "@/panels/uxFlow/useControlMutation";
import { ROLE_OPTIONS } from "./options";

export function usePairForm(channelId: string) {
  const [ext, setExt] = useState("");
  const [subject, setSubject] = useState("");
  const [role, setRole] = useState("member");
  const [minted, setMinted] = useState<{ code: string; pairingId: string; role: string } | null>(
    null,
  );
  const mutation = useControlMutation({
    verb: "control.channel.pair",
    onApplied(output, params) {
      const issued = outputRecord(output);
      if (typeof issued.code !== "string") return;
      setMinted({
        code: issued.code,
        pairingId: typeof issued.pairing_id === "string" ? issued.pairing_id : "",
        role: String(params.role),
      });
      setExt("");
      setSubject("");
    },
  });

  async function issue() {
    if (!ext.trim() || !subject.trim()) {
      mutation.onPendingDenied("An external user id and a subject are required.");
      return;
    }
    await mutation.invoke({
      channel_id: channelId,
      external_user_id: ext.trim(),
      subject: subject.trim(),
      role,
    });
  }

  return {
    ext,
    setExt,
    subject,
    setSubject,
    role,
    setRole,
    mutation,
    minted,
    setMinted,
    issue,
  };
}

export function PairForm({ channelId }: { channelId: string }) {
  const { ext, setExt, subject, setSubject, role, setRole, mutation, minted, setMinted, issue } =
    usePairForm(channelId);

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
      {mutation.pending && (
        <PendingHumanCard
          hitlRequestId={mutation.pending.id}
          noun="control"
          verb="control.channel.pair"
          sentParams={mutation.pending.params}
          onApplied={mutation.onPendingApplied}
          onDenied={mutation.onPendingDenied}
          onReset={mutation.resetPending}
        />
      )}
      <div className="form__actions">
        <button className="btn" disabled={mutation.busy || mutation.pending !== null} onClick={() => void issue()}>
          {mutation.busy ? "Issuing..." : "Issue code"}
        </button>
        {mutation.error && <span className="error">{mutation.error}</span>}
      </div>
    </div>
  );
}
