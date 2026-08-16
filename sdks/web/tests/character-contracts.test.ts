import assert from "node:assert/strict";
import { test } from "node:test";

import {
  type Character,
  characterFor,
  characterRegistryRevision,
  isCharacterId,
  listCharacters,
  registerCharacter,
  subscribeCharacters,
} from "../src/index.js";

test("character registration validates ids, labels, duplicates, and subscriptions", () => {
  const before = characterRegistryRevision();
  let notifications = 0;
  const unsubscribe = subscribeCharacters(() => { notifications += 1; });

  registerCharacter({
    id: "sdk-contract-character",
    name: "SDK Contract Character",
    readsPhenotype: false,
    blurb: "A bounded character used by the SDK contract test.",
    render: () => null,
  });

  assert.equal(characterRegistryRevision(), before + 1);
  assert.equal(notifications, 1);
  assert.equal(characterFor("sdk-contract-character")?.name, "SDK Contract Character");
  assert.equal(listCharacters().some(({ id }) => id === "sdk-contract-character"), true);
  assert.throws(() => registerCharacter({
    id: "sdk-contract-character",
    name: "Another Name",
    readsPhenotype: false,
    blurb: "Duplicate id.",
    render: () => null,
  }), /already registered/);
  assert.throws(() => registerCharacter({
    id: "sdk-contract-character-two",
    name: "sdk contract character",
    readsPhenotype: false,
    blurb: "Duplicate display name.",
    render: () => null,
  }), /name is already registered/);

  unsubscribe();
});

test("the registry and persisted setting share one character id grammar", () => {
  assert.equal(isCharacterId("familiar"), true);
  assert.equal(isCharacterId("clip-character-2"), true);
  for (const invalid of ["Maya", "maya_v2", " maya", "a".repeat(65), ""]) {
    assert.equal(isCharacterId(invalid), false);
    assert.throws(() => registerCharacter({
      id: invalid,
      name: `Invalid ${invalid || "empty"}`,
      readsPhenotype: false,
      blurb: "Must not enter the registry.",
      render: () => null,
    }), /character id/);
  }
});

test("registration snapshots plugin metadata instead of retaining a mutable alias", () => {
  const plugin: Character<unknown> = {
    id: "mutable-plugin-input",
    name: "Stable Plugin Label",
    readsPhenotype: false,
    blurb: "The registry must retain exactly the metadata it validated.",
    render: () => null,
  };
  registerCharacter(plugin);

  plugin.id = "changed-after-registration";
  plugin.name = "Changed after registration";
  plugin.render = () => "different output";

  const registered = characterFor("mutable-plugin-input");
  assert.equal(registered?.id, "mutable-plugin-input");
  assert.equal(registered?.name, "Stable Plugin Label");
  assert.equal(registered?.render({
    budgets: null,
    input: {
      loading: false,
      hasLiveEvents: false,
      liveEnded: false,
      voiceSpeaking: false,
      voiceLevel: 0,
    },
    mode: "conversation",
    phenotype: null,
    sensing: {},
  }), null);
  assert.equal(Object.isFrozen(registered), true);
});

test("a broken subscriber cannot turn a committed registration into an apparent failure", () => {
  let healthyNotifications = 0;
  const stopBroken = subscribeCharacters(() => { throw new Error("broken host"); });
  const stopHealthy = subscribeCharacters(() => { healthyNotifications += 1; });

  assert.doesNotThrow(() => registerCharacter({
    id: "subscriber-isolation-character",
    name: "Subscriber Isolation Character",
    readsPhenotype: false,
    blurb: "A registry contract used to prove notification isolation.",
    render: () => null,
  }));
  assert.equal(characterFor("subscriber-isolation-character")?.name,
    "Subscriber Isolation Character");
  assert.equal(healthyNotifications, 1);

  stopBroken();
  stopHealthy();
});
