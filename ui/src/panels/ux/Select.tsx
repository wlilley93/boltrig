import type { Option } from "./types";

// --- Select: a labelled dropdown over a known value space ------------------
export function Select({
  value,
  onChange,
  options,
  id,
  ariaLabel,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  options: Option[];
  id?: string;
  ariaLabel?: string;
  disabled?: boolean;
}) {
  return (
    <select
      id={id}
      aria-label={ariaLabel}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
