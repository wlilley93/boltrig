import { lazy, Suspense } from "react";

const OperationsSection = lazy(async () => ({
  default: (await import("../OperationsView")).OperationsSection,
}));

/**
 * Keep the operational evidence surface out of the initial settings bundle.
 * Its data ownership remains in OperationsView; this boundary only defers the
 * large renderer until the user selects the Operations section.
 */
export function OperationsSettingsSection({ head = true }: { head?: boolean }) {
  return (
    <Suspense fallback={<p className="muted" role="status">Loading operations…</p>}>
      <OperationsSection head={head} />
    </Suspense>
  );
}
