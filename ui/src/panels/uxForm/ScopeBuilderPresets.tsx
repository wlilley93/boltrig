export interface ScopeBuilderPresetsProps {
  presets?: { label: string; value: string[] }[];
  disabled: boolean;
  onChange: (v: string[]) => void;
}

export function ScopeBuilderPresets({ presets, disabled, onChange }: ScopeBuilderPresetsProps) {
  if (!presets || presets.length === 0) return null;
  return (
    <div className="ux-scope__presets">
      <span className="ux-hint">Presets:</span>
      {presets.map((p) => (
        <button
          key={p.label}
          type="button"
          className="btn btn--sm btn--ghost"
          disabled={disabled}
          onClick={() => onChange([...p.value])}
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}
