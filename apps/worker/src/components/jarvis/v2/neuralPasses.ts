// The GPU object graph and the passes that run against it.
//
// Split from JarvisNeuralRenderer on the seam between LIFECYCLE and RENDERING:
// the renderer owns the host element, the state, the clock and the rAF loop;
// this owns every WebGL object and knows the order the passes run in. Neither
// half fits the worker's 400-line structural floor with the other attached, and
// the seam is a real one rather than a slice taken to satisfy the gate.
//
// PASS ORDER, and why it is this order:
//
//   SIM     advect every particle; writes the state texture, reads the other
//   RING    the exterior platters -- FIRST, so the field draws over them
//   LINK    connections; dim, behind the streaks
//   DRAW    the velocity-stretched streaks
//   SHARD   circuit fragments; last of the additive passes, so they sit on top
//   BLOOM   bright-pass then separable Gaussian, half resolution
//   (the composite is the renderer's, because it targets the canvas)

import {
  createProgram,
  createStateTarget,
  createTarget,
  seedParticles,
  setUniforms,
  type FloatUniforms,
} from "../../canvas/glResources";
import { JARVIS_TUNING, pulsedCore, ramp, type JarvisTuning } from "../../canvas/bodyTuning";
import { BLOOM_FRAG, COMPOSITE_FRAG } from "../../canvas/shadersPost";
import { DRAW_FRAG, DRAW_VERT, LINK_FRAG, LINK_VERT } from "./shadersField";
import { QUAD_VERT, SIM_FRAG } from "../../canvas/shadersSim";
import { GLYPH_FRAG, GLYPH_VERT } from "./shadersGlyph";
import { IRIS_FRAG, IRIS_VERT } from "../../canvas/shadersIris";
import { RING_FRAG, RING_VERT, SHARD_FRAG, SHARD_VERT } from "./shadersRing";
import {
  GRID,
  PARTICLES,
  drawGlyphs,
  drawIris,
  drawLinks,
  drawParticles,
  drawRings,
  drawShards,
  type Drive,
} from "./neuralScene";

export { GRID, PARTICLES, type Drive };

/** Half-resolution bloom. Quarter looked soft at the core; full res bought
 *  nothing visible for four times the bandwidth. */
const BLOOM_DIV = 2;

export class NeuralPasses {
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

  /** Compiles everything and seeds the simulation. Throws; the caller reports. */
  init(): void {
    const gl = this.gl;
    this.progs = {
      sim: createProgram(gl, QUAD_VERT, SIM_FRAG),
      link: createProgram(gl, LINK_VERT, LINK_FRAG),
      draw: createProgram(gl, DRAW_VERT, DRAW_FRAG),
      ring: createProgram(gl, RING_VERT, RING_FRAG),
      glyph: createProgram(gl, GLYPH_VERT, GLYPH_FRAG),
      iris: createProgram(gl, IRIS_VERT, IRIS_FRAG),
      shard: createProgram(gl, SHARD_VERT, SHARD_FRAG),
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

  /** Reallocates the scene and blur targets. A no-op at an unchanged size. */
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

  /**
   * One frame.
   *
   * `tuning` defaults to what ships, so every existing caller is unaffected and
   * the bench is the only thing that ever passes anything else.
   */
  render(d: Drive, palette: FloatUniforms, tuning: JarvisTuning = JARVIS_TUNING): void {
    this.simulate(d, tuning);
    this.drawScene(d, palette, tuning);
    this.bloom();
    this.composite(palette, pulsedCore(tuning.core, d.energy, d.bands), tuning.starburst, tuning.eye);
  }

  destroy(): void {
    const gl = this.gl;
    [...this.simFbo, ...this.blurFbo, this.sceneFbo].forEach((f) => f && gl.deleteFramebuffer(f));
    [...this.simTex, ...this.blurTex, this.sceneTex].forEach((t) => t && gl.deleteTexture(t));
    Object.values(this.progs).forEach((p) => gl.deleteProgram(p));
    if (this.quad) gl.deleteBuffer(this.quad);
    if (this.vao) gl.deleteVertexArray(this.vao);
  }

  // ------------------------------------------------------------------ passes

  private fullscreen(prog: WebGLProgram): void {
    const gl = this.gl;
    gl.useProgram(prog);
    gl.bindVertexArray(this.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  private simulate(d: Drive, tuning: JarvisTuning): void {
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
      // The simulation integrates the same rate every draw pass walks backwards
      // along, so it has to be handed the same value or the motion blur points
      // where the particle is not going.
      uSwirl: tuning.swirl,
      uLayerPace: [0, tuning.outerPace],
      uOuter: tuning.outerShell,
    }, { uState: 0 });
    this.fullscreen(prog);
    this.ping = 1 - this.ping;
  }

  private drawScene(d: Drive, palette: FloatUniforms, tuning: JarvisTuning): void {
    const gl = this.gl;
    const [w, h] = this.size;
    const aspect = w / Math.max(1, h);
    const shared: FloatUniforms = {
      ...palette, uTime: d.time, uAspect: aspect, uEnergy: d.energy,
      // The wavefront, to the DRAW passes. SIM already has these and uses them
      // as a force; the draws use them as light, which is what makes the pulse
      // visible rather than merely real.
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

    // THE ORDER IS THE PICTURE, which is why it is legible here and the pass
    // bodies are not. The exterior wheels go down first so the field lies over
    // them; the iris sits after the inscriptions and before the particles; the
    // inner cloud draws last so it composites over the shell rather than under.
    drawRings(gl, this.progs.ring, shared, d, tuning);
    drawGlyphs(gl, this.progs.glyph, shared, d, tuning);
    drawIris(gl, this.progs.iris, shared, d, tuning);
    drawLinks(gl, this.progs.link, shared, d, tuning);
    drawParticles(gl, this.progs.draw, shared, d, tuning);
    drawShards(gl, this.progs.shard, shared, d, tuning);
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
    setUniforms(gl, prog, { uDir: [1.6 / bw, 0], uThreshold: 0.55 }, { uSrc: 0 });
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
      ...palette, uAspect: w / Math.max(1, h), uBloomGain: 0.85,
      uCore: core, uStarburst: starburst, uEye: eye,
    }, { uScene: 0, uBloom: 1 });
    this.fullscreen(prog);
    gl.activeTexture(gl.TEXTURE0);
  }
}
