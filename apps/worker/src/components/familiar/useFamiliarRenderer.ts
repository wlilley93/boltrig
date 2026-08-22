// The Stage's renderer lifecycle, as a hook.
//
// SPLIT FOR THE SAME REASON JARVIS'S IS (see useJarvisRenderer): the component
// is a picture -- a host div, a fallback badge and a live region -- and this is
// five effects that own a WebGL context. Reading either meant scrolling past
// the other, and the mount effect in particular is the one place a mistake is
// invisible: it deliberately runs ONCE, so anything that belongs in it and gets
// written into one of the prop-watching effects instead simply never happens
// on the first frame.

import { useEffect, useRef, useState } from "react";
import type { FamiliarGenotype, FamiliarPhenotypeResponse } from "@wlilley93/boltrig-web-sdk";
import { FamiliarWebGLRenderer } from "./FamiliarWebGLRenderer";
import type { FamiliarPresentationMode, FamiliarStageState } from "./FamiliarState";

/** Which body is on screen: the premium renderer, the CSS badge, or not yet
 *  decided. `pending` is a real answer and not a loading state -- the Stage
 *  reports it as `aria-busy` until a frame has actually painted. */
export type FamiliarRendererKind = "pending" | "webgl2" | "badge";

export function useFamiliarRenderer(input: {
  // `| null` is React 19's shape: useRef<T>(null) returns RefObject<T | null>
  // there, where React 18 returned RefObject<T>. This file was written on the
  // 18 side of the branch and is the only host ref in the tree still declared
  // the old way; the other sixteen already carry it.
  host: React.RefObject<HTMLDivElement | null>;
  mode: FamiliarPresentationMode;
  state: FamiliarStageState;
  phenotype?: FamiliarPhenotypeResponse | null;
  genotype?: FamiliarGenotype | null;
}): FamiliarRendererKind {
  const { host, mode, state, phenotype, genotype } = input;
  const rendererRef = useRef<FamiliarWebGLRenderer | null>(null);
  const [kind, setKind] = useState<FamiliarRendererKind>("pending");

  // MOUNT ONCE. The genotype is seeded here as well as watched below, because a
  // renderer that linked its program without one would upload the neutral
  // defaults for its first frames and visibly change identity afterwards.
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    let active = true;
    const renderer = new FamiliarWebGLRenderer({
      onFirstPaint: () => {
        if (active) setKind("webgl2");
      },
    });
    renderer.setGenotype(genotype);
    rendererRef.current = renderer;
    renderer.mount(element);
    // Never rewrite the look to survive a failure: fall back to the badge.
    if (renderer.status().state === "failed") setKind("badge");
    return () => {
      active = false;
      renderer.destroy();
      rendererRef.current = null;
    };
  }, []);

  useEffect(() => {
    rendererRef.current?.update(state);
  }, [state]);

  useEffect(() => {
    rendererRef.current?.setMode(mode);
  }, [mode]);

  // A stale projection is handed over as null rather than as its last value: an
  // absent relay must look like a calm creature, not a held expression.
  useEffect(() => {
    rendererRef.current?.applyPhenotype(
      phenotype?.fresh && phenotype.phenotype ? phenotype.phenotype : null,
    );
  }, [phenotype]);

  useEffect(() => {
    rendererRef.current?.setGenotype(genotype);
  }, [genotype]);

  return kind;
}
