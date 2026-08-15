import { Component, type ErrorInfo, type ReactNode } from "react";

import { BrandWordmark } from "./BrandWordmark";

export const WORKER_CHUNK_RECOVERY_KEY = "boltrig.worker.chunk-recovery";

type RecoveryStore = Pick<Storage, "getItem" | "removeItem" | "setItem">;

interface WorkerErrorBoundaryProps {
  children: ReactNode;
  recoveryStore?: RecoveryStore;
  reload?: () => void;
}

interface WorkerErrorBoundaryState {
  error: Error | null;
  recovering: boolean;
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error ?? "");
}

export function isRecoverableChunkError(error: unknown): boolean {
  return /(chunkloaderror|loading chunk .+ failed|failed to fetch dynamically imported module|error loading dynamically imported module|importing a module script failed)/i
    .test(errorMessage(error));
}

function recoveryFingerprint(error: unknown): string {
  const message = errorMessage(error).trim();
  return (message || "dynamic-module-load-failure").slice(0, 512);
}

function browserRecoveryStore(): RecoveryStore | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function browserReload(): void {
  window.location.reload();
}

function RecoveryScreen({ error, recovering, reload }: {
  error: Error;
  recovering: boolean;
  reload: () => void;
}) {
  const staleChunk = isRecoverableChunkError(error);
  const title = recovering
    ? "Updating Boltrig…"
    : staleChunk ? "The update didn’t load." : "Boltrig couldn’t open.";
  const detail = recovering
    ? "A newer version is ready. Reloading once to finish the update."
    : "Your work is safe. Reload the app to try again.";

  return (
    <main className="worker-recovery" role="alert">
      <section className="worker-recovery-card">
        <BrandWordmark className="worker-recovery-brand" />
        <h1>{title}</h1>
        <p>{detail}</p>
        <button className="primary-button" onClick={reload} type="button">
          Reload
        </button>
      </section>
    </main>
  );
}

export class WorkerErrorBoundary extends Component<
  WorkerErrorBoundaryProps,
  WorkerErrorBoundaryState
> {
  state: WorkerErrorBoundaryState = { error: null, recovering: false };

  static getDerivedStateFromError(error: Error): WorkerErrorBoundaryState {
    return { error, recovering: isRecoverableChunkError(error) };
  }

  componentDidMount(): void {
    if (this.state.error) return;
    const store = this.props.recoveryStore ?? browserRecoveryStore();
    try {
      store?.removeItem(WORKER_CHUNK_RECOVERY_KEY);
    } catch {
      // Storage can be unavailable in privacy-restricted browser contexts.
    }
  }

  componentDidCatch(error: Error, _info: ErrorInfo): void {
    if (!isRecoverableChunkError(error)) return;
    const store = this.props.recoveryStore ?? browserRecoveryStore();
    const fingerprint = recoveryFingerprint(error);

    try {
      if (!store || store.getItem(WORKER_CHUNK_RECOVERY_KEY) === fingerprint) {
        this.setState({ recovering: false });
        return;
      }
      store.setItem(WORKER_CHUNK_RECOVERY_KEY, fingerprint);
    } catch {
      this.setState({ recovering: false });
      return;
    }

    try {
      (this.props.reload ?? browserReload)();
    } catch {
      this.setState({ recovering: false });
    }
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      <RecoveryScreen
        error={this.state.error}
        recovering={this.state.recovering}
        reload={this.props.reload ?? browserReload}
      />
    );
  }
}
