import { describe, expect, it } from "vitest";

import { speechTakeaway } from "../src/components/chat/speechTakeaway";
import { tickerFor } from "../src/components/colossus/tickerText";
import { clampColossusState, colossusStateFromTurn } from "../src/components/colossus/ColossusState";
import { glyphIds } from "../src/components/colossus/glyphAtlas";

describe("the phrase a sign may carry", () => {
  it("quotes the opening sentence rather than summarising it", () => {
    expect(speechTakeaway("The deployment finished. Every check passed."))
      .toBe("The deployment finished");
  });

  // Six is the ask. The seventh word is where a sign stops being read, and the
  // ellipsis is a promise that there is more -- so it only appears when there is.
  it("caps a long sentence at six words and says so", () => {
    expect(speechTakeaway("I have finished evaluating the situation and reached a conclusion"))
      .toBe("I have finished evaluating the situation...");
  });

  it("keeps a short reply whole rather than truncating what already fits", () => {
    expect(speechTakeaway("The deployment finished and every check passed"))
      .toBe("The deployment finished and every check passed");
  });

  // A sixth of the sign is too much to spend on a word carrying nothing.
  it("drops a discourse opener, but never when it is the whole reply", () => {
    expect(speechTakeaway("So the migration is complete.")).toBe("the migration is complete");
    expect(speechTakeaway("No.")).toBe("No");
  });

  it("returns nothing for nothing, rather than an empty sign", () => {
    expect(speechTakeaway("")).toBe("");
    expect(speechTakeaway("   ")).toBe("");
  });

  // A cut at a fixed word count lands wherever it lands. Ending on "the" reads
  // as a sign that broke mid-word rather than one that stopped, so the dangling
  // word goes and the comma with it -- the ellipsis stays, because there IS more.
  it("does not end a truncation on a dangling article or comma", () => {
    expect(speechTakeaway("Yes, the build is green, the tests pass, and it deployed"))
      .toBe("Yes, the build is green...");
    expect(speechTakeaway("I have reviewed the plan and I am satisfied with it"))
      .toBe("I have reviewed the plan...");
  });

  // Only a TRUNCATION is trimmed. A complete short sentence that happens to end
  // on a preposition ends there because that is what it says.
  it("leaves a whole short reply ending however it ends", () => {
    expect(speechTakeaway("It is up to you.")).toBe("It is up to you");
  });
});

describe("the sign", () => {
  // Territory's rule: the display communicates its plot point within seconds of
  // being on camera, and the plot point is what the MACHINE is doing. The
  // quotation is elaboration in the slot the canned clause occupied.
  it("keeps the mode word first and puts the quotation after it", () => {
    const spoken = tickerFor("speaking", "The deployment finished");
    expect(readBack(spoken)).toBe("TRANSMITTING * THE DEPLOYMENT FINISHED * ");
  });

  it("falls back to its own copy when there is nothing to quote", () => {
    expect(readBack(tickerFor("speaking"))).toBe(readBack(tickerFor("speaking", null)));
    expect(readBack(tickerFor("speaking"))).toContain("THIS IS THE VOICE OF WORLD CONTROL");
  });

  // Every other mode is a statement about the machine, so a phrase from a reply
  // has no business under it.
  it("carries a takeaway only while he is speaking", () => {
    expect(clampColossusState({ mode: "speaking", takeaway: "All systems nominal" }).takeaway)
      .toBe("All systems nominal");
    expect(clampColossusState({ mode: "thinking", takeaway: "All systems nominal" }).takeaway)
      .toBeNull();
  });

  // The cap is on the side that would be damaged, not only on the side that is
  // well behaved: this is the boundary a third-party host crosses.
  it("bounds whatever a host hands it", () => {
    const long = "word ".repeat(200);
    expect(clampColossusState({ mode: "speaking", takeaway: long }).takeaway!.length)
      .toBeLessThanOrEqual(80);
    expect(clampColossusState({ mode: "speaking", takeaway: 42 as never }).takeaway).toBeNull();
    expect(clampColossusState({ mode: "speaking", takeaway: "   " }).takeaway).toBeNull();
  });

  it("takes the phrase off the turn input", () => {
    const state = colossusStateFromTurn({
      loading: false,
      hasLiveEvents: false,
      liveEnded: false,
      voiceSpeaking: true,
      voiceLevel: 0.5,
      speechTakeaway: "The decision is made",
    });
    expect(state.takeaway).toBe("The decision is made");
  });

  // A live call delivers audio with no text at all, which is the case the
  // fallback exists for -- not an error.
  it("shows his own copy when the host quotes nothing", () => {
    const state = colossusStateFromTurn({
      loading: false,
      hasLiveEvents: false,
      liveEnded: false,
      voiceSpeaking: true,
      voiceLevel: 0.5,
    });
    expect(state.takeaway).toBeNull();
  });
});

/**
 * The compiled glyph buffer, read back as text.
 *
 * Through the atlas rather than against the input string, because the atlas is
 * what the panel actually draws: a phrase that compiled to the wrong ids would
 * pass any assertion made against the source text and still spell something
 * else on screen.
 */
function readBack(buffer: { glyphs: Int32Array; length: number }): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-,:/+%*";
  const table = new Map(alphabet.split("").map((char) => [glyphIds(char)[0], char]));
  return [...buffer.glyphs.slice(0, buffer.length)]
    .map((id) => table.get(id) ?? "?")
    .join("");
}
