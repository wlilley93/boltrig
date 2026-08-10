/* familiar-bench - measure the real GPU cost of familiar.frag, headless.
 *
 * A raymarched wallpaper is easy to make beautiful and easy to make unaffordable, and you cannot
 * judge either by reading it. This renders the actual shader to an offscreen framebuffer on the real
 * GPU (surfaceless EGL, no compositor and no monitor needed) and reports milliseconds per frame, so
 * shader tuning is measured rather than guessed.
 *
 *   familiar-bench [shader.frag] [width] [height] [frames]
 *   defaults: ./familiar.frag 1920 1080 60
 *
 * Read the result against your frame budget: 16.7 ms = 60 fps, 33.3 ms = 30 fps. A wallpaper should
 * sit far under its budget - it is background furniture sharing the GPU with real work.
 */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <stdbool.h>
#include <time.h>
#include <math.h>

#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>

#include "genotype.h"

static const char *VERT_SRC =
    "#version 300 es\n"
    "void main() {\n"
    "  vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));\n"
    "  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);\n"
    "}\n";

static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static char *read_file(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n <= 0) { fclose(f); return NULL; }
    char *buf = malloc((size_t)n + 1);
    if (buf && fread(buf, 1, (size_t)n, f) == (size_t)n) buf[n] = 0;
    else { free(buf); buf = NULL; }
    fclose(f);
    return buf;
}

static GLuint compile(GLenum type, const char *src)
{
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok = 0;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[4096];
        glGetShaderInfoLog(s, sizeof log, NULL, log);
        fprintf(stderr, "familiar-bench: shader compile failed:\n%s\n", log);
        glDeleteShader(s);
        return 0;
    }
    return s;
}

/* Every uniform the bench sets is recorded, so it can then tell you about any the SHADER declares but
 * the bench never sets. Those default to zero, which is how a new uniform silently turned the bench
 * into a black rectangle once: uWorldRes = 0 divided the whole scene away. The pixel-statistics
 * readback caught it, but only as "SUSPECT"; this names the culprit. */
static const char *g_set[128];
static int g_nset;
static void mark(const char *n) { if (g_nset < 128) g_set[g_nset++] = n; }
static void set1f(GLuint p, const char *n, float v)
{ mark(n); glUniform1f(glGetUniformLocation(p, n), v); }
static void set2f(GLuint p, const char *n, float a, float b)
{ mark(n); glUniform2f(glGetUniformLocation(p, n), a, b); }
static void set4f(GLuint p, const char *n, float a, float b, float c, float d)
{ mark(n); glUniform4f(glGetUniformLocation(p, n), a, b, c, d); }

/* Scan the shader source for `uniform <type> <name>` and report any we did not set. */
static void report_unset_uniforms(const char *src)
{
    int missing = 0;
    for (const char *p = strstr(src, "uniform"); p; p = strstr(p + 7, "uniform")) {
        const char *q = p + 7;
        while (*q == ' ' || *q == '\t') q++;
        while (*q && *q != ' ' && *q != '\t') q++;              /* skip the type */
        while (*q == ' ' || *q == '\t') q++;
        char name[64]; size_t i = 0;
        while (*q && (isalnum((unsigned char)*q) || *q == '_') && i < sizeof name - 1) name[i++] = *q++;
        name[i] = 0;
        if (!i) continue;
        bool seen = false;
        for (int k = 0; k < g_nset; k++) if (!strcmp(g_set[k], name)) { seen = true; break; }
        if (!seen) {
            if (!missing++) fprintf(stderr, "  WARNING: uniform(s) the bench never sets (default 0):");
            fprintf(stderr, " %s", name);
        }
    }
    if (missing) fprintf(stderr, "\n           the measured frame is NOT what the wallpaper draws.\n");
}

int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "familiar.frag";
    int W = argc > 2 ? atoi(argv[2]) : 1920;
    int H = argc > 3 ? atoi(argv[3]) : 1080;
    int FRAMES = argc > 4 ? atoi(argv[4]) : 60;
    if (W <= 0 || H <= 0 || FRAMES <= 0) { fprintf(stderr, "bad args\n"); return 2; }

    /* surfaceless EGL: a real GPU context with no compositor, window or monitor */
    PFNEGLGETPLATFORMDISPLAYEXTPROC getPlatformDisplay =
        (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    EGLDisplay dpy = EGL_NO_DISPLAY;
    if (getPlatformDisplay)
        dpy = getPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, NULL);
    if (dpy == EGL_NO_DISPLAY) dpy = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    if (dpy == EGL_NO_DISPLAY) { fprintf(stderr, "familiar-bench: no EGL display\n"); return 1; }
    if (!eglInitialize(dpy, NULL, NULL)) { fprintf(stderr, "familiar-bench: eglInitialize failed\n"); return 1; }
    eglBindAPI(EGL_OPENGL_ES_API);

    const EGLint cfg_attr[] = {
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8,
        EGL_NONE,
    };
    EGLConfig cfg;
    EGLint n_cfg = 0;
    if (!eglChooseConfig(dpy, cfg_attr, &cfg, 1, &n_cfg) || n_cfg < 1) {
        fprintf(stderr, "familiar-bench: no EGL config\n");
        return 1;
    }
    const EGLint ctx_attr[] = { EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE };
    EGLContext ctx = eglCreateContext(dpy, cfg, EGL_NO_CONTEXT, ctx_attr);
    if (ctx == EGL_NO_CONTEXT) { fprintf(stderr, "familiar-bench: no EGL context\n"); return 1; }
    if (!eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx)) {
        fprintf(stderr, "familiar-bench: eglMakeCurrent failed\n");
        return 1;
    }

    /* offscreen target at the real wallpaper resolution */
    GLuint tex = 0, fbo = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        fprintf(stderr, "familiar-bench: incomplete framebuffer\n");
        return 1;
    }
    glViewport(0, 0, W, H);

    char *frag = read_file(path);
    if (!frag) { fprintf(stderr, "familiar-bench: cannot read %s\n", path); return 1; }
    GLuint vs = compile(GL_VERTEX_SHADER, VERT_SRC);
    GLuint fs = compile(GL_FRAGMENT_SHADER, frag);
    if (!vs || !fs) return 1;
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    GLint ok = 0;
    glGetProgramiv(prog, GL_LINK_STATUS, &ok);
    if (!ok) { fprintf(stderr, "familiar-bench: link failed\n"); return 1; }
    glUseProgram(prog);

    GLuint vao = 0;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);

    /* A representative mid-mood creature: awake, mildly tense, looking slightly off-centre. This is
     * the expensive case (the body fills a good part of the screen and the interior march runs). */
    set2f(prog, "iResolution", (float)W, (float)H);
    set4f(prog, "uAudio", 0.4f, 0.5f, 0.4f, 0.3f);
    set2f(prog, "uMouse", 0.62f, 0.55f);
    mark("iTime");   /* driven per frame in the loop below */
    set1f(prog, "uBeat", 0.2f);
    set1f(prog, "uDay", 0.6f);
    set1f(prog, "uValence", 0.65f);
    set1f(prog, "uArousal", 0.5f);
    set1f(prog, "uIrritation", 0.15f);
    set1f(prog, "uFatigue", 0.25f);
    set1f(prog, "uAttention", 0.6f);
    set1f(prog, "uSocial", 0.4f);
    set1f(prog, "uBuoyancy", 0.55f);
    set1f(prog, "uLuminosity", 0.6f);
    set1f(prog, "uTension", 0.35f);
    set1f(prog, "uGesture", 0.0f);
    set1f(prog, "uGestureAmt", 0.0f);
    /* One world, two windows: with no compositor here the bench IS the whole world. */
    /* By default the bench IS the whole world (the wallpaper case). The porthole can be checked too:
     *   BENCH_WORLD=1920x1080 BENCH_ORIGIN=194,992 BENCH_FILL=1 BENCH_PRESENCE=0 \
     *     familiar-bench familiar.frag 126 88
     * renders exactly what the bar surface renders, so the handover geometry can be verified with no
     * compositor, no monitor, and no unlocking anything. */
    float wW = (float)W, wH = (float)H, oX = 0.0f, oY = 0.0f, fill = 0.0f, pres = 1.0f;
    { const char *e; float a, b;
      if ((e = getenv("BENCH_WORLD"))  && sscanf(e, "%fx%f", &a, &b) == 2) { wW = a; wH = b; }
      if ((e = getenv("BENCH_ORIGIN")) && sscanf(e, "%f,%f", &a, &b) == 2) { oX = a; oY = b; }
      if ((e = getenv("BENCH_FILL")))     fill = (float)atof(e);
      if ((e = getenv("BENCH_PRESENCE"))) pres = (float)atof(e); }
    set2f(prog, "uWorldRes", wW, wH);
    set2f(prog, "uOrigin", oX, oY);
    set1f(prog, "uPxScale", 1.0f);
    /* Where the being docks, in SCREEN pixels: BENCH_DOCK="centreX,centreY,radius". Defaults to the
     * left end of a full-width 34 px bar. Keep this a knob, not a constant - it was a constant, the
     * bar moved, and the migration tests silently measured a dock that no longer existed. */
    float dx = 17.0f, dy = 17.0f, dr = 15.0f, fit = -1.0f;
    { const char *e; float a, b, cc;
      if ((e = getenv("BENCH_DOCK")) && sscanf(e, "%f,%f,%f", &a, &b, &cc) == 3) { dx=a; dy=b; dr=cc; }
      if ((e = getenv("BENCH_FIT"))) fit = (float)atof(e); }
    set2f(prog, "uCentreDock", (dx - 0.5f*wW)/wH, (wH - dy - 0.5f*wH)/wH);
    set1f(prog, "uScaleDock", dr/wH);
    set1f(prog, "uFitScale", (fit > 0.0f ? fit : (float)(W < H ? W : H)*0.5f)/wH);
    set1f(prog, "uFill", fill);
    set1f(prog, "uGaze", 1.0f);   /* watching the cursor; BENCH_U="uGaze=0" to let it wander */
    set1f(prog, "uPresence", pres);
    /* Override any float uniform from the environment, so a mood can be swept without a rebuild:
     *   BENCH_U="uValence=0.1,uIrritation=0.9" familiar-bench familiar.frag
     * This is how you check the palette actually holds across the whole emotional range. */
    /* uAudio is a vec4, which BENCH_U's scalar parser cannot reach - and the filament shell is
     * audio-driven, so its extreme states are exactly the ones worth capturing:
     *   BENCH_AUDIO="level,bass,mid,treble" familiar-bench familiar.frag */
    { const char *e = getenv("BENCH_AUDIO"); float al, ab, am, at;
      if (e && sscanf(e, "%f,%f,%f,%f", &al, &ab, &am, &at) == 4)
          set4f(prog, "uAudio", al, ab, am, at); }
    { const char *e = getenv("BENCH_U");
      if (e) {
        char tmp[512];
        snprintf(tmp, sizeof tmp, "%s", e);
        for (char *tok = strtok(tmp, ","); tok; tok = strtok(NULL, ",")) {
            char nm[64]; float v;
            if (sscanf(tok, "%63[^=]=%f", nm, &v) == 2) set1f(prog, nm, v);
        }
      } }
    /* THE GENOTYPE. This is what makes the bench a shape previewer and not just a timer:
     *   BENCH_GENE="shape=1,focal=0.85,cassiniB=0.85" BENCH_PPM=/tmp/fig8.ppm familiar-bench
     * draws a figure-of-8 with no compositor, no monitor and no genotype.json. It reads the
     * SAME key names and the SAME defaults as familiar-bg, from genotype.h, so what the
     * bench draws is what the desktop draws - a preview that could disagree with the real
     * thing would be worse than no preview at all.
     *
     * An unknown key is reported rather than ignored. Silently dropping a typo'd gene is how
     * you spend an afternoon concluding a parameter "does nothing". */
    { float gene[GENOTYPE_SLOTS];
      memcpy(gene, GENOTYPE_DEFAULTS, sizeof gene);
      const char *e = getenv("BENCH_GENE");
      if (e) {
        char tmp[512];
        snprintf(tmp, sizeof tmp, "%s", e);
        for (char *tok = strtok(tmp, ","); tok; tok = strtok(NULL, ",")) {
            char nm[64]; float v;
            if (sscanf(tok, "%63[^=]=%f", nm, &v) != 2) continue;
            int hit = 0;
            for (int i = 0; i < GENOTYPE_SLOTS; i++)
                if (GENOTYPE_KEYS[i] && !strcmp(nm, GENOTYPE_KEYS[i])) { gene[i] = v; hit = 1; break; }
            if (!hit) fprintf(stderr, "familiar-bench: BENCH_GENE: no gene named '%s' - ignored\n", nm);
        }
      }
      mark("uGene");
      glUniform4fv(glGetUniformLocation(prog, "uGene"), GENOTYPE_VEC4S, gene);
    }
    report_unset_uniforms(frag);
    free(frag);

    GLint uTime = glGetUniformLocation(prog, "iTime");

    /* warm up: shader/driver compilation and caches must not land in the measurement */
    for (int i = 0; i < 10; i++) {
        glUniform1f(uTime, (float)i * 0.016f);
        glDrawArrays(GL_TRIANGLES, 0, 3);
    }
    glFinish();

    double t0 = now_s();
    for (int i = 0; i < FRAMES; i++) {
        glUniform1f(uTime, 10.0f + (float)i * 0.016f);
        glDrawArrays(GL_TRIANGLES, 0, 3);
    }
    glFinish();
    double dt = now_s() - t0;

    double ms = dt * 1000.0 / (double)FRAMES;
    printf("%s  %dx%d  %.2f ms/frame  (%.0f fps)  budget: 16.7ms=60fps 33.3ms=30fps\n",
           path, W, H, ms, 1000.0 / ms);

    /* Sanity readback. Optimising a shader you cannot see is how you ship a black rectangle, so
     * check the frame actually contains an image: some light, some variation, no NaN. */
    unsigned char *px = malloc((size_t)W * (size_t)H * 4);
    if (px) {
        glReadPixels(0, 0, W, H, GL_RGBA, GL_UNSIGNED_BYTE, px);
        double sum = 0.0, sum2 = 0.0;
        int lo = 255, hi = 0, lit = 0;
        long n = (long)W * H;
        for (long i = 0; i < n; i++) {
            int l = (px[i*4] * 30 + px[i*4+1] * 59 + px[i*4+2] * 11) / 100;
            sum += l; sum2 += (double)l * l;
            if (l < lo) lo = l;
            if (l > hi) hi = l;
            if (l > 24) lit++;
        }
        double mr = 0.0, mg = 0.0, mb = 0.0;   /* the being's own colour, lit pixels only */
        double cx = 0.0, cy = 0.0, cw = 0.0;
        int topRow = -1;   /* highest lit row, in rows from the TOP of the window */
        for (long i = 0; i < n; i++) {
            int l = (px[i*4] * 30 + px[i*4+1] * 59 + px[i*4+2] * 11) / 100;
            if (l > 24) {
                cx += (double)(i % W) * l; cy += (double)(i / W) * l; cw += l;
                mr += px[i*4]; mg += px[i*4+1]; mb += px[i*4+2];
                int fromTop = H - 1 - (int)(i / W);
                if (topRow < 0 || fromTop < topRow) topRow = fromTop;
            }
        }
        double mean = sum / (double)n;
        double sd = (sum2 / (double)n) - mean * mean;
        sd = sd > 0.0 ? sqrt(sd) : 0.0;
        printf("  image: mean=%.1f sd=%.1f min=%d max=%d lit=%.1f%% -> %s\n",
               mean, sd, lo, hi, 100.0 * (double)lit / (double)n,
               (hi > 40 && sd > 3.0) ? "looks like a creature" : "SUSPECT (flat/black?)");
        if (cw > 0.0) {
            printf("  centroid: %.1f,%.1f px from bottom-left; top edge %d px from the top\n",
                   cx/cw, cy/cw, topRow);
            printf("  lit colour: R%.0f G%.0f B%.0f -> %s\n", mr/lit, mg/lit, mb/lit,
                   (mb > mg && mg > mr) ? "blue family"
                   : (mb > mg && mr > mg) ? "PURPLE (red has overtaken green)" : "not blue");
        }
        /* Optional frame dump, so the look can be reviewed (or sent to someone) without a monitor,
         * a compositor, or a particular mood happening to occur on the desktop:
         *   BENCH_U="uIrritation=0.9" BENCH_PPM=/tmp/angry.ppm familiar-bench familiar.frag
         * Binary PPM keeps this dependency-free; convert with any tool that reads P6. */
        const char *dump = getenv("BENCH_PPM");
        if (dump) {
            FILE *f = fopen(dump, "wb");
            if (f) {
                fprintf(f, "P6\n%d %d\n255\n", W, H);
                for (int y = H - 1; y >= 0; y--)          /* GL reads bottom-up; PPM is top-down */
                    for (int x = 0; x < W; x++) {
                        long i = (long)y * W + x;
                        fwrite(&px[i*4], 1, 3, f);
                    }
                fclose(f);
                printf("  wrote %s (%dx%d)\n", dump, W, H);
            } else {
                fprintf(stderr, "familiar-bench: cannot write %s\n", dump);
            }
        }
        free(px);
    }
    return 0;
}
