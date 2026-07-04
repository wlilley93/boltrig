import { api } from "@/api/client";
import { errText, scopeLabel } from "@/panels/shared";
import type { InsightFields } from "./useInsightFields";

export interface InsightActions {
  search: () => Promise<void>;
  exportAudit: () => Promise<void>;
}

export function useInsightActions(f: InsightFields): InsightActions {
  async function search() {
    f.setSearchBusy(true);
    f.setSearchError(null);
    try {
      const res = await api.auditSearch({
        actor: f.actor.trim() || undefined,
        verb: f.verb.trim() || undefined,
        run: f.run.trim() || undefined,
      });
      f.setRows(res.results);
      f.setSearchScope(scopeLabel(res.scope));
    } catch (err) {
      f.setSearchError(errText(err));
    } finally {
      f.setSearchBusy(false);
    }
  }

  async function exportAudit() {
    f.setExportBusy(true);
    f.setExportError(null);
    f.setExported(null);
    try {
      const res = await api.auditExport();
      if (res.error) f.setExportError(res.error);
      else f.setExported(res);
    } catch (err) {
      f.setExportError(errText(err));
    } finally {
      f.setExportBusy(false);
    }
  }

  return { search, exportAudit };
}
