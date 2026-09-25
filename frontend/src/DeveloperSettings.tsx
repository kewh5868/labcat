import { useEffect, useRef, useState } from "react";
import "./developerSettings.css";

interface Controls {
  reference_search: boolean;
  literature_followup: boolean;
  allow_preprints: boolean;
  include_history: boolean;
  viewer_enabled: boolean;
  max_reference_results: number;
  max_attribute_queries: number;
  max_article_downloads: number;
  literature_timeout_seconds: number;
  max_agent_tool_calls: number;
  default_model_account_id: string | null;
}
interface DeveloperStatus {
  settings: Controls;
  defaults: Controls;
  limits: Record<string, [number, number]>;
  immutable_boundaries: string[];
  model_accounts: {
    id: string;
    label: string;
    provider: string;
    model: string;
  }[];
}
const toggles: {
  key: keyof Pick<
    Controls,
    | "reference_search"
    | "literature_followup"
    | "allow_preprints"
    | "include_history"
  >;
  label: string;
  description: string;
}[] = [
  {
    key: "reference_search",
    label: "Search public references",
    description:
      "Allow the reference-discovery stage for sources selected in Search Criterion.",
  },
  {
    key: "literature_followup",
    label: "Follow up on missing properties",
    description:
      "Skim supported open-access articles after repository retrieval. Passages stay unscored until verified.",
  },
  {
    key: "allow_preprints",
    label: "Include public preprints",
    description:
      "Allow the preprint adapter when the scientist selects it. Disabling this also blocks direct preprint search requests.",
  },
  {
    key: "include_history",
    label: "Include conversation and project context",
    description:
      "Allow bounded chat history and pinned context in model requests. Context remains search guidance, never evidence.",
  },
];
const budgets: {
  key: keyof Pick<
    Controls,
    | "max_reference_results"
    | "max_attribute_queries"
    | "max_article_downloads"
    | "literature_timeout_seconds"
    | "max_agent_tool_calls"
  >;
  label: string;
  description: string;
}[] = [
  {
    key: "max_reference_results",
    label: "References per source",
    description: "Upper limit; a scientist can select a smaller number.",
  },
  {
    key: "max_attribute_queries",
    label: "Missing-property searches",
    description: "Maximum separate attribute queries in one report.",
  },
  {
    key: "max_article_downloads",
    label: "Open-access article attempts",
    description:
      "Maximum article downloads attempted during property follow-up.",
  },
  {
    key: "literature_timeout_seconds",
    label: "Literature search time (seconds)",
    description: "Time budget for the complete article follow-up stage.",
  },
  {
    key: "max_agent_tool_calls",
    label: "Agent tool requests",
    description:
      "Maximum requests to the two supported research stages. This cannot add tools or trigger experiments.",
  },
];

async function request(
  settings?: Controls,
  signal?: AbortSignal,
): Promise<DeveloperStatus> {
  let headers: Record<string, string> = { Accept: "application/json" };
  if (settings) {
    const session = await fetch("/api/session", {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal,
    });
    if (!session.ok)
      throw new Error("Refresh the developer session and try again.");
    const token = (await session.json()).csrf_token;
    if (typeof token !== "string")
      throw new Error("The developer session is unavailable.");
    headers = {
      ...headers,
      "Content-Type": "application/json",
      "X-CSRF-Token": token,
    };
  }
  const response = await fetch("/api/developer-settings", {
    method: settings ? "PUT" : "GET",
    headers,
    body: settings ? JSON.stringify(settings) : undefined,
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal,
  });
  if (!response.ok)
    throw new Error(
      response.status === 404
        ? "Developer Settings are unavailable in this edition."
        : "Developer settings could not be loaded or saved. Check the selected connection and reload.",
    );
  const value = await response.json();
  if (
    typeof value?.settings?.viewer_enabled !== "boolean" ||
    typeof value?.defaults?.viewer_enabled !== "boolean"
  )
    throw new Error(
      "Developer settings are incomplete. Reload the application before changing them.",
    );
  return value;
}

export default function DeveloperSettings() {
  const [data, setData] = useState<DeveloperStatus | null>(null);
  const [draft, setDraft] = useState<Controls | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const alive = useRef(true);
  const lock = useRef(false);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    request(undefined, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setData(value);
          setDraft({ ...value.settings });
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setError(
            error instanceof Error
              ? error.message
              : "Developer settings are unavailable.",
          );
      });
    return () => controller.abort();
  }, [revision]);
  function update<K extends keyof Controls>(key: K, value: Controls[K]) {
    setDraft((current) => (current ? { ...current, [key]: value } : current));
    setNotice("");
  }
  async function save() {
    if (!draft || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const value = await request(draft);
      if (alive.current) {
        setData(value);
        setDraft({ ...value.settings });
        setNotice(
          "Deployment controls saved. New research requests and structure views will use these settings.",
        );
      }
    } catch (error) {
      if (alive.current)
        setError(
          error instanceof Error
            ? error.message
            : "Developer settings could not be saved.",
        );
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  }
  const changed =
    data && draft && JSON.stringify(data.settings) !== JSON.stringify(draft);
  return (
    <section className="developer-settings">
      <header className="settings-intro">
        <p className="eyebrow">DEVELOPER EDITION</p>
        <h1>Developer Settings</h1>
        <p>
          Control how this installation carries out public research. These
          controls are unavailable in the user edition.
        </p>
      </header>
      {error && (
        <div role="alert" className="workspace-error">
          <p>{error}</p>
          <button
            type="button"
            className="quiet-button"
            disabled={busy}
            onClick={() => setRevision((value) => value + 1)}
          >
            Reload developer settings
          </button>
        </div>
      )}
      {!data || !draft ? (
        <p role="status">Loading deployment controls…</p>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <section className="card developer-card">
            <p className="eyebrow">AGENT ACTIONS</p>
            <h2>Choose the research stages.</h2>
            <div className="developer-actions">
              {toggles.map((item) => (
                <label key={item.key}>
                  <input
                    type="checkbox"
                    checked={draft[item.key]}
                    disabled={busy}
                    onChange={(event) => update(item.key, event.target.checked)}
                  />
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.description}</small>
                  </span>
                </label>
              ))}
            </div>
          </section>
          <section className="card developer-card">
            <p className="eyebrow">STRUCTURE VIEWER</p>
            <h2>Interactive structure display.</h2>
            <div className="developer-actions">
              <label>
                <input
                  type="checkbox"
                  checked={draft.viewer_enabled}
                  disabled={busy}
                  onChange={(event) =>
                    update("viewer_enabled", event.target.checked)
                  }
                />
                <span>
                  <strong>Enable interactive structure viewer</strong>
                  <small>
                    Show supported public structures with JSmol. Turn this off
                    to stop loading the interactive viewer; structure downloads
                    remain available.
                  </small>
                </span>
              </label>
            </div>
          </section>
          <section className="card developer-card">
            <p className="eyebrow">ONLINE RESEARCH LIMITS</p>
            <h2>Keep each request bounded.</h2>
            <p>
              These limits can narrow the supported workflow. They cannot expand
              network access or remove evidence checks.
            </p>
            <div className="developer-budgets">
              {budgets.map((item) => (
                <div className="developer-budget" key={item.key}>
                  <div>
                    <label htmlFor={`developer-${item.key}`}>
                      {item.label}
                    </label>
                    <p>{item.description}</p>
                  </div>
                  <div className="developer-budget-input">
                    <input
                      aria-label={`${item.label} slider`}
                      type="range"
                      min={data.limits[item.key][0]}
                      max={data.limits[item.key][1]}
                      step={1}
                      disabled={busy}
                      value={draft[item.key]}
                      onChange={(event) =>
                        update(item.key, Number(event.target.value))
                      }
                    />
                    <input
                      id={`developer-${item.key}`}
                      type="number"
                      required
                      min={data.limits[item.key][0]}
                      max={data.limits[item.key][1]}
                      step={1}
                      disabled={busy}
                      value={draft[item.key]}
                      onChange={(event) =>
                        update(item.key, Number(event.target.value))
                      }
                    />
                  </div>
                </div>
              ))}
            </div>
          </section>
          <section className="card developer-card">
            <p className="eyebrow">MODEL DEFAULT</p>
            <h2>Default research connection.</h2>
            <label htmlFor="developer-default-model">
              Saved model connection
            </label>
            <select
              id="developer-default-model"
              disabled={busy}
              value={draft.default_model_account_id ?? ""}
              onChange={(event) =>
                update("default_model_account_id", event.target.value || null)
              }
            >
              <option value="">
                Use the scientist’s selection in Connections
              </option>
              {data.model_accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.label} · {account.model || "model not selected"}
                </option>
              ))}
            </select>
            <p>
              Used when no model connection is selected. A scientist’s explicit
              choice takes priority; account consent, authentication and model
              verification are still required.
            </p>
          </section>
          <section className="card developer-card developer-boundaries">
            <p className="eyebrow">FIXED EVIDENCE BOUNDARIES</p>
            <h2>Always enforced.</h2>
            <ul>
              {data.immutable_boundaries.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
          {notice && (
            <p role="status" className="settings-saved">
              {notice}
            </p>
          )}
          <div className="settings-actions">
            <button
              type="button"
              className="quiet-button"
              disabled={busy}
              onClick={() => {
                setDraft({ ...data.defaults });
                setNotice("Defaults loaded into the form. Save to apply them.");
              }}
            >
              Reset form to defaults
            </button>
            <button
              type="submit"
              className="primary-button"
              disabled={busy || !changed}
            >
              {busy ? "Saving…" : "Save developer settings"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
