import { afterEach, describe, it } from "vitest";
import { render } from "@testing-library/react";
import { ChannelsPanel } from "@/panels/ChannelsPanel";
import { clearApiMocks, mockApi } from "../helpers";

describe("ChannelsPanel", () => {
  afterEach(clearApiMocks);

  it("renders without crashing", () => {
    mockApi();
    render(<ChannelsPanel />);
  });
});
