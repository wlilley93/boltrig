// General Montgomery's canvas source, and the character built on it.
//
// EXTRACTED FROM characters.ts, which the structural ratchet stopped at
// 430/400 lines when he was added inline. That is the gate doing its job: the
// registry module is a list of who can be on the Stage, and a body that needs
// a config, a source and three comments explaining why it is not a shader had
// outgrown a slot in a list.
//
// It sits beside the body it describes rather than in components/, for the
// same reason a bundle owns its own shader: everything that knows what a
// frame-graph character is now lives in one directory.
import { createElement } from "react";
import montgomeryBundle from "../../bundles/general-montgomery/character.json";
import { characterFromBundle, type CharacterCanvasSource } from "../characterBundle";
import { FrameGraphStage } from "./FrameGraphStage";
import { montgomeryStateFromTurn } from "./MontgomeryState";

/**
 * The same test `desktop.ts` makes, restated rather than imported.
 *
 * Importing it would put the desktop module in the import graph of the
 * CHARACTER REGISTRY, which almost every component pulls in -- and six test
 * files mock `../src/desktop` with their own inline fixture, so every one of
 * them would have to grow an `isDesktop` export or fail at import time. A
 * one-line platform check is not worth that blast radius.
 *
 * It is a second copy, so it is gated: montgomeryPlayerUrl.test.ts asserts this
 * agrees with `desktop.ts`. Two copies of a rule is one copy and a
 * disagreement, unless something is checking.
 */
function onDesktop(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/**
 * His player. Loopback, and the renderer refuses anything else because this
 * value doubles as the postMessage target origin.
 *
 * A build where the player is not running shows an empty frame rather than an
 * error, which is the one weakness of embedding a process instead of drawing a
 * canvas. That is the same bargain the voice runtime already makes.
 */
const MONTGOMERY_CONFIG = {
  id: "general-montgomery",
  library: "GeneralMontgomery",
  // WHERE HIS PLAYER IS DEPENDS ON WHO IS ASKING, and there are only two
  // answers because there are only two kinds of surface.
  //
  // HOSTED (web, and a cell's own UI): the player is served from THIS origin at
  // /companion/montgomery/. It has to be -- a browser on dev.boltrig.ai
  // resolves `localhost` to the VIEWER's machine, where there is no player and
  // never will be. Same-origin is also tighter than loopback: the frame is the
  // app, so `frame-src 'self'` covers it.
  //
  // DESKTOP: localhost genuinely IS the user's machine, and the player is a
  // sidecar beside the app. That port is also pinned in the desktop CSP
  // (src-tauri/tauri.conf.json, `frame-src http://localhost:8902`) and the two
  // must agree -- changing one without the other raises no error, it refuses
  // the frame and shows an empty stage, which looks exactly like a player that
  // is not running.
  playerUrl: onDesktop() ? "http://localhost:8902" : "/companion/montgomery/",
  voiceBase: "montgomery",
};

/**
 * The companion source -- the FIFTH, and the first that is not a shader at all.
 *
 * The other four differ in which channels they drive. This one differs in what
 * a body IS. There is no canvas, no uniform loop and no simulation: General
 * Montgomery is a man in a room, rendered ahead of time as a closed graph of
 * clips joined byte-exactly at hub frames, and the thing on screen is a video
 * element seeking between them.
 *
 * WHY IT IS PUBLIC NOW, when the note this replaces said it never would be.
 * That note said "the companion source -- the proprietary .frame.mp4 reader --
 * is deliberately absent from the public build", and it was right about the
 * READER. The reader is a separate local process that owns the 142MB bundle
 * and its uuid-box graph, and it is still not here. What ships is an iframe
 * onto it and a postMessage bridge, which is no more proprietary than the
 * fetch that reaches the voice runtime.
 *
 * WHAT IT SUPPLIES IS SELECTION, NOT DRAWING. `supplies` is empty because
 * there are no uniforms to drive; what this source implements is the emotion
 * model, and naming it is what lets a bundle asking for one this canvas does
 * not implement be refused out loud rather than rendering as stillness.
 */
const COMPANION_SOURCE: CharacterCanvasSource = {
  id: "boltrig.canvas.companion",
  type: "companion",
  // `graph-directed`: ambient tags drift inside the player on their own
  // adjacency walk, and only the directed three are ever pushed from here. A
  // surprised face never appears without a surprise.
  emotionModels: ["graph-directed"],
  render: ({ input, mode, phenotype, label }) =>
    createElement(FrameGraphStage, {
      config: MONTGOMERY_CONFIG,
      label,
      mode,
      phenotype,
      state: montgomeryStateFromTurn(input),
    }),
};

/**
 * General Montgomery, from his bundle like the other four. He SHIPS: his
 * constitution says so, his prompts and voice registers travel in the manifest,
 * and the part that stays out of this build is the player, not the character.
 */
export const MONTGOMERY = characterFromBundle(montgomeryBundle, [COMPANION_SOURCE]);

