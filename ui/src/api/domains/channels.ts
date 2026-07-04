// Channel management (decision 0003, admin-gated).
// Every call carries tolerateStatus so a 403 (not an author), 400 (bad input)
// or 404 (unknown channel) renders as a message instead of throwing. The
// connect body's signing_secret and the pair response's code are the only
// secret material and are handled show-once by the caller.

import { request } from "@/api/transport";
import type {
  BindChannelRequest,
  BindChannelResponse,
  ChannelAck,
  ChannelBindingsResponse,
  ChannelsResponse,
  ConfigureChannelRequest,
  ConnectChannelRequest,
  ConnectChannelResponse,
  PairChannelRequest,
  PairChannelResponse,
} from "@/api/types";

export const channelsApi = {
  channels(): Promise<ChannelsResponse> {
    return request<ChannelsResponse>("/v1/channels", { tolerateStatus: true });
  },

  connectChannel(body: ConnectChannelRequest): Promise<ConnectChannelResponse> {
    return request<ConnectChannelResponse>("/v1/channels", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  configureChannel(
    id: string,
    body: ConfigureChannelRequest,
  ): Promise<ChannelAck> {
    return request<ChannelAck>(`/v1/channels/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body,
      tolerateStatus: true,
    });
  },

  disconnectChannel(id: string): Promise<ChannelAck> {
    return request<ChannelAck>(`/v1/channels/${encodeURIComponent(id)}`, {
      method: "DELETE",
      tolerateStatus: true,
    });
  },

  channelBindings(id: string): Promise<ChannelBindingsResponse> {
    return request<ChannelBindingsResponse>(
      `/v1/channels/${encodeURIComponent(id)}/bindings`,
      { tolerateStatus: true },
    );
  },

  // The minted pairing code is in the response ONCE and is never returned again.
  pairChannel(
    id: string,
    body: PairChannelRequest,
  ): Promise<PairChannelResponse> {
    return request<PairChannelResponse>(
      `/v1/channels/${encodeURIComponent(id)}/pair`,
      { method: "POST", body, tolerateStatus: true },
    );
  },

  bindChannel(
    id: string,
    body: BindChannelRequest,
  ): Promise<BindChannelResponse> {
    return request<BindChannelResponse>(
      `/v1/channels/${encodeURIComponent(id)}/bindings`,
      { method: "POST", body, tolerateStatus: true },
    );
  },

  deleteChannelBinding(id: string, bindingId: string): Promise<ChannelAck> {
    return request<ChannelAck>(
      `/v1/channels/${encodeURIComponent(id)}/bindings/${encodeURIComponent(bindingId)}`,
      { method: "DELETE", tolerateStatus: true },
    );
  },
};
