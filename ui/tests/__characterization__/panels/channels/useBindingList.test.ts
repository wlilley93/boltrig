import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useBindingList } from "@/panels/channels/useBindingList";
import { api } from "@/api/client";
import { clearApiMocks, mockApi } from "../../helpers";

describe("useBindingList", () => {
  afterEach(clearApiMocks);

  const channelId = "ch-1";
  const binding = {
    id: "b-1",
    external_user_id: "ext-1",
    subject: "sub-1",
    role: "member",
  };

  it("loads the bindings list and exposes default form state", async () => {
    mockApi({ channelBindings: { bindings: [binding] } });
    const { result } = renderHook(() => useBindingList(channelId));

    await waitFor(() => expect(result.current.bindings.data).toBeTruthy());

    expect(result.current.list).toHaveLength(1);
    expect(result.current.list[0]).toEqual(binding);
    expect(result.current.denied).toBeNull();
    expect(result.current.ext).toBe("");
    expect(result.current.subject).toBe("");
    expect(result.current.role).toBe("member");
  });

  it("reports denied when the response has no bindings", async () => {
    mockApi({ channelBindings: { status: "denied", reason: "not an author" } });
    const { result } = renderHook(() => useBindingList(channelId));

    await waitFor(() => expect(result.current.denied).toBe("not an author"));
    expect(result.current.list).toHaveLength(0);
  });

  it("requires both ext and subject before adding", async () => {
    mockApi({ channelBindings: { bindings: [] } });
    const { result } = renderHook(() => useBindingList(channelId));

    await waitFor(() => expect(result.current.bindings.data).toBeTruthy());

    await act(async () => {
      await result.current.addBinding();
    });

    expect(result.current.error).toBe("An external user id and a subject are required.");
    expect(api.bindChannel).not.toHaveBeenCalled();
  });

  it("adds a binding and resets the form on success", async () => {
    mockApi({
      channelBindings: { bindings: [] },
      bindChannel: { status: "ok", binding: "b-2" },
    });
    const { result } = renderHook(() => useBindingList(channelId));

    await waitFor(() => expect(result.current.bindings.data).toBeTruthy());

    act(() => {
      result.current.setExt("ext-2");
      result.current.setSubject("sub-2");
      result.current.setRole("admin");
    });

    await act(async () => {
      await result.current.addBinding();
    });

    expect(api.bindChannel).toHaveBeenCalledWith(channelId, {
      external_user_id: "ext-2",
      subject: "sub-2",
      role: "admin",
    });
    expect(result.current.ext).toBe("");
    expect(result.current.subject).toBe("");
    expect(result.current.error).toBeNull();
  });

  it("surfaces a rejected bind reason", async () => {
    mockApi({
      channelBindings: { bindings: [] },
      bindChannel: { status: "rejected", reason: "already bound" },
    });
    const { result } = renderHook(() => useBindingList(channelId));

    await waitFor(() => expect(result.current.bindings.data).toBeTruthy());

    act(() => {
      result.current.setExt("ext-3");
      result.current.setSubject("sub-3");
    });

    await act(async () => {
      await result.current.addBinding();
    });

    expect(result.current.error).toBe("already bound");
  });

  it("removes a binding and reloads the list", async () => {
    const reload = vi.fn();
    vi.spyOn(api, "channelBindings").mockResolvedValue({ bindings: [binding] });
    vi.spyOn(api, "deleteChannelBinding").mockResolvedValue({ status: "ok" });
    const { result } = renderHook(() => useBindingList(channelId));

    await waitFor(() => expect(result.current.bindings.data).toBeTruthy());
    result.current.bindings.reload = reload;

    await act(async () => {
      await result.current.removeBinding("b-1");
    });

    expect(api.deleteChannelBinding).toHaveBeenCalledWith(channelId, "b-1");
    expect(reload).toHaveBeenCalled();
  });

  it("throws when removeBinding is rejected", async () => {
    vi.spyOn(api, "channelBindings").mockResolvedValue({ bindings: [] });
    vi.spyOn(api, "deleteChannelBinding").mockResolvedValue({ status: "denied", reason: "no" });
    const { result } = renderHook(() => useBindingList(channelId));

    await waitFor(() => expect(result.current.bindings.data).toBeTruthy());

    await expect(result.current.removeBinding("b-1")).rejects.toThrow("no");
  });
});
