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

import { setUniforms, type FloatUniforms } from "../../canvas/glResources";
import { ramp, type JarvisTuning } from "../../canvas/bodyTuning";
import { GRID, PARTICLES, shardCount, type Drive } from "./neuralPasses";
import { LINK_SEGMENTS } from "./shadersField";
import { GLYPH_VERTS } from "./shadersGlyph";
import { IRIS_VERTS } from "../../canvas/shadersIris";
import { RING_SEGMENTS } from "./shadersRing";

export function drawRing(
gl: WebGL2RenderingContext, progs: Record<string, WebGLProgram>,
d: Drive, tuning: JarvisTuning, shared: FloatUniforms,
): void {
  // THE EXTERIOR WHEELS, DRAWN FIRST so the field lies over them.
  //
  // They were off, and the note here gave the reason: bright arcs turning at
  // the limb read as solar flares around the edge. That was true of their GAIN
  // and their SPEED, and it was taken as a reason to have no crest at all --
  // but the reference frame plainly has one. Side by side with this body, the
  // difference that reads first is not colour or density: it is that the
  // reference has SURFACES. Thick great-circle bands sweeping round a bright
  // centre, with a feathered fan of them at the limb. That is this pass.
  //
  // Back at roughly a fifth of the field's brightness and a third of the old
  // rate, both on sliders, so "orbiting slowly" is something you set rather
  // than something you re-derive.
  //
  // Cheap, too: six rings of 420 elements is 5040 vertices against the field's
  // 32768, and they are the part of the design a viewer actually recognises.
  const ring = progs.ring;
  gl.useProgram(ring);
  setUniforms(gl, ring, {
    ...shared,
    uGain: ramp(tuning.ringGain, d.energy),
    uRingSpin: tuning.ringSpin,
    uRingLife: tuning.ringLife,
    uRingArc: tuning.ringArc,
    uRingWidth: tuning.ringWidth,
    uRingRadius: tuning.ringRadius,
    uBeam: tuning.ringBeam,
    uRadius: d.radius,
    uBands: d.bands,
  }, { uSegments: RING_SEGMENTS, uRings: tuning.rings });
  gl.drawArrays(gl.TRIANGLES, 0, tuning.rings * RING_SEGMENTS * 6);
}

export function drawGlyph(
gl: WebGL2RenderingContext, progs: Record<string, WebGLProgram>,
d: Drive, tuning: JarvisTuning, shared: FloatUniforms,
): void {
  // ------------------------------------------------------------ GLYPH layers
  //
  // Its own program and its own uniforms, so the inscriptions can be tuned
  // without touching the wheels. Sharing a channel is what lost them last time.
  const glyph = progs.glyph;
  gl.useProgram(glyph);
  setUniforms(gl, glyph, {
    ...shared,
    // The phenotype is already folded into `tuning` by jarvisEmotion before this
    // is called, so there is no mood to apply again here -- doing so would apply
    // brightness twice and make an attentive body wash out.
    uGain: ramp(tuning.glyphGain, d.energy),
    uGlyphRadius: tuning.glyphRadius,
    uGlyphSize: tuning.glyphSize,
    uGlyphSpin: tuning.glyphSpin,
    uGlyphDensity: tuning.glyphDensity,
    uRadius: d.radius,
    uBands: d.bands,
  });
  gl.drawArrays(gl.TRIANGLES, 0, GLYPH_VERTS);
}

export function drawIris(
gl: WebGL2RenderingContext, progs: Record<string, WebGLProgram>,
d: Drive, tuning: JarvisTuning, shared: FloatUniforms,
): void {
  // ---------------------------------------------------------------- THE IRIS
  //
  // After the glyph layers and before the field, so the particles draw over its
  // outer reaches while it still sits on top of the inscriptions. It replaces the
  // LINK pass as the centre's structure -- see irisGain in bodyTuning.
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

export function drawLink(
gl: WebGL2RenderingContext, progs: Record<string, WebGLProgram>,
d: Drive, tuning: JarvisTuning, shared: FloatUniforms,
): void {
  const link = progs.link;
  gl.useProgram(link);
  // Wider as well as brighter. The range is the distance under which a
  // texture-neighbour pair counts as connected at all, so widening it is what
  // makes the graph DENSE; brightening a sparse graph just gives brighter
  // gaps.
  setUniforms(gl, link, {
    ...shared,
    uGain: ramp(tuning.linkGain, d.energy),
    uLinkRange: tuning.linkRange,
    uLimb: tuning.linkLimb,
    uLinkBow: tuning.linkBow,
    uClump: tuning.clump,
  }, { uState: 0, uGrid: GRID });
  gl.drawArrays(gl.LINES, 0, PARTICLES * LINK_SEGMENTS * 2);
}

export function drawParticleLayers(
gl: WebGL2RenderingContext, progs: Record<string, WebGLProgram>,
d: Drive, tuning: JarvisTuning, shared: FloatUniforms,
): void {
  // ------------------------------------------------------- TWO PARTICLE LAYERS
  //
  // The inner cloud and the outer shell are drawn separately so each can carry
  // its own brightness, trail length and silhouette. They were one draw with one
  // set of uniforms, and an outer sphere that shares the interior's gain and
  // streak does not read as a distant surface -- it reads as the same cloud
  // sprayed wider, which is exactly how it looked.
  //
  // The inner layer draws SECOND, so the near cloud composites over the shell
  // rather than under it. Additive blending makes the order matter less than it
  // would, but the fringe test is not additive and the shell would otherwise
  // punch through the middle of the body.
  const draw = progs.draw;
  gl.useProgram(draw);
  for (const layer of [1, 0]) {
    const outer = layer === 1;
    setUniforms(gl, draw, {
      ...shared,
      uLayer: layer,
      uStreak: ramp(outer ? tuning.outerStreak : tuning.streak, d.energy),
      uGain: ramp(outer ? tuning.outerGain : tuning.drawGain, d.energy),
      uLimb: outer ? tuning.outerLimb : tuning.drawLimb,
      uClump: tuning.clump,
      // THE FRINGE FLOOR IS PER LAYER, and this is the third pass to be bitten
      // by it not being.
      //
      // fringeShade zeroes anything below uInner / uFringeScale -- 0.52 / 2.4 =
      // 0.217 -- and it exists for one reason: sixteen thousand additive
      // particles overlapping in the middle of the frame climb one colour ramp
      // together until the centre goes white. That is a STACKING defence.
      //
      // The outer layer does not stack. It is a thin shell, deliberately dim: a
      // gain around 0.42 multiplied by outerFade's 0.28 puts almost every shell
      // particle under the floor, so the entire layer was culled and drew
      // NOTHING. Measured: the shell annulus read 0.00022 with the population at
      // 0.6, and zeroing the INNER layer's gain took even that away -- because
      // what was out there was inner-layer strays, not the shell.
      //
      // The rings and the dendrites each hit this same floor and each fixed it by
      // dropping the fringe entirely. A shell of particles genuinely does want
      // some, so it gets a floor proportionate to its brightness instead.
      uInner: outer ? 0.12 : 0.52,
    }, { uState: 0, uGrid: GRID });
    gl.drawArrays(gl.LINES, 0, PARTICLES * 2);
  }
}

export function drawShard(
gl: WebGL2RenderingContext, progs: Record<string, WebGLProgram>,
d: Drive, tuning: JarvisTuning, shared: FloatUniforms,
): void {
  const shard = progs.shard;
  gl.useProgram(shard);
  setUniforms(gl, shard, {
    ...shared,
    uSize: tuning.shardSize,
    uGain: ramp(tuning.shardGain, d.energy),
    uLimb: tuning.drawLimb,
    uClump: tuning.clump,
    uFocus: tuning.focus,
  }, { uState: 0, uGrid: GRID, uStride: tuning.shardStride });
  gl.drawArrays(gl.TRIANGLES, 0, shardCount(tuning.shardStride) * 6);
}
