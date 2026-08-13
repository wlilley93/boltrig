import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import type { ApprovalPosture } from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import {
  localAgentPosture,
  putLocalAgentPosture,
} from "../localAgentClient";
import { navigate } from "../routes";
import "./ApprovalPostureControl.css";

export const APPROVAL_POSTURE_EVENT = "boltrig:approval-posture";

interface PostureOption {
  id: ApprovalPosture;
  label: string;
  shortLabel: string;
  description: string;
}

export type ApprovalRuntime = "cloud" | "local";

export const APPROVAL_POSTURES: PostureOption[] = [
  {
    id: "always_ask",
    label: "Ask for approval",
    shortLabel: "Ask",
    description: "Ask before every delegated agent tool uses an external adapter.",
  },
  {
    id: "risk_based",
    label: "Approve for me",
    shortLabel: "Approve for me",
    description: "Ask only for high-consequence actions and workspace-required approvals.",
  },
  {
    id: "full_access",
    label: "Full access",
    shortLabel: "Full access",
    description: "Use already-granted external tools without asking; hard limits still apply.",
  },
];

const LOCAL_APPROVAL_POSTURES: PostureOption[] = [
  {
    id: "always_ask",
    label: "Ask for approval",
    shortLabel: "Ask",
    description: "Ask before local commands or file changes outside trusted reads.",
  },
  {
    id: "risk_based",
    label: "Approve for me",
    shortLabel: "Approve for me",
    description: "Ask only when the local agent judges an action needs approval.",
  },
  {
    id: "full_access",
    label: "Full access",
    shortLabel: "Full access",
    description: "Unrestricted access to local files, commands and the internet.",
  },
];

function optionsFor(runtime: ApprovalRuntime): PostureOption[] {
  return runtime === "local" ? LOCAL_APPROVAL_POSTURES : APPROVAL_POSTURES;
}

function selectedOption(runtime: ApprovalRuntime, posture: ApprovalPosture | null) {
  return optionsFor(runtime).find((option) => option.id === posture) ?? null;
}

function useApprovalPosture(runtime: ApprovalRuntime) {
  const [posture, setPosture] = useState<ApprovalPosture | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);

  useEffect(() => {
    let active = true;
    const requestGeneration = generation.current;
    const read = runtime === "local"
      ? localAgentPosture()
      : typeof client.approvalPosture === "function"
        ? client.approvalPosture()
        : Promise.reject(new Error("approval_posture_unavailable"));
    void read
      .then((result) => {
        if (active && generation.current === requestGeneration) setPosture(result.posture);
      })
      .catch(() => {
        if (active && generation.current === requestGeneration) {
          setError("Approval posture is unavailable.");
        }
      });
    const sync = (event: Event) => {
      const detail = (event as CustomEvent<{
        runtime: ApprovalRuntime;
        posture: ApprovalPosture;
      }>).detail;
      if (detail?.runtime === runtime
          && optionsFor(runtime).some((option) => option.id === detail.posture)) {
        generation.current += 1;
        setPosture(detail.posture);
      }
    };
    window.addEventListener(APPROVAL_POSTURE_EVENT, sync);
    return () => {
      active = false;
      window.removeEventListener(APPROVAL_POSTURE_EVENT, sync);
    };
  }, [runtime]);

  async function choose(next: ApprovalPosture) {
    if (saving || next === posture) return false;
    generation.current += 1;
    setSaving(true);
    setError("");
    try {
      const result = runtime === "local"
        ? await putLocalAgentPosture(next)
        : typeof client.putApprovalPosture === "function"
          ? await client.putApprovalPosture({
              posture: next,
              ...(next === "full_access" ? { confirm: "full_access" as const } : {}),
            })
          : await Promise.reject(new Error("approval_posture_unavailable"));
      generation.current += 1;
      setPosture(result.posture);
      window.dispatchEvent(new CustomEvent(APPROVAL_POSTURE_EVENT, {
        detail: { runtime, posture: result.posture },
      }));
      return true;
    } catch {
      setError(runtime === "local"
        ? "This computer did not change the local approval posture."
        : "The kernel did not change the cloud approval posture.");
      return false;
    } finally {
      setSaving(false);
    }
  }

  return { choose, error, posture, saving };
}

function PostureRows({
  compact,
  onChoose,
  posture,
  runtime,
  saving,
}: {
  compact: boolean;
  onChoose(posture: ApprovalPosture): void;
  posture: ApprovalPosture | null;
  runtime: ApprovalRuntime;
  saving: boolean;
}) {
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"].includes(event.key)) return;
    const rows = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]:not(:disabled)'),
    );
    if (rows.length === 0) return;
    const active = rows.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === "Home"
      ? 0
      : event.key === "End"
        ? rows.length - 1
        : event.key === "ArrowDown" || event.key === "ArrowRight"
          ? (Math.max(active, 0) + 1) % rows.length
          : (active <= 0 ? rows.length : active) - 1;
    const row = rows[next];
    const nextPosture = row?.dataset.posture as ApprovalPosture | undefined;
    if (!row || !nextPosture) return;
    event.preventDefault();
    row.focus();
    onChoose(nextPosture);
  }

  return <div
    aria-label="Agent tool approval posture"
    className="approval-posture-options"
    onKeyDown={onKeyDown}
    role="radiogroup"
  >
    {optionsFor(runtime).map((option, index) => (
      <button
        aria-checked={posture === option.id}
        className="approval-posture-option"
        data-posture={option.id}
        disabled={saving}
        key={option.id}
        onClick={() => onChoose(option.id)}
        role="radio"
        tabIndex={posture === option.id || (posture === null && index === 0) ? 0 : -1}
        type="button"
      >
        <span aria-hidden className="approval-posture-icon">
          {option.id === "always_ask" ? "✋" : option.id === "risk_based" ? "◈" : "!"}
        </span>
        <span className="approval-posture-copy">
          <span>{option.label}</span>
          <small>{option.description}</small>
          {!compact && option.id === "full_access" && (
            <small className="approval-posture-boundary">
              {runtime === "local"
                ? "This applies only to this signed desktop app. It is separate from cloud tool grants."
                : "Grants, workspace blocks, control changes, budgets and audit still apply."}
            </small>
          )}
        </span>
        {posture === option.id && <span aria-hidden className="approval-posture-check">✓</span>}
      </button>
    ))}
  </div>;
}

export function ApprovalPostureSettings({
  runtime = "cloud",
}: {
  runtime?: ApprovalRuntime;
}) {
  const state = useApprovalPosture(runtime);
  return (
    <div className="approval-posture-settings">
      <PostureRows
        compact={false}
        onChoose={(posture) => void state.choose(posture)}
        posture={state.posture}
        runtime={runtime}
        saving={state.saving}
      />
      {state.error && <p className="approval-posture-error" role="alert">{state.error}</p>}
    </div>
  );
}

export function ApprovalPostureMenu({
  disabled = false,
  runtime = "cloud",
}: {
  disabled?: boolean;
  runtime?: ApprovalRuntime;
}) {
  const state = useApprovalPosture(runtime);
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const selected = selectedOption(runtime, state.posture);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => {
      root.current?.querySelector<HTMLButtonElement>('[role="radio"][tabindex="0"]')?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      root.current?.querySelector<HTMLButtonElement>(".composer-posture")?.focus();
    }
  }

  return (
    <div className="approval-posture-menu" onKeyDown={onKeyDown} ref={root}>
      <button
        aria-expanded={open}
        aria-haspopup="dialog"
        className="composer-posture"
        data-posture={state.posture ?? undefined}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        title={runtime === "local"
          ? "Choose how local files, commands and network access are approved"
          : "Choose how delegated cloud tools are approved"}
        type="button"
      >
        <span aria-hidden />
        {selected?.shortLabel ?? "Policy"}
      </button>
      {open && (
        <div aria-label="Agent tool approvals" className="approval-posture-popover" role="dialog">
          <div className="approval-posture-head">
            <span>{runtime === "local"
              ? "How should local agent actions be approved?"
              : "How should cloud agent actions be approved?"}</span>
            <a
              href="/settings/autonomy"
              onClick={(event) => {
                event.preventDefault();
                navigate("settings", "autonomy");
                setOpen(false);
              }}
            >Learn more</a>
          </div>
          <PostureRows
            compact
            onChoose={(posture) => {
              void state.choose(posture).then((changed) => { if (changed) setOpen(false); });
            }}
            posture={state.posture}
            runtime={runtime}
            saving={state.saving}
          />
          {state.error && <p className="approval-posture-error" role="alert">{state.error}</p>}
        </div>
      )}
    </div>
  );
}
