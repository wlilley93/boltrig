import type { DisplayField } from "@wlilley93/boltrig-web-sdk";

export type DisplayFieldValue = string | number | boolean | string[];

export function initialFieldValues(fields: DisplayField[]): Record<string, DisplayFieldValue> {
  return Object.fromEntries(fields.map((field) => [field.id, field.value ?? defaultValue(field)]));
}

function defaultValue(field: DisplayField): DisplayFieldValue {
  if (field.type === "checkbox") return false;
  if (field.type === "multi_select") return [];
  if (field.type === "number") return 0;
  return "";
}

export function DisplayFields({
  fields,
  values,
  onChange,
  disabled = false,
}: {
  fields: DisplayField[];
  values: Record<string, DisplayFieldValue>;
  onChange(id: string, value: DisplayFieldValue): void;
  disabled?: boolean;
}) {
  return <div className="display-object-fields">{fields.map((field) => (
    <label key={field.id}>
      <span>{field.label}{field.required ? " *" : ""}</span>
      <DisplayFieldControl
        disabled={disabled}
        field={field}
        onChange={(value) => onChange(field.id, value)}
        value={values[field.id] ?? defaultValue(field)}
      />
      {field.help && <small>{field.help}</small>}
    </label>
  ))}</div>;
}

function DisplayFieldControl({ field, value, onChange, disabled }: {
  field: DisplayField;
  value: DisplayFieldValue;
  onChange(value: DisplayFieldValue): void;
  disabled: boolean;
}) {
  if (field.type === "textarea") return <textarea
    disabled={disabled} maxLength={4_000} onChange={(event) => onChange(event.target.value)}
    placeholder={field.placeholder} rows={4} value={String(value)}
  />;
  if (field.type === "checkbox") return <input
    checked={Boolean(value)} disabled={disabled} onChange={(event) => onChange(event.target.checked)}
    type="checkbox"
  />;
  if (field.type === "multi_select") return <select
    disabled={disabled} multiple onChange={(event) => onChange(
      [...event.target.selectedOptions].map((option) => option.value),
    )} value={Array.isArray(value) ? value : []}
  >{field.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>;
  if (field.type === "select" || (field.options?.length ?? 0) > 0) return <select
    disabled={disabled} onChange={(event) => onChange(event.target.value)} value={String(value)}
  ><option value="">Choose…</option>{field.options?.map((option) => (
    <option key={option.value} value={option.value}>{option.label}</option>
  ))}</select>;
  if (field.type === "file") return <button className="secondary-button" disabled type="button">
    Attach through the composer
  </button>;
  return <input
    disabled={disabled}
    maxLength={4_000}
    onChange={(event) => onChange(field.type === "number" ? Number(event.target.value) : event.target.value)}
    placeholder={field.placeholder}
    type={inputType(field.type)}
    value={String(value)}
  />;
}

function inputType(type: DisplayField["type"]): "text" | "number" | "date" | "datetime-local" {
  if (type === "number") return "number";
  if (type === "date") return "date";
  if (type === "datetime") return "datetime-local";
  return "text";
}
