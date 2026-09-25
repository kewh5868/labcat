import { validatePresentation } from "./workspaceApi";
import type { ExportFormat, ReportPresentation } from "./workspaceApi";

export type PreviewViews = "pi" | "audit" | "both";
export interface ReportPreview {
  render_url: string;
  label: string;
  html: string;
  text: string;
  json: string;
  presentation: ReportPresentation;
  layout_note: string;
  documents?: { pi_summary: string; technical_audit: string };
}
const failure = () =>
  new Error(
    "Report preview could not be prepared. Check the format settings and try again.",
  );
function body(presentation: ReportPresentation, views: PreviewViews) {
  validatePresentation(presentation);
  if (!["pi", "audit", "both"].includes(views)) throw failure();
  return { presentation, views };
}
async function request(
  payload: unknown,
  action: "preview" | "download" | "download-link",
  signal?: AbortSignal,
): Promise<Response> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timeout = window.setTimeout(abort, 20000);
  try {
    const session = await fetch("/api/session", {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal: controller.signal,
    });
    if (!session.ok) throw failure();
    const value: unknown = await session.json();
    if (
      !value ||
      typeof value !== "object" ||
      !("csrf_token" in value) ||
      typeof value.csrf_token !== "string" ||
      !/^[A-Za-z0-9_-]{20,200}$/.test(value.csrf_token)
    )
      throw failure();
    const response = await fetch(
      action === "preview"
        ? "/api/report-preview"
        : `/api/report-preview/${action}`,
      {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": value.csrf_token,
        },
        body: JSON.stringify(payload),
      },
    );
    if (!response.ok) throw failure();
    return response;
  } catch (error) {
    if (signal?.aborted) throw error;
    throw failure();
  } finally {
    window.clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}
export const reportFormatApi = {
  async preview(
    presentation: ReportPresentation,
    views: PreviewViews,
    signal?: AbortSignal,
  ): Promise<ReportPreview> {
    const response = await request(
      body(presentation, views),
      "preview",
      signal,
    );
    const data: unknown = await response.json();
    if (!data || typeof data !== "object") throw failure();
    const item = data as Record<string, unknown>;
    if (
      !["label", "html", "text", "json", "layout_note"].every(
        (key) =>
          typeof item[key] === "string" &&
          (item[key] as string).length <= 2_000_000,
      ) ||
      item.download_endpoint !== "/api/report-preview/download" ||
      typeof item.render_url !== "string" ||
      !/^\/api\/report-preview\/render\/[a-f0-9]{32}$/.test(item.render_url)
    )
      throw failure();
    validatePresentation(item.presentation);
    if (item.documents !== undefined) {
      const documents = item.documents as Record<string, unknown>;
      if (
        !documents ||
        typeof documents !== "object" ||
        Array.isArray(documents) ||
        !["pi_summary", "technical_audit"].every(
          (key) =>
            typeof documents[key] === "string" &&
            (documents[key] as string).length <= 2_000_000,
        )
      )
        throw failure();
    }
    return item as unknown as ReportPreview;
  },
  async downloadLink(
    presentation: ReportPresentation,
    views: PreviewViews,
    format: ExportFormat,
  ): Promise<{ url: string; filename: string }> {
    if (!["text", "json", "pdf", "docx"].includes(format)) throw failure();
    const response = await request(
      { ...body(presentation, views), format },
      "download-link",
    );
    const item: unknown = await response.json();
    if (
      !item ||
      typeof item !== "object" ||
      !("url" in item) ||
      !("filename" in item) ||
      typeof item.url !== "string" ||
      typeof item.filename !== "string" ||
      !new RegExp(
        `^/api/report-preview/download/[a-f0-9]{32}\\?format=${format}$`,
      ).test(item.url) ||
      !/^labcat-[A-Za-z0-9_-]+\.(?:txt|json|pdf|docx)$/.test(item.filename)
    )
      throw failure();
    return { url: item.url, filename: item.filename };
  },
  async download(
    presentation: ReportPresentation,
    views: PreviewViews,
    format: ExportFormat,
    signal?: AbortSignal,
  ): Promise<Blob> {
    if (!["text", "json", "pdf", "docx"].includes(format)) throw failure();
    const response = await request(
      { ...body(presentation, views), format },
      "download",
      signal,
    );
    const types = {
      text: "text/plain",
      json: "application/json",
      pdf: "application/pdf",
      docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    };
    if (response.headers.get("Content-Type")?.split(";")[0] !== types[format])
      throw failure();
    const blob = await response.blob();
    if (!blob.size || blob.size > 20_000_000) throw failure();
    return blob;
  },
};
