import { useEffect, useState } from "react";
import { workspaceApi } from "./workspaceApi";
import type { ResearchStatus } from "./workspaceApi";
import LabcatMascot from "./LabcatMascot";
import "./mascotPlacements.css";

export interface ResearchSubmission {
  runId: string;
  startedAt: number;
}

export function beginResearchSubmission(): ResearchSubmission {
  return { runId: crypto.randomUUID(), startedAt: Date.now() };
}

function elapsedLabel(milliseconds: number) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return seconds < 60
    ? `${seconds}s`
    : `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
}

/** Mount only for the active message request. Polling never submits research. */
export default function ResearchProgress({
  chatId,
  submission,
}: {
  chatId: string | null;
  submission: ResearchSubmission;
}) {
  const [observed, setObserved] = useState<{
    chatId: string;
    runId: string;
    value: ResearchStatus;
  } | null>(null);
  const [connectionError, setConnectionError] = useState(false);
  const [checking, setChecking] = useState(false);
  const [retry, setRetry] = useState(0);
  const [now, setNow] = useState(Date.now());
  const status =
    observed?.runId === submission.runId && observed.chatId === chatId
      ? observed.value
      : null;
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    let sequence = status?.sequence ?? -1;
    setConnectionError(false);
    setChecking(false);
    if (!chatId) return () => controller.abort();
    async function poll() {
      if (controller.signal.aborted) return;
      setChecking(true);
      try {
        const next = await workspaceApi.researchStatus(
          chatId!,
          submission.runId,
          controller.signal,
        );
        if (controller.signal.aborted) return;
        if (next.run_id === submission.runId && next.sequence >= sequence) {
          sequence = next.sequence;
          setObserved({
            chatId: chatId!,
            runId: submission.runId,
            value: next,
          });
        }
        if (next.status === "idle") setObserved(null);
        setConnectionError(false);
      } catch {
        if (!controller.signal.aborted) setConnectionError(true);
      } finally {
        if (!controller.signal.aborted) {
          setChecking(false);
          timer = window.setTimeout(() => void poll(), 1000);
        }
      }
    }
    void poll();
    return () => {
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [chatId, submission.runId, retry]);
  const heading = connectionError
    ? "Waiting for a progress connection"
    : !chatId
      ? "Creating your saved chat"
      : status
        ? status.phase.replaceAll("_", " ")
        : "Waiting for research progress";
  const message = connectionError
    ? "Progress updates are unavailable. Your request may still be running; reconnecting automatically."
    : !chatId
      ? "Saving a chat before submitting your question."
      : status?.message ||
        "Waiting for the research service to report its current stage.";
  return (
    <aside
      className={`research-progress-panel mascot-progress-panel ${connectionError ? "connection-waiting" : ""}`}
      aria-label="Research progress"
    >
      <LabcatMascot scene="beaker" className="mascot-progress" />
      <div className="research-progress-heading">
        <span className="loading-ring" aria-hidden="true" />
        <div
          className="research-progress-stage"
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          <strong>{heading}</strong>
          <p>{message}</p>
        </div>
        <span className="research-elapsed" role="timer" aria-live="off">
          Elapsed {elapsedLabel(now - submission.startedAt)}
        </span>
      </div>
      {connectionError && status && (
        <p className="research-last-stage">
          Last reported stage: {status.phase.replaceAll("_", " ")}.
        </p>
      )}
      {status && (
        <p className="research-last-update">
          Last stage update {elapsedLabel(now - Date.parse(status.updated_at!))}{" "}
          ago
          {status.status === "completed" || status.status === "failed"
            ? " · Waiting for the saved response."
            : ""}
        </p>
      )}
      {connectionError && (
        <button
          className="quiet-button"
          type="button"
          disabled={checking}
          onClick={() => setRetry((value) => value + 1)}
        >
          {checking ? "Checking progress…" : "Check progress now"}
        </button>
      )}
    </aside>
  );
}
