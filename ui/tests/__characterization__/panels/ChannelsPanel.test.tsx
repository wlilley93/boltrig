import { afterEach, describe, it } from "vitest";
import { render } from "@testing-library/react";
import { ChannelsPanel } from "@/panels/ChannelsPanel";
import { ConnectForm } from "@/panels/channels/ConnectForm";
import { BindingList } from "@/panels/channels/BindingList";
import { PairForm } from "@/panels/channels/PairForm";
import { ChannelRow } from "@/panels/channels/ChannelRow";
import { clearApiMocks, mockApi } from "../helpers";

const channel = {
  id: "ch-1",
  name: "test-channel",
  platform: "webhook",
  transport: "http",
  enabled: true,
  unpaired_behavior: "reject",
};

describe("ChannelsPanel", () => {
  afterEach(clearApiMocks);

  it("renders without crashing", () => {
    mockApi();
    render(<ChannelsPanel />);
  });

  it("renders ConnectForm", () => {
    mockApi();
    render(<ConnectForm onConnected={() => {}} />);
  });

  it("renders BindingList", () => {
    mockApi();
    render(<BindingList channelId={channel.id} />);
  });

  it("renders PairForm", () => {
    mockApi();
    render(<PairForm channelId={channel.id} />);
  });

  it("renders ChannelRow", () => {
    mockApi();
    render(<ChannelRow channel={channel} onChanged={() => {}} />);
  });
});
