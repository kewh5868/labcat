import { publicLink, validatePresentation } from "./workspaceApi";
import type { ReportPresentation, Source } from "./workspaceApi";
import { savedReportTables } from "./reportTables";
import { safeMaterialNames } from "./chemicalNamesApi";
import type { MaterialName } from "./chemicalNamesApi";

export interface ReportReference {
  id: string;
  title: string;
  url: string;
  source_name: string;
  kind: "material_evidence" | "discovery_reference";
}
export interface PresentedReport {
  version: "report-presentation-v2";
  chat_id: string;
  report_id: string;
  format_source: "saved" | "current";
  settings_source: "saved-report" | "current-settings" | "defaults";
  presentation: ReportPresentation;
  pi_summary: string;
  technical_audit: string;
  report_tables: unknown;
  references: ReportReference[];
  legacy: boolean;
  material_names?: MaterialName[];
}
function invalid() {
  return new Error(
    "The report layout could not be loaded. The original saved report remains available.",
  );
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw invalid();
  return value as Record<string, unknown>;
}
function text(value: unknown, maximum = 12000): value is string {
  return typeof value === "string" && value.length <= maximum;
}
export function parsePresentedReport(
  value: unknown,
  chatId: string,
  reportId: string,
  formatSource: "saved" | "current",
): PresentedReport {
  const item = object(value);
  if (
    item.version !== "report-presentation-v2" ||
    item.chat_id !== chatId ||
    item.report_id !== reportId ||
    item.format_source !== formatSource ||
    !["saved-report", "current-settings", "defaults"].includes(
      String(item.settings_source),
    ) ||
    (formatSource === "current" &&
      item.settings_source !== "current-settings") ||
    !text(item.pi_summary, 2_000_000) ||
    !text(item.technical_audit, 2_000_000) ||
    typeof item.legacy !== "boolean" ||
    !Array.isArray(item.references) ||
    item.references.length > 1000
  )
    throw invalid();
  validatePresentation(item.presentation);
  if (
    item.report_tables !== null &&
    !savedReportTables({ report_tables: item.report_tables })
  )
    throw invalid();
  const references = item.references.map((value) => {
    const reference = object(value);
    if (
      !text(reference.id, 12) ||
      !/^[RS][1-9][0-9]{0,4}$/.test(reference.id) ||
      !text(reference.title) ||
      !text(reference.source_name, 200) ||
      !text(reference.url, 4000) ||
      !["material_evidence", "discovery_reference"].includes(
        String(reference.kind),
      ) ||
      !publicLink({ url: reference.url, access_scope: "public" } as Source)
    )
      throw invalid();
    return reference as unknown as ReportReference;
  });
  if (new Set(references.map(({ id }) => id)).size !== references.length)
    throw invalid();
  return {
    ...item,
    references,
    ...(item.material_names !== undefined
      ? { material_names: safeMaterialNames(item.material_names) }
      : {}),
  } as unknown as PresentedReport;
}
export const reportPresentationApi = {
  async load(
    chatId: string,
    reportId: string,
    formatSource: "saved" | "current",
    signal: AbortSignal,
  ): Promise<PresentedReport> {
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) controller.abort();
    const timeout = window.setTimeout(abort, 20000);
    try {
      const response = await fetch(
        `/api/chats/${encodeURIComponent(chatId)}/reports/${encodeURIComponent(reportId)}/presentation?format_source=${formatSource}`,
        {
          signal: controller.signal,
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
          headers: { Accept: "application/json" },
        },
      );
      if (!response.ok) throw invalid();
      return parsePresentedReport(
        await response.json(),
        chatId,
        reportId,
        formatSource,
      );
    } catch {
      throw invalid();
    } finally {
      window.clearTimeout(timeout);
      signal.removeEventListener("abort", abort);
    }
  },
};
