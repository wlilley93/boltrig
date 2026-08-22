// What this deployment calls itself.
//
// Boltrig alone is "Boltrig"; a Boltrig that an Opbox provisioned is "Opbox
// Agents". The kernel decides, from the active addon (see boltrig/branding.py),
// because the runtime already keys its harness, adapter id and consequence
// hint off the same signal and the surface must not be able to disagree with
// it. Baking the name into the bundle is the other option and it is the one
// that has already failed on this estate: a build-time flag nothing passed
// shipped the wrong behaviour in every image and stayed invisible.
//
// THE FLASH IS THE INTERESTING PART. /v1/branding is unauthenticated so the
// sign-in screen can ask, but it is still a round trip, and rendering "Boltrig"
// for 200ms on an Opbox deployment is a visible wrong answer. The last known
// name is therefore cached, so only the very first visit to a given origin can
// show the default. Nothing here is a trust decision - it is a word - so a
// stale or tampered cache costs a wrong label until the fetch lands.
import { client } from "./client";

export const DEFAULT_PRODUCT_NAME = "Boltrig";

const CACHE_KEY = "boltrig.product-name";
// Only names the kernel can actually return. An unrecognised cached value is
// discarded rather than rendered: localStorage is writable by anything sharing
// the origin, and the wordmark is not a place to display arbitrary text.
const KNOWN = new Set([DEFAULT_PRODUCT_NAME, "Opbox Agents"]);

function cached(): string | null {
  try {
    const value = window.localStorage.getItem(CACHE_KEY);
    return value && KNOWN.has(value) ? value : null;
  } catch {
    return null; // private mode, or storage disabled. The default still works.
  }
}

function remember(name: string): void {
  try {
    window.localStorage.setItem(CACHE_KEY, name);
  } catch {
    /* not worth failing a render over */
  }
}

let current = initialProductName();
const listeners = new Set<(name: string) => void>();
let started = false;

/**
 * Ask the kernel what this deployment is called. Called ONCE from the app
 * entry beside bootstrapAppearance/bootstrapCharacter.
 *
 * The fetch lives here rather than in the component that renders the name.
 * A component that does network I/O on mount does it again in every test that
 * renders it - which showed up immediately as a connection error in the
 * wordmark suite - and would do it once per mount in the app. Bootstrap asks;
 * components subscribe.
 */
export function bootstrapProductName(): void {
  if (started) return;
  started = true;
  void resolveProductName().then((name) => {
    if (name === current) return;
    current = name;
    for (const listener of listeners) listener(name);
  });
}

export function currentProductName(): string {
  return current;
}

export function subscribeProductName(listener: (name: string) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

async function resolveProductName(): Promise<string> {
  try {
    const { product_name: name } = await client.branding();
    if (typeof name !== "string" || !KNOWN.has(name)) {
      return cached() ?? DEFAULT_PRODUCT_NAME;
    }
    remember(name);
    return name;
  } catch {
    // Offline, or the kernel is not up yet. The sign-in screen still renders.
    return cached() ?? DEFAULT_PRODUCT_NAME;
  }
}


function initialProductName(): string {
  return cached() ?? DEFAULT_PRODUCT_NAME;
}
