// Colossus's GPU object graph and pass order.
//
// FAR SIMPLER THAN THE OTHER THREE, and that is the design rather than a
// shortcut. Familiar, Jarvis and Ultron are particle simulations: a state
// texture, an advection pass, ping-pong buffers, geometry drawn from the
// simulation. A lamp panel has no state to integrate. Every lamp's brightness
// is a closed-form function of position and time, so the whole body is one
// fullscreen fragment pass -- no simulation, no float extension, no ping-pong.
//
// It also means he runs where they do not. The other three fail closed without
// EXT_color_buffer_float; this needs plain WebGL2 and half-float targets, which
// is worth stating because the fallback surface for a panel is much worse than
// for an orb -- an orb degrades to a gradient, a sign degrades to a blank.
//
// PASS ORDER:
//
//   PANEL      the lamps, the ticker, the fields, the counter -> scene target
//   BLOOM x2   separable bright-pass blur at half res (shared with the others)
//   COMPOSITE  vignette, glass sheen, tone -- his own, not the shared one

import {
  createProgram,
  setUniforms,
  type FloatUniforms,
} from "../canvas/glResources";
import { BLOOM_FRAG } from "../canvas/shadersPost";
import { QUAD_VERT } from "../canvas/shadersSim";
import {
  PANEL_COMPOSITE_FRAG,
  PANEL_FRAG,
  READOUT_LEN,
  TICKER_CAPACITY,
} from "./shadersColossus";

const BLOOM_DIV = 2;

/**
 * An 8-bit colour target, and the reason this file does not use the shared
 * `createTarget`.
 *
 * THE SHARED ONE IS RGBA16F, WHICH IS NOT RENDERABLE IN CORE WEBGL2. Half-float
 * textures are filterable by default but only become COLOR-RENDERABLE with
 * EXT_color_buffer_float (or its half-float sibling), which the other three
 * bodies enable because their simulations need it. This body deliberately does
 * not -- and the failure mode of getting that wrong is silent: the framebuffer
 * is incomplete, every draw into it is dropped, and the canvas composites a
 * black scene with no GL error raised anywhere. It cost this panel its first
 * render.
 *
 * Eight bits is also simply enough. There is no HDR here to preserve: a lamp
 * clips at full brightness and the reference lamps genuinely do blow out, so
 * the range being lost is range the look does not want.
 */
function createLdrTarget(
  gl: WebGL2RenderingContext,
  width: number,
  height: number,
): [WebGLTexture, WebGLFramebuffer] {
  const tex = gl.createTexture();
  const fbo = gl.createFramebuffer();
  if (!tex || !fbo) throw new Error("could not create render target");
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, width, height, 0,
    gl.RGBA, gl.UNSIGNED_BYTE, null);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
  if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) {
    // Loud, because the silent version of this is a black canvas and an hour.
    throw new Error("colossus render target incomplete");
  }
  return [tex, fbo];
}

/** Everything a frame is driven by, derived once by the renderer. */
export interface ColossusDrive {
  /** Animation seconds. NOT wall clock -- see ColossusRenderer.animClock. */
  time: number;
  /** 0..1 overall activity; sets how busy the indicator fields are. */
  energy: number;
  /** 0..1 speech level, zero when not speaking. */
  voice: number;
  /** Eight 0..1 voice bands; each owns a column region of the lamp fields. */
  bands: Float32Array;
  /** Ticker offset in CELLS. Fractional, so the sign slides rather than snaps. */
  scroll: number;
  /** Glyph ids, padded to capacity. */
  ticker: Int32Array;
  tickerLen: number;
  /** The counter window's eight glyphs. */
  readout: Int32Array;
  /** 0..1, decaying -- lifts the counter on the frame it changes. */
  readoutGlow: number;
}

export class ColossusPasses {
  private progs: Record<string, WebGLProgram> = {};
  private quad: WebGLBuffer | null = null;
  private vao: WebGLVertexArrayObject | null = null;
  private sceneTex: WebGLTexture | null = null;
  private sceneFbo: WebGLFramebuffer | null = null;
  private blurTex: WebGLTexture[] = [];
  private blurFbo: WebGLFramebuffer[] = [];
  private size: [number, number] = [0, 0];

  constructor(private readonly gl: WebGL2RenderingContext) {}

  init(): void {
    const gl = this.gl;
    this.progs.panel = createProgram(gl, QUAD_VERT, PANEL_FRAG);
    this.progs.bloom = createProgram(gl, QUAD_VERT, BLOOM_FRAG);
    this.progs.composite = createProgram(gl, QUAD_VERT, PANEL_COMPOSITE_FRAG);

    this.quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.bufferData(gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    this.vao = gl.createVertexArray();
    gl.bindVertexArray(this.vao);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.bindVertexArray(null);
  }

  resize(width: number, height: number): void {
    const gl = this.gl;
    if (width === this.size[0] && height === this.size[1]) return;
    this.size = [width, height];
    this.releaseTargets();
    [this.sceneTex, this.sceneFbo] = createLdrTarget(gl, width, height);
    const bw = Math.max(1, Math.floor(width / BLOOM_DIV));
    const bh = Math.max(1, Math.floor(height / BLOOM_DIV));
    for (let i = 0; i < 2; i++) {
      const [tex, fbo] = createLdrTarget(gl, bw, bh);
      this.blurTex[i] = tex;
      this.blurFbo[i] = fbo;
    }
  }

  destroy(): void {
    const gl = this.gl;
    this.releaseTargets();
    for (const prog of Object.values(this.progs)) gl.deleteProgram(prog);
    this.progs = {};
    if (this.quad) gl.deleteBuffer(this.quad);
    if (this.vao) gl.deleteVertexArray(this.vao);
    this.quad = null;
    this.vao = null;
  }

  render(drive: ColossusDrive, palette: FloatUniforms, bloomGain: number, vignette = 0.85): void {
    const gl = this.gl;
    const [w, h] = this.size;
    if (!w || !h) return;
    const aspect = w / h;

    gl.bindVertexArray(this.vao);
    gl.disable(gl.BLEND);

    this.panel(drive, palette, aspect);
    this.bloom();
    this.composite(drive, bloomGain, aspect, vignette);

    gl.bindVertexArray(null);
  }

  // ------------------------------------------------------------------ passes

  private panel(drive: ColossusDrive, palette: FloatUniforms, aspect: number): void {
    const gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.sceneFbo);
    gl.viewport(0, 0, this.size[0], this.size[1]);
    gl.clearColor(0, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);

    const prog = this.progs.panel;
    gl.useProgram(prog);
    setUniforms(gl, prog, {
      ...palette,
      uTime: drive.time,
      uAspect: aspect,
      uEnergy: drive.energy,
      uVoice: drive.voice,
      uBands: drive.bands,
      uScroll: drive.scroll,
      uReadoutGlow: drive.readoutGlow,
    }, { uTickerLen: drive.tickerLen });

    // Int ARRAYS, which the shared setUniforms does not carry: it exists to
    // hand one block of floats to several passes, and every other character's
    // integer state is a scalar. Two calls here beat widening a helper three
    // other bodies depend on.
    this.intArray(prog, "uTicker", drive.ticker, TICKER_CAPACITY);
    this.intArray(prog, "uReadout", drive.readout, READOUT_LEN);

    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  private intArray(prog: WebGLProgram, name: string, data: Int32Array, len: number): void {
    const gl = this.gl;
    const loc = gl.getUniformLocation(prog, `${name}[0]`) ?? gl.getUniformLocation(prog, name);
    if (!loc) return;
    gl.uniform1iv(loc, data.subarray(0, len));
  }

  private bloom(): void {
    const gl = this.gl;
    const bw = Math.max(1, Math.floor(this.size[0] / BLOOM_DIV));
    const bh = Math.max(1, Math.floor(this.size[1] / BLOOM_DIV));
    const prog = this.progs.bloom;
    gl.useProgram(prog);
    gl.viewport(0, 0, bw, bh);

    // Horizontal, with the bright-pass; then vertical with it disabled, which
    // is what uThreshold < 0 means to BLOOM_FRAG.
    const axes: Array<[WebGLTexture | null, WebGLFramebuffer | null, number[], number]> = [
      [this.sceneTex, this.blurFbo[0], [1 / bw, 0], 0.30],
      [this.blurTex[0], this.blurFbo[1], [0, 1 / bh], -1],
    ];
    for (const [src, dst, dir, threshold] of axes) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, dst);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, src);
      setUniforms(gl, prog, { uDir: dir, uThreshold: threshold }, { uSrc: 0 });
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
  }

  private composite(drive: ColossusDrive, bloomGain: number, aspect: number, vignette: number): void {
    const gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, this.size[0], this.size[1]);
    const prog = this.progs.composite;
    gl.useProgram(prog);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.sceneTex);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.blurTex[1]);
    setUniforms(gl, prog, {
      uBloomGain: bloomGain,
      uAspect: aspect,
      uTime: drive.time,
      uVignette: vignette,
    }, { uScene: 0, uBloom: 1 });
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  private releaseTargets(): void {
    const gl = this.gl;
    if (this.sceneTex) gl.deleteTexture(this.sceneTex);
    if (this.sceneFbo) gl.deleteFramebuffer(this.sceneFbo);
    this.sceneTex = null;
    this.sceneFbo = null;
    for (const tex of this.blurTex) gl.deleteTexture(tex);
    for (const fbo of this.blurFbo) gl.deleteFramebuffer(fbo);
    this.blurTex = [];
    this.blurFbo = [];
  }
}
