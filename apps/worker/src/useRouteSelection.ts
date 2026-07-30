import { useCallback, useEffect, useState } from "react";

import {
  navigate,
  selectionFromHash,
  type WorkerRoute,
} from "./routes";

export function useRouteSelection(
  route: WorkerRoute,
): [string | null, (selectionId: string | null) => void] {
  const [selectionId, setSelectionId] = useState<string | null>(
    () => selectionFromHash(window.location.hash, route),
  );

  useEffect(() => {
    const onHashChange = () => {
      setSelectionId(selectionFromHash(window.location.hash, route));
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [route]);

  const select = useCallback((next: string | null) => {
    setSelectionId(next);
    navigate(route, next);
  }, [route]);

  return [selectionId, select];
}
