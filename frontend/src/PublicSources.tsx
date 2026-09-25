import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { publicSourceError, publicSourcesApi } from "./publicSourcesApi";
import type {
  PublicSource,
  SourceRegistry,
  SourceSettings,
} from "./publicSourcesApi";
import "./publicSources.css";

interface PublicSourcesPanelProps {
  context?: "settings" | "connections";
  onStateChange?: (state: { dirty: boolean; busy: boolean }) => void;
  onConnections?: () => void;
  refreshKey?: string;
  materialsProjectCard?: ReactNode;
}

function DatabaseLinks({
  source,
}: {
  source: Pick<PublicSource, "name" | "homepage" | "documentation_url">;
}) {
  return (
    <>
      <a href={source.homepage} target="_blank" rel="noopener noreferrer">
        Visit database <span aria-hidden="true">↗</span>
      </a>
      <a
        href={source.documentation_url}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`API access guide for ${source.name}`}
      >
        API access guide <span aria-hidden="true">↗</span>
      </a>
    </>
  );
}

export default function PublicSourcesPanel({
  context = "settings",
  onStateChange,
  onConnections,
  refreshKey = "",
  materialsProjectCard,
}: PublicSourcesPanelProps) {
  const [registry, setRegistry] = useState<SourceRegistry>({
    sources: [],
    connected_sources: [],
  });
  const [draft, setDraft] = useState<SourceSettings | null>(null);
  const [saved, setSaved] = useState<SourceSettings | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const mounted = useRef(true);
  const lock = useRef(false);
  const loadedRevision = useRef<number | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    // Credential updates refresh availability without discarding unsaved database choices.
    const loadSettings = loadedRevision.current !== revision;
    Promise.all([
      publicSourcesApi.registry(controller.signal),
      loadSettings ? publicSourcesApi.settings(controller.signal) : null,
    ])
      .then(([catalog, settings]) => {
        if (controller.signal.aborted) return;
        setRegistry(catalog);
        if (settings) {
          setDraft(
            settings.materials_project_mode === "snapshot"
              ? { ...settings, materials_project_mode: "off" }
              : settings,
          );
          setSaved(settings);
          loadedRevision.current = revision;
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setError(publicSourceError(error));
      });
    return () => controller.abort();
  }, [revision, refreshKey]);
  function update<K extends keyof SourceSettings>(
    key: K,
    value: SourceSettings[K],
  ) {
    setDraft((current) => (current ? { ...current, [key]: value } : current));
    setNotice("");
  }
  const api = registry.connected_sources.find(
    (source) => source.id === "materials_project",
  );
  const apiReady = api?.availability.selectable === true;
  const apiSelected =
    draft?.materials_project_mode === "api" ||
    (draft?.materials_project_mode === "auto" && apiReady);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!draft || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    // Replace legacy automatic use with the exact selection visible when saved.
    const selection =
      draft.materials_project_mode === "auto"
        ? {
            ...draft,
            materials_project_mode: apiReady
              ? ("api" as const)
              : ("off" as const),
          }
        : draft;
    try {
      const next = await publicSourcesApi.save(selection);
      if (mounted.current) {
        setDraft(next);
        setSaved(next);
        setNotice("Public source preferences saved for new searches.");
      }
    } catch (error) {
      if (mounted.current) setError(publicSourceError(error));
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  const changed =
    context === "settings" && JSON.stringify(draft) !== JSON.stringify(saved);
  useEffect(() => {
    onStateChange?.({ dirty: changed, busy });
  }, [changed, busy, onStateChange]);
  useEffect(
    () => () => onStateChange?.({ dirty: false, busy: false }),
    [onStateChange],
  );
  const sources = registry.sources;
  const errorNotice = error && (
    <div className="workspace-error" role="alert">
      <p>{error}</p>
      <button
        className="quiet-button"
        type="button"
        disabled={busy}
        onClick={() => setRevision((value) => value + 1)}
      >
        Reload source settings
      </button>
    </div>
  );
  if (context === "connections")
    return (
      <section className="public-sources-panel card">
        <p className="eyebrow">PUBLIC SOURCE REGISTRY</p>
        <h2>Supported research databases.</h2>
        <p className="source-panel-intro">
          Connect optional APIs here, then choose which databases research uses
          in Search Criterion. The other public databases below need no account
          or API key.
        </p>
        {errorNotice}
        <div className="selected-public-sources source-registry-cards">
          {materialsProjectCard}
          {sources.map((source) => (
            <article key={source.id} className="selected-public-source">
              <div className="selected-source-heading">
                <h3>{source.name}</h3>
                <span>Available · No account or key needed</span>
              </div>
              <p>{source.description}</p>
              <div className="selected-source-actions">
                <DatabaseLinks source={source} />
              </div>
            </article>
          ))}
        </div>
      </section>
    );
  return (
    <section className="public-sources-panel card">
      <div className="connection-card-heading">
        <div>
          <p className="eyebrow">PUBLIC DATA SOURCES</p>
          <h2>Choose where research looks.</h2>
        </div>
      </div>
      <p className="source-panel-intro">
        Search supported public resources for any material class. Ranking uses
        independently verified property evidence; references can be reviewed and
        pinned. Coverage varies by source, material and property.
      </p>
      {errorNotice}
      {!draft ? (
        <p role="status">Loading source preferences…</p>
      ) : (
        <form onSubmit={submit}>
          <div className="source-search-fields">
            <div>
              <label htmlFor="settings-add-source">
                Add a research database
              </label>
              <select
                id="settings-add-source"
                value=""
                disabled={busy}
                onChange={(event) => {
                  const id = event.target.value;
                  if (id === "materials_project") {
                    if (apiReady) update("materials_project_mode", "api");
                    return;
                  }
                  const source = sources.find((item) => item.id === id);
                  if (source && !draft.enabled_sources.includes(source.id))
                    update("enabled_sources", [
                      ...draft.enabled_sources,
                      source.id,
                    ]);
                }}
              >
                <option value="">Choose a public database…</option>
                <option
                  value="materials_project"
                  disabled={apiSelected || !apiReady}
                >
                  Materials Project ·{" "}
                  {apiSelected
                    ? apiReady
                      ? "added"
                      : "added · verification required"
                    : apiReady
                      ? "verified connection"
                      : "connect and verify first"}
                </option>
                {sources.map((source) => (
                  <option
                    key={source.id}
                    value={source.id}
                    disabled={draft.enabled_sources.includes(source.id)}
                  >
                    {source.name}
                    {draft.enabled_sources.includes(source.id)
                      ? " · added"
                      : " · no account required"}
                  </option>
                ))}
              </select>
              {onConnections && (
                <button
                  type="button"
                  className="text-action source-connections-link"
                  onClick={onConnections}
                >
                  Connect or manage research databases
                </button>
              )}
            </div>
            <div>
              <label htmlFor="settings-reference-limit">
                References per database
              </label>
              <input
                id="settings-reference-limit"
                type="number"
                min={1}
                max={10}
                step={1}
                value={draft.max_results_per_source}
                disabled={busy}
                onChange={(event) => {
                  if (event.target.value !== "")
                    update(
                      "max_results_per_source",
                      Number(event.target.value),
                    );
                }}
              />
            </div>
          </div>
          <label className="public-search-toggle">
            <input
              type="checkbox"
              checked={draft.search_public_references}
              disabled={busy}
              onChange={(event) =>
                update("search_public_references", event.target.checked)
              }
            />
            <span>
              <strong>Search public references</strong>
              <small>
                Send search terms to selected public sources and skim available
                open-access articles for unscored review leads. Turn off to skip
                this additional research.
              </small>
            </span>
          </label>
          <div className="selected-public-sources">
            {apiSelected && (
              <article
                className="selected-public-source"
                data-source-id="materials_project"
              >
                <div className="selected-source-heading">
                  <h3>Materials Project</h3>
                  <span>
                    {apiReady
                      ? "Verified property API"
                      : "Unavailable · Verification required"}
                  </span>
                </div>
                <p>
                  {api?.description ??
                    "Public materials property records and available crystal structures."}
                </p>
                {!apiReady && (
                  <p className="source-unavailable">
                    {api?.availability.message ||
                      "Connect and verify this database in Connections before it can be used."}
                  </p>
                )}
                <div className="selected-source-actions">
                  {api && <DatabaseLinks source={api} />}
                  {onConnections && (
                    <button
                      type="button"
                      className="text-action"
                      onClick={onConnections}
                    >
                      {apiReady ? "Manage connection" : "Connect and verify"}
                    </button>
                  )}
                  <button
                    type="button"
                    className="text-action"
                    disabled={busy}
                    onClick={() => update("materials_project_mode", "off")}
                  >
                    Remove database
                  </button>
                </div>
              </article>
            )}
            {sources
              .filter((source) => draft.enabled_sources.includes(source.id))
              .map((source) => (
                <article
                  key={source.id}
                  className="selected-public-source"
                  data-source-id={source.id}
                >
                  <div className="selected-source-heading">
                    <h3>{source.name}</h3>
                    <span>No account or key needed</span>
                  </div>
                  <p>{source.description}</p>
                  <div className="selected-source-actions">
                    <DatabaseLinks source={source} />
                    <button
                      type="button"
                      className="text-action"
                      disabled={busy}
                      onClick={() =>
                        update(
                          "enabled_sources",
                          draft.enabled_sources.filter(
                            (id) => id !== source.id,
                          ),
                        )
                      }
                    >
                      Remove database
                    </button>
                  </div>
                </article>
              ))}
          </div>
          {!sources.some((source) =>
            draft.enabled_sources.includes(source.id),
          ) &&
            !apiSelected && (
              <p className="field-help">
                Add supported databases to broaden public research. Only
                verified property evidence contributes to a scored shortlist.
              </p>
            )}
          {notice && (
            <p className="connection-saved" role="status">
              {notice}
            </p>
          )}
          <div className="source-settings-actions">
            <button
              className="primary-button"
              type="submit"
              disabled={busy || !changed}
            >
              {busy ? "Saving…" : "Save source preferences"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
