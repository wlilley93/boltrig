// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  answerQuestion: vi.fn(),
  hitl: vi.fn(),
  hitlPolicy: vi.fn(),
  respondHitl: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { InboxQueue } from "../src/components/InboxHitl";
import { LiveQuestionCard } from "../src/components/LiveQuestionCard";

const requests = [
  {
    id: "approval-a",
    type: "approval",
    urgency: "high",
    question: "Approve the transfer?",
    verb: "finance.transfer",
    run_id: "run/a",
    work_item_id: "work-a",
    inputs: { amount: 42, currency: "GBP" },
    context: { policy: "four-eyes" },
  },
  {
    id: "question-a",
    type: "question",
    question: "Which signed copy?",
    options: ["Latest", "Original"],
    run_id: "run-question",
    secure: false,
  },
  {
    id: "clarification-a",
    type: "clarification",
    question: "Clarify the intended audience",
  },
  {
    id: "escalation-a",
    type: "escalation",
    question: "Choose an escalation owner",
    options: ["Legal", "Finance"],
  },
];

beforeEach(() => {
  api.hitl.mockResolvedValue({ requests });
  api.hitlPolicy.mockResolvedValue({
    policy: {
      state: "configured",
      source: "process_start_manifest",
      generation: "approval-policy-generation",
      blocking_verbs: ["device.write", "finance.transfer"],
      approval_timeout_seconds: 900,
      routing: {
        primary_channel: "slack",
        notify_via: ["slack"],
        escalation_chain: ["owner"],
        serving_state: "inactive_no_consumer",
      },
      changes_apply_at: "process_restart",
    },
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Worker human-decision Inbox", () => {
  it("shows effective blocking policy without claiming escalation delivery", async () => {
    render(<InboxQueue />);

    expect(await screen.findByText("Approval policy")).toBeTruthy();
    expect(screen.getByText(/2 explicitly blocking verbs · timeout 900 seconds/)).toBeTruthy();
    expect(screen.getByText("device.write, finance.transfer")).toBeTruthy();
    expect(screen.getByText("Escalation routing is inactive")).toBeTruthy();
  });

  it("renders all request kinds, literal context, options, and run references", async () => {
    render(<InboxQueue />);
    await screen.findByText("Approve the transfer?");
    expect(screen.getByText("Which signed copy?")).toBeTruthy();
    expect(screen.getByText("Clarify the intended audience")).toBeTruthy();
    expect(screen.getByText("Choose an escalation owner")).toBeTruthy();
    // The run is still NAMED on the request - which is what the reader needs -
    // but it is no longer a link: the Runs console went with its route.
    expect(screen.getByText("run/a")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "run/a" })).toBeNull();
    expect(screen.getByRole("button", { name: "Latest" })).toBeTruthy();
    expect(document.body.textContent).toContain('"amount": 42');
    expect(document.body.textContent).toContain('"policy": "four-eyes"');
  });

  it("arms an approval, sends notes once, and filters a stale refresh", async () => {
    api.respondHitl.mockResolvedValue({ status: "answered", response_id: "response-a" });
    render(<InboxQueue />);
    const card = (await screen.findByText("Approve the transfer?")).closest("article")!;
    fireEvent.change(within(card).getByLabelText("Response notes"), {
      target: { value: "Reviewed against invoice 42" },
    });
    fireEvent.click(within(card).getByRole("button", { name: "approve" }));
    expect(api.respondHitl).not.toHaveBeenCalled();
    fireEvent.click(within(card).getByRole("button", { name: "Confirm approve" }));
    await waitFor(() => expect(api.respondHitl).toHaveBeenCalledWith(
      "approval-a",
      "approve",
      "Reviewed against invoice 42",
    ));
    await waitFor(() => expect(screen.queryByText("Approve the transfer?")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(api.hitl).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Approve the transfer?")).toBeNull();
  });

  it("uses the owner-question route and blocks duplicate in-flight answers", async () => {
    let resolveAnswer: ((value: { status: string; response_id: string }) => void) | undefined;
    api.answerQuestion.mockReturnValue(new Promise((resolve) => {
      resolveAnswer = resolve;
    }));
    render(<InboxQueue />);
    const card = (await screen.findByText("Which signed copy?")).closest("article")!;
    const input = within(card).getByLabelText("Question answer");
    fireEvent.change(input, { target: { value: "Use the countersigned PDF" } });
    const send = within(card).getByRole("button", { name: "Send answer" });
    fireEvent.click(send);
    fireEvent.click(send);
    expect(api.answerQuestion).toHaveBeenCalledTimes(1);
    expect(api.answerQuestion).toHaveBeenCalledWith(
      "question-a",
      "Use the countersigned PDF",
    );
    resolveAnswer?.({ status: "ok", response_id: "response-question" });
    await waitFor(() => expect(screen.queryByText("Which signed copy?")).toBeNull());
  });

  it("preserves exact secure Inbox material and labels its bounded purpose", async () => {
    api.hitl.mockResolvedValue({
      requests: [{
        id: "secure-inbox",
        type: "question",
        question: "Paste the provider key",
        run_id: "run-secure",
        secure: true,
        secure_purpose: "provider-api-key",
      }],
    });
    api.answerQuestion.mockResolvedValue({
      status: "ok",
      response_id: "secure-response",
    });
    render(<InboxQueue />);
    const input = await screen.findByLabelText("Secure answer");
    expect((input as HTMLInputElement).type).toBe("password");
    expect(screen.getByText(/used only for provider-api-key/)).toBeTruthy();

    fireEvent.change(input, { target: { value: "  exact secret value  " } });
    fireEvent.click(screen.getByRole("button", { name: "Send answer" }));
    await waitFor(() => expect(api.answerQuestion).toHaveBeenCalledWith(
      "secure-inbox",
      "  exact secret value  ",
    ));
  });

  it("keeps a denied clarification visible with an honest error", async () => {
    api.respondHitl.mockResolvedValue({ status: "denied", reason: "not in your scope" });
    render(<InboxQueue />);
    const card = (await screen.findByText("Clarify the intended audience")).closest("article")!;
    fireEvent.change(within(card).getByLabelText("clarification response"), {
      target: { value: "External counsel" },
    });
    fireEvent.click(within(card).getByRole("button", { name: "Send response" }));
    expect(await within(card).findByText("not in your scope")).toBeTruthy();
    expect(screen.getByText("Clarify the intended audience")).toBeTruthy();
  });
});

describe("live chat owner questions", () => {
  it("renders choices and reports a dedicated-route denial in place", async () => {
    api.answerQuestion.mockResolvedValue({ status: "denied", reason: "not your run" });
    render(
      <LiveQuestionCard question={{
        questionId: "live-question",
        prompt: "Which environment?",
        choices: ["Staging", "Production"],
      }} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Staging" }));
    expect(await screen.findByText("not your run")).toBeTruthy();
    expect(api.answerQuestion).toHaveBeenCalledWith("live-question", "Staging");
  });

  it("preserves an exact secure answer, labels its purpose, and clears it", async () => {
    api.answerQuestion.mockResolvedValue({ status: "ok", response_id: "secure-response" });
    render(
      <LiveQuestionCard question={{
        questionId: "secure-question",
        prompt: "Paste the provider key",
        choices: [],
        secure: true,
        securePurpose: "provider-api-key",
      }} />,
    );
    const input = screen.getByLabelText("Secure live question answer") as HTMLInputElement;
    expect(input.type).toBe("password");
    expect(screen.getByText(/used only for provider-api-key/)).toBeTruthy();

    fireEvent.change(input, { target: { value: "  exact secret value  " } });
    fireEvent.click(screen.getByRole("button", { name: "Answer" }));

    await waitFor(() => expect(api.answerQuestion).toHaveBeenCalledWith(
      "secure-question",
      "  exact secret value  ",
    ));
    await screen.findByText("Answer accepted.");
    expect(screen.queryByDisplayValue("  exact secret value  ")).toBeNull();
  });
});
