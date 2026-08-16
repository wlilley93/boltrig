import { useState } from "react";

import { appliedTheme, toggleTheme } from "../../theme";

export function ThemeToggle() {
  const [theme, setTheme] = useState(appliedTheme);
  return (
    <button
      aria-label="Toggle theme"
      className="icon-button theme-toggle"
      onClick={() => setTheme(toggleTheme())}
      title={theme === "dark" ? "Switch to light" : "Switch to dark"}
      type="button"
    >
      {theme === "dark" ? (
        <svg aria-hidden fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" viewBox="0 0 24 24" width="15">
          <path d="M12 7.6a4.4 4.4 0 1 1 0 8.8 4.4 4.4 0 0 1 0-8.8z" />
          <path d="M12 2v2.2M12 19.8V22M4.3 4.3l1.6 1.6M18.1 18.1l1.6 1.6M2 12h2.2M19.8 12H22M4.3 19.7l1.6-1.6M18.1 5.9l1.6-1.6" />
        </svg>
      ) : (
        <svg aria-hidden fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" viewBox="0 0 24 24" width="15">
          <path d="M20 14.5A8.2 8.2 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />
        </svg>
      )}
    </button>
  );
}
