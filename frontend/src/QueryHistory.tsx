import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { Message, ResearchReport } from "./workspaceApi";
import { shortlistPreview } from "./ReportContent";
import "./queryHistory.css";

export interface QueryTurn {
  question: Message;
  responses: Message[];
  reports: ResearchReport[];
}

/** Message order is authoritative, including equal timestamps. A report must
 * belong to its saved assistant response; never pair by result-array position. */
export function queryHistory(
  messages: Message[],
  reports: ResearchReport[],
): QueryTurn[] {
  const turns: QueryTurn[] = [];
  for (const message of messages) {
    if (message.role === "user")
      turns.push({ question: message, responses: [], reports: [] });
    else {
      const turn = turns.at(-1);
      if (!turn || turn.question.chat_id !== message.chat_id) continue;
      turn.responses.push(message);
      const report = reports.find(
        (item) =>
          item.id === message.report_id &&
          item.message_id === message.id &&
          item.chat_id === message.chat_id,
      );
      if (report && !turn.reports.some((item) => item.id === report.id))
        turn.reports.push(report);
    }
  }
  return turns;
}

export function QueryTime({ value }: { value: string }) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? null : (
    <time dateTime={value} title={date.toLocaleString()}>
      {date.toLocaleString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })}
    </time>
  );
}

function SavedReport({
  report,
  renderReport,
  searchReportId,
}: {
  report: ResearchReport;
  renderReport: (report: ResearchReport) => ReactNode;
  searchReportId?: string | null;
}) {
  const [open, setOpen] = useState(searchReportId === report.id);
  useEffect(() => {
    if (searchReportId === report.id) setOpen(true);
  }, [searchReportId, report.id]);
  const preview =
    shortlistPreview(report.pi_summary) ??
    shortlistPreview(report.technical_audit);
  return (
    <div className="query-saved-result" data-search-report={report.id}>
      {preview ? (
        <div
          className="query-shortlist-scroll"
          tabIndex={0}
          role="region"
          aria-label="Saved shortlist preview, scroll horizontally if needed"
        >
          <table className="query-shortlist">
            <caption>
              Saved shortlist · {preview.rows.length} of {preview.total}{" "}
              materials
            </caption>
            <thead>
              <tr>
                {preview.headers.map((header) => (
                  <th scope="col" key={header}>
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((row, index) => (
                <tr key={index}>
                  {row.map((cell, column) => (
                    <td key={column}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="query-result-note">
          {["complete", "partial"].includes(report.stage)
            ? "No compact shortlist is available for this saved report."
            : "This request did not produce a shortlist."}
        </p>
      )}
      <details
        className="query-full-report"
        open={open}
        onToggle={(event) => setOpen(event.currentTarget.open)}
      >
        <summary>
          View saved report{" "}
          <span>{report.stage === "partial" ? "Partial results" : ""}</span>
        </summary>
        {open && renderReport(report)}
      </details>
    </div>
  );
}

export default function QueryHistory({
  turns,
  renderReport,
  renderMessage,
  searchReportId,
}: {
  turns: QueryTurn[];
  renderReport: (report: ResearchReport) => ReactNode;
  renderMessage: (message: Message) => ReactNode;
  searchReportId?: string | null;
}) {
  const section = useRef<HTMLElement>(null);
  if (!turns.length) return null;
  return (
    <section
      ref={section}
      className="query-history"
      aria-label="Earlier questions"
      tabIndex={-1}
    >
      <header className="query-history-heading">
        <h2>Earlier questions</h2>
        <span>
          {turns.length} {turns.length === 1 ? "question" : "questions"}
        </span>
      </header>
      <ol className="query-history-list">
        {turns.map((turn, index) => (
          <li key={turn.question.id}>
            <article
              className="query-history-card"
              data-search-message={turn.question.id}
            >
              <header>
                <h3>Question {index + 1}</h3>
                <QueryTime value={turn.question.created_at} />
              </header>
              <p className="query-history-question">{turn.question.content}</p>
              {turn.reports.map((report) => (
                <SavedReport
                  key={report.id}
                  report={report}
                  renderReport={renderReport}
                  searchReportId={searchReportId}
                />
              ))}
              {!turn.reports.length && (
                <p className="query-result-note">
                  {turn.responses.some(
                    (message) =>
                      message.intake?.status === "clarification_required",
                  )
                    ? "Clarification requested · no shortlist yet."
                    : turn.responses.some(
                          (message) => message.intake?.status === "refused",
                        )
                      ? "Request declined · no shortlist generated."
                      : "No saved shortlist for this question."}
                </p>
              )}
              {turn.responses.length > 0 && (
                <details className="query-original-messages">
                  <summary>
                    Original response{turn.responses.length === 1 ? "" : "s"}
                  </summary>
                  {turn.responses.map((message) => (
                    <div key={message.id} data-search-message={message.id}>
                      {renderMessage(message)}
                    </div>
                  ))}
                </details>
              )}
            </article>
          </li>
        ))}
      </ol>
    </section>
  );
}
