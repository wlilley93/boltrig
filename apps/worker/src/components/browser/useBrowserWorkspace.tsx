import { useCallback, useEffect, useRef, useState } from "react";
import type { InvokeRequest, InvokeResult } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { useExactApprovalFinalizer } from "../ExactApprovalFinalizer";
import {
  parseBrowserAction,
  parseBrowserFrameData,
  parseBrowserNodes,
  parseBrowserTabs,
  type BrowserActionOutput,
  type BrowserCursor,
  type BrowserFrame,
  type BrowserNode,
  type BrowserTab,
} from "./BrowserWorkspaceModel";

const SESSION = "workspace";

interface BrowserMutation {
  request: InvokeRequest;
  expectedFrameId: string | null;
}

export interface BrowserWorkspaceController {
  address: string;
  busy: boolean;
  cursor: BrowserCursor | null;
  cursorTick: number;
  frame: BrowserFrame | null;
  frameSrc: string;
  message: string;
  nodes: BrowserNode[];
  tabs: BrowserTab[];
  finalizer: ReturnType<typeof useExactApprovalFinalizer<BrowserMutation, InvokeResult>>;
  setAddress(value: string): void;
  click(x: number, y: number): Promise<void>;
  closeTab(id: string): Promise<void>;
  inspect(): Promise<void>;
  navigate(): Promise<void>;
  press(key: string): Promise<void>;
  refresh(): Promise<void>;
  scroll(deltaY: number): Promise<void>;
  selectTab(id: string): Promise<void>;
  type(text: string): Promise<void>;
}

export function useBrowserWorkspace(): BrowserWorkspaceController {
  const [frame, setFrame] = useState<BrowserFrame | null>(null);
  const [frameSrc, setFrameSrc] = useState("");
  const [tabs, setTabs] = useState<BrowserTab[]>([]);
  const [nodes, setNodes] = useState<BrowserNode[]>([]);
  const [cursor, setCursor] = useState<BrowserCursor | null>(null);
  const [cursorTick, setCursorTick] = useState(0);
  const [address, setAddress] = useState("");
  const [message, setMessage] = useState("Connecting to the shared browser…");
  const [busy, setBusy] = useState(false);
  const frameRef = useRef<BrowserFrame | null>(null);
  const readGeneration = useRef(0);
  const booted = useRef(false);

  const readFrame = useCallback(async (next: BrowserFrame) => {
    const generation = ++readGeneration.current;
    const result = await client.invoke(browserRequest("browser.frame.read", { id: next.id }));
    if (generation !== readGeneration.current || result.status !== "ok") return;
    const src = parseBrowserFrameData(result.output);
    if (src) setFrameSrc(src);
  }, []);

  const refreshTabs = useCallback(async () => {
    const result = await client.invoke(browserRequest("browser.tabs.list", { name: SESSION }));
    if (result.status === "ok") setTabs(parseBrowserTabs(result.output));
  }, []);

  const applyAction = useCallback(async (output: BrowserActionOutput) => {
    frameRef.current = output.frame;
    setFrame(output.frame);
    setAddress(output.frame.url);
    setCursor(output.cursor);
    if (output.cursor) setCursorTick((value) => value + 1);
    setMessage(output.status === "stale_frame"
      ? "The page changed before the action. Review this fresh frame and try again."
      : "Browser frame is current.");
    await readFrame(output.frame);
    await refreshTabs();
  }, [readFrame, refreshTabs]);

  const { finalizer, invokeAction } = useBrowserMutation({
    applyAction, frameRef, readFrame, setBusy, setMessage,
  });

  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    void refreshTabs().then(() => invokeAction("browser.snapshot", {}, "Refresh browser"));
  }, [invokeAction, refreshTabs]);

  return browserController({
    address, busy, cursor, cursorTick, finalizer, frame, frameSrc, message, nodes, tabs,
    setAddress, setNodes, invokeAction, refreshTabs,
  });
}

function useBrowserMutation(options: {
  applyAction(output: BrowserActionOutput): Promise<void>;
  frameRef: React.MutableRefObject<BrowserFrame | null>;
  readFrame(frame: BrowserFrame): Promise<void>;
  setBusy(value: boolean): void;
  setMessage(value: string): void;
}) {
  const consume = useCallback(async (result: InvokeResult) => {
    if (result.status !== "ok") {
      options.setMessage(result.status === "pending_human" ? "Waiting for approval." : refusal(result));
      return false;
    }
    const output = parseBrowserAction(result.output);
    if (!output) {
      options.setMessage("The browser returned an invalid frame receipt.");
      return false;
    }
    await options.applyAction(output);
    return true;
  }, [options]);
  const finalizer = useExactApprovalFinalizer<BrowserMutation, InvokeResult>({
    isCurrent: (input) => !input.expectedFrameId
      || input.expectedFrameId === options.frameRef.current?.id,
    replay: (input, approvalId) => client.invoke({ ...input.request, approval_id: approvalId }),
    isApplied: (result) => result.status === "ok" && parseBrowserAction(result.output) !== null,
    onApplied: async (result) => { await consume(result); },
    onRefused: (result) => options.setMessage(refusal(result)),
    onUncertain: async () => {
      await readCurrentFrame(options.readFrame, options.frameRef.current);
    },
  });
  const invokeAction = useCallback(async (
    verb: string, params: Record<string, unknown>, label: string,
  ) => {
    options.setBusy(true);
    options.setMessage("");
    const request = browserRequest(verb, { ...params, name: SESSION });
    const expectedFrameId = typeof params.expected_frame_id === "string"
      ? params.expected_frame_id : null;
    try {
      const result = await client.invoke(request);
      if (!finalizer.begin({ request, expectedFrameId }, result, label)) await consume(result);
    } catch {
      options.setMessage("The browser is unavailable. No action is inferred.");
    } finally {
      options.setBusy(false);
    }
  }, [consume, finalizer, options]);
  return { finalizer, invokeAction };
}

function browserController(input: {
  address: string; busy: boolean; cursor: BrowserCursor | null; cursorTick: number;
  finalizer: BrowserWorkspaceController["finalizer"]; frame: BrowserFrame | null;
  frameSrc: string; message: string; nodes: BrowserNode[]; tabs: BrowserTab[];
  setAddress(value: string): void; setNodes(value: BrowserNode[]): void;
  invokeAction(verb: string, params: Record<string, unknown>, label: string): Promise<void>;
  refreshTabs(): Promise<void>;
}): BrowserWorkspaceController {
  const exact = () => input.frame?.id ?? "";
  const centre = () => ({
    x: Math.round((input.frame?.width ?? 1) / 2),
    y: Math.round((input.frame?.height ?? 1) / 2),
  });
  return {
    ...input,
    click: (x, y) => input.invokeAction("browser.click", { expected_frame_id: exact(), x, y }, "Click"),
    closeTab: (targetId) => input.invokeAction(
      "browser.tab.close", { target_id: targetId }, "Close tab",
    ),
    navigate: () => input.invokeAction("browser.navigate", { url: input.address }, "Open address"),
    press: (key) => input.invokeAction("browser.key.press", { expected_frame_id: exact(), key }, `Press ${key}`),
    refresh: async () => { await input.refreshTabs(); await input.invokeAction("browser.snapshot", {}, "Refresh browser"); },
    scroll: (deltaY) => input.invokeAction("browser.scroll", {
      expected_frame_id: exact(), ...centre(), delta_x: 0, delta_y: deltaY,
    }, "Scroll"),
    selectTab: (targetId) => input.invokeAction("browser.tab.select", { target_id: targetId }, "Select tab"),
    type: (text) => input.invokeAction("browser.type", { expected_frame_id: exact(), text }, "Type text"),
    inspect: async () => {
      const result = await client.invoke(browserRequest("browser.inspect", { name: SESSION, limit: 40 }));
      input.setNodes(result.status === "ok" ? parseBrowserNodes(result.output) : []);
    },
  };
}

function browserRequest(verb: string, params: Record<string, unknown>): InvokeRequest {
  return { noun: "browser", verb, params };
}

async function readCurrentFrame(
  read: (frame: BrowserFrame) => Promise<void>, frame: BrowserFrame | null,
) {
  if (frame) await read(frame);
}

function refusal(result: InvokeResult): string {
  if (result.status === "denied" || result.status === "unavailable" || result.status === "error") {
    return result.reason;
  }
  if (result.status === "degraded") return "The browser is degraded. No action is inferred.";
  return "The browser action is waiting for approval.";
}
