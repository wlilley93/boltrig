import { useEffect, useState } from "react";
import type { BackupStatusResponse } from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { Unavailable } from "./Shell";

export function BackupStatusCard() {
  const [backup, setBackup] = useState<BackupStatusResponse["backup"] | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  function refresh() {
    void Promise.resolve()
      .then(() => client.backupStatus())
      .then((result) => {
        setBackup(result.backup);
        setUnavailable(false);
      })
      .catch(() => {
        setBackup(null);
        setUnavailable(true);
      });
  }

  useEffect(refresh, []);

  return (
    <section className="settings-card" aria-label="Backup freshness evidence">
      <div className="section-heading">
        <div><p className="eyebrow">Disaster recovery</p><h2>Backup freshness</h2></div>
        <button className="secondary-button" onClick={refresh}>Refresh</button>
      </div>
      {backup ? (
        <>
          <div className="compact-row">
            <span className={`activity-dot ${backup.state === "fresh" ? "ok" : "paused"}`} />
            <span>
              <strong>{backup.state.replaceAll("_", " ")}</strong>
              <small>
                {backup.last_success_at
                  ? `Last success ${new Date(backup.last_success_at).toLocaleString()}`
                  : "No successful scheduled backup marker is visible"}
              </small>
            </span>
            <span className="row-meta">
              {backup.age_seconds === null
                ? "age unknown"
                : `${backup.age_seconds}s old`}
            </span>
          </div>
          <Unavailable title="Restore readiness is not proven">
            This marker proves only that one complete scheduled backup command
            succeeded recently. It is not sidecar liveness, off-box/encryption
            evidence, replica coverage or a restore-drill receipt.
          </Unavailable>
        </>
      ) : (
        <Unavailable title="Backup evidence unavailable">
          {unavailable
            ? "The safe backup marker could not be read."
            : "Loading backup freshness evidence…"}
        </Unavailable>
      )}
    </section>
  );
}
