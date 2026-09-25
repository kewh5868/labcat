import { validatePresentation } from "./workspaceApi";
import type { ReportPresentation } from "./workspaceApi";
import { validBandGapTarget, validMinimumBandGap } from "./rankingProfilesApi";

export interface ReportColumn {
  id: string;
  label: string;
  kind: "rank" | "identity" | "score" | "property" | "text";
  unit?: string;
}
export interface ReportProperty {
  value: number | boolean | string | null;
  unit: string;
  status: "available" | "unknown" | "unavailable";
  display: string;
  utility: number;
  contribution: number;
  weight: number;
  citation_ids: string[];
}
export interface ScoreAnalysis {
  observed_fit: number;
  coverage: number;
  possible_upper_score: number;
  required_criteria: string[];
  missing_required_criteria: string[];
  status: "comparable" | "needs_evidence";
}
export interface ReportRow {
  rank: number;
  material_id: string;
  formula: string;
  source_formula?: string;
  material: string;
  score: number;
  score_analysis?: ScoreAnalysis;
  score_color: string;
  score_band: "low" | "medium" | "high";
  properties: Record<string, ReportProperty>;
  citation_ids: string[];
  rationale: string;
  caveats: string[];
  missing_criteria: string[];
  selected_weight_coverage: number;
  leading?: string;
  caveat?: string;
}
export interface ReportTable {
  columns: ReportColumn[];
  rows: ReportRow[];
}
export interface ReportTables {
  summary: ReportTable;
  technical: ReportTable;
}
export interface ProfileSnapshot {
  name: string;
  material_class: string;
  application: string;
  importance: Record<string, number>;
  minimum_band_gap_ev?: number | null;
  target_band_gap_ev?: number | null;
  band_gap_tolerance_ev?: number | null;
  normalized_weights?: Record<string, number>;
  selection_reason?: string;
}

function object(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
function text(value: unknown): value is string {
  return typeof value === "string" && value.length <= 12000;
}
function fraction(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= 1
  );
}
function texts(value: unknown): value is string[] {
  return Array.isArray(value) && value.length <= 200 && value.every(text);
}
function weights(value: unknown): value is Record<string, number> {
  const record = object(value);
  return (
    !!record &&
    Object.keys(record).length <= 100 &&
    Object.values(record).every(fraction)
  );
}
function scoreAnalysis(
  value: unknown,
  row: Record<string, unknown>,
): value is ScoreAnalysis {
  const record = object(value);
  const keys = [
    "observed_fit",
    "coverage",
    "possible_upper_score",
    "required_criteria",
    "missing_required_criteria",
    "status",
  ];
  const criterionIds = (value: unknown): value is string[] =>
    Array.isArray(value) &&
    value.length <= 100 &&
    value.every(
      (id) => typeof id === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(id),
    ) &&
    new Set(value).size === value.length;
  if (
    !record ||
    Object.keys(record).length !== keys.length ||
    !keys.every((key) => Object.hasOwn(record, key)) ||
    !fraction(record.observed_fit) ||
    !fraction(record.coverage) ||
    !fraction(record.possible_upper_score) ||
    !criterionIds(record.required_criteria) ||
    !criterionIds(record.missing_required_criteria) ||
    !["comparable", "needs_evidence"].includes(record.status as string)
  )
    return false;
  const required = record.required_criteria;
  if (
    record.missing_required_criteria.some((id) => !required.includes(id)) ||
    (record.status === "needs_evidence") !==
      record.missing_required_criteria.length > 0
  )
    return false;
  // The server rounds the saved score; tolerate that rounding without allowing
  // contradictory fit/coverage metadata to replace the saved contribution.
  const tolerance = 1e-7;
  return (
    Math.abs(record.coverage - Number(row.selected_weight_coverage)) <=
      tolerance &&
    Math.abs(record.observed_fit * record.coverage - Number(row.score)) <=
      tolerance &&
    Math.abs(
      record.possible_upper_score -
        Math.min(1, Number(row.score) + 1 - record.coverage),
    ) <= tolerance
  );
}
function property(value: unknown): value is ReportProperty {
  const record = object(value);
  return (
    !!record &&
    text(record.display) &&
    text(record.unit) &&
    (record.value === null ||
      typeof record.value === "boolean" ||
      text(record.value) ||
      (typeof record.value === "number" && Number.isFinite(record.value))) &&
    ["available", "unknown", "unavailable"].includes(record.status as string) &&
    fraction(record.utility) &&
    fraction(record.contribution) &&
    fraction(record.weight) &&
    texts(record.citation_ids)
  );
}
function table(value: unknown): ReportTable | null {
  const record = object(value);
  if (
    !record ||
    !Array.isArray(record.columns) ||
    record.columns.length < 3 ||
    record.columns.length > 103 ||
    !Array.isArray(record.rows) ||
    record.rows.length > 200
  )
    return null;
  const columns: ReportColumn[] = [];
  for (const value of record.columns) {
    const column = object(value);
    if (
      !column ||
      !text(column.id) ||
      !text(column.label) ||
      (column.unit !== undefined && !text(column.unit)) ||
      !["rank", "identity", "score", "property", "text"].includes(
        column.kind as string,
      ) ||
      (column.kind === "text" && !["leading", "caveat"].includes(column.id))
    )
      return null;
    columns.push(column as unknown as ReportColumn);
  }
  if (
    columns[0].kind !== "rank" ||
    columns[1].kind !== "identity" ||
    columns[2].kind !== "score" ||
    new Set(columns.map((column) => column.id)).size !== columns.length
  )
    return null;
  for (const value of record.rows) {
    const row = object(value),
      properties = object(row?.properties);
    if (
      !row ||
      !properties ||
      !Number.isSafeInteger(row.rank) ||
      Number(row.rank) < 1 ||
      !["material_id", "formula", "material", "rationale"].every((key) =>
        text(row[key]),
      ) ||
      (row.source_formula !== undefined &&
        (typeof row.source_formula !== "string" ||
          row.source_formula.length > 256)) ||
      !fraction(row.score) ||
      !/^#[0-9a-f]{6}$/i.test(String(row.score_color)) ||
      !["low", "medium", "high"].includes(row.score_band as string) ||
      !texts(row.citation_ids) ||
      !texts(row.caveats) ||
      !texts(row.missing_criteria) ||
      !fraction(row.selected_weight_coverage) ||
      (row.score_analysis !== undefined &&
        !scoreAnalysis(row.score_analysis, row)) ||
      columns.some((column) =>
        column.kind === "property"
          ? !property(properties[column.id])
          : column.kind === "text" && !text(row[column.id]),
      )
    )
      return null;
  }
  return { columns, rows: record.rows as ReportRow[] };
}

/** Optional presentation metadata is never reconstructed from current settings
 * or scientific claims in report text. Unknown older schemas keep their prose.
 */
export function savedReportTables(result: unknown): ReportTables | null {
  const value = object(object(result)?.report_tables);
  if (!value || value.schema !== "ranking-tables-v1") return null;
  const summary = table(value.summary),
    technical = table(value.technical);
  return summary && technical ? { summary, technical } : null;
}
export function savedProfileSnapshot(result: unknown): ProfileSnapshot | null {
  const execution = object(object(result)?.execution),
    profile = object(execution?.ranking_profile);
  if (
    !profile ||
    !text(profile.name) ||
    !text(profile.material_class) ||
    !text(profile.application) ||
    !weights(profile.importance) ||
    !validMinimumBandGap(profile.minimum_band_gap_ev) ||
    !validBandGapTarget(
      profile.target_band_gap_ev,
      profile.band_gap_tolerance_ev,
    )
  )
    return null;
  const selection = object(execution?.ranking_selection);
  return {
    name: profile.name,
    material_class: profile.material_class,
    application: profile.application,
    importance: profile.importance,
    ...(profile.minimum_band_gap_ev !== undefined
      ? { minimum_band_gap_ev: profile.minimum_band_gap_ev }
      : {}),
    ...(profile.target_band_gap_ev !== undefined
      ? { target_band_gap_ev: profile.target_band_gap_ev as number | null }
      : {}),
    ...(profile.band_gap_tolerance_ev !== undefined
      ? {
          band_gap_tolerance_ev: profile.band_gap_tolerance_ev as number | null,
        }
      : {}),
    ...(weights(profile.normalized_weights)
      ? { normalized_weights: profile.normalized_weights }
      : {}),
    ...(text(selection?.reason) ? { selection_reason: selection.reason } : {}),
  };
}
export function savedReportPresentation(
  result: unknown,
): ReportPresentation | null {
  try {
    return validatePresentation(
      object(object(result)?.execution)?.presentation,
    );
  } catch {
    return null;
  }
}
