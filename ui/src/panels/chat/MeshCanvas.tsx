import { useEffect, useRef } from "react";
import { motionOff } from "@/deck/types";

interface MeshCanvasProps {
  active: boolean;
}

const COLOR_TOKENS = [
  "--color-accent",
  "--color-accent-2",
  "--color-node-agent",
  "--color-node-service",
  "--color-ok",
  "--color-border-strong",
  "--color-text-muted",
];

type Rgb = [number, number, number];

function parseColor(value: string): Rgb | null {
  const hex = value.trim().match(/^#([0-9a-f]{6})$/i)?.[1];
  if (hex) {
    return [
      Number.parseInt(hex.slice(0, 2), 16),
      Number.parseInt(hex.slice(2, 4), 16),
      Number.parseInt(hex.slice(4, 6), 16),
    ];
  }
  const channels = value.match(/[\d.]+/g)?.slice(0, 3).map(Number);
  return channels?.length === 3 ? channels as Rgb : null;
}

function resolveToken(name: string): Rgb | null {
  const probe = document.createElement("span");
  probe.style.color = `var(${name})`;
  probe.hidden = true;
  document.body.appendChild(probe);
  const value = getComputedStyle(probe).color;
  probe.remove();
  return parseColor(value);
}

export function MeshCanvas({ active }: MeshCanvasProps): JSX.Element {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (!active) return;
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const colors = COLOR_TOKENS.map(resolveToken).filter((color): color is Rgb => color !== null);
    if (colors.length === 0) return;

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
      colors.forEach((c, i) => {
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
    };

    if (motionOff()) {
      draw();
      return;
    }

    const loop = () => {
      draw();
      raf = window.requestAnimationFrame(loop);
    };
    raf = window.requestAnimationFrame(loop);
    return () => window.cancelAnimationFrame(raf);
  }, [active]);

  return <canvas ref={ref} className="chat-mesh" aria-hidden="true" />;
}

export { type MeshCanvasProps };
