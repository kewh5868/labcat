import { useEffect, useRef, useState } from "react";
import { errorMessage } from "./workspaceApi";
import type { ReportPin, ResearchReport } from "./workspaceApi";
import "./reportPins.css";

export type ReportPinAction =
  | { type: "tracking"; chatId: string; tracking: boolean }
  | { type: "update_snapshot"; pin: ReportPin; reportId: string };

type Props = {
  report: ResearchReport;
  trackingPin?: ReportPin | null;
  snapshots?: ReportPin[];
  onSnapshot: () => Promise<void>;
  onAction?: (action: ReportPinAction) => Promise<void>;
  disabled?: boolean;
  requiresProject?: boolean;
};

function savedDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "Saved revision"
    : date.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
}

export default function ReportPinControls({
  report,
  trackingPin,
  snapshots = [],
  onSnapshot,
  onAction,
  disabled = false,
  requiresProject = false,
}: Props) {
  const [busy, setBusy] = useState<"" | "snapshot" | "tracking" | "update">(""),
    [error, setError] = useState("");
  const lock = useRef(false),
    mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const tracking =
    trackingPin ??
    report.tracking_pin ??
    (report.pin?.mode === "latest" ? report.pin : null);
  const current =
    report.latest_report_id ??
    (["complete", "partial"].includes(report.stage) ? report.id : null);
  const updatePin =
    report.pin?.mode === "snapshot" && report.pin.report_id !== current
      ? report.pin
      : null;
  const alreadySavedCurrent = snapshots.some(
    (pin) => pin.mode === "snapshot" && pin.report_id === current,
  );
  async function perform(
    kind: Exclude<typeof busy, "">,
    action: () => Promise<void>,
  ) {
    if (disabled || lock.current) return;
    lock.current = true;
    setBusy(kind);
    setError("");
    try {
      await action();
    } catch (failure) {
      if (mounted.current) setError(errorMessage(failure));
    } finally {
      lock.current = false;
      if (mounted.current) setBusy("");
    }
  }
  return (
    <div className="report-pin-controls" aria-busy={Boolean(busy)}>
      {report.pin && (
        <span
          className={`report-pin-label report-pin-${report.pin.mode}`}
          title={
            report.pin.mode === "latest"
              ? "This project pin follows the newest completed report from this chat."
              : "This snapshot keeps the report and its saved format until you explicitly update it."
          }
        >
          {report.pin.mode === "latest" ? "Tracking latest" : "Snapshot"} ·{" "}
          {savedDate(
            report.pin.mode === "latest"
              ? report.pin.updated_at
              : report.pin.created_at,
          )}
        </span>
      )}
      <div className="report-pin-actions">
        <button
          type="button"
          className={`pin-button ${report.pinned ? "is-pinned" : ""}`}
          aria-pressed={report.pinned}
          disabled={disabled || Boolean(busy)}
          title={
            requiresProject
              ? "Choose a project first, then preserve this report revision as a snapshot."
              : report.pinned
                ? "Remove this snapshot from the project. Its report remains in chat history, and tracking is unchanged."
                : "Preserve this report revision and its saved format in the project. Later prompts will not change it."
          }
          onClick={() => void perform("snapshot", onSnapshot)}
        >
          <span aria-hidden="true">⌑</span>
          {busy === "snapshot"
            ? "Saving…"
            : report.pinned
              ? "Unpin snapshot"
              : "Pin snapshot"}
        </button>
        {onAction && (
          <button
            type="button"
            className={`pin-button ${tracking ? "is-pinned" : ""}`}
            aria-pressed={Boolean(tracking)}
            disabled={disabled || Boolean(busy) || !current}
            title={
              requiresProject
                ? "Choose a project first, then pin a report that follows this chat’s newest completed revision."
                : tracking
                  ? "Stop following this chat’s newest completed report. Existing snapshots and chat history remain saved."
                  : "Keep one project pin that automatically shows this chat’s newest completed report. Saved snapshots stay unchanged."
            }
            onClick={() =>
              void perform("tracking", () =>
                onAction({
                  type: "tracking",
                  chatId: report.chat_id,
                  tracking: !tracking,
                }),
              )
            }
          >
            <span aria-hidden="true">⌑</span>
            {busy === "tracking"
              ? "Saving…"
              : tracking
                ? "Unpin tracking"
                : "Pin tracking"}
          </button>
        )}
      </div>
      {requiresProject && (
        <small className="report-pin-project-hint">
          Choose a project to save either pin.
        </small>
      )}
      {onAction &&
        !requiresProject &&
        updatePin &&
        current &&
        !alreadySavedCurrent && (
          <div className="snapshot-update-controls">
            <button
              type="button"
              disabled={disabled || Boolean(busy)}
              title="Replace only this saved snapshot with the chat’s latest completed revision. The earlier report stays in chat history. Use Pin snapshot on the latest report to preserve both in the project."
              onClick={() =>
                void perform("update", () =>
                  onAction({
                    type: "update_snapshot",
                    pin: updatePin,
                    reportId: current,
                  }),
                )
              }
            >
              {busy === "update"
                ? "Updating…"
                : "Update this snapshot to latest"}
            </button>
            <small>
              This replaces the snapshot shown here. The earlier revision
              remains in chat history.
            </small>
          </div>
        )}
      {error && (
        <p className="pin-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
