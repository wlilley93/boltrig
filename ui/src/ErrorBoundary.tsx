// A render-error boundary. Without one, any uncaught throw in a panel - or a
// rejected lazy-chunk import after a redeploy (a stale chunk hash) - white-screens
// the whole console with no recovery. This catches it and shows a recoverable card.

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  // a short label for what failed (e.g. "Boltrig", "this panel")
  label?: string;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // surface to the console; no telemetry sink is wired.
    // eslint-disable-next-line no-console
    console.error("Render error caught by ErrorBoundary:", error, info.componentStack);
  }

  reset = () => {
    this.setState({ error: null });
  };

  reload = () => {
    // a lazy-chunk failure is fixed by a full reload (fresh chunk hashes).
    window.location.reload();
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    const what = this.props.label ?? "Something";
    return (
      <div className="errbnd" role="alert">
        <div className="errbnd__card">
          <div className="errbnd__title">{what} hit an error</div>
          <p className="errbnd__body">
            {error.message || "An unexpected error occurred."} You can try again, or
            reload if the problem persists (this also fixes a stale build after a
            deploy).
          </p>
          <div className="errbnd__actions">
            <button className="btn btn--primary" onClick={this.reset}>
              Try again
            </button>
            <button className="btn" onClick={this.reload}>
              Reload
            </button>
          </div>
        </div>
      </div>
    );
  }
}
