import {
  useEffect,
  useId,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import "./GovernedCreateModal.css";

export type GovernedCreateMethod = {
  title: string;
  description: string;
  tag?: string;
  icon: ReactNode;
  available: boolean;
  unavailableReason?: string;
  onSelect?(): void;
};

export function GovernedCreateModal({
  title,
  lead,
  methods,
  onClose,
}: {
  title: string;
  lead: string;
  methods: GovernedCreateMethod[];
  onClose(): void;
}) {
  const cardRef = useRef<HTMLElement>(null);
  const titleId = useId();

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const initial = cardRef.current?.querySelector<HTMLButtonElement>(
      ".governed-create-method:not(:disabled)",
    ) ?? cardRef.current?.querySelector<HTMLButtonElement>("button:not(:disabled)");
    initial?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      previous?.focus();
    };
  }, []);

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const controls = Array.from(
      cardRef.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    ).filter((control) => control.getAttribute("aria-hidden") !== "true");
    if (controls.length === 0) {
      event.preventDefault();
      cardRef.current?.focus();
      return;
    }
    const current = controls.indexOf(document.activeElement as HTMLElement);
    if (event.shiftKey && current <= 0) {
      event.preventDefault();
      controls.at(-1)?.focus();
    } else if (!event.shiftKey && current === controls.length - 1) {
      event.preventDefault();
      controls[0]?.focus();
    }
  }

  return (
    <div className="governed-create-scrim" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }} role="presentation">
      <section
        aria-labelledby={titleId}
        aria-modal="true"
        className="governed-create-card"
        data-screen-label="New"
        onKeyDown={handleKeyDown}
        ref={cardRef}
        role="dialog"
        tabIndex={-1}
      >
        <header>
          <div>
            <h2 id={titleId}>{title}</h2>
            <p>{lead}</p>
          </div>
          <button aria-label={`Close ${title.toLowerCase()}`} onClick={onClose} type="button">×</button>
        </header>
        <div className="governed-create-methods">
          {methods.map((method) => (
            <button
              aria-disabled={!method.available}
              className="governed-create-method"
              disabled={!method.available}
              key={method.title}
              onClick={method.available ? method.onSelect : undefined}
              title={!method.available ? method.unavailableReason : undefined}
              type="button"
            >
              <span className="governed-create-method-icon">{method.icon}</span>
              <span className="governed-create-method-copy">
                <span>
                  <strong>{method.title}</strong>
                  {method.tag && <em>{method.tag}</em>}
                  {!method.available && <em data-tone="quiet">Unavailable</em>}
                </span>
                <small>{method.available ? method.description : `${method.description} ${method.unavailableReason ?? "This method is not exposed by the current API."}`}</small>
              </span>
              <span aria-hidden="true" className="governed-create-chevron">›</span>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

export function CreateMethodIcon({ kind }: { kind: "copy" | "describe" | "empty" | "system" | "address" | "tools" }) {
  const paths: Record<typeof kind, ReactNode> = {
    copy: <><path d="M7 7h11v11H7z" /><path d="M4 15V4h11" /></>,
    describe: <><path d="M4 5h16v11H9l-5 4z" /><path d="M8 9h8M8 12h5" /></>,
    empty: <><circle cx="12" cy="8" r="3" /><path d="M5 20c.7-4 3-6 7-6s6.3 2 7 6" /></>,
    system: <><path d="M5 5h14v14H5z" /><path d="M8 9h8M8 13h5" /></>,
    address: <><path d="M10 13a4 4 0 0 0 5.7 0l2-2a4 4 0 0 0-5.7-5.7l-1.1 1.1" /><path d="M14 11a4 4 0 0 0-5.7 0l-2 2A4 4 0 0 0 12 18.7l1.1-1.1" /></>,
    tools: <><path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z" /></>,
  };
  return (
    <svg aria-hidden="true" fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 24 24" width="16">
      {paths[kind]}
    </svg>
  );
}
