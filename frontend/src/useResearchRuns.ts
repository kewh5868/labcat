import { useCallback, useEffect, useRef, useState } from "react";
import {
  workspaceApi,
  errorMessage,
  ResearchRequestError,
} from "./workspaceApi";
import type { Chat, ChatDetail, ResearchReport } from "./workspaceApi";
import type { ResearchSubmission } from "./ResearchProgress";

export interface WorkspaceRun {
  submission: ResearchSubmission;
  status: "running" | "completed" | "failed";
  prompt?: string;
  error?: string;
  setupRequired?: boolean;
  completionKey?: string;
  revision: number;
  requestPending: boolean;
  observed: boolean;
}
export type WorkspaceResearch = ReturnType<typeof useResearchRuns>;

/** Celebrate only a new report returned by this submission, never saved history. */
export function completedResearchKey(
  next: ChatDetail,
  previous: ResearchReport[] = [],
): string {
  const response = next.messages.at(-1);
  if (response?.role !== "assistant" || !response.report_id) return "";
  return next.reports.some(
    (report) =>
      report.id === response.report_id &&
      report.message_id === response.id &&
      ["complete", "partial"].includes(report.stage) &&
      !previous.some((saved) => saved.id === report.id),
  )
    ? response.report_id
    : "";
}

/** The workspace owns submissions; navigating views only detaches their display. */
export function useResearchRuns(onChatChanged: (chat: Chat) => void) {
  const [runs, setRuns] = useState<Record<string, WorkspaceRun>>({});
  const current = useRef(runs),
    alive = useRef(true),
    changed = useRef(onChatChanged);
  changed.current = onChatChanged;
  const update = useCallback((chatId: string, run: WorkspaceRun) => {
    if (!alive.current) return;
    const next = { ...current.current, [chatId]: run };
    // Keep completed bookkeeping bounded without dropping ongoing work.
    const finished = Object.keys(next).filter(
      (id) => next[id].status !== "running",
    );
    for (const id of finished.slice(0, Math.max(0, finished.length - 32)))
      delete next[id];
    current.current = next;
    setRuns(next);
  }, []);
  const start = useCallback(
    async (
      chatId: string,
      content: string,
      profile: string,
      submission: ResearchSubmission,
      structures: boolean,
      previousReports: ResearchReport[] = [],
    ): Promise<ChatDetail> => {
      if (current.current[chatId]?.status === "running")
        throw new Error("The workspace is still researching in this chat.");
      const run: WorkspaceRun = {
        submission,
        status: "running",
        prompt: content,
        revision: 0,
        requestPending: true,
        observed: false,
      };
      update(chatId, run);
      try {
        // No view-owned signal: this request belongs to the saved chat, not its screen.
        const result = await workspaceApi.message(
          chatId,
          content,
          profile,
          submission.runId,
          structures,
        );
        if (
          alive.current &&
          current.current[chatId]?.submission.runId === submission.runId
        ) {
          changed.current(result.chat);
          update(chatId, {
            ...current.current[chatId],
            status: "completed",
            completionKey: completedResearchKey(result, previousReports),
            requestPending: false,
            revision: current.current[chatId].revision + 1,
            error: undefined,
          });
        }
        return result;
      } catch (error) {
        if (
          alive.current &&
          current.current[chatId]?.submission.runId === submission.runId
        ) {
          const latest = current.current[chatId];
          // A failed HTTP connection does not establish that server work stopped.
          // Release the pending request flag and let read-only progress reconcile it.
          update(
            chatId,
            error instanceof ResearchRequestError
              ? {
                  ...latest,
                  status: "failed",
                  requestPending: false,
                  revision: latest.revision + 1,
                  error: errorMessage(error),
                  setupRequired: error.setupRequired,
                }
              : { ...latest, requestPending: false },
          );
        }
        throw error;
      }
    },
    [update],
  );
  const consumeCompletion = useCallback(
    (chatId: string, runId: string) => {
      const run = current.current[chatId];
      if (run?.submission.runId === runId && run.completionKey)
        update(chatId, { ...run, completionKey: undefined });
    },
    [update],
  );
  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    let timer: number | undefined;
    async function poll() {
      try {
        const active = await workspaceApi.activeResearch(controller.signal);
        if (controller.signal.aborted) return;
        const identities = new Set(
          active.map((run) => `${run.chat_id}:${run.run_id}`),
        );
        for (const status of active) {
          const previous = current.current[status.chat_id];
          if (
            previous?.submission.runId === status.run_id &&
            previous.status !== "running"
          )
            continue;
          const same = previous?.submission.runId === status.run_id;
          if (!same && previous?.requestPending) continue;
          update(status.chat_id, {
            ...(same ? previous : { revision: 0, requestPending: false }),
            submission: {
              runId: status.run_id!,
              startedAt: Date.parse(status.started_at!),
            },
            status: "running",
            observed: true,
          });
          if (!same || !previous.observed) {
            const detail = await workspaceApi.chat(
              status.chat_id,
              controller.signal,
            );
            if (!controller.signal.aborted) changed.current(detail.chat);
          }
        }
        for (const [chatId, run] of Object.entries(current.current)) {
          if (
            run.status !== "running" ||
            run.requestPending ||
            identities.has(`${chatId}:${run.submission.runId}`)
          )
            continue;
          const status = await workspaceApi.researchStatus(
            chatId,
            run.submission.runId,
            controller.signal,
          );
          if (
            controller.signal.aborted ||
            current.current[chatId]?.submission.runId !==
              run.submission.runId ||
            current.current[chatId]?.status !== "running"
          )
            continue;
          if (status.status === "running") continue;
          const detail = await workspaceApi.chat(chatId, controller.signal);
          if (
            controller.signal.aborted ||
            current.current[chatId]?.submission.runId !==
              run.submission.runId ||
            current.current[chatId]?.status !== "running"
          )
            continue;
          changed.current(detail.chat);
          update(chatId, {
            ...run,
            requestPending: false,
            status: status.status === "completed" ? "completed" : "failed",
            revision: run.revision + 1,
            error:
              status.status === "completed"
                ? undefined
                : "Research is no longer running. Review the saved response before trying again.",
          });
        }
      } catch {
        /* Keep last known running state during a progress connection outage. */
      } finally {
        if (!controller.signal.aborted)
          timer = window.setTimeout(() => void poll(), 2000);
      }
    }
    void poll();
    return () => {
      alive.current = false;
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [update]);
  return { runs, start, consumeCompletion };
}
