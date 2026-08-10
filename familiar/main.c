/* familiar-bg - the living familiar: a detailed raymarched creature desktop background for Hyprland.
 *
 * The successor to orb-bg. Same proven harness (one wlr-layer-shell BACKGROUND surface, EGL/GLES3,
 * frame-callback paced), but the crude 2D orb shader is replaced by a fully volumetric raymarched
 * creature (familiar.frag) whose entire look is driven by boltrig's nine-scalar phenotype. Fed every
 * frame by four input streams merged on the CPU:
 *
 *   phenotype - boltrig's emotion relay publishes $XDG_RUNTIME_DIR/boltrig-phenotype.json (~2 Hz); its
 *               nine 0..1 mood scalars (valence, arousal, irritation, fatigue, attention, social,
 *               buoyancy, luminosity, tension) ARE the creature's inner state. The host smooths them
 *               toward their target (mood morphs, never snaps) and hands them to the shader, which owns
 *               palette, motion, silhouette, subsurface glow and gaze. Stale/absent (or FAMILIAR_PHENO=0)
 *               falls back to a calm resting baseline (PHENO_IDLE).
 *   audio    - a thread popen()s a PipeWire capture of the default sink's monitor, runs a 1024-point FFT
 *              and reduces it to smoothed level/bass/mid/treble bands plus a beat-onset envelope.
 *   mouse    - a thread polls the Hyprland IPC socket ("cursorpos") at 10 Hz; the shader gazes toward it
 *              in proportion to uAttention.
 *   time     - local wall-clock hour becomes a 0..1 "day warmth" (warm by day, cool at night).
 *
 * The shader is loaded from ~/.config/familiar/familiar.frag (override: $FAMILIAR_SHADER) so the look is
 * live-tweakable without a recompile; SIGUSR1 hot-reloads it, keeping the old program if the new one
 * fails to compile. Rendering is frame-callback paced (stops for free when occluded / display off) with
 * an additional FPS cap ($FAMILIAR_FPS, default 60).
 *
 * Single-threaded Wayland: only the main thread touches libwayland. The audio and mouse threads write
 * into small mutex-guarded structs. If audio capture dies it is respawned every few seconds; if it is
 * absent entirely the familiar still lives on phenotype + time + mouse. WL-1: this surface imports
 * nothing from boltrig, consuming only the versioned phenotype file. WL-2: no compositor / no EGL / no
 * phenotype degrades to a typed message or the resting baseline, never a crash.
 */
#define _DEFAULT_SOURCE           /* M_PI, usleep on glibc with -std=c11 */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <stddef.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <math.h>
#include <time.h>
#include <signal.h>
#include <poll.h>
#include <pthread.h>
#include <unistd.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/un.h>

#include <wayland-client.h>
#include <wayland-egl.h>
#include <EGL/egl.h>
#include <GLES3/gl3.h>

#include "genotype.h"
#include "xdg-shell-client-protocol.h"
#include "wlr-layer-shell-unstable-v1-client-protocol.h"

/* ------------------------------------------------------------------ config */
/* A wallpaper is background furniture: it shares the GPU with real work, so it is paced and scaled
 * conservatively by default. 30 fps is imperceptible for a slow-breathing creature and halves the
 * per-second GPU load; RENDER_SCALE renders the raymarch offscreen at a fraction of the display size
 * and upscales it, which is the single biggest saving because raymarch cost is per pixel. Both are
 * overridable ($FAMILIAR_FPS, $FAMILIAR_SCALE) - measure changes with familiar-bench. */
#define DEFAULT_FPS        30   /* 30 fps is imperceptible for a glacial creature and HALVES the
                                 * per-second GPU load. Measured on this box (Radeon 680M, 2304x1296):
                                 * 60 fps at scale 1.5 was ~650 ms of GPU per second and the desktop
                                 * felt laggy; 30 fps at 1.25 is ~230 ms/s and does not. */
#define DEFAULT_SCALE      1.25f  /* offscreen render FACTOR. >1 supersamples: the being is built from
                                   * fine filaments that alias badly at native resolution, which is why
                                   * it looks softer here than in a retina browser preview. 2.0 was the
                                   * sharpest option (an exact box-filter downscale) but cost ~14 ms a
                                   * frame at this display's geometry; 1.25 smudges the downscale
                                   * slightly but keeps the wallpaper well under budget alongside real
                                   * work. <1 trades sharpness for speed. */
#define MIN_SCALE          0.30f
#define MAX_SCALE          2.00f
#define FFT_N              1024
#define AUDIO_RATE         44100
#define AUDIO_HOP          512
#define MOUSE_POLL_MS      50   /* the gaze has to be quick to read as deliberate */
#define STATE_POLL_FRAMES  15     /* stat() the emotion + phenotype files every N frames (~4 Hz at 60) */
#define EMO_TAU            0.9f   /* seconds, emotion crossfade time constant */
#define PRESENCE_TAU       0.28f  /* seconds; the EXIT time constant. Collapsing out of your way when
                                   * a window opens should be quick - the whole exit lands in well
                                   * under a second. Override with $FAMILIAR_PRESENCE_TAU (0.05..5.0).
                                   * Note the other half of "snappy" is detection latency: the
                                   * workspace is polled every MOUSE_POLL_MS, not every fifth poll. */
#define PRESENCE_IN_TAU    0.80f  /* seconds; the ENTRANCE time constant, deliberately slower than
                                   * the exit: the being fades in over about three seconds - present,
                                   * but never keeping you waiting. Override with
                                   * $FAMILIAR_PRESENCE_IN_TAU (0.05..5.0). */
#define PHENO_FRESH_S      5.0    /* seconds; a phenotype file older than this falls back to idle */
#define PHENO_MAX_BYTES    4096   /* phenotype file read cap (the real file is ~250 bytes) */

/* Default capture command; overridden by $FAMILIAR_AUDIO_CMD. Verified on this box (PipeWire 1.6.2):
 * `-P stream.capture.sink=true` makes WirePlumber bind the stream to the CURRENT default sink's
 * monitor (what is playing, not the mic) and it follows default-sink changes. */
#ifndef AUDIO_CMD_DEFAULT
#define AUDIO_CMD_DEFAULT \
    "pw-record -P stream.capture.sink=true --rate 44100 --channels 1 --format s16 --raw - 2>/dev/null"
#endif

/* ------------------------------------------------------------- phenotype */
/* The familiar has no discrete emotion table: its whole inner state is the nine 0..1 phenotype
 * scalars boltrig's emotion relay publishes. The shader owns the entire look, deriving palette,
 * motion, silhouette and gaze from these; the host only reads the file, smooths the scalars toward
 * their targets (so mood morphs instead of snapping), and uploads them. */
typedef struct {
    float valence, arousal, irritation, fatigue, attention,
          social, buoyancy, luminosity, tension;
} Phenotype;

/* Resting baseline, used whenever no fresh phenotype is published - which is most of the time, since
 * the emotion relay only publishes while events are flowing and anything older than PHENO_FRESH_S is
 * ignored. This IS the "nothing is happening" state, so it has to be genuinely idle: the old 0.28
 * arousal had the being working hard at a desk where nothing was going on. Calm, content, awake. */
static const Phenotype PHENO_IDLE = {
    .valence = 0.60f, .arousal = 0.07f, .irritation = 0.02f, .fatigue = 0.22f,
    .attention = 0.50f, .social = 0.40f, .buoyancy = 0.55f, .luminosity = 0.50f, .tension = 0.03f,
};

/* ------------------------------------------------------------ shared state */
static volatile sig_atomic_t running = 1;
static volatile sig_atomic_t want_reload = 0;
static volatile sig_atomic_t want_companion_toggle = 0;
static bool companion_mode = false;

static struct {
    pthread_mutex_t mu;
    float level, bass, mid, treble, beat;
} g_audio = { .mu = PTHREAD_MUTEX_INITIALIZER };

static struct {
    pthread_mutex_t mu;
    float level, beat;
    time_t mtime;
} g_voice = { .mu = PTHREAD_MUTEX_INITIALIZER, .level = 0.0f, .beat = 0.0f, .mtime = 0 };

/* Chat surface geometry published by familiar-chat; the companion orb tracks this rectangle. */
#define GEOM_PATH_DEFAULT "/tmp/boltrig-rt/familiar-geometry.json"
typedef enum { OM_IMMERSIVE, OM_PORTAL, OM_WINDOW } OverlayMode;
static struct {
    OverlayMode mode;
    int32_t x, y, w, h;
    time_t mtime;
    bool dirty;
} g_geom = { .mode = OM_IMMERSIVE, .mtime = 0, .dirty = false };

static struct {
    pthread_mutex_t mu;
    float x, y;          /* normalized 0..1, origin bottom-left */
    bool valid;
    /* Is the pointer actually being used? The being looks at you when you are here and lets its gaze
     * wander when you are not. "Not here" is either a cursor that has not moved for a while, or one
     * parked hard against the screen edge - which is exactly where lan-mouse leaves it when you have
     * crossed over to the Mac, so the being correctly stops staring at a cursor you took with you. */
    double last_move;    /* seconds, monotonic */
    bool   at_edge;
} g_mouse = { .mu = PTHREAD_MUTEX_INITIALIZER };
#define GAZE_IDLE_S  2.5   /* still for this long and it looks away */
static double now_s(void);

/* Presence: 1 = the desktop is bare, so the being takes the whole screen; 0 = you are working, so it
 * withdraws to a small bead beside the clock. With the wallpaper retired in favour of the blurred
 * chat companion, the target is now always 0 and the migration is between the clockbar bead and the
 * large centred companion, driven by SIGUSR2. */
static struct {
    pthread_mutex_t mu;
    float target;
} g_presence = { .mu = PTHREAD_MUTEX_INITIALIZER, .target = 1.0f };

/* --------------------------------------------------------------- wayland */
static struct wl_display    *dpy;
static struct wl_compositor *compositor;
static struct wl_seat       *seat;
static struct wl_pointer    *pointer;
static struct zwlr_layer_shell_v1 *layer_shell;
static struct wl_surface    *surface;
static struct zwlr_layer_surface_v1 *layer_surface;
static struct wl_egl_window *egl_window;
static int32_t surf_w = 1920, surf_h = 1080;
static bool configured = false;
static bool frame_inflight = false;

static EGLDisplay egl_dpy;
static EGLContext egl_ctx;
static EGLSurface egl_surf;

/* Offscreen render target for the scaled raymarch pass (see DEFAULT_SCALE). */
static GLuint rt_fbo = 0, rt_tex = 0;
static int32_t rt_w = 0, rt_h = 0;
/* The porthole's own offscreen target. It is tiny, so it is supersampled harder than the wallpaper:
 * this is the one place the being is only 30 px across and every jagged filament shows. */
static GLuint brt_fbo = 0, brt_tex = 0;
static int32_t brt_w = 0, brt_h = 0;
#define BEAD_SS 2.0f   /* integer, for the same reason as DEFAULT_SCALE */
#define BAR_INSET 22   /* px from the bar's left edge to the being's left edge */
#define BAR_DROP  9    /* px below the bar's vertical centre; it hangs a little low on purpose */
static float render_scale = DEFAULT_SCALE;

/* (Re)build the offscreen target to match the current surface size and scale. Falls back to drawing
 * straight to the display (rt_fbo = 0) if the framebuffer is ever incomplete, so a driver quirk
 * costs sharpness, never the wallpaper. */
static void rt_resize(void)
{
    int32_t w = (int32_t)((float)surf_w * render_scale + 0.5f);
    int32_t h = (int32_t)((float)surf_h * render_scale + 0.5f);
    if (w < 1) w = 1;
    if (h < 1) h = 1;
    if (rt_fbo && w == rt_w && h == rt_h) return;
    rt_w = w; rt_h = h;
    if (!rt_tex) glGenTextures(1, &rt_tex);
    glBindTexture(GL_TEXTURE_2D, rt_tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, rt_w, rt_h, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    if (!rt_fbo) glGenFramebuffers(1, &rt_fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, rt_fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, rt_tex, 0);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        fprintf(stderr, "familiar-bg: offscreen target incomplete, rendering at native size\n");
        glDeleteFramebuffers(1, &rt_fbo);
        rt_fbo = 0;
    }
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

/* Same construction as rt_resize, for the porthole. Incomplete -> draw at native size, never fail. */
static void brt_resize(int32_t w0, int32_t h0)
{
    int32_t w = (int32_t)((float)w0*BEAD_SS + 0.5f), h = (int32_t)((float)h0*BEAD_SS + 0.5f);
    if (brt_fbo && w == brt_w && h == brt_h) return;
    brt_w = w; brt_h = h;
    if (!brt_tex) glGenTextures(1, &brt_tex);
    glBindTexture(GL_TEXTURE_2D, brt_tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, brt_w, brt_h, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    if (!brt_fbo) glGenFramebuffers(1, &brt_fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, brt_fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, brt_tex, 0);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        fprintf(stderr, "familiar-bg: porthole target incomplete, drawing at native size\n");
        glDeleteFramebuffers(1, &brt_fbo);
        brt_fbo = 0;
    }
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}


static GLuint program = 0;
static struct {
    GLint iTime, iResolution, uAudio, uBeat, uMouse, uDay,
          uValence, uArousal, uIrritation, uFatigue, uAttention,
          uSocial, uBuoyancy, uLuminosity, uTension,
          uGesture, uGestureAmt, uPresence, uFill, uCentreDock,
          uWorldRes, uOrigin, uPxScale, uScaleDock, uFitScale, uGaze, uHover,
          uCompanion, uAperture, uGene;
} uni;

/* THE BEAD: a second, small layer surface on the OVERLAY layer. Hyprland ignores set_layer on an
 * already-mapped surface, and the wallpaper layer is behind your windows, so the withdrawn familiar
 * needs a surface of its own that is born on the overlay layer. Overlay sits ABOVE waybar, so this
 * floats on the bar to the right of the clock and reads as part of it - without having to reimplement
 * a bar (fonts, modules, tray, click handling) to get there. */
static struct wl_surface *bead_surface;
static struct zwlr_layer_surface_v1 *bead_ls;
static struct wl_egl_window *bead_egl_window;
static EGLSurface bead_egl_surf = EGL_NO_SURFACE;
static int32_t bead_w = 30, bead_h = 30;
static bool bead_configured = false;

static void bead_configure(void *data, struct zwlr_layer_surface_v1 *ls,
                           uint32_t serial, uint32_t w, uint32_t h)
{
    (void)data;
    zwlr_layer_surface_v1_ack_configure(ls, serial);
    if (w > 0) bead_w = (int32_t)w;
    if (h > 0) bead_h = (int32_t)h;
    if (bead_egl_window) wl_egl_window_resize(bead_egl_window, bead_w, bead_h, 0, 0);
    bead_configured = true;
}
static void bead_closed(void *data, struct zwlr_layer_surface_v1 *ls)
{
    (void)data; (void)ls; bead_surface = NULL;
}
static const struct zwlr_layer_surface_v1_listener bead_listener = { bead_configure, bead_closed };

/* THE SUMMON. The bead accepts clicks ONLY while the being is withdrawn (docked): its input
 * region is the bead's own rect then, and EMPTY whenever the familiar owns the screen, so it
 * can never intercept a click meant for your windows. A click on the docked clockbar doughnut
 * sends the same SIGUSR1 toggle that Super+Space sends to familiar-chat, opening the chat
 * overlay and the centred companion orb. */
static bool bead_hover = false;
static bool docked_mode;   /* defined below with the layer-surface code (tentative here) */
static bool port_wide;     /* defined below with the porthole geometry (tentative here) */
static ssize_t hypr_query(const char *path, const char *cmd, char *buf, size_t bufsz);

static void toggle_chat_overlay(void)
{
    /* The clockbar doughnut is the same action as Super+Space: toggle the chat overlay
     * (and therefore the centred companion orb). Fire-and-forget via systemctl. */
    pid_t pid = fork();
    if (pid == 0) {
        execlp("systemctl", "systemctl", "--user", "kill", "-s", "USR1", "familiar-chat.service", (char *)NULL);
        _exit(1);
    }
}

static void set_bead_input(bool on)
{
    if (!bead_surface) return;
    struct wl_region *region = wl_compositor_create_region(compositor);
    if (on) wl_region_add(region, 0, 0, bead_w, bead_h);
    wl_surface_set_input_region(bead_surface, region);
    wl_region_destroy(region);
    wl_surface_commit(bead_surface);   /* input regions apply only on commit */
}

/* The bead surface is purely decorative now. Clicks go through to the clockbar's own
 * familiar module (custom/familiar), which sends the same SIGUSR1 toggle as Super+Space. */
static void update_bead_input(void)
{
    set_bead_input(false);
}

static void pointer_enter(void *data, struct wl_pointer *p, uint32_t serial,
                          struct wl_surface *surf, wl_fixed_t sx, wl_fixed_t sy)
{
    (void)data; (void)p; (void)serial; (void)sx; (void)sy;
    if (surf == bead_surface) bead_hover = true;
}
static void pointer_leave(void *data, struct wl_pointer *p, uint32_t serial, struct wl_surface *surf)
{
    (void)data; (void)p; (void)serial;
    if (surf == bead_surface) bead_hover = false;
}
static void pointer_button(void *data, struct wl_pointer *p, uint32_t serial,
                           uint32_t t, uint32_t button, uint32_t state)
{
    (void)data; (void)p; (void)serial; (void)t;
    if (button == 0x110 && state == 1 && bead_hover && docked_mode)   /* BTN_LEFT press, docked only */
        toggle_chat_overlay();
}
static void pointer_motion(void *d, struct wl_pointer *p, uint32_t t, wl_fixed_t x, wl_fixed_t y)
{ (void)d; (void)p; (void)t; (void)x; (void)y; }
static void pointer_frame(void *d, struct wl_pointer *p) { (void)d; (void)p; }
static void pointer_axis(void *d, struct wl_pointer *p, uint32_t t, uint32_t a, wl_fixed_t v)
{ (void)d; (void)p; (void)t; (void)a; (void)v; }
static void pointer_axis_source(void *d, struct wl_pointer *p, uint32_t s) { (void)d; (void)p; (void)s; }
static void pointer_axis_stop(void *d, struct wl_pointer *p, uint32_t t, uint32_t a)
{ (void)d; (void)p; (void)t; (void)a; }
static void pointer_axis_discrete(void *d, struct wl_pointer *p, uint32_t a, int32_t v)
{ (void)d; (void)p; (void)a; (void)v; }
static const struct wl_pointer_listener pointer_listener = {
    .enter = pointer_enter, .leave = pointer_leave, .motion = pointer_motion,
    .button = pointer_button, .axis = pointer_axis, .frame = pointer_frame,
    .axis_source = pointer_axis_source, .axis_stop = pointer_axis_stop,
    .axis_discrete = pointer_axis_discrete,
};

static float dock_u = 0.0f, dock_v = 0.0f;   /* the bead's centre in shader uv space */
static float dock_scale = 0.0125f;           /* the being's uv radius when fully docked */
static int   port_ox = 0, port_oy = 0;       /* porthole origin in GL pixels (y up) */
static float fit_scale = 0.04f;              /* largest uv radius the porthole can hold */
static float presence_tau = PRESENCE_TAU;       /* exit (collapse) time constant, seconds */
static float presence_tau_in = PRESENCE_IN_TAU; /* entrance (fade-in) time constant, seconds */

/* The porthole's two shapes. DOCKED is a small patch around the resting spot, deliberately ending
 * above the strip where hyprbars draws each window's buttons. WIDE is grown for the migration only,
 * so the being withdraws OVER your windows instead of disappearing behind them - it is a background
 * wallpaper the rest of the time, and a wallpaper cannot draw on top of anything.
 *
 * It is never grown to the full screen, and never near the right edge: lan-mouse's capture strip
 * lives at x = screen-1, and putting one of ours over it swallows the cursor coming from the Mac.
 * That has happened twice; the width cap is the standing lesson, not a guess. */
static int dock_x = 14, dock_y = 7, dock_px = 30, port_pad = 48, port_drop = 9;
static bool port_wide = false;
static bool bead_wants_clear = false;
typedef enum { PG_DOCKED, PG_TRANSITION, PG_COMPANION } PortholeMode;

/* Position/size the bead layer surface from a screen-rectangle. anchor_all uses all four
 * layer-shell edges with margins so the compositor centres the surface; otherwise it is
 * anchored top-left with a top/left margin. */
static void porthole_set_rect(int32_t x, int32_t y, int32_t w, int32_t h, bool anchor_all)
{
    int32_t W32 = surf_w > 0 ? surf_w : 1920, H32 = surf_h > 0 ? surf_h : 1080;
    bead_w = w > 0 ? w : 280;
    bead_h = h > 0 ? h : 280;
    int32_t port_x = x < 0 ? 0 : x;
    int32_t port_y = y < 0 ? 0 : y;
    if (port_x + bead_w > W32) bead_w = W32 - port_x;
    if (port_y + bead_h > H32) bead_h = H32 - port_y;
    if (bead_w < 1) bead_w = 1;
    if (bead_h < 1) bead_h = 1;

    float cx = (float)(port_x + bead_w/2);
    float cy = (float)(port_y + bead_h/2);
    port_ox = port_x;
    port_oy = H32 - port_y - bead_h;              /* GL origin is bottom-left */

    float W = (float)W32, H = (float)H32;
    dock_u = (cx - 0.5f*W)/H;
    dock_v = (H - cy - 0.5f*H)/H;
    dock_scale = ((float)bead_w*0.40f)/H;         /* companion: the being fills more of the square */

    float fit = 1e9f;
    if (port_x > 0            && cx - (float)port_x < fit)            fit = cx - (float)port_x;
    if (port_x + bead_w < W32 && (float)(port_x + bead_w) - cx < fit) fit = (float)(port_x + bead_w) - cx;
    if (port_y > 0            && cy - (float)port_y < fit)            fit = cy - (float)port_y;
    if (port_y + bead_h < H32 && (float)(port_y + bead_h) - cy < fit) fit = (float)(port_y + bead_h) - cy;
    if (fit > 1e8f) fit = (float)(bead_w < bead_h ? bead_w : bead_h)*0.5f;
    fit_scale = fit/H;

    if (bead_ls) {
        zwlr_layer_surface_v1_set_size(bead_ls, (uint32_t)bead_w, (uint32_t)bead_h);
        if (anchor_all) {
            uint32_t all = ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP | ZWLR_LAYER_SURFACE_V1_ANCHOR_BOTTOM |
                           ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT | ZWLR_LAYER_SURFACE_V1_ANCHOR_RIGHT;
            zwlr_layer_surface_v1_set_anchor(bead_ls, all);
            int32_t mr = W32 - port_x - bead_w; if (mr < 0) mr = 0;
            int32_t mb = H32 - port_y - bead_h; if (mb < 0) mb = 0;
            zwlr_layer_surface_v1_set_margin(bead_ls, port_y, mr, mb, port_x);
        } else {
            zwlr_layer_surface_v1_set_anchor(bead_ls,
                ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP | ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT);
            zwlr_layer_surface_v1_set_margin(bead_ls, port_y, 0, 0, port_x);
        }
        wl_surface_commit(bead_surface);
    }
    /* The input region tracks the porthole's shape: clickable only as the small docked bead. */
    update_bead_input();
    /* Never let the previous buffer present squashed after this resize (see bead_clear_now). */
    bead_wants_clear = true;
    g_geom.dirty = false;
}

static void porthole_geometry(PortholeMode mode)
{
    int32_t W32 = surf_w > 0 ? surf_w : 1920, H32 = surf_h > 0 ? surf_h : 1080;
    if (mode == PG_COMPANION) {
        /* Large centred square for the blurred chat companion. Sized relative to the smaller
         * screen dimension so it survives monitor changes, with a hard cap so it never fills
         * the whole display. */
        int dim = (int)(0.42f * (float)(W32 < H32 ? W32 : H32));
        if (dim > 520) dim = 520;
        if (dim < 280) dim = 280;
        int port_x = (W32 - dim) / 2;
        int port_y = (H32 - dim) / 2;
        porthole_set_rect(port_x, port_y, dim, dim, false);
        port_wide = false;
        return;
    }

    int port_x, port_y;
    float cx, cy;   /* porthole centre in screen pixels */
    if (mode == PG_TRANSITION) {
        /* Enough to hold the being at full size at screen centre, plus its corona - and no more. */
        int reach = (int)(0.25f*(float)H32) + 60;
        port_x = 0;
        port_y = 0;
        bead_w = W32/2 + reach;  if (bead_w > W32 - 200) bead_w = W32 - 200;   /* never the KVM edge */
        bead_h = H32/2 + reach;  if (bead_h > H32 - 60)  bead_h = H32 - 60;
        cx = (float)(dock_x + dock_px/2);
        cy = (float)(dock_y + dock_px/2);
    } else {
        /* Docked: the clockbar indicator is now a waybar module, so this layer surface is hidden.
         * Keep it at 1x1 so it takes no visible space but remains alive for the companion summon. */
        port_x = 0; port_y = 0;
        bead_w = bead_h = 1;
        cx = (float)(dock_x + dock_px/2);
        cy = (float)(dock_y + dock_px/2);
    }
    port_ox = port_x;
    port_oy = H32 - port_y - bead_h;              /* GL origin is bottom-left */

    float W = (float)W32, H = (float)H32;
    dock_u = (cx - 0.5f*W)/H;
    dock_v = (H - cy - 0.5f*H)/H;
    dock_scale = ((float)dock_px*0.5f)/H;

    float fit = 1e9f;
    if (port_x > 0            && cx - (float)port_x < fit)            fit = cx - (float)port_x;
    if (port_x + bead_w < W32 && (float)(port_x + bead_w) - cx < fit) fit = (float)(port_x + bead_w) - cx;
    if (port_y > 0            && cy - (float)port_y < fit)            fit = cy - (float)port_y;
    if (port_y + bead_h < H32 && (float)(port_y + bead_h) - cy < fit) fit = (float)(port_y + bead_h) - cy;
    if (fit > 1e8f) fit = (float)(bead_w < bead_h ? bead_w : bead_h)*0.5f;
    fit_scale = fit/H;

    port_wide = (mode == PG_TRANSITION);
    if (bead_ls) {
        zwlr_layer_surface_v1_set_size(bead_ls, (uint32_t)bead_w, (uint32_t)bead_h);
        zwlr_layer_surface_v1_set_anchor(bead_ls,
            ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP | ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT);
        zwlr_layer_surface_v1_set_margin(bead_ls, port_y, 0, 0, port_x);
        wl_surface_commit(bead_surface);
    }
    update_bead_input();
    bead_wants_clear = true;
}

/* Clear the bead surface to fully transparent, right now. Without this the compositor can hold
 * the PREVIOUS buffer for a frame or two after a resize: a full-size creature frame from the
 * wide porthole then presents squashed into the 106x52 dock - an "oval orb" at the top-left
 * that looks like a leftover of the old fly-to-bar animation (the reported 2nd-orb glitch). */
static void bead_clear_now(void)
{
    if (bead_egl_surf == EGL_NO_SURFACE) return;
    if (eglMakeCurrent(egl_dpy, bead_egl_surf, bead_egl_surf, egl_ctx)) {
        glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        eglSwapBuffers(egl_dpy, bead_egl_surf);
        eglMakeCurrent(egl_dpy, egl_surf, egl_surf, egl_ctx);
    }
}

static void read_geometry(void);

static void set_companion_mode(bool want)
{
    if (want == companion_mode) return;
    // Blank the old content BEFORE the geometry changes. Otherwise the compositor can present
    // the previous buffer (docked doughnut or companion orb) at the new size/position for a
    // frame, which reads as the orb flying in from the top-left.
    bead_clear_now();
    companion_mode = want;
    if (companion_mode) {
        read_geometry();
        if (g_geom.mode == OM_IMMERSIVE)
            porthole_geometry(PG_COMPANION);
        else
            porthole_set_rect(g_geom.x, g_geom.y, g_geom.w, g_geom.h, true);
    } else {
        porthole_geometry(PG_DOCKED);
    }
}


static void on_signal(int sig)
{
    if (sig == SIGUSR1) want_reload = 1;
    else if (sig == SIGUSR2) want_companion_toggle = 1;
    else running = 0;
}

/* registry ---------------------------------------------------------------- */
static void registry_global(void *data, struct wl_registry *reg, uint32_t name,
                            const char *iface, uint32_t version)
{
    (void)data;
    if (strcmp(iface, wl_compositor_interface.name) == 0)
        compositor = wl_registry_bind(reg, name, &wl_compositor_interface, version < 4 ? version : 4);
    else if (strcmp(iface, wl_seat_interface.name) == 0)
        seat = wl_registry_bind(reg, name, &wl_seat_interface, 1);
    else if (strcmp(iface, zwlr_layer_shell_v1_interface.name) == 0)
        /* v2+ for set_layer: the familiar moves between the BACKGROUND layer (full presence)
         * and the OVERLAY layer (docked bead, which must float above your windows). */
        layer_shell = wl_registry_bind(reg, name, &zwlr_layer_shell_v1_interface,
                                       version < 5 ? version : 5);
}
static void registry_global_remove(void *d, struct wl_registry *r, uint32_t n) { (void)d; (void)r; (void)n; }
static const struct wl_registry_listener registry_listener = { registry_global, registry_global_remove };

/* layer surface ----------------------------------------------------------- */
/* Opaque as a wallpaper (lets the compositor skip everything behind it), but NOT when docked: in that
 * mode the surface floats on the overlay layer and everything except the bead must be see-through. */
static bool docked_mode = false;

static void set_opaque(void)
{
    struct wl_region *region = wl_compositor_create_region(compositor);
    if (!docked_mode) wl_region_add(region, 0, 0, surf_w, surf_h);
    wl_surface_set_opaque_region(surface, region);
    wl_region_destroy(region);
}

/* Track whether the being is withdrawn, purely so the wallpaper can drop its opaque-region hint while
 * it is drawing transparently.
 *
 * The main surface MUST STAY ON THE BACKGROUND LAYER. An earlier version moved it to the overlay layer
 * when docking, on the theory that the bead needed to float above windows. That put a full-screen
 * surface above lan-mouse's edge-capture strip and broke the KVM bridge to the Mac. The bead has its
 * own small overlay surface for that job; the wallpaper never leaves the background. */
static void set_docked(bool want)
{
    if (want == docked_mode || !layer_surface) return;
    docked_mode = want;
    set_opaque();
    /* The summon click target exists only while docked (the being withdrawn); with the familiar
     * fullscreen the bead's input region is EMPTY so it can never steal a click. */
    update_bead_input();
    if (!want) bead_hover = false;
    wl_surface_commit(surface);
}

/* An EMPTY input region, not the default (whole-surface) one. A decorative background must
 * never claim pointer/keyboard input: left at the Wayland default, this full-screen surface
 * silently intercepts pointer motion at the screen edges, which broke lan-mouse's own
 * layer-shell edge-capture surface (it stopped seeing the cursor reach the edge to hand off
 * to the Mac). */
static void set_no_input(void)
{
    struct wl_region *region = wl_compositor_create_region(compositor);
    wl_surface_set_input_region(surface, region);
    wl_region_destroy(region);
}

static void layer_configure(void *data, struct zwlr_layer_surface_v1 *ls,
                            uint32_t serial, uint32_t w, uint32_t h)
{
    (void)data;
    zwlr_layer_surface_v1_ack_configure(ls, serial);
    if (w > 0) surf_w = (int32_t)w;
    if (h > 0) surf_h = (int32_t)h;
    if (egl_window) {
        wl_egl_window_resize(egl_window, surf_w, surf_h, 0, 0);
        glViewport(0, 0, surf_w, surf_h);
        rt_resize();
    }
    set_opaque();
    set_no_input();
    configured = true;
}
static void layer_closed(void *data, struct zwlr_layer_surface_v1 *ls)
{
    (void)data; (void)ls;
    running = 0;
}
static const struct zwlr_layer_surface_v1_listener layer_listener = { layer_configure, layer_closed };

/* frame callback ---------------------------------------------------------- */
static void frame_done(void *data, struct wl_callback *cb, uint32_t t)
{
    (void)data; (void)t;
    wl_callback_destroy(cb);
    frame_inflight = false;
}
static const struct wl_callback_listener frame_listener = { frame_done };

/* ------------------------------------------------------------------ audio */
/* Iterative radix-2 complex FFT, in-place. n must be a power of two. */
static void fft(float *re, float *im, int n)
{
    for (int i = 1, j = 0; i < n; i++) {                    /* bit-reversal permutation */
        int bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) {
            float tr = re[i]; re[i] = re[j]; re[j] = tr;
            float ti = im[i]; im[i] = im[j]; im[j] = ti;
        }
    }
    for (int len = 2; len <= n; len <<= 1) {
        float ang = -2.0f * (float)M_PI / (float)len;
        float wr = cosf(ang), wi = sinf(ang);
        for (int i = 0; i < n; i += len) {
            float cr = 1.0f, ci = 0.0f;
            for (int k = 0; k < len / 2; k++) {
                int a = i + k, b = i + k + len / 2;
                float xr = re[b] * cr - im[b] * ci;
                float xi = re[b] * ci + im[b] * cr;
                re[b] = re[a] - xr; im[b] = im[a] - xi;
                re[a] += xr;        im[a] += xi;
                float ncr = cr * wr - ci * wi;
                ci = cr * wi + ci * wr;
                cr = ncr;
            }
        }
    }
}

static float band_energy(const float *re, const float *im, int lo, int hi)
{
    float s = 0.0f;
    for (int i = lo; i < hi; i++) s += sqrtf(re[i] * re[i] + im[i] * im[i]);
    return s / (float)(hi - lo);
}

static void *audio_thread(void *arg)
{
    const char *cmd = (const char *)arg;
    int16_t hopbuf[AUDIO_HOP];
    float window[FFT_N];                      /* sliding sample window */
    float re[FFT_N], im[FFT_N], hann[FFT_N];
    for (int i = 0; i < FFT_N; i++)
        hann[i] = 0.5f - 0.5f * cosf(2.0f * (float)M_PI * (float)i / (float)(FFT_N - 1));
    memset(window, 0, sizeof window);

    /* Per-band adaptive gain (slow-decaying peak trackers) + attack/decay smoothing state. */
    float pk_l = 1e-4f, pk_b = 1e-4f, pk_m = 1e-4f, pk_t = 1e-4f;
    float sm_l = 0, sm_b = 0, sm_m = 0, sm_t = 0, bass_avg = 0, beat_env = 0;

    while (running) {
        FILE *f = popen(cmd, "r");
        if (!f) { sleep(3); continue; }
        while (running) {
            size_t got = fread(hopbuf, sizeof(int16_t), AUDIO_HOP, f);
            if (got < AUDIO_HOP) break;                       /* stream died - respawn */
            memmove(window, window + AUDIO_HOP, (FFT_N - AUDIO_HOP) * sizeof(float));
            for (int i = 0; i < AUDIO_HOP; i++)
                window[FFT_N - AUDIO_HOP + i] = (float)hopbuf[i] / 32768.0f;

            float rms = 0.0f;
            for (int i = 0; i < FFT_N; i++) {
                re[i] = window[i] * hann[i];
                im[i] = 0.0f;
                rms += window[i] * window[i];
            }
            rms = sqrtf(rms / (float)FFT_N);
            fft(re, im, FFT_N);

            /* bin width = 44100/1024 ~ 43 Hz: bass 43-260, mid 260-2000, treble 2000-8000 */
            float b = band_energy(re, im, 1, 6);
            float m = band_energy(re, im, 6, 46);
            float t = band_energy(re, im, 46, 186);

            /* AGC: normalize each band by its own slowly-decaying peak so quiet and loud sources
             * both use the full 0..1 range. */
            pk_l = fmaxf(pk_l * 0.9995f, rms); pk_b = fmaxf(pk_b * 0.9995f, b);
            pk_m = fmaxf(pk_m * 0.9995f, m);   pk_t = fmaxf(pk_t * 0.9995f, t);
            float nl = rms / fmaxf(pk_l, 1e-4f), nb = b / fmaxf(pk_b, 1e-4f);
            float nm = m / fmaxf(pk_m, 1e-4f),  nt = t / fmaxf(pk_t, 1e-4f);

            /* fast attack, slow decay */
            sm_l += (nl - sm_l) * (nl > sm_l ? 0.5f : 0.08f);
            sm_b += (nb - sm_b) * (nb > sm_b ? 0.5f : 0.08f);
            sm_m += (nm - sm_m) * (nm > sm_m ? 0.5f : 0.08f);
            sm_t += (nt - sm_t) * (nt > sm_t ? 0.5f : 0.08f);

            /* beat: positive bass flux against a slow-moving average, held in a decaying envelope */
            float flux = fmaxf(0.0f, nb - bass_avg);
            bass_avg += (nb - bass_avg) * 0.03f;
            beat_env = fmaxf(beat_env * 0.85f, fminf(1.0f, flux * 4.0f));

            pthread_mutex_lock(&g_audio.mu);
            g_audio.level = sm_l; g_audio.bass = sm_b; g_audio.mid = sm_m;
            g_audio.treble = sm_t; g_audio.beat = beat_env;
            pthread_mutex_unlock(&g_audio.mu);
        }
        pclose(f);
        /* silence the uniforms while the stream is down, then retry */
        pthread_mutex_lock(&g_audio.mu);
        g_audio.level = g_audio.bass = g_audio.mid = g_audio.treble = g_audio.beat = 0.0f;
        pthread_mutex_unlock(&g_audio.mu);
        for (int i = 0; i < 30 && running; i++) usleep(100 * 1000);
    }
    return NULL;
}

/* ------------------------------------------------------------------ mouse */
/* One short-lived Hyprland IPC request. Returns bytes read, or -1. */
static ssize_t hypr_query(const char *path, const char *cmd, char *buf, size_t bufsz)
{
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    struct sockaddr_un sa = { .sun_family = AF_UNIX };
    memcpy(sa.sun_path, path, strlen(path) + 1);
    ssize_t n = -1;
    if (connect(fd, (struct sockaddr *)&sa, sizeof sa) == 0) {
        size_t len = strlen(cmd);
        if (write(fd, cmd, len) == (ssize_t)len) {
            n = read(fd, buf, bufsz - 1);
            if (n > 0) buf[n] = 0;
        }
    }
    close(fd);
    return n;
}

/* Ask the compositor where the bar actually is, so the bead can nestle into it instead of us
 * hardcoding a guess. Parses one line of `hyprctl layers`:
 *     Layer 57461c0a4900: xywh: 240 8 1440 34, a: 1, namespace: waybar, pid: 1042004
 * Returns false if there is no compositor, no bar, or the format has moved - the caller then falls
 * back to the fixed defaults, so a missing bar is a cosmetic miss and never a failure to start. */
static bool bar_geometry(const char *ns, int *bx, int *by, int *bw, int *bh)
{
    const char *sig = getenv("HYPRLAND_INSTANCE_SIGNATURE");
    const char *rt  = getenv("XDG_RUNTIME_DIR");
    if (!sig || !rt) return false;
    char path[sizeof ((struct sockaddr_un *)0)->sun_path];
    if ((size_t)snprintf(path, sizeof path, "%s/hypr/%s/.socket.sock", rt, sig) >= sizeof path)
        return false;

    static char buf[64 * 1024];
    if (hypr_query(path, "layers", buf, sizeof buf) <= 0) return false;

    char want[64];
    if ((size_t)snprintf(want, sizeof want, "namespace: %s,", ns) >= sizeof want) return false;

    for (char *line = strtok(buf, "\n"); line; line = strtok(NULL, "\n")) {
        const char *xy = strstr(line, "xywh:");
        if (!xy || !strstr(line, want)) continue;
        int x, y, w, h;
        if (sscanf(xy + 5, "%d %d %d %d", &x, &y, &w, &h) == 4 && w > 0 && h > 0) {
            *bx = x; *by = y; *bw = w; *bh = h;
            return true;
        }
    }
    return false;
}

/* Poll Hyprland's IPC socket for "cursorpos". One short-lived connection per poll (hyprctl does the
 * same); 10 Hz is plenty - the main loop smooths toward the target. */
static void *mouse_thread(void *arg)
{
    (void)arg;
    const char *sig = getenv("HYPRLAND_INSTANCE_SIGNATURE");
    const char *rt  = getenv("XDG_RUNTIME_DIR");
    if (!sig || !rt) return NULL;
    char path[sizeof ((struct sockaddr_un *)0)->sun_path];   /* fits sun_path by construction */
    if ((size_t)snprintf(path, sizeof path, "%s/hypr/%s/.socket.sock", rt, sig) >= sizeof path)
        return NULL;

    unsigned tick = 0;
    while (running) {
        char buf[512];
        if (hypr_query(path, "cursorpos", buf, sizeof buf) > 0) {
            int cx, cy;
            if (sscanf(buf, "%d, %d", &cx, &cy) == 2) {
                int W = surf_w > 0 ? surf_w : 1920, H = surf_h > 0 ? surf_h : 1080;
                float nx = (float)cx / (float)W, ny = 1.0f - (float)cy / (float)H;
                pthread_mutex_lock(&g_mouse.mu);
                if (!g_mouse.valid || fabsf(nx - g_mouse.x) > 0.0015f
                                   || fabsf(ny - g_mouse.y) > 0.0015f)
                    g_mouse.last_move = now_s();
                g_mouse.x = nx; g_mouse.y = ny;
                g_mouse.at_edge = (cx <= 1 || cx >= W - 2 || cy <= 1 || cy >= H - 2);
                g_mouse.valid = true;
                pthread_mutex_unlock(&g_mouse.mu);
            }
        }
        /* The full-screen wallpaper background is retired: the familiar now lives only inside the
         * blurred chat overlay (companion mode) or as the small clockbar bead. Keep presence at 0
         * so the main BACKGROUND surface stays hidden at all times. */
        if ((tick++ & 1u) == 0u) {
            pthread_mutex_lock(&g_presence.mu);
            g_presence.target = 0.0f;
            pthread_mutex_unlock(&g_presence.mu);
        }
        usleep(MOUSE_POLL_MS * 1000);
    }
    return NULL;
}

/* ---------------------------------------------------------------- emotion */
static float clamp01(float v)
{
    return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v);
}

/* ---------------------------------------------------- boltrig phenotype */
/* Boltrig's emotion relay publishes {"v": 1, "ts": <epoch>, "phenotype": {...}} with nine 0..1
 * scalars. The familiar only ever needs "key": number pairs out of it, so it is read with a tiny
 * hand-rolled scanner instead of a JSON library. */
static void pheno_path(char *buf, size_t n)
{
    const char *rt = getenv("XDG_RUNTIME_DIR");
    if (rt) snprintf(buf, n, "%s/boltrig-phenotype.json", rt);
    else    snprintf(buf, n, "/tmp/boltrig-phenotype.json");
}

static void voice_level_path(char *buf, size_t n)
{
    const char *rt = getenv("XDG_RUNTIME_DIR");
    if (rt) snprintf(buf, n, "%s/boltrig-rt/familiar-voice-level.json", rt);
    else    snprintf(buf, n, "/tmp/boltrig-rt/familiar-voice-level.json");
}

/* ---------------------------------------------------------------------------
 * GENOTYPE (familiar/GENOTYPE.md). The phenotype says how the being FEELS and is
 * republished ~2 Hz; the genotype says what it IS and changes only when someone
 * re-authors it. So it lives in ~/.config/familiar/genotype.json beside the shader,
 * not in $XDG_RUNTIME_DIR, and is read on start and on SIGUSR1 with the shader.
 *
 * ABSENT IS A CIRCLE. The defaults below are the identity case: gShape 0 makes
 * shapeDist() return length(), which is byte-for-byte the body this surface drew
 * before the genotype existed. A missing, truncated or garbage file therefore
 * degrades to the old familiar rather than to a black screen (WL-2), and there is
 * no path where a bad genotype can fail to render.
 * ------------------------------------------------------------------------- */
static float g_gene[GENOTYPE_SLOTS];

static void genotype_path(char *buf, size_t n)
{
    const char *ov = getenv("FAMILIAR_GENOTYPE");
    if (ov && *ov) { snprintf(buf, n, "%s", ov); return; }
    const char *home = getenv("HOME");
    snprintf(buf, n, "%s/.config/familiar/genotype.json", home ? home : ".");
}

/* One flat "key": value scan. No JSON library and none wanted: the file is a flat
 * map of 15 numbers, and a parser that cannot fail is worth more here than one that
 * validates. A key that is absent keeps its default, which is why a partial file is
 * a legal file - write only the three keys you care about. */
static void genotype_key(const char *buf, const char *key, float *out)
{
    char pat[64];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = strstr(buf, pat);
    if (!p) return;
    p = strchr(p + strlen(pat), ':');
    if (!p) return;
    char *end = NULL;
    double v = strtod(p + 1, &end);
    if (end && end != p + 1) *out = (float)v;
}

static void genotype_load(void)
{
    /* Reset to the defaults FIRST, every time. This runs on SIGUSR1 as well as at start,
     * and without the reset a reload could only ever add: delete a key from the file and
     * the old value would quietly survive, so the running shape would stop matching the
     * file that claims to describe it. Reloading is now idempotent - the file is the whole
     * truth about the body, not a diff against whatever was loaded last. */
    memcpy(g_gene, GENOTYPE_DEFAULTS, sizeof(g_gene));

    char path[512];
    genotype_path(path, sizeof(path));
    FILE *f = fopen(path, "rb");
    if (!f) return;                     /* no file: keep the circle defaults */
    char buf[4096];
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    buf[n] = 0;
    for (int i = 0; i < GENOTYPE_SLOTS; i++)
        if (GENOTYPE_KEYS[i]) genotype_key(buf, GENOTYPE_KEYS[i], &g_gene[i]);
    fprintf(stderr, "familiar-bg: genotype loaded from %s (shape=%.0f focal=%.2f superM=%.0f)\n",
            path, g_gene[0], g_gene[2], g_gene[5]);
}

static void geometry_path(char *buf, size_t n)
{
    /* familiar-chat explicitly publishes to this world-writable /tmp path so it works even
       when the chat client and familiar-bg are in different systemd user sessions. */
    snprintf(buf, n, "%s", GEOM_PATH_DEFAULT);
}

static void voice_level_parse(const char *buf, float *level, float *beat)
{
    const char *p = strstr(buf, "\"level\"");
    if (p) *level = (float)strtod(p + 8, NULL);
    p = strstr(buf, "\"beat\"");
    if (p) *beat = (float)strtod(p + 7, NULL);
}

static void read_voice_level(void)
{
    char path[256];
    voice_level_path(path, sizeof(path));
    struct stat st;
    if (stat(path, &st) != 0) {
        pthread_mutex_lock(&g_voice.mu);
        g_voice.level = g_voice.beat = 0.0f;
        pthread_mutex_unlock(&g_voice.mu);
        return;
    }
    pthread_mutex_lock(&g_voice.mu);
    if (st.st_mtime == g_voice.mtime) {
        pthread_mutex_unlock(&g_voice.mu);
        return;
    }
    g_voice.mtime = st.st_mtime;
    pthread_mutex_unlock(&g_voice.mu);

    FILE *f = fopen(path, "r");
    if (!f) return;
    char buf[512];
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    if (n == 0) return;
    buf[n] = '\0';
    float level = 0.0f, beat = 0.0f;
    voice_level_parse(buf, &level, &beat);
    pthread_mutex_lock(&g_voice.mu);
    g_voice.level = clamp01(level);
    g_voice.beat = clamp01(beat);
    pthread_mutex_unlock(&g_voice.mu);
}

/* -------------------------------------------------- chat surface geometry */
static bool geometry_parse_mode(const char *buf, OverlayMode *out)
{
    const char *p = strstr(buf, "\"mode\"");
    if (!p) return false;
    p = strchr(p + 6, '"');
    if (!p) return false;
    p++;
    const char *e = strchr(p, '"');
    if (!e) return false;
    size_t len = (size_t)(e - p);
    if (len == 6 && strncmp(p, "portal", 6) == 0) *out = OM_PORTAL;
    else if (len == 6 && strncmp(p, "window", 6) == 0) *out = OM_WINDOW;
    else *out = OM_IMMERSIVE;
    return true;
}

static int32_t geometry_parse_int(const char *buf, const char *key)
{
    const char *p = strstr(buf, key);
    if (!p) return 0;
    p = strchr(p + strlen(key), ':');
    if (!p) return 0;
    return (int32_t)strtol(p + 1, NULL, 10);
}

static void read_geometry(void)
{
    char path[256];
    geometry_path(path, sizeof(path));
    struct stat st;
    if (stat(path, &st) != 0) return;
    if (st.st_mtime == g_geom.mtime) return;

    FILE *f = fopen(path, "r");
    if (!f) return;
    char buf[1024];
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    if (n == 0) return;
    buf[n] = '\0';

    OverlayMode m = OM_IMMERSIVE;
    geometry_parse_mode(buf, &m);
    int32_t x = geometry_parse_int(buf, "\"x\"");
    int32_t y = geometry_parse_int(buf, "\"y\"");
    int32_t w = geometry_parse_int(buf, "\"w\"");
    int32_t h = geometry_parse_int(buf, "\"h\"");

    g_geom.mtime = st.st_mtime;
    if (m != g_geom.mode || x != g_geom.x || y != g_geom.y || w != g_geom.w || h != g_geom.h) {
        g_geom.mode = m; g_geom.x = x; g_geom.y = y; g_geom.w = w; g_geom.h = h;
        g_geom.dirty = true;
    }
}

/* Scan buf for "key": number pairs. Non-numeric values (the nested "phenotype" object, strings)
 * are skipped harmlessly; unknown numeric keys ("v", "ts") are ignored. Returns true if at least
 * one of the nine scalars was found; missing scalars keep neutral defaults. */
static bool pheno_parse(const char *buf, Phenotype *out)
{
    static const struct { const char *key; size_t off; } FIELDS[] = {
        { "fatigue",    offsetof(Phenotype, fatigue) },
        { "valence",    offsetof(Phenotype, valence) },
        { "arousal",    offsetof(Phenotype, arousal) },
        { "irritation", offsetof(Phenotype, irritation) },
        { "attention",  offsetof(Phenotype, attention) },
        { "social",     offsetof(Phenotype, social) },
        { "buoyancy",   offsetof(Phenotype, buoyancy) },
        { "luminosity", offsetof(Phenotype, luminosity) },
        { "tension",    offsetof(Phenotype, tension) },
    };
    *out = (Phenotype){ .valence = 0.5f, .arousal = 0.35f, .attention = 0.5f,
                        .buoyancy = 0.5f, .luminosity = 0.5f };
    int found = 0;
    const char *p = buf;
    while ((p = strchr(p, '"')) != NULL) {
        const char *key = ++p;
        const char *end = strchr(key, '"');
        if (!end) break;
        size_t klen = (size_t)(end - key);
        p = end + 1;
        while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
        if (*p != ':') continue;
        p++;
        while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
        char *num_end = NULL;
        double v = strtod(p, &num_end);
        if (num_end == p) continue;                       /* value is not a number - skip */
        p = num_end;
        for (size_t i = 0; i < sizeof FIELDS / sizeof FIELDS[0]; i++) {
            if (klen == strlen(FIELDS[i].key) && strncmp(key, FIELDS[i].key, klen) == 0) {
                *(float *)((char *)out + FIELDS[i].off) = clamp01((float)v);
                found++;
                break;
            }
        }
    }
    return found > 0;
}

static bool pheno_read(const char *path, Phenotype *out)
{
    FILE *f = fopen(path, "r");
    if (!f) return false;
    char buf[PHENO_MAX_BYTES];
    size_t n = fread(buf, 1, sizeof buf - 1, f);
    fclose(f);
    buf[n] = 0;
    return pheno_parse(buf, out);
}

/* Re-resolve the phenotype TARGET from whichever source currently wins:
 *   1. fresh boltrig phenotype (mtime within PHENO_FRESH_S) - the creature's real mood
 *   2. resting baseline (PHENO_IDLE) when nothing fresh is being published
 * The file is stat()ed every poll (~4 Hz) but re-read only when its mtime moves. The shader owns the
 * entire look; the host just hands it the nine smoothed scalars. FAMILIAR_PHENO=0 forces the idle
 * baseline (useful for a demo/screensaver mode with no boltrig running). */
static void pheno_poll(Phenotype *target)
{
    static int pheno_enabled = -1;
    if (pheno_enabled < 0) {
        const char *pe = getenv("FAMILIAR_PHENO");
        pheno_enabled = !(pe && strcmp(pe, "0") == 0);
    }

    static struct timespec ph_stamp = { -1, 0 };
    static bool ph_ok = false;
    static Phenotype ph;
    char path[256];
    struct stat st;
    pheno_path(path, sizeof path);
    if (pheno_enabled && stat(path, &st) == 0
        && difftime(time(NULL), st.st_mtime) <= PHENO_FRESH_S) {
        if (st.st_mtim.tv_sec != ph_stamp.tv_sec || st.st_mtim.tv_nsec != ph_stamp.tv_nsec) {
            ph_stamp = st.st_mtim;
            ph_ok = pheno_read(path, &ph);
        }
        if (ph_ok) {
            *target = ph;
            return;
        }
    }

    /* baseline: a calm, resting creature */
    *target = PHENO_IDLE;
}

/* ------------------------------------------- voluntary expression (WL-3) */
/* familiar.express (a governed boltrig verb) writes {"v":1,"gesture":"<name>","intensity":f,"ttl_s":f}
 * to $XDG_RUNTIME_DIR/boltrig-express.json. Unlike the sustained autonomic phenotype, a gesture is a
 * DELIBERATE transient act: the surface fires it once when the file's mtime moves, then lets it decay
 * over ttl_s and layers it over the mood. The gesture is a closed enum, so we map the name to an id the
 * shader branches on (order matches the adapter's GESTURES tuple; 0 = none). */
enum { GES_NONE = 0, GES_LOOK, GES_PULSE, GES_FLINCH, GES_CELEBRATE,
       GES_GREET, GES_NOD, GES_RECOIL, GES_PREEN };

static int gesture_id(const char *name, size_t len)
{
    static const char *NAMES[] = { "look", "pulse", "flinch", "celebrate",
                                   "greet", "nod", "recoil", "preen" };
    for (int i = 0; i < (int)(sizeof NAMES / sizeof NAMES[0]); i++)
        if (strlen(NAMES[i]) == len && strncmp(name, NAMES[i], len) == 0)
            return i + 1;                 /* GES_LOOK == 1 */
    return GES_NONE;
}

/* Poll the express channel. Returns 1 and fills the outs only when a NEW gesture has appeared
 * (mtime moved and the file is fresh); otherwise 0 and the caller keeps decaying the current one. */
static int express_poll(int *out_id, float *out_intensity, float *out_ttl)
{
    static int enabled = -1;
    if (enabled < 0) {
        const char *e = getenv("FAMILIAR_EXPRESS");
        enabled = !(e && strcmp(e, "0") == 0);
    }
    if (!enabled) return 0;

    static struct timespec stamp = { -1, 0 };
    const char *rt = getenv("XDG_RUNTIME_DIR");
    char path[256];
    if (rt) snprintf(path, sizeof path, "%s/boltrig-express.json", rt);
    else    snprintf(path, sizeof path, "/tmp/boltrig-express.json");

    struct stat st;
    if (stat(path, &st) != 0) return 0;
    if (difftime(time(NULL), st.st_mtime) > PHENO_FRESH_S) return 0;    /* stale = no live producer */
    if (st.st_mtim.tv_sec == stamp.tv_sec && st.st_mtim.tv_nsec == stamp.tv_nsec) return 0;  /* seen */
    stamp = st.st_mtim;

    FILE *f = fopen(path, "r");
    if (!f) return 0;
    char buf[PHENO_MAX_BYTES];
    size_t n = fread(buf, 1, sizeof buf - 1, f);
    fclose(f);
    buf[n] = 0;

    /* find "gesture" : "<name>" */
    int id = GES_NONE;
    const char *g = strstr(buf, "\"gesture\"");
    if (g) {
        const char *q = strchr(g + 9, '"');           /* opening quote of the value */
        if (q) {
            const char *e = strchr(++q, '"');
            if (e) id = gesture_id(q, (size_t)(e - q));
        }
    }
    if (id == GES_NONE) return 0;

    float intensity = 0.7f, ttl = 2.0f;
    const char *ip = strstr(buf, "\"intensity\"");
    if (ip) { const char *c = strchr(ip, ':'); if (c) intensity = strtof(c + 1, NULL); }
    const char *tp = strstr(buf, "\"ttl_s\"");
    if (tp) { const char *c = strchr(tp, ':'); if (c) ttl = strtof(c + 1, NULL); }

    *out_id = id;
    *out_intensity = clamp01(intensity);
    *out_ttl = ttl < 0.0f ? 0.0f : (ttl > 15.0f ? 15.0f : ttl);
    return 1;
}

/* ------------------------------------------------------------ time of day */
static float day_warmth(void)
{
    time_t t = time(NULL);
    struct tm tm;
    localtime_r(&t, &tm);
    float h = (float)tm.tm_hour + (float)tm.tm_min / 60.0f;
    /* rise 6..10, plateau, fall 18..22 */
    float up   = h <= 6.0f ? 0.0f : h >= 10.0f ? 1.0f : (h - 6.0f) / 4.0f;
    float down = h <= 18.0f ? 1.0f : h >= 22.0f ? 0.0f : (22.0f - h) / 4.0f;
    float d = up * down;
    return d * d * (3.0f - 2.0f * d);                     /* smoothstep the ramps */
}

/* -------------------------------------------------------------------- GL */
static const char *VERT_SRC =
    "#version 300 es\n"
    "void main() {\n"
    "  vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));\n"
    "  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);\n"
    "}\n";

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
        fprintf(stderr, "familiar-bg: shader compile failed:\n%s\n", log);
        glDeleteShader(s);
        return 0;
    }
    return s;
}

static char *read_file(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n <= 0 || n > 1 << 20) { fclose(f); return NULL; }
    char *buf = malloc((size_t)n + 1);
    if (buf && fread(buf, 1, (size_t)n, f) == (size_t)n) buf[n] = 0;
    else { free(buf); buf = NULL; }
    fclose(f);
    return buf;
}

static void shader_path(char *buf, size_t n)
{
    const char *p = getenv("FAMILIAR_SHADER");
    if (p) { snprintf(buf, n, "%s", p); return; }
    const char *home = getenv("HOME");
    snprintf(buf, n, "%s/.config/familiar/familiar.frag", home ? home : ".");
}

/* Build (or rebuild) the program from the on-disk fragment shader. Keeps the previous program if the
 * new source fails, so a bad live edit never blanks the desktop. Returns true on success. */
static bool load_program(void)
{
    char path[512];
    shader_path(path, sizeof path);
    char *frag_src = read_file(path);
    if (!frag_src) {
        fprintf(stderr, "familiar-bg: cannot read shader %s\n", path);
        return false;
    }
    GLuint vs = compile(GL_VERTEX_SHADER, VERT_SRC);
    GLuint fs = compile(GL_FRAGMENT_SHADER, frag_src);
    free(frag_src);
    if (!vs || !fs) { if (vs) glDeleteShader(vs); if (fs) glDeleteShader(fs); return false; }

    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    glDeleteShader(vs);
    glDeleteShader(fs);
    GLint ok = 0;
    glGetProgramiv(prog, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[4096];
        glGetProgramInfoLog(prog, sizeof log, NULL, log);
        fprintf(stderr, "familiar-bg: program link failed:\n%s\n", log);
        glDeleteProgram(prog);
        return false;
    }
    if (program) glDeleteProgram(program);
    program = prog;
    glUseProgram(program);
    /* Re-read the genotype here rather than only at startup: load_program() is the
       SIGUSR1 hot-reload path too, so editing genotype.json and sending USR1 reshapes
       the body live - the authoring loop the editor needs. */
    genotype_load();
    uni.uGene       = glGetUniformLocation(program, "uGene");
    uni.iTime       = glGetUniformLocation(program, "iTime");
    uni.iResolution = glGetUniformLocation(program, "iResolution");
    uni.uAudio      = glGetUniformLocation(program, "uAudio");
    uni.uBeat       = glGetUniformLocation(program, "uBeat");
    uni.uMouse      = glGetUniformLocation(program, "uMouse");
    uni.uDay        = glGetUniformLocation(program, "uDay");
    uni.uValence    = glGetUniformLocation(program, "uValence");
    uni.uArousal    = glGetUniformLocation(program, "uArousal");
    uni.uIrritation = glGetUniformLocation(program, "uIrritation");
    uni.uFatigue    = glGetUniformLocation(program, "uFatigue");
    uni.uAttention  = glGetUniformLocation(program, "uAttention");
    uni.uSocial     = glGetUniformLocation(program, "uSocial");
    uni.uBuoyancy   = glGetUniformLocation(program, "uBuoyancy");
    uni.uLuminosity = glGetUniformLocation(program, "uLuminosity");
    uni.uTension    = glGetUniformLocation(program, "uTension");
    uni.uGesture    = glGetUniformLocation(program, "uGesture");
    uni.uGestureAmt = glGetUniformLocation(program, "uGestureAmt");
    uni.uPresence   = glGetUniformLocation(program, "uPresence");
    uni.uFill       = glGetUniformLocation(program, "uFill");
    uni.uCentreDock = glGetUniformLocation(program, "uCentreDock");
    uni.uWorldRes   = glGetUniformLocation(program, "uWorldRes");
    uni.uOrigin     = glGetUniformLocation(program, "uOrigin");
    uni.uPxScale    = glGetUniformLocation(program, "uPxScale");
    uni.uScaleDock  = glGetUniformLocation(program, "uScaleDock");
    uni.uFitScale   = glGetUniformLocation(program, "uFitScale");
    uni.uGaze       = glGetUniformLocation(program, "uGaze");
    uni.uHover      = glGetUniformLocation(program, "uHover");
    uni.uCompanion  = glGetUniformLocation(program, "uCompanion");
    uni.uAperture   = glGetUniformLocation(program, "uAperture");
    fprintf(stderr, "familiar-bg: shader loaded from %s\n", path);
    return true;
}

/* ------------------------------------------------------------------- main */
static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

int main(void)
{
    struct sigaction sa = { .sa_handler = on_signal };
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGUSR1, &sa, NULL);
    sigaction(SIGUSR2, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);

    int fps = DEFAULT_FPS;
    const char *fps_env = getenv("FAMILIAR_FPS");
    if (fps_env) {
        int v = atoi(fps_env);
        if (v >= 10 && v <= 120) fps = v;
    }
    const double period = 1.0 / (double)fps;

    const char *scale_env = getenv("FAMILIAR_SCALE");
    if (scale_env) {
        float v = strtof(scale_env, NULL);
        if (v >= MIN_SCALE && v <= MAX_SCALE) render_scale = v;
    }

    dpy = wl_display_connect(NULL);
    if (!dpy) { fprintf(stderr, "familiar-bg: no wayland display\n"); return 1; }
    struct wl_registry *reg = wl_display_get_registry(dpy);
    wl_registry_add_listener(reg, &registry_listener, NULL);
    wl_display_roundtrip(dpy);
    if (!compositor || !layer_shell) {
        fprintf(stderr, "familiar-bg: missing wl_compositor or zwlr_layer_shell_v1\n");
        return 1;
    }
    /* The summon click (see THE SUMMON above): a pointer purely for the bead's docked click target.
     * The wallpaper keeps an empty input region, so this seat only ever sees the bead's events. */
    if (seat) {
        pointer = wl_seat_get_pointer(seat);
        if (pointer) wl_pointer_add_listener(pointer, &pointer_listener, NULL);
    }

    surface = wl_compositor_create_surface(compositor);
    layer_surface = zwlr_layer_shell_v1_get_layer_surface(
        layer_shell, surface, NULL, ZWLR_LAYER_SHELL_V1_LAYER_BACKGROUND, "familiar");
    zwlr_layer_surface_v1_add_listener(layer_surface, &layer_listener, NULL);
    zwlr_layer_surface_v1_set_anchor(layer_surface,
        ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP | ZWLR_LAYER_SURFACE_V1_ANCHOR_BOTTOM |
        ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT | ZWLR_LAYER_SURFACE_V1_ANCHOR_RIGHT);
    zwlr_layer_surface_v1_set_exclusive_zone(layer_surface, -1);
    zwlr_layer_surface_v1_set_keyboard_interactivity(layer_surface, 0);
    wl_surface_commit(surface);
    while (!configured && running && wl_display_dispatch(dpy) != -1) { }
    if (!running) return 0;

    /* The bead: born on the OVERLAY layer, anchored top-left, nestled into the LEFT end of the bar.
     * We ask the compositor where the bar is rather than hardcoding it, so it survives a resized bar,
     * a different monitor or a changed margin; the fixed numbers are only the no-compositor fallback.
     * All three are still env-overridable to nudge it without a rebuild. */
    int bead_px = 36, bead_x = 244, bead_y = 10;
    {   int bx, by, bw, bh;
        if (bar_geometry(getenv("FAMILIAR_BAR_NS") ? getenv("FAMILIAR_BAR_NS") : "waybar",
                         &bx, &by, &bw, &bh)) {
            /* Deliberately NOT clamped to the bar height: the bar has no background of its own now,
             * so the being is free to be larger than it and hang below the text line. The real limit
             * is the porthole having to end above the strip where hyprbars draws window buttons. */
            if (bead_px > bh*2) bead_px = bh*2;
            bead_x = bx + BAR_INSET;                         /* in from the edge, not jammed against it */
            bead_y = by + (bh - bead_px)/2 + BAR_DROP;       /* centred, then nudged down */
        }
    }
    { const char *e;
      if ((e = getenv("FAMILIAR_BEAD_PX"))) { int v = atoi(e); if (v >= 8 && v <= 200) bead_px = v; }
      if ((e = getenv("FAMILIAR_BEAD_X")))  { int v = atoi(e); if (v >= 0) bead_x = v; }
      if ((e = getenv("FAMILIAR_BEAD_Y")))  { int v = atoi(e); if (v >= 0) bead_y = v; }
      if ((e = getenv("FAMILIAR_PRESENCE_TAU"))) {
          float v = (float)atof(e); if (v >= 0.05f && v <= 5.0f) presence_tau = v; }
      if ((e = getenv("FAMILIAR_PRESENCE_IN_TAU"))) {
          float v = (float)atof(e); if (v >= 0.05f && v <= 5.0f) presence_tau_in = v; } }
    /* The overlay surface is a PORTHOLE, not a sprite: it is a window onto the same world the
     * wallpaper draws, padded around the docked spot so the being can fly into it without being
     * clipped by its own frame. Everything outside the being is transparent, so the pad is invisible. */
    /* Keep the porthole SHORT. It used to reach 110 px below the dock so the being could fly through
     * an opaque bar without being clipped by its own frame - but the bar is transparent now, so the
     * wallpaper shows the flight directly and none of that height is needed. It also has to stay
     * clear of hyprbars, which draws each window's close/minimise/maximise buttons in the strip just
     * below the bar: an overlay surface lying over those buttons is at best pointless and at worst
     * eats the clicks. Anything of ours near the top-left has to end above them. */
    const int PORT_PAD = 48, PORT_DROP = 8;
    dock_x = bead_x; dock_y = bead_y; dock_px = bead_px;
    port_pad = PORT_PAD; port_drop = PORT_DROP;
    porthole_geometry(PG_DOCKED);
    bead_surface = wl_compositor_create_surface(compositor);
    bead_ls = zwlr_layer_shell_v1_get_layer_surface(
        layer_shell, bead_surface, NULL, ZWLR_LAYER_SHELL_V1_LAYER_OVERLAY, "familiar-bead");
    zwlr_layer_surface_v1_add_listener(bead_ls, &bead_listener, NULL);
    zwlr_layer_surface_v1_set_anchor(bead_ls,
        ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP | ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT);
    porthole_geometry(PG_DOCKED);       /* now that bead_ls exists, push size + margin */
    zwlr_layer_surface_v1_set_exclusive_zone(bead_ls, -1);
    zwlr_layer_surface_v1_set_keyboard_interactivity(bead_ls, 0);
    {   /* decorative: never take pointer input (the lan-mouse lesson) */
        struct wl_region *r = wl_compositor_create_region(compositor);
        wl_surface_set_input_region(bead_surface, r);
        wl_region_destroy(r);
    }
    wl_surface_commit(bead_surface);
    while (!bead_configured && running && wl_display_dispatch(dpy) != -1) { }

    /* EGL after the first configure so the window is born at the real size */
    egl_dpy = eglGetDisplay((EGLNativeDisplayType)dpy);
    if (egl_dpy == EGL_NO_DISPLAY || !eglInitialize(egl_dpy, NULL, NULL)) {
        fprintf(stderr, "familiar-bg: eglInitialize failed\n");
        return 1;
    }
    static const EGLint cfg_attrs[] = {
        EGL_SURFACE_TYPE, EGL_WINDOW_BIT,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8,
        EGL_NONE
    };
    EGLConfig cfg;
    EGLint ncfg = 0;
    eglBindAPI(EGL_OPENGL_ES_API);
    if (!eglChooseConfig(egl_dpy, cfg_attrs, &cfg, 1, &ncfg) || ncfg < 1) {
        fprintf(stderr, "familiar-bg: no EGL config\n");
        return 1;
    }
    static const EGLint ctx_attrs[] = { EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE };
    egl_ctx = eglCreateContext(egl_dpy, cfg, EGL_NO_CONTEXT, ctx_attrs);
    egl_window = wl_egl_window_create(surface, surf_w, surf_h);
    egl_surf = eglCreateWindowSurface(egl_dpy, cfg, (EGLNativeWindowType)egl_window, NULL);
    if (egl_ctx == EGL_NO_CONTEXT || egl_surf == EGL_NO_SURFACE ||
        !eglMakeCurrent(egl_dpy, egl_surf, egl_surf, egl_ctx)) {
        fprintf(stderr, "familiar-bg: EGL context/surface failed\n");
        return 1;
    }
    if (bead_surface) {
        bead_egl_window = wl_egl_window_create(bead_surface, bead_w, bead_h);
        if (bead_egl_window)
            bead_egl_surf = eglCreateWindowSurface(egl_dpy, cfg,
                                                   (EGLNativeWindowType)bead_egl_window, NULL);
        if (bead_egl_surf == EGL_NO_SURFACE)
            fprintf(stderr, "familiar-bg: no bead surface, docking will be invisible\n");
    }
    eglSwapInterval(egl_dpy, 0);              /* frame callbacks pace us, not the swapchain */
    glViewport(0, 0, surf_w, surf_h);
    rt_resize();
    fprintf(stderr, "familiar-bg: %dx%d @ %d fps, raymarch at %.0f%% (%dx%d)\n",
            surf_w, surf_h, fps, (double)render_scale * 100.0, rt_w, rt_h);

    if (!load_program()) return 1;

    /* threads */
    const char *audio_cmd = getenv("FAMILIAR_AUDIO_CMD");
    if (!audio_cmd || !*audio_cmd) audio_cmd = AUDIO_CMD_DEFAULT;
    pthread_t th_a, th_m;
    pthread_create(&th_a, NULL, audio_thread, (void *)audio_cmd);
    pthread_create(&th_m, NULL, mouse_thread, NULL);

    Phenotype cur = PHENO_IDLE, target = PHENO_IDLE;
    pheno_poll(&target);

    float presence = 0.0f;                    /* smoothed 0..1; see g_presence */
    float aperture = 0.0f;                    /* 0..1 black-hole aperture, follows companion_mode */

    /* voluntary gesture (WL-3): fired once when a new express record appears, then decays over ttl */
    int   ges_id = GES_NONE;
    float ges_intensity = 0.0f, ges_ttl = 0.0f;
    double ges_start = -1e9;

    float smx = 0.5f, smy = 0.5f;             /* smoothed mouse */
    float day = day_warmth();
    const double t0 = now_s();
    double next_frame = t0;
    double last = t0;
    uint64_t frame_no = 0;
    int wl_fd = wl_display_get_fd(dpy);

    while (running) {
        wl_display_flush(dpy);
        double now = now_s();
        int timeout;
        if (frame_inflight)               timeout = 100;
        else if (now >= next_frame)       timeout = 0;
        else                              timeout = (int)((next_frame - now) * 1000.0) + 1;

        struct pollfd pfd = { .fd = wl_fd, .events = POLLIN };
        int pr = poll(&pfd, 1, timeout);
        if (pr < 0 && errno != EINTR) break;
        if (pr > 0 && (pfd.revents & POLLIN)) {
            if (wl_display_dispatch(dpy) == -1) break;    /* compositor gone */
        }
        if (pfd.revents & (POLLERR | POLLHUP)) break;

        if (want_reload) {
            want_reload = 0;
            load_program();                                /* keeps old program on failure */
        }
        if (want_companion_toggle) {
            want_companion_toggle = 0;
            set_companion_mode(!companion_mode);
        }
        read_geometry();
        if (companion_mode && g_geom.mode != OM_IMMERSIVE && g_geom.dirty) {
            porthole_set_rect(g_geom.x, g_geom.y, g_geom.w, g_geom.h, true);
        }

        now = now_s();
        if (frame_inflight || now < next_frame || !configured) continue;

        double dt = now - last;
        if (dt > 0.1) dt = 0.1;
        last = now;

        /* inputs -> uniforms. The shader owns the whole look; the host smooths the nine phenotype
         * scalars toward their target (so mood morphs, never snaps) and hands the creature its raw
         * senses (audio, cursor, time of day) alongside. */
        if ((frame_no % STATE_POLL_FRAMES) == 0) pheno_poll(&target);
        if ((frame_no % STATE_POLL_FRAMES) == 0) {
            int nid; float ni, nt;
            if (express_poll(&nid, &ni, &nt)) {       /* a new deliberate gesture just arrived */
                ges_id = nid; ges_intensity = ni; ges_ttl = nt; ges_start = now;
            }
        }
        /* gesture envelope: rise fast, then decay to zero over ttl; clears when spent */
        float ges_amt = 0.0f;
        if (ges_id != GES_NONE && ges_ttl > 0.0f) {
            float u = (float)(now - ges_start) / ges_ttl;   /* 0..1 across the gesture's life */
            if (u >= 1.0f) { ges_id = GES_NONE; }
            else {
                float rise = 1.0f - expf(-u * 12.0f);       /* quick attack */
                ges_amt = ges_intensity * rise * (1.0f - u); /* then linear release */
            }
        }
        if ((frame_no % 60) == 0) day = day_warmth();
        /* Collapse out when working; a click on the dormant clockbar doughnut toggles the chat overlay. */
        pthread_mutex_lock(&g_presence.mu);
        float pres_target = g_presence.target;
        pthread_mutex_unlock(&g_presence.mu);
        /* Asymmetric migration: a slow, graceful fade-in; a quick exit when you need the space.
         * In the blurred-companion design the wallpaper is retired, so the target is always 0
         * (fully docked). The only migration now is between the small clockbar bead and the
         * large centred companion, driven by SIGUSR2 rather than workspace occupancy. */
        float pres_tau = (pres_target > presence) ? presence_tau_in : presence_tau;
        presence += (pres_target - presence)*(1.0f - expf(-(float)dt/pres_tau));
        /* Black-hole aperture: opens quickly, collapses almost instantly. */
        float apt_tau = companion_mode ? 0.25f : 0.03f;
        float apt_target = companion_mode ? 1.0f : 0.0f;
        aperture += (apt_target - aperture)*(1.0f - expf(-(float)dt/apt_tau));
        /* Wide only while it is actually moving. With the background retired this is only used
         * for the brief dock<->companion resize transition. */
        {   bool want_wide = (presence > 0.015f && presence < 0.985f);
            if (want_wide != port_wide && !companion_mode)
                porthole_geometry(want_wide ? PG_TRANSITION : PG_DOCKED); }
        /* The main wallpaper stays docked (hidden) at all times. */
        set_docked(true);
        /* The summon mist swells on hover (and ebbs fast if the pointer slips off mid-swell). */
        static float hover = 0.0f;
        hover += (((docked_mode && bead_hover) ? 1.0f : 0.0f) - hover)*(1.0f - expf(-(float)dt/0.11f));
        float k = 1.0f - expf(-(float)dt / EMO_TAU);
        cur.valence    += (target.valence    - cur.valence)    * k;
        cur.arousal    += (target.arousal    - cur.arousal)    * k;
        cur.irritation += (target.irritation - cur.irritation) * k;
        cur.fatigue    += (target.fatigue    - cur.fatigue)    * k;
        cur.attention  += (target.attention  - cur.attention)  * k;
        cur.social     += (target.social     - cur.social)     * k;
        cur.buoyancy   += (target.buoyancy   - cur.buoyancy)   * k;
        cur.luminosity += (target.luminosity - cur.luminosity) * k;
        cur.tension    += (target.tension    - cur.tension)    * k;

        pthread_mutex_lock(&g_mouse.mu);
        float tx = g_mouse.valid ? g_mouse.x : 0.5f;
        float ty = g_mouse.valid ? g_mouse.y : 0.5f;
        pthread_mutex_unlock(&g_mouse.mu);
        float mk = 1.0f - expf(-(float)dt * 22.0f);  /* was 8: a 125 ms lag read as sluggish */
        smx += (tx - smx) * mk;                    /* raw cursor; the shader gates gaze by uAttention */
        smy += (ty - smy) * mk;

        pthread_mutex_lock(&g_audio.mu);
        float a_l = g_audio.level, a_b = g_audio.bass, a_m = g_audio.mid,
              a_t = g_audio.treble, a_beat = g_audio.beat;
        pthread_mutex_unlock(&g_audio.mu);

        read_voice_level();
        pthread_mutex_lock(&g_voice.mu);
        float v_l = g_voice.level, v_beat = g_voice.beat;
        pthread_mutex_unlock(&g_voice.mu);
        a_l = fmaxf(a_l, v_l);
        a_beat = fmaxf(a_beat, v_beat);

        glUseProgram(program);
        glUniform1f(uni.iTime, (float)(now - t0));
        glUniform2f(uni.iResolution, (float)surf_w, (float)surf_h);
        glUniform4f(uni.uAudio, a_l, a_b, a_m, a_t);
        glUniform1f(uni.uBeat, a_beat);
        glUniform2f(uni.uMouse, smx, smy);
        glUniform1f(uni.uDay, day);
        glUniform1f(uni.uHover, hover);
        glUniform1f(uni.uCompanion,  companion_mode ? 1.0f : 0.0f);
        glUniform1f(uni.uAperture,   aperture);
        glUniform4fv(uni.uGene, GENOTYPE_VEC4S, g_gene);
        glUniform1f(uni.uValence,    cur.valence);
        glUniform1f(uni.uArousal,    cur.arousal);
        glUniform1f(uni.uIrritation, cur.irritation);
        glUniform1f(uni.uFatigue,    cur.fatigue);
        glUniform1f(uni.uAttention,  cur.attention);
        glUniform1f(uni.uSocial,     cur.social);
        glUniform1f(uni.uBuoyancy,   cur.buoyancy);
        glUniform1f(uni.uLuminosity, cur.luminosity);
        glUniform1f(uni.uTension,    cur.tension);
        glUniform1f(uni.uGesture,    (float)ges_id);
        glUniform1f(uni.uGestureAmt, ges_amt);
        glUniform1f(uni.uPresence,   presence);
        glUniform2f(uni.uCentreDock, dock_u, dock_v);
        {   /* Gaze: 1 = it is watching your cursor, 0 = it has looked away and lets its eye wander.
             * Smoothed on the host so the shader gets a continuous value and never snaps. */
            pthread_mutex_lock(&g_mouse.mu);
            bool live = g_mouse.valid && !g_mouse.at_edge
                     && (now_s() - g_mouse.last_move) < GAZE_IDLE_S;
            pthread_mutex_unlock(&g_mouse.mu);
            static float gaze = 0.0f;
            gaze += ((live ? 1.0f : 0.0f) - gaze)*(1.0f - expf(-(float)dt/0.7f));
            glUniform1f(uni.uGaze, gaze);
        }
        glUniform1f(uni.uScaleDock,  dock_scale);
        glUniform1f(uni.uFitScale,   fit_scale);
        glUniform2f(uni.uWorldRes,   (float)surf_w, (float)surf_h);
        glUniform2f(uni.uOrigin,     0.0f, 0.0f);
        glUniform1f(uni.uPxScale,    1.0f);
        glUniform1f(uni.uFill,       0.0f);

        /* Pass 1: the expensive raymarch, offscreen at render_scale. Pass 2: a linear upscale blit to
         * the display. The creature is all soft gradients, so the upscale is visually near-free while
         * the pixel count (and therefore the whole cost) drops by scale^2. */
        if (rt_fbo) {
            glBindFramebuffer(GL_FRAMEBUFFER, rt_fbo);
            glViewport(0, 0, rt_w, rt_h);
            glUniform2f(uni.iResolution, (float)rt_w, (float)rt_h);
            glUniform1f(uni.uPxScale, (float)surf_w/(float)(rt_w > 0 ? rt_w : 1));
            glDrawArrays(GL_TRIANGLES, 0, 3);
            glBindFramebuffer(GL_READ_FRAMEBUFFER, rt_fbo);
            glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
            glBlitFramebuffer(0, 0, rt_w, rt_h, 0, 0, surf_w, surf_h,
                              GL_COLOR_BUFFER_BIT, GL_LINEAR);
            glBindFramebuffer(GL_FRAMEBUFFER, 0);
            glViewport(0, 0, surf_w, surf_h);
        } else {
            glDrawArrays(GL_TRIANGLES, 0, 3);
        }

        /* Second pass: the SAME world, framed through the porthole on the bar. Identical uv mapping,
         * offset by the porthole's origin, so the being is one continuous object seen through two
         * windows rather than two drawings that have to be cross-faded into each other. Nothing to
         * show while it still owns the screen. */
        if (bead_wants_clear) {
            /* A resize just happened: blank the surface before any old buffer can present
             * squashed (the "2nd orb" flash). Runs even when the pass below is skipped. */
            bead_clear_now();
            bead_wants_clear = false;
        }
        if (bead_egl_surf != EGL_NO_SURFACE && companion_mode) {
            if (eglMakeCurrent(egl_dpy, bead_egl_surf, bead_egl_surf, egl_ctx)) {
                brt_resize(bead_w, bead_h);
                glUniform2f(uni.uOrigin,  (float)port_ox, (float)port_oy);
                glUniform1f(uni.uFill, 1.0f);
                if (brt_fbo) {
                    glBindFramebuffer(GL_FRAMEBUFFER, brt_fbo);
                    glViewport(0, 0, brt_w, brt_h);
                    glUniform2f(uni.iResolution, (float)brt_w, (float)brt_h);
                    glUniform1f(uni.uPxScale, (float)bead_w/(float)brt_w);
                    glDrawArrays(GL_TRIANGLES, 0, 3);
                    glBindFramebuffer(GL_READ_FRAMEBUFFER, brt_fbo);
                    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
                    glBlitFramebuffer(0, 0, brt_w, brt_h, 0, 0, bead_w, bead_h,
                                      GL_COLOR_BUFFER_BIT, GL_LINEAR);
                    glBindFramebuffer(GL_FRAMEBUFFER, 0);
                } else {
                    glViewport(0, 0, bead_w, bead_h);
                    glUniform2f(uni.iResolution, (float)bead_w, (float)bead_h);
                    glUniform1f(uni.uPxScale, 1.0f);
                    glDrawArrays(GL_TRIANGLES, 0, 3);
                }
                eglSwapBuffers(egl_dpy, bead_egl_surf);
            }
            eglMakeCurrent(egl_dpy, egl_surf, egl_surf, egl_ctx);
            glViewport(0, 0, surf_w, surf_h);
        }

        struct wl_callback *cb = wl_surface_frame(surface);
        wl_callback_add_listener(cb, &frame_listener, NULL);
        frame_inflight = true;
        eglSwapBuffers(egl_dpy, egl_surf);

        frame_no++;
        next_frame += period;
        if (next_frame < now) next_frame = now + period;  /* do not spiral after a stall */
    }

    eglMakeCurrent(egl_dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    if (egl_surf != EGL_NO_SURFACE) eglDestroySurface(egl_dpy, egl_surf);
    if (egl_ctx != EGL_NO_CONTEXT) eglDestroyContext(egl_dpy, egl_ctx);
    if (egl_window) wl_egl_window_destroy(egl_window);
    eglTerminate(egl_dpy);
    zwlr_layer_surface_v1_destroy(layer_surface);
    wl_surface_destroy(surface);
    wl_display_disconnect(dpy);
    return 0;
}
