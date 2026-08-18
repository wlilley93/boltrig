// The five draw passes that make up an Ultron frame, one function each.
//
// The same split as jarvis/v2/neuralScene, and for the same reason: `drawScene`
// had grown to 126 lines, past the Worker structural floor's 80 (NFR-MNT-07).
// The passes were already independent, so this only names the seam.
//
// Keeping the two bodies the same shape is deliberate. They are read side by
// side whenever a tuning question is "does Jarvis do this too", and a reader
// who has found the Jarvis pass should find Ultron's in the same place.

import { setUniforms, type FloatUniforms } from "../canvas/glResources";
import { ramp, type UltronTuning } from "../canvas/bodyTuning";
import { IRIS_VERTS } from "../canvas/shadersIris";
import { DENDRITE_DEPTH, DENDRITE_SEGMENTS, DENDRITE_TRUNKS } from "./shadersDendrite";
import { CRACK_SEGMENTS, FACET_STRIDE } from "./shadersUltron";

export const GRID = 128;
export const PARTICLES = GRID * GRID;
const FACETS = Math.floor(PARTICLES / FACET_STRIDE);

/** Everything a frame is driven by, derived once by the renderer and shared. */
export interface UltronDrive {
  /** Eight 0..1 voice bands. The membrane reads them as pressure per region. */
  bands: Float32Array;
  /** Overall speech level, so a silent body still holds its shape. */
  voice: number;
  /** Animation seconds. NOT wall clock -- see UltronRenderer.animClock. */
  time: number;
  dt: number;
  energy: number;
  /** 0..1. Drives crack kink, arc frequency and how far shards separate. */
  aggression: number;
  waveT: number;
  waveAmp: number;
  radius: number;
  /** A low continuous breath while speaking, so a held note still moves. */
  swell: number;
}


export function drawDendrites(
  gl: WebGL2RenderingContext, dendrite: WebGLProgram,
  shared: FloatUniforms, d: UltronDrive, tuning: UltronTuning,
): void {
    // THE NEURONS, FIRST. They are the armature the rest of him hangs on, so the
    // membrane and the fractures draw over them rather than under.
    //
    // 558 vertices for the whole tree, against 32768 for the field. Cheap enough
    // that the question is only whether it is right, never whether it fits.
    gl.useProgram(dendrite);
    setUniforms(gl, dendrite, {
      ...shared,
      uGain: ramp(tuning.dendriteGain, d.energy),
      uDend: tuning.dendrite,
      uDendTip: tuning.dendriteTip,
      uBead: tuning.bead,
      uSignal: tuning.signal,
      uArc: tuning.arc,
      uRadius: d.radius,
      // uLimb is set PER PASS, never in `shared` -- so a pass that forgets it
      // gets (0,0), limbMix returns zero, and the whole pass draws nothing while
      // the renderer reports itself healthy. That is how this one debuted.
      uLimb: tuning.veinLimb,
    }, {});
    gl.drawArrays(gl.LINES, 0, DENDRITE_TRUNKS * DENDRITE_SEGMENTS * 2);
}

export function drawIris(
  gl: WebGL2RenderingContext, iris: WebGLProgram,
  shared: FloatUniforms, d: UltronDrive, tuning: UltronTuning,
): void {
    // ------------------------------------------------------------- THE IRIS
    //
    // He has one for the same reason Jarvis does: filaments running radially out
    // of the middle say "this is the centre" from any angle, and without that the
    // dendrites leave the soma in four directions and the eye has nothing to fix
    // on. Concentrated and small -- his brief is a crystalline cloud, so the iris
    // is the thing at the heart of the cloud, not the subject.
    //
    // Drawn FIRST, so the neurons and the crystal composite over it rather than
    // being hidden behind it.
    gl.useProgram(iris);
    setUniforms(gl, iris, {
      ...shared,
      uGain: ramp(tuning.irisGain, d.energy),
      uIrisRadius: tuning.irisRadius,
      uIrisFil: tuning.irisFil,
      uIrisFlow: tuning.irisFlow,
      uRadius: d.radius,
      uBands: d.bands,
    });
    gl.drawArrays(gl.TRIANGLES, 0, IRIS_VERTS);
}

export function drawVeins(
  gl: WebGL2RenderingContext, vein: WebGLProgram,
  shared: FloatUniforms, d: UltronDrive, tuning: UltronTuning,
): void {
    gl.useProgram(vein);
    setUniforms(gl, vein, {
      ...shared,
      // Longer than Jarvis's streak: growth, not data in motion.
      uStreak: ramp(tuning.veinStreak, d.energy),
      uGain: ramp(tuning.veinGain, d.energy),
      uLimb: tuning.veinLimb,
    }, { uState: 0, uGrid: GRID });
    gl.drawArrays(gl.LINES, 0, PARTICLES * 2);
}

export function drawCracks(
  gl: WebGL2RenderingContext, crack: WebGLProgram,
  shared: FloatUniforms, d: UltronDrive, tuning: UltronTuning,
): void {
    gl.useProgram(crack);
    setUniforms(gl, crack, {
      ...shared,
      // Wider than LINK's range: a membrane wants a connected web, where a
      // neural interior wants sparse, flickering connections.
      // "VERY CHAOTIC AND NOT NICE TO LOOK AT" WAS A GAIN ORDER, not a petal
      // count. The three passes ran at vein 0.11 + 0.13e, crack 0.72 + 0.50e
      // and facet 0.78 + 0.55e -- so the jagged web and the loose shards were
      // each roughly six times the body they were supposed to be cracking, and
      // he read as a swarm of debris with nothing inside it. Reducing the
      // petals addressed the reaching arms and could not have addressed this.
      //
      // The range matters as much as the gain, and separately. It is the
      // distance under which a pair counts as connected, and at 0.26 -- against
      // Jarvis's 0.16 at the time -- the web was drawing long wires straight
      // across the volume, which is most of what "chaotic" was describing.
      // Tightened, the cracks are local again: they run along the surface
      // rather than through the middle.
      //
      // HE IS STILL NOT JARVIS IN BLUE. The separation is silhouette and
      // colour -- petals against a plain shell, cold against warm -- which is
      // how Animal Logic separated them. It was never brightness.
      uLinkRange: tuning.crackRange,
      uGain: ramp(tuning.crackGain, d.energy),
      uLimb: tuning.crackLimb,
    }, { uState: 0, uGrid: GRID, uSegments: CRACK_SEGMENTS });
    gl.drawArrays(gl.LINES, 0, PARTICLES * CRACK_SEGMENTS * 2);
}

export function drawFacets(
  gl: WebGL2RenderingContext, facet: WebGLProgram,
  shared: FloatUniforms, d: UltronDrive, tuning: UltronTuning,
): void {
    gl.useProgram(facet);
    // Nearly twice Jarvis's shard at 0.030, and brighter than everything else
    // on screen. Both halves of that were why the facets read as the subject
    // rather than as fracture ON a subject.
    setUniforms(gl, facet, {
      ...shared,
      uSize: tuning.facetSize,
      uGain: ramp(tuning.facetGain, d.energy),
      uLimb: tuning.facetLimb,
      uFacetSpin: tuning.facetSpin,
    },
      { uState: 0, uGrid: GRID, uStride: FACET_STRIDE });
    gl.drawArrays(gl.LINES, 0, FACETS * 4);
}
