// Filled-SVG icon set for canvas nodes (design brief sec 22.3). These are
// geometric solid icons using fill="currentColor" (NOT Lucide stroke icons) so
// they pick up each node kind's colour. ~20-22px at the rendered size.

import type { CSSProperties, SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Svg({ size = 20, children, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

// Lightning bolt (trigger / Start).
function BoltIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path
        fill="currentColor"
        d="M13.5 1.5 4 13.6h6.1L9 22.5l9.6-12.2h-6l.9-8.8Z"
      />
    </Svg>
  );
}

// Agent (person/bot head + shoulders).
function AgentIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="12" cy="8" r="4.2" fill="currentColor" />
      <path
        fill="currentColor"
        d="M3.6 20.4c0-4.2 3.8-6.9 8.4-6.9s8.4 2.7 8.4 6.9a.9.9 0 0 1-.9.9H4.5a.9.9 0 0 1-.9-.9Z"
      />
    </Svg>
  );
}

// End (a square stop / output block).
function EndIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="4.5" y="4.5" width="15" height="15" rx="3" fill="currentColor" />
      <rect x="8.5" y="8.5" width="7" height="7" rx="1.5" fill="#04060D" />
    </Svg>
  );
}

// Branch (IF/ELSE fork).
function BranchIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path
        fill="currentColor"
        d="M10 3v5.2c0 1.7-1 3.2-2.5 3.9L4 13.5v7h3v-4.7l2.1-1c.7-.3 1.3-.8 1.9-1.4.6.6 1.2 1.1 1.9 1.4l2.1 1V20.5h3v-7l-3.5-1.4C13 11.4 12 9.9 12 8.2V3h-2Z"
      />
    </Svg>
  );
}

// Code (chevrons).
function CodeIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path
        fill="currentColor"
        d="M9.2 6.4 3.4 12l5.8 5.6 2-2-3.7-3.6 3.7-3.6-2-2Zm5.6 0-2 2 3.7 3.6-3.7 3.6 2 2L20.6 12l-5.8-5.6Z"
      />
    </Svg>
  );
}

// Loop (circular arrows).
function LoopIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path
        fill="currentColor"
        d="M12 4a8 8 0 0 1 7.3 4.7l1.2-1.2 1.6 1.6-4 4-4-4 1.6-1.6 1.3 1.3A5.5 5.5 0 0 0 7.4 8L5.3 6.9A8 8 0 0 1 12 4Zm0 16a8 8 0 0 1-7.3-4.7l-1.2 1.2-1.6-1.6 4-4 4 4-1.6 1.6-1.3-1.3a5.5 5.5 0 0 0 9.6-2.2l2.1 1.1A8 8 0 0 1 12 20Z"
      />
    </Svg>
  );
}

// Book (knowledge / RAG).
function BookIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path
        fill="currentColor"
        d="M4 4.5C4 3.7 4.7 3 5.5 3H12v16.2H5.5c-.8 0-1.5.7-1.5 1.5V4.5Zm9-1.5h5.5c.8 0 1.5.7 1.5 1.5V21c0-.8-.7-1.5-1.5-1.5H13V3Z"
      />
    </Svg>
  );
}

// Globe (HTTP).
function GlobeIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm-1.4 2.3A8 8 0 0 0 5 7.3c.7-.1 1.9-.2 3.2 0 .6.1 1.4.4 2.4.9v-3.9Zm0 5.7c-1.4-.7-2.5-.9-3.1-1-1-.2-2 0-2.6.1A8 8 0 0 0 4 12c0 1 .2 2 .5 2.9.6-.4 1.6-1 2.8-1.4 1-.4 2.3-.7 3.8-.7V10Zm0 5.6c-1.2 0-2.2.2-3 .5a8 8 0 0 0 4.9 3.6v-4.1Zm2.8 4.1a8 8 0 0 0 4.9-3.6c-.8-.3-1.8-.5-3-.5v4.1Zm0-6.9c1.5 0 2.8.3 3.8.7 1.2.4 2.2 1 2.8 1.4.3-.9.5-1.9.5-2.9a8 8 0 0 0-.9-3.6c-.6-.1-1.6-.3-2.6-.1-.6.1-1.7.3-3.1 1v3.5Zm0-7.6c1-.5 1.8-.8 2.4-.9 1.3-.2 2.5-.1 3.2 0a8 8 0 0 0-5.6-3.3v4.2Z"
        clipRule="evenodd"
      />
    </Svg>
  );
}

// Cylinder (database).
function CylinderIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M12 3c-4.1 0-7.5 1.3-7.5 3v12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6c0-1.7-3.4-3-7.5-3Zm-5 4.6c1.3.7 3 1.1 5 1.1s3.7-.4 5-1.1V9c0 .5-2 1.6-5 1.6S7 9.5 7 9V7.6Zm0 4.4c1.3.7 3 1.1 5 1.1s3.7-.4 5-1.1V18c0 .5-2 1.6-5 1.6S7 18.5 7 18v-6Z"
        clipRule="evenodd"
      />
    </Svg>
  );
}

// Wrench (tool).
function WrenchIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path
        fill="currentColor"
        d="M14.5 3.5a5.5 5.5 0 0 0-5.2 7.3l-5 5a2.1 2.1 0 0 0 3 3l5-5a5.5 5.5 0 0 0 7.2-6.8l-3 3-2.8-.7-.7-2.8 3-3c-.5-.1-1-.2-1.5 0Z"
      />
    </Svg>
  );
}

// Bell (notify).
function BellIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path
        fill="currentColor"
        d="M12 2a6 6 0 0 0-6 6v3.6L4.5 15h15L18 11.6V8a6 6 0 0 0-6-6Zm0 20a3 3 0 0 0 2.8-2H9.2a3 3 0 0 0 2.8 2Z"
      />
    </Svg>
  );
}

// Template (document with lines).
function TemplateIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path
        fill="currentColor"
        d="M5 3h9l5 5v13H5V3Zm9 1.5V9h4.5L14 4.5ZM8 12h8v1.6H8V12Zm0 3.4h8V17H8v-1.6Z"
      />
    </Svg>
  );
}

// Shield (high-consequence badge).
function ShieldGlyph(p: IconProps) {
  return (
    <Svg {...p}>
      <path
        fill="currentColor"
        d="M12 2 4 5v6c0 5 3.4 8.7 8 11 4.6-2.3 8-6 8-11V5l-8-3Z"
      />
    </Svg>
  );
}

const ICONS: Record<string, (p: IconProps) => JSX.Element> = {
  bolt: BoltIcon,
  agent: AgentIcon,
  end: EndIcon,
  branch: BranchIcon,
  code: CodeIcon,
  loop: LoopIcon,
  book: BookIcon,
  globe: GlobeIcon,
  cylinder: CylinderIcon,
  wrench: WrenchIcon,
  bell: BellIcon,
  template: TemplateIcon,
  shield: ShieldGlyph,
};

export interface NodeIconProps {
  name: string;
  size?: number;
  style?: CSSProperties;
}

export function NodeIcon({ name, size, style }: NodeIconProps) {
  const Cmp = ICONS[name] ?? AgentIcon;
  return <Cmp size={size} style={style} />;
}

// Small filled shield used as the high-consequence badge on node cards.
export function ShieldBadge({ size = 11 }: { size?: number }) {
  return <ShieldGlyph size={size} />;
}
