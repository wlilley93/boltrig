import type { VerbFormState } from "./useVerbForm";

export function VerbSchemaFields({ s }: { s: VerbFormState }) {
  return (
    <>
      <label className="field">
        <span>input_schema (JSON)</span>
        <textarea
          className="code"
          value={s.inputSchema}
          onChange={(e) => s.setInputSchema(e.target.value)}
        />
      </label>
      <label className="field">
        <span>output_schema (JSON)</span>
        <textarea
          className="code"
          value={s.outputSchema}
          onChange={(e) => s.setOutputSchema(e.target.value)}
        />
      </label>
    </>
  );
}
