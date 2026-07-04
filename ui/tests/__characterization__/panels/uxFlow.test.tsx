import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { Skeleton } from "@/panels/uxFlow";

describe("uxFlow (Skeleton)", () => {
  it("renders the requested skeleton variant", () => {
    const { container } = render(<Skeleton variant="rows" count={2} />);
    expect(container.querySelector(".ux-skel")?.children).toHaveLength(2);
  });
});
