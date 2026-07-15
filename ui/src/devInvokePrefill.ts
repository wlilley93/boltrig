export interface DevInvokePrefill {
  noun: string;
  verb: string;
}

let pending: DevInvokePrefill | null = null;
const listeners = new Set<() => void>();

export function setDevInvokePrefill(value: DevInvokePrefill) {
  pending = value;
  for (const listener of listeners) listener();
}

export function peekDevInvokePrefill(): DevInvokePrefill | null {
  return pending;
}

export function consumeDevInvokePrefill(value: DevInvokePrefill) {
  if (pending?.noun === value.noun && pending.verb === value.verb) pending = null;
}

export function onDevInvokePrefill(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
