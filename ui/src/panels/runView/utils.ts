export function isNotFound(err: string | null): boolean {
  return !!err && (err.includes("404") || err.toLowerCase().includes("not found"));
}
