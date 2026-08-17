// Ultron's GPU object graph and pass order.
//
// A SIBLING OF NeuralPasses, NOT A SUBCLASS. The two share a substrate --
// components/canvas carries the curl field, the advection pass, the projection,
// the bloom and the composite -- and nothing else. Parameterising one class to
// draw both would have meant a flag deciding whether to run the data rings or
// the fracture facets, and that flag would be the seam along which the two
// characters slowly became one with different colours.
//
// PASS ORDER:
//
//   SIM     advect every particle (shared)
//   VEIN    the filaments, longer and slower than Jarvis's streaks
//   CRACK   the jagged proximity web -- his silhouette
//   FACET   triangular shards lifting off the surface
//   BLOOM   shared
//   (composite is the renderer's, because it targets the canvas)

import {
  createProgram,
  createStateTarget,
  createTarget,
  seedParticles,
  setUniforms,
  type FloatUniforms,
} from "../canvas/glResources";
import { ULTRON_TUNING, pulsedCore, ramp, type UltronTuning } from "../canvas/bodyTuning";
import { BLOOM_FRAG, COMPOSITE_FRAG } from "../canvas/shadersPost";
import { QUAD_VERT, SIM_FRAG } from "../canvas/shadersSim";
import {
  DENDRITE_DEPTH,
  DENDRITE_FRAG,
  DENDRITE_SEGMENTS,
  DENDRITE_TRUNKS,
  DENDRITE_VERT,
} from "./shadersDendrite";
import {
  CRACK_FRAG,
  CRACK_SEGMENTS,
  CRACK_VERT,
  FACET_FRAG,
  FACET_STRIDE,
  FACET_VERT,
  VEIN_FRAG,
  VEIN_VERT,
} from "./shadersUltron";

const GRID = 128;
const PARTICLES = GRID * GRID;
const FACETS = Math.floor(PARTICLES / FACET_STRIDE);
const BLOOM_DIV = 2;

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

export class UltronPasses {
  private progs: Record<string, WebGLProgram> = {};
  private quad: WebGLBuffer | null = null;
  private vao: WebGLVertexArrayObject | null = null;
  private simTex: WebGLTexture[] = [];
  private simFbo: WebGLFramebuffer[] = [];
  private sceneTex: WebGLTexture | null = null;
  private sceneFbo: WebGLFramebuffer | null = null;
  private blurTex: WebGLTexture[] = [];
  private blurFbo: WebGLFramebuffer[] = [];
  private ping = 0;
  private size: [number, number] = [0, 0];

  constructor(private readonly gl: WebGL2RenderingContext) {}

  init(): void {
    const gl = this.gl;
    this.progs = {
      sim: createProgram(gl, QUAD_VERT, SIM_FRAG),
      dendrite: createProgram(gl, DENDRITE_VERT, DENDRITE_FRAG),
      vein: createProgram(gl, VEIN_VERT, VEIN_FRAG),
      crack: createProgram(gl, CRACK_VERT, CRACK_FRAG),
      facet: createProgram(gl, FACET_VERT, FACET_FRAG),
      bloom: createProgram(gl, QUAD_VERT, BLOOM_FRAG),
      comp: createProgram(gl, QUAD_VERT, COMPOSITE_FRAG),
    };

    const seed = seedParticles(PARTICLES);
    for (let i = 0; i < 2; i++) {
      const [tex, fbo] = createStateTarget(gl, GRID, i === 0 ? seed : null);
      this.simTex.push(tex);
      this.simFbo.push(fbo);
    }

    this.quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    this.vao = gl.createVertexArray();
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  }

  resize(width: number, height: number): void {
    const gl = this.gl;
    if (width === this.size[0] && height === this.size[1]) return;
    this.size = [width, height];
    [this.sceneFbo, ...this.blurFbo].forEach((f) => f && gl.deleteFramebuffer(f));
    [this.sceneTex, ...this.blurTex].forEach((t) => t && gl.deleteTexture(t));
    this.blurTex = [];
    this.blurFbo = [];
    const [tex, fbo] = createTarget(gl, width, height);
    this.sceneTex = tex;
    this.sceneFbo = fbo;
    for (let i = 0; i < 2; i++) {
      const [t, f] = createTarget(gl,
        Math.max(1, Math.floor(width / BLOOM_DIV)), Math.max(1, Math.floor(height / BLOOM_DIV)));
      this.blurTex.push(t);
      this.blurFbo.push(f);
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  }

  /** One frame. `tuning` defaults to what ships; only the bench overrides it. */
  render(d: UltronDrive, palette: FloatUniforms, tuning: UltronTuning = ULTRON_TUNING): void {
    this.simulate(d, tuning);
    this.drawScene(d, palette, tuning);
    this.bloom();
    this.composite(palette, pulsedCore(tuning.core, d.energy, d.bands), 0.0, tuning.eye);
  }

  destroy(): void {
    const gl = this.gl;
    [...this.simFbo, ...this.blurFbo, this.sceneFbo].forEach((f) => f && gl.deleteFramebuffer(f));
    [...this.simTex, ...this.blurTex, this.sceneTex].forEach((t) => t && gl.deleteTexture(t));
    Object.values(this.progs).forEach((p) => gl.deleteProgram(p));
    if (this.quad) gl.deleteBuffer(this.quad);
    if (this.vao) gl.deleteVertexArray(this.vao);
  }

  private fullscreen(prog: WebGLProgram): void {
    const gl = this.gl;
    gl.useProgram(prog);
    gl.bindVertexArray(this.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  private simulate(d: UltronDrive, tuning: UltronTuning): void {
    const gl = this.gl;
    const prog = this.progs.sim;
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.simFbo[1 - this.ping]);
    gl.viewport(0, 0, GRID, GRID);
    gl.disable(gl.BLEND);
    gl.useProgram(prog);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.simTex[this.ping]);
    setUniforms(gl, prog, {
      uTime: d.time, uDt: d.dt, uEnergy: d.energy, uRadius: d.radius,
      uWaveT: d.waveT, uWaveAmp: d.waveAmp,
      // Three concentric clouds reaching out in arms; Jarvis leaves this at 0
      // and keeps the plain shell. The value and its reasoning now live in
      // canvas/bodyTuning, so the bench can move it while you watch.
      uPetal: tuning.petal,
      uSwirl: tuning.swirl,
      // Ultron has ONE particle layer. Zero is the no-change offset, set
      // explicitly rather than left to default so the intent is on the page: he
      // shares canvas/shadersSim.ts, so the uniform exists in his program too.
      uLayerPace: [0, 0],
      uOuter: tuning.outerShell,
    }, { uState: 0 });
    this.fullscreen(prog);
    this.ping = 1 - this.ping;
  }

  private drawScene(d: UltronDrive, palette: FloatUniforms, tuning: UltronTuning): void {
    const gl = this.gl;
    const [w, h] = this.size;
    const aspect = w / Math.max(1, h);
    const shared: FloatUniforms = {
      ...palette, uTime: d.time, uAspect: aspect, uEnergy: d.energy,
      uAggression: d.aggression, uBands: d.bands, uVoice: d.voice,
      // The wavefront reaches the DRAW passes, not only SIM: there it is a
      // force, here it is light, and only the second one is visible.
      uWaveT: d.waveT, uWaveAmp: d.waveAmp, uSwell: d.swell,
      uReverb: tuning.reverb,
      uSwirl: tuning.swirl,
      uOuter: tuning.outerShell,
    };

    gl.bindFramebuffer(gl.FRAMEBUFFER, this.sceneFbo);
    gl.viewport(0, 0, w, h);
    gl.clearColor(0, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
    gl.bindVertexArray(this.vao);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.simTex[this.ping]);

    // THE NEURONS, FIRST. They are the armature the rest of him hangs on, so the
    // membrane and the fractures draw over them rather than under.
    //
    // 558 vertices for the whole tree, against 32768 for the field. Cheap enough
    // that the question is only whether it is right, never whether it fits.
    const dendrite = this.progs.dendrite;
    gl.useProgram(dendrite);
    setUniforms(gl, dendrite, {
      ...shared,
      uGain: ramp(tuning.dendriteGain, d.energy),
      uDend: tuning.dendrite,
      uDendTip: tuning.dendriteTip,
      uBead: tuning.bead,
      uRadius: d.radius,
      // uLimb is set PER PASS, never in `shared` -- so a pass that forgets it
      // gets (0,0), limbMix returns zero, and the whole pass draws nothing while
      // the renderer reports itself healthy. That is how this one debuted.
      uLimb: tuning.veinLimb,
    }, {});
    gl.drawArrays(gl.LINES, 0, DENDRITE_TRUNKS * DENDRITE_SEGMENTS * 2);

    const vein = this.progs.vein;
    gl.useProgram(vein);
    setUniforms(gl, vein, {
      ...shared,
      // Longer than Jarvis's streak: growth, not data in motion.
      uStreak: ramp(tuning.veinStreak, d.energy),
      uGain: ramp(tuning.veinGain, d.energy),
      uLimb: tuning.veinLimb,
    }, { uState: 0, uGrid: GRID });
    gl.drawArrays(gl.LINES, 0, PARTICLES * 2);

    const crack = this.progs.crack;
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

    const facet = this.progs.facet;
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

  private bloom(): void {
    const gl = this.gl;
    const [w, h] = this.size;
    const bw = Math.max(1, Math.floor(w / BLOOM_DIV));
    const bh = Math.max(1, Math.floor(h / BLOOM_DIV));
    const prog = this.progs.bloom;
    gl.disable(gl.BLEND);
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.blurFbo[0]);
    gl.viewport(0, 0, bw, bh);
    gl.useProgram(prog);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.sceneTex);
    setUniforms(gl, prog, { uDir: [1.6 / bw, 0], uThreshold: 0.45 }, { uSrc: 0 });
    this.fullscreen(prog);

    gl.bindFramebuffer(gl.FRAMEBUFFER, this.blurFbo[1]);
    gl.bindTexture(gl.TEXTURE_2D, this.blurTex[0]);
    setUniforms(gl, prog, { uDir: [0, 1.6 / bh], uThreshold: -1.0 }, { uSrc: 0 });
    this.fullscreen(prog);
  }

  private composite(
    palette: FloatUniforms, core: number, starburst: number,
    // Passed in rather than read off a field: this method has no tuning of its
    // own, and reaching for one is what made it fail to compile.
    eye: readonly number[],
  ): void {
    const gl = this.gl;
    const [w, h] = this.size;
    const prog = this.progs.comp;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, w, h);
    gl.useProgram(prog);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.sceneTex);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.blurTex[1]);
    setUniforms(gl, prog, {
      ...palette, uAspect: w / Math.max(1, h), uBloomGain: 1.05,
      uCore: core, uStarburst: starburst, uEye: eye,
    }, { uScene: 0, uBloom: 1 });
    this.fullscreen(prog);
    gl.activeTexture(gl.TEXTURE0);
  }
}
