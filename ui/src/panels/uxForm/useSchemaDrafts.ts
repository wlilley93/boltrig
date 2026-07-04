import { useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

export interface UseSchemaDraftsResult {
  drafts: Record<string, string>;
  setDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  jsonErrs: Record<string, string>;
  setJsonErrs: Dispatch<SetStateAction<Record<string, string>>>;
  invalid: boolean;
  clearJsonErr: (path: string) => void;
}

export function useSchemaDrafts(onValidity?: (valid: boolean) => void): UseSchemaDraftsResult {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [jsonErrs, setJsonErrs] = useState<Record<string, string>>({});
  const invalid = Object.keys(jsonErrs).length > 0;

  useEffect(() => {
    onValidity?.(!invalid);
  }, [invalid, onValidity]);

  const clearJsonErr = (path: string) => {
    setJsonErrs((m) => {
      if (!(path in m)) return m;
      const next = { ...m };
      delete next[path];
      return next;
    });
  };

  return { drafts, setDrafts, jsonErrs, setJsonErrs, invalid, clearJsonErr };
}
