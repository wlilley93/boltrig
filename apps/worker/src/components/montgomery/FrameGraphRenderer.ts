// The body a FRAME-GRAPH character wears: the local frame player embedded as
// an iframe, driven over its `clip:` bridge and listened to on the way back.
//
// WHY THIS IS NOT ClipVideoRenderer. They look like the same thing and are
// not, and the difference is not cosmetic:
//
//   - ClipVideoRenderer posts `{clip: "react", emotion, energy}`. The frame
//     player listens for `{type: "clip:emotion", tag}` and drops anything
//     whose `type` does not begin `clip:`. Pointing one at the other is a
//     character who never reacts, with no error anywhere -- and that is what
//     General Montgomery's registration actually did: it also inherited
//     ClipVideoRenderer's default player URL, so it addressed Maya's library
//     on :8901 rather than his own on :8902.
//   - ClipVideoRenderer is WRITE-ONLY. It posts and never listens, so it
//     cannot know where he is, and every decision it makes is about where it
//     last ASKED him to be. The frame player answers `clip:state` on every
//     clip boundary; this reads it, so the drive is computed against where he
//     actually is.
//   - ClipStage forwards no phenotype, by an accepted omission in its own
//     comment. That is precisely the channel a frame-graph character needs,
//     because his expression IS clip selection and there is nothing else for a
//     measured affect to move.
//
// Both doctrines the older renderer carries still bind here, unchanged:
//   - Cosmetic only (ADR 0025): nothing below may influence dispatch, grants,
//     HITL or routing. These messages choose a clip. They carry no text, no
//     credentials and no identifiers.
//   - One chokepoint: DELIBERATE acts stay behind the governed companion.*
//     verbs. What this sends is the ambient mirror of Stage state that every
//     other body gets for free.
import type { CharacterPresentationMode, CharacterStageState } from "@wlilley93/boltrig-web-sdk";
import {
  agreeOnVocabulary,
  drive,
  voiceIdFor,
  type Drive,
  type Emotion,
  type Phenotype,
  type Position,
  type Register,
} from "./frameGraphDrive";

export interface FrameGraphRendererStatus {
  kind: "iframe";
  state: "mounted" | "running" | "suspended" | "failed" | "destroyed";
  /** Present only when state is "failed"; safe to log, never user content. */
  reason?: string;
}

export interface FrameGraphConfig {
  /** Matches the character id. */
  id: string;
  /** The player's own name for the character, for the iframe title. */
  library: string;
  /** Loopback player. Each frame-graph character has its OWN, unlike the clip
   *  library players -- his graph rides inside his own .frame.mp4. */
  playerUrl: string;
  /** The base pocket-voice clone. Registers are `${base}-${register}`. */
  voiceBase?: string;
}

/** What the player answers with on every clip boundary (see WIRE.md). */
export interface ClipState {
  type: "clip:state";
  character?: string;
  node?: Position | string | null;
  mood?: Emotion | string | null;
  wantEmotion?: string | null;
  targetHub?: string | null;
  speaking?: boolean;
  positions?: string[];
  talkBase?: string[];
  emotions?: { tags?: string[] };
  /** False while he is still walking in through the doors. */
  entered?: boolean;
  speechHeld?: boolean;
}

/** Loopback only, and no credentials, query or fragment: this value doubles as
 *  the postMessage target origin, so a permissive one would widen where these
 *  messages can land. Identical rule to the clip renderer, deliberately. */
export function validatedPlayerUrl(value: string): string | null {
  try {
    const parsed = new URL(value);
    const loopback = new Set(["localhost", "127.0.0.1", "[::1]"]);
    if (
      !["http:", "https:"].includes(parsed.protocol)
      || !loopback.has(parsed.hostname.toLowerCase())
      || parsed.username
      || parsed.password
      || parsed.search
      || parsed.hash
    ) return null;
    return parsed.toString();
  } catch {
    return null;
  }
}

type ClipCommand =
  | { type: "clip:emotion"; tag: Emotion }
  | { type: "clip:position"; hub: Position }
  | { type: "clip:state?" };

export class FrameGraphRenderer {
  readonly kind = "iframe" as const;

  private readonly playerUrl: string | null;
  private readonly origin: string | null;
  private frame: HTMLIFrameElement | null = null;
  private statusValue: FrameGraphRendererStatus = { kind: "iframe", state: "mounted" };
  private state: ClipState = {};
  private listener: ((event: MessageEvent) => void) | null = null;

  // EDGES, NOT POLLS. update() runs on every render; a walk across the room is
  // a transition. Re-posting the position he is already heading to restarts
  // nothing here but would restart the plan in the player, so he would step on
  // the spot forever while a turn streamed.
  private lastEmotion: Emotion | null = null;
  private lastPosition: Position | null = null;
  private lastDrive: Drive | null = null;
  /** Logged once, not per frame: a vocabulary mismatch is a build fact. */
  private warnedVocabulary = false;

  constructor(private readonly config: FrameGraphConfig) {
    this.playerUrl = validatedPlayerUrl(config.playerUrl);
    this.origin = this.playerUrl ? new URL(this.playerUrl).origin : null;
  }

  mount(container: HTMLElement): void {
    if (this.playerUrl === null) {
      this.statusValue = { kind: "iframe", state: "failed", reason: "player_url_invalid" };
      return;
    }
    const frame = document.createElement("iframe");
    frame.className = "frame-stage-frame";
    frame.src = this.playerUrl;
    frame.title = this.config.library;
    frame.setAttribute("allow", "autoplay");
    // Scripts and its own origin for the bridge, and nothing else: no
    // navigation, popups, forms, downloads or parent authority.
    frame.setAttribute("sandbox", "allow-scripts allow-same-origin");
    frame.referrerPolicy = "no-referrer";

    // The return channel. Origin-checked against the one URL we were willing
    // to load: a page that is not the player cannot tell us where he is.
    this.listener = (event: MessageEvent) => {
      if (this.origin === null || event.origin !== this.origin) return;
      const data = event.data as ClipState | undefined;
      if (!data || data.type !== "clip:state") return;
      this.state = data;
      this.checkVocabulary(data);
    };
    window.addEventListener("message", this.listener);

    frame.addEventListener("load", () => {
      // Ask once rather than wait for the first boundary: a character that has
      // just mounted may be several seconds of walk away from one.
      this.post({ type: "clip:state?" });
    }, { once: true });

    container.appendChild(frame);
    this.frame = frame;
    this.statusValue = { kind: "iframe", state: "running" };
  }

  /**
   * The one decision point. Turn facts and the measured phenotype in; a clip
   * choice and a voice register out.
   *
   * The register is RETURNED rather than sent, because the player does not
   * render his speech -- boltrig does, through the governed voice verb, and
   * then hands the finished audio back over `clip:speak`. So the register has
   * to reach the caller in time to be part of that request.
   */
  update(
    next: Partial<CharacterStageState>,
    phenotype?: Phenotype | null,
    reply?: string | null,
    address?: string | null,
  ): Drive {
    const decision = drive({
      turn: next as CharacterStageState,
      phenotype,
      reply,
      address,
      at: (this.state.node as Position | undefined) ?? null,
    });
    this.lastDrive = decision;

    // A DIRECTED tag only. `drive` returns undefined for everything ambient,
    // and undefined here means "leave him alone" -- his own drift is the
    // resting behaviour and overriding it with a poll would replace a mood
    // with a metronome.
    if (decision.emotion && decision.emotion !== this.lastEmotion) {
      this.post({ type: "clip:emotion", tag: decision.emotion });
      this.lastEmotion = decision.emotion;
    }
    if (decision.position && decision.position !== this.lastPosition) {
      this.post({ type: "clip:position", hub: decision.position });
      this.lastPosition = decision.position;
    }
    return decision;
  }

  /** The clone that should speak the next line, given the last decision. */
  voiceId(fallback: string, register?: Register): string {
    const base = this.config.voiceBase ?? fallback;
    const wanted = register ?? this.lastDrive?.register ?? "base";
    return voiceIdFor(base, wanted, this.availableRegisters(base));
  }

  /** Where he is, as the player last reported it. Never where we last asked. */
  where(): ClipState {
    return this.state;
  }

  /** False while he is still crossing the room. The player holds his first
   *  line until this is true; a caller may show "arriving" rather than guess. */
  hasEntered(): boolean {
    return this.state.entered !== false;
  }

  /** The iframe fills its host via CSS; there is no canvas to re-size. */
  resize(): void {}

  setMode(mode: CharacterPresentationMode): void {
    // "voice" changes nothing visual: he is already a full-motion body.
    if (mode === "minimised") this.suspend();
    else this.resume();
  }

  suspend(): void {
    if (this.statusValue.state !== "running") return;
    if (this.frame) this.frame.style.visibility = "hidden";
    this.statusValue = { kind: "iframe", state: "suspended" };
  }

  resume(): void {
    if (this.statusValue.state !== "suspended") return;
    if (this.frame) this.frame.style.visibility = "";
    this.statusValue = { kind: "iframe", state: "running" };
  }

  status(): FrameGraphRendererStatus {
    return this.statusValue;
  }

  destroy(): void {
    if (this.listener) window.removeEventListener("message", this.listener);
    this.listener = null;
    this.frame?.remove();
    this.frame = null;
    this.statusValue = { kind: "iframe", state: "destroyed" };
  }

  /**
   * Registers this install can actually reach.
   *
   * Derived from what the PLAYER reports rather than from a list here: a clone
   * that has not been cut yet must fall back to his base voice, and a list
   * compiled into this file would claim otherwise the moment one is retired.
   * Absent knowledge means base, which is the same man rather than a stranger.
   */
  private availableRegisters(base: string): string[] {
    const talk = this.state.talkBase ?? [];
    void talk;
    // The player does not enumerate voices; the runtime does, and the caller
    // holds that catalogue. Until one is supplied, only the base is claimed --
    // deliberately pessimistic, because claiming a clone that is not there
    // would ask the runtime for a voice it would refuse.
    return [base];
  }

  private checkVocabulary(state: ClipState): void {
    if (this.warnedVocabulary) return;
    const tags = state.emotions?.tags;
    const positions = state.positions;
    if (!tags || !positions) return;
    this.warnedVocabulary = true;
    const missing = agreeOnVocabulary(tags, positions);
    if (missing.emotions.length === 0 && missing.positions.length === 0) return;
    // Warn, never throw: a regenerated bundle should cost him expressiveness,
    // not the Stage. Silence here is the failure mode that matters -- an
    // unknown tag is DROPPED by the player, so without this line the symptom
    // is a character who simply stopped reacting.
    console.warn(
      `[${this.config.id}] the player's vocabulary no longer matches the drive:`,
      missing.emotions.length ? `emotions missing ${missing.emotions.join(", ")}` : "",
      missing.positions.length ? `positions missing ${missing.positions.join(", ")}` : "",
    );
  }

  private post(command: ClipCommand): void {
    // Not mounted yet / already gone, or the frame has not loaded: the gesture
    // is transient, so dropping it beats queueing it.
    if (this.playerUrl !== null) {
      this.frame?.contentWindow?.postMessage(command, this.playerUrl);
    }
  }
}
