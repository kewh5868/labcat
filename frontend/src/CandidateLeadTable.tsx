import type { ReactNode } from "react";
import ChemicalName from "./MaterialName";
import type { ReportReference } from "./reportPresentationApi";
import type { ReportView } from "./workspaceApi";
import { publicLink } from "./workspaceApi";
import type { Source } from "./workspaceApi";

interface LeadCitation {
  document_id: string;
  source_id: string;
  record_id: string;
  url: string;
  title: string;
  quote: string;
}
export interface CandidateLead extends Omit<LeadCitation, "document_id"> {
  id: string;
  name: string;
  status: "candidate_lead";
  properties_verified: false;
  suitability_verified: false;
  missing_criteria: string[];
  cautions: string[];
  citations: LeadCitation[];
}
const headers = [
  "Review order",
  "Candidate",
  "Source",
  "Supporting quote",
  "Missing measurements",
];
const gapLabels: Record<string, string> = {
  stability: "Thermodynamic stability",
  ambient_phase_stability: "Room-temperature phase stability",
  operational_stability: "Operational stability",
  band_gap: "Band gap",
  dielectric_total: "Total dielectric scalar",
  dielectric_electronic: "Electronic dielectric scalar",
  density: "Density",
  bulk_modulus: "Bulk modulus (VRH)",
  shear_modulus: "Shear modulus (VRH)",
  nsites: "Cell site count",
  metallicity: "Metallic character",
  direct_gap: "Direct band gap",
  element_screen: "Element screening",
  simplicity: "Composition simplicity",
  evidence_quality: "Supported-field completeness",
};
function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
function text(value: unknown, max: number): value is string {
  return (
    typeof value === "string" && value.trim().length > 0 && value.length <= max
  );
}
function clean(value: string) {
  return value.trim().replace(/\s+/gu, " ").replaceAll("|", "/");
}
function excerpt(value: string, limit: number) {
  const normalized = clean(value);
  if (normalized.length <= limit) return normalized;
  const prefix = normalized.slice(0, limit),
    space = prefix.lastIndexOf(" ");
  return (space < 0 ? prefix : prefix.slice(0, space)) + "…";
}
function label(id: string) {
  const value = id.replaceAll("_", " ");
  return gapLabels[id] ?? value[0].toUpperCase() + value.slice(1);
}
function citation(
  value: unknown,
  references: ReportReference[],
): value is LeadCitation {
  if (
    !object(value) ||
    !text(value.document_id, 28) ||
    !/^doc-[a-f0-9]{24}$/.test(value.document_id) ||
    !text(value.source_id, 120) ||
    !text(value.record_id, 200) ||
    !text(value.title, 1200) ||
    !text(value.quote, 480) ||
    !text(value.url, 2048)
  )
    return false;
  return (
    value.url.startsWith("https://") &&
    publicLink({ access_scope: "public", url: value.url } as Source) ===
      value.url &&
    references.some(
      (reference) =>
        reference.kind === "discovery_reference" && reference.url === value.url,
    )
  );
}
export function savedCandidateLeads(
  value: unknown,
  references: ReportReference[],
): CandidateLead[] | null {
  if (!Array.isArray(value) || value.length === 0 || value.length > 12)
    return null;
  for (const item of value) {
    if (
      !object(item) ||
      !text(item.id, 29) ||
      !/^lead-[a-f0-9]{24}$/.test(item.id) ||
      !text(item.name, 120) ||
      item.status !== "candidate_lead" ||
      item.properties_verified !== false ||
      item.suitability_verified !== false ||
      Object.keys(item).some(
        (key) =>
          ![
            "id",
            "name",
            "quote",
            "source_id",
            "record_id",
            "url",
            "title",
            "status",
            "properties_verified",
            "suitability_verified",
            "missing_criteria",
            "cautions",
            "citations",
          ].includes(key),
      ) ||
      !Array.isArray(item.missing_criteria) ||
      item.missing_criteria.length > 103 ||
      !item.missing_criteria.every(
        (key) => typeof key === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(key),
      ) ||
      new Set(item.missing_criteria).size !== item.missing_criteria.length ||
      !Array.isArray(item.cautions) ||
      item.cautions.length < 1 ||
      item.cautions.length > 10 ||
      !item.cautions.every((note) => text(note, 1200)) ||
      !Array.isArray(item.citations) ||
      item.citations.length < 1 ||
      item.citations.length > 4 ||
      !item.citations.every((entry) => citation(entry, references))
    )
      return null;
    const missing = item.missing_criteria;
    if (
      !["stability", "ambient_phase_stability", "operational_stability"].every(
        (key) => missing.includes(key),
      )
    )
      return null;
    const first = item.citations[0];
    if (
      !(Object.keys(first) as (keyof LeadCitation)[])
        .filter((key) => key !== "document_id")
        .every((key) => item[key] === first[key])
    )
      return null;
  }
  return new Set(value.map((item) => item.id)).size === value.length
    ? (value as CandidateLead[])
    : null;
}
export function candidateLeadCells(
  leads: CandidateLead[],
  view: ReportView,
  references: ReportReference[],
): string[][] {
  return (view === "pi" ? leads.slice(0, 5) : leads).map((lead, index) => [
    String(index + 1),
    clean(lead.name),
    excerpt(lead.title, view === "pi" ? 100 : 160) +
      ` [${references.find((reference) => reference.url === lead.url)?.id}]`,
    "“" + excerpt(lead.quote, view === "pi" ? 180 : 240) + "”",
    lead.missing_criteria.map(label).join("; "),
  ]);
}
export function matchesCandidateLeadTable(
  labels: string[],
  cells: string[][],
  expected: string[][],
) {
  return (
    labels.length === headers.length &&
    labels.every((value, index) => value === headers[index]) &&
    cells.length === expected.length &&
    cells.every(
      (row, index) =>
        row.length === headers.length &&
        row.every((cell, column) => cell === expected[index][column]),
    )
  );
}
export default function CandidateLeadTable({
  leads,
  cells,
  renderRow,
}: {
  leads: CandidateLead[];
  cells: string[][];
  renderRow?: (
    lead: CandidateLead,
    cells: (action?: ReactNode) => ReactNode,
  ) => ReactNode;
}) {
  return (
    <div
      className="report-shortlist-scroll"
      tabIndex={0}
      role="region"
      aria-label="Source-grounded candidate leads, scroll horizontally if needed"
    >
      <table className="report-shortlist-table report-lead-table">
        <caption>
          Source-grounded candidates · Review order, not performance ranking
        </caption>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header} scope="col">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cells.map((row, index) => {
            const contents = (action?: ReactNode) => (
              <>
                <td>{row[0]}</td>
                <td>
                  <strong>{row[1]}</strong>
                  <ChemicalName
                    target={{ kind: "lead", id: leads[index].id }}
                    formula={leads[index].name}
                  />
                  <small>Suitability unverified</small>
                  {action}
                </td>
                <td>
                  <a
                    href={leads[index].url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {row[2]}
                    <span className="sr-only"> (opens source)</span>
                  </a>
                </td>
                <td>
                  <blockquote>{row[3]}</blockquote>
                </td>
                <td>{row[4]}</td>
              </>
            );
            return renderRow ? (
              renderRow(leads[index], contents)
            ) : (
              <tr key={leads[index].id}>{contents()}</tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
