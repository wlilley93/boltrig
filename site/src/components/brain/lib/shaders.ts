/**
 * GLSL shader sources for the particle brain, ported verbatim from
 * `scenes/brain-particles.html`. Three groups:
 *   - ambient cloud (drifting points around the brain)
 *   - brain surface (the sampled point cloud + synapse flashes)
 *   - final composite (warped corner-gradient background + bloom layers)
 */

export const AMBIENT_VERTEX = /* glsl */ `
  attribute vec3 aDir;
  attribute float aSeed;
  uniform float iTime;
  uniform float iResolutionY;
  uniform float uSize;
  uniform float uSpeed;
  uniform float uRange;
  varying float vSeed;
  varying float vPhase;
  void main() {
    vSeed = aSeed;
    float speed = 0.35 + aSeed * 0.9;
    float phase = fract(iTime * uSpeed * speed + aSeed);
    vPhase = phase;
    vec3 dir = normalize(aDir + vec3(1e-5));
    vec3 p = position + dir * phase * uRange;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    float lifeSize = mix(1.0, 0.6, phase);
    gl_PointSize = uSize * lifeSize * (iResolutionY / 720.0) * (200.0 / -mv.z);
  }
`;

export const AMBIENT_FRAGMENT = /* glsl */ `
  uniform vec3 uColor;
  uniform float iAlpha;
  varying float vSeed;
  varying float vPhase;
  void main() {
    vec2 p = gl_PointCoord - 0.5;
    float r = length(p);
    if (r > 0.5) discard;
    float k = smoothstep(0.5, 0.0, r);
    float life = smoothstep(0.0, 0.1, vPhase) * smoothstep(1.0, 0.7, vPhase);
    float twinkle = 0.5 + 0.5 * sin(vSeed * 40.0 + vPhase * 30.0);
    gl_FragColor = vec4(uColor * k * life * (0.4 + 0.6 * twinkle), k * life * iAlpha * 0.6);
  }
`;

export const BRAIN_VERTEX = /* glsl */ `
  attribute float aSeed;
  attribute float aOcclusion;
  attribute vec3 aNormal;
  uniform float iTime;
  uniform float iResolutionY;
  uniform float uSize;
  uniform float uSynapseRate;
  uniform float uCenterRadius;
  uniform float uFlowSpeed;
  uniform float uFlowAmount;
  uniform vec3 uHighlightPos;
  uniform float uHighlightRadius;
  uniform float uHighlightStrength;
  uniform float uExplode;
  uniform float uExplodeDist;
  uniform vec2 uMouse;        // cursor in NDC (-1..1)
  uniform float uCursor;      // cursor effect strength (0..1)
  uniform float uAspect;      // viewport width / height (circular halo)
  uniform float uCursorRadius;// NDC halo radius (shrinks as the brain gets far)
  uniform float uCursorStrength; // overall halo intensity multiplier
  varying float vSeed;
  varying float vSynapse;
  varying float vHemi;
  varying float vDepth;
  varying float vFrontness;
  varying float vCenterness;
  varying float vOcclusion;
  varying float vHighlight;
  varying float vFar;
  varying float vCursor;
  varying vec3 vWorldPos;
  void main() {
    vSeed = aSeed;
    vOcclusion = aOcclusion;
    vec3 p = position;
    vWorldPos = p;
    vHemi = step(0.0, p.x);
    // Region highlight: 1 at the active anchor, fading out over uHighlightRadius.
    vHighlight = (1.0 - smoothstep(0.0, uHighlightRadius, distance(position, uHighlightPos))) * uHighlightStrength;
    // vFar: 0 on the side facing the active region, 1 on the opposite side —
    // used to fade the far half of the brain to accent the focus.
    vec3 focalDir = normalize(uHighlightPos + vec3(1e-5));
    float align = dot(normalize(position + vec3(1e-5)), focalDir);
    vFar = smoothstep(0.55, -0.35, align);
    vec3 rad = normalize(p + vec3(1e-5));
    float breathe = sin(iTime * 1.6 + aSeed * 6.0) * 0.012;
    p += rad * breathe;
    // Continuous looped flow: each particle traces a full closed circle within
    // its surface tangent plane, so it orbits *around* on the brain's shape
    // (never leaving it) — alive, but the silhouette stays readable.
    vec3 nrm = normalize(aNormal + vec3(1e-5));
    vec3 ref = abs(nrm.y) < 0.95 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0);
    vec3 tA = normalize(cross(nrm, ref));
    vec3 tB = cross(nrm, tA);
    float ph = iTime * uFlowSpeed + aSeed * 6.2831;
    vec3 loopDir = tA * cos(ph) + tB * sin(ph);
    p += loopDir * uFlowAmount;
    // Finale: blow the particles outward along a seeded radial direction.
    vec3 exDir = normalize(rad + vec3(sin(aSeed * 41.0), cos(aSeed * 57.0), sin(aSeed * 73.0)) * 0.45);
    p += exDir * uExplode * uExplodeDist;
    float period = mix(3.0, 9.0, aSeed);
    float firePhase = aSeed * period;
    float ft = mod(iTime + firePhase, period);
    float fire = pow(clamp(1.0 - ft / 0.4, 0.0, 1.0), 2.5);
    if (aSeed > uSynapseRate) fire = 0.0;
    vSynapse = fire;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    vec4 centerMv = modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0);
    float rel = centerMv.z - mv.z;
    vFrontness = clamp(rel * 0.6 + 0.5, 0.0, 1.0);
    gl_Position = projectionMatrix * mv;
    vec4 centerClip = projectionMatrix * centerMv;
    vec2 centerNDC = centerClip.xy / max(0.0001, centerClip.w);
    vec2 pNDC = gl_Position.xy / max(0.0001, gl_Position.w);
    float screenDist = length(pNDC - centerNDC);
    vCenterness = 1.0 - clamp(screenDist / max(0.05, uCenterRadius), 0.0, 1.0);
    // Cursor halo: particles whose screen position is near the pointer light up
    // and swell, so neurons appear to fire wherever you point. Aspect-corrected
    // so the halo stays circular, not stretched.
    vec2 dMouse = pNDC - uMouse;
    dMouse.x *= uAspect;
    vCursor = (1.0 - smoothstep(0.0, uCursorRadius, length(dMouse))) * uCursor;
    float baseSize = uSize * (iResolutionY / 720.0) * (200.0 / -mv.z);
    gl_PointSize = baseSize * (1.0 + fire * 2.5 + vHighlight * 1.8 + vCursor * 1.3 * uCursorStrength);
    vDepth = -mv.z;
  }
`;

export const BRAIN_FRAGMENT = /* glsl */ `
  uniform vec3 uCool;
  uniform vec3 uWarm;
  uniform vec3 uEdgeColor;
  uniform vec3 uCenterColor;
  uniform float uCenterFalloff;
  uniform vec3 uSynapse;
  uniform float iAlpha;
  uniform float uGlow;
  uniform float uDepthDarkness;
  uniform vec3 uDeepColor;
  uniform float uOcclusionStrength;
  uniform vec3 uHighlightColor;
  uniform float uHighlightStrength;
  uniform float uFocusFadeStrength;
  uniform float uIsolateStrength;
  uniform float uExplode;
  uniform vec3 uCursorColor;
  uniform float uCursorStrength;
  varying float vSeed;
  varying float vSynapse;
  varying float vHemi;
  varying float vDepth;
  varying float vFrontness;
  varying float vCenterness;
  varying float vOcclusion;
  varying float vHighlight;
  varying float vFar;
  varying float vCursor;
  varying vec3 vWorldPos;
  void main() {
    vec2 p = gl_PointCoord - 0.5;
    float r = length(p);
    if (r > 0.5) discard;
    float core = pow(smoothstep(0.5, 0.0, r), 2.2);
    float t = pow(vCenterness, max(0.05, uCenterFalloff));
    vec3 base = mix(uEdgeColor, uCenterColor, t);
    vec3 yTint = mix(uCool, uWarm, smoothstep(-0.6, 1.0, vWorldPos.y) * 0.6 + vSeed * 0.25);
    yTint = mix(yTint, yTint * vec3(0.95, 1.0, 1.05), vHemi * 0.4);
    base *= mix(vec3(1.0), yTint, 0.35);
    // Cavity depth: particles in folds (sulci) sink toward the deep colour.
    base = mix(base, uDeepColor, clamp(vOcclusion * uOcclusionStrength, 0.0, 1.0));
    vec3 col = base + uSynapse * vSynapse * 2.0;
    // Active-region highlight: tint the local cluster toward a deeper green and
    // add a gentle glow so it reads as the focal accent.
    col = mix(col, uHighlightColor, vHighlight * 0.5);
    col += uHighlightColor * vHighlight * 0.7;
    // Isolate the focus: while a region is active, darken everything that ISN'T
    // the highlighted cluster toward the deep green so the zone clearly stands out.
    float nonFocus = (1.0 - vHighlight) * uHighlightStrength;
    col = mix(col, uDeepColor, nonFocus * uIsolateStrength);
    float depthMul = mix(1.0 - uDepthDarkness, 1.0, vFrontness);
    col *= depthMul;
    float alphaOut = core * iAlpha * mix(1.0 - uDepthDarkness * 0.7, 1.0, vFrontness);
    alphaOut *= 1.0 + vHighlight * 0.8;
    // Fade the side opposite the active region to focus attention.
    float focusDim = 1.0 - uHighlightStrength * uFocusFadeStrength * vFar;
    col *= focusDim;
    alphaOut *= focusDim;
    // Cursor halo: gently lift particles under the pointer (additive, so even dim
    // particles register where you point — kept subtle).
    col += uCursorColor * vCursor * 0.8 * uCursorStrength;
    alphaOut += vCursor * core * 0.32 * uCursorStrength;
    // Finale: the brain blows up and thins out as it disperses.
    alphaOut *= 1.0 - smoothstep(0.0, 1.0, uExplode) * 0.8;
    gl_FragColor = vec4(col * uGlow, alphaOut);
  }
`;

export const FINAL_VERTEX = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position, 1.0);
  }
`;

export const FINAL_FRAGMENT = /* glsl */ `
  uniform float iTime;
  uniform sampler2D tScene;   // brain + real bloom, rendered off-screen
  uniform vec3 iCornerBlue;
  uniform vec3 iCornerOrange;
  varying vec2 vUv;
  vec3 warp3d(vec3 pos, float t) {
    float curv = .8, a = 1.9, b = 0.7; pos *= 2.;
    pos.x += curv * sin(t + a * pos.y) + t * b; pos.y += curv * cos(t + a * pos.x);
    pos.y += curv * sin(t + a * pos.z) + t * b; pos.z += curv * cos(t + a * pos.y);
    pos.z += curv * sin(t + a * pos.x) + t * b; pos.x += curv * cos(t + a * pos.z);
    return 0.5 + 0.5 * cos(pos.xyz + vec3(1, 2, 4));
  }
  void main() {
    vec2 uv = 2. * vUv - 1.;
    vec3 w = pow(warp3d(vec3(uv.x, sin(uv.y), uv.y), iTime * 1.5), vec3(1.5));
    vec3 col = 1.5 * iCornerBlue * w.x; col *= w.y; col += iCornerOrange * w.z;
    col *= smoothstep(0.6, 1., abs(uv.y));
    col *= smoothstep(-.5, 1., -uv.y * uv.x); col *= smoothstep(-.5, 1., -uv.y * uv.x);
    gl_FragColor = vec4(col + texture2D(tScene, vUv).xyz, 1.);
  }
`;
