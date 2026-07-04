import { afterEach, describe, it } from "vitest";
import { render } from "@testing-library/react";
import { ChatPanel } from "@/panels/ChatPanel";
import { clearApiMocks, mockApi } from "../helpers";

describe("ChatPanel", () => {
  afterEach(clearApiMocks);

  it("renders without crashing", () => {
    mockApi({
      listConversations: { conversations: [], next_offset: null },
      searchConversations: { results: [], next_offset: null },
      conversation: { messages: [] },
    });
    render(<ChatPanel />);
  });
});
