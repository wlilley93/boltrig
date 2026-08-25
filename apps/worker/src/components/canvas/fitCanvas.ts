/** Fit a body's canvas to its host at the device pixel ratio, capped.
 *  Returns the new [w, h] when the size actually changed, else null.
 *  One copy of what was identical twin logic in two renderers. */
export function fitCanvasToHost(
  canvas: HTMLCanvasElement,
  host: HTMLElement,
  maxDevicePixelRatio: number,
  current: readonly [number, number],
): [number, number] | null {
  const dpr = Math.min(window.devicePixelRatio || 1, maxDevicePixelRatio);
  const w = Math.max(1, Math.round(host.clientWidth * dpr));
  const h = Math.max(1, Math.round(host.clientHeight * dpr));
  if (w === current[0] && h === current[1]) return null;
  canvas.width = w;
  canvas.height = h;
  return [w, h];
}
