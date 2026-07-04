// Shared value/term shapes used across the dreamy-UX primitives and the
// panels that consume them.

export interface Option {
  value: string;
  label: string;
  hint?: string;
}

export interface Term {
  label: string;
  tip: string;
  cls: string; // a .badge--* modifier for colour
}
