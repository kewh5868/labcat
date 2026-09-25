import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import ChatIdentity from "./ChatIdentity";
import { workspaceApi } from "./workspaceApi";
import type {
  ChatSearchMatch,
  Project,
  WorkspaceSearchResults,
} from "./workspaceApi";

export default function WorkspaceSearch({
  children,
  revision,
  onProject,
  onChat,
}: {
  children: ReactNode;
  revision: number;
  onProject: (project: Project) => void;
  onChat: (match: ChatSearchMatch) => void;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const term = query.trim();
  const [results, setResults] = useState<WorkspaceSearchResults | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    setResults(null);
    setFailed(false);
    if (!term) {
      setBusy(false);
      return;
    }
    const controller = new AbortController();
    setBusy(true);
    const timer = window.setTimeout(() => {
      workspaceApi
        .search(term, controller.signal)
        .then((next) => {
          if (!controller.signal.aborted) setResults(next);
        })
        .catch(() => {
          if (!controller.signal.aborted) setFailed(true);
        })
        .finally(() => {
          if (!controller.signal.aborted) setBusy(false);
        });
    }, 200);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [term, retry, revision]);
  const visible = results?.query === term ? results : null;
  function clear() {
    setQuery("");
    input.current?.focus();
  }
  return (
    <>
      <div
        className="sidebar-search"
        role="search"
        aria-label="Search saved workspace"
      >
        <label className="sr-only" htmlFor={id}>
          Search chats and projects
        </label>
        <svg
          className="sidebar-search-icon"
          aria-hidden="true"
          viewBox="0 0 20 20"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        >
          <circle cx="8.5" cy="8.5" r="5.5" />
          <path d="m13 13 4 4" />
        </svg>
        <input
          ref={input}
          id={id}
          type="search"
          placeholder="Search workspace"
          value={query}
          maxLength={200}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              clear();
            }
          }}
          title="Search saved names, messages and reports"
        />
        {query && (
          <button
            type="button"
            aria-label="Clear workspace search"
            title="Clear search"
            onClick={clear}
          >
            ×
          </button>
        )}
      </div>
      {!term ? (
        children
      ) : (
        <div
          className="sidebar-history sidebar-search-results"
          aria-label="Workspace search results"
          aria-busy={busy}
        >
          <p className="sidebar-search-status" role="status">
            {busy
              ? "Searching saved chats and projects…"
              : failed
                ? "Search is unavailable."
                : visible
                  ? `${visible.projects.length} projects · ${visible.chats.length} chats`
                  : ""}
          </p>
          {failed ? (
            <div className="sidebar-search-retry">
              <button
                type="button"
                className="text-button"
                onClick={() => setRetry((value) => value + 1)}
              >
                Try search again
              </button>
            </div>
          ) : (
            <>
              <section
                className="sidebar-history-section"
                aria-labelledby={`${id}-projects`}
              >
                <div className="project-list-heading">
                  <span className="small-label" id={`${id}-projects`}>
                    PROJECTS
                  </span>
                </div>
                <nav
                  className="project-list sidebar-section-list"
                  aria-label="Project search results"
                  tabIndex={0}
                >
                  {visible?.projects.map((match) => (
                    <button
                      type="button"
                      className="sidebar-search-result"
                      key={match.project.id}
                      onClick={() => onProject(match.project)}
                    >
                      <strong>{match.project.name}</strong>
                      {match.match_field === "description" && (
                        <span>{match.snippet}</span>
                      )}
                      <small>{match.project.chat_count} chats</small>
                    </button>
                  ))}
                  {!busy && visible && !visible.projects.length && (
                    <p className="sidebar-empty">No matching projects.</p>
                  )}
                </nav>
              </section>
              <section
                className="sidebar-history-section"
                aria-labelledby={`${id}-chats`}
              >
                <div className="project-list-heading">
                  <span className="small-label" id={`${id}-chats`}>
                    CHATS
                  </span>
                </div>
                <nav
                  className="all-chat-list sidebar-section-list"
                  aria-label="Chat search results"
                  tabIndex={0}
                >
                  {visible?.chats.map((match) => (
                    <button
                      type="button"
                      className="sidebar-search-result"
                      key={match.chat.id}
                      onClick={() => onChat(match)}
                    >
                      <ChatIdentity
                        title={match.chat.title}
                        number={match.chat.chat_number}
                      />
                      <small>
                        {match.project_name ?? "General Chats"}
                        {match.match_field !== "title" &&
                          ` · ${match.match_field === "message" ? "Message" : "Report"} match`}
                      </small>
                      {match.match_field !== "title" && (
                        <span>{match.snippet}</span>
                      )}
                    </button>
                  ))}
                  {!busy && visible && !visible.chats.length && (
                    <p className="sidebar-empty">No matching chats.</p>
                  )}
                </nav>
              </section>
              {visible?.has_more && (
                <p className="sidebar-search-status">
                  More matches available. Add more words to narrow your search.
                </p>
              )}
            </>
          )}
        </div>
      )}
    </>
  );
}
