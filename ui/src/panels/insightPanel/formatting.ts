// micros are millionths of a currency unit; show a readable amount, raw on hover.
export function money(micros: number): string {
  return (micros / 1_000_000).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

export function whenText(ts: string): string {
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString();
}

export function pct(spent: number, limit: number | null): number | null {
  if (!limit || limit <= 0) return null;
  return Math.min(100, Math.round((spent / limit) * 100));
}
