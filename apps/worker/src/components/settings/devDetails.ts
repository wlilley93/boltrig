import { useSyncExternalStore } from "react";

import { client } from "../../client";

// The one "Developer details" switch, persisted in the per-user settings blob
// (client.meSettings / putMeSettings) under this key. The row-control kit
// gates every monospace tech chip on it, so identifiers appear everywhere at
// once or nowhere at all — the design's app.tech behaviour, backed by a real
// stored value rather than component-local state.
const KEY = "developer_details";

let value = false;
let loaded = false;
let loading = false;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function load() {
  if (loaded || loading) return;
  // The SDK can be partially stubbed (tests, degraded builds); missing
  // methods mean the preference simply stays off rather than crashing a row.
  if (typeof client.meSettings !== "function") {
    loaded = true;
    return;
  }
  loading = true;
  void client.meSettings()
    .then((result) => {
      value = result.settings?.[KEY] === true;
    })
    .catch(() => {
      // Unreadable settings leave the chips hidden — the quiet default.
    })
    .finally(() => {
      loaded = true;
      loading = false;
      emit();
    });
}

/** Whether tech identifiers should be shown, from the persisted settings blob. */
export function useDeveloperDetails(): boolean {
  return useSyncExternalStore(
    (callback) => {
      listeners.add(callback);
      load();
      return () => listeners.delete(callback);
    },
    () => value,
  );
}

/**
 * Persist the preference. Optimistic locally, rolled back if the kernel
 * refuses the write, so the switch never claims a state that was not stored.
 */
export async function setDeveloperDetails(on: boolean): Promise<boolean> {
  const previous = value;
  value = on;
  emit();
  if (typeof client.putMeSettings !== "function") {
    value = previous;
    emit();
    return false;
  }
  try {
    const result = await client.putMeSettings({ key: KEY, value: on });
    if (result.status !== "ok") {
      value = previous;
      emit();
      return false;
    }
    return true;
  } catch {
    value = previous;
    emit();
    return false;
  }
}
