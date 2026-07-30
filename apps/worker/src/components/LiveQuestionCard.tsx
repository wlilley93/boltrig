import { useRef, useState } from "react";
import type { QuestionEntry } from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";

export function LiveQuestionCard({ question }: { question: QuestionEntry }) {
  const [answer, setAnswer] = useState("");
  const [status, setStatus] = useState("");
  const [answered, setAnswered] = useState(false);
  const inFlight = useRef(false);

  async function submit(value: string) {
    const text = question.secure ? value : value.trim();
    if (!text || inFlight.current || answered) return;
    inFlight.current = true;
    setStatus("Sending…");
    try {
      const result = await client.answerQuestion(question.questionId, text);
      if (result.status === "ok") {
        setAnswered(true);
        setAnswer("");
        setStatus("Answer accepted. The run is continuing.");
      } else {
        setStatus(result.reason ?? `Answer was not accepted (${result.status}).`);
      }
    } catch {
      setStatus("The answer could not be sent. It is safe to retry.");
    } finally {
      inFlight.current = false;
    }
  }

  return (
    <div className="approval-card live-question">
      <strong>Question from this run</strong>
      <p>{question.prompt}</p>
      {question.secure && (
        <p className="muted small">
          Secure answer
          {question.securePurpose ? ` · used only for ${question.securePurpose}` : ""}
          . The value is sealed and is not shown to the agent.
        </p>
      )}
      {!answered && (
        <>
          {question.choices.slice(0, 10).map((choice) => (
            <button
              className="secondary-button"
              key={choice}
              onClick={() => void submit(choice)}
            >
              {choice.slice(0, 200)}
            </button>
          ))}
          <div className="inline-actions">
            <input
              className="field-control"
              aria-label={question.secure ? "Secure live question answer" : "Live question answer"}
              type={question.secure ? "password" : "text"}
              autoComplete="off"
              spellCheck={!question.secure}
              maxLength={4_000}
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
            />
            <button
              className="primary-button"
              disabled={question.secure ? !answer : !answer.trim()}
              onClick={() => void submit(answer)}
            >
              Answer
            </button>
          </div>
        </>
      )}
      {status && <p className={answered ? "muted small" : "notice"} role="status">{status}</p>}
    </div>
  );
}
