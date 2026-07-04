import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ChannelRow, useChannelRow } from "@/panels/channels/ChannelRow";
import { api } from "@/api/client";
import { clearApiMocks, mockApi } from "../../helpers";
import type { ChannelSummary } from "@/api/types";

describe("ChannelRow", () => {
  afterEach(() => {
    cleanup();
    clearApiMocks();
  });

  const channel: ChannelSummary = {
    id: "ch-1",
    name: "test-channel",
    platform: "webhook",
    transport: "http",
    enabled: true,
    unpaired_behavior: "reject",
  };

  it("preserves the public exports", () => {
    expect(typeof ChannelRow).toBe("function");
    expect(typeof useChannelRow).toBe("function");
  });

  it("renders the channel summary", () => {
    mockApi();
    render(<ChannelRow channel={channel} onChanged={() => {}} />);
    expect(screen.getByText("test-channel")).toBeTruthy();
    expect(screen.getByText("enabled")).toBeTruthy();
  });

  it("opens the management panel when Manage is clicked", async () => {
    mockApi({ channelBindings: { bindings: [] } });
    render(<ChannelRow channel={channel} onChanged={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Manage" }));
    await waitFor(() => expect(screen.getByText("Configure")).toBeTruthy());
  });

  it("saves configuration changes", async () => {
    mockApi({
      channelBindings: { bindings: [] },
      configureChannel: { status: "ok" },
    });
    const onChanged = vi.fn();
    render(<ChannelRow channel={channel} onChanged={onChanged} />);
    fireEvent.click(screen.getByRole("button", { name: "Manage" }));
    await waitFor(() => expect(screen.getByText("Configure")).toBeTruthy());

    const inputs = screen.getAllByRole("textbox");
    fireEvent.change(inputs[0], { target: { value: "renamed" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(api.configureChannel).toHaveBeenCalledWith("ch-1", {
        name: "renamed",
        unpaired_behavior: "reject",
        enabled: true,
      }),
    );
  });

  it("disconnects after confirming", async () => {
    mockApi({
      channelBindings: { bindings: [] },
      disconnectChannel: { status: "ok" },
    });
    const onChanged = vi.fn();
    render(<ChannelRow channel={channel} onChanged={onChanged} />);
    fireEvent.click(screen.getByRole("button", { name: "Manage" }));
    await waitFor(() => expect(screen.getByText("Configure")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm disconnect" }));

    await waitFor(() => expect(api.disconnectChannel).toHaveBeenCalledWith("ch-1"));
    expect(onChanged).toHaveBeenCalled();
  });
});
