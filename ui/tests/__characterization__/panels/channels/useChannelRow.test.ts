import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useChannelRow } from "@/panels/channels/useChannelRow";
import { api } from "@/api/client";
import { clearApiMocks, mockApi } from "../../helpers";
import type { ChannelSummary } from "@/api/types";

describe("useChannelRow", () => {
  afterEach(clearApiMocks);

  const channel: ChannelSummary = {
    id: "ch-1",
    name: "test-channel",
    platform: "webhook",
    transport: "http",
    enabled: true,
    unpaired_behavior: "reject",
  };

  it("mirrors the channel state on first render", () => {
    const { result } = renderHook(() => useChannelRow(channel, vi.fn()));

    expect(result.current.name).toBe("test-channel");
    expect(result.current.unpaired).toBe("reject");
    expect(result.current.enabled).toBe("true");
    expect(result.current.open).toBe(false);
  });

  it("configures the channel and calls onChanged on success", async () => {
    mockApi({ configureChannel: { status: "ok" } });
    const onChanged = vi.fn();
    const { result } = renderHook(() => useChannelRow(channel, onChanged));

    act(() => {
      result.current.setName("new-name");
      result.current.setUnpaired("ignore");
      result.current.setEnabled("false");
    });

    await act(async () => {
      await result.current.configure();
    });

    expect(api.configureChannel).toHaveBeenCalledWith("ch-1", {
      name: "new-name",
      unpaired_behavior: "ignore",
      enabled: false,
    });
    expect(result.current.msg).toBe("Saved.");
    expect(onChanged).toHaveBeenCalled();
  });

  it("falls back to the existing name when trimmed to empty", async () => {
    mockApi({ configureChannel: { status: "ok" } });
    const { result } = renderHook(() => useChannelRow(channel, vi.fn()));

    act(() => {
      result.current.setName("   ");
    });

    await act(async () => {
      await result.current.configure();
    });

    expect(api.configureChannel).toHaveBeenCalledWith(
      "ch-1",
      expect.objectContaining({ name: "test-channel" }),
    );
  });

  it("surfaces a rejected configuration reason", async () => {
    mockApi({ configureChannel: { status: "denied", reason: "not allowed" } });
    const { result } = renderHook(() => useChannelRow(channel, vi.fn()));

    await act(async () => {
      await result.current.configure();
    });

    expect(result.current.error).toBe("not allowed");
  });

  it("disconnects the channel and calls onChanged", async () => {
    mockApi({ disconnectChannel: { status: "ok" } });
    const onChanged = vi.fn();
    const { result } = renderHook(() => useChannelRow(channel, onChanged));

    await act(async () => {
      await result.current.disconnect();
    });

    expect(api.disconnectChannel).toHaveBeenCalledWith("ch-1");
    expect(onChanged).toHaveBeenCalled();
  });

  it("throws when disconnect is rejected", async () => {
    mockApi({ disconnectChannel: { status: "denied", reason: "no" } });
    const { result } = renderHook(() => useChannelRow(channel, vi.fn()));

    await expect(result.current.disconnect()).rejects.toThrow("no");
  });
});
