// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  archiveNoun: vi.fn(),
  archiveSkill: vi.fn(),
  archiveVerb: vi.fn(),
  invokeApprovalState: vi.fn(),
  noun: vi.fn(),
  nouns: vi.fn(),
  restoreNoun: vi.fn(),
  restoreSkill: vi.fn(),
  restoreVerb: vi.fn(),
  skill: vi.fn(),
  skills: vi.fn(),
  setBinding: vi.fn(),
  upsertNoun: vi.fn(),
  upsertSkill: vi.fn(),
  upsertVerb: vi.fn(),
  verb: vi.fn(),
  verbs: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { RegistryBuild } from "../src/components/build/RegistryBuild";
import { SkillsBuild } from "../src/components/build/SkillsBuild";

const activeNoun = {
  id: "ticket",
  description: "Tickets",
  schema: {},
  is_active: true,
  status: "active" as const,
};
const archivedNoun = {
  id: "invoice",
  description: "Invoices",
  schema: {},
  is_active: false,
  status: "archived" as const,
};
const archivedVerb = {
  id: "ticket.read",
  noun_id: "ticket",
  input_schema: {},
  output_schema: {},
  description: "Read ticket",
  consequence: "low" as const,
  degraded_mode: null,
  identity_mode: "service-principal" as const,
  idempotency_mode: "cacheable" as const,
  is_active: false,
  status: "archived" as const,
  noun_status: "active" as const,
  binding: {
    target_type: "adapter" as const,
    target_ref: "memory-tickets",
    rate_limit: null,
  },
};
const activeVerb = {
  ...archivedVerb,
  is_active: true,
  status: "active" as const,
};
const archivedSkill = {
  id: "records-review",
  version: "1.0.0",
  extends: null,
  tool_grants: ["ticket.read"],
  locale: "en",
  is_active: false,
  status: "archived" as const,
};

beforeEach(() => {
  api.nouns.mockResolvedValue({ nouns: [activeNoun, archivedNoun] });
  api.verbs.mockResolvedValue({ verbs: [archivedVerb] });
  api.noun.mockResolvedValue({ noun: activeNoun });
  api.verb.mockResolvedValue({
    verb: {
      ...archivedVerb,
      binding: undefined,
    },
    binding: archivedVerb.binding,
  });
  api.restoreNoun.mockResolvedValue({
    status: "pending_human",
    hitl_request_id: "approval/noun",
  });
  api.restoreVerb.mockResolvedValue({
    status: "pending_human",
    hitl_request_id: "approval/verb",
  });
  api.skills.mockResolvedValue({ skills: [archivedSkill] });
  api.skill.mockResolvedValue({
    skill: {
      ...archivedSkill,
      prompt_fragment: "Review records.",
      context_requirements: {},
      description: "Record review",
    },
  });
  api.restoreSkill.mockResolvedValue({
    status: "pending_human",
    hitl_request_id: "approval/skill",
  });
  api.invokeApprovalState.mockResolvedValue({ status: "approved" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Worker authored-definition lifecycle", () => {
  it("keeps archived nouns and verbs visible with restore-only controls", async () => {
    render(<RegistryBuild />);

    fireEvent.click(await screen.findByText("invoice"));
    fireEvent.click(await screen.findByRole("button", { name: "Restore noun" }));
    await waitFor(() => expect(api.restoreNoun).toHaveBeenCalledWith("invoice"));
    expect(await screen.findByText(/Noun restore is waiting for human approval/)).toBeTruthy();

    fireEvent.click(screen.getByText("ticket.read"));
    fireEvent.click(await screen.findByRole("button", { name: "Restore verb" }));
    await waitFor(() => expect(api.restoreVerb).toHaveBeenCalledWith("ticket.read"));
    expect(await screen.findByText(/Verb restore is waiting for human approval/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save binding" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Restore the verb and its noun before changing this binding/)).toBeTruthy();
  });

  it("keeps archived skills editable but disables selection until restore", async () => {
    render(<SkillsBuild />);

    fireEvent.click(await screen.findByText("records-review"));
    const restore = await screen.findByRole("button", { name: "Restore skill" });
    expect((screen.getByRole("button", { name: "Test spawn" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Archived skills remain editable but cannot be selected/)).toBeTruthy();

    fireEvent.click(restore);
    await waitFor(() => expect(api.restoreSkill).toHaveBeenCalledWith("records-review"));
    expect(await screen.findByText(/Skill restore is waiting for human approval/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("Skill restore changed")).toBeTruthy();
  });

  it("continues exact noun and verb lifecycle routes after approval", async () => {
    api.restoreNoun
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval/noun-exact",
      })
      .mockResolvedValueOnce({ status: "ok", definition_status: "active" });
    api.restoreVerb
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval/verb-exact",
      })
      .mockResolvedValueOnce({ status: "ok", definition_status: "active" });

    render(<RegistryBuild />);
    fireEvent.click(await screen.findByText("invoice"));
    fireEvent.click(await screen.findByRole("button", { name: "Restore noun" }));
    await screen.findByText("Noun restore is waiting for approval");
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.restoreNoun).toHaveBeenNthCalledWith(
      2,
      "invoice",
      "approval/noun-exact",
    ));

    fireEvent.click(screen.getByText("ticket.read"));
    fireEvent.click(await screen.findByRole("button", { name: "Restore verb" }));
    await screen.findByText("Verb restore is waiting for approval");
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.restoreVerb).toHaveBeenNthCalledWith(
      2,
      "ticket.read",
      "approval/verb-exact",
    ));
  });

  it("continues exact noun upsert inputs and invalidates them on edit", async () => {
    api.upsertNoun
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval/noun-upsert",
      })
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval/noun-upsert",
      })
      .mockResolvedValueOnce({ status: "ok" });

    render(<RegistryBuild />);
    await screen.findByText("invoice");
    fireEvent.change(screen.getByLabelText("Identifier"), {
      target: { value: "project" },
    });
    fireEvent.change(screen.getAllByLabelText("Description")[0], {
      target: { value: "Project record" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save noun" }));
    await screen.findByText("Noun definition change is waiting for approval");
    const firstBody = api.upsertNoun.mock.calls[0][0];

    fireEvent.change(screen.getAllByLabelText("Description")[0], {
      target: { value: "Changed after review" },
    });
    expect(await screen.findByText("Noun definition change changed")).toBeTruthy();
    expect(api.upsertNoun).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getAllByLabelText("Description")[0], {
      target: { value: "Project record" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save noun" }));
    await screen.findByText("Noun definition change is waiting for approval");
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.upsertNoun).toHaveBeenLastCalledWith(
      firstBody,
      "approval/noun-upsert",
    ));
  });

  it("continues exact verb upsert and binding SDK methods", async () => {
    api.verbs.mockResolvedValue({ verbs: [activeVerb] });
    api.verb.mockResolvedValue({
      verb: { ...activeVerb, binding: undefined },
      binding: activeVerb.binding,
    });
    api.upsertVerb
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval/verb-upsert",
      })
      .mockResolvedValueOnce({ status: "ok" });
    api.setBinding
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval/binding",
      })
      .mockResolvedValueOnce({ status: "ok" });

    render(<RegistryBuild />);
    fireEvent.change((await screen.findAllByLabelText("Verb identifier"))[0], {
      target: { value: "ticket.search" },
    });
    fireEvent.change(screen.getByLabelText("Noun identifier"), {
      target: { value: "ticket" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save verb" }));
    await screen.findByText("Verb definition change is waiting for approval");
    const verbBody = api.upsertVerb.mock.calls[0][0];
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.upsertVerb).toHaveBeenLastCalledWith(
      verbBody,
      "approval/verb-upsert",
    ));

    fireEvent.click(screen.getByText("ticket.read"));
    fireEvent.change(await screen.findByLabelText("Registered target"), {
      target: { value: "approved-target" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save binding" }));
    await screen.findByText("Verb binding change is waiting for approval");
    const bindingBody = api.setBinding.mock.calls[0][1];
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.setBinding).toHaveBeenLastCalledWith(
      "ticket.read",
      bindingBody,
      "approval/binding",
    ));
  });

  it("continues exact skill upsert and lifecycle methods", async () => {
    api.upsertSkill
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval/skill-upsert",
      })
      .mockResolvedValueOnce({ status: "ok" });
    api.restoreSkill
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval/skill-restore",
      })
      .mockResolvedValueOnce({ status: "ok", definition_status: "active" });

    render(<SkillsBuild />);
    await screen.findByText("records-review");
    fireEvent.change(screen.getByLabelText("Identifier"), {
      target: { value: "research" },
    });
    fireEvent.change(screen.getByLabelText("Prompt fragment"), {
      target: { value: "Research carefully." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save skill" }));
    await screen.findByText("Skill definition change is waiting for approval");
    const skillBody = api.upsertSkill.mock.calls[0][0];
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.upsertSkill).toHaveBeenLastCalledWith(
      skillBody,
      "approval/skill-upsert",
    ));

    fireEvent.click(screen.getByText("records-review"));
    fireEvent.click(await screen.findByRole("button", { name: "Restore skill" }));
    await screen.findByText("Skill restore is waiting for approval");
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));
    await waitFor(() => expect(api.restoreSkill).toHaveBeenLastCalledWith(
      "records-review",
      "approval/skill-restore",
    ));
  });

  it("refreshes canonical registry state without replaying consumed approval", async () => {
    api.invokeApprovalState.mockResolvedValue({ status: "consumed" });

    render(<RegistryBuild />);
    fireEvent.click(await screen.findByText("invoice"));
    fireEvent.click(await screen.findByRole("button", { name: "Restore noun" }));
    await screen.findByText("Noun restore is waiting for approval");
    fireEvent.click(screen.getByRole("button", {
      name: "Check approval and apply exact change",
    }));

    expect(await screen.findByText(
      "Noun restore approval was already consumed",
    )).toBeTruthy();
    await waitFor(() => expect(api.nouns).toHaveBeenCalledTimes(2));
    expect(api.restoreNoun).toHaveBeenCalledTimes(1);
  });
});
