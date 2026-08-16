import { useId } from "react";

import type { TranscriptNavigationModel } from "./useTranscriptViewport";
import "./TranscriptNavigation.css";

interface TranscriptNavigationProps {
  model: TranscriptNavigationModel;
  transcriptId?: string;
}

/**
 * Compact, keyboard-operable transcript navigation. It is deliberately a
 * sibling of the transcript rather than part of any message, so it cannot
 * disturb OrderedWorkTranscript's chronological DOM order.
 */
export function TranscriptNavigation({ model, transcriptId }: TranscriptNavigationProps) {
  const statusId = `transcript-navigation-${useId().replaceAll(":", "")}`;
  if (model.userMessageCount === 0 && !model.showJumpToLatest) return null;
  const position = model.activeUserMessageIndex == null
    ? "No user message selected"
    : `User message ${model.activeUserMessageIndex + 1} of ${model.userMessageCount}`;

  return (
    <nav
      aria-describedby={statusId}
      aria-label="Transcript navigation"
      className="transcript-navigation"
    >
      <button
        aria-controls={transcriptId}
        aria-label="Previous user message"
        disabled={!model.canGoToPreviousUserMessage}
        onClick={model.goToPreviousUserMessage}
        title="Previous user message"
        type="button"
      >
        <svg aria-hidden fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" viewBox="0 0 24 24" width="14">
          <path d="m7 14 5-5 5 5" />
        </svg>
      </button>
      <button
        aria-controls={transcriptId}
        aria-label="Next user message"
        disabled={!model.canGoToNextUserMessage}
        onClick={model.goToNextUserMessage}
        title="Next user message"
        type="button"
      >
        <svg aria-hidden fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" viewBox="0 0 24 24" width="14">
          <path d="m7 10 5 5 5-5" />
        </svg>
      </button>
      {model.showJumpToLatest && (
        <button
          aria-controls={transcriptId}
          aria-label="Jump to latest"
          className="transcript-navigation-latest"
          onClick={model.jumpToLatest}
          title="Jump to latest"
          type="button"
        >
          <svg aria-hidden fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" viewBox="0 0 24 24" width="14">
            <path d="m7 9 5 5 5-5" />
            <path d="M7 15h10" />
          </svg>
        </button>
      )}
      <output
        aria-atomic="true"
        aria-live="polite"
        className="transcript-navigation-status"
        id={statusId}
        role="status"
      >
        {position}
      </output>
    </nav>
  );
}
