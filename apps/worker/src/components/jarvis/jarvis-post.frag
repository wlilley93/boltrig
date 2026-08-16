#version 300 es
// =============================================================================
// jarvis-post.frag - the offscreen passes that give the instrument real bloom.
//
// jarvis.frag draws thin bright lines on black. Its own `soft()` skirt is a
// per-element fake: it widens each stroke individually, so light never crosses
// between elements and a dense cluster glows no more than a lone hairline. Real
// bloom is a property of the IMAGE, not of a stroke - which is why the dense
// listening sweep should wash and a single tick should not.
//
// Four passes, selected by uPass, all drawn as one fullscreen triangle:
//
//   0  BRIGHT   downsample 4x and keep only what is above the threshold
//   1  BLUR_H   separable gaussian, horizontal
//   2  BLUR_V   separable gaussian, vertical
//   3  COMPOSITE scene + bloom, then tone-map, vignette and grain
//
// The grade lives in the COMPOSITE pass, not in jarvis.frag, because bloom has
// to be gathered from LINEAR light. Tone-mapping first would crush the very
// highlights the bloom is supposed to spread. jarvis.frag keeps its own grade
// behind uHDR for the single-pass desktop host, which has no framebuffers.
// =============================================================================
precision highp float;

out vec4 fragColor;

uniform sampler2D uTex;      // pass input (scene, or the bloom chain)
uniform sampler2D uScene;    // COMPOSITE only: the untouched scene
uniform vec2  uTexel;        // 1.0 / size of uTex, in pixels
uniform vec2  uResolution;   // output size
uniform int   uPass;
uniform float uThreshold;    // where "bright" begins
uniform float uKnee;         // soft shoulder so the threshold has no hard edge
uniform float uStrength;     // how much bloom to add back
uniform float uTime;

const int PASS_BRIGHT    = 0;
const int PASS_BLUR_H    = 1;
const int PASS_BLUR_V    = 2;
const int PASS_COMPOSITE = 3;

// Nine taps at 1.4px spacing. Wide enough to read as glow after two runs at
// quarter resolution (an effective ~45px radius at full size), cheap enough to
// stay honest on an integrated GPU.
const float W0 = 0.2270270270;
const float W1 = 0.1945945946;
const float W2 = 0.1216216216;
const float W3 = 0.0540540541;
const float W4 = 0.0162162162;

float hash21(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

vec3 blur(vec2 uv, vec2 dir) {
    vec3 acc = texture(uTex, uv).rgb * W0;
    acc += texture(uTex, uv + dir * 1.0).rgb * W1;
    acc += texture(uTex, uv - dir * 1.0).rgb * W1;
    acc += texture(uTex, uv + dir * 2.0).rgb * W2;
    acc += texture(uTex, uv - dir * 2.0).rgb * W2;
    acc += texture(uTex, uv + dir * 3.0).rgb * W3;
    acc += texture(uTex, uv - dir * 3.0).rgb * W3;
    acc += texture(uTex, uv + dir * 4.0).rgb * W4;
    acc += texture(uTex, uv - dir * 4.0).rgb * W4;
    return acc;
}

void main() {
    vec2 uv = gl_FragCoord.xy / uResolution;

    if (uPass == PASS_BRIGHT) {
        // Four bilinear taps at the source's half-texel offsets average sixteen
        // source pixels for the price of four - the standard downsample, and it
        // matters here because the dial is mostly sub-pixel hairlines that a
        // naive point sample would drop entirely.
        vec2 o = uTexel;
        vec3 c = texture(uTex, uv + vec2(-o.x, -o.y)).rgb
               + texture(uTex, uv + vec2( o.x, -o.y)).rgb
               + texture(uTex, uv + vec2(-o.x,  o.y)).rgb
               + texture(uTex, uv + vec2( o.x,  o.y)).rgb;
        c *= 0.25;

        // Soft-knee threshold: a hard cutoff makes bloom pop in and out as a
        // rotating hairline crosses it, which reads as flicker on exactly the
        // elements that rotate.
        float lum = dot(c, vec3(0.2126, 0.7152, 0.0722));
        float knee = max(uKnee, 1e-4);
        float soft = clamp((lum - uThreshold + knee) / (2.0 * knee), 0.0, 1.0);
        float contrib = max(soft * soft * knee, max(lum - uThreshold, 0.0));
        fragColor = vec4(c * (contrib / max(lum, 1e-5)), 1.0);
        return;
    }

    if (uPass == PASS_BLUR_H) {
        fragColor = vec4(blur(uv, vec2(uTexel.x * 1.4, 0.0)), 1.0);
        return;
    }

    if (uPass == PASS_BLUR_V) {
        fragColor = vec4(blur(uv, vec2(0.0, uTexel.y * 1.4)), 1.0);
        return;
    }

    // COMPOSITE.
    vec3 scene = texture(uScene, uv).rgb;
    vec3 bloom = texture(uTex, uv).rgb;
    vec3 col = scene + bloom * uStrength;

    // Vignette here rather than in the scene pass, so the bloom gathered near
    // the edges is dimmed once rather than twice.
    vec2 p = (gl_FragCoord.xy - 0.5 * uResolution) / min(uResolution.x, uResolution.y);
    col *= 1.0 - 0.22 * smoothstep(0.55, 1.30, length(p));

    // Grain last: it is a display-space effect, and blooming it would turn
    // dither into a glowing haze.
    col += (hash21(gl_FragCoord.xy + fract(uTime) * 91.7) - 0.5) * 0.008;

    col = max(col, vec3(0.0));
    col = col / (1.0 + col * 0.22);   // gentle shoulder, keeps cores white
    fragColor = vec4(col, 1.0);
}
