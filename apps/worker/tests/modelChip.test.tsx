// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ModelChip } from "../src/components/chat/ModelChip";

const choices = [
  {
    id: "choice-reasoning",
    model_name: "openai/gpt-5.4",
    available: true,
    is_default: true,
    modalities: ["text"],
  },
  {
    id: "choice-writing",
    model_name: "anthropic/claude-sonnet-4-5",
    available: true,
    is_default: false,
    modalities: ["text", "vision"],
  },
  {
    id: "choice-offline",
    model_name: "google/gemini-3-pro",
    available: false,
    is_default: false,
    modalities: ["text"],
    unavailable_reason: "Provider health check failed.",
  },
];

afterEach(cleanup);

describe("chat model switcher", () => {
  it("shows exact model names and sends only the opaque selected id", () => {
    const onChange = vi.fn();
    render(
      <ModelChip
        choices={choices}
        defaultModelName="openai/gpt-5.4"
        onChange={onChange}
        value=""
      />,
    );

    const trigger = screen.getByRole("button", { name: "Model" });
    expect(trigger.textContent).toContain("Automatic · openai/gpt-5.4");
    expect(trigger.textContent).not.toContain("Best available");

    fireEvent.click(trigger);
    const listbox = screen.getByRole("listbox", { name: "Models" });
    expect(within(listbox).getByText("anthropic/claude-sonnet-4-5")).toBeTruthy();
    expect(within(listbox).queryByText("choice-writing")).toBeNull();

    fireEvent.click(within(listbox).getByRole("option", {
      name: "anthropic/claude-sonnet-4-5",
    }));
    expect(onChange).toHaveBeenCalledWith("choice-writing");
  });

  it("keeps unavailable choices visible but non-selectable", () => {
    const onChange = vi.fn();
    render(<ModelChip choices={choices} onChange={onChange} value="" />);

    fireEvent.click(screen.getByRole("button", { name: "Model" }));
    const unavailable = screen.getByRole("option", {
      name: "google/gemini-3-pro Unavailable",
    });
    expect(unavailable.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(unavailable);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("does not claim Automatic is runnable when the server says it is unavailable", () => {
    const onChange = vi.fn();
    render(
      <ModelChip
        choices={choices}
        defaultAvailable={false}
        defaultModelName="openai/gpt-5.4"
        defaultUnavailableReason="model_gateway_unavailable"
        onChange={onChange}
        value=""
      />,
    );

    expect(screen.getByRole("button", { name: "Model" }).textContent)
      .toContain("Automatic · openai/gpt-5.4Unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Model" }));
    const automatic = screen.getByRole("option", {
      name: "Automatic · openai/gpt-5.4 Unavailable",
    });
    expect(automatic.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(automatic);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("puts model management outside the listbox and locks during a live turn", () => {
    const onManage = vi.fn();
    const view = render(
      <ModelChip
        choices={choices}
        disabled
        disabledReason="The model can be changed after the current turn finishes."
        onChange={vi.fn()}
        onManage={onManage}
        value=""
      />,
    );

    const locked = screen.getByRole("button", { name: "Model" });
    expect(locked).toHaveProperty("disabled", true);
    expect(locked.getAttribute("title")).toContain("after the current turn finishes");

    view.rerender(
      <ModelChip
        choices={choices}
        onChange={vi.fn()}
        onManage={onManage}
        value=""
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Model" }));
    const manage = screen.getByRole("button", { name: "Manage models…" });
    expect(manage.closest('[role="listbox"]')).toBeNull();
    fireEvent.click(manage);
    expect(onManage).toHaveBeenCalledOnce();
  });

  it("disambiguates duplicate exact names without replacing the name", () => {
    render(
      <ModelChip
        choices={[
          { ...choices[0]!, id: "route-a" },
          { ...choices[0]!, id: "route-b", is_default: false },
        ]}
        onChange={vi.fn()}
        value="route-b"
      />,
    );

    expect(screen.getByRole("button", { name: "Model" }).textContent)
      .toContain("openai/gpt-5.4");
    expect(screen.getByRole("button", { name: "Model" }).textContent)
      .toContain("route-b");
  });
});
