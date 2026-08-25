#!/usr/bin/env python3
"""Play a .frame.mp4 -- one character, one scene, one file.

The whole point of the format is that playback needs nothing else: no clip
store, no network, no kernel. This server hands the browser the file and the
manifest, and the page navigates by SEEKING rather than by loading clips. Every
segment starts on a keyframe (the bake guarantees it), so a seek is instant and
the graph becomes currentTime arithmetic.

Deliberately standalone: this serves a GRAPH, where the clip-library players
2900 lines with its UI in Python string constants, and its double-buffered
VA/VB clip swapping cannot be verified without a browser. The seam to merge is
one line -- where it does `vid.src = '/media/' + file`, a .frame.mp4 keeps a
single src and sets `vid.currentTime = segment.start` instead.
"""
import os
import argparse, json, mimetypes, os, pathlib, re, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import frame_box

FRAME = None          # pathlib.Path to the .frame.mp4
MANIFEST = None
WAVS_DIR = None       # bundle voice/lines, for tier-1 speak-in-place audio
SPRITES_DIR = None    # bundle visual/sprites, for tier-1.5 viseme mouths
AMB_DIR = None        # bundle audio/, ambience + door SFX
VOICE_URL = os.environ.get("VOICE_URL", "http://127.0.0.1:8911")
VOICE_NAME = os.environ.get("VOICE_NAME", "montgomery")
MSE_DIR = None        # bundle visual/mse: shared init + per-edge fragments


PAGE_V2 = r"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>framegraph player v2 (MSE)</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#06070a;color:#e9e3d5;font:14px/1.5 system-ui,-apple-system,sans-serif;
     height:100dvh;overflow:hidden}
#stage{position:absolute;inset:0;background:#000}
video{width:100%;height:100%;object-fit:contain;display:block}
#lips{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
#vignette{position:absolute;inset:0;pointer-events:none;
  background:radial-gradient(120% 90% at 50% 42%,transparent 62%,rgba(0,0,0,.42) 100%),
             linear-gradient(to top,rgba(4,5,8,.55),transparent 26%)}
#plate{position:absolute;top:calc(10px + env(safe-area-inset-top));left:14px;display:flex;align-items:center;gap:10px;
  padding:8px 14px 8px 10px;border:1px solid rgba(201,164,92,.35);border-radius:10px;
  background:rgba(10,11,15,.55);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
  transition:opacity .6s}
#crest{width:30px;height:30px;border-radius:50%;border:1px solid rgba(201,164,92,.55);
  display:flex;align-items:center;justify-content:center;color:#c9a45c;font-size:15px}
#pname{font-family:Georgia,'Times New Roman',serif;font-size:13px;letter-spacing:.17em;color:#e6d5ae}
#pscene{font-size:10px;letter-spacing:.08em;color:#98917f;text-transform:uppercase}
#lamp{width:9px;height:9px;border-radius:50%;background:#3a3d45;margin-left:4px;transition:all .3s}
body.speaking #lamp{background:#43c98a;box-shadow:0 0 10px 2px rgba(67,201,138,.55)}
#hud{position:absolute;top:calc(10px + env(safe-area-inset-top));right:94px;max-width:56vw;display:none;
  font:11px ui-monospace,monospace;color:#9fb0c4;background:rgba(7,9,13,.7);
  padding:5px 9px;border-radius:6px;border:1px solid #1e2836}
body.debug #hud{display:block}
#devbtn{position:absolute;top:calc(12px + env(safe-area-inset-top));right:12px;width:30px;height:30px;
  border-radius:8px;border:1px solid #2a2c33;background:rgba(10,11,15,.45);color:#6d6a60;
  font-size:14px;cursor:pointer;transition:opacity .6s;min-height:0;padding:0}
#toast{position:absolute;left:50%;bottom:30dvh;transform:translateX(-50%) translateY(8px);
  padding:10px 18px;border-radius:10px;border:1px solid rgba(201,164,92,.5);color:#e6d5ae;
  background:rgba(10,11,15,.82);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);
  font-size:13px;letter-spacing:.03em;opacity:0;pointer-events:none;transition:all .35s;white-space:nowrap}
#toast.show{opacity:1;transform:translateX(-50%)}
#pad{position:absolute;left:0;right:0;bottom:0;display:flex;flex-wrap:wrap;gap:10px 22px;
  padding:14px 16px calc(12px + env(safe-area-inset-bottom));transition:opacity .6s;
  background:linear-gradient(to top,rgba(6,7,10,.88) 55%,transparent);align-items:flex-end}
.grp{display:flex;flex-direction:column;gap:6px;min-width:0}
.cap{font-size:9px;letter-spacing:.22em;text-transform:uppercase;color:#8a8272;padding-left:2px}
.row{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
#grpsay{flex:1;min-width:220px}
button,select,input[type=text]{font:inherit;font-size:12px;letter-spacing:.04em;padding:0 14px;min-height:40px;border-radius:9px;
  border:1px solid #33363e;background:rgba(18,20,26,.82);color:#d8d2c4;cursor:pointer;
  -webkit-tap-highlight-color:transparent}
button:active{transform:translateY(1px)}
button.on{border-color:#c9a45c;background:rgba(201,164,92,.14);color:#f0e2bd}
button[data-emo]{text-transform:capitalize;position:relative}
button[data-emo].live::after{content:'';position:absolute;top:6px;right:6px;width:5px;height:5px;
  border-radius:50%;background:#43c98a;box-shadow:0 0 6px rgba(67,201,138,.8)}
input[type=text]{flex:1;min-width:0;color:#e9e3d5;cursor:text}
input[type=text]:focus{outline:none;border-color:#c9a45c}
input[type=text]::placeholder{color:#6d6a60}
select{width:100%;appearance:none;-webkit-appearance:none;padding-right:34px;
  background-image:linear-gradient(45deg,transparent 50%,#c9a45c 50%),linear-gradient(135deg,#c9a45c 50%,transparent 50%);
  background-position:calc(100% - 18px) 50%,calc(100% - 13px) 50%;background-size:5px 5px;background-repeat:no-repeat}
#setbtn{position:absolute;top:calc(12px + env(safe-area-inset-top));right:52px;width:30px;height:30px;
  border-radius:8px;border:1px solid #2a2c33;background:rgba(10,11,15,.45);color:#8a8272;
  font-size:14px;cursor:pointer;transition:opacity .6s;min-height:0;padding:0}
#settings{position:absolute;top:calc(50px + env(safe-area-inset-top));right:12px;width:250px;display:none;
  flex-direction:column;gap:8px;padding:12px;border-radius:12px;border:1px solid rgba(201,164,92,.35);
  background:rgba(10,11,15,.85);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);z-index:5}
#settings.show{display:flex}
.shead{font-size:9px;letter-spacing:.22em;text-transform:uppercase;color:#8a8272}
.srow{display:flex;align-items:center;gap:8px}
.sname{flex:1;font-size:12px;text-transform:capitalize;color:#d8d2c4}
.scount{font-size:10px;color:#6d6a60}
.smode{min-height:26px;padding:2px 10px;font-size:10px;letter-spacing:.06em;border-radius:7px}
.smode.amb{border-color:#3fae7a;color:#7fd7ab}
.snote{font-size:10px;line-height:1.45;color:#8a8272}
body.idle #pad,body.idle #devbtn,body.idle #setbtn{opacity:0;pointer-events:none}
body.idle #settings{display:none}
body.idle #plate{opacity:.25}
@media (max-width:700px){
  #pad{gap:8px 14px}
  .grp{width:100%}
  #grpsay{min-width:0}
  #pname{font-size:11px;letter-spacing:.13em}
  #pscene{font-size:9px}
  button,select,input[type=text]{min-height:44px}
  #toast{white-space:normal;width:max-content;max-width:86vw;text-align:center;bottom:38dvh}
}
</style>
<div id=stage><video id=v playsinline webkit-playsinline muted autoplay poster=mse/poster.jpg></video><canvas id=lips></canvas><div id=vignette></div>
<div id=plate><div id=crest>&#9733;</div><div><div id=pname>GENERAL MONTGOMERY</div><div id=pscene>Foreign Secretary&#39;s Office</div></div><div id=lamp></div></div>
<div id=hud></div><div id=toast></div></div>
<script>
// SPLICE, NEVER SEEK. Traversal appends each chosen edge's fMP4 fragment into
// one continuous SourceBuffer; the boundary is just the next sample. The lag
// the seek engine could not hide -- range round-trips at every cut -- has no
// place to exist here. Lookahead is exactly ONE fragment, so a button press
// replans by removing the unplayed tail and appending the new intent.
// Delivery tier: phones get the 720p derivative (half the bytes through the
// proxy -- the lag lever), larger screens the 1080p master. ?q=720 / ?q=1080
// override for testing.
const qOverride = new URLSearchParams(location.search).get('q');
// 720 is the DEFAULT for every screen: a 1080 walk fragment is ~2.9MB and a
// slow tailnet hop stalls it mid-walk, which reads as a dead button. HD is
// an opt-in (?q=1080 or the settings toggle), never an inference from size.
// The stored `mg.hd` preference is GONE with the settings toggle that wrote
// it. A preference nothing can set and nothing can clear is worse than no
// preference: a browser that happened to have it would ask for an `mse/` set
// this bundle may not carry, and 404 in silence forever. ?q=1080 remains, for
// a deliberate one-off on a bundle that has the 1080p derivative.
const MSEBASE = qOverride === '1080' ? 'mse/' : 'mse720/';
const earlyInit = fetch(MSEBASE + 'init.mp4').then(r => r.arrayBuffer());
const earlySegs = fetch(MSEBASE + 'segments.json').then(r => r.json());
const earlyManifest = fetch('manifest.json').then(r => r.json());
const v = document.getElementById('v'), hud = document.getElementById('hud'), pad = document.getElementById('pad');
const lips = document.getElementById('lips'), lctx = lips.getContext('2d');
const toastEl = document.getElementById('toast');
let toastT = null, toastSticky = false;
function toast(msg, sticky){
  toastEl.textContent = msg; toastEl.classList.add('show'); toastSticky = !!sticky;
  clearTimeout(toastT);
  if (!sticky) toastT = setTimeout(() => toastEl.classList.remove('show'), 4000);
}
document.addEventListener('click', () => {
  if (toastSticky){ toastEl.classList.remove('show'); toastSticky = false; }
});
// The room is the interface: chrome sleeps after 4.5s and any touch wakes it.
let idleT = null;
function wake(){
  document.body.classList.remove('idle');
  clearTimeout(idleT);
  idleT = setTimeout(() => document.body.classList.add('idle'), 4500);
}
for (const ev of ['pointerdown','pointermove','touchstart','keydown','focusin'])
  document.addEventListener(ev, wake, {passive: true});
wake();
// The telemetry and settings buttons were deleted with the pad. Nothing is
// wired to them, and buildSettings has no sheet to fill.
function buildSettings(){
  const el = document.getElementById('emorows');
  if (!el) return;
  el.innerHTML = '';
  for (const tag of EMO.tags){
    const positions = openHubs().filter(h =>
      (spokes[h] || []).some(e => e.emotion === tag && e.mode !== 'speaking'));
    const row = document.createElement('div'); row.className = 'srow';
    const nm = document.createElement('span'); nm.className = 'sname'; nm.textContent = tag;
    const ct = document.createElement('span'); ct.className = 'scount'; ct.textContent = positions.length + ' pos';
    const md = document.createElement('button'); md.className = 'smode';
    const amb = EMO.ambient.includes(tag);
    md.textContent = amb ? 'ambient' : 'directed'; md.classList.toggle('amb', amb);
    md.onclick = (ev) => {
      ev.stopPropagation();
      const i = EMO.ambient.indexOf(tag);
      if (i >= 0) EMO.ambient.splice(i, 1); else EMO.ambient.push(tag);
      EMO.directed = EMO.tags.filter(t => !EMO.ambient.includes(t));
      try { localStorage.setItem('mg.ambient', JSON.stringify(EMO.ambient)); } catch(_){}
      buildSettings();
    };
    row.append(nm, ct, md); el.appendChild(row);
  }
  const hd = document.createElement('div'); hd.className = 'srow';
  const hn = document.createElement('span'); hn.className = 'sname'; hn.textContent = 'HD (1080p)';
  const hb = document.createElement('button'); hb.className = 'smode';
  const on = MSEBASE === 'mse/';
  hb.textContent = on ? 'on' : 'off'; hb.classList.toggle('amb', on);
  hb.onclick = (ev) => {
    ev.stopPropagation();
    try { localStorage.setItem('mg.hd', on ? '0' : '1'); } catch(_){}
    location.reload();
  };
  hd.append(hn, hb); el.appendChild(hd);
}
let M, SEGS = {}, sb, ms;
let timeline = [];          // appended, in order: {start,end,edge}
let appendClock = 0, feeding = false, current = -1;
let node = null, targetHub = null, wantEmotion = null, walkQueue = [], lastSpoke = '';
let spokes = {}, adj = {}, phrasesByKey = {}, speakingHold = false, visemesOn = false, activeCues = null;

// MOOD IS A PATH, NOT A DIE -- and strong feeling is never ambient. An
// emotion is a STATE HUB inside the current pose: ambient play drifts only
// through the CALM subset (composed, patient, reflective); vigilant,
// displeased and wry are DIRECTED states that appear only when chosen (a
// chip press; Boltrig's emotion engine over the clip: wire) and release
// after holdMs, decaying home through the adjacency graph. The taxonomy is
// the bundle's (manifest.emotions) when it carries one.
let EMO = {
  tags: ['composed', 'patient', 'reflective', 'vigilant', 'displeased', 'wry'],
  adjacency: {
    composed:  ['patient', 'vigilant', 'wry'],
    patient:   ['composed', 'reflective'],
    reflective:['patient'],
    vigilant:  ['composed', 'displeased'],
    displeased:['vigilant'],
    wry:       ['composed'],
  },
  ambient: ['composed', 'patient', 'reflective'],
  directed: ['vigilant', 'displeased', 'wry'],
  default: 'composed', holdMs: 45000,
};
const PHENO = {drift: 0.4, gravity: 0.3, wryCooldownMs: 240000};
let TALKBASE = {};
let mood = 'composed', lastWry = 0, directedAt = 0;
function driftMood(){
  if (wantEmotion){
    if (performance.now() - directedAt > EMO.holdMs){ wantEmotion = null; paint(); }
    else { mood = wantEmotion; return mood; }
  }
  if (Math.random() > PHENO.drift) return mood;          // stay
  const now = performance.now();
  let opts = (EMO.adjacency[mood] || ['composed'])
    .filter(e => EMO.ambient.includes(e) || e === 'composed')
    .filter(e => e !== 'wry' || now - lastWry > PHENO.wryCooldownMs);
  if (mood !== 'composed' && Math.random() < PHENO.gravity) opts = ['composed'];
  if (!opts.length) return mood;
  mood = opts[Math.floor(Math.random() * opts.length)];
  if (mood === 'wry') lastWry = now;
  return mood;
}
// THE SOUNDSCAPE. Graph clips are silent by design; the room's sound is a
// player layer: a looping murmur bed (his own phrases smeared past
// recognition behind a wall) that ducks under speech, and a door for the
// enter/exit edges. All of it waits for the unlock gesture.
let amb = null, doorOpen = null, doorClose = null, ambGain = 0.12, duckGain = 0.05;
function initSoundscape(){
  if (!M.audio) return;
  ambGain = M.audio.ambienceGain != null ? M.audio.ambienceGain : 0.12;
  duckGain = M.audio.duckGain != null ? M.audio.duckGain : 0.05;
  if (M.audio.ambience){ amb = new Audio('amb/' + M.audio.ambience); amb.loop = true; amb.volume = 0; }
  if (M.audio.doorOpen) doorOpen = new Audio('amb/' + M.audio.doorOpen);
  if (M.audio.doorClose) doorClose = new Audio('amb/' + M.audio.doorClose);
}
function door(kind){
  const d = kind === 'exit' ? (doorClose || doorOpen) : doorOpen;
  if (!d || !audioUnlocked) return;
  try { d.currentTime = 0; d.volume = 0.5; d.play().catch(()=>{}); } catch(_){}
}
const say_audio = new Audio();
say_audio.onended = () => { speakingHold = false; activeCues = null; };
// iOS AUTOPLAY UNLOCK. A <select> change is not a user gesture on iOS, so
// say_audio.play() inside it rejects silently and the clock pins at 0.00 --
// measured on device: 'SPEAK t=0.00 cues=66 aerr=-'. The cure: bless the
// element with one real tap (play a zero-sample wav), after which
// programmatic play is permitted for the element's lifetime.
let audioUnlocked = false, pendingSay = null;
function unlockAudio(){
  if (audioUnlocked) return;
  const src = say_audio.src;
  say_audio.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";
  say_audio.play().then(() => {
    audioUnlocked = true;
    say_audio.pause();
    if (amb) amb.play().catch(()=>{});
    // the doors may still be swinging when the first tap lands
    const ce = (current >= 0 && timeline[current]) ? timeline[current] : null;
    if (ce && ce.edge.kind === 'enter' && v.currentTime - ce.start < 3) door('enter');
    if (pendingSay){ const pi = pendingSay; pendingSay = null; say(pi); }
    else if (src) say_audio.src = src;
  }).catch(()=>{});
}
document.addEventListener('touchend', unlockAudio, {once: true});
document.addEventListener('click', unlockAudio, {once: true});
const spriteCache = {};
function sprite(hub, shape){
  const k = hub + '/' + shape;
  if (!spriteCache[k]){ const im = new Image(); im.src = 'sprite/' + hub + '/' + shape + '.png'; spriteCache[k] = im; }
  return spriteCache[k];
}
// POSITIONS RETIRED BY THE AUTHOR, 2026-08-25: Montgomery's H2 (standing
// beyond the far end of the conference table) and H5 (seated). Both read too
// far or too small on the boltrig stage. Their clips stay in the bundle and
// their walks stay in the graph -- nothing is deleted, because deletion is
// the one edit that cannot be taken back -- but the character no longer
// offers them and no longer chooses them. Keyed by character so a second
// bundle served by this same page keeps its own positions.
const RETIRED_HUBS = {'General Montgomery': ['H2', 'H5']};
let hiddenHubs = new Set();
// The single answer to "which positions does he have". The player's own row,
// the count in settings and the `positions` the boltrig wire advertises all
// read from here, so a retirement cannot be true in one place and false in
// another.
function openHubs(){ return Object.keys(spokes).filter(h => !hiddenHubs.has(h)); }
function hubHasEmotion(hub, emo){
  return (spokes[hub] || []).some(e => e.mode !== 'speaking' && e.emotion === emo);
}
function bfs(from, to){
  if (from === to) return [];
  if (hiddenHubs.has(to)) return null;
  const prev = {}, q = [from], seen = new Set([from]);
  while (q.length){
    const n = q.shift();
    for (const e of (adj[n] || [])){
      // Barred as a waypoint too, not merely as a destination -- a walk that
      // passes through a retired position still shows him standing in it.
      // Safe in this room: H2 and H5 are leaves off the desk, so nothing
      // else is reachable only through them.
      if (seen.has(e.dst) || hiddenHubs.has(e.dst)) continue;
      seen.add(e.dst); prev[e.dst] = e;
      if (e.dst === to){
        const path = [];
        for (let at = to; at !== from; at = prev[at].src) path.unshift(prev[at]);
        return path;
      }
      q.push(e.dst);
    }
  }
  return null;
}
function pickSpoke(atNode){
  let pool = (spokes[atNode] || []).filter(e => e.id !== lastSpoke);
  if (speakingHold){
    // Speech canvas ladder: a talk_base loop (head held steady by
    // construction, fixed sprite rect) beats the stillest clips, which beat
    // generic talk motion where no bank exists.
    const tb = TALKBASE[atNode];
    if (tb) return tb;
    if (M.sprites && M.sprites[atNode]){
      const still = pool.filter(e => e.mode === 'standby' || e.mode === 'listening');
      if (still.length) return still[Math.floor(Math.random() * still.length)];
    } else {
      const talk = pool.filter(e => e.mode === 'speaking');
      if (talk.length) return talk[Math.floor(Math.random() * talk.length)];
    }
  }
  pool = pool.filter(e => e.mode !== 'speaking');
  const m = driftMood();
  // Ambient play stays inside the current emotion state hub, may step to an
  // ADJACENT AMBIENT state, and reaches a directed state only when that state
  // was chosen -- a surprised face never appears without a surprise.
  const allowed = e => EMO.ambient.includes(e.emotion) || e.emotion === m || e.emotion === 'reorient';
  let f = pool.filter(e => e.emotion === m || e.emotion === 'reorient');
  if (!f.length) f = pool.filter(e => (EMO.adjacency[m] || []).includes(e.emotion) && allowed(e));
  if (f.length) pool = f;
  else pool = pool.filter(allowed);
  if (!pool.length) pool = (spokes[atNode] || []).filter(e => e.mode !== 'speaking' && allowed(e));
  if (!pool.length) pool = (spokes[atNode] || []).filter(e => e.mode !== 'speaking');
  return pool[Math.floor(Math.random() * pool.length)];
}
function nextEdge(fromNode){
  let edge = null;
  // Retired while he was standing there: a client that asked for the
  // position before the retirement leaves him parked in it, so walk him home
  // rather than let him idle somewhere the UI no longer names.
  if (!walkQueue.length && !targetHub && hiddenHubs.has(fromNode)){
    const open = openHubs();
    if (open.length) targetHub = open.includes(M.graph.home) ? M.graph.home : open[0];
  }
  if (walkQueue.length) edge = walkQueue.shift();
  else if (targetHub && targetHub !== fromNode){ walkQueue = bfs(fromNode, targetHub) || []; edge = walkQueue.shift() || null; }
  if (!edge && wantEmotion && !targetHub && !hubHasEmotion(fromNode, wantEmotion)){
    let best = null;
    for (const h of openHubs()){
      if (!hubHasEmotion(h, wantEmotion)) continue;
      const path = bfs(fromNode, h);
      if (path && (!best || path.length < best.length)) best = path;
    }
    if (best && best.length){ walkQueue = best; edge = walkQueue.shift(); }
  }
  if (!edge){ edge = pickSpoke(fromNode); if (edge) lastSpoke = edge.id; }
  return edge;
}
function plannedNode(){
  return timeline.length ? timeline[timeline.length - 1].edge.dst : node;
}
// EVERY SourceBuffer operation goes through one serial queue. feed, replan
// and eviction racing each other is how the append position desyncs, a gap
// opens, and playback freezes staring at it.
// Bandersnatch's trick, adapted: while a spoke plays, the fragments a plan
// CHANGE would need are already local. The cache holds whole responses; the
// reorient spoke of the planned hub is always warmed, because barge-in and
// button presses route through it.
const fragCache = new Map();
function prefetch(id){
  if (!id || !SEGS[id] || fragCache.has(id)) return;
  if (fragCache.size > 6){ fragCache.delete(fragCache.keys().next().value); }
  fragCache.set(id, fetch(MSEBASE + SEGS[id].m4s).then(r => r.arrayBuffer()).catch(() => { fragCache.delete(id); }));
}
async function fetchFrag(id){
  if (fragCache.has(id)){
    const buf = await fragCache.get(id);
    fragCache.delete(id);
    if (buf) return {body: null, cached: buf};
  }
  return await fetch(MSEBASE + SEGS[id].m4s);
}
let opChain = Promise.resolve();
function sbOp(fn){
  opChain = opChain.then(() => new Promise(res => {
    const run = () => {
      const done = () => { sb.removeEventListener('updateend', done); res(); };
      sb.addEventListener('updateend', done);
      try { fn(); } catch(e){ sb.removeEventListener('updateend', done); res(); }
    };
    if (sb.updating) sb.addEventListener('updateend', run, {once: true});
    else run();
  }));
  return opChain;
}
async function feed(){
  if (feeding || !sb) return;
  if (timeline.length - Math.max(current, 0) > 1 &&
      appendClock - v.currentTime > 9) return;   // ~9s ahead, at least two entries
  const edge = nextEdge(plannedNode());
  if (!edge || !SEGS[edge.id]) return;
  feeding = true;
  try {
    // STREAMED append: playback can begin on the first slice of a fragment.
    const at = appendClock;
    timeline.push({start: at, end: at + SEGS[edge.id].dur, edge});
    appendClock = at + SEGS[edge.id].dur;
    const resp = await fetchFrag(edge.id);
    if (resp.cached){
      await sbOp(() => { sb.timestampOffset = at; sb.appendBuffer(resp.cached); });
    } else {
      const reader = resp.body.getReader();
      let first = true;
      while (true){
        const {done, value} = await reader.read();
        if (done) break;
        const off = first ? at : null; first = false;
        await sbOp(() => { if (off !== null) sb.timestampOffset = off; sb.appendBuffer(value); });
      }
    }
    // warm the plan-change paths for the hub we just committed to
    const dst = edge.dst;
    const reo = (spokes[dst] || []).find(x => x.emotion === 'reorient');
    if (reo) prefetch(reo.id);
  } catch(e){}
  feeding = false;
}
async function replan(){
  if (!sb || current < 0 || !timeline.length) return;
  const keep = timeline[Math.min(current, timeline.length - 1)];
  if (keep.end < appendClock){
    await sbOp(() => sb.remove(keep.end, Infinity));
  }
  timeline = timeline.slice(0, current + 1);
  appendClock = keep.end;
}
function paint(){
  document.querySelectorAll('#pad [data-hub]').forEach(b =>
    b.classList.toggle('on', b.dataset.hub === (targetHub || node)));
  document.querySelectorAll('#pad [data-emo]').forEach(b => {
    b.classList.toggle('on', b.dataset.emo === wantEmotion);
    b.classList.toggle('live', b.dataset.emo === mood);
  });
  postState();
}
// THE ENTRANCE CURTAIN. He arrives through the double doors and walks the
// length of the room to the desk, and that walk is six seconds long. A line
// delivered while he is still crossing plays to an empty desk: the voice
// starts before the man is there to say it.
//
// So the first line is HELD, never dropped -- the reply is still spoken, a
// moment later, from the position he speaks from. Only the most recent held
// line survives: a queue would empty itself onto the desk in one burst, and
// the older lines would be answering a question two turns stale.
//
// It opens three ways, and the third is the one that matters: the walk
// finishing, the graph having no entrance at all, or a wall-clock deadline.
// A curtain that can only be raised by an event that might not arrive is a
// character who is silent forever, and nobody would report that as a bug --
// he would simply seem to have nothing to say.
const ENTRANCE_DEADLINE_MS = 12000;
let curtain = {open: false, until: 0, held: null};
function openCurtain(){
  if (curtain.open) return;
  curtain.open = true;
  const held = curtain.held;
  curtain.held = null;
  if (held) held();
  paint();
}
/** True while a line must wait. Also opens the curtain the moment the
 *  entrance walk is behind us in MEDIA time -- media time rather than the
 *  clock, so a buffering stall delays the line instead of losing it. */
function curtainHolds(){
  if (curtain.open) return false;
  if (curtain.until && v.currentTime >= curtain.until){ openCurtain(); return false; }
  return true;
}
let frozenSpeech = false, speechAtBoundary = null;
function beginSpeech(pi){
  say_audio.src = 'pw/' + pi.wav;
  activeCues = (pi.visemes && pi.visemes.length) ? pi.visemes : null;
  say_audio.play().then(() => { audioUnlocked = true; }).catch(() => {
    pendingSay = pi;
    toast('Tap anywhere to let him speak', true);
  });
  speakingHold = true;
}
function say(pi){
  if (curtainHolds()){ curtain.held = () => say(pi); return; }
  v.muted = false;
  const synced = phrasesByKey[pi.n + '@' + node];
  if (synced){ walkQueue.unshift(synced); replan().then(feed); return; }
  // He speaks IN MOTION. The tracker finds the mouth in the moving frame at
  // ~12Hz (SAD template search, three scales), so gesture clips and live
  // lips coexist; when lock is lost the sprite hides rather than smearing.
  beginSpeech(pi);
  replan().then(feed);
}

// (The SAD mouth tracker is gone: a patch pasted onto a gesturing face
// reads as a ghost. Sprites draw only on steady canvases at fixed rects.)
function drawLips(){
  lips.width = lips.clientWidth; lips.height = lips.clientHeight;
  lctx.clearRect(0, 0, lips.width, lips.height);
  if (speakingHold){
    // the truth line: what the speech engine thinks is happening
    const t0 = say_audio.currentTime;
    const cue = activeCues ? activeCues.find(c => t0 >= c.start && t0 < c.end) : null;
    hud.textContent = 'SPEAK t=' + t0.toFixed(2) +
      ' cues=' + (activeCues ? activeCues.length : 'none') +
      ' cue=' + (cue ? cue.value : '-') +
      ' sprites@' + node + '=' + (M.sprites && M.sprites[node] ? 'yes' : 'NO') +
      ' aerr=' + (say_audio.error ? say_audio.error.code : '-');
  }
  if (!visemesOn || !speakingHold || !M.sprites || !M.sprites[node]) return;
  const ce = (current >= 0 && timeline[current]) ? timeline[current].edge : null;
  if (!frozenSpeech && !(ce && ce.kind === 'talk_base')) return;
  const [rx, ry, rw, rh] = M.sprites[node].rect;
  const tk = {x: rx, y: ry, w: rw, h: rh};
  let cue = null;
  if (activeCues){
    const ta = say_audio.currentTime;
    cue = activeCues.find(c => ta >= c.start && ta < c.end);
  }
  if (!cue) cue = {value: 'X'};
  // minimum hold + crossfade: shapes hold >=60ms and blend ~45ms
  const now = performance.now();
  if (drawLips.last && now - drawLips.lastAt < 60) cue = drawLips.last;
  else if (!drawLips.last || drawLips.last.value !== cue.value){
    drawLips.prev = drawLips.last;
    drawLips.last = cue; drawLips.lastAt = now;
  }
  const scale = Math.min(lips.width / 1920, lips.height / 1080);
  const ox = (lips.width - 1920 * scale) / 2, oy = (lips.height - 1080 * scale) / 2;
  const dx = ox + tk.x * scale, dy = oy + tk.y * scale,
        dw = tk.w * scale, dh = tk.h * scale;
  const fade = Math.min(1, (now - drawLips.lastAt) / 45);
  const cur = sprite(node, cue.value);
  if (drawLips.prev && fade < 1){
    const pv = sprite(node, drawLips.prev.value);
    if (pv.complete && pv.naturalWidth) lctx.drawImage(pv, dx, dy, dw, dh);
  }
  if (cur.complete && cur.naturalWidth){
    lctx.globalAlpha = (drawLips.prev && fade < 1) ? fade : 1;
    lctx.drawImage(cur, dx, dy, dw, dh);
    lctx.globalAlpha = 1;
  }
}
function tick(){
  if (timeline.length){
    let i = current;
    while (i + 1 < timeline.length && v.currentTime >= timeline[i + 1].start - 0.02) i++;
    if (i !== current){
      current = i;
      const e = timeline[current].edge;
      node = e.dst;
      if (e.kind === 'enter' || e.kind === 'exit') door(e.kind);
      // The walk is on screen: the curtain lifts when it is behind us.
      if (e.kind === 'enter' && !curtain.open){
        const seg = SEGS[e.id];
        curtain.until = timeline[current].start + (seg ? seg.dur : 0);
      }
      if (speechAtBoundary && M.sprites && M.sprites[e.src]){
        // the first frame of this entry is the hub plate: freeze on it
        v.currentTime = timeline[current].start + 0.001;
        v.pause();
        frozenSpeech = true;
        const pi = speechAtBoundary; speechAtBoundary = null;
        beginSpeech(pi);
      }
      hud.textContent = e.id + ' [' + e.emotion + ']  mood:' + mood + '  @' + node + '  buf ' + (appendClock - v.currentTime).toFixed(1) + 's';
      paint();
    }
    // evict what is far behind so memory stays flat
    if (sb && v.currentTime > 30 && (!tick.lastEvict || v.currentTime - tick.lastEvict > 10)){
      tick.lastEvict = v.currentTime;
      sbOp(() => sb.remove(0, v.currentTime - 20));
    }
  }
  // Stall watchdog: playing, data exists ahead, but the head is not moving --
  // a gap. Jump to the start of the next buffered range instead of freezing.
  if (!v.paused && sb){
    if (tick.lastT === v.currentTime){
      tick.stuck = (tick.stuck || 0) + 1;
      if (tick.stuck > 300){                      // ~5s: a slow fetch is not a gap
        tick.stuck = 0;
        const b = v.buffered;
        for (let i = 0; i < b.length; i++){
          if (b.start(i) > v.currentTime + 0.01){
            hud.textContent += '  [gap-jump]';
            v.currentTime = b.start(i) + 0.001;
            break;
          }
        }
      }
    } else { tick.stuck = 0; tick.lastT = v.currentTime; }
  }
  document.body.classList.toggle('speaking', !!speakingHold);
  if (amb) amb.volume += ((speakingHold ? duckGain : ambGain) - amb.volume) * 0.06;
  feed();
  drawLips();
  requestAnimationFrame(tick);
}
// EMBEDDED MEANS DRIVEN. When a host frames this page, the host is choosing
// his position, his bearing and what he says -- from the turn, the phenotype
// and the reply. Leaving the pad on screen beside that offers a second hand on
// the same wheel: a click would fight the drive, and the drive would win on
// its next update, so the control would look broken rather than absent.
//
// It is also a fidelity point rather than only a UI one. His whole design is
// that a directed state needs a cause -- "a surprised face never appears
// without a surprise" -- and a button that produces displeasure with no
// displeasing thing is exactly the surprise with no cause.
//
// STANDALONE KEEPS THEM. Opened directly, this page is the bench: the pad is
// how a person exercises the graph, and `/say` still renders his voice. The
// condition is the same one postState() already uses to decide it has a host,
// so the two answers cannot drift apart.
// ALWAYS. The shipped player offers no controls at all: his position and
// bearing are chosen from the turn, the phenotype and the reply, and a
// button that produced displeasure with no displeasing thing would be
// exactly the surprise-without-a-cause his design forbids.
const EMBEDDED = true;
function hideDriverControls(){
  if (!EMBEDDED) return;
  const pad = document.getElementById('pad');
  if (pad) pad.style.display = 'none';
  // The settings sheet edits which tags drift; that is the drive's business
  // too once a host is attached. Telemetry stays -- it reads, it does not act.

}
async function boot(){
  hideDriverControls();
  M = await earlyManifest;
  for (const s of await earlySegs) SEGS[s.id] = s;
  document.title = M.character + ' — ' + M.scene + ' (v2)';
  hiddenHubs = new Set(RETIRED_HUBS[M.character] || []);
  for (const e of M.graph.edges){
    if (e.kind === 'talk_base'){ TALKBASE[e.src] = e; (spokes[e.src] ||= []).push(e); }
    else if (e.kind === 'spoke') (spokes[e.src] ||= []).push(e);
    else (adj[e.src] ||= []).push(e);
    if (e.kind === 'phrase') phrasesByKey[e.n + '@' + e.src] = e;
  }
  if (M.emotions) EMO = Object.assign({}, EMO, M.emotions);
  try {
    const ov = JSON.parse(localStorage.getItem('mg.ambient') || 'null');
    if (Array.isArray(ov) && ov.length) EMO.ambient = ov.filter(t => EMO.tags.includes(t));
  } catch(_){}
  EMO.directed = EMO.tags.filter(t => !EMO.ambient.includes(t));
  visemesOn = !!(Object.keys(TALKBASE).length && M.sprites && Object.keys(M.sprites).length);
  buildSettings();
  // NO CONTROLS AT ALL, and they are absent rather than hidden.
  //
  // A position row, a bearing row and an address box used to be built here.
  // A hidden button is still in the accessibility tree, still focusable and
  // still clickable by script, so hiding them was never the same as not
  // having them.
  //
  // He moves by himself: his ambient states drift on their own adjacency
  // walk, and everything directed comes from the host, which reads the turn,
  // the phenotype and the reply. A control here would be a second hand on the
  // same wheel -- it would fight the drive and lose on its next update, which
  // reads as a broken button rather than an absent one.
  initSoundscape();
  const enter = M.graph.edges.find(e => e.id === M.graph.enter);
  node = enter ? enter.src : (M.graph.home || 'H1');
  if (enter) walkQueue = [enter];
  // A character with no entrance has nobody to wait for.
  if (!enter) openCurtain();
  else setTimeout(openCurtain, ENTRANCE_DEADLINE_MS);
  // His day begins at the desk: doors, a beat standing, then he walks to
  // where the work is.
  targetHub = 'H1';

  const MS = window.ManagedMediaSource || window.MediaSource;
  ms = new MS();
  if (window.ManagedMediaSource) v.disableRemotePlayback = true;
  v.src = URL.createObjectURL(ms);
  ms.addEventListener('sourceopen', async () => {
    let codec = 'video/mp4; codecs="avc1.640028"';
    try { sb = ms.addSourceBuffer(codec); }
    catch(e){ sb = ms.addSourceBuffer('video/mp4; codecs="avc1.64002a"'); }
    sb.mode = 'segments';   // explicit offsets; sequence-mode auto-placement
                             // fights remove() and opens unplayable gaps
    const init = await earlyInit;
    await new Promise(res => { sb.addEventListener('updateend', res, {once: true}); sb.appendBuffer(init); });
    feed();
    v.play().catch(()=>{});
  }, {once: true});
  document.addEventListener('click', () => { v.muted = false; }, {once: true});
  requestAnimationFrame(tick);
}
// THE BOLTRIG WIRE. ClipStage iframes this page and speaks 'clip:' messages;
// state flows back on every boundary. clip:speak carries live TTS -- the
// exact shape pocket-voice /v1/audio/speech_with_visemes returns.
function playerState(){
  return {type: 'clip:state', character: M ? M.character : null, node, mood,
          wantEmotion, targetHub, speaking: !!speakingHold,
          emotions: {tags: EMO.tags, ambient: EMO.ambient, directed: EMO.directed,
                     adjacency: EMO.adjacency, default: EMO.default, holdMs: EMO.holdMs},
          positions: openHubs(), talkBase: Object.keys(TALKBASE),
          entered: curtain.open, speechHeld: !!curtain.held};
}
function postState(){
  if (window.parent !== window){
    try { window.parent.postMessage(playerState(), '*'); } catch(_){}
  }
}
function beginSpeechData(b64, cues){
  if (curtainHolds()){ curtain.held = () => beginSpeechData(b64, cues); return; }
  v.muted = false;
  say_audio.src = 'data:audio/wav;base64,' + b64;
  activeCues = (cues && cues.length) ? cues : null;
  say_audio.play().then(() => { audioUnlocked = true; }).catch(() => {
    toast('Tap anywhere to let him speak', true);
  });
  speakingHold = true;
  replan().then(feed);
}
window.addEventListener('message', ev => {
  const d = ev.data;
  if (!d || typeof d.type !== 'string' || d.type.indexOf('clip:') !== 0) return;
  if (d.type === 'clip:emotion'){
    wantEmotion = EMO.tags.includes(d.tag) ? d.tag : null;
    directedAt = performance.now();
    walkQueue = []; replan().then(feed); paint();
  } else if (d.type === 'clip:position'){
    if (!hiddenHubs.has(d.hub) && (spokes[d.hub] || adj[d.hub])){ targetHub = d.hub; walkQueue = []; replan().then(feed); paint(); }
  } else if (d.type === 'clip:say'){
    const idx = M.phrase_index || [];
    const pi = (d.n != null) ? idx.find(x => x.n === d.n) : idx.find(x => x.text === d.text);
    if (pi) say(pi);
  } else if (d.type === 'clip:speak'){
    if (d.audio_b64) beginSpeechData(d.audio_b64, d.mouthCues || null);
  } else if (d.type === 'clip:visemes'){
    visemesOn = !!d.on;
  } else if (d.type === 'clip:state?'){
    (ev.source || window.parent).postMessage(playerState(), '*');
  }
});
boot();
</script>"""


class H(BaseHTTPRequestHandler):
    def _hdr(self, code, ctype, length, extra=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            # v2 (MSE splice engine) is canonical since 2026-08-21: no seeks,
            # instant doors, streamed appends. The seek player survives at /v1
            # for a bake with no mse/ derivative.
            body = PAGE_V2.encode()
            return self._hdr(200, "text/html; charset=utf-8", len(body)) or self.wfile.write(body)
        if path == "/v1":
            body = PAGE_V2.encode()
            return self._hdr(200, "text/html; charset=utf-8", len(body)) or self.wfile.write(body)
        if path == "/v2":
            body = PAGE_V2.encode()
            return self._hdr(200, "text/html; charset=utf-8", len(body)) or self.wfile.write(body)
        mm = re.match(r"^/(mse|mse720)/([A-Za-z0-9_.-]+)$", path)
        if mm:
            # Serve whichever set was ASKED for, when the bundle carries it.
            # Deriving the sibling from MSE_DIR meant the answer depended on
            # which one happened to be found first.
            base = FRAME.parent / mm.group(1)
            f = base / mm.group(2)
            if base.is_dir() and f.is_file() and f.parent == base:
                body = f.read_bytes()
                ctype = ("application/json" if f.suffix == ".json" else "video/mp4")
                return self._hdr(200, ctype, len(body)) or self.wfile.write(body)
        if path == "/manifest.json":
            # The state blob is the big half and the page does not use it yet;
            # send the segment list only, so a phone is not parsing 1.5 MB.
            slim = {k: v for k, v in MANIFEST.items() if k != "state"}
            # graph rides along: it is the whole point for a graph bake
            body = json.dumps(slim).encode()
            return self._hdr(200, "application/json", len(body)) or self.wfile.write(body)
        if path == "/state.json":
            body = json.dumps(MANIFEST.get("state", {})).encode()
            return self._hdr(200, "application/json", len(body)) or self.wfile.write(body)
        if path == "/media":
            return self.media()
        ms = re.match(r"^/sprite/([A-Za-z0-9]+)/([A-Z])\.png$", path)
        if ms and SPRITES_DIR:
            f = SPRITES_DIR / ms.group(1) / (ms.group(2) + ".png")
            if f.is_file():
                body = f.read_bytes()
                return self._hdr(200, "image/png", len(body)) or self.wfile.write(body)
        ma = re.match(r"^/amb/([a-z_]+\.wav)$", path)
        if ma and AMB_DIR:
            f = AMB_DIR / ma.group(1)
            if f.is_file():
                body = f.read_bytes()
                return self._hdr(200, "audio/wav", len(body)) or self.wfile.write(body)
        m = re.match(r"^/pw/(p\d{2}\.wav)$", path)
        if m and WAVS_DIR:
            f = WAVS_DIR / m.group(1)
            if f.is_file():
                body = f.read_bytes()
                return self._hdr(200, "audio/wav", len(body)) or self.wfile.write(body)
        self._hdr(404, "text/plain", 9)
        self.wfile.write(b"not found")

    def do_POST(self):
        # /say {text}: live line -> pocket-voice speech_with_visemes (over the
        # the TTS tunnel) -> {audio_b64, mouthCues} passed through untouched.
        import urllib.request as _rq
        path = self.path.split("?")[0]
        if path == "/say":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(n) or b"{}")
                text = (req.get("text") or "").strip()[:400]
                if not text:
                    raise ValueError("empty text")
                body = json.dumps({"model": "pocket-tts", "input": text,
                                   "voice": VOICE_NAME,
                                   "response_format": "wav"}).encode()
                r = _rq.Request(VOICE_URL + "/v1/audio/speech_with_visemes",
                                data=body,
                                headers={"Content-Type": "application/json"})
                with _rq.urlopen(r, timeout=90) as resp:
                    out = resp.read()
                return self._hdr(200, "application/json", len(out)) or self.wfile.write(out)
            except Exception as e:
                out = json.dumps({"error": str(e)[:200]}).encode()
                return self._hdr(502, "application/json", len(out)) or self.wfile.write(out)
        self._hdr(404, "text/plain", 9)
        self.wfile.write(b"not found")

    def media(self):
        size = FRAME.stat().st_size
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng.strip())
            if m:
                a, b = m.group(1), m.group(2)
                if a:
                    start = int(a)
                    if b:
                        end = int(b)
                else:                                   # suffix range: last N bytes
                    start = max(0, size - int(b or 0))
            if start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        end = min(end, size - 1)
        length = end - start + 1
        code = 206 if rng else 200
        extra = [("Accept-Ranges", "bytes")]
        if rng:
            extra.append(("Content-Range", f"bytes {start}-{end}/{size}"))
        self._hdr(code, "video/mp4", length, extra)
        with open(FRAME, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(262144, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return                              # the browser seeked away
                left -= len(chunk)

    def log_message(self, *a):
        pass


def main():
    global FRAME, MANIFEST
    ap = argparse.ArgumentParser(description="Play a .frame.mp4")
    ap.add_argument("file")
    ap.add_argument("--port", type=int, default=8902)
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 exposes it; prefer a tailscale serve instead")
    a = ap.parse_args()

    global WAVS_DIR
    FRAME = pathlib.Path(a.file).expanduser().resolve()
    global SPRITES_DIR
    cand = FRAME.parent.parent / "voice/lines"
    WAVS_DIR = cand if cand.is_dir() else None
    sc = FRAME.parent / "sprites"
    SPRITES_DIR = sc if sc.is_dir() else None
    global AMB_DIR
    ac = FRAME.parent.parent / "audio"
    AMB_DIR = ac if ac.is_dir() else None
    global MSE_DIR
    # EITHER DERIVATIVE IS ENOUGH. This used to be `mse` alone, and everything
    # -- including mse720 -- was gated on that one directory existing. A bundle
    # shipped with only the 720p set (34MB, against 114MB for the 1080p one)
    # therefore served NO fragments at all, and the symptom was a page that
    # loaded, reported its manifest correctly and then sat on a black frame.
    mc = FRAME.parent / "mse"
    m7 = FRAME.parent / "mse720"
    MSE_DIR = mc if mc.is_dir() else (m7 if m7.is_dir() else None)
    if not FRAME.is_file():
        raise SystemExit(f"no such file: {FRAME}")
    MANIFEST = frame_box.read(FRAME)
    if MANIFEST is None:
        raise SystemExit(f"{FRAME.name} carries no .frame payload -- baked with frame_bake.py?")

    print(f"{MANIFEST['character']} / {MANIFEST['scene']}: "
          f"{len(MANIFEST['segments'])} segments, {MANIFEST['duration']/60:.1f} min")
    print(f"framegraph player on http://{a.host}:{a.port}")
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()


if __name__ == "__main__":
    main()
