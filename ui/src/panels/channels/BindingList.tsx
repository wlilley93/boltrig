import type { ChannelBindingSummary, ChannelBindingsResponse } from "@/api/types";
import type { FetchState } from "@/useFetch";
import { SegmentedV2 } from "@/panels/uxForm";
import { ArmConfirm, Skeleton } from "@/panels/uxFlow";
import { EmptyState, Field, FetchError } from "@/panels/ux";
import { ROLE_OPTIONS } from "./options";
import { useBindingList } from "./useBindingList";

export { useBindingList } from "./useBindingList";

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
    busy,
    error,
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
        busy={busy}
        error={error}
        onAdd={addBinding}
      />
    </div>
  );
}
