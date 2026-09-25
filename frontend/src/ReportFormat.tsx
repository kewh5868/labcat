import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  defaultReportLayout,
  errorMessage,
  toggleReportOutput,
  workspaceApi,
} from "./workspaceApi";
import type {
  ExportFormat,
  ReportLayout,
  ReportPresentation,
  ReportView,
  SearchSettings,
} from "./workspaceApi";
import { reportFormatApi } from "./reportFormatApi";
import type { PreviewViews, ReportPreview } from "./reportFormatApi";
import ReportContent from "./ReportContent";
import LabcatMascot from "./LabcatMascot";
import "./reportFormat.css";
import "./mascotPlacements.css";

const clone = (value: SearchSettings): SearchSettings => ({
  ranking: { ...value.ranking },
  presentation: {
    ...value.presentation,
    outputs: [...value.presentation.outputs],
    layout: { ...defaultReportLayout, ...value.presentation.layout },
  },
});
export function OutputCheckboxes({
  outputs,
  onToggle,
  disabled = false,
}: {
  outputs: ReportView[];
  onToggle: (view: ReportView) => void;
  disabled?: boolean;
}) {
  return (
    <div className="output-checkboxes">
      {(["pi", "audit"] as const).map((view) => (
        <label key={view}>
          <input
            type="checkbox"
            checked={outputs.includes(view)}
            disabled={disabled || (outputs.length === 1 && outputs[0] === view)}
            onChange={() => onToggle(view)}
          />
          <span>{view === "pi" ? "Summary" : "Technical View"}</span>
        </label>
      ))}
    </div>
  );
}

export default function ReportFormat({
  initial,
  onSaved,
}: {
  initial: SearchSettings;
  onSaved: (value: SearchSettings) => void;
}) {
  const [draft, setDraft] = useState(() => clone(initial));
  const [saved, setSaved] = useState(() => clone(initial));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [view, setView] = useState<PreviewViews>("pi");
  const [format, setFormat] = useState<ExportFormat | "screen">("screen");
  const [preview, setPreview] = useState<ReportPreview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [previewBusy, setPreviewBusy] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [downloadBusy, setDownloadBusy] = useState(false);
  const mounted = useRef(true);
  const saveLock = useRef(false);
  const downloadLock = useRef(false);
  const downloadFormat = format === "screen" ? "pdf" : format;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const signature = JSON.stringify(draft.presentation);
  useEffect(() => {
    const controller = new AbortController();
    setPreviewBusy(true);
    setPreviewError("");
    const timer = window.setTimeout(() => {
      reportFormatApi
        .preview(
          JSON.parse(signature) as ReportPresentation,
          view,
          controller.signal,
        )
        .then((value) => {
          if (!controller.signal.aborted) setPreview(value);
        })
        .catch((error: unknown) => {
          if (!controller.signal.aborted)
            setPreviewError(
              error instanceof Error
                ? error.message
                : "Report preview is unavailable.",
            );
        })
        .finally(() => {
          if (!controller.signal.aborted) setPreviewBusy(false);
        });
    }, 180);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [signature, view, format, attempt]);
  function presentation<K extends keyof ReportPresentation>(
    key: K,
    value: ReportPresentation[K],
  ) {
    setDraft((current) => ({
      ...current,
      presentation: { ...current.presentation, [key]: value },
    }));
    setNotice("");
  }
  function layout<K extends keyof ReportLayout>(
    key: K,
    value: ReportLayout[K],
  ) {
    setDraft((current) => ({
      ...current,
      presentation: {
        ...current.presentation,
        layout: {
          ...defaultReportLayout,
          ...current.presentation.layout,
          [key]: value,
        },
      },
    }));
    setNotice("");
  }
  function outputs(value: ReportView) {
    const selected = toggleReportOutput(draft.presentation.outputs, value);
    presentation("outputs", selected);
    if (!selected.includes(draft.presentation.style))
      presentation("style", selected[0]);
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (saveLock.current) return;
    saveLock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const next = await workspaceApi.saveSettings(draft);
      if (mounted.current) {
        setDraft(clone(next));
        setSaved(clone(next));
        onSaved(next);
        setNotice(
          "Report format saved for new reports. Saved reports retain their recorded presentation.",
        );
      }
    } catch (error) {
      if (mounted.current)
        setError(
          `${errorMessage(error)} Reload saved format settings before retrying.`,
        );
    } finally {
      saveLock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function reload() {
    if (saveLock.current) return;
    saveLock.current = true;
    setBusy(true);
    try {
      const next = await workspaceApi.settings();
      if (mounted.current) {
        setDraft(clone(next));
        setSaved(clone(next));
        onSaved(next);
        setError("");
      }
    } catch (error) {
      if (mounted.current) setError(errorMessage(error));
    } finally {
      saveLock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function download() {
    if (downloadLock.current) return;
    downloadLock.current = true;
    setDownloadBusy(true);
    setPreviewError("");
    try {
      const file = await reportFormatApi.downloadLink(
        draft.presentation,
        view,
        downloadFormat,
      );
      if (mounted.current) {
        const link = document.createElement("a");
        link.href = file.url;
        link.download = file.filename;
        document.body.append(link);
        link.click();
        link.remove();
      }
    } catch (error) {
      if (mounted.current)
        setPreviewError(
          error instanceof Error
            ? error.message
            : "Template download is unavailable.",
        );
    } finally {
      downloadLock.current = false;
      if (mounted.current) setDownloadBusy(false);
    }
  }
  const appearance = draft.presentation.layout!;
  return (
    <section className="report-format-page">
      <header className="settings-intro mascot-settings-header">
        <LabcatMascot scene="typewriter" className="mascot-header" />
        <p className="eyebrow">PRESENTATION & EXPORTS</p>
        <h1>Report Format</h1>
        <p>
          Choose how summaries and technical views read and look. Previews use
          placeholders and never run research.
        </p>
      </header>
      <form onSubmit={save}>
        <section className="settings-card card">
          <p className="eyebrow">REPORT PRESENTATION</p>
          <h2>Write for your audience.</h2>
          <div className="settings-fields">
            <fieldset className="report-output-settings">
              <legend>Report outputs</legend>
              <OutputCheckboxes
                outputs={draft.presentation.outputs}
                onToggle={outputs}
                disabled={busy}
              />
              <p>Choose one or both for new reports and initial downloads.</p>
            </fieldset>
            <div>
              <label htmlFor="setting-verbosity">Verbosity</label>
              <select
                id="setting-verbosity"
                value={draft.presentation.verbosity}
                disabled={busy}
                onChange={(event) =>
                  presentation(
                    "verbosity",
                    event.target.value as ReportPresentation["verbosity"],
                  )
                }
              >
                <option value="concise">Concise</option>
                <option value="standard">Standard</option>
                <option value="detailed">Detailed</option>
              </select>
            </div>
            <div>
              <label htmlFor="setting-terminology">Terminology</label>
              <select
                id="setting-terminology"
                value={draft.presentation.terminology}
                disabled={busy}
                onChange={(event) =>
                  presentation(
                    "terminology",
                    event.target.value as ReportPresentation["terminology"],
                  )
                }
              >
                <option value="general">General overview</option>
                <option value="research">Research context</option>
                <option value="specialist">Specialist detail</option>
              </select>
            </div>
            <div>
              <label htmlFor="setting-format">Default output format</label>
              <select
                id="setting-format"
                value={draft.presentation.format}
                disabled={busy}
                onChange={(event) =>
                  presentation("format", event.target.value as ExportFormat)
                }
              >
                <option value="text">TXT</option>
                <option value="json">JSON</option>
                <option value="pdf">PDF</option>
                <option value="docx">Word document (.docx)</option>
              </select>
            </div>
          </div>
        </section>
        <section className="settings-card card">
          <p className="eyebrow">DOCUMENT APPEARANCE</p>
          <h2>Set a consistent report style.</h2>
          <p className="report-format-scope">
            Typeface, text size, spacing, accent and table style apply to the
            report on screen and to PDF and Word documents. Page size and page
            numbers apply to printed documents; TXT width and JSON indentation
            apply to their respective exports.
          </p>
          <div className="settings-fields">
            <div>
              <label htmlFor="report-page-size">Page size</label>
              <select
                id="report-page-size"
                value={appearance.page_size}
                disabled={busy}
                onChange={(event) =>
                  layout(
                    "page_size",
                    event.target.value as ReportLayout["page_size"],
                  )
                }
              >
                <option value="letter">US Letter</option>
                <option value="a4">A4</option>
              </select>
            </div>
            <div>
              <label htmlFor="report-font">Typeface</label>
              <select
                id="report-font"
                value={appearance.font_family}
                disabled={busy}
                onChange={(event) =>
                  layout(
                    "font_family",
                    event.target.value as ReportLayout["font_family"],
                  )
                }
              >
                <option value="sans">Sans serif</option>
                <option value="serif">Serif</option>
              </select>
            </div>
            <div>
              <label htmlFor="report-font-size">Text size</label>
              <select
                id="report-font-size"
                value={appearance.font_size}
                disabled={busy}
                onChange={(event) =>
                  layout(
                    "font_size",
                    Number(event.target.value) as ReportLayout["font_size"],
                  )
                }
              >
                {[10, 11, 12].map((size) => (
                  <option key={size} value={size}>
                    {size} pt
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="report-spacing">Line spacing</label>
              <select
                id="report-spacing"
                value={appearance.line_spacing}
                disabled={busy}
                onChange={(event) =>
                  layout(
                    "line_spacing",
                    event.target.value as ReportLayout["line_spacing"],
                  )
                }
              >
                <option value="comfortable">Comfortable</option>
                <option value="compact">Compact</option>
              </select>
            </div>
            <div>
              <label htmlFor="report-accent">Accent color</label>
              <select
                id="report-accent"
                value={appearance.accent}
                disabled={busy}
                onChange={(event) =>
                  layout("accent", event.target.value as ReportLayout["accent"])
                }
              >
                <option value="sage">Sage</option>
                <option value="teal">Teal</option>
                <option value="slate">Slate</option>
              </select>
            </div>
            <div>
              <label htmlFor="report-table-style">Table style</label>
              <select
                id="report-table-style"
                value={appearance.table_style}
                disabled={busy}
                onChange={(event) =>
                  layout(
                    "table_style",
                    event.target.value as ReportLayout["table_style"],
                  )
                }
              >
                <option value="striped">Alternating rows</option>
                <option value="grid">Grid</option>
                <option value="minimal">Minimal</option>
              </select>
            </div>
            <div>
              <label htmlFor="report-text-width">TXT line width</label>
              <select
                id="report-text-width"
                value={appearance.text_width}
                disabled={busy}
                onChange={(event) =>
                  layout(
                    "text_width",
                    Number(event.target.value) as ReportLayout["text_width"],
                  )
                }
              >
                {[72, 88, 100].map((width) => (
                  <option key={width} value={width}>
                    {width} characters
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="report-json-indent">JSON indentation</label>
              <select
                id="report-json-indent"
                value={appearance.json_indent}
                disabled={busy}
                onChange={(event) =>
                  layout(
                    "json_indent",
                    Number(event.target.value) as ReportLayout["json_indent"],
                  )
                }
              >
                <option value={2}>2 spaces</option>
                <option value={4}>4 spaces</option>
              </select>
            </div>
          </div>
          <label className="report-page-number-toggle">
            <input
              type="checkbox"
              checked={appearance.page_numbers}
              disabled={busy}
              onChange={(event) => layout("page_numbers", event.target.checked)}
            />
            <span>Show page numbers in PDF and Word</span>
          </label>
        </section>
        {error && (
          <div className="workspace-error" role="alert">
            <p>{error}</p>
            <button
              type="button"
              className="quiet-button"
              disabled={busy}
              onClick={() => void reload()}
            >
              Reload saved format
            </button>
          </div>
        )}
        {notice && (
          <p className="settings-saved" role="status">
            {notice}
          </p>
        )}
        <div className="settings-actions">
          <button
            className="quiet-button"
            type="button"
            disabled={busy}
            onClick={() => {
              presentation("layout", { ...defaultReportLayout });
              setNotice("Default appearance is in the form. Save to apply it.");
            }}
          >
            Reset appearance
          </button>
          <button
            className="primary-button"
            type="submit"
            disabled={busy || JSON.stringify(draft) === JSON.stringify(saved)}
          >
            {busy ? "Saving…" : "Save report format"}
          </button>
        </div>
      </form>
      <section
        className="report-format-preview card"
        aria-labelledby="report-format-preview-title"
      >
        <header>
          <div>
            <p className="eyebrow">TEMPLATE PREVIEW</p>
            <h2 id="report-format-preview-title">
              Preview your report format.
            </h2>
            <p>Placeholders only · No research performed</p>
          </div>
          <button
            type="button"
            className="quiet-button"
            disabled={downloadBusy || previewBusy}
            onClick={() => void download()}
          >
            {downloadBusy
              ? "Preparing…"
              : `Download ${downloadFormat === "docx" ? "Word" : downloadFormat === "text" ? "TXT" : downloadFormat.toUpperCase()} template`}
          </button>
        </header>
        <div className="report-preview-controls">
          <label>
            Report view
            <select
              aria-label="Preview report view"
              value={view}
              onChange={(event) => setView(event.target.value as PreviewViews)}
            >
              <option value="pi">Summary</option>
              <option value="audit">Technical View</option>
              <option value="both">Both reports</option>
            </select>
          </label>
          <label>
            Preview format
            <select
              aria-label="Preview format"
              value={format}
              onChange={(event) =>
                setFormat(event.target.value as ExportFormat | "screen")
              }
            >
              <option value="screen">On screen</option>
              <option value="text">TXT</option>
              <option value="json">JSON</option>
              <option value="pdf">PDF</option>
              <option value="docx">Word</option>
            </select>
          </label>
        </div>
        {previewError && (
          <div className="workspace-error" role="alert">
            <p>{previewError}</p>
            <button
              type="button"
              className="quiet-button"
              onClick={() => setAttempt((value) => value + 1)}
            >
              Retry preview
            </button>
          </div>
        )}
        {previewBusy && <p role="status">Updating template preview…</p>}
        {preview && !previewError && (
          <div className="report-preview-content" aria-busy={previewBusy}>
            {format === "screen" ? (
              <>
                <p className="report-preview-note">
                  This uses the same report display as your chats. Placeholder
                  rows show the layout, without material claims or scores.
                </p>
                {preview.documents ? (
                  <div className="report-screen-previews">
                    {(view === "pi" || view === "both") && (
                      <ReportContent
                        content={preview.documents.pi_summary}
                        view="pi"
                        presentation={preview.presentation}
                      />
                    )}
                    {(view === "audit" || view === "both") && (
                      <ReportContent
                        content={preview.documents.technical_audit}
                        view="audit"
                        presentation={preview.presentation}
                      />
                    )}
                  </div>
                ) : (
                  <p>
                    The on-screen template is unavailable from this
                    installation. PDF, Word and text previews remain available.
                  </p>
                )}
              </>
            ) : format === "text" || format === "json" ? (
              <pre
                tabIndex={0}
                aria-label={
                  format === "text"
                    ? "TXT template preview"
                    : "JSON template preview"
                }
              >
                {format === "text" ? preview.text : preview.json}
              </pre>
            ) : (
              <>
                <p className="report-preview-note">{`Representative ${format === "pdf" ? "PDF" : "Word"} layout. Download the template to inspect final pagination.`}</p>
                <iframe
                  title={`${view === "pi" ? "Summary" : view === "audit" ? "Technical View" : "Both reports"} ${format === "pdf" ? "PDF" : "Word"} layout preview`}
                  sandbox="allow-same-origin"
                  referrerPolicy="no-referrer"
                  src={preview.render_url}
                />
              </>
            )}
          </div>
        )}
      </section>
    </section>
  );
}
