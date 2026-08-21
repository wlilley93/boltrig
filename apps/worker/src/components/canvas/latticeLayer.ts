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
// 0 = tint toward the warm colour (a body whose footage already carries its
// palette); 1 = RECOLOUR: luminance drives the warm colour outright, for a
// body whose colour is her mood -- the footage is shot once in blue and the
// emotion decides what colour that light is tonight.
uniform float uMode;
// The video channel's effects rack: x = motion blur (a tangential smear, so a
// turning lattice streaks along its own travel), y = saturation, z = glow (a
// four-tap halo, bloom at video prices). All neutral at [0, 1, 0].
uniform vec3 uFx;
void main() {
  vec2 uv = (vUV - 0.5) * uFit + 0.5;
  if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) {
    oColor = vec4(0.0);
    return;
  }
  vec2 tuv = vec2(uv.x, 1.0 - uv.y);
  vec3 c = texture(uVideo, tuv).rgb;
  if (uFx.x > 0.001) {
    vec2 rel = tuv - 0.5;
    vec2 dir = vec2(-rel.y, rel.x);
    vec3 acc = c;
    float wsum = 1.0;
    for (int i = 1; i <= 4; i++) {
      float t = float(i) / 4.0;
      vec2 o = dir * uFx.x * 0.14 * t;
      float w = 1.0 - 0.55 * t;
      acc += texture(uVideo, tuv + o).rgb * w;
      acc += texture(uVideo, tuv - o).rgb * w;
      wsum += 2.0 * w;
    }
    c = acc / wsum;
  }
  float lum = dot(c, vec3(0.299, 0.587, 0.114));
  c = clamp(mix(vec3(lum), c, uFx.y), 0.0, 4.0);
  if (uFx.z > 0.001) {
    vec3 halo = texture(uVideo, tuv + vec2(0.014, 0.0)).rgb
      + texture(uVideo, tuv - vec2(0.014, 0.0)).rgb
      + texture(uVideo, tuv + vec2(0.0, 0.014)).rgb
      + texture(uVideo, tuv - vec2(0.0, 0.014)).rgb;
    c += halo * 0.3 * uFx.z;
  }
  vec3 tint = mix(vec3(1.0), uWarm * 1.55, 0.45);
  // Recolour reads the FINAL luminance, so blur and glow reach her too.
  float lumOut = dot(c, vec3(0.299, 0.587, 0.114));
  vec3 shaded = uMode > 0.5 ? lumOut * uWarm * 2.0 : c * tint;
  oColor = vec4(shaded * uGain, 1.0);
}`;

/** blur / saturation / glow, in slider terms. Neutral is [0, 1, 0]. */
export type LatticeFx = readonly [number, number, number];
const NEUTRAL_FX: LatticeFx = [0, 1, 0];

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
    if (this.dead || !video) {
      this.ready = false;
      return;
    }
    // KEEP THE LAST FRAME through a readyState dip. At a loop wrap (and on
    // decoder hiccups) the element can report unreadable for a single tick;
    // blanking then made the footage cut out for exactly one frame while the
    // texture still held a perfectly good image. Only a genuine source change
    // resets the layer — the deck calls reset() when it swaps a slot's URL.
    if (video.readyState < 2) {
      if (!this.tex) this.ready = false;
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

  /** Whether a frame is actually on the texture — the deck's fade waits for
   *  this, so a crossfade never dims into a layer that has no pixels yet. */
  isReady(): boolean {
    return this.ready;
  }

  /** Forget the held frame. Called by the deck when a slot's SOURCE changes:
   *  without this, keep-the-last-frame would let a crossfade land on the old
   *  loop's stale frame while the new one is still decoding. */
  reset(): void {
    this.ready = false;
    this.at = -1;
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
    recolour = false,
    scale = 1,
    fx: LatticeFx = NEUTRAL_FX,
  ): void {
    const gl = this.gl;
    if (!this.ready || !this.tex || !this.prog || gain <= 0) return;
    const [w, h] = size;
    const aspect = w / Math.max(1, h);
    // Presence: dividing the fit enlarges the footage, so the baked layer and
    // the shader body grow and shrink together as one composite piece.
    const grow = Math.max(0.05, scale);
    const fit: [number, number] = (aspect > this.aspect
      ? [aspect / this.aspect / grow, 1 / grow]
      : [1 / grow, this.aspect / aspect / grow]) as [number, number];
    gl.useProgram(this.prog);
    gl.activeTexture(gl.TEXTURE2);
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    setUniforms(gl, this.prog, {
      uWarm: [warm[0], warm[1], warm[2]], uGain: gain, uFit: fit,
      uMode: recolour ? 1 : 0, uFx: [fx[0], fx[1], fx[2]],
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
 * TWO LAYERS AND A FADE: per-state footage for one body.
 *
 * Each state has its own loop, and a state change must CROSSFADE the footage
 * rather than cut it — the shader's own transition eases, and a hard video
 * pop under an eased body would give the game away. A state's loop is still
 * warm when the body returns to it; the retiring loop pauses once the fade
 * lands. "standby" is every state's understudy, so a missing file degrades
 * to the resting loop rather than to nothing.
 */
export class LatticeDeck {
  private slots: { layer: LatticeLayer; el: HTMLVideoElement | null; url: string | null }[] = [];
  private active = 0;
  private fade = 1;
  private map: Partial<Record<string, string>> | null = null;

  constructor(private readonly gl: WebGL2RenderingContext) {}

  init(): void {
    this.slots = [0, 1].map(() => {
      const layer = new LatticeLayer(this.gl);
      layer.init();
      return { layer, el: null, url: null };
    });
  }

  /** One URL serves every state; a map gives each state its own loop. */
  setSource(source: string | Partial<Record<string, string>> | null): void {
    for (const slot of this.slots) {
      slot.el?.remove();
      slot.el = null;
      slot.url = null;
      slot.layer.reset();
    }
    this.map = source == null
      ? null
      : typeof source === "string" ? { standby: source } : source;
    this.fade = 1;
  }

  /** Advance the fade and pull in video frames. Once per frame, before draw.
   *  `rate` is the footage's playback speed — half-time membrane, double-time
   *  lattice — applied to both slots so a crossfade never runs two clocks. */
  tick(mode: string, dt: number, rate = 1): void {
    if (!this.map || this.slots.length < 2) return;
    const speed = Math.min(4, Math.max(0.25, rate));
    for (const slot of this.slots) {
      if (slot.el && slot.el.playbackRate !== speed) slot.el.playbackRate = speed;
    }
    const desired = this.map[mode] ?? this.map.standby ?? null;
    const active = this.slots[this.active];
    if (desired !== active.url) {
      this.active = 1 - this.active;
      const next = this.slots[this.active];
      if (next.url !== desired) {
        next.el?.remove();
        next.el = desired ? latticeVideo(desired) : null;
        next.url = desired;
        next.layer.reset();
      } else {
        // Returning to a recently-left state: its loop is still loaded.
        void next.el?.play().catch(() => undefined);
      }
      this.fade = 0;
    }
    const front = this.slots[this.active];
    const back = this.slots[1 - this.active];
    front.layer.upload(front.el);
    // THE FADE WAITS FOR PIXELS. Advancing it while the incoming loop is
    // still decoding faded the retiring loop into a hole — a visible blink
    // on every state change. The retiring loop holds at full weight until
    // the new one has a frame on its texture; only then does the cross run.
    if (this.fade < 1 && (front.layer.isReady() || front.el === null)) {
      this.fade = Math.min(1, this.fade + dt / 0.8);
    }
    if (this.fade < 1 && back.el) back.layer.upload(back.el);
    else if (back.el && !back.el.paused) back.el.pause();
  }

  /** Both slots, additively, fade-weighted. Gain includes tuning and voice. */
  draw(
    size: readonly [number, number],
    warm: ArrayLike<number>,
    gain: number,
    fullscreen: (prog: WebGLProgram) => void,
    recolour = false,
    scale = 1,
    fx: LatticeFx = NEUTRAL_FX,
  ): void {
    if (!this.map || this.slots.length < 2 || gain <= 0) return;
    const front = this.slots[this.active];
    const back = this.slots[1 - this.active];
    // A raised cosine, so the cross leaves and arrives gently rather than
    // snapping at both ends of a linear ramp.
    const eased = 0.5 - 0.5 * Math.cos(Math.PI * this.fade);
    front.layer.draw(size, warm, gain * eased, fullscreen, recolour, scale, fx);
    if (this.fade < 1 && back.el) {
      back.layer.draw(size, warm, gain * (1 - eased), fullscreen, recolour, scale, fx);
    }
  }

  destroy(): void {
    for (const slot of this.slots) {
      slot.el?.remove();
      slot.el = null;
      slot.layer.destroy();
    }
    this.slots = [];
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
