import { useId, useState } from "react";

import { Disclosure } from "@/panels/uxFlow";

interface ImportedFile {
  name: string;
  bytes: number;
}

/**
 * Prefer a document import over exposing a large JSON editor. The raw document
 * remains available as an explicit advanced escape hatch for repair/review.
 */
export function OpenApiImport({
  value,
  onChange,
  onError,
}: {
  value: string;
  onChange: (value: string) => void;
  onError: (message: string | null) => void;
}) {
  const inputId = useId();
  const [imported, setImported] = useState<ImportedFile | null>(null);

  async function importFile(file: File | undefined) {
    if (file === undefined) return;
    try {
      const text = await file.text();
      if (!text.trim()) throw new Error("The selected file is empty.");
      onChange(text);
      onError(null);
      setImported({ name: file.name, bytes: file.size });
    } catch (error) {
      setImported(null);
      onError(
        error instanceof Error ? error.message : "Could not read the OpenAPI file.",
      );
    }
  }

  return (
    <div className="stack">
      <label className="field" htmlFor={inputId}>
        <span>OpenAPI document</span>
        <input
          id={inputId}
          type="file"
          accept=".json,application/json"
          onChange={(event) => void importFile(event.currentTarget.files?.[0])}
        />
      </label>
      <p className="muted" role="status">
        {imported
          ? `Imported ${imported.name} (${imported.bytes.toLocaleString()} bytes).`
          : "Choose an OpenAPI JSON file. It is parsed locally before generation."}
      </p>
      <Disclosure
        summary="Advanced: raw OpenAPI JSON"
        count={value ? `${value.length.toLocaleString()} chars` : "empty"}
      >
        <label className="field">
          <span>Raw document</span>
          <textarea
            aria-label="Raw OpenAPI JSON"
            className="code code--tall"
            value={value}
            onChange={(event) => {
              setImported(null);
              onError(null);
              onChange(event.target.value);
            }}
            placeholder='{"openapi":"3.0.0","info":{...},"paths":{...}}'
          />
        </label>
      </Disclosure>
    </div>
  );
}
