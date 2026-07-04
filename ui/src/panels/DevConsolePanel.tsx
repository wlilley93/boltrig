// Developer console (Capability plane). Surfaces three client-ready kernel
// endpoints that no other panel exposes: direct verb invoke (POST /v1/invoke),
// ephemeral agent spawn (POST /v1/spawn) and the generated adapter source
// (GET /v1/adapters/{id}/source). Every call is server-authoritative: a denial,
// a pending-human pause or a degraded result is rendered faithfully, exactly as
// the kernel returned it (the AdminPanel pattern). The role gate on the tab is
// cosmetic; the chokepoint is the real gate (a 403 returns a denial body).

import { api } from "../api/client";
import { useFetch } from "../useFetch";
import { PageIntro } from "./ux";
import { AdapterSourceSection } from "./devConsole/AdapterSourceSection";
import { InvokeSection } from "./devConsole/InvokeSection";
import { SpawnSection } from "./devConsole/SpawnSection";

export function DevConsolePanel() {
  // The scoped verb registry powers the invoke picker; the adapter inventory
  // powers the source viewer; the skills list powers the spawn chips. All are
  // caller-scoped server-side.
  const caps = useFetch(() => api.capabilities(), []);
  const adapters = useFetch(() => api.adapters(), []);
  const skillsList = useFetch(() => api.skills(), []);

  return (
    <section className="panel">
      <PageIntro
        title="Dev console"
        lead="Run one verb at a time, by hand, to test or debug a capability."
        how="Pick a verb from the registry; the kernel checks your grants and shows the real result - success, a denial, or a pause for human approval. Nothing here bypasses governance."
        actions={
          <button
            className="btn"
            onClick={() => {
              caps.reload();
              adapters.reload();
              skillsList.reload();
            }}
          >
            Refresh
          </button>
        }
      />

      <InvokeSection caps={caps} />
      <SpawnSection skillsList={skillsList} />
      <AdapterSourceSection adapters={adapters} />
    </section>
  );
}
