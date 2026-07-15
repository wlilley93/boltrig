import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { api } from "@/api/client";
import { ChatHitlCard } from "@/panels/chatTurnHitl";
import { clearApiMocks, mockApi } from "../helpers";

afterEach(() => {
  cleanup();
  clearApiMocks();
});

describe("ChatHitlCard", () => {
  it("uses the shared two-step approval ritual", async () => {
    mockApi({ respondHitl: { status: "answered", response_id: "response-1" } });
    const onResolve = vi.fn();
    render(
      <ChatHitlCard
        entry={{
          hitlRequestId: "approval-1",
          kind: "approval",
          question: "Approve the update?",
          options: ["approve", "reject"],
        }}
        resolved={undefined}
        onResolve={onResolve}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "approve" }));
    expect(api.respondHitl).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Confirm approve" }));
    await waitFor(() => {
      expect(api.respondHitl).toHaveBeenCalledWith("approval-1", {
        decision: "approve",
        notes: "",
      });
    });
    expect(onResolve).toHaveBeenCalledWith("approval-1", "recorded");
  });

  it("keeps questions on the dedicated answer endpoint", async () => {
    mockApi({ answerQuestion: { status: "ok", question_id: "question-1" } });
    render(
      <ChatHitlCard
        entry={{
          hitlRequestId: "question-1",
          kind: "question",
          question: "Which environment?",
          options: [],
        }}
        resolved={undefined}
        onResolve={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Your answer"), {
      target: { value: "staging" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send answer" }));

    await waitFor(() => {
      expect(api.answerQuestion).toHaveBeenCalledWith("question-1", "staging");
    });
    expect(api.respondHitl).not.toHaveBeenCalled();
  });
});
