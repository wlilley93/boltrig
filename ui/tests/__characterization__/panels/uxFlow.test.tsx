import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { DeckSlideContext } from "@/deck/context";
import {
  ArmConfirm,
  type ArmTone,
  ByChat,
  CoachMark,
  DiffView,
  Disclosure,
  GrantList,
  PendingHumanCard,
  SaveBar,
  SecretOnce,
  Skeleton,
  useArmConfirm,
  type UseArmConfirm,
} from "@/panels/uxFlow";

describe("uxFlow public API", () => {
  it("renders Skeleton", () => {
    const { container } = render(<Skeleton variant="rows" count={2} />);
    expect(container.querySelector(".ux-skel")?.children).toHaveLength(2);
  });

  it("renders Disclosure", () => {
    const { container } = render(<Disclosure summary="Summary">Body</Disclosure>);
    expect(container.querySelector(".ux-disclosure")).toBeTruthy();
  });

  it("renders GrantList", () => {
    const { container } = render(<GrantList grants={["a", "b"]} />);
    expect(container.querySelectorAll(".tag")).toHaveLength(2);
  });

  it("renders CoachMark", () => {
    const { container } = render(<CoachMark id="test">Tip</CoachMark>);
    expect(container.querySelector(".ux-coach")).toBeTruthy();
  });

  it("renders ByChat", () => {
    const { container } = render(<ByChat phrase="do thing" />);
    expect(container.querySelector(".ux-bychat")).toBeTruthy();
  });

  it("renders DiffView", () => {
    const { container } = render(<DiffView before={{ a: 1 }} after={{ a: 2 }} />);
    expect(container.querySelector(".ux-diff")).toBeTruthy();
  });

  it("renders ArmConfirm", () => {
    const { container } = render(
      <ArmConfirm
        label="Delete"
        armLabel="Really delete?"
        confirmLabel="Yes"
        tone="danger"
        busyLabel="Deleting..."
        onConfirm={async () => {}}
      />,
    );
    expect(container.querySelector(".btn")).toBeTruthy();
  });

  it("renders SaveBar", () => {
    const { container } = render(
      <SaveBar
        dirty={true}
        saving={false}
        label="Unsaved"
        saveLabel="Save"
        onSave={() => {}}
        onDiscard={() => {}}
      />,
    );
    expect(container.querySelector(".ux-savebar")).toBeTruthy();
  });

  it("renders SecretOnce", () => {
    const { container } = render(<SecretOnce secret="shh" onDone={() => {}} />);
    expect(container.querySelector(".ux-secret")).toBeTruthy();
  });

  it("renders PendingHumanCard without polling when inactive", () => {
    const { container } = render(
      <DeckSlideContext.Provider value={{ active: false, neighbour: false }}>
        <PendingHumanCard
          hitlRequestId="hitl-123"
          verb="control.test"
          noun="test"
          sentParams={{}}
          onApplied={() => {}}
        />
      </DeckSlideContext.Provider>,
    );
    expect(container.querySelector(".ux-pending")).toBeTruthy();
  });

  it("redacts credentials from pending-approval disclosures", () => {
    const { container } = render(
      <DeckSlideContext.Provider value={{ active: false, neighbour: false }}>
        <PendingHumanCard
          hitlRequestId="hitl-secret"
          verb="control.ai_key.set"
          noun="control"
          sentParams={{
            provider: "example",
            api_key: "never-render-this",
            tokens_limit: 25000,
            config: { signing_secret: "nor-this" },
          }}
          onApplied={() => {}}
        />
      </DeckSlideContext.Provider>,
    );

    expect(container.textContent).toContain("example");
    expect(container.textContent).toContain("25000");
    expect(container.textContent).toContain("[redacted]");
    expect(container.textContent).not.toContain("never-render-this");
    expect(container.textContent).not.toContain("nor-this");
  });

  it("exposes useArmConfirm with the published contract", () => {
    let result: UseArmConfirm | undefined;
    const tone: ArmTone = "danger";
    function Consumer() {
      result = useArmConfirm(async () => {});
      return null;
    }
    render(<Consumer />);
    expect(result).toBeTruthy();
    expect(result?.armed).toBe(false);
    expect(result?.busy).toBe(false);
    expect(result?.error).toBeNull();
    expect(result?.arm).toBeInstanceOf(Function);
    expect(result?.disarm).toBeInstanceOf(Function);
    expect(result?.confirm).toBeInstanceOf(Function);
    expect(result?.containerProps).toBeTruthy();
    expect(tone).toBe("danger");
  });
});
