/** Real-browser geometry checks. Run npm run test:report-layout, then open the
 * printed loopback URL in the browser under test. This does not contact the app,
 * sign in, run research, or create workspace records. All content is synthetic.
 */
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const source = new URL("../src/", import.meta.url);
const requestedPort = process.env.LABCAT_LAYOUT_PORT ?? "0";
if (!/^\d+$/.test(requestedPort) || Number(requestedPort) > 65535)
  throw new Error("LABCAT_LAYOUT_PORT must be an integer from 0 to 65535.");
const temporary = await mkdtemp(join(tmpdir(), "labcat-layout-browser-"));
let server;
async function cleanup() {
  server?.close();
  await rm(temporary, { recursive: true, force: true });
}
for (const signal of ["SIGINT", "SIGTERM"])
  process.once(signal, () => {
    cleanup().finally(() => process.exit());
  });

try {
  for (const name of await readdir(source)) {
    if (!/\.tsx?$/.test(name)) continue;
    const input = await readFile(new URL(name, source), "utf8");
    const compiled = ts
      .transpileModule(input, {
        compilerOptions: {
          target: ts.ScriptTarget.ES2022,
          module: ts.ModuleKind.ES2022,
          jsx: ts.JsxEmit.ReactJSX,
        },
      })
      .outputText.replace(/import ['"][^'"]+\.css['"];?/g, "")
      .replace(
        /from (['"])([^'"]+)\1/g,
        (_match, _quote, specifier) =>
          `from '${specifier.startsWith(".") ? `${specifier}.js` : import.meta.resolve(specifier)}'`,
      );
    await writeFile(join(temporary, name.replace(/\.tsx?$/, ".js")), compiled);
  }
  await writeFile(join(temporary, "package.json"), '{"type":"module"}');
  const { default: ReportContent } = await import(
    pathToFileURL(join(temporary, "ReportContent.js"))
  );
  const { candidateLeadCells } = await import(
    pathToFileURL(join(temporary, "CandidateLeadTable.js"))
  );
  const { defaultReportLayout } = await import(
    pathToFileURL(join(temporary, "workspaceApi.js"))
  );
  const saved = JSON.parse(
    await readFile(
      new URL("./fixtures/candidate-lead-report.json", import.meta.url),
      "utf8",
    ),
  );
  const leads = structuredClone(saved.leads).slice(0, 3);
  const references = structuredClone(saved.references);
  for (const lead of leads) {
    lead.title =
      "TEST ONLY layout fixture: an intentionally long publication title for reproducing narrow source columns and retaining complete readable text";
    lead.quote = `TEST ONLY: ${lead.name} is a synthetic name in a deliberately lengthy quotation used to test prose wrapping. This fixture contains no scientific evidence, material measurement or recommendation.`;
    lead.missing_criteria = [
      "stability",
      "ambient_phase_stability",
      "operational_stability",
      "band_gap",
      "dielectric_total",
      "evidence_quality",
    ];
    lead.citations[0].title = lead.title;
    lead.citations[0].quote = lead.quote;
  }
  const markdown = (headers, rows) =>
    `Summary:\n\nSynthetic layout fixture only.\n\n| ${headers.join(" | ")} |\n| ${headers.map(() => "---").join(" | ")} |\n${rows.map((row) => `| ${row.join(" | ")} |`).join("\n")}`;
  const leadHeaders = [
    "Review order",
    "Candidate",
    "Source",
    "Supporting quote",
    "Missing measurements",
  ];
  const leadContent = markdown(
    leadHeaders,
    candidateLeadCells(leads, "pi", references),
  );
  const wideText =
    "TEST ONLY: A long synthetic explanation remains fully available even when the table needs horizontal scrolling. No measurements or conclusions are asserted.";
  const row = {
    rank: 1,
    material_id: "layout-fixture",
    formula: "Fixture",
    material: "Synthetic record [R1]",
    score: 0.25,
    score_color: "#edf0f2",
    score_band: "low",
    selected_weight_coverage: 0.5,
    citation_ids: [],
    rationale: wideText,
    caveats: [wideText],
    missing_criteria: ["field_b"],
    leading: wideText,
    caveat: wideText,
    properties: {
      field_a: {
        value: null,
        unit: "",
        status: "unknown",
        display: wideText,
        utility: 0,
        contribution: 0,
        weight: 0.5,
        citation_ids: [],
      },
      field_b: {
        value: null,
        unit: "",
        status: "unknown",
        display: "Unknown test field",
        utility: 0,
        contribution: 0,
        weight: 0.5,
        citation_ids: [],
      },
    },
  };
  const rankedColumns = [
    { id: "rank", label: "Rank", kind: "rank" },
    { id: "material", label: "Material", kind: "identity" },
    { id: "score", label: "Score", kind: "score" },
  ];
  const summaryTable = {
    columns: [
      ...rankedColumns,
      { id: "leading", label: "Leading criteria", kind: "text" },
      { id: "caveat", label: "Key caveat", kind: "text" },
    ],
    rows: [row],
  };
  const technicalTable = {
    columns: [
      ...rankedColumns,
      { id: "field_a", label: "Synthetic criterion", kind: "property" },
      { id: "field_b", label: "Missing synthetic criterion", kind: "property" },
    ],
    rows: [row],
  };
  const rankedContent = (table) =>
    markdown(
      table.columns.map(({ label }) => label),
      table.rows.map((item) =>
        table.columns.map(({ id, kind }) =>
          kind === "rank"
            ? String(item.rank)
            : kind === "identity"
              ? item.material
              : kind === "score"
                ? item.score.toFixed(4)
                : kind === "property"
                  ? item.properties[id].display
                  : item[id],
        ),
      ),
    );
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
  const fixtures = [
    {
      name: "historical-no-metadata",
      content: leadContent,
      selector: ".report-shortlist-table",
      excluded: ".report-lead-table",
      proseColumns: [1, 2, 3, 4],
    },
    {
      name: "historical-mismatched-metadata",
      content: leadContent.replace("Fixture-A", "Altered synthetic name"),
      options: { candidateLeads: leads, references },
      selector: ".report-shortlist-table",
      excluded: ".report-lead-table",
      proseColumns: [1, 2, 3, 4],
    },
    {
      name: "enhanced-candidate-leads",
      content: leadContent,
      options: { candidateLeads: leads, references },
      selector: ".report-lead-table",
      proseColumns: [1, 2, 3, 4],
    },
    {
      name: "provisional-literature",
      content: markdown(literatureHeaders, [
        [
          "1",
          "Synthetic candidate",
          "50% supported fit; 50%–100% bound",
          wideText,
          "50% assessed; 3 unknown criteria",
          wideText,
        ],
      ]),
      selector: ".report-literature-table",
      proseColumns: [1, 2, 3, 4, 5],
    },
    {
      name: "preliminary-v2-candidate-shortlist",
      content: markdown(screeningHeaders, [
        [
          "1",
          "Synthetic application candidate",
          "78% · Assessed review priority",
          `Application relevance: supports; demonstrated use: mixed. ${wideText}`,
          `25% attribute coverage; 100% observed attribute fit. ${wideText}`,
          `Room-temperature phase stability is unknown. ${wideText}`,
        ],
        [
          "2",
          "Synthetic unknown-only candidate",
          "22% · Unassessed review prior",
          `Application relevance: unknown; demonstrated use: unknown. ${wideText}`,
          "No selected attribute assessments; the fixed unknown review prior is shown explicitly.",
          `No source-bound stability assessment is available. ${wideText}`,
        ],
        [
          "3",
          "Synthetic mixed-evidence candidate",
          "95% · Mixed evidence",
          `Application relevance: mixed. ${wideText}`,
          "Selected attributes do not erase mixed application evidence.",
          `A retained mixed stability assessment takes precedence over the numeric priority. ${wideText}`,
        ],
        [
          "4",
          "Synthetic adverse candidate",
          "90% · Concern reported",
          `Application relevance: concern; contradictory passages remain visible. ${wideText}`,
          "All selected criteria assessed; concerns still control review order.",
          `A retained operational-stability concern takes precedence over the numeric priority. ${wideText}`,
        ],
      ]),
      selector: ".report-literature-table",
      proseColumns: [1, 2, 3, 4, 5],
    },
    {
      name: "ranked-summary",
      content: rankedContent(summaryTable),
      options: { table: summaryTable },
      selector: ".report-ranked-table",
      proseColumns: [1, 3, 4],
    },
    {
      name: "ranked-technical",
      content: rankedContent(technicalTable),
      view: "audit",
      options: { table: technicalTable },
      selector: ".report-ranked-table",
      proseColumns: [1, 3, 4],
    },
    {
      name: "generic-two-columns",
      content: markdown(
        ["Synthetic explanation", "Additional context"],
        [[wideText, wideText]],
      ),
      selector: ".report-shortlist-table",
      proseColumns: [0, 1],
    },
    {
      name: "generic-twelve-columns",
      content: markdown(
        Array.from({ length: 12 }, (_, i) => `Synthetic column ${i + 1}`),
        [Array.from({ length: 12 }, () => wideText)],
      ),
      selector: ".report-shortlist-table",
      proseColumns: Array.from({ length: 12 }, (_, i) => i),
    },
  ].map(({ content, options, view, ...fixture }) => ({
    ...fixture,
    html: renderToStaticMarkup(
      createElement(ReportContent, {
        content,
        view: view ?? "pi",
        ...options,
        presentation: { layout: defaultReportLayout },
      }),
    ),
  }));
  const script = await readFile(
    new URL("./reportLayoutChecks.js", import.meta.url),
    "utf8",
  );
  const data = JSON.stringify(fixtures).replaceAll("<", "\\u003c");
  const page = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Report table layout checks</title><style>body{font:15px/1.5 system-ui,sans-serif;margin:24px;color:#254c3c}h1{font-size:24px}button,select{font:inherit;padding:7px 12px;margin-right:8px}#status{padding:12px;background:#eef4ed;border-radius:8px}#results{white-space:pre-wrap;font:13px/1.5 monospace}#test-frame{position:absolute;left:-20000px;top:0;border:0;height:900px}#preview-frame{display:block;max-width:100%;height:700px;border:1px solid #b5c8b5;margin-top:16px}details{margin:18px 0}</style><h1>Report table layout checks</h1><p>Synthetic fixtures only. These checks use this browser's actual layout engine and the application's current CSS. They do not access the application or run research.</p><p id="status" role="status">Preparing layout checks…</p><button id="rerun">Run again</button><details><summary>Inspect a case</summary><select id="case-picker"></select><iframe id="preview-frame" title="Selected synthetic table fixture"></iframe></details><pre id="results"></pre><iframe id="test-frame" title="Synthetic geometry test frame"></iframe><script type="application/json" id="fixtures">${data}</script><script>${script}</script></html>`;
  let lastResults = null;
  server = createServer(async (request, response) => {
    response.setHeader("Cache-Control", "no-store");
    const pathname = new URL(request.url, "http://127.0.0.1").pathname;
    if (request.method === "GET" && pathname === "/") {
      response.setHeader("Content-Type", "text/html; charset=utf-8");
      response.end(page);
      return;
    }
    if (request.method === "GET" && pathname === "/results") {
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify(lastResults));
      return;
    }
    const cssNames = ["styles.css", "workspace.css", "reportContent.css"];
    if (request.method === "GET" && cssNames.includes(pathname.slice(1))) {
      response.setHeader("Content-Type", "text/css");
      response.end(await readFile(new URL(pathname.slice(1), source)));
      return;
    }
    if (
      request.method === "POST" &&
      pathname === "/results" &&
      request.headers.origin === `http://${request.headers.host}`
    ) {
      let text = "";
      for await (const chunk of request) {
        text += chunk;
        if (text.length > 1000000) {
          response.writeHead(413).end();
          return;
        }
      }
      try {
        lastResults = JSON.parse(text);
      } catch {
        response.writeHead(400).end();
        return;
      }
      console.log(
        JSON.stringify({
          browser: lastResults.userAgent,
          passed: lastResults.passed,
          cases: lastResults.cases?.length,
          failures: lastResults.cases
            ?.filter((item) => !item.passed)
            .map(({ name, errors }) => ({ name, errors })),
        }),
      );
      response.writeHead(204).end();
      return;
    }
    response.writeHead(404).end();
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(Number(requestedPort), "127.0.0.1", resolve);
  });
  console.log(
    `Report layout checks: http://127.0.0.1:${server.address().port}/`,
  );
  console.log(
    `Open the URL in WebKit or Chrome; each browser automatically checks all ${fixtures.length} fixtures across the configured widths, fonts and table styles. GET /results returns the latest result. Press Ctrl+C when finished.`,
  );
} catch (error) {
  await cleanup();
  throw error;
}
