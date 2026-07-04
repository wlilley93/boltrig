import { useEffect, useRef } from "react";

interface MeshCanvasProps {
  active: boolean;
}

const COLORS: Array<[number, number, number]> = [
  [61, 211, 240],
  [30, 180, 220],
  [94, 105, 221],
  [124, 139, 255],
  [63, 185, 132],
  [61, 240, 200],
  [30, 46, 70],
];

export function MeshCanvas({ active }: MeshCanvasProps): JSX.Element {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (!active) return;
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let frame = 0;
    let raf = 0;

    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      const w = Math.max(1, Math.floor(rect.width * 0.5));
      const h = Math.max(1, Math.floor(rect.height * 0.5));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
      ctx.clearRect(0, 0, w, h);
      COLORS.forEach((c, i) => {
        const t = frame * 0.002 + i * 1.7;
        const x = w * (0.25 + 0.5 * ((Math.sin(t) + 1) / 2));
        const y = h * (0.22 + 0.56 * ((Math.cos(t * 0.83) + 1) / 2));
        const r = w * (0.18 + 0.05 * (i % 3));
        const g = ctx.createRadialGradient(x, y, 0, x, y, r);
        g.addColorStop(0, `rgba(${c[0]},${c[1]},${c[2]},0.40)`);
        g.addColorStop(1, `rgba(${c[0]},${c[1]},${c[2]},0)`);
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, w, h);
      });
      frame += 1;
      raf = window.requestAnimationFrame(draw);
    };

    raf = window.requestAnimationFrame(draw);
    return () => window.cancelAnimationFrame(raf);
  }, [active]);

  return <canvas ref={ref} className="chat-mesh" aria-hidden="true" />;
}

export { type MeshCanvasProps };
