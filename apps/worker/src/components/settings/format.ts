// Shared formatting for the settings family. Money is micro-USD — the kernel's
// own reading (boltrig/kernel/cost.py: "A micro is $0.000001") and the one
// ParityViews and the run drill-down already render; any other currency symbol
// would be an invented exchange rate. Dates render short ("9 Aug") the way the
// design draws them.

// THE LOCALE IS PINNED, and it has to be. `undefined` means "whatever locale
// this machine happens to have", and Intl renders USD differently in each: en-US
// gives "$12.40", en-GB gives "US$12.40". The zero case below returns the
// literal "$0.00", so on any non-US box the same panel disagreed with itself --
//
//     Total so far    $0.00
//     Today           US$12.40 of US$40.00
//
// -- and it looked correct only to whoever ran it in a US locale. Pinning en-US
// makes both halves the same shape everywhere, which is what the surrounding
// comment means by not inventing a second symbol for one currency. shortDate
// pins its locale for the same reason, in the other direction.
const MONEY = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function money(micros: number): string {
  if (!Number.isFinite(micros) || micros <= 0) return "$0.00";
  return MONEY.format(micros / 1_000_000);
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const time = Date.parse(iso);
  if (!Number.isFinite(time)) return "";
  return new Date(time).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}
