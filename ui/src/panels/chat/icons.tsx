import type { CSSProperties, ReactNode } from "react";

export type IconName =
  | "panel"
  | "search"
  | "plus"
  | "file"
  | "phone"
  | "moon"
  | "sun"
  | "mic"
  | "send"
  | "wave"
  | "x"
  | "chevDown"
  | "chevLeft"
  | "chevRight"
  | "copy"
  | "refresh"
  | "download"
  | "paperclip"
  | "speaker"
  | "pin";

interface IconProps {
  name: IconName;
  size?: number;
  // When true the glyph is drawn with fill=currentColor (e.g. a pinned pin)
  // instead of the default hollow stroke. Only meaningful for icons that have a
  // distinct solid form (currently "pin").
  filled?: boolean;
}

function svgProps(size: number): {
  width: number;
  height: number;
  viewBox: string;
  fill: string;
  stroke: string;
  strokeWidth: number;
  strokeLinecap: "round";
  strokeLinejoin: "round";
  "aria-hidden": boolean;
  style: CSSProperties;
} {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
    style: { display: "block" },
  };
}

const ICON_PATHS: Record<IconName, ReactNode> = {
  panel: (
    <>
      <path d="M4 5h16v14H4z" />
      <path d="M9 5v14" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="6" />
      <path d="m16 16 4 4" />
    </>
  ),
  plus: (
    <>
      <path d="M12 5v14M5 12h14" />
    </>
  ),
  file: (
    <>
      <path d="M7 3h7l4 4v14H7z" />
      <path d="M14 3v5h5" />
    </>
  ),
  phone: (
    <path d="M6.6 4.8 9 4l2.1 4-1.5 1.1c1.1 2.2 2.9 4 5.1 5.1l1.1-1.5 4 2.1-.8 2.4c-.4 1.2-1.6 1.9-2.8 1.6C10.8 17.7 6.3 13.2 5.2 7.8 4.9 6.6 5.5 5.2 6.6 4.8Z" />
  ),
  moon: <path d="M20 15.5A8 8 0 0 1 8.5 4 7 7 0 1 0 20 15.5Z" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </>
  ),
  mic: (
    <>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </>
  ),
  send: (
    <>
      <path d="M12 19V5M6 11l6-6 6 6" />
    </>
  ),
  wave: (
    <>
      <path d="M6 14v-4M10 17V7M14 15V9M18 13v-2" />
    </>
  ),
  x: (
    <>
      <path d="M6 6l12 12M18 6 6 18" />
    </>
  ),
  chevDown: <path d="m7 10 5 5 5-5" />,
  chevLeft: <path d="m15 18-6-6 6-6" />,
  chevRight: <path d="m9 18 6-6-6-6" />,
  copy: (
    <>
      <rect x="8" y="8" width="11" height="11" rx="2" />
      <path d="M5 15V5h10" />
    </>
  ),
  download: (
    <>
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <path d="M7 10l5 5 5-5" />
      <path d="M12 15V3" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 12a8 8 0 0 1-14 5M4 12a8 8 0 0 1 14-5" />
      <path d="M18 3v4h-4M6 21v-4h4" />
    </>
  ),
  paperclip: (
    <path d="M16.5 6.5 8.5 14.5a2.5 2.5 0 0 0 3.5 3.5l8.5-8.5a4.5 4.5 0 0 0-6.36-6.36l-9.5 9.5a6.5 6.5 0 0 0 9.19 9.19l9.25-9.25" />
  ),
  speaker: (
    <>
      <path d="M11 5 6 9H2v6h4l5 4V5z" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7" />
      <path d="M19.5 4.5a10 10 0 0 1 0 15" />
    </>
  ),
  pin: (
    <>
      <path d="M9.5 3.5h5l-.7 4.6 2.4 2.4a.8.8 0 0 1-.6 1.4H8.4a.8.8 0 0 1-.6-1.4l2.4-2.4Z" />
      <path d="M12 12.5V20" />
    </>
  ),
};

export function Icon({ name, size = 18, filled = false }: IconProps): JSX.Element {
  const props = svgProps(size);
  const paths = ICON_PATHS[name] ?? (
    <>
      <path d="M12 4v12" />
      <path d="m7 11 5 5 5-5" />
      <path d="M5 20h14" />
    </>
  );
  return (
    <svg {...props} fill={filled ? "currentColor" : "none"}>
      {paths}
    </svg>
  );
}

export { type IconProps };
