import { api } from "@/api/client";
import { errText, scopeLabel } from "@/panels/shared";
import type { InsightFields } from "./useInsightFields";

export interface InsightActions {
  search: () => Promise<void>;
  exportAudit: () => Promise<void>;
}

export function downloadAuditExport(
  response: unknown,
  date = new Date(),
): string {
  const day = date.toISOString().slice(0, 10);
  const filename = `boltrig-audit-${day}.json`;
  const blob = new Blob([JSON.stringify(response, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
  return filename;
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
        resource: f.resource.trim() || undefined,
        status: f.status || undefined,
        since: f.since || undefined,
        until: f.until || undefined,
        security: f.stream === "security",
        eventType: f.stream === "security" ? f.eventType.trim() || undefined : undefined,
      });
      f.setRows(res.results);
      f.setStream(res.stream ?? f.stream);
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
      else {
        downloadAuditExport(res);
        f.setExported(res);
      }
    } catch (err) {
      f.setExportError(errText(err));
    } finally {
      f.setExportBusy(false);
    }
  }

  return { search, exportAudit };
}
