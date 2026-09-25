import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { brandName, brandTagline, LabcatMark } from "./Brand";
import "./workspace.css";

import type { StatusReport } from "./api";
import { fetchStatus } from "./api";

type IconName =
  | "overview"
  | "shield"
  | "plan"
  | "arrow"
  | "download"
  | "computer"
  | "model"
  | "source"
  | "check";

function Icon({
  name,
  className = "",
}: {
  name: IconName;
  className?: string;
}) {
  const shapes: Record<IconName, ReactNode> = {
    overview: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </>
    ),
    shield: (
      <>
        <path d="M12 3 4.5 6v5.5c0 4.4 3.1 7.7 7.5 9.5 4.4-1.8 7.5-5.1 7.5-9.5V6L12 3Z" />
        <path d="m8.5 12 2.2 2.2 4.8-4.8" />
      </>
    ),
    plan: (
      <>
        <circle cx="5" cy="5" r="2" />
        <circle cx="19" cy="19" r="2" />
        <path d="M5 7v8a4 4 0 0 0 4 4h8M7 5h8a4 4 0 0 1 4 4v4" />
        <path d="m16 10 3 3 3-3" />
      </>
    ),
    arrow: (
      <>
        <path d="M5 12h14m-5-5 5 5-5 5" />
      </>
    ),
    download: (
      <>
        <path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4" />
      </>
    ),
    computer: (
      <>
        <rect x="3" y="4" width="18" height="12" rx="2" />
        <path d="M8 21h8m-4-5v5" />
      </>
    ),
    model: (
      <>
        <path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z" />
        <path d="m4 7.5 8 4.5 8-4.5M12 12v9" />
      </>
    ),
    source: (
      <>
        <ellipse cx="12" cy="5" rx="8" ry="3" />
        <path d="M4 5v7c0 4 16 4 16 0V5M4 12v7c0 4 16 4 16 0v-7" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
  };
  return (
    <svg
      className={`icon ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {shapes[name]}
    </svg>
  );
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; report: StatusReport };

export default function App() {
  return (
    <WorkspaceShell>
      <Overview />
    </WorkspaceShell>
  );
}

function Overview() {
  const style = "audit" as const;
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setState({ status: "loading" });
    const timeout = window.setTimeout(() => {
      controller.abort();
      if (active)
        setState({
          status: "error",
          message:
            "The local application took too long to respond. Check that it is running and try again.",
        });
    }, 15000);
    fetchStatus(style, controller.signal)
      .then((report) => {
        if (active) setState({ status: "ready", report });
      })
      .catch((error: unknown) => {
        if (!active || controller.signal.aborted) return;
        const message =
          error instanceof Error && error.message.startsWith("The ")
            ? error.message
            : "Unable to reach the application status service. Check that the local application is running.";
        setState({ status: "error", message });
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [style, attempt]);

  const report = state.status === "ready" ? state.report : null;

  return (
    <section className="connection-overview" aria-label="Workspace services">
      <details className="connection-capabilities card">
        <summary>Research process and application capabilities</summary>

        {state.status === "loading" && (
          <p role="status">Reading application capabilities…</p>
        )}
        {state.status === "error" && (
          <div role="alert">
            <p>{state.message}</p>
            <button
              type="button"
              className="quiet-button"
              onClick={() => setAttempt((value) => value + 1)}
            >
              Reload capabilities
            </button>
          </div>
        )}
        {report && <ReportContent report={report} />}
      </details>
    </section>
  );
}

function ReportContent({ report }: { report: StatusReport }) {
  return (
    <>
      <div className="framework-banner" role="status">
        <span className="banner-icon">
          <Icon name="check" />
        </span>
        <div>
          <strong>Application capabilities</strong>
          <p>{report.message}</p>
        </div>
        <span className="outline-badge">{report.stage}</span>
      </div>

      <section
        className="card shortlist-card"
        aria-labelledby="shortlist-title"
      >
        <div className="card-header">
          <div>
            <p className="eyebrow">RESEARCH OUTPUT</p>
            <h2 id="shortlist-title">A report for each question.</h2>
          </div>
          <span className="neutral-badge">Summary + Technical View</span>
        </div>
        <div className="empty-state">
          <h3>Explore materials with the command-line interface.</h3>
          <p>
            The command-line research interface searches public sources for your
            research question. Reports preserve references, ranking rationale
            and missing evidence. A scored shortlist is generated only when
            verified material properties support it.
          </p>
          <div className="output-qualities">
            <span>
              <Icon name="source" />
              Cited evidence
            </span>
            <span>
              <Icon name="plan" />
              Ranking rationale
            </span>
            <span>
              <Icon name="shield" />
              Clear caveats
            </span>
          </div>
        </div>
      </section>

      <div className="detail-grid">
        <section
          id="boundaries"
          className="card boundaries-card"
          aria-labelledby="boundaries-title"
        >
          <div className="section-title">
            <span className="section-icon">
              <Icon name="shield" />
            </span>
            <div>
              <p className="eyebrow">RESEARCH BOUNDARIES</p>
              <h2 id="boundaries-title">Evidence has a source.</h2>
            </div>
          </div>
          <p className="section-description">
            The enforced boundaries for every search and report.
          </p>
          <ul className="boundary-list">
            {report.constraints.map((constraint) => (
              <li key={constraint}>
                <span className="list-marker" aria-hidden="true" />
                {constraint}
              </li>
            ))}
          </ul>
        </section>
        <section
          className="card limitations-card"
          aria-labelledby="limitations-title"
        >
          <div className="section-title">
            <span className="section-icon neutral">
              <Icon name="plan" />
            </span>
            <div>
              <p className="eyebrow">TRANSPARENCY</p>
              <h2 id="limitations-title">Limits and remaining work</h2>
            </div>
          </div>
          <p className="section-description">
            Review these limits alongside the evidence in each report.
          </p>
          <ul className="limitation-list">
            {report.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </section>
      </div>

      <section
        id="roadmap"
        className="card roadmap-card"
        aria-labelledby="roadmap-title"
      >
        <div className="card-header">
          <div>
            <p className="eyebrow">APPLICATION CAPABILITIES</p>
            <h2 id="roadmap-title">Current capabilities and next steps</h2>
          </div>
          <Icon name="plan" />
        </div>
        {
          <div className="audit-notes">
            {report.implemented && (
              <div>
                <h3>Implemented capabilities</h3>
                <ul>
                  {report.implemented.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
            {report.next_steps && (
              <div>
                <h3>Next steps from the application</h3>
                <ul>
                  {report.next_steps.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        }
      </section>
    </>
  );
}

function WorkspaceShell({
  children,
  navigation,
}: {
  children: ReactNode;
  navigation?: ReactNode;
}) {
  return (
    <div className="app-shell project-app prompt-first-app">
      <a className="skip-link" href="#project-main">
        Skip to content
      </a>
      <aside
        className="sidebar project-sidebar"
        aria-label="Workspace navigation"
      >
        <div className="brand">
          <LabcatMark />
          <span className="brand-copy">
            {brandName}
            <span className="brand-subtitle">{brandTagline}</span>
          </span>
        </div>
        {navigation}
        <div className="sidebar-footer">
          <span className="connection-dot is-connected" />
          <span>Local workspace</span>
        </div>
      </aside>
      <div className="workspace project-area">
        <header className="topbar">
          <span className="workspace-breadcrumb">Research workspace</span>
        </header>
        <main id="project-main" className="project-main" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
