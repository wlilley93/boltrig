import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";

import { api } from "@/api/client";
import type { DirectoryUser } from "@/api/types";
import { DeckSlideContext } from "@/deck/context";
import { UserRow } from "@/panels/admin/tenancy/UserDirectory";
import { ADMIN_SECTIONS } from "@/panels/admin/sections";
import { useAdminConfig } from "@/panels/admin/useAdminConfig";
import { ScheduleForm } from "@/panels/studio/workflow/forms/ScheduleForm";
import { PendingHumanCard, useControlMutation } from "@/panels/uxFlow";
import { clearApiMocks, mockApi } from "../helpers";

function InactiveSlide({ children }: { children: ReactNode }) {
  return (
    <DeckSlideContext.Provider value={{ active: false, neighbour: false }}>
      {children}
    </DeckSlideContext.Provider>
  );
}

function MutationHarness({ onApplied }: { onApplied: ReturnType<typeof vi.fn> }) {
  const mutation = useControlMutation({
    verb: "control.test.change",
    onApplied,
  });
  const params = { resource_id: "resource-1", enabled: true };
  return (
    <>
      <button
        disabled={mutation.busy || mutation.pending !== null}
        onClick={() => void mutation.invoke(params)}
      >
        Change
      </button>
      {mutation.pending && (
        <PendingHumanCard
          hitlRequestId={mutation.pending.id}
          noun="control"
          verb="control.test.change"
          sentParams={mutation.pending.params}
          onApplied={mutation.onPendingApplied}
          onDenied={mutation.onPendingDenied}
          onReset={mutation.resetPending}
        />
      )}
    </>
  );
}

function AdminRollbackHarness() {
  const admin = useAdminConfig();
  return (
    <>
      <button
        disabled={admin.pending !== null}
        onClick={() => void admin.rollback(42)}
      >
        Rollback 42
      </button>
      {admin.saveMsg && <p>{admin.saveMsg}</p>}
      {admin.pending && (
        <PendingHumanCard
          hitlRequestId={admin.pending.id}
          noun="control"
          verb={admin.pending.verb}
          sentParams={admin.pending.params}
          onApplied={admin.onPendingApplied}
          onDenied={admin.onPendingDenied}
          onReset={admin.onPendingReset}
        />
      )}
    </>
  );
}

afterEach(() => {
  cleanup();
  clearApiMocks();
});

describe("governed control mutations", () => {
  it("keeps a pending invoke paused with its exact re-apply contract", async () => {
    mockApi({
      invoke: { status: "pending_human", hitl_request_id: "hitl-control-1" },
    });
    const onApplied = vi.fn();
    render(
      <InactiveSlide>
        <MutationHarness onApplied={onApplied} />
      </InactiveSlide>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Change" }));

    await screen.findByText("Paused for approval");
    expect(api.invoke).toHaveBeenCalledWith({
      noun: "control",
      verb: "control.test.change",
      params: { resource_id: "resource-1", enabled: true },
    });
    expect(screen.getByText("control.test.change")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Change" }).hasAttribute("disabled"),
    ).toBe(true);
    expect(onApplied).not.toHaveBeenCalled();
  });

  it("runs the success callback only after an applied result", async () => {
    const output = { id: "resource-1", enabled: true };
    mockApi({ invoke: { status: "ok", output } });
    const onApplied = vi.fn();
    render(
      <InactiveSlide>
        <MutationHarness onApplied={onApplied} />
      </InactiveSlide>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Change" }));

    await waitFor(() =>
      expect(onApplied).toHaveBeenCalledWith(
        output,
        { resource_id: "resource-1", enabled: true },
        { status: "ok", output },
      ),
    );
    expect(screen.queryByText("Paused for approval")).toBeNull();
  });

  it("reuses one idempotency key when an approval re-apply response is lost", async () => {
    const output = { id: "resource-1", enabled: true };
    mockApi({
      hitl: { requests: [] },
      invoke: { status: "ok", output },
    });
    const invoke = vi.mocked(api.invoke);
    invoke
      .mockRejectedValueOnce(new Error("response lost"))
      .mockResolvedValueOnce({ status: "ok", output });
    const onApplied = vi.fn();
    render(
      <DeckSlideContext.Provider value={{ active: true, neighbour: false }}>
        <PendingHumanCard
          hitlRequestId="hitl-retry-1"
          noun="control"
          verb="control.test.change"
          sentParams={{ resource_id: "resource-1", enabled: true }}
          onApplied={onApplied}
        />
      </DeckSlideContext.Provider>,
    );

    await screen.findByText("Applying failed");
    const firstKey = invoke.mock.calls[0]?.[0].idempotency_key;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
    expect(firstKey).toMatch(/^phc-/);
    expect(invoke.mock.calls[1]?.[0].idempotency_key).toBe(firstKey);
  });

  it("lets a terminal approval outcome return a locked form to editing", async () => {
    mockApi({
      hitl: { requests: [] },
      invoke: { status: "pending_human", hitl_request_id: "hitl-fresh-1" },
    });
    const onApplied = vi.fn();
    render(
      <DeckSlideContext.Provider value={{ active: true, neighbour: false }}>
        <MutationHarness onApplied={onApplied} />
      </DeckSlideContext.Provider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    await screen.findByRole("button", { name: "Start again" });
    fireEvent.click(screen.getByRole("button", { name: "Start again" }));

    expect(
      screen.getByRole("button", { name: "Change" }).hasAttribute("disabled"),
    ).toBe(false);
    expect(onApplied).not.toHaveBeenCalled();
  });

  it("schedules through control.workflow.schedule without showing a result on 202", async () => {
    mockApi({
      invoke: { status: "pending_human", hitl_request_id: "hitl-schedule-1" },
    });
    render(
      <InactiveSlide>
        <ScheduleForm
          wfOptions={[{ value: "invoice-flow", label: "invoice-flow" }]}
        />
      </InactiveSlide>,
    );

    fireEvent.change(screen.getByLabelText("Workflow"), {
      target: { value: "invoice-flow" },
    });
    fireEvent.change(screen.getByPlaceholderText("0 9 * * 1"), {
      target: { value: "0 9 * * 1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Schedule" }));

    await screen.findByText("Paused for approval");
    expect(api.invoke).toHaveBeenCalledWith({
      noun: "control",
      verb: "control.workflow.schedule",
      params: {
        workflow_id: "invoice-flow",
        cron: "0 9 * * 1",
        timezone: "UTC",
      },
    });
    expect(screen.queryByText(/schedule_id/i)).toBeNull();
  });

  it("uses the dedicated deactivation verb and waits before refreshing users", async () => {
    mockApi({
      invoke: { status: "pending_human", hitl_request_id: "hitl-user-1" },
    });
    const onChanged = vi.fn();
    const user: DirectoryUser = {
      id: "user-7",
      email: "operator@example.test",
      role: "operator",
      scope: {},
      status: "active",
    };
    render(
      <InactiveSlide>
        <UserRow user={user} verbs={[]} onChanged={onChanged} />
      </InactiveSlide>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm deactivate" }),
    );

    await screen.findByText("Paused for approval");
    expect(api.invoke).toHaveBeenCalledWith({
      noun: "control",
      verb: "control.user.deactivate",
      params: { user_id: "user-7" },
    });
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("updates a user through control.user.update with the selected patch", async () => {
    mockApi({
      invoke: { status: "pending_human", hitl_request_id: "hitl-user-update-1" },
    });
    const onChanged = vi.fn();
    const user: DirectoryUser = {
      id: "user-8",
      email: "manager@example.test",
      role: "manager",
      scope: {},
      status: "active",
    };
    render(
      <InactiveSlide>
        <UserRow user={user} verbs={[]} onChanged={onChanged} />
      </InactiveSlide>,
    );

    fireEvent.change(screen.getByLabelText("Role for manager@example.test"), {
      target: { value: "agent" },
    });

    await screen.findByText("Paused for approval");
    expect(api.invoke).toHaveBeenCalledWith({
      noun: "control",
      verb: "control.user.update",
      params: { user_id: "user-8", role: "agent" },
    });
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("keeps config rollback pending until its governed re-apply succeeds", async () => {
    mockApi({
      getConfig: { section: ADMIN_SECTIONS[0].key, value: {} },
      configHistory: { section: ADMIN_SECTIONS[0].key, revisions: [] },
      invoke: { status: "pending_human", hitl_request_id: "hitl-rollback-1" },
    });
    render(
      <InactiveSlide>
        <AdminRollbackHarness />
      </InactiveSlide>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Rollback 42" }));

    await screen.findByText("Paused for approval");
    expect(api.invoke).toHaveBeenCalledWith({
      noun: "control",
      verb: "control.config.rollback",
      params: { section: ADMIN_SECTIONS[0].key, revision_id: 42 },
    });
    expect(screen.queryByText(/rolled back to revision/i)).toBeNull();
  });
});
