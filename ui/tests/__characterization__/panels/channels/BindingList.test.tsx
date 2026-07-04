import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BindingList, useBindingList } from "@/panels/channels/BindingList";
import { api } from "@/api/client";
import { clearApiMocks, mockApi } from "../../helpers";

describe("BindingList", () => {
  afterEach(() => {
    cleanup();
    clearApiMocks();
  });

  const channelId = "ch-1";
  const binding = {
    id: "b-1",
    external_user_id: "ext-1",
    subject: "sub-1",
    role: "member",
  };

  it("preserves the public exports", () => {
    expect(typeof BindingList).toBe("function");
    expect(typeof useBindingList).toBe("function");
  });

  it("shows the empty state when there are no bindings", async () => {
    mockApi({ channelBindings: { bindings: [] } });
    render(<BindingList channelId={channelId} />);
    await waitFor(() => expect(screen.getByText("No bindings")).toBeTruthy());
  });

  it("renders the bindings list", async () => {
    mockApi({ channelBindings: { bindings: [binding] } });
    render(<BindingList channelId={channelId} />);

    await waitFor(() => expect(screen.getByText("ext-1")).toBeTruthy());
    expect(screen.getByText(/sub-1/)).toBeTruthy();
    expect(screen.getByText(/role: member/)).toBeTruthy();
  });

  it("reloads when the refresh button is clicked", async () => {
    mockApi({ channelBindings: { bindings: [] } });
    render(<BindingList channelId={channelId} />);
    await waitFor(() => expect(screen.getByText("No bindings")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(api.channelBindings).toHaveBeenCalledTimes(2));
  });

  it("adds a binding from the form", async () => {
    mockApi({
      channelBindings: { bindings: [] },
      bindChannel: { status: "ok", binding: "b-2" },
    });
    render(<BindingList channelId={channelId} />);
    await waitFor(() => expect(screen.getByText("No bindings")).toBeTruthy());

    const inputs = screen.getAllByRole("textbox");
    fireEvent.change(inputs[0], { target: { value: "ext-2" } });
    fireEvent.change(inputs[1], { target: { value: "sub-2" } });
    fireEvent.click(screen.getByRole("button", { name: "Add binding" }));

    await waitFor(() =>
      expect(api.bindChannel).toHaveBeenCalledWith(channelId, {
        external_user_id: "ext-2",
        subject: "sub-2",
        role: "member",
      }),
    );
  });

  it("removes a binding after confirming", async () => {
    mockApi({
      channelBindings: { bindings: [binding] },
      deleteChannelBinding: { status: "ok" },
    });
    render(<BindingList channelId={channelId} />);
    await waitFor(() => expect(screen.getByText("ext-1")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm remove" }));

    await waitFor(() => expect(api.deleteChannelBinding).toHaveBeenCalledWith(channelId, "b-1"));
  });
});
