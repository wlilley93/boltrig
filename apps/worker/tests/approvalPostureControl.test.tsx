// @vitest-environment happy-dom

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  approvalPosture: vi.fn(),
  putApprovalPosture: vi.fn(),
}));
const local = vi.hoisted(() => ({
  localAgentPosture: vi.fn(),
  putLocalAgentPosture: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/localAgentClient", () => local);

import {
  ApprovalPostureMenu,
  ApprovalPostureSettings,
} from "../src/components/ApprovalPostureControl";

const enforcement = {
  applies_to: "delegated_agent_adapter_calls" as const,
  workspace_blocking_verbs_remain: true as const,
  control_plane_approvals_remain: true as const,
  direct_human_consequence_gate_remains: true as const,
  authority_is_never_widened: true as const,
};
const workerCss = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../src/styles.css"),
  "utf8",
);

beforeEach(() => {
  api.approvalPosture.mockResolvedValue({
    posture: "risk_based",
    source: "safe_default",
    enforcement,
  });
  api.putApprovalPosture.mockImplementation(async ({ posture }) => ({
    status: "ok",
    posture,
    source: "user_override",
    enforcement,
  }));
  local.localAgentPosture.mockResolvedValue({ posture: "always_ask" });
  local.putLocalAgentPosture.mockImplementation(async (posture) => ({ posture }));
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("agent tool approval posture", () => {
  it("shows the kernel posture in the composer and sends exact full-access consent", async () => {
    render(<ApprovalPostureMenu />);

    const trigger = await screen.findByRole("button", { name: "Approve for me" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(trigger);

    expect(screen.getByRole("dialog", { name: "Agent tool approvals" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: /Ask for approval/ })).toBeTruthy();
    const full = screen.getByRole("radio", { name: /Full access/ });
    fireEvent.click(full);

    await waitFor(() => {
      expect(api.putApprovalPosture).toHaveBeenCalledWith({
        posture: "full_access",
        confirm: "full_access",
      });
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Agent tool approvals" })).toBeNull();
    });
    expect(screen.getByRole("button", { name: "Full access" })).toBeTruthy();
  });

  it("implements radio arrow-key selection and retains the hard-limit boundary", async () => {
    render(<ApprovalPostureSettings />);

    const selected = await screen.findByRole("radio", { name: /Approve for me/ });
    expect(selected.getAttribute("aria-checked")).toBe("true");
    selected.focus();
    fireEvent.keyDown(selected, { key: "ArrowDown" });

    await waitFor(() => {
      expect(api.putApprovalPosture).toHaveBeenCalledWith({
        posture: "full_access",
        confirm: "full_access",
      });
    });
    expect(screen.getByText(/Grants, workspace blocks, control changes, budgets and audit still apply/)).toBeTruthy();
  });

  it("keeps local full-access consent separate from the cloud posture", async () => {
    render(<ApprovalPostureMenu runtime="local" />);

    const trigger = await screen.findByRole("button", { name: "Ask" });
    fireEvent.click(trigger);
    expect(screen.getByText("How should local agent actions be approved?")).toBeTruthy();
    expect(screen.getByText("Unrestricted access to local files, commands and the internet."))
      .toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /Full access/ }));

    await waitFor(() => {
      expect(local.putLocalAgentPosture).toHaveBeenCalledWith("full_access");
    });
    expect(api.putApprovalPosture).not.toHaveBeenCalled();
  });

  it("does not offer cloud posture mutations when the current posture is unavailable", async () => {
    api.approvalPosture.mockRejectedValue(new Error("unavailable"));
    render(<ApprovalPostureMenu />);

    fireEvent.click(screen.getByRole("button", { name: "Policy" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Approval posture is unavailable.",
    );
    for (const option of screen.getAllByRole("radio")) {
      expect(option.hasAttribute("disabled")).toBe(true);
      fireEvent.click(option);
    }
    expect(api.putApprovalPosture).not.toHaveBeenCalled();
  });

  it("does not let a late initial read overwrite a confirmed change", async () => {
    let resolveRead!: (value: unknown) => void;
    api.approvalPosture.mockReturnValue(new Promise((resolve) => { resolveRead = resolve; }));
    render(<ApprovalPostureSettings />);

    fireEvent.click(screen.getByRole("radio", { name: /Full access/ }));
    await waitFor(() => {
      expect(screen.getByRole("radio", { name: /Full access/ }).getAttribute("aria-checked"))
        .toBe("true");
    });
    await act(async () => {
      resolveRead({ posture: "risk_based", source: "safe_default", enforcement });
      await Promise.resolve();
    });
    expect(screen.getByRole("radio", { name: /Full access/ }).getAttribute("aria-checked"))
      .toBe("true");
  });

  it("keeps the composer frame open so the menu is not clipped", () => {
    expect(workerCss).toMatch(/\.composer-frame\s*\{[\s\S]*?overflow:\s*visible;/);
  });
});
