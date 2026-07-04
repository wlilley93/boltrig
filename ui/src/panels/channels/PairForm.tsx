import { useState } from "react";

import { api } from "@/api/client";
import { errText } from "@/panels/shared";
import { Field } from "@/panels/ux";
import { SegmentedV2 } from "@/panels/uxForm";
import { SecretOnce } from "@/panels/uxFlow";
import { ROLE_OPTIONS } from "./options";

export function usePairForm(channelId: string) {
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

  return {
    ext,
    setExt,
    subject,
    setSubject,
    role,
    setRole,
    busy,
    error,
    minted,
    setMinted,
    issue,
  };
}

export function PairForm({ channelId }: { channelId: string }) {
  const { ext, setExt, subject, setSubject, role, setRole, busy, error, minted, setMinted, issue } =
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
      <div className="form__actions">
        <button className="btn" disabled={busy} onClick={() => void issue()}>
          {busy ? "Issuing..." : "Issue code"}
        </button>
        {error && <span className="error">{error}</span>}
      </div>
    </div>
  );
}
