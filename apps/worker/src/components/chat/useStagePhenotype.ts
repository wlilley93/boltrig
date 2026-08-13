import { useEffect, useState } from "react";
import type { FamiliarPhenotypeResponse } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";

export function useStagePhenotype(enabled: boolean): {
  pageHidden: boolean;
  phenotype: FamiliarPhenotypeResponse | null;
} {
  const [phenotype, setPhenotype] = useState<FamiliarPhenotypeResponse | null>(null);
  const [pageHidden, setPageHidden] = useState(
    typeof document !== "undefined" && document.visibilityState === "hidden",
  );

  useEffect(() => {
    const onVisibility = () => setPageHidden(document.visibilityState === "hidden");
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    if (!enabled || pageHidden) {
      setPhenotype(null);
      return;
    }
    let cancelled = false;
    const pull = () => {
      if (typeof client.familiarPhenotype !== "function") return;
      void client.familiarPhenotype()
        .then((result) => { if (!cancelled) setPhenotype(result); })
        .catch(() => { if (!cancelled) setPhenotype(null); });
    };
    pull();
    const timer = window.setInterval(pull, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [enabled, pageHidden]);

  return { pageHidden, phenotype };
}
