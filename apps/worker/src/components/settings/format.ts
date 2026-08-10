// Shared formatting for the settings family. Money is micro-USD — the kernel's
// own reading (boltrig/kernel/cost.py: "A micro is $0.000001") and the one
// ParityViews and the run drill-down already render; any other currency symbol
// would be an invented exchange rate. Dates render short ("9 Aug") the way the
// design draws them.

export function money(micros: number): string {
  if (!Number.isFinite(micros) || micros <= 0) return "$0.00";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(micros / 1_000_000);
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const time = Date.parse(iso);
  if (!Number.isFinite(time)) return "";
  return new Date(time).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}
