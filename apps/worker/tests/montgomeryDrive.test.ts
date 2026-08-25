import { describe, expect, it } from "vitest";
import type { CharacterStageState } from "@wlilley93/boltrig-web-sdk";
import {
  addressedAsMonty,
  agreeOnVocabulary,
  drive,
  isDirectable,
  voiceIdFor,
} from "../src/components/montgomery/frameGraphDrive";

// His body cannot emote; it can only choose a clip. So these are not tests of
// a renderer, they are tests of the character -- the ordering below IS the
// policy, and a change to it is a change to who he is.
const idle: CharacterStageState = { working: false, speaking: false, level: 0 };
const busy: CharacterStageState = { working: true, speaking: false, level: 0 };

describe("what General Montgomery does next", () => {
  it("puts him at the desk for a run in flight, and directs no emotion", () => {
    const d = drive({ turn: busy });
    expect(d.position).toBe("H1");
    // Ordinary work must not wear a face.
    expect(d.emotion).toBeUndefined();
  });

  it("reads measured irritation as displeasure, at the fireplace", () => {
    const d = drive({ turn: idle, phenotype: { irritation: 0.8 } });
    expect(d.emotion).toBe("displeased");
    expect(d.position).toBe("H3");
    expect(d.register).toBe("serious");
  });

  it("does not move him to deliver a grave assessment", () => {
    const d = drive({ turn: idle, reply: "The situation has changed.", at: "H4" });
    expect(d.emotion).toBe("vigilant");
    // He speaks from where he is; movement is never the price of a reply.
    expect(d.position).toBe("H4");
  });

  it("treats a dry aside as a directed state, not a drift", () => {
    const d = drive({ turn: idle, reply: "Well. That is one way to do it." });
    expect(d.emotion).toBe("wry");
    expect(d.register).toBe("amused");
  });

  it("walks him to the window for the long view but directs NO emotion", () => {
    const d = drive({ turn: idle, reply: "History is an operating manual." });
    expect(d.position).toBe("H4");
    // `reflective` is ambient: he is taken there and arrives at the mood himself.
    expect(d.emotion).toBeUndefined();
    expect(d.register).toBe("tender");
  });

  it("never emits an ambient tag, whatever it is given", () => {
    const replies = [
      "The situation has changed", "Well. Quite.", "No. And I want you to understand why",
      "History is long", "Hold your position", "You made the right call", "", "ordinary text",
    ];
    for (const reply of replies) {
      const d = drive({ turn: idle, reply });
      if (d.emotion) expect(isDirectable(d.emotion)).toBe(true);
    }
  });

  it("never chooses a retired position", () => {
    const seen = new Set<string>();
    for (const irritation of [0, 0.3, 0.7, 1]) {
      for (const alertness of [0, 0.3, 0.7, 1]) {
        for (const reply of ["", "grave loss", "Well. Quite.", "history", "hold", "right call", "chatter"]) {
          for (const working of [true, false]) {
            const d = drive({ turn: { working, speaking: false, level: 0 },
                              phenotype: { irritation, alertness }, reply });
            if (d.position) seen.add(d.position);
          }
        }
      }
    }
    // H2 (beyond the far end of the table) and H5 (seated) were retired.
    expect(seen.has("H2")).toBe(false);
    expect(seen.has("H5")).toBe(false);
  });
});

describe("the Monty register", () => {
  it("replaces the register without softening the news", () => {
    const d = drive({ turn: idle, reply: "The situation has changed.", address: "Monty, what of it?" });
    expect(d.register).toBe("monty");
    expect(d.emotion).toBe("vigilant");
  });

  it("does not trip on his full name", () => {
    expect(addressedAsMonty("General Montgomery, report")).toBe(false);
    expect(addressedAsMonty("Monty")).toBe(true);
  });
});

describe("voice resolution", () => {
  it("falls back to HIS base voice, never to a stranger", () => {
    expect(voiceIdFor("montgomery", "serious", ["montgomery"])).toBe("montgomery");
    expect(voiceIdFor("montgomery", "serious", ["montgomery", "montgomery-serious"]))
      .toBe("montgomery-serious");
    expect(voiceIdFor("montgomery", "base", ["montgomery", "montgomery-serious"]))
      .toBe("montgomery");
  });
});

describe("vocabulary drift", () => {
  it("reports a mismatch rather than throwing", () => {
    expect(agreeOnVocabulary(
      ["composed", "patient", "reflective", "vigilant", "displeased", "wry"],
      ["H1", "H3", "H4"],
    )).toEqual({ emotions: [], positions: [] });
    // A regenerated bundle should cost him expressiveness, not the Stage: the
    // player DROPS an unknown tag, so without this the symptom is a character
    // who quietly stopped reacting.
    const drifted = agreeOnVocabulary(["composed", "patient"], ["H1"]);
    expect(drifted.emotions).toEqual(["vigilant", "displeased", "wry"]);
    expect(drifted.positions).toEqual(["H3", "H4"]);
  });
});
