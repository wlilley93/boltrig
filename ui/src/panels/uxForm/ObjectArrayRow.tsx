import type { Dispatch, SetStateAction } from "react";

import { ControlField } from "./ControlField";
import type { PropSpec, SchemaFieldContext } from "./schemaTypes";

export interface ObjectArrayRowProps {
  index: number;
  singular: string;
  row: unknown;
  itemProps: Record<string, PropSpec>;
  itemReq: Set<string>;
  orderedItem: string[];
  path: string;
  depth: number;
  errors?: Record<string, string>;
  drafts: Record<string, string>;
  setDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  jsonErrs: Record<string, string>;
  setJsonErrs: Dispatch<SetStateAction<Record<string, string>>>;
  clearJsonErr: (path: string) => void;
  setRow: (i: number, next: Record<string, unknown>) => void;
  removeRow: (i: number) => void;
}

export function ObjectArrayRow({
  index,
  singular,
  row,
  itemProps,
  itemReq,
  orderedItem,
  path,
  depth,
  errors,
  drafts,
  setDrafts,
  jsonErrs,
  setJsonErrs,
  clearJsonErr,
  setRow,
  removeRow,
}: ObjectArrayRowProps) {
  const obj = (row && typeof row === "object" && !Array.isArray(row) ? row : {}) as Record<string, unknown>;
  return (
    <div className="ux-inset">
      <span
        className="ux-inset__label"
        style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
      >
        <span>
          {singular} {index + 1}
        </span>
        <button
          type="button"
          className="btn btn--sm btn--ghost"
          aria-label={`Remove ${singular} ${index + 1}`}
          onClick={() => removeRow(index)}
        >
          Remove
        </button>
      </span>
      <div className="ux-inset__grid">
        {orderedItem.map((sub) => {
          const childCtx: SchemaFieldContext = {
            path: `${path}.${index}.${sub}`,
            fieldKey: sub,
            spec: itemProps[sub],
            value: obj[sub],
            onChange: (nv) => setRow(index, { ...obj, [sub]: nv }),
            required: itemReq.has(sub),
            depth: depth + 1,
            errors,
            drafts,
            setDrafts,
            jsonErrs,
            setJsonErrs,
            clearJsonErr,
          };
          return <ControlField key={childCtx.path} ctx={childCtx} />;
        })}
      </div>
    </div>
  );
}
