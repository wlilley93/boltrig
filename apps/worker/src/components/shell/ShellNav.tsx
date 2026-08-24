import type { WorkerRoute } from "../../routes";
import { CompanionSwitcher } from "./CompanionSwitcher";
import { ShellIcon, type ShellIconName } from "./ShellIcon";

const primary: Array<{
  route: WorkerRoute;
  label: string;
  icon: ShellIconName;
  shortcut?: string;
  title?: string;
}> = [
  {
    route: "chat",
    label: "New chat",
    icon: "compose",
    shortcut: "⌘N",
    title: "Start something new. Anything running carries on",
  },
  // Agents, Plugins, Browser and Routines were consoles over the kernel; a
  // Hermes cell has none of it, so the rows went with the routes rather than
  // becoming four entries that lead to "unavailable".
];

interface ShellNavProps {
  route: WorkerRoute;
  onRoute(route: WorkerRoute): void;
  onCommandPalette?(): void;
}

/** The stable top-level shell hierarchy. Conversation history is rendered separately. */
export function ShellNav({ route, onRoute, onCommandPalette }: ShellNavProps) {
  return (
    <>
      <div className="side-top">
        <CompanionSwitcher route={route} />
        {onCommandPalette && (
          <button
            aria-label="Open command palette"
            className="side-icon-button"
            onClick={onCommandPalette}
            title="Search everything (Ctrl or Command K)"
            type="button"
          >
            <svg aria-hidden fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 24 24" width="16">
              <circle cx="11" cy="11" r="7" />
              <line x1="16.5" x2="21" y1="16.5" y2="21" />
            </svg>
          </button>
        )}
      </div>

      <nav aria-label="Primary" className="side-nav">
        {primary.map((item) => (
          <button
            aria-current={route === item.route ? "page" : undefined}
            aria-label={item.label}
            className={route === item.route ? "nav-row active" : "nav-row"}
            key={item.route}
            onClick={() => onRoute(item.route)}
            title={item.title}
            type="button"
          >
            <span className="nav-icon"><ShellIcon name={item.icon} /></span>
            <span>{item.label}</span>
            {item.shortcut && <span className="nav-key">{item.shortcut}</span>}
          </button>
        ))}
      </nav>
    </>
  );
}
