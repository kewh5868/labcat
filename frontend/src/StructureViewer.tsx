import { useEffect, useId, useRef, useState } from "react";
import {
  structureApi,
  structureError,
  structureSourceLink,
} from "./structureApi";
import type {
  ReferenceStatus,
  ReportStructures,
  StructureRecord,
  StructureTarget,
} from "./structureApi";
import { MaterialFormula } from "./ReportContent";
import "./structureViewer.css";

/** The iframe receives only server-generated CIF, never report prose or user text. */
function JSmolFrame({ cif, label }: { cif: string; label: string }) {
  const iframe = useRef<HTMLIFrameElement>(null);
  const channel = useRef(crypto.randomUUID());
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [attempt, setAttempt] = useState(0);
  function hello() {
    iframe.current?.contentWindow?.postMessage(
      { type: "labcat-jsmol-hello" },
      "*",
    );
  }
  useEffect(() => {
    channel.current = crypto.randomUUID();
    setStatus("loading");
    let sent = false;
    const timeout = window.setTimeout(() => setStatus("error"), 45000);
    function message(event: MessageEvent) {
      if (
        !iframe.current?.contentWindow ||
        event.source !== iframe.current.contentWindow ||
        event.origin !== "null" ||
        !event.data ||
        typeof event.data !== "object"
      )
        return;
      if (event.data.type === "labcat-jsmol-ready" && !sent) {
        sent = true;
        iframe.current.contentWindow.postMessage(
          { type: "labcat-jsmol-load", channel: channel.current, cif },
          "*",
        );
      } else if (
        event.data.channel === channel.current &&
        ["labcat-jsmol-loaded", "labcat-jsmol-error"].includes(event.data.type)
      ) {
        window.clearTimeout(timeout);
        setStatus(
          event.data.type === "labcat-jsmol-loaded" ? "ready" : "error",
        );
      }
    }
    window.addEventListener("message", message);
    // Replay readiness whether the iframe or React's listener became ready first.
    hello();
    return () => {
      window.clearTimeout(timeout);
      window.removeEventListener("message", message);
    };
  }, [cif, attempt]);
  function command(command: "reset" | "spin") {
    iframe.current?.contentWindow?.postMessage(
      { type: "labcat-jsmol-command", channel: channel.current, command },
      "*",
    );
  }
  return (
    <div className="structure-viewer">
      <div className="structure-viewer-toolbar">
        <span>JSmol · drag to rotate, scroll to zoom</span>
        <div>
          <button
            type="button"
            disabled={status !== "ready"}
            onClick={() => command("reset")}
          >
            Reset view
          </button>
          <button
            type="button"
            disabled={status !== "ready"}
            onClick={() => command("spin")}
          >
            Toggle rotation
          </button>
        </div>
      </div>
      {status === "loading" && (
        <p role="status" className="structure-viewer-status">
          Opening the structure viewer…
        </p>
      )}
      {status === "error" && (
        <div className="structure-error">
          <p role="alert">
            The interactive viewer could not display this structure. The CIF
            file remains available to download.
          </p>
          <button
            type="button"
            className="quiet-button"
            onClick={() => setAttempt((value) => value + 1)}
          >
            Retry viewer
          </button>
        </div>
      )}
      <iframe
        key={attempt}
        ref={iframe}
        onLoad={hello}
        className={
          status === "error"
            ? "structure-frame structure-frame-failed"
            : "structure-frame"
        }
        title={`JSmol structure for ${label}`}
        src="/structure-viewer/index.html"
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
      />
    </div>
  );
}

function SelectedStructure({
  item,
  chatId,
  reportId,
  viewerEnabled,
  onRetrieved,
  requested = 0,
  leadId,
}: {
  item: StructureRecord;
  chatId: string;
  reportId: string;
  viewerEnabled: boolean;
  onRetrieved: (item: StructureRecord) => void;
  requested?: number;
  leadId?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [cif, setCif] = useState("");
  const operation = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      operation.current?.abort();
    },
    [],
  );
  useEffect(() => {
    if (!viewerEnabled) {
      operation.current?.abort();
      setCif("");
      setBusy(false);
    }
  }, [viewerEnabled]);
  async function load() {
    if (operation.current && !operation.current.signal.aborted) return;
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true);
    setError("");
    try {
      const ready =
        item.status === "ready"
          ? item
          : await structureApi.retrieve(
              chatId,
              reportId,
              item.material_id,
              controller.signal,
            );
      if (controller.signal.aborted) return;
      onRetrieved(ready);
      if (viewerEnabled) {
        const content = await structureApi.content(
          chatId,
          reportId,
          item.material_id,
          controller.signal,
        );
        if (!controller.signal.aborted) setCif(content);
      }
    } catch (error) {
      if (!controller.signal.aborted) setError(structureError(error));
    } finally {
      if (!controller.signal.aborted) {
        operation.current = null;
        setBusy(false);
      }
    }
  }
  const components =
    item.literature_association?.components?.filter(
      (component) => !leadId || component.lead_id === leadId,
    ) ?? [];
  const sourceLink = structureSourceLink(item.source_url);
  const structureLink = item.structure_source_url
    ? structureSourceLink(item.structure_source_url)
    : null;
  const retrievable = item.status === "ready" || item.status === "not_loaded";
  useEffect(() => {
    if (requested && retrievable) void load();
  }, [requested]);
  return (
    <div className="structure-selected">
      <div className="structure-record-heading">
        <div>
          <strong>
            <MaterialFormula formula={item.formula || item.material_id} />
          </strong>
        </div>
        <span className={`structure-state structure-state-${item.status}`}>
          {item.status === "ready"
            ? "CIF available"
            : item.status === "not_loaded"
              ? "Retrieve on request"
              : item.status === "connection_required"
                ? "Connection needed"
                : "Unavailable"}
        </span>
      </div>
      {item.literature_association && (
        <div className="structure-reference-notice">
          <strong>
            {components.length ? "Component reference" : "Reference structure"}{" "}
            · Phase match unverified
          </strong>
          {components.length ? (
            <p>
              This is an independent bulk reference for{" "}
              {components
                .map((component) => `${component.label} (${component.formula})`)
                .join(", ")}
              . It does not represent the assembled interface, core–shell
              particle or nanoparticle geometry. Viewing it does not change the
              ranking.
            </p>
          ) : (
            <p>
              {item.literature_association.relation ===
              "cited_repository_record"
                ? "This structure comes from a cited repository system or record for "
                : "This repository record matches the composition of "}
              {item.literature_association.lead_names.join(", ")}. It is not
              established as the same phase, sample or device discussed in the
              report. Viewing it does not change the ranking.
            </p>
          )}
        </div>
      )}
      {item.structure_match === "composition_reference" && (
        <div className="structure-reference-notice">
          <strong>Reference structure</strong>
          <p>
            This structure matches the composition. Its phase and measurement
            conditions are not established as identical to the ranked property
            record.
          </p>
          <ul>
            {item.structure_differences?.map((difference) => (
              <li key={difference}>{difference}</li>
            ))}
          </ul>
        </div>
      )}
      {item.source_name && (
        <p className="structure-source">
          {item.literature_association
            ? "Repository source: "
            : structureLink
              ? "Ranked property source: "
              : "Source: "}
          {sourceLink ? (
            <a href={sourceLink} target="_blank" rel="noreferrer noopener">
              {item.source_name} <span aria-hidden="true">↗</span>
            </a>
          ) : (
            item.source_name
          )}
          {structureLink && (
            <>
              <br />
              Structure source:{" "}
              <a href={structureLink} target="_blank" rel="noreferrer noopener">
                Public crystallography dataset{" "}
                <span aria-hidden="true">↗</span>
              </a>
            </>
          )}
        </p>
      )}
      {item.reason && <p>{item.reason}</p>}
      {!viewerEnabled && (
        <p className="structure-disabled">
          The interactive viewer is turned off in Developer Settings. Available
          structure files can still be retrieved and downloaded.
        </p>
      )}
      {error && (
        <p className="structure-error" role="alert">
          {error}
        </p>
      )}
      <div className="structure-actions">
        {retrievable && !cif && (viewerEnabled || item.status !== "ready") && (
          <button
            type="button"
            className="quiet-button"
            disabled={busy}
            onClick={() => void load()}
          >
            {busy
              ? "Loading structure…"
              : item.status === "ready"
                ? "View structure"
                : viewerEnabled
                  ? "Retrieve and view structure"
                  : "Retrieve CIF"}
          </button>
        )}
        {item.status === "ready" && (
          <a
            className="report-download-link"
            href={item.download_url}
            download={item.filename}
          >
            {item.source_cif ? "Download displayed structure" : "Download CIF"}{" "}
            <span aria-hidden="true">↓</span>
          </a>
        )}
        {item.source_cif && (
          <a
            className="report-download-link"
            href={item.source_cif.download_url}
            download={item.source_cif.filename}
          >
            Download original CIF <span aria-hidden="true">↓</span>
          </a>
        )}
      </div>
      {viewerEnabled && cif && (
        <JSmolFrame
          key={item.sha256}
          cif={cif}
          label={`${item.formula || item.material_id} (${item.material_id})`}
        />
      )}
      {item.caveats.length > 0 && (
        <details className="structure-limitations">
          <summary>Structure limitations</summary>
          <ul className="structure-caveats">
            {item.caveats.map((caveat, index) => (
              <li key={index}>{caveat}</li>
            ))}
          </ul>
        </details>
      )}
      <details className="structure-provenance">
        <summary>Structure file provenance</summary>
        <dl>
          {item.source_formula && item.source_formula !== item.formula && (
            <div>
              <dt>Original source formula</dt>
              <dd>
                {item.source_formula}
                <br />
                <small>
                  The displayed formula uses conventional element ordering; the
                  source composition and file are unchanged.
                </small>
              </dd>
            </div>
          )}
          <div>
            <dt>Source record</dt>
            <dd className="structure-hash">{item.material_id}</dd>
          </div>
          {item.status === "ready" && (
            <>
              <div>
                <dt>Retrieved</dt>
                <dd>
                  <time dateTime={item.retrieved_at}>
                    {new Date(item.retrieved_at!).toLocaleString()}
                  </time>
                </dd>
              </div>
              <div>
                <dt>Atomic sites</dt>
                <dd>{item.n_sites}</dd>
              </div>
              <div>
                <dt>SHA-256</dt>
                <dd className="structure-hash">{item.sha256}</dd>
              </div>
            </>
          )}
        </dl>
      </details>
      {item.source_cif && (
        <details className="structure-provenance">
          <summary>Original crystallography file</summary>
          <dl>
            <div>
              <dt>File</dt>
              <dd>{item.source_cif.filename}</dd>
            </div>
            <div>
              <dt>Displayed block</dt>
              <dd>{item.source_cif.block}</dd>
            </div>
            <div>
              <dt>Original SHA-256</dt>
              <dd className="structure-hash">{item.source_cif.sha256}</dd>
            </div>
            <div>
              <dt>Archive SHA-256</dt>
              <dd className="structure-hash">
                {item.source_cif.archive_sha256}
              </dd>
            </div>
          </dl>
          <p>
            The original file is preserved unchanged and may contain other
            structures. The viewer displays only the validated block listed
            above.
          </p>
        </details>
      )}
    </div>
  );
}

function retainReadyStructures(
  next: ReportStructures,
  current: ReportStructures | null,
): ReportStructures {
  // A metadata request may predate an in-flight geometry download. Retain that
  // completed result only for the same exact record in this report; newer
  // candidate associations and explicit unavailable statuses remain authoritative.
  return {
    ...next,
    structures: next.structures.map((entry) => {
      const cached = current?.structures.find(
        (item) => item.material_id === entry.material_id,
      );
      if (
        entry.status !== "not_loaded" ||
        cached?.status !== "ready" ||
        cached.formula !== entry.formula ||
        cached.source_formula !== entry.source_formula ||
        cached.source_name !== entry.source_name ||
        cached.source_url !== entry.source_url
      )
        return entry;
      return {
        ...entry,
        ...cached,
        literature_association: entry.literature_association,
        caveats: [...new Set([...entry.caveats, ...cached.caveats])],
      };
    }),
  };
}

const referenceStatusLabels: Record<ReferenceStatus, string> = {
  cited_record_available: "Cited reference available",
  references_found: "Reference records found",
  reference_lookup_available: "Not searched yet",
  no_reference_matches: "No matching records found",
  reference_lookup_failed: "Lookup incomplete — retry available",
  unsupported: "Composition not resolved",
};
const retryableReference = (status: ReferenceStatus) =>
  [
    "reference_lookup_available",
    "reference_lookup_failed",
    "no_reference_matches",
  ].includes(status);

/** Mounted inside an expanded shortlist row, never as a global candidate picker. */
export default function StructureViewer({
  chatId,
  reportId,
  target,
  label,
  autoLoad = false,
}: {
  chatId: string;
  reportId: string;
  target: StructureTarget;
  label?: string;
  autoLoad?: boolean;
}) {
  const [savedData, setData] = useState<ReportStructures | null>(null);
  const [selected, setSelected] = useState("");
  const [finding, setFinding] = useState(false);
  const lookup = useRef<AbortController | null>(null);
  const dataScope = useRef("");
  const scope = `${chatId}:${reportId}:${target.kind}:${target.id}`;
  const data = dataScope.current === scope ? savedData : null;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [requested, setRequested] = useState(1);
  const id = useId();
  useEffect(() => {
    lookup.current?.abort();
    setFinding(false);
    const sameScope = dataScope.current === scope;
    dataScope.current = scope;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    if (!sameScope) {
      setData(null);
      setSelected("");
    }
    structureApi
      .list(chatId, reportId, controller.signal)
      .then((next) => {
        if (!controller.signal.aborted)
          setData((current) =>
            retainReadyStructures(next, sameScope ? current : null),
          );
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setError(structureError(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
      lookup.current?.abort();
    };
  }, [chatId, reportId, scope, revision]);
  const lead =
    target.kind === "lead"
      ? data?.literature_candidates?.find(
          (entry) => entry.lead_id === target.id,
        )
      : undefined;
  const visible =
    data?.structures.filter((entry) =>
      target.kind === "material"
        ? entry.material_id === target.id
        : Boolean(lead) &&
          entry.literature_association?.lead_ids.includes(target.id),
    ) ?? [];
  const components = lead?.components ?? [];
  const componentSearchNeeded = components.some((component) =>
    retryableReference(component.status),
  );
  const canFindReferences = Boolean(
    lead &&
      ((!visible.length && lead.status !== "unsupported") ||
        componentSearchNeeded),
  );
  const retryingReferences =
    lead?.status === "reference_lookup_failed" ||
    lead?.status === "no_reference_matches" ||
    components.some((component) =>
      ["reference_lookup_failed", "no_reference_matches"].includes(
        component.status,
      ),
    );
  const item =
    visible.find((entry) => entry.material_id === selected) ??
    (visible.length === 1 ? visible[0] : undefined);
  useEffect(() => {
    // Keep a loaded component selected when discovery adds other records.
    if (item && selected !== item.material_id) setSelected(item.material_id);
  }, [item?.material_id, selected]);
  async function findReferences() {
    if (!lead || loading || finding || !canFindReferences) return;
    lookup.current?.abort();
    const controller = new AbortController();
    lookup.current = controller;
    setFinding(true);
    setError("");
    try {
      const next = await structureApi.references(
        chatId,
        reportId,
        lead.lead_id,
        controller.signal,
      );
      if (!controller.signal.aborted)
        setData((current) => retainReadyStructures(next, current));
    } catch (error) {
      if (!controller.signal.aborted) setError(structureError(error));
    } finally {
      if (!controller.signal.aborted) {
        setFinding(false);
        lookup.current = null;
      }
    }
  }
  return (
    <section
      className="report-structures report-structures-inline"
      aria-labelledby={`${id}-heading`}
    >
      <header>
        <h4 id={`${id}-heading`}>
          Structure
          {label ? (
            <>
              {" "}
              · <MaterialFormula formula={label} />
            </>
          ) : (
            ""
          )}
        </h4>
        <button
          className="structure-refresh"
          type="button"
          disabled={loading || finding}
          onClick={() => setRevision((value) => value + 1)}
        >
          Refresh availability
        </button>
      </header>
      {loading && <p role="status">Checking structure availability…</p>}
      {error && (
        <p className="structure-error" role="alert">
          {error}
        </p>
      )}
      {!loading && data && !visible.length && (
        <p>
          {lead?.reason ||
            "No accessible structure is currently associated with this candidate."}
        </p>
      )}
      {components.length > 0 && (
        <div className="structure-components">
          <h5>Component references</h5>
          <p>
            Individual materials can have separate bulk reference structures.
            These do not establish the assembled interface, particle shape or
            core and shell roles.
          </p>
          <ul>
            {components.map((component) => (
              <li key={component.component_id}>
                <strong>
                  {component.label} ·{" "}
                  <MaterialFormula formula={component.formula} />
                </strong>
                <span>{referenceStatusLabels[component.status]}</span>
                {component.reason &&
                  !["cited_record_available", "references_found"].includes(
                    component.status,
                  ) && <small>{component.reason}</small>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {canFindReferences && (
        <div className="structure-reference-search">
          <p>
            {components.length
              ? "Search available public sources for the remaining component references. Any existing structures stay available."
              : "A public reference lookup may find the same composition. Phase and sample matching will remain unverified."}
          </p>
          {lead?.status === "no_reference_matches" && (
            <p>The previous bounded lookup found no matching records.</p>
          )}
          <button
            type="button"
            className="quiet-button"
            disabled={loading || finding}
            onClick={() => void findReferences()}
          >
            {finding
              ? "Finding reference structures…"
              : retryingReferences
                ? "Retry reference lookup"
                : "Find reference structures"}
          </button>
        </div>
      )}
      {visible.length > 1 && (
        <div
          className="structure-record-options"
          role="group"
          aria-label="Available structure records for this candidate"
        >
          <p>
            Choose a source record to view. Composition references do not
            establish a phase match.
          </p>
          {visible.map((entry, index) => {
            const matches =
              entry.literature_association?.components?.filter(
                (component) => component.lead_id === target.id,
              ) ?? [];
            return (
              <button
                type="button"
                key={entry.material_id}
                className="quiet-button"
                aria-pressed={item?.material_id === entry.material_id}
                onClick={() => {
                  setSelected(entry.material_id);
                  setRequested((value) => value + 1);
                }}
              >
                {components.length > 0 && (
                  <strong>
                    {matches.length
                      ? matches.map((component) => component.label).join(", ")
                      : "Candidate reference"}{" "}
                    · <MaterialFormula formula={entry.formula} />
                  </strong>
                )}
                {entry.source_name || "Public record"} · {entry.material_id}
                <small>
                  Record {index + 1}
                  {entry.literature_association
                    ? " · Phase match unverified"
                    : ""}
                </small>
              </button>
            );
          })}
        </div>
      )}
      {item && (
        <SelectedStructure
          key={`${scope}:${item.material_id}`}
          item={item}
          leadId={target.kind === "lead" ? target.id : undefined}
          chatId={chatId}
          reportId={reportId}
          viewerEnabled={data!.viewer_enabled}
          requested={autoLoad ? requested : 0}
          onRetrieved={(next) =>
            setData((current) =>
              current
                ? {
                    ...current,
                    structures: current.structures.map((entry) =>
                      entry.material_id === next.material_id ? next : entry,
                    ),
                  }
                : current,
            )
          }
        />
      )}
    </section>
  );
}
