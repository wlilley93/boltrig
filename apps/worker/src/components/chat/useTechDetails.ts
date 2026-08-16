import { useEffect, useState } from "react";

import { client } from "../../client";

/** The me-settings key that switches the console into developer detail:
 * monospace verb chips on approvals and fan-out rows, raw model/profile ids
 * on the model chip, and the model-routing note. */
export const DEVELOPER_DETAILS_KEY = "developer_details";

// The decided target gates monospace noun.verb chips and raw model ids behind
// a tech preference. The worker persists that choice in the me-settings blob
// (client.meSettings/putMeSettings accept arbitrary keys), so it follows the
// person across clients. This hook only READS the flag - the Settings surface
// owns the toggle - and a build whose settings lack the key honestly renders
// the plain-words console.
export function useTechDetails(): boolean {
  const [tech, setTech] = useState(false);
  useEffect(() => {
    if (typeof client.meSettings !== "function") return;
    let cancelled = false;
    void client.meSettings()
      .then((result) => {
        if (!cancelled) setTech(result.settings?.[DEVELOPER_DETAILS_KEY] === true);
      })
      .catch(() => { if (!cancelled) setTech(false); });
    return () => { cancelled = true; };
  }, []);
  return tech;
}
