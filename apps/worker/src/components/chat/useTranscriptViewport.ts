import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type MutableRefObject,
  type UIEventHandler,
} from "react";

import { useMediaQuery } from "../../useMediaQuery";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
const DEFAULT_BOTTOM_THRESHOLD = 80;
const DEFAULT_USER_MESSAGE_SELECTOR = '[data-transcript-role="user"], .message.user';

type ConversationKey = string | null;
type ContentRevision = string | number;

interface UseTranscriptViewportOptions {
  /** The selected conversation. A change is a hard viewport boundary. */
  conversationKey: ConversationKey;
  /**
   * A primitive that changes after transcript DOM content changes. Streaming
   * consumers should include the event count/text length as well as durable
   * message changes.
   */
  contentRevision: ContentRevision;
  bottomThreshold?: number;
  userMessageSelector?: string;
}

interface NavigationState {
  activeUserMessageIndex: number | null;
  userMessageCount: number;
}

interface PrependAnchor {
  conversationKey: ConversationKey;
  scrollHeight: number;
  scrollTop: number;
}

export interface TranscriptNavigationModel {
  activeUserMessageIndex: number | null;
  canGoToNextUserMessage: boolean;
  canGoToPreviousUserMessage: boolean;
  goToNextUserMessage(): void;
  goToPreviousUserMessage(): void;
  jumpToLatest(): void;
  showJumpToLatest: boolean;
  userMessageCount: number;
}

export interface TranscriptViewportController {
  /** Attach to the element that owns transcript scrolling. */
  transcriptRef: MutableRefObject<HTMLDivElement | null>;
  /** Attach to the same element's onScroll prop. */
  onTranscriptScroll: UIEventHandler<HTMLDivElement>;
  /**
   * Call immediately before committing older messages above the visible
   * transcript. The next contentRevision restores the same reading position.
   */
  prepareForHistoryPrepend(): void;
  /** Cancel a prepared prepend when loading older messages fails. */
  cancelHistoryPrepend(): void;
  followingLatest: boolean;
  navigation: TranscriptNavigationModel;
}

function userMessages(viewport: HTMLElement, selector: string): HTMLElement[] {
  return [...viewport.querySelectorAll<HTMLElement>(selector)];
}

function nearBottom(viewport: HTMLElement, threshold: number): boolean {
  return viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight <= threshold;
}

function setScrollTop(viewport: HTMLElement, top: number): void {
  // Assignment is intentional for automatic following and prepend restores.
  // CSS smooth scrolling must never animate a reader-preservation correction.
  viewport.scrollTop = top;
}

/**
 * Owns transcript viewport behavior without owning transcript rendering or its
 * event vocabulary. OrderedWorkTranscript therefore remains the sole renderer
 * of chronological prose and governed work receipts.
 */
export function useTranscriptViewport({
  conversationKey,
  contentRevision,
  bottomThreshold = DEFAULT_BOTTOM_THRESHOLD,
  userMessageSelector = DEFAULT_USER_MESSAGE_SELECTOR,
}: UseTranscriptViewportOptions): TranscriptViewportController {
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const followingLatestRef = useRef(true);
  const activeUserMessageRef = useRef<HTMLElement | null>(null);
  const prependAnchorRef = useRef<PrependAnchor | null>(null);
  const previousConversationRef = useRef<ConversationKey>(conversationKey);
  const mountedRef = useRef(false);
  const reducedMotion = useMediaQuery(REDUCED_MOTION_QUERY);
  const [followingLatest, setFollowingLatestState] = useState(true);
  const [navigationState, setNavigationState] = useState<NavigationState>({
    activeUserMessageIndex: null,
    userMessageCount: 0,
  });

  const setFollowingLatest = useCallback((following: boolean) => {
    followingLatestRef.current = following;
    setFollowingLatestState((current) => current === following ? current : following);
  }, []);

  const refreshNavigation = useCallback(() => {
    const viewport = transcriptRef.current;
    if (!viewport) return;
    const messages = userMessages(viewport, userMessageSelector);
    const activeIndex = activeUserMessageRef.current
      ? messages.indexOf(activeUserMessageRef.current)
      : -1;
    if (activeIndex < 0) activeUserMessageRef.current = null;
    const next = {
      activeUserMessageIndex: activeIndex < 0 ? null : activeIndex,
      userMessageCount: messages.length,
    };
    setNavigationState((current) => (
      current.activeUserMessageIndex === next.activeUserMessageIndex
      && current.userMessageCount === next.userMessageCount
        ? current
        : next
    ));
  }, [userMessageSelector]);

  const clearNavigation = useCallback(() => {
    activeUserMessageRef.current = null;
    setNavigationState((current) => (
      current.activeUserMessageIndex == null
        ? current
        : { ...current, activeUserMessageIndex: null }
    ));
  }, []);

  const jumpToLatest = useCallback(() => {
    const viewport = transcriptRef.current;
    if (!viewport) return;
    clearNavigation();
    setFollowingLatest(true);
    if (!reducedMotion && typeof viewport.scrollTo === "function") {
      viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
      return;
    }
    setScrollTop(viewport, viewport.scrollHeight);
  }, [clearNavigation, reducedMotion, setFollowingLatest]);

  const goToUserMessage = useCallback((direction: -1 | 1) => {
    const viewport = transcriptRef.current;
    if (!viewport) return;
    const messages = userMessages(viewport, userMessageSelector);
    if (messages.length === 0) return;

    const currentIndex = activeUserMessageRef.current
      ? messages.indexOf(activeUserMessageRef.current)
      : -1;
    const targetIndex = currentIndex < 0
      ? (direction < 0 ? messages.length - 1 : 0)
      : currentIndex + direction;
    const target = messages[targetIndex];
    if (!target) return;

    activeUserMessageRef.current = target;
    setFollowingLatest(false);
    setNavigationState({
      activeUserMessageIndex: targetIndex,
      userMessageCount: messages.length,
    });
    const behavior: ScrollBehavior = reducedMotion ? "auto" : "smooth";
    if (typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ behavior, block: "start", inline: "nearest" });
    } else {
      setScrollTop(viewport, target.offsetTop);
    }
  }, [reducedMotion, setFollowingLatest, userMessageSelector]);

  const goToPreviousUserMessage = useCallback(
    () => goToUserMessage(-1),
    [goToUserMessage],
  );
  const goToNextUserMessage = useCallback(
    () => goToUserMessage(1),
    [goToUserMessage],
  );

  const onTranscriptScroll = useCallback<UIEventHandler<HTMLDivElement>>((event) => {
    setFollowingLatest(nearBottom(event.currentTarget, bottomThreshold));
    refreshNavigation();
  }, [bottomThreshold, refreshNavigation, setFollowingLatest]);

  const prepareForHistoryPrepend = useCallback(() => {
    const viewport = transcriptRef.current;
    if (!viewport) return;
    prependAnchorRef.current = {
      conversationKey,
      scrollHeight: viewport.scrollHeight,
      scrollTop: viewport.scrollTop,
    };
  }, [conversationKey]);

  const cancelHistoryPrepend = useCallback(() => {
    prependAnchorRef.current = null;
  }, []);

  useLayoutEffect(() => {
    const viewport = transcriptRef.current;
    if (!viewport) return;
    const conversationChanged = (
      !mountedRef.current || previousConversationRef.current !== conversationKey
    );
    mountedRef.current = true;
    previousConversationRef.current = conversationKey;

    if (conversationChanged) {
      prependAnchorRef.current = null;
      activeUserMessageRef.current = null;
      setFollowingLatest(true);
      setScrollTop(viewport, viewport.scrollHeight);
      refreshNavigation();
      return;
    }

    const prependAnchor = prependAnchorRef.current;
    if (prependAnchor) {
      prependAnchorRef.current = null;
      if (prependAnchor.conversationKey === conversationKey) {
        const addedHeight = viewport.scrollHeight - prependAnchor.scrollHeight;
        setScrollTop(viewport, Math.max(0, prependAnchor.scrollTop + addedHeight));
        setFollowingLatest(nearBottom(viewport, bottomThreshold));
        refreshNavigation();
        return;
      }
    }

    if (followingLatestRef.current) {
      setScrollTop(viewport, viewport.scrollHeight);
    }
    refreshNavigation();
  }, [
    bottomThreshold,
    contentRevision,
    conversationKey,
    refreshNavigation,
    setFollowingLatest,
  ]);

  const activeUserMessageIndex = navigationState.activeUserMessageIndex;
  const userMessageCount = navigationState.userMessageCount;

  return {
    transcriptRef,
    onTranscriptScroll,
    prepareForHistoryPrepend,
    cancelHistoryPrepend,
    followingLatest,
    navigation: {
      activeUserMessageIndex,
      canGoToNextUserMessage: (
        activeUserMessageIndex != null
        && activeUserMessageIndex < userMessageCount - 1
      ),
      canGoToPreviousUserMessage: (
        userMessageCount > 0
        && activeUserMessageIndex !== 0
      ),
      goToNextUserMessage,
      goToPreviousUserMessage,
      jumpToLatest,
      showJumpToLatest: !followingLatest,
      userMessageCount,
    },
  };
}
