import type { CSSProperties, ReactNode } from "react";
import { createContext, useContext, useRef } from "react";
import type { CandidateLead } from "./CandidateLeadTable";
import CandidateLeadTable, {
  candidateLeadCells,
  matchesCandidateLeadTable,
  savedCandidateLeads,
} from "./CandidateLeadTable";
import ChemicalName, { MaterialNamesContext } from "./MaterialName";
import { safeMaterialNames } from "./chemicalNamesApi";
import "./reportContent.css";
import type { ReportReference } from "./reportPresentationApi";
import type { ReportColumn, ReportRow, ReportTable } from "./reportTables";
import type { StructureTarget } from "./structureApi";
import type { ReportPresentation, ReportView } from "./workspaceApi";
import { defaultReportLayout } from "./workspaceApi";

const FormulaTypographyContext = createContext<readonly string[]>([]);
// Same conservative symbol subset as the server's flat-formula display parser.
// This is typography only, never a material identity or composition inference.
const formulaSymbols = new Set(
  "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr".split(
    " ",
  ),
);

function flatFormulaParts(
  formula: string,
): { symbol: string; count: string }[] | null {
  if (!formula || formula.length > 256) return null;
  const parts = [...formula.matchAll(/([A-Z][a-z]?)([1-9][0-9]*)?/g)];
  if (
    parts.map((part) => part[0]).join("") !== formula ||
    new Set(parts.map((part) => part[1])).size !== parts.length ||
    parts.some((part) => !formulaSymbols.has(part[1]))
  )
    return null;
  return parts.map((part) => ({ symbol: part[1], count: part[2] ?? "" }));
}

function FormulaText({
  text,
  formulas,
}: {
  text: string;
  formulas: readonly string[];
}) {
  const known = [
    ...new Set(formulas.filter((formula) => flatFormulaParts(formula))),
  ].sort((a, b) => b.length - a.length);
  if (!known.length) return text;
  const escaped = known.map((formula) =>
    formula.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
  );
  const tokens = new RegExp(
    `(?<![\\p{L}\\p{N}_./:+·-])(${escaped.join("|")})(?![\\p{L}\\p{N}_/:+·-]|\\.[\\p{L}\\p{N}])`,
    "gu",
  );
  // URL/DOI text is an identifier, even when it contains a known formula.
  return (
    <>
      {text
        .split(/((?:https?:\/\/|www\.)[^\s<]+|\b10\.[0-9]{4,9}\/[^\s<]+)/giu)
        .map((segment, index) =>
          index % 2 ? (
            segment
          ) : (
            <span key={index}>
              {segment
                .split(tokens)
                .map((part, partIndex) =>
                  partIndex % 2 ? (
                    <MaterialFormula key={partIndex} formula={part} />
                  ) : (
                    part
                  ),
                )}
            </span>
          ),
        )}
    </>
  );
}

type ReportBlock =
  | { kind: "heading"; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "literal"; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "table"; headers: string[]; rows: string[][] };

const literatureHeaders = [
  "Provisional rank",
  "Material",
  "Literature fit",
  "Selected criterion assessments",
  "Assessment coverage",
  "Stability & uncertainty",
];
const screeningHeaders = [
  "Rank",
  "Material",
  "Screening priority",
  "Why considered",
  "Attribute evidence",
  "Stability / key caveat",
];
const screeningGroups = [
  {
    label: "First review group",
    description:
      "No application or stability concern was recorded. This group includes unassessed candidates; it does not establish suitability.",
  },
  {
    label: "Mixed evidence",
    description:
      "Mixed application or stability evidence places these candidates after the first group, regardless of percentage.",
  },
  {
    label: "Reported concerns",
    description:
      "A reported application or stability concern places these candidates after the other groups, regardless of percentage.",
  },
];
function isScreeningTable(block: ReportBlock): boolean {
  return (
    block.kind === "table" &&
    block.headers.length === screeningHeaders.length &&
    block.headers.every(
      (header, index) =>
        header === screeningHeaders[index] ||
        (index === 4 && header === "Relevant properties"),
    )
  );
}
function isLiteratureTable(block: ReportBlock): boolean {
  return (
    isScreeningTable(block) ||
    (block.kind === "table" &&
      block.headers.length === literatureHeaders.length &&
      block.headers.every(
        (header, index) => header === literatureHeaders[index],
      ))
  );
}

function RelevantProperties({
  text,
  references,
}: {
  text: string;
  references: ReportReference[];
}) {
  // Expand original source context instead of promoting quoted device values
  // or model interpretation to an intrinsic material measurement.
  const properties = text.split(" ▪ ");
  if (properties.length > 3)
    return (
      <ReportText
        text={text}
        references={references}
        chemicalTypography={false}
      />
    );
  return (
    <ul className="report-relevant-properties">
      {properties.map((property, index) => {
        const split = property.indexOf(" — ");
        if (split < 0)
          return (
            <li key={index}>
              <ReportText
                text={property}
                references={references}
                chemicalTypography={false}
              />
            </li>
          );
        const label = property.slice(0, split),
          evidence = property.slice(split + 3);
        const long = evidence.length > 220;
        return (
          <li key={index}>
            <strong>{label}</strong>
            {long ? (
              <>
                <span className="report-property-excerpt">
                  <ReportText
                    text={evidence.slice(0, 180) + "…"}
                    references={references}
                    chemicalTypography={false}
                  />
                </span>
                <details>
                  <summary>Full source passage</summary>
                  <ReportText
                    text={evidence}
                    references={references}
                    chemicalTypography={false}
                  />
                </details>
              </>
            ) : (
              <span>
                <ReportText
                  text={evidence}
                  references={references}
                  chemicalTypography={false}
                />
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function screeningPriority(cell: string) {
  // Only the current server renderer's explicit status labels authorize these
  // colors. Historical "No adverse assessment" does not establish an assessment.
  const match = cell.match(
    /^(\d{1,3})% · (Unassessed review prior|Assessed review priority|Mixed evidence|Concern reported)$/,
  );
  if (!match || Number(match[1]) > 100) return null;
  const percentage = Number(match[1]),
    label = match[2];
  const state =
    label === "Unassessed review prior"
      ? "unassessed"
      : label === "Mixed evidence"
        ? "mixed"
        : label === "Concern reported"
          ? "concern"
          : "assessed";
  const fixedColors = {
    unassessed: "#EDF0F2",
    mixed: "#FFE0B2",
    concern: "#F8D7DA",
  };
  const color =
    state === "assessed"
      ? `#${[255, 240, 194]
          .map((low, index) =>
            Math.round(
              low + (([213, 237, 221][index] - low) * percentage) / 100,
            )
              .toString(16)
              .padStart(2, "0"),
          )
          .join("")}`
      : fixedColors[state];
  const explanation =
    state === "unassessed"
      ? "This score comes entirely from a fixed review prior. Application relevance, demonstrated use and selected attributes lack informative assessments. It is not evidence of suitability or a favorable finding."
      : state === "mixed"
        ? "Retained application or stability assessments include mixed evidence. This caution takes precedence over the numerical review priority."
        : state === "concern"
          ? "A retained application or stability assessment reports a concern. This caution takes precedence over the numerical review priority."
          : "Review priority uses retained source-passage assessments, refined by available selected-attribute evidence. Higher values mean higher review priority, not better established material performance.";
  return {
    percentage,
    label,
    state,
    color,
    explanation: `${explanation} The percentage is not a success rate or confidence.`,
  };
}

function ScreeningPriorityLegend() {
  return (
    <div
      className="report-screening-legend"
      role="note"
      aria-label="Screening priority color key"
    >
      <p>
        Color shows review priority and assessment status, not performance or
        confidence.
      </p>
      <div>
        <span>
          <i className="report-screening-gradient" aria-hidden="true" />
          Assessed priority: lower → higher
        </span>
        <span>
          <i
            className="report-screening-swatch report-screening-unassessed"
            aria-hidden="true"
          />
          Unassessed prior
        </span>
        <span>
          <i
            className="report-screening-swatch report-screening-mixed"
            aria-hidden="true"
          />
          Mixed evidence
        </span>
        <span>
          <i
            className="report-screening-swatch report-screening-concern"
            aria-hidden="true"
          />
          Concern reported
        </span>
      </div>
      <p>
        Gray is a default for missing assessments. A missing concern is not a
        favorable finding.
      </p>
    </div>
  );
}

function SupportedScoreLegend() {
  return (
    <p className="report-score-legend">
      <span className="report-score-gradient" aria-hidden="true" />
      <span>
        Supported score (0–1) is the weighted contribution backed by retrieved
        evidence, not predicted material performance. Coverage shows how much
        selected importance has evidence. Color applies only with complete
        evidence; neutral badges mark incomplete evidence or historical
        contributions.
      </span>
    </p>
  );
}

const methodHeadings = new Set([
  "ranking method",
  "preliminary ranking method",
  "measured-property ranking method",
  "research completion",
  "requested ranking goals",
  "retrieval and methods",
  "audit archive",
]);
function formulaSignature(formula: string): string | undefined {
  return flatFormulaParts(formula)
    ?.map(({ symbol, count }) => `${symbol}:${count}`)
    .sort()
    .join(";");
}

function tableCells(line: string): string[] | null {
  const value = line.trim();
  if (!value.startsWith("|") || !value.endsWith("|")) return null;
  const cells = value
    .slice(1, -1)
    .split("|")
    .map((cell) => cell.trim());
  return cells.length >= 2 ? cells : null;
}

function isHeading(line: string): boolean {
  // Report templates use short, standalone "Heading:" lines. URLs, markup and
  // inline instructions receive no extra interpretation or interactive behavior.
  return /^[\p{L}\p{N}][\p{L}\p{N} .,/&()—–·-]{0,119}:$/u.test(
    line.trim().replace(/\[[RS][1-9][0-9]{0,4}\]/g, "R"),
  );
}

function tableStart(lines: string[], index: number): string[] | null {
  const headers = tableCells(lines[index]);
  const separator = tableCells(lines[index + 1] ?? "");
  return headers &&
    separator &&
    headers.length === separator.length &&
    separator.every((cell) => /^-{3,}$/.test(cell))
    ? headers
    : null;
}

function isCodeFence(line: string): boolean {
  return /^```[a-zA-Z0-9_-]*\s*$/.test(line.trim());
}

function reportBlocks(content: string, maxColumns = 12): ReportBlock[] {
  const lines = content.replace(/\r\n?/g, "\n").split("\n");
  const blocks: ReportBlock[] = [];
  let index = 0;
  while (index < lines.length) {
    if (!lines[index].trim()) {
      index += 1;
      continue;
    }
    if (isCodeFence(lines[index])) {
      const start = index++;
      while (index < lines.length && lines[index].trim() !== "```") index += 1;
      const closed = index < lines.length;
      blocks.push({
        kind: "literal",
        text: lines.slice(closed ? start + 1 : start, index).join("\n"),
      });
      if (closed) index += 1;
      continue;
    }
    const headers = tableStart(lines, index);
    if (headers) {
      const rows: string[][] = [];
      const start = index;
      let valid =
        headers.length <= maxColumns &&
        headers.every((cell) => cell.length <= 4000);
      index += 2;
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        const cells = tableCells(lines[index]);
        if (
          !cells ||
          cells.length !== headers.length ||
          cells.some((cell) => cell.length > 4000)
        )
          valid = false;
        if (cells) rows.push(cells);
        index += 1;
      }
      // Preserve all text when a table is malformed or exceeds useful UI bounds.
      // Do not partially display it as a plausible but incomplete shortlist.
      blocks.push(
        valid && rows.length <= 200
          ? { kind: "table", headers, rows }
          : { kind: "literal", text: lines.slice(start, index).join("\n") },
      );
    } else if (isHeading(lines[index])) {
      blocks.push({ kind: "heading", text: lines[index].trim().slice(0, -1) });
      index += 1;
    } else if (/^- /.test(lines[index])) {
      const items: string[] = [];
      while (index < lines.length && /^- /.test(lines[index])) {
        items.push(lines[index].slice(2));
        index += 1;
      }
      blocks.push({ kind: "list", items });
    } else {
      const paragraph = [lines[index++]];
      while (
        index < lines.length &&
        lines[index].trim() &&
        !isHeading(lines[index]) &&
        !/^- /.test(lines[index]) &&
        !isCodeFence(lines[index]) &&
        !tableStart(lines, index)
      )
        paragraph.push(lines[index++]);
      blocks.push({ kind: "paragraph", text: paragraph.join("\n") });
    }
  }
  return blocks;
}

/** Compact copies of the saved report's primary shortlist. No new ordering,
 * scoring, material parsing, or interpretation of arbitrary Markdown tables. */
export function shortlistPreview(
  content: string,
): { headers: string[]; rows: string[][]; total: number } | null {
  const blocks = reportBlocks(content);
  for (const block of blocks) {
    if (block.kind !== "table" || !block.rows.length) continue;
    let columns: number[] | null = null;
    if (isLiteratureTable(block)) columns = [0, 1, 2, 5];
    else if (
      block.headers[0] === "Rank" &&
      ["Material", "Material (record)"].includes(block.headers[1]) &&
      ["Score", "Supported score"].includes(block.headers[2]) &&
      block.headers.at(-1) === "Key caveat"
    )
      columns = [0, 1, 2, block.headers.length - 1];
    else if (
      block.headers.join("|") ===
      "Review order|Candidate|Source|Supporting quote|Missing measurements"
    )
      columns = [0, 1, 4];
    if (
      !columns ||
      !block.rows.every((row) => /^[1-9][0-9]*(?: \(tie\))?$/.test(row[0]))
    )
      continue;
    return {
      headers: columns.map((index) => block.headers[index]),
      rows: block.rows
        .slice(0, 3)
        .map((row) => columns!.map((index) => row[index])),
      total: block.rows.length,
    };
  }
  return null;
}

/** Only citations in the validated saved-source map become links. Report prose
 * remains text, never HTML, arbitrary Markdown links, styles or scripts. */
function ReportText({
  text,
  references,
  chemicalTypography = true,
}: {
  text: string;
  references: ReportReference[];
  chemicalTypography?: boolean;
}) {
  const formulas = useContext(FormulaTypographyContext);
  return (
    <>
      {text.split(/(\[[RS][1-9][0-9]{0,4}\])/g).map((part, index) => {
        const reference = references.find(({ id }) => part === `[${id}]`);
        return reference ? (
          <a
            key={index}
            className="report-citation"
            href={reference.url}
            title={`${reference.title} · ${reference.source_name}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            {part}
            <span className="sr-only"> {reference.title} (opens source)</span>
          </a>
        ) : chemicalTypography ? (
          <FormulaText key={index} text={part} formulas={formulas} />
        ) : (
          part
        );
      })}
    </>
  );
}

export function MaterialFormula({ formula }: { formula: string }) {
  const parts = flatFormulaParts(formula);
  return (
    <span className="material-formula" aria-label={formula}>
      {parts
        ? parts.map(({ symbol, count }, index) => (
            <span key={index}>
              {symbol}
              {count && <sub>{count}</sub>}
            </span>
          ))
        : formula}
    </span>
  );
}

type StructureScope = { chatId: string; reportId: string };

function InlineStructureRow({
  children,
}: {
  children: (action?: ReactNode) => ReactNode;
  scope?: StructureScope;
  target?: StructureTarget;
  label: string;
  colSpan: number;
}) {
  return <tr>{children()}</tr>;
}

function literatureStructureTarget(
  materialCell: string,
  leads: CandidateLead[] | null,
  references: ReportReference[],
): StructureTarget | undefined {
  if (!leads) return;
  const citations = [
    ...materialCell.matchAll(/\[([RS][1-9][0-9]{0,4})\]/g),
  ].map((match) => match[1]);
  if (!citations.length) return;
  const name = materialCell
    .replace(/\[[RS][1-9][0-9]{0,4}\]/g, "")
    .trim()
    .replace(/\s+/gu, " ");
  const signature = formulaSignature(name);
  const matches = leads.filter((lead) => {
    const savedName = lead.name
      .trim()
      .replace(/\s+/gu, " ")
      .replaceAll("|", "/");
    if (
      savedName !== name &&
      (!signature || signature !== formulaSignature(savedName))
    )
      return false;
    return citations.every((id) =>
      references.some(
        (reference) =>
          reference.id === id &&
          lead.citations.some((citation) => citation.url === reference.url),
      ),
    );
  });
  // Rank and row order are presentation, never identity. Equal names or formula
  // aliases sharing citations must not silently select one of several lead IDs.
  return matches.length === 1 ? { kind: "lead", id: matches[0].id } : undefined;
}

export default function ReportContent({
  content,
  view,
  table,
  candidateLeads,
  references = [],
  presentation,
  afterShortlist,
  onViewStructure,
  structureScope,
  materialNames,
}: {
  content: string;
  view: ReportView;
  table?: ReportTable;
  candidateLeads?: unknown;
  references?: ReportReference[];
  presentation?: ReportPresentation;
  afterShortlist?: ReactNode;
  onViewStructure?: (materialId: string) => void;
  structureScope?: StructureScope;
  materialNames?: unknown;
}) {
  const appearance = { ...defaultReportLayout, ...presentation?.layout };
  const docStyle = {
    "--report-text-size": `${appearance.font_size}pt`,
  } as CSSProperties;
  try {
    const value: unknown = JSON.parse(content);
    if (value && typeof value === "object") {
      return (
        <div className="report-json">
          <p>
            This historical report was saved as structured data. Open the
            archive below to inspect its full contents.
          </p>
          <details className="report-audit-disclosure">
            <summary>Saved JSON report</summary>
            <pre tabIndex={0} aria-label="Report JSON">
              {JSON.stringify(value, null, appearance.json_indent)}
            </pre>
          </details>
          {afterShortlist}
        </div>
      );
    }
  } catch {
    /* Historical text and current prose share the safe block renderer. */
  }
  const blocks = reportBlocks(content, table ? 103 : 12);
  // Current reports have an explicit appendix. Older reports may interleave
  // known process sections with results; move only those sections, preserving
  // every block and its original index for trusted table matching.
  const detailsIndex = blocks.findIndex(
    (block) =>
      block.kind === "heading" && block.text === "Search and analysis details",
  );
  const detailIndexes = new Set<number>();
  let methodSection = false;
  blocks.forEach((block, index) => {
    if (index === detailsIndex) return;
    if (detailsIndex >= 0 && index > detailsIndex) {
      detailIndexes.add(index);
      return;
    }
    if (block.kind === "heading")
      methodSection = methodHeadings.has(block.text.toLowerCase());
    if (methodSection) detailIndexes.add(index);
  });
  const tableIndex = table
    ? blocks.findIndex(
        (block) =>
          block.kind === "table" &&
          block.headers.length === table.columns.length &&
          block.headers.every(
            (label, index) => label === table.columns[index].label,
          ) &&
          block.rows.length === table.rows.length &&
          block.rows.every((cells, rowIndex) =>
            cells.every(
              (cell, columnIndex) =>
                cell ===
                savedCellText(table.rows[rowIndex], table.columns[columnIndex]),
            ),
          ),
      )
    : -1;
  const firstTable = blocks.findIndex(
    (block, index) => block.kind === "table" && !detailIndexes.has(index),
  );
  const leads = savedCandidateLeads(candidateLeads, references);
  const leadCells = leads ? candidateLeadCells(leads, view, references) : [];
  const leadTableIndex = leads
    ? blocks.findIndex(
        (block) =>
          block.kind === "table" &&
          matchesCandidateLeadTable(block.headers, block.rows, leadCells),
      )
    : -1;
  const citedReferences = references.filter(({ id }) =>
    content.includes(`[${id}]`),
  );
  const hasLiteratureEvaluation = blocks.some(isLiteratureTable);
  // A v2 table may contain a display-reordered formula without a property row.
  // Authorize typography only when its tokens match an admitted source name;
  // product names such as PM6 and arbitrary prose remain literal.
  const leadSignatures = new Set(
    (leads ?? []).map(({ name }) => formulaSignature(name)).filter(Boolean),
  );
  const screeningFormulas = blocks.flatMap((block) =>
    block.kind === "table" && isScreeningTable(block)
      ? block.rows
          .map((row) => row[1].replace(/\[[RS][1-9][0-9]{0,4}\]/g, "").trim())
          .filter((name) => {
            const signature = formulaSignature(name);
            return signature && leadSignatures.has(signature);
          })
      : [],
  );
  const formulas = [
    ...(table?.rows.map((row) => row.formula) ?? []),
    ...screeningFormulas,
  ];
  const methodNotes: ReactNode[] = [];
  let inReferences = false;
  const renderedBlocks = blocks.map((block, index) => {
    if (block.kind === "literal")
      return (
        <details key={index} className="report-audit-disclosure">
          <summary>Recorded technical details</summary>
          <pre
            className="report-literal"
            tabIndex={0}
            aria-label="Literal report text"
          >
            {block.text}
          </pre>
        </details>
      );
    if (block.kind === "heading") {
      inReferences = /^(Public references|References|Source references)$/i.test(
        block.text,
      );
      return inReferences && references.length ? null : (
        <h4 className="report-section-heading" key={index}>
          <ReportText
            text={
              block.text === "Technical Overview" ||
              block.text === "Technical Audit"
                ? "Technical View"
                : block.text === "PI Summary"
                  ? "Summary"
                  : block.text
            }
            references={references}
          />
        </h4>
      );
    }
    if (inReferences && references.length) return null;
    if (block.kind === "list")
      return (
        <ul key={index}>
          {block.items.map((item, itemIndex) => (
            <li key={itemIndex}>
              <ReportText text={item} references={references} />
            </li>
          ))}
        </ul>
      );
    if (block.kind === "table" && leads && index === leadTableIndex)
      return (
        <div key={index}>
          <CandidateLeadTable
            leads={leads}
            cells={leadCells}
            renderRow={
              structureScope
                ? (lead, cells) => (
                    <InlineStructureRow
                      key={lead.id}
                      scope={structureScope}
                      target={{ kind: "lead", id: lead.id }}
                      label={lead.name}
                      colSpan={5}
                    >
                      {cells}
                    </InlineStructureRow>
                  )
                : undefined
            }
          />
          {index === firstTable && afterShortlist}
        </div>
      );
    if (block.kind === "table" && isLiteratureTable(block)) {
      const screening = isScreeningTable(block);
      const priorities = screening
        ? block.rows.map((row) => screeningPriority(row[2]))
        : [];
      const tiers = priorities.map((priority) =>
        priority
          ? priority.state === "concern"
            ? 2
            : priority.state === "mixed"
              ? 1
              : 0
          : null,
      );
      // Annotate the server's order; never sort by rounded display percentages
      // or infer ties from them. Unrecognized historical tables stay literal.
      const knownOrder =
        priorities.length > 0 &&
        priorities.every(
          (priority, rowIndex) =>
            priority !== null &&
            /^[1-9][0-9]*$/.test(block.rows[rowIndex][0]) &&
            (rowIndex === 0 ||
              (Number(block.rows[rowIndex][0]) >=
                Number(block.rows[rowIndex - 1][0]) &&
                (tiers[rowIndex]! > tiers[rowIndex - 1]! ||
                  (tiers[rowIndex] === tiers[rowIndex - 1] &&
                    priority.percentage <=
                      priorities[rowIndex - 1]!.percentage)))),
        );
      const showGroups = knownOrder && new Set(tiers).size > 1;
      const groups: { tier: number | null; indexes: number[] }[] = [];
      const rankCounts = new Map<string, number>();
      block.rows.forEach((row, rowIndex) => {
        const tier = showGroups ? tiers[rowIndex] : null;
        if (!groups.length || groups[groups.length - 1].tier !== tier)
          groups.push({ tier, indexes: [] });
        groups[groups.length - 1].indexes.push(rowIndex);
        if (knownOrder)
          rankCounts.set(row[0], (rankCounts.get(row[0]) ?? 0) + 1);
      });
      const caption = screening
        ? "Candidate shortlist · Application evidence and attribute refinement"
        : "Provisional literature shortlist · Source-based assessments";
      if (priorities.some(Boolean) || knownOrder)
        methodNotes.push(
          <section key={`screening-${index}`}>
            <h4 className="report-section-heading">
              How to read screening priorities
            </h4>
            {priorities.some(Boolean) && <ScreeningPriorityLegend />}
            {knownOrder && (
              <p
                className="report-screening-order"
                role="note"
                aria-label="Shortlist ordering"
              >
                <strong>How this is ordered:</strong> first review group, then
                mixed evidence, then reported concerns. Scores run highest to
                lowest within each group. Equal ranks are ties, so later rank
                numbers may be skipped. Rounded percentages can look equal even
                when ranks differ.
              </p>
            )}
          </section>,
        );
      return (
        <div key={index}>
          <div
            className="report-shortlist-scroll"
            tabIndex={0}
            role="region"
            aria-label={`${screening ? "Candidate shortlist" : "Provisional literature shortlist"}, scroll horizontally if needed`}
          >
            <table className="report-shortlist-table report-literature-table">
              <caption>{caption}</caption>
              <thead>
                <tr>
                  {block.headers.map((header, cellIndex) => (
                    <th key={cellIndex} scope="col">
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              {groups.map((group, groupIndex) => (
                <tbody key={groupIndex}>
                  {group.tier !== null && (
                    <tr className="report-screening-group">
                      <th colSpan={block.headers.length} scope="rowgroup">
                        <strong>{screeningGroups[group.tier].label}</strong>
                        <span>{screeningGroups[group.tier].description}</span>
                      </th>
                    </tr>
                  )}
                  {group.indexes.map((rowIndex) => {
                    const row = block.rows[rowIndex];
                    const priority = priorities[rowIndex];
                    const tied = (rankCounts.get(row[0]) ?? 0) > 1;
                    return (
                      <InlineStructureRow
                        key={rowIndex}
                        scope={structureScope}
                        target={literatureStructureTarget(
                          row[1],
                          leads,
                          references,
                        )}
                        label={row[1]
                          .replace(/\[[RS][1-9][0-9]{0,4}\]/g, "")
                          .trim()}
                        colSpan={block.headers.length}
                      >
                        {(structureAction) =>
                          row.map((cell, cellIndex) => (
                            <td key={cellIndex}>
                              {cellIndex === 0 ? (
                                <>
                                  <span
                                    className="report-literature-rank"
                                    style={
                                      priority
                                        ? { backgroundColor: priority.color }
                                        : undefined
                                    }
                                    aria-label={
                                      tied
                                        ? `Rank ${cell}, tied with ${rankCounts.get(cell)! - 1} other ${rankCounts.get(cell) === 2 ? "candidate" : "candidates"}`
                                        : undefined
                                    }
                                    title={
                                      screening
                                        ? `Review priority within the reported concern tier; tied ranks cannot be distinguished by available evidence${priority ? `. ${priority.explanation}` : ""}`
                                        : "Provisional rank based on assessed criteria; tied ranks have the same supported fit"
                                    }
                                  >
                                    {cell}
                                  </span>
                                  {tied && (
                                    <small
                                      className="report-rank-tie"
                                      aria-hidden="true"
                                    >
                                      tie
                                    </small>
                                  )}
                                </>
                              ) : cellIndex === 2 && priority ? (
                                <span
                                  className={`report-screening-priority report-screening-${priority.state}`}
                                  style={{ backgroundColor: priority.color }}
                                  title={priority.explanation}
                                  aria-label={`${priority.percentage}% · ${priority.label}. ${priority.explanation}`}
                                >
                                  <strong>{priority.percentage}%</strong>
                                  <small>{priority.label}</small>
                                </span>
                              ) : cellIndex === 4 &&
                                block.headers[4] === "Relevant properties" ? (
                                <RelevantProperties
                                  text={cell}
                                  references={references}
                                />
                              ) : (
                                <>
                                  <ReportText
                                    text={cell}
                                    references={references}
                                    chemicalTypography={
                                      screening && cellIndex === 1
                                    }
                                  />
                                  {cellIndex === 1 && (
                                    <>
                                      <ChemicalName
                                        target={literatureStructureTarget(
                                          row[1],
                                          leads,
                                          references,
                                        )}
                                        formula={cell
                                          .replace(
                                            /\[[RS][1-9][0-9]{0,4}\]/g,
                                            "",
                                          )
                                          .trim()}
                                      />
                                      {structureAction}
                                    </>
                                  )}
                                </>
                              )}
                            </td>
                          ))
                        }
                      </InlineStructureRow>
                    );
                  })}
                </tbody>
              ))}
            </table>
          </div>
          {index === firstTable && afterShortlist}
        </div>
      );
    }
    if (block.kind === "table") {
      if (table && index === tableIndex)
        methodNotes.push(
          <section key={`score-${index}`}>
            <h4 className="report-section-heading">
              How to read supported scores
            </h4>
            <SupportedScoreLegend />
          </section>,
        );
      return (
        <div key={index}>
          {table && index === tableIndex ? (
            <RankedTable
              table={table}
              view={view}
              references={references}
              onViewStructure={onViewStructure}
              structureScope={structureScope}
            />
          ) : (
            <div
              className="report-shortlist-scroll"
              tabIndex={0}
              role="region"
              aria-label={
                view === "pi"
                  ? "Summary shortlist table, scroll horizontally if needed"
                  : "Expanded shortlist table, scroll horizontally if needed"
              }
            >
              <table className="report-shortlist-table">
                <caption className="sr-only">
                  {view === "pi" ? "Summary shortlist" : "Expanded shortlist"}
                </caption>
                <thead>
                  <tr>
                    {block.headers.map((header, cellIndex) => (
                      <th key={cellIndex} scope="col">
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex}>
                          <ReportText
                            text={cell}
                            references={references}
                            chemicalTypography={false}
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {index === firstTable && afterShortlist}
        </div>
      );
    }
    return (
      <p key={index}>
        <ReportText text={block.text} references={references} />
      </p>
    );
  });
  return (
    <MaterialNamesContext.Provider value={safeMaterialNames(materialNames)}>
      <FormulaTypographyContext.Provider value={formulas}>
        <div
          className={`report-prose report-document report-document-${view} report-accent-${appearance.accent} report-font-${appearance.font_family} report-spacing-${appearance.line_spacing} report-table-${appearance.table_style}`}
          style={docStyle}
        >
          {renderedBlocks.filter(
            (_, index) => index !== detailsIndex && !detailIndexes.has(index),
          )}
          {firstTable < 0 && afterShortlist}
          {citedReferences.length > 0 && (
            <section
              className="report-reference-list"
              aria-label="Cited public references"
            >
              <h4 className="report-section-heading">Public references</h4>
              <ol>
                {citedReferences.map((reference) => (
                  <li key={reference.id}>
                    <span className="report-reference-id">
                      [{reference.id}]
                    </span>
                    <div>
                      <a
                        href={reference.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {reference.kind === "material_evidence" ? (
                          <FormulaText
                            text={reference.title}
                            formulas={formulas}
                          />
                        ) : (
                          reference.title
                        )}
                        <span className="sr-only"> (opens source)</span>{" "}
                        <span aria-hidden="true">↗</span>
                      </a>
                      <small>
                        {reference.source_name}
                        {reference.kind === "discovery_reference"
                          ? hasLiteratureEvaluation
                            ? " · Public literature; assessments cite source passages"
                            : " · Background reference; not used to score material properties"
                          : " · Material evidence"}
                      </small>
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          )}
          {(detailsIndex >= 0 ||
            detailIndexes.size > 0 ||
            methodNotes.length > 0) && (
            <details className="report-method-disclosure">
              <summary>Search and analysis details</summary>
              <div className="report-method-content">
                {methodNotes}
                {renderedBlocks.filter((_, index) => detailIndexes.has(index))}
              </div>
            </details>
          )}
        </div>
      </FormulaTypographyContext.Provider>
    </MaterialNamesContext.Provider>
  );
}

function savedCellText(row: ReportRow, column: ReportColumn): string {
  const value =
    column.kind === "rank"
      ? String(row.rank)
      : column.kind === "score"
        ? row.score.toFixed(4)
        : column.kind === "identity"
          ? row.material
          : column.kind === "property"
            ? row.properties[column.id].display
            : column.id === "leading"
              ? row.leading
              : row.caveat;
  return (value ?? "").trim().replace(/\s+/gu, " ").replaceAll("|", "/");
}

function criterionLabel(id: string, columns: ReportColumn[]): string {
  const known: Record<string, string> = {
    dielectric_total: "total dielectric scalar",
    band_gap: "band gap",
  };
  const column = columns.find(
    (column) => column.kind === "property" && column.id === id,
  );
  return known[id] ?? column?.label ?? id.replaceAll("_", " ");
}

function ScoreDetails({
  row,
  columns,
}: {
  row: ReportRow;
  columns: ReportColumn[];
}) {
  const analysis = row.score_analysis;
  return (
    <details className="report-score-details">
      <summary>Score details</summary>
      {analysis ? (
        <>
          <p>
            <strong>
              Fit on known criteria: {analysis.observed_fit.toFixed(4)}.
            </strong>{" "}
            This describes only criteria with evidence; it is a partial fit, not
            predicted material performance.
          </p>
          <p>
            <strong>
              Missing-criterion range: {row.score.toFixed(4)}–
              {analysis.possible_upper_score.toFixed(4)}.
            </strong>{" "}
            Holding observed property scores fixed, this is the range if missing
            criteria contribute from 0 to 1. It is not a confidence interval or
            a performance prediction.
          </p>
          {analysis.required_criteria.length > 0 && (
            <p>
              Required criteria:{" "}
              {analysis.required_criteria
                .map((id) => criterionLabel(id, columns))
                .join(", ")}
              . Missing required evidence:{" "}
              {analysis.missing_required_criteria
                .map((id) => criterionLabel(id, columns))
                .join(", ") || "None"}
              .
            </p>
          )}
        </>
      ) : (
        <p>
          This is the historical supported contribution recorded in this report.
          The saved score and order are unchanged. This report did not save a
          fit or required-evidence assessment; no current ranking rules have
          been applied.
        </p>
      )}
      <p>
        Coverage is the share of selected importance supported by retrieved
        evidence. Missing data does not establish poor material performance.
      </p>
    </details>
  );
}

function RankedCell({
  row,
  column,
  columns,
  view,
  references,
  onViewStructure,
  structureAction,
}: {
  row: ReportRow;
  column: ReportColumn;
  columns: ReportColumn[];
  view: ReportView;
  references: ReportReference[];
  onViewStructure?: (materialId: string) => void;
  structureAction?: ReactNode;
}) {
  const sourceFormulaDiffers = Boolean(
    row.source_formula && row.source_formula !== row.formula,
  );
  const analysis = row.score_analysis;
  const needsEvidence = analysis?.status === "needs_evidence";
  const neutral = needsEvidence || !analysis || analysis.coverage < 1;
  const coverage = (
    (analysis?.coverage ?? row.selected_weight_coverage) * 100
  ).toFixed(1);
  const status = needsEvidence
    ? `Needs ${analysis.missing_required_criteria.map((id) => criterionLabel(id, columns)).join(", ")} evidence`
    : analysis
      ? analysis.coverage < 1
        ? "Partial evidence"
        : "Selected evidence available"
      : "Historical contribution";
  const color = neutral ? undefined : { backgroundColor: row.score_color };
  if (column.kind === "rank")
    return (
      <span
        className={`report-rank-badge${neutral ? " report-score-neutral" : ""}`}
        style={color}
        title={`Rank ${row.rank}; supported score ${row.score.toFixed(4)}; ${coverage}% evidence coverage; ${status}`}
      >
        {row.rank}
      </span>
    );
  if (column.kind === "score")
    return (
      <>
        <span
          className={`report-utility${neutral ? " report-score-neutral" : ""}`}
          style={color}
          aria-label={`Supported score ${row.score.toFixed(4)}; ${coverage}% evidence coverage; ${status}; not confidence or predicted performance`}
        >
          <strong>{row.score.toFixed(4)}</strong>
          <small>Supported score</small>
        </span>
        <small className="report-score-coverage">{coverage}% coverage</small>
        {!analysis && (
          <small className="report-historical-score">
            Historical contribution
          </small>
        )}
        <ScoreDetails row={row} columns={columns} />
      </>
    );
  if (column.kind === "identity")
    return (
      <>
        <MaterialFormula formula={row.formula} />
        <span className="report-material-citations">
          <ReportText
            text={row.citation_ids.map((id) => `[${id}]`).join(" ")}
            references={references}
          />
        </span>
        <ChemicalName
          target={{ kind: "material", id: row.material_id }}
          formula={row.formula}
        />
        {needsEvidence && (
          <span className="report-evidence-status">{status}</span>
        )}
        {structureAction ??
          (view === "audit" && onViewStructure && (
            <button
              type="button"
              className="report-structure-action"
              onClick={() => onViewStructure(row.material_id)}
              aria-label={`View structure for rank ${row.rank}, ${row.formula}`}
            >
              View structure <span aria-hidden="true">↗</span>
            </button>
          ))}
        {(row.caveats.length > 0 || row.rationale || sourceFormulaDiffers) && (
          <details className="report-candidate-notes">
            <summary>Rationale & caveats</summary>
            {row.rationale && (
              <p>
                <ReportText text={row.rationale} references={references} />
              </p>
            )}
            {row.caveats.length > 0 && (
              <ul>
                {row.caveats.map((caveat, index) => (
                  <li key={index}>
                    <ReportText text={caveat} references={references} />
                  </li>
                ))}
              </ul>
            )}
            <p className="report-record-id">Source record: {row.material_id}</p>
            {sourceFormulaDiffers && (
              <p>
                Original source formula:{" "}
                <span className="report-source-formula">
                  {row.source_formula}
                </span>
              </p>
            )}
            <p>
              Selected importance coverage:{" "}
              {(row.selected_weight_coverage * 100).toFixed(1)}%. Missing
              criteria:{" "}
              {row.missing_criteria
                .map((id) => criterionLabel(id, columns))
                .join(", ") || "None among selected criteria"}
              .
            </p>
          </details>
        )}
      </>
    );
  if (column.kind === "text")
    return (
      <ReportText
        text={(column.id === "leading" ? row.leading : row.caveat) ?? ""}
        references={references}
      />
    );
  const property = row.properties[column.id];
  return (
    <>
      <span
        className={
          property.status === "available" ? "" : "report-property-unknown"
        }
      >
        <ReportText
          text={property.display}
          references={references}
          chemicalTypography={false}
        />
      </span>
      <small className="report-property-score">
        {property.status === "available"
          ? `Criterion fit ${property.utility.toFixed(2)}`
          : "Unscored"}{" "}
        · weight {(property.weight * 100).toFixed(1)}%
      </small>
    </>
  );
}

function RankedTable({
  table,
  view,
  references,
  onViewStructure,
  structureScope,
}: {
  table: ReportTable;
  view: ReportView;
  references: ReportReference[];
  onViewStructure?: (materialId: string) => void;
  structureScope?: StructureScope;
}) {
  const scroll = useRef<HTMLDivElement>(null);
  function move(direction: number) {
    const region = scroll.current;
    if (region)
      region.scrollBy({
        left: direction * Math.max(240, region.clientWidth * 0.7),
        behavior: "auto",
      });
  }
  return (
    <div className="ranked-table-block">
      {view === "audit" && (
        <div className="report-property-navigation">
          <span>Compare selected properties</span>
          <button
            type="button"
            aria-label="Show earlier ranking properties"
            onClick={() => move(-1)}
          >
            ←
          </button>
          <button
            type="button"
            aria-label="Show later ranking properties"
            onClick={() => move(1)}
          >
            →
          </button>
        </div>
      )}
      <div
        ref={scroll}
        className="report-shortlist-scroll"
        tabIndex={0}
        onKeyDown={(event) => {
          if (
            event.target === event.currentTarget &&
            ["ArrowLeft", "ArrowRight"].includes(event.key)
          ) {
            event.preventDefault();
            move(event.key === "ArrowLeft" ? -1 : 1);
          }
        }}
        role="region"
        aria-label={
          view === "pi"
            ? "Summary shortlist table, scroll horizontally if needed"
            : "Selected ranking properties table, scroll horizontally if needed"
        }
      >
        <table className="report-shortlist-table report-ranked-table">
          <caption className="sr-only">
            {view === "pi"
              ? "Summary shortlist"
              : "Technical View · selected ranking properties"}
          </caption>
          <thead>
            <tr>
              {table.columns.map((column) => (
                <th
                  key={column.id}
                  scope="col"
                  className={`report-column-${column.kind}`}
                >
                  {column.kind === "score" ? "Supported score" : column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row) => (
              <InlineStructureRow
                key={`${row.rank}-${row.material_id}`}
                scope={structureScope}
                target={{ kind: "material", id: row.material_id }}
                label={row.formula}
                colSpan={table.columns.length}
              >
                {(structureAction) =>
                  table.columns.map((column) => (
                    <td
                      key={column.id}
                      className={`report-column-${column.kind}`}
                    >
                      <RankedCell
                        row={row}
                        column={column}
                        columns={table.columns}
                        view={view}
                        references={references}
                        onViewStructure={onViewStructure}
                        structureAction={structureAction}
                      />
                    </td>
                  ))
                }
              </InlineStructureRow>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
