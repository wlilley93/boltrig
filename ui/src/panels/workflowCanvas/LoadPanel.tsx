interface LoadPanelProps {
  loadText: string;
  loadError: string | null;
  onChange: (v: string) => void;
  onLoad: () => void;
}

export function LoadPanel({ loadText, loadError, onChange, onLoad }: LoadPanelProps) {
  return (
    <div className="form">
      <div className="form__title">Load definition (JSON)</div>
      <p className="muted">
        Paste a steps array or a {"{steps:[...]}"} object to render it on the
        canvas (the inverse of Save).
      </p>
      <textarea
        className="code"
        value={loadText}
        onChange={(e) => onChange(e.target.value)}
      />
      <div className="form__actions">
        <button className="btn" onClick={onLoad}>
          Load onto canvas
        </button>
        {loadError && <span className="error">{loadError}</span>}
      </div>
    </div>
  );
}
