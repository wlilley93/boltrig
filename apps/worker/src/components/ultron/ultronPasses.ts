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
import { IRIS_FRAG, IRIS_VERT, IRIS_VERTS } from "../canvas/shadersIris";
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

export const GRID = 128;
export const PARTICLES = GRID * GRID;
export const FACETS = Math.floor(PARTICLES / FACET_STRIDE);
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

import {
  drawDendrite,
  drawIris,
  drawVein,
  drawCrack,
  drawFacet,
} from "./ultronScenePasses";

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
      iris: createProgram(gl, IRIS_VERT, IRIS_FRAG),
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
      uCloud: tuning.cloud,
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

    drawDendrite(gl, this.progs, d, tuning, shared);
    drawIris(gl, this.progs, d, tuning, shared);
    drawVein(gl, this.progs, d, tuning, shared);
    drawCrack(gl, this.progs, d, tuning, shared);
    drawFacet(gl, this.progs, d, tuning, shared);
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
