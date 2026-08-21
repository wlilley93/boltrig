// The baked layer: a pre-rendered loop composited additively under a body's
// live passes.
//
// The film bodies' density -- Jarvis's lattice, Ultron's membrane and crust --
// is offline rendering no 16ms frame can afford, but a video of it decodes in
// hardware on any phone. Because the footage is light on black, the composite
// still answers the voice: the GAIN is live even though the geometry is baked,
// and the layer takes the emotion's warm tint, so mood and speech reach the
// footage. One class serves every body; each passes object owns an instance.

import { createProgram, setUniforms } from "./glResources";
import { QUAD_VERT } from "./shadersSim";

const LATTICE_FRAG = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 oColor;
uniform sampler2D uVideo;
uniform float uGain;
uniform vec2 uFit;
uniform vec3 uWarm;
void main() {
  vec2 uv = (vUV - 0.5) * uFit + 0.5;
  if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) {
    oColor = vec4(0.0);
    return;
  }
  vec3 c = texture(uVideo, vec2(uv.x, 1.0 - uv.y)).rgb;
  vec3 tint = mix(vec3(1.0), uWarm * 1.55, 0.45);
  oColor = vec4(c * tint * uGain, 1.0);
}`;

export class LatticeLayer {
  private tex: WebGLTexture | null = null;
  private prog: WebGLProgram | null = null;
  private ready = false;
  private aspect = 1;
  private at = -1;
  /** Set on a failed upload; the layer stands down rather than retrying into
   *  the same failure. A CPU rasteriser (SwiftShader) LOSES THE CONTEXT on
   *  video texImage2D — measured, not theorised — so the one thing this path
   *  must never do is keep poking a context it may have already killed. */
  private dead = false;

  constructor(private readonly gl: WebGL2RenderingContext) {}

  /** Compiles the layer's program. Called from the owning passes' init(). */
  init(): void {
    this.prog = createProgram(this.gl, QUAD_VERT, LATTICE_FRAG);
  }

  /**
   * Pull the current video frame into the texture. Cheap to call every frame
   * -- a paused or absent video is one early return -- and the caller never
   * learns GL exists.
   */
  upload(video: HTMLVideoElement | null): void {
    const gl = this.gl;
    if (this.dead || !video || video.readyState < 2) {
      this.ready = false;
      return;
    }
    // ONLY ON A NEW VIDEO FRAME. The loop runs at 60 and the video at ~24, so
    // uploading per render frame more than doubles the conversion work for
    // identical pixels -- measured on the CPU rasteriser as the difference
    // between a live body and a starved one.
    if (video.currentTime === this.at && this.ready) return;
    this.at = video.currentTime;
    // EVERYTHING ON UNIT 2, including creation. Creating the texture while
    // unit 0 is active steals the sim texture's binding for a frame.
    gl.activeTexture(gl.TEXTURE2);
    if (!this.tex) {
      this.tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, this.tex);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    } else {
      gl.bindTexture(gl.TEXTURE_2D, this.tex);
    }
    try {
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, video);
    } catch {
      this.dead = true;
      this.ready = false;
      gl.activeTexture(gl.TEXTURE0);
      return;
    }
    gl.activeTexture(gl.TEXTURE0);
    if (gl.isContextLost()) {
      this.dead = true;
      this.ready = false;
      return;
    }
    this.aspect = video.videoWidth / Math.max(1, video.videoHeight);
    this.ready = true;
  }

  /**
   * The layer, under everything. Skipped entirely at zero gain, contain-fitted
   * so the loop is never cropped. `fullscreen` is the owning passes' triangle
   * -- the layer borrows the geometry rather than owning a copy.
   */
  draw(
    size: readonly [number, number],
    warm: ArrayLike<number>,
    gain: number,
    fullscreen: (prog: WebGLProgram) => void,
  ): void {
    const gl = this.gl;
    if (!this.ready || !this.tex || !this.prog || gain <= 0) return;
    const [w, h] = size;
    const aspect = w / Math.max(1, h);
    const fit: [number, number] = aspect > this.aspect
      ? [aspect / this.aspect, 1]
      : [1, this.aspect / aspect];
    gl.useProgram(this.prog);
    gl.activeTexture(gl.TEXTURE2);
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    setUniforms(gl, this.prog, {
      uWarm: [warm[0], warm[1], warm[2]], uGain: gain, uFit: fit,
    }, { uVideo: 2 });
    fullscreen(this.prog);
    gl.activeTexture(gl.TEXTURE0);
  }

  destroy(): void {
    if (this.tex) this.gl.deleteTexture(this.tex);
    if (this.prog) this.gl.deleteProgram(this.prog);
    this.tex = null;
    this.prog = null;
  }
}

/**
 * The video element for a layer. Muted, looping, inline, and every failure
 * path degrades to "no layer": a body whose extra footage is missing must
 * still be a body.
 */
export function latticeVideo(url: string): HTMLVideoElement {
  const video = document.createElement("video");
  video.muted = true;
  video.loop = true;
  video.playsInline = true;
  video.crossOrigin = "anonymous";
  video.src = url;
  void video.play().catch(() => undefined);
  return video;
}
