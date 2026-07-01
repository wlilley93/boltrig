"use client";

import { useEffect, useState, type ReactNode } from "react";
import { animated, useSpring } from "@react-spring/web";

import { serializeBrainConfig } from "./config";
import { useBrainControls } from "./use-brain-controls";

/**
 * The parameters drawer — live control over every scene knob: colours, particle
 * sizes/counts, motion, and the camera's idle rotation. Slides in from the right
 * with a spring (rule #1). Colour/size/motion edits stream straight into the
 * shader uniforms (no rebuild); count edits commit on release because they
 * re-sample geometry. This is a **dev-only** tuning tool (mounted only in
 * development, see `HomeView`). Open/close it with the floating gear button
 * (bottom-right) or **Shift+P**.
 */
export const BrainControls = () => {
  const open = useBrainControls((s) => s.panelOpen);
  const setPanelOpen = useBrainControls((s) => s.setPanelOpen);
  const config = useBrainControls((s) => s.config);
  const camera = useBrainControls((s) => s.camera);
  const setParam = useBrainControls((s) => s.setParam);
  const setCamera = useBrainControls((s) => s.setCamera);
  const reset = useBrainControls((s) => s.reset);

  const drawer = useSpring({
    x: open ? 0 : 360,
    opacity: open ? 1 : 0,
    config: { tension: 240, friction: 30 },
  });

  // Open/close with Shift+P (the floating gear button below is the discoverable
  // affordance; the shortcut is the power-user path).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.shiftKey && (e.key === "P" || e.key === "p")) {
        setPanelOpen(!useBrainControls.getState().panelOpen);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setPanelOpen]);

  return (
    <>
      {/* Floating, dev-only toggle — makes the drawer discoverable without the
          Shift+P shortcut. Hidden while the drawer is open (it has its own Close). */}
      {/* {!open && (
        <button
          type="button"
          onClick={() => setPanelOpen(true)}
          aria-label="Open scene parameters"
          className="fixed bottom-5 right-5 z-40 flex h-11 w-11 items-center justify-center rounded-full border border-brain-sky/25 bg-brain-void/70 text-base text-brain-sky/80 backdrop-blur-xl hover:border-brain-sky/60 hover:text-white"
        >
          ⚙
        </button>
      )} */}

      <animated.aside
        aria-label="Scene parameters"
        style={{ x: drawer.x, opacity: drawer.opacity, pointerEvents: open ? "auto" : "none" }}
        className="fixed right-0 top-0 z-40 flex h-[100lvh] w-80 flex-col border-l border-brain-sky/15 bg-brain-void/70 backdrop-blur-xl md:w-96"
      >
      <header className="flex items-center justify-between px-6 pb-4 pt-6">
        <p className="text-xs font-semibold uppercase tracking-[0.28em] text-brain-sky/80">
          Parameters
        </p>
        <button
          type="button"
          onClick={() => setPanelOpen(false)}
          aria-label="Close parameters"
          className="rounded-full border border-brain-sky/20 px-3 py-1 text-[0.7rem] uppercase tracking-[0.2em] text-brain-sky/60 hover:border-brain-sky/50 hover:text-white"
        >
          Close
        </button>
      </header>

      {/* data-lenis-prevent: let this scroll natively — Lenis owns the global
          wheel (smoothWheel), so without it the panel's overflow never scrolls. */}
      <div
        data-lenis-prevent
        className="min-h-0 flex-1 space-y-7 overflow-y-auto overscroll-contain px-6 pb-10"
      >
        <Section title="Palette">
          <ColorField label="Lower tint" value={config.brainCool} onChange={(v) => setParam("brainCool", v)} />
          <ColorField label="Upper tint" value={config.brainWarm} onChange={(v) => setParam("brainWarm", v)} />
          <ColorField label="Silhouette" value={config.edgeColor} onChange={(v) => setParam("edgeColor", v)} />
          <ColorField label="Fold depth" value={config.deepColor} onChange={(v) => setParam("deepColor", v)} />
          <ColorField label="Synapse" value={config.synapseColor} onChange={(v) => setParam("synapseColor", v)} />
          <ColorField label="Ambient cloud" value={config.ambientColor} onChange={(v) => setParam("ambientColor", v)} />
          <ColorField label="Background A" value={config.cornerBlue} onChange={(v) => setParam("cornerBlue", v)} />
          <ColorField label="Background B" value={config.cornerOrange} onChange={(v) => setParam("cornerOrange", v)} />
        </Section>

        <Section title="Particles">
          <Range label="Brain size" value={config.particleSize} min={0.005} max={0.08} step={0.001} digits={3} onChange={(v) => setParam("particleSize", v)} />
          <Range label="Ambient size" value={config.ambientSize} min={0.01} max={0.12} step={0.001} digits={3} onChange={(v) => setParam("ambientSize", v)} />
          <CommitRange label="Brain count" value={config.surfaceCount} min={20000} max={600000} step={10000} onChange={(v) => setParam("surfaceCount", v)} />
          <CommitRange label="Ambient count" value={config.ambientCount} min={0} max={40000} step={1000} onChange={(v) => setParam("ambientCount", v)} />
        </Section>

        <Section title="Motion & glow">
          <Range label="Glow" value={config.glowStrength} min={0} max={1} step={0.01} digits={2} onChange={(v) => setParam("glowStrength", v)} />
          <Range label="Flow speed" value={config.flowSpeed} min={0} max={1.5} step={0.01} digits={2} onChange={(v) => setParam("flowSpeed", v)} />
          <Range label="Flow amount" value={config.flowAmount} min={0} max={0.2} step={0.005} digits={3} onChange={(v) => setParam("flowAmount", v)} />
          <Range label="Fold depth strength" value={config.occlusionStrength} min={0} max={1} step={0.01} digits={2} onChange={(v) => setParam("occlusionStrength", v)} />
        </Section>

        <Section title="Cursor">
          <ColorField label="Halo colour" value={config.cursorColor} onChange={(v) => setParam("cursorColor", v)} />
          <Range label="Halo strength" value={config.cursorStrength} min={0} max={3} step={0.01} digits={2} onChange={(v) => setParam("cursorStrength", v)} />
          <Range label="Halo size" value={config.cursorRadius} min={0.02} max={0.3} step={0.005} digits={3} onChange={(v) => setParam("cursorRadius", v)} />
          <Range label="Follow" value={config.cursorFollow} min={0.02} max={1} step={0.01} digits={2} onChange={(v) => setParam("cursorFollow", v)} />
          <Range label="Fade speed" value={config.cursorFade} min={0.01} max={0.5} step={0.01} digits={2} onChange={(v) => setParam("cursorFade", v)} />
          <Range label="Parallax tilt" value={config.cursorParallax} min={0} max={3} step={0.05} digits={2} onChange={(v) => setParam("cursorParallax", v)} />
        </Section>

        <Section title="Bloom">
          <Range label="Strength" value={config.bloomStrength} min={0} max={3} step={0.01} digits={2} onChange={(v) => setParam("bloomStrength", v)} />
          <Range label="Radius" value={config.bloomRadius} min={0} max={1.5} step={0.01} digits={2} onChange={(v) => setParam("bloomRadius", v)} />
          <Range label="Threshold" value={config.bloomThreshold} min={0} max={1} step={0.01} digits={2} onChange={(v) => setParam("bloomThreshold", v)} />
        </Section>

        <Section title="Camera">
          <Toggle label="Auto-rotate" value={camera.autoRotate} onChange={(v) => setCamera("autoRotate", v)} />
          <Range label="Rotate speed" value={camera.autoRotateSpeed} min={0} max={2} step={0.05} digits={2} onChange={(v) => setCamera("autoRotateSpeed", v)} />
        </Section>

        <ConfigExport source={serializeBrainConfig(config)} />

        <button
          type="button"
          onClick={reset}
          className="w-full rounded-lg border border-brain-sky/20 py-2.5 text-xs font-medium uppercase tracking-[0.22em] text-brain-sky/70 hover:border-brain-sky/50 hover:text-white"
        >
          Reset to defaults
        </button>
      </div>
    </animated.aside>
    </>
  );
};

/**
 * The copy-paste config snippet. Mirrors the live values back as the exact
 * `BRAIN_CONFIG` source literal — paste it over the const in
 * `src/components/brain/config.ts` to bake the current look in as the default.
 */
const ConfigExport = ({ source }: { source: string }) => {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(source).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1600);
      },
      () => setCopied(false),
    );
  };
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-[0.65rem] font-semibold uppercase tracking-[0.24em] text-brain-sky/40">
          Export
        </h3>
        <button
          type="button"
          onClick={copy}
          className="rounded-md border border-brain-sky/20 px-2.5 py-1 text-[0.65rem] font-medium uppercase tracking-[0.18em] text-brain-sky/70 hover:border-brain-sky/50 hover:text-white"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <p className="text-[0.65rem] leading-relaxed text-brain-sky/40">
        Paste over <span className="text-brain-sky/70">BRAIN_CONFIG</span> in{" "}
        <span className="text-brain-sky/70">config.ts</span> to make it the default.
      </p>
      <pre className="max-h-48 select-text overflow-auto rounded-lg border border-brain-sky/12 bg-brain-void/60 p-3 font-mono text-[0.6rem] leading-relaxed text-brain-sky/70">
        {source}
      </pre>
    </section>
  );
};

const Section = ({ title, children }: { title: string; children: ReactNode }) => (
  <section className="space-y-3">
    <h3 className="text-[0.65rem] font-semibold uppercase tracking-[0.24em] text-brain-sky/40">
      {title}
    </h3>
    <div className="space-y-3">{children}</div>
  </section>
);

const Row = ({ label, value, children }: { label: string; value: string; children: ReactNode }) => (
  <label className="block space-y-1.5">
    <span className="flex items-baseline justify-between">
      <span className="text-xs font-medium text-brain-sky/75">{label}</span>
      <span className="text-[0.7rem] tabular-nums text-brain-sky/45">{value}</span>
    </span>
    {children}
  </label>
);

const ColorField = ({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) => (
  <Row label={label} value={value.toUpperCase()}>
    <input
      type="color"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-8 w-full cursor-pointer rounded-md border border-brain-sky/15 bg-transparent"
    />
  </Row>
);

const Range = ({
  label,
  value,
  min,
  max,
  step,
  digits,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  digits: number;
  onChange: (value: number) => void;
}) => (
  <Row label={label} value={value.toFixed(digits)}>
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-full accent-brain-azure"
    />
  </Row>
);

/**
 * A range that only commits on release — used for geometry-rebuilding params
 * (counts) so dragging doesn't re-sample the point cloud on every step.
 */
const CommitRange = ({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) => {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    if (draft !== value) onChange(draft);
  };
  return (
    <Row label={label} value={draft.toLocaleString("en-US")}>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={draft}
        onChange={(e) => setDraft(Number(e.target.value))}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
        className="w-full accent-brain-azure"
      />
    </Row>
  );
};

const Toggle = ({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (value: boolean) => void;
}) => (
  <div className="flex items-center justify-between">
    <span className="text-xs font-medium text-brain-sky/75">{label}</span>
    <button
      type="button"
      role="switch"
      aria-checked={value}
      onClick={() => onChange(!value)}
      className={`flex h-5 w-9 items-center rounded-full border px-0.5 ${
        value ? "justify-end border-brain-azure bg-brain-azure/40" : "justify-start border-brain-sky/25 bg-brain-void/60"
      }`}
    >
      <span className="h-3.5 w-3.5 rounded-full bg-brain-sky" />
    </button>
  </div>
);
