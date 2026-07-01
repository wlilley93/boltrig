import { BrainCanvas, BrainControls, BrainLoader, BrainTelemetry } from "@/components/brain";
import { StoryOverlay } from "@/components/story";

/**
 * Home view — a Server Component. A scroll-driven neural narrative: a full-bleed,
 * **fixed** WebGL particle brain (`BrainCanvas`, z-0) sits behind a stack of
 * animated story chapters (`StoryOverlay`). The brain stands to one side at rest;
 * scrolling flies the camera between chapters, scans regions, and disperses the
 * brain in the finale, while a full-screen procedural "signal field" takes over
 * mid-story and then reveals the brain again. The terminal-style telemetry monitor
 * (`BrainTelemetry`) tracks the active chapter; the loader (`BrainLoader`) fronts
 * the first paint. The dev parameters drawer mounts only in development.
 */
export const HomeView = () => {
  return (
    <main className="relative w-full bg-black text-white">
      <h1 className="sr-only">The Human Brain — an interactive particle model</h1>

      <div className="fixed inset-0 z-0">
        <BrainCanvas />
      </div>

      <BrainTelemetry />
      <StoryOverlay />
      <BrainLoader />

      {process.env.NODE_ENV === "development" && <BrainControls />}
    </main>
  );
};
