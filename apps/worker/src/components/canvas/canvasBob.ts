/** Bob the whole canvas on a sine: one transform moves a procedural body and
 *  its baked layer together, at no shader cost. No trails — a procedural
 *  body is not a texture to ghost-tap — so the setting is the bob. */
export function applyCanvasBob(
  canvas: HTMLCanvasElement,
  bounce: readonly number[],
  t: number,
  reducedMotion: boolean,
): void {
  const bob = bounce[0] > 0.0001 && !reducedMotion
    ? Math.sin(2 * Math.PI * bounce[1] * t) * bounce[0] * canvas.clientHeight
    : 0;
  const lift = bob === 0 ? "" : `translateY(${(-bob).toFixed(2)}px)`;
  if (canvas.style.transform !== lift) canvas.style.transform = lift;
}
