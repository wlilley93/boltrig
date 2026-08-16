// WebGL2 resource construction for the neural field.
//
// Split out of the renderer because it is generic plumbing -- compile, link,
// allocate, set -- with no opinion about Jarvis in it, and because keeping it
// beside the frame loop pushed that file past the worker's structural floor.
//
// Every function here THROWS on failure rather than returning null. The
// renderer catches once, at mount, and reports a fallback; a resource that
// silently came back null would surface much later as a blank canvas with no
// error to grep for.

/** Values a pass sets per frame. Integers go in a separate map -- see below.
 *
 * Float32Array is admitted alongside plain arrays because the voice bands are
 * held in one across frames rather than reallocated eight numbers at a time. */
export type FloatUniforms = Record<string, number | readonly number[] | Float32Array>;

/**
 * Sampler bindings, grid sizes, segment counts: anything that must reach the
 * shader as an `int`.
 *
 * A SEPARATE MAP RATHER THAN SNIFFING THE VALUE. `uniform1f` on an `int`
 * uniform is silently ignored by the driver, so a sampler set through the float
 * path leaves the texture unbound and the pass draws black. Sniffing
 * `Number.isInteger` would do exactly that the moment a float uniform happened
 * to land on a whole number.
 */
export type IntUniforms = Record<string, number>;

function compile(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) throw new Error("could not create shader");
  gl.shaderSource(shader, src);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(shader) ?? "shader compile failed");
  }
  return shader;
}

export function createProgram(
  gl: WebGL2RenderingContext,
  vertexSource: string,
  fragmentSource: string,
): WebGLProgram {
  const program = gl.createProgram();
  if (!program) throw new Error("could not create program");
  gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, vertexSource));
  gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, fragmentSource));
  // Bound before linking: the fullscreen passes share one quad buffer at
  // location 0, and the geometry passes use gl_VertexID with no attributes.
  gl.bindAttribLocation(program, 0, "aPos");
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(program) ?? "link failed");
  }
  return program;
}

/** A half-float colour target. Half is enough: it is a display buffer, not state. */
export function createTarget(
  gl: WebGL2RenderingContext,
  width: number,
  height: number,
): [WebGLTexture, WebGLFramebuffer] {
  const tex = gl.createTexture();
  const fbo = gl.createFramebuffer();
  if (!tex || !fbo) throw new Error("could not create render target");
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA16F, width, height, 0, gl.RGBA, gl.HALF_FLOAT, null);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
  return [tex, fbo];
}

/**
 * A simulation state texture. FULL float, not half, and NEAREST filtering:
 * positions quantised to half-float visibly band the cloud into shells, and
 * linear filtering would interpolate between two unrelated particles.
 */
export function createStateTarget(
  gl: WebGL2RenderingContext,
  size: number,
  seed: Float32Array | null,
): [WebGLTexture, WebGLFramebuffer] {
  const tex = gl.createTexture();
  const fbo = gl.createFramebuffer();
  if (!tex || !fbo) throw new Error("could not create state target");
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, size, size, 0, gl.RGBA, gl.FLOAT, seed);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
  return [tex, fbo];
}

/**
 * Sets a pass's uniforms in one call.
 *
 * A uniform the shader does not declare -- or declares and never reads, which
 * the compiler strips -- resolves to a null location and is skipped. That is
 * deliberate: the passes share uniform names (uWarm, uAspect, uTime) and a
 * caller should be able to hand the same block to each without knowing which
 * ones a given shader happens to consume.
 */
export function setUniforms(
  gl: WebGL2RenderingContext,
  program: WebGLProgram,
  floats: FloatUniforms,
  ints: IntUniforms = {},
): void {
  for (const [name, value] of Object.entries(floats)) {
    const loc = gl.getUniformLocation(program, name);
    if (!loc) continue;
    if (typeof value === "number") gl.uniform1f(loc, value);
    else if (value.length === 2) gl.uniform2f(loc, value[0], value[1]);
    else if (value.length === 3) gl.uniform3f(loc, value[0], value[1], value[2]);
    else gl.uniform1fv(loc, value as Float32Array | number[]);
  }
  for (const [name, value] of Object.entries(ints)) {
    const loc = gl.getUniformLocation(program, name);
    if (loc) gl.uniform1i(loc, value);
  }
}

/**
 * The seeded starting state: every particle already at its home radius.
 *
 * Seeded on the CPU rather than letting the shader respawn everything over the
 * first frames, because an empty first second reads as a broken canvas rather
 * than as a system starting up. `homeRadiusJs` must agree with `homeRadius()`
 * in field.glsl.ts about the interior band -- it does not have to be identical,
 * because the shader takes over on frame one, but a wildly different seed would
 * show as a visible settle.
 */
export function seedParticles(count: number, random: () => number = Math.random): Float32Array {
  const seed = new Float32Array(count * 4);
  for (let i = 0; i < count; i++) {
    const a = random() * Math.PI * 2;
    const z = random() * 2 - 1;
    const r = Math.sqrt(Math.max(0, 1 - z * z));
    // The interior band from field.glsl.ts, plus the occasional migrant already
    // out near the rings so the first frame is not uniformly small.
    const s = random() > 0.92 ? 0.2 + random() * 0.75 : 0.2 + random() * 0.34;
    seed[i * 4 + 0] = r * Math.cos(a) * s;
    seed[i * 4 + 1] = r * Math.sin(a) * s;
    seed[i * 4 + 2] = z * s;
    seed[i * 4 + 3] = random();
  }
  return seed;
}
