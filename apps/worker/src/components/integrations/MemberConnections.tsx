import { useCallback, useEffect, useState } from "react";
import type { MemberIntegrationConnection } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  useExactApprovalFinalizer,
} from "../ExactApprovalFinalizer";
import { SettingsGroup, SettingsRow } from "../settings/rowKit";

type GovernedAck = { status?: string; reason?: string };

/**
 * Offboarding: revoke a departed member's personal integration credential.
 *
 * Per-user credentials gave every member a sealed third-party token of their
 * own, and nothing could reach one but its owner -- `control.integration.revoke`
 * refuses a row that is not yours, and the connection list hides it from
 * everyone else. So a member who left took a live provider token with them and
 * no administrator could destroy it. This panel is the path that closes that.
 *
 * It shows LESS than the member's own view of the same rows, on purpose: the
 * server never sends `accounts` here, because that field carries their identity
 * at the provider and administering a connection is not a reason to read it.
 *
 * The panel renders nothing when the list is empty OR when the route refuses the
 * caller. That second case IS the role gate -- the route is author-only, and a
 * non-author never sees the section rather than being shown a control that
 * always fails. It imports the row kit directly rather than through
 * SettingsSurface, which mounts this component and would otherwise cycle.
 */
export function MemberIntegrationConnections() {
  const { rows, busyId, message, finalizer, revoke } = useMemberConnections();
  if (rows === null || rows.length === 0) return null;
  return (
    <SettingsGroup
      title="Members' own integrations"
      foot={(
        <>
          <ExactApprovalFinalizer controller={finalizer} />
          {message && <div className="settings-row-desc" role="status">{message}</div>}
        </>
      )}
    >
      {rows.map((row) => (
        <SettingsRow
          key={row.id}
          title={row.owner}
          desc={`${row.label} — ${row.health}`}
          tech={row.integration_id}
          control={(
            <button
              className="secondary-button"
              type="button"
              disabled={busyId === row.id || row.health === "revoked"}
              onClick={() => void revoke(row)}
            >
              {busyId === row.id ? "Revoking…" : "Revoke"}
            </button>
          )}
        />
      ))}
    </SettingsGroup>
  );
}

/** The list, the governed revocation and the approval replay, kept out of the
 * component so neither half exceeds the worker's function-size floor. */
function useMemberConnections() {
  const [rows, setRows] = useState<MemberIntegrationConnection[] | null>(null);
  const [busyId, setBusyId] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    try {
      const result = await client.memberIntegrationConnections();
      setRows(result.connections);
    } catch {
      setRows([]);  // includes the 403 a non-author gets; both mean "no section"
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const finalizer = useExactApprovalFinalizer<{ id: string }, GovernedAck>({
    isCurrent: (input) => rows?.some((row) => row.id === input.id) ?? false,
    replay: (input, approvalId) => client.revokeMemberIntegrationConnection(input.id, approvalId),
    isApplied: (result) => result.status === "revoked",
    onApplied: async () => {
      setMessage("The credential was destroyed.");
      await refresh();
    },
    onRefused: (result) => setMessage(
      governedResultReason(result, "The revocation was refused."),
    ),
    onUncertain: async () => {
      await refresh();
      setMessage("Connection state was refreshed. No revocation is inferred.");
    },
  });

  async function revoke(row: MemberIntegrationConnection) {
    finalizer.clear();
    setBusyId(row.id);
    setMessage("");
    try {
      const result = await client.revokeMemberIntegrationConnection(row.id);
      if (finalizer.begin({ id: row.id }, result, `${row.label} revocation`)) {
        setMessage(`${row.label} revocation is waiting for approval.`);
      } else if (result.status === "revoked") {
        setMessage("The credential was destroyed.");
        await refresh();
      } else {
        setMessage(governedResultReason(result, "The revocation could not be applied."));
      }
    } catch {
      setMessage("The revocation could not be applied.");
    } finally {
      setBusyId("");
    }
  }

  return { rows, busyId, message, finalizer, revoke };
}
