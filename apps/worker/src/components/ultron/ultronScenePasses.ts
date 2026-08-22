// The scene passes, one function per program, in the order they draw.
//
// They were methods on NeuralPasses and before that one 166-line drawScene. The
// method extraction made the sequence legible but made the FILE longer -- six
// signatures on a module already over the worker's 400-line floor, which cannot
// be pinned because the structure gate refuses a new debt entry. They need
// nothing from the class except the GL context and the compiled programs, so
// out here they cost the class one import and take their reasoning with them.
//
// ORDER IS THE POINT. What draws over what is the design; drawScene calls these
// in exactly the sequence they appear below.

import { setUniforms, type FloatUniforms } from "../canvas/glResources";
import { ramp, type UltronTuning } from "../canvas/bodyTuning";
import { FACETS, GRID, PARTICLES, type UltronDrive } from "./ultronPasses";
import { IRIS_VERTS } from "../canvas/shadersIris";
import {
  DENDRITE_DEPTH,
  DENDRITE_SEGMENTS,
  DENDRITE_TRUNKS,
} from "./shadersDendrite";
import { CRACK_SEGMENTS, FACET_STRIDE } from "./shadersUltron";

export function drawMembrane(
gl: WebGL2RenderingContext, progs: Record<string, WebGLProgram>,
d: UltronDrive, tuning: UltronTuning, shared: FloatUniforms,
): void {
  // THE BODY ITSELF, UNDER EVERYTHING. The analytic shell is the ground the
  // structural passes read against -- drawn first so veins, cracks and facets
  // sit ON a surface instead of floating in the dark, which is the difference
  // between fracture on a membrane and debris in a void.
  const membrane = progs.membrane;
  gl.useProgram(membrane);
  setUniforms(gl, membrane, {
    ...shared,
    uGain: ramp(tuning.membraneGain, d.energy),
    uMembrane: tuning.membrane,
    uRadius: d.radius,
  }, {});
  gl.drawArrays(gl.TRIANGLES, 0, 3);
}

export function drawDendrite(
gl: WebGL2RenderingContext, progs: Record<string, WebGLProgram>,
d: UltronDrive, tuning: UltronTuning, shared: FloatUniforms,
): void {
  // THE NEURONS, FIRST. They are the armature the rest of him hangs on, so the
  // membrane and the fractures draw over them rather than under.
  //
  // 558 vertices for the whole tree, against 32768 for the field. Cheap enough
  // that the question is only whether it is right, never whether it fits.
  const dendrite = progs.dendrite;
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
gl: WebGL2RenderingContext, progs: Record<string, WebGLProgram>,
d: UltronDrive, tuning: UltronTuning, shared: FloatUniforms,
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
  const iris = progs.iris;
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

export function drawVein(
gl: WebGL2RenderingContext, progs: Record<string, WebGLProgram>,
d: UltronDrive, tuning: UltronTuning, shared: FloatUniforms,
): void {
  const vein = progs.vein;
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

export function drawCrack(
gl: WebGL2RenderingContext, progs: Record<string, WebGLProgram>,
d: UltronDrive, tuning: UltronTuning, shared: FloatUniforms,
): void {
  const crack = progs.crack;
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

export function drawFacet(
gl: WebGL2RenderingContext, progs: Record<string, WebGLProgram>,
d: UltronDrive, tuning: UltronTuning, shared: FloatUniforms,
): void {
  const facet = progs.facet;
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
