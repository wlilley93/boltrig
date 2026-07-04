/** SecretOnce (N18, settings spec 1.5/3): show-once secret material. */
// Warn tone, never amber: no kernel governance is in play (L4).

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArmConfirm } from "@/panels/uxFlow/armConfirm";
import { copyText } from "@/panels/uxFlow/copyText";

function SecretOnceLayout({
  secret,
  title,
  body,
  meta,
  onDone,
  copyLabel,
  copiedFlash,
  everCopied,
  blockRef,
  copy,
  selectAll,
}: {
  secret: string;
  title?: ReactNode;
  body?: ReactNode;
  meta?: ReactNode;
  onDone: () => void;
  copyLabel?: string;
  copiedFlash: boolean;
  everCopied: boolean;
  blockRef: React.RefObject<HTMLPreElement>;
  copy: () => void;
  selectAll: () => void;
}) {
  return (
    <div className="ux-secret" role="status">
      <strong className="ux-secret__title">{title ?? "Copy this secret now."}</strong>
      <p className="ux-secret__body">
        {body ?? "This is the only time it is shown. It cannot be retrieved again."}
      </p>
      <pre
        className="ux-secret__block"
        ref={blockRef}
        onClick={selectAll}
        title="Click to select"
      >
        {secret}
      </pre>
      <div className="ux-secret__actions">
        <button type="button" className="btn btn--primary" onClick={copy}>
          {copiedFlash ? "Copied" : copyLabel ?? "Copy"}
        </button>
        {everCopied ? (
          <button type="button" className="btn btn--ghost" onClick={onDone}>
            Done
          </button>
        ) : (
          // P27 semantics on an uncopied dismiss: the secret is unrecoverable
          <ArmConfirm
            label="Done"
            armLabel="Dismiss without copying? The secret cannot be shown again."
            confirmLabel="Dismiss anyway"
            tone="warn"
            busyLabel="Dismissing..."
            onConfirm={async () => onDone()}
          />
        )}
      </div>
      {meta != null && <div className="ux-secret__meta">{meta}</div>}
    </div>
  );
}

export function SecretOnce({
  secret,
  title,
  body,
  meta,
  onDone,
  copyLabel,
}: {
  secret: string;
  title?: ReactNode;
  body?: ReactNode;
  meta?: ReactNode; // e.g. token name + expiry + a GrantList of its scope
  onDone: () => void;
  copyLabel?: string;
}) {
  const [copiedFlash, setCopiedFlash] = useState(false);
  const [everCopied, setEverCopied] = useState(false);
  const blockRef = useRef<HTMLPreElement>(null);

  // While mounted the secret exists nowhere else; guard accidental unloads.
  useEffect(() => {
    const guard = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, []);

  const selectAll = () => {
    const el = blockRef.current;
    const sel = window.getSelection();
    if (!el || !sel) return;
    const range = document.createRange();
    range.selectNodeContents(el);
    sel.removeAllRanges();
    sel.addRange(range);
  };

  const copy = () => {
    void copyText(secret).then((ok) => {
      if (ok) {
        setEverCopied(true);
        setCopiedFlash(true);
        window.setTimeout(() => setCopiedFlash(false), 2000);
      } else {
        // clipboard unavailable (permissions / insecure context): select so a
        // manual copy works
        selectAll();
      }
    });
  };

  return (
    <SecretOnceLayout
      secret={secret}
      title={title}
      body={body}
      meta={meta}
      onDone={onDone}
      copyLabel={copyLabel}
      copiedFlash={copiedFlash}
      everCopied={everCopied}
      blockRef={blockRef}
      copy={copy}
      selectAll={selectAll}
    />
  );
}
