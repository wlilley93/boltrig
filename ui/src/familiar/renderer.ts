/**
 * ONE GPU CONTEXT FOR EVERY FAMILIAR ON THE PAGE.
 *
 * The obvious build gives each avatar its own <canvas> with its own WebGL context. It works
 * beautifully with three agents and then falls over: browsers cap live WebGL contexts at
 * around 16, and when you pass the cap they do not error, they silently kill the OLDEST
 * context. A fleet bar with twenty agents would blank the first ones as you scrolled, which
 * looks like a rendering bug and is actually an architecture bug.
 *
 * So: one offscreen WebGL2 context does all the drawing, and each avatar keeps a cheap 2D
 * canvas that it blits into. Contexts stay at one no matter how many agents exist, and the
 * per-avatar cost is a drawImage.
 *
 * The shader is a 107KB raymarcher built for a full-screen wallpaper, which sounds alarming
 * for an avatar and is not: cost is per PIXEL, and an avatar is 32-48px. Measured on the
 * desktop build, 520x520 runs at 1.38 ms; a 40px familiar is roughly 1/170th of that area.
 * Twenty of them is comfortably under one millisecond of GPU per frame.
 *
 * DEGRADING. If WebGL2 is missing or the shader fails to compile, `available()` goes false
 * and every caller falls back to initials. A familiar is how you recognise an agent, so the
 * failure mode has to be "you get the old avatar", never "you get a blank hole where the
 * agent used to be".
 */

import { packGenotype, type Genotype } from "./genotype";
import { type Phenotype } from "./phenotype";

/**
 * THE SHADER IS FETCHED, NOT BUNDLED, and the bundle budget is how that was found out.
 *
 * A static `import FAMILIAR_FRAG from "./familiar.frag?raw"` inlines 107KB of GLSL into the
 * main chunk. That took the entry bundle to 509,696 bytes against a 500,000 budget, and CI
 * refused the build - correctly, and for a better reason than the number: it meant every user
 * downloaded a raymarcher on first paint, including on the login screen, including if they
 * never opened a chat.
 *
 * A dynamic import puts it in its own chunk, fetched once when the first familiar mounts.
 * The cost is that readiness becomes asynchronous, which is why `available()` can return false
 * and later become true, and why there is a subscription below rather than a plain boolean.
 */
let FRAG: string | null = null;
let fragLoad: Promise<void> | null = null;
const readyListeners = new Set<() => void>();

/** Notified when the shader has arrived and the first program has linked. Components hold
 *  initials until this fires, so the failure mode of a slow network is the OLD avatar. */
export function onFamiliarReady(cb: () => void): () => void {
  readyListeners.add(cb);
  return () => readyListeners.delete(cb);
}

const VERT = `#version 300 es
void main() {
  vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`;

export interface FamiliarSubject {
  /** where to blit the finished frame */
  target: HTMLCanvasElement;
  genotype: Genotype;
  /** read fresh every frame, so mood can change without re-registering */
  phenotype: () => Phenotype;
  /** 0..1 voice level; drives the swell so a speaking agent visibly pulses */
  voice?: () => number;
  /** device-pixel size of the square to render */
  size: number;
}

type UniformMap = Record<string, WebGLUniformLocation | null>;

class Renderer {
  private gl: WebGL2RenderingContext | null = null;
  private prog: WebGLProgram | null = null;
  private uni: UniformMap = {};
  private canvas: HTMLCanvasElement | OffscreenCanvas | null = null;
  private subjects = new Set<FamiliarSubject>();
  private raf = 0;
  private t0 = 0;
  private failed = false;

  /**
   * True once the shader has arrived AND a context and a linked program exist. Never
   * optimistic: it returns false while the fetch is in flight, so a caller that asks early
   * gets initials rather than an empty canvas that may or may not fill in later.
   *
   * Calling it starts the fetch. That makes it a getter with a side effect, which is usually
   * a smell and is right here: every call site is asking "should I draw a familiar", and the
   * honest answer to the first one is "not yet, and I have started making it possible".
   */
  available(): boolean {
    if (this.failed) return false;
    if (this.prog) return true;
    if (FRAG === null) {
      if (!fragLoad) {
        fragLoad = import("./familiar.frag?raw")
          .then((m) => {
            FRAG = m.default;
            // Link immediately so `available()` is true by the time a listener runs. A
            // listener that fired before the program linked would re-render into another false.
            this.init();
            for (const cb of readyListeners) cb();
          })
          .catch((err) => {
            console.warn("familiar: shader failed to load:", err);
            this.failed = true;
          });
      }
      return false;
    }
    return this.init();
  }

  private init(): boolean {
    if (this.failed || this.prog) return !!this.prog;
    if (FRAG === null) return false;
    try {
      // Sized generously once; each subject renders into the top-left corner at its own size
      // via glViewport, so one buffer serves every avatar size on the page without resizing
      // (a resize would reallocate the drawing buffer every frame in a mixed-size list).
      const c = document.createElement("canvas");
      c.width = 256;
      c.height = 256;
      const gl = c.getContext("webgl2", {
        alpha: true,
        premultipliedAlpha: false,
        antialias: false,
        // The blit reads the drawing buffer AFTER the frame is submitted, so it must survive
        // the swap. Without this the browser is free to discard it and the avatars flicker
        // between the real frame and an empty one, at a rate that depends on the compositor.
        preserveDrawingBuffer: true,
        powerPreference: "low-power",
      });
      if (!gl) { this.failed = true; return false; }

      const vs = this.compile(gl, gl.VERTEX_SHADER, VERT);
      const fs = this.compile(gl, gl.FRAGMENT_SHADER, FRAG);
      if (!vs || !fs) { this.failed = true; return false; }
      const prog = gl.createProgram();
      if (!prog) { this.failed = true; return false; }
      gl.attachShader(prog, vs);
      gl.attachShader(prog, fs);
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
        console.warn("familiar: link failed:", gl.getProgramInfoLog(prog));
        this.failed = true;
        return false;
      }
      gl.useProgram(prog);

      const names = [
        "iTime", "iResolution", "uAudio", "uBeat", "uMouse", "uDay",
        "uValence", "uArousal", "uIrritation", "uFatigue", "uAttention",
        "uSocial", "uBuoyancy", "uLuminosity", "uTension",
        "uGesture", "uGestureAmt", "uPresence", "uCentreDock", "uScaleDock",
        "uFitScale", "uGaze", "uWorldRes", "uOrigin", "uPxScale", "uFill",
        "uPortWide", "uHover", "uCompanion", "uAperture", "uGene",
      ];
      for (const n of names) this.uni[n] = gl.getUniformLocation(prog, n);

      gl.bindVertexArray(gl.createVertexArray());
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

      this.gl = gl;
      this.prog = prog;
      this.canvas = c;
      this.t0 = performance.now();
      return true;
    } catch (err) {
      console.warn("familiar: renderer unavailable:", err);
      this.failed = true;
      return false;
    }
  }

  private compile(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader | null {
    const s = gl.createShader(type);
    if (!s) return null;
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      console.warn("familiar: shader compile failed:", gl.getShaderInfoLog(s));
      gl.deleteShader(s);
      return null;
    }
    return s;
  }

  add(subject: FamiliarSubject): () => void {
    if (!this.available()) return () => {};
    this.subjects.add(subject);
    this.start();
    return () => {
      this.subjects.delete(subject);
      if (this.subjects.size === 0) this.stop();
    };
  }

  private start(): void {
    if (this.raf) return;
    const tick = () => {
      this.raf = requestAnimationFrame(tick);
      this.frame();
    };
    this.raf = requestAnimationFrame(tick);
  }

  private stop(): void {
    // Nothing on screen wants a familiar, so stop burning a frame callback. The context is
    // kept: re-acquiring one costs a shader recompile of a 107KB program, and a chat where
    // the last agent leaves and another arrives a second later would pay it repeatedly.
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
  }

  private frame(): void {
    const gl = this.gl;
    if (!gl || !this.prog) return;
    const t = (performance.now() - this.t0) / 1000;

    for (const s of this.subjects) {
      const size = Math.max(1, Math.round(s.size));
      // A target detached from the document cannot be seen, so drawing it is pure waste.
      // This is the whole visibility policy: React removes the canvas, the work stops.
      if (!s.target.isConnected) continue;

      gl.viewport(0, 0, size, size);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);

      const u = this.uni;
      const p = s.phenotype();
      const voice = s.voice ? s.voice() : 0;

      gl.uniform1f(u.iTime, t);
      gl.uniform2f(u.iResolution, size, size);
      gl.uniform2f(u.uWorldRes, size, size);
      gl.uniform2f(u.uOrigin, 0, 0);
      gl.uniform1f(u.uPxScale, 1);
      // Voice drives the same swell channel the desktop familiar uses, so an agent that is
      // speaking in a call pulses with its own audio rather than on a timer.
      gl.uniform4f(u.uAudio, voice, voice * 0.9, voice, voice * 0.7);
      gl.uniform1f(u.uBeat, 0);
      gl.uniform2f(u.uMouse, 0.5, 0.5);
      gl.uniform1f(u.uDay, 0.5);
      gl.uniform1f(u.uValence, p.valence);
      gl.uniform1f(u.uArousal, p.arousal);
      gl.uniform1f(u.uIrritation, p.irritation);
      gl.uniform1f(u.uFatigue, p.fatigue);
      gl.uniform1f(u.uAttention, p.attention);
      gl.uniform1f(u.uSocial, p.social);
      gl.uniform1f(u.uBuoyancy, p.buoyancy);
      gl.uniform1f(u.uLuminosity, p.luminosity);
      gl.uniform1f(u.uTension, p.tension);
      gl.uniform1f(u.uGesture, 0);
      gl.uniform1f(u.uGestureAmt, 0);
      // COMPANION MODE, and this is the difference between an avatar and a dark square.
      //
      // The shader has three composition modes and only one of them is an avatar:
      //   presence 1, fill 0  - WALLPAPER. `a = mix(cover, 1.0, ...)` resolves to 1 for every
      //     pixel. Correct on a desktop; in a chat list it draws a hard opaque rectangle
      //     behind every agent. Measured: alpha 255 across all 102,400 pixels of a render.
      //   presence 0          - WITHDRAWN. The being leaves for the bar. Measured: alpha 0
      //     everywhere, an invisible avatar.
      //   fill 1 + companion 1 - "show the full being, then feather the porthole edge". This
      //     one. The being at full size, transparent outside it.
      //
      // uAperture is the companion's entrance: at 0 it is shut and nothing renders at all
      // (measured: alpha 0, cover 0%), so it must be opened.
      gl.uniform1f(u.uPresence, 1);
      gl.uniform1f(u.uFill, 1);
      gl.uniform1f(u.uCompanion, 1);
      gl.uniform1f(u.uAperture, 1);
      gl.uniform1f(u.uPortWide, 0);
      gl.uniform1f(u.uHover, 0);
      gl.uniform1f(u.uGaze, 0);            // no cursor to watch in an avatar; it looks around
      gl.uniform2f(u.uCentreDock, 0, 0);   // (0,0) is dead centre of a square porthole
      // 0.34, chosen by measurement rather than by taste. The companion's edge feather is
      // `smoothstep(uFitScale, uFitScale - band, dScreen)`, and dScreen is the NORMALISED
      // shape distance - so for a radial body the far field is not uniform, and at 0.42 the
      // feather had not finished by the time it reached the canvas corner: corner alpha 71 of
      // 255, a soft square around every star. At 0.34 corner alpha is 0 and the body still
      // covers 55% of the frame. Below that it just gets small.
      gl.uniform1f(u.uScaleDock, 0.34);
      gl.uniform1f(u.uFitScale, 0.34);
      gl.uniform4fv(u.uGene, packGenotype(s.genotype));

      gl.drawArrays(gl.TRIANGLES, 0, 3);

      const ctx = s.target.getContext("2d");
      if (!ctx) continue;
      if (s.target.width !== size || s.target.height !== size) {
        s.target.width = size;
        s.target.height = size;
      }
      ctx.clearRect(0, 0, size, size);
      // The shared buffer is 256 tall and GL's origin is bottom-left, so the rendered square
      // sits in the BOTTOM-left corner. Copying from the top-left would silently blit empty
      // pixels for any subject smaller than the buffer, which is all of them.
      const src = this.canvas as HTMLCanvasElement;
      ctx.drawImage(src, 0, src.height - size, size, size, 0, 0, size, size);
    }
  }
}

export const familiarRenderer = new Renderer();
