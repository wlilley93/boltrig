import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { api } from "@/api/client";
import { ApprovalsPanel } from "@/panels/ApprovalsPanel";
import { clearApiMocks, mockApi } from "../helpers";

afterEach(() => {
  cleanup();
  clearApiMocks();
});

describe("ApprovalsPanel", () => {
  it("requires an explicit confirmation before submitting an approval", async () => {
    mockApi({
      hitl: {
        requests: [{
          id: "approval-1",
          type: "approval",
          urgency: "blocking",
          question: "Approve the outbound update?",
          // Legacy producers may omit options; the UI still keeps the ritual.
          options: [],
        }],
      },
      respondHitl: { status: "answered", response_id: "response-1" },
    });

    render(<ApprovalsPanel />);
    await screen.findByText("Approve the outbound update?");

    fireEvent.click(screen.getByRole("button", { name: "approve" }));
    expect(api.respondHitl).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Confirm approve" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Confirm approve" }));
    await waitFor(() => {
      expect(api.respondHitl).toHaveBeenCalledWith("approval-1", {
        decision: "approve",
        notes: "",
      });
    });
  });

  it("shows the exact governed action and literal inputs before approval", async () => {
    mockApi({
      hitl: {
        requests: [{
          id: "approval-rich",
          type: "approval",
          urgency: "blocking",
          question: "Approve ticket.create?",
          options: ["approve", "reject"],
          run_id: "run-approval",
          verb: "ticket.create",
          requested_by: "agent:release",
          requested_on_behalf_of: "will",
          inputs: { title: "Ship the release", api_key: "[redacted]" },
        }],
      },
    });

    render(<ApprovalsPanel />);
    await screen.findByText("Approve ticket.create?");

    expect(screen.getByText("ticket.create")).toBeTruthy();
    expect(screen.getByText("agent:release")).toBeTruthy();
    expect(screen.getByText("will")).toBeTruthy();
    expect(screen.getByText("Literal inputs")).toBeTruthy();
    expect(screen.getByText(/Ship the release/)).toBeTruthy();
    expect(screen.getByText(/\[redacted\]/)).toBeTruthy();
    expect(screen.getByText("run-approval")).toBeTruthy();
  });

  it("orders blocking decisions first and filters by type and urgency", async () => {
    mockApi({
      hitl: {
        requests: [
          { id: "q-async", type: "question", urgency: "async", question: "Question", options: [] },
          { id: "approval-async", type: "approval", urgency: "async", question: "Later approval", options: ["approve", "reject"] },
          { id: "clarify-blocking", type: "clarification", urgency: "blocking", question: "Blocking clarification", options: ["a", "b"] },
          { id: "approval-blocking", type: "approval", urgency: "blocking", question: "Blocking approval", options: ["approve", "reject"] },
        ],
      },
    });

    render(<ApprovalsPanel />);
    await screen.findByText("Blocking approval");

    expect(
      Array.from(document.querySelectorAll(".hitl-card__id"), (node) => node.textContent),
    ).toEqual([
      "approval-blocking",
      "clarify-blocking",
      "approval-async",
      "q-async",
    ]);

    fireEvent.change(screen.getByLabelText("Request type filter"), {
      target: { value: "question" },
    });
    expect(document.querySelector(".hitl-card__question")?.textContent).toBe("Question");
    expect(screen.queryByText("Blocking approval")).toBeNull();

    fireEvent.change(screen.getByLabelText("Request type filter"), {
      target: { value: "all-types" },
    });
    fireEvent.change(screen.getByLabelText("Request urgency filter"), {
      target: { value: "blocking" },
    });
    expect(screen.getByText("Blocking approval")).toBeTruthy();
    expect(screen.getByText("Blocking clarification")).toBeTruthy();
    expect(screen.queryByText("Later approval")).toBeNull();
  });

  it("answers owner questions through the dedicated route", async () => {
    mockApi({
      hitl: {
        requests: [{
          id: "question-1",
          type: "question",
          question: "Which account should the run use?",
          options: [],
        }],
      },
      answerQuestion: { status: "ok", question_id: "question-1" },
    });

    render(<ApprovalsPanel />);
    await screen.findByText("Which account should the run use?");
    expect(screen.queryByLabelText("Notes (optional)")).toBeNull();

    fireEvent.change(screen.getByLabelText("Your answer"), {
      target: { value: "Use staging" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send answer" }));

    await waitFor(() => {
      expect(api.answerQuestion).toHaveBeenCalledWith("question-1", "Use staging");
    });
    expect(api.respondHitl).not.toHaveBeenCalled();
    expect(await screen.findByText(/Runtime state will update according to server policy/)).toBeTruthy();
  });
});
