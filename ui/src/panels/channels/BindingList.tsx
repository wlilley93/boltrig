import { useState } from "react";

import { api } from "@/api/client";
import type { ChannelBindingSummary, ChannelBindingsResponse } from "@/api/types";
import { useFetch, type FetchState } from "@/useFetch";
import { SegmentedV2 } from "@/panels/uxForm";
import { ArmConfirm, Skeleton } from "@/panels/uxFlow";
import { PendingHumanCard } from "@/panels/uxFlow/pendingHumanCard";
import { useControlMutation } from "@/panels/uxFlow/useControlMutation";
import { EmptyState, Field, FetchError } from "@/panels/ux";
import { ROLE_OPTIONS } from "./options";

export function useBindingList(channelId: string) {
  const bindings = useFetch(() => api.channelBindings(channelId), [channelId]);

  const [ext, setExt] = useState("");
  const [subject, setSubject] = useState("");
  const [role, setRole] = useState("member");
  const addMutation = useControlMutation({
    verb: "control.channel.bind",
    onApplied() {
      setExt("");
      setSubject("");
      bindings.reload();
    },
  });
  const removeMutation = useControlMutation({
    verb: "control.channel.unbind",
    onApplied() {
      bindings.reload();
    },
  });

  async function addBinding() {
    if (!ext.trim() || !subject.trim()) {
      addMutation.onPendingDenied("An external user id and a subject are required.");
      return;
    }
    await addMutation.invoke({
      channel_id: channelId,
      external_user_id: ext.trim(),
      subject: subject.trim(),
      role,
    });
  }

  async function removeBinding(bindingId: string) {
    await removeMutation.invoke({ channel_id: channelId, binding_id: bindingId });
  }

  const denied =
    bindings.data && bindings.data.bindings === undefined
      ? bindings.data.reason ?? "not permitted"
      : null;
  const list: ChannelBindingSummary[] = bindings.data?.bindings ?? [];

  return {
    bindings,
    ext,
    setExt,
    subject,
    setSubject,
    role,
    setRole,
    addMutation,
    removeMutation,
    addBinding,
    removeBinding,
    denied,
    list,
  };
}

function BindingCard(
  props: {
    bindings: FetchState<ChannelBindingsResponse>;
    denied: string | null;
    list: ChannelBindingSummary[];
    onRemove: (id: string) => Promise<void>;
  },
) {
  const { bindings, denied, list, onRemove } = props;
  return (
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
              onConfirm={() => onRemove(b.id)}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function AddBindingForm(
  props: {
    ext: string;
    setExt: (v: string) => void;
    subject: string;
    setSubject: (v: string) => void;
    role: string;
    setRole: (v: string) => void;
    busy: boolean;
    error: string | null;
    onAdd: () => Promise<void>;
  },
) {
  const { ext, setExt, subject, setSubject, role, setRole, busy, error, onAdd } = props;
  return (
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
        <button className="btn" disabled={busy} onClick={() => void onAdd()}>
          {busy ? "Binding..." : "Add binding"}
        </button>
        {error && <span className="error">{error}</span>}
      </div>
    </div>
  );
}

export function BindingList({ channelId }: { channelId: string }) {
  const {
    bindings,
    ext,
    setExt,
    subject,
    setSubject,
    role,
    setRole,
    addMutation,
    removeMutation,
    addBinding,
    removeBinding,
    denied,
    list,
  } = useBindingList(channelId);

  return (
    <div className="stack">
      <BindingCard
        bindings={bindings}
        denied={denied}
        list={list}
        onRemove={removeBinding}
      />
      <AddBindingForm
        ext={ext}
        setExt={setExt}
        subject={subject}
        setSubject={setSubject}
        role={role}
        setRole={setRole}
        busy={addMutation.busy || addMutation.pending !== null}
        error={addMutation.error ?? removeMutation.error}
        onAdd={addBinding}
      />
      {addMutation.pending && (
        <PendingHumanCard
          hitlRequestId={addMutation.pending.id}
          noun="control"
          verb="control.channel.bind"
          sentParams={addMutation.pending.params}
          onApplied={addMutation.onPendingApplied}
          onDenied={addMutation.onPendingDenied}
          onReset={addMutation.resetPending}
        />
      )}
      {removeMutation.pending && (
        <PendingHumanCard
          hitlRequestId={removeMutation.pending.id}
          noun="control"
          verb="control.channel.unbind"
          sentParams={removeMutation.pending.params}
          onApplied={removeMutation.onPendingApplied}
          onDenied={removeMutation.onPendingDenied}
          onReset={removeMutation.resetPending}
        />
      )}
    </div>
  );
}
