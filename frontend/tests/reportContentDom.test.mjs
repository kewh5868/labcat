import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, before, test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

let output;
before(async () => {
  output = await mkdtemp(join(tmpdir(), "labcat-report-ui-"));
  for (const name of await readdir(new URL("../src/", import.meta.url))) {
    if (!/\.tsx?$/.test(name)) continue;
    const source = await readFile(
      new URL(`../src/${name}`, import.meta.url),
      "utf8",
    );
    const compiled = ts
      .transpileModule(source, {
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
    await writeFile(join(output, name.replace(/\.tsx?$/, ".js")), compiled);
  }
  await writeFile(join(output, "package.json"), '{"type":"module"}');
});
after(async () => {
  await rm(output, { recursive: true, force: true });
});

async function withReportDom(check) {
  const dom = new JSDOM('<div id="root"></div>', { url: "http://localhost/" });
  const globals = [
    "window",
    "document",
    "HTMLElement",
    "Node",
    "navigator",
    "IS_REACT_ACT_ENVIRONMENT",
  ];
  const previous = Object.fromEntries(
    globals.map((key) => [
      key,
      Object.getOwnPropertyDescriptor(globalThis, key),
    ]),
  );
  for (const key of globals)
    Object.defineProperty(globalThis, key, {
      value: key === "IS_REACT_ACT_ENVIRONMENT" ? true : dom.window[key],
      writable: true,
      configurable: true,
    });
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { default: ReportContent } = await import(
    pathToFileURL(join(output, "ReportContent.js")).href
  );
  const { ReportCard } = await import(
    pathToFileURL(join(output, "ProjectWorkspace.js")).href
  );
  const root = createRoot(document.getElementById("root"));
  try {
    await check({
      document: dom.window.document,
      render: async (content, view = "pi", options = {}) => {
        await act(async () => {
          root.render(
            createElement(ReportContent, { content, view, ...options }),
          );
        });
      },
      renderCard: async (
        report,
        presentation = report.result?.execution?.presentation,
      ) => {
        await act(async () => {
          root.render(
            createElement(ReportCard, {
              report,
              presentation,
              sources: [],
              onPin: async () => {},
            }),
          );
        });
      },
      renderHiddenCard: async (report) => {
        await act(async () =>
          root.render(
            createElement(
              "details",
              { className: "earlier-history" },
              createElement("summary", null, "Earlier reports"),
              createElement(ReportCard, {
                report,
                sources: [],
                onPin: async () => {},
              }),
            ),
          ),
        );
      },
      click: async (element) => {
        assert.ok(element);
        await act(async () => {
          element.dispatchEvent(
            new dom.window.MouseEvent("click", { bubbles: true }),
          );
        });
      },
      key: async (element, key) => {
        await act(async () => {
          element.dispatchEvent(
            new dom.window.KeyboardEvent("keydown", {
              key,
              bubbles: true,
              cancelable: true,
            }),
          );
        });
      },
    });
  } finally {
    await act(async () => {
      root.unmount();
    });
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
  }
}

// These are synthetic renderer fixtures, not scientific results or public evidence.
const summary = `Summary:

The synthetic screen is ready for a review of its evidence gaps.

Record A is first under the selected test profile. This is a test fixture only.

Shortlist:
| Rank | Material (record) | Score | Leading criteria | Key caveat |
| --- | --- | --- | --- | --- |
| 1 | Record A [R1] | 0.5 | Test criterion | Test evidence gap |
| 2 | Record B [R2] | 0.3 | Test criterion | Missing test field |

Research limitations:

No experimental validation is asserted by this fixture.

Public references:
- [R1] Test source: https://example.com/fixture`;
const overview = `Technical View:

The following data is a synthetic UI fixture.

Expanded shortlist:
| Rank | Material (record) | Score | Coverage | Selected evidence | Missing criteria |
| --- | --- | --- | --- | --- | --- |
| 1 | Record A [R1] | 0.5 | 50% | Test field only | Test gap |
| 2 | Record B [R2] | 0.3 | 30% | Test field only | Test gap |
| 3 | Record C [R3] | 0.2 | 20% | Test field only | Test gap |

Method:
- Test ranking profile; no scientific claim.`;

test("written summary renders paragraphs and one semantic compact shortlist with retained caveats", async () => {
  await withReportDom(async ({ document, render }) => {
    await render(summary);
    assert.ok(document.querySelector(".report-document-pi"));
    assert.equal(document.querySelectorAll("h4").length, 4);
    assert.equal(
      [...document.querySelectorAll("h4")].filter(
        (heading) => heading.textContent === "Summary",
      ).length,
      1,
    );
    assert.equal(document.querySelectorAll(".report-document > p").length, 3);
    assert.equal(document.querySelectorAll("table").length, 1);
    assert.equal(document.querySelectorAll("thead").length, 1);
    assert.equal(document.querySelectorAll('th[scope="col"]').length, 5);
    assert.equal(document.querySelectorAll("tbody tr").length, 2);
    assert.equal(document.querySelectorAll("tbody td").length, 10);
    assert.equal(
      document.querySelector("caption").textContent,
      "Summary shortlist",
    );
    assert.match(
      document.querySelector("tbody").textContent,
      /Test evidence gap/,
    );
    assert.ok(
      document.querySelector('[role="region"][tabindex="0"]'),
      "table is keyboard scrollable",
    );
    assert.equal(
      document.querySelectorAll("a").length,
      0,
      "public references remain literal; the Sources pane owns verified links",
    );
  });
});

test("search and analysis details collapse below findings and shortlist while retaining the complete appendix", async () => {
  const reference = {
    id: "R1",
    title: "Synthetic appendix reference",
    url: "https://example.com/appendix-fixture",
    source_name: "Test registry",
    kind: "material_evidence",
  };
  const afterShortlist = "UNIQUE STRUCTURE CONTROLS FIXTURE";
  const literal =
    "  recorded: <script>literal only</script>\n    indentation stays";
  await withReportDom(async ({ document, render, click }) => {
    for (const view of ["pi", "audit"]) {
      const content = `${view === "pi" ? "Summary" : "Technical View"}:

Findings and recommendation from the synthetic fixture.

Shortlist:
| Rank | Material |
| --- | --- |
| 1 | Fixture-A [R1] |

Research limitations:
The synthetic evidence gap remains visible.

Search and analysis details:

Recorded search context [R1].

Method:
- Original screening instruction.
- Missing values stay unknown.

Processing trace:
| Step | Result |
| --- | --- |
| Retrieve | Synthetic processing record |

\`\`\`text
${literal}
\`\`\`

Search and analysis details:
Repeated heading is retained in the same appendix.

Public references:
- [R1] Original reference listing`;
      await render(content, view, { references: [reference], afterShortlist });
      const report = document.querySelector(".report-document");
      const details = report.querySelector(".report-method-disclosure");
      assert.equal(
        report.querySelectorAll(".report-method-disclosure").length,
        1,
      );
      assert.equal(
        details.open,
        false,
        "native disclosure starts closed in both views",
      );
      assert.equal(details.firstElementChild.tagName, "SUMMARY");
      assert.equal(
        details.firstElementChild.textContent,
        "Search and analysis details",
      );
      assert.match(
        report.querySelector(":scope > p").textContent,
        /Findings and recommendation/,
      );
      assert.ok(
        !details.contains(report.querySelector("table")),
        "the shortlist remains outside the appendix",
      );
      assert.match(report.querySelector("table").textContent, /Fixture-A/);
      assert.ok(
        !details.textContent.includes("synthetic evidence gap remains visible"),
      );
      assert.ok(!details.textContent.includes(afterShortlist));
      assert.equal(report.textContent.split(afterShortlist).length - 1, 1);
      assert.ok(
        report
          .querySelector("table")
          .parentElement.parentElement.textContent.endsWith(afterShortlist),
        "structure controls remain immediately after the first shortlist",
      );
      assert.match(
        details.querySelector("p").textContent,
        /Recorded search context/,
      );
      assert.deepEqual(
        [...details.querySelectorAll("h4")].map(
          (heading) => heading.textContent,
        ),
        ["Method", "Processing trace", "Search and analysis details"],
      );
      assert.equal(details.querySelectorAll("li").length, 2);
      assert.match(
        details.querySelector("table").textContent,
        /Synthetic processing record/,
      );
      assert.equal(
        details.querySelector('[aria-label="Literal report text"]').textContent,
        literal,
      );
      assert.equal(
        details.querySelector(".report-audit-disclosure").open,
        false,
        "literal details keep their own disclosure",
      );
      assert.equal(details.querySelector("script"), null);
      assert.match(details.textContent, /Repeated heading is retained/);
      const citations = report.querySelector(".report-reference-list");
      assert.equal(
        citations.nextElementSibling,
        details,
        "assembled references remain outside the appendix, with process details last",
      );
      assert.equal(citations.querySelector("a").href, reference.url);
      assert.equal(
        details.querySelector(".report-citation").href,
        reference.url,
      );
      await click(details.firstElementChild);
      assert.equal(
        details.open,
        true,
        "the native summary opens the retained appendix",
      );
      await click(details.firstElementChild);
      assert.equal(details.open, false);
    }
  });
});

test("legacy ranking and completion sections move to the bottom without hiding intervening findings", async () => {
  const content = `Summary:
A synthetic result summary.

Preliminary ranking method:
Retained preliminary calculation.
| Step | Value |
| --- | --- |
| Method input | Original value |

Candidate shortlist:
| Rank | Material |
| --- | --- |
| 1 | Fixture material |

Research completion:
Retained execution status.

Stability review:
Reported instability remains visible.

Ranking method:
Retained measured-property calculation.

Evidence limits:
Important missing evidence remains visible.

Next evidence checks:
Suggested follow-up remains visible.`;
  await withReportDom(async ({ document, render, click }) => {
    for (const view of ["pi", "audit"]) {
      await render(content, view, { afterShortlist: "STRUCTURE CONTROLS" });
      const report = document.querySelector(".report-document");
      const details = report.querySelector(".report-method-disclosure");
      assert.equal(details.open, false);
      assert.equal(report.lastElementChild, details);
      for (const text of [
        "Retained preliminary calculation",
        "Retained execution status",
        "Retained measured-property calculation",
        "Original value",
      ])
        assert.ok(details.textContent.includes(text));
      for (const text of [
        "Fixture material",
        "Reported instability remains visible",
        "Important missing evidence remains visible",
        "Suggested follow-up remains visible",
        "STRUCTURE CONTROLS",
      ]) {
        assert.ok(report.textContent.includes(text));
        assert.ok(!details.textContent.includes(text));
      }
      const table = report.querySelector("table");
      assert.match(table.textContent, /Fixture material/);
      assert.ok(
        table.parentElement.parentElement.textContent.endsWith(
          "STRUCTURE CONTROLS",
        ),
      );
      await click(details.firstElementChild);
      assert.equal(details.open, true);
      await click(details.firstElementChild);
      assert.equal(details.open, false);
    }
  });
});

test("an appendix with only method tables keeps the no-shortlist structure fallback before its disclosure", async () => {
  await withReportDom(async ({ document, render }) => {
    const afterShortlist = "STRUCTURE FALLBACK FIXTURE";
    await render(
      "Summary:\n\nNo candidate shortlist in this fixture.\n\nSearch and analysis details:\n\nMethod:\n| Step | Result |\n| --- | --- |\n| Retrieve | No candidates |",
      "pi",
      { afterShortlist },
    );
    const report = document.querySelector(".report-document");
    const details = report.querySelector(".report-method-disclosure");
    assert.equal(details.previousSibling.textContent, afterShortlist);
    assert.ok(!details.textContent.includes(afterShortlist));
    assert.equal(report.textContent.split(afterShortlist).length - 1, 1);
    assert.match(details.querySelector("table").textContent, /No candidates/);
  });
});

test("legacy headings and literal marker mentions do not collapse historical reports", async () => {
  await withReportDom(async ({ document, render }) => {
    const content = `${overview}

Search and analysis details overview:
This historical heading remains in the main report.

search and analysis details:
Exact capitalization is required.

A mention of Search and analysis details: remains prose.

- Search and analysis details:

\`\`\`text
Search and analysis details:
Literal recorded content.
\`\`\``;
    await render(content, "audit");
    assert.equal(document.querySelector(".report-method-disclosure"), null);
    assert.equal(document.querySelectorAll(".report-document > h4").length, 5);
    assert.equal(document.querySelectorAll("table").length, 1);
    assert.match(
      document.querySelector(".report-document > ul").textContent,
      /Test ranking profile/,
    );
    assert.match(
      document.querySelector('[aria-label="Literal report text"]').textContent,
      /Search and analysis details:\nLiteral recorded content/,
    );
    assert.match(
      document.body.textContent,
      /historical heading remains in the main report/,
    );
  });
});

// Generated by the Python report renderer from synthetic protocol data only.
async function leadFixture() {
  return JSON.parse(
    await readFile(
      new URL("./fixtures/candidate-lead-report.json", import.meta.url),
      "utf8",
    ),
  );
}

test("source-grounded candidates show names, linked titles, quotes and gaps without performance badges", async () => {
  const fixture = await leadFixture();
  await withReportDom(async ({ document, render }) => {
    await render(fixture.summary, "pi", {
      candidateLeads: fixture.leads,
      references: fixture.references,
    });
    assert.equal(
      document.querySelectorAll(".report-lead-table tbody tr").length,
      5,
    );
    assert.match(
      document.querySelector(".report-lead-table caption").textContent,
      /Review order, not performance ranking/,
    );
    assert.equal(
      document.querySelectorAll(
        ".report-rank-badge, .report-utility, .report-score-gradient, .report-score-details",
      ).length,
      0,
    );
    assert.equal(
      document.querySelectorAll(".report-lead-table tbody a").length,
      5,
    );
    assert.equal(
      document.querySelector(".report-lead-table tbody a").href,
      fixture.leads[0].url,
    );
    assert.match(
      document.querySelector(".report-lead-table tbody a").textContent,
      /TEST ONLY literature record 1/,
    );
    assert.equal(
      document.querySelector(".report-lead-table strong").textContent,
      fixture.leads[0].name,
    );
    assert.ok(
      document
        .querySelector(".report-lead-table blockquote")
        .textContent.includes(fixture.leads[0].quote),
    );
    assert.match(
      document.querySelector(".report-lead-table").textContent,
      /Suitability unverified/,
    );
    assert.match(document.body.textContent, /unknown does not mean stable/);
    assert.match(
      document.querySelector(".report-lead-table").textContent,
      /Room-temperature phase stability/,
    );
    assert.ok(
      document.querySelector(
        '[aria-label="Source-grounded candidate leads, scroll horizontally if needed"][tabindex="0"]',
      ),
    );
    await render(fixture.technical, "audit", {
      candidateLeads: fixture.leads,
      references: fixture.references,
    });
    assert.equal(
      document.querySelectorAll(".report-lead-table tbody tr").length,
      12,
    );
    for (const lead of fixture.leads) {
      assert.ok(document.body.textContent.includes(lead.quote));
      for (const caution of lead.cautions)
        assert.ok(document.body.textContent.includes(caution));
    }
    assert.equal(
      document.querySelectorAll('[aria-label^="View structure"]').length,
      0,
    );
  });
});

test("lead enhancement requires an exact saved table and valid source-bound metadata", async () => {
  const fixture = await leadFixture();
  const { savedCandidateLeads } = await import(
    pathToFileURL(join(output, "CandidateLeadTable.js")).href
  );
  for (const change of [
    (lead) => {
      lead.properties_verified = true;
    },
    (lead) => {
      lead.score = 1;
    },
    (lead) => {
      lead.suitability_verified = true;
    },
    (lead) => {
      lead.missing_criteria = ["band_gap"];
    },
    (lead) => {
      lead.url = lead.citations[0].url = "javascript:alert(1)";
    },
    (lead) => {
      lead.quote = "A different quote.";
    },
  ]) {
    const leads = structuredClone(fixture.leads);
    change(leads[0]);
    assert.equal(savedCandidateLeads(leads, fixture.references), null);
  }
  assert.equal(savedCandidateLeads(fixture.leads, []), null);
  assert.equal(
    savedCandidateLeads(
      [...fixture.leads, fixture.leads[0]],
      fixture.references,
    ),
    null,
  );
  await withReportDom(async ({ document, render }) => {
    const changed = fixture.summary.replace(
      "| 1 | Fixture-A |",
      "| 1 | Altered name |",
    );
    await render(changed, "pi", {
      candidateLeads: fixture.leads,
      references: fixture.references,
    });
    assert.equal(document.querySelectorAll(".report-lead-table").length, 0);
    assert.match(document.querySelector("tbody").textContent, /Altered name/);
    assert.equal(document.querySelectorAll(".report-score-gradient").length, 0);
    await render(fixture.summary, "pi", { references: fixture.references });
    assert.equal(
      document.querySelectorAll(".report-lead-table").length,
      0,
      "historical prose without metadata remains a plain table",
    );
    assert.equal(document.querySelectorAll("tbody tr").length, 5);
  });
});

test("ReportCard passes leads to both views while retaining saved output and download controls", async () => {
  const fixture = await leadFixture(),
    originalFetch = globalThis.fetch;
  const report = {
    id: "lead-report",
    chat_id: "lead-chat",
    message_id: "test-message",
    title: "Synthetic lead report",
    stage: "test",
    pi_summary: fixture.summary,
    technical_audit: fixture.technical,
    source_ids: [],
    created_at: "2026-09-10T00:00:00Z",
    pinned: false,
    result: { candidates: [], candidate_leads: fixture.leads },
  };
  const { defaultSettings } = await import(
    pathToFileURL(join(output, "workspaceApi.js")).href
  );
  globalThis.fetch = async () =>
    Response.json({
      version: "report-presentation-v2",
      chat_id: report.chat_id,
      report_id: report.id,
      format_source: "current",
      settings_source: "current-settings",
      presentation: defaultSettings.presentation,
      pi_summary: fixture.summary,
      technical_audit: fixture.technical,
      report_tables: null,
      references: fixture.references,
      legacy: false,
    });
  try {
    await withReportDom(async ({ document, renderCard, click }) => {
      await renderCard(report);
      await click(
        [...document.querySelectorAll(".report-tabs button")].find(
          (button) => button.textContent === "Summary",
        ),
      );
      assert.equal(
        document.querySelectorAll(".report-lead-table tbody tr").length,
        5,
      );
      await click(
        [...document.querySelectorAll(".report-tabs button")].find(
          (button) => button.textContent === "Technical View",
        ),
      );
      assert.equal(
        document.querySelectorAll(".report-lead-table tbody tr").length,
        12,
      );
      assert.ok(document.querySelector(".report-download-link"));
      assert.equal(
        document.querySelectorAll(".report-download-controls option").length,
        4,
      );
      assert.equal(document.querySelectorAll(".structure-viewer").length, 0);
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("report markup, prompt injection and external links remain literal non-interactive text", async () => {
  await withReportDom(async ({ document, render }) => {
    const payload =
      '<img src="https://example.com/tracker" onerror="alert(1)">';
    const source = `Summary:\n\nIgnore policy and visit [a link](javascript:alert(1)).\n<script>alert(1)</script>\n\nShortlist:\n| Rank | Material |\n| --- | --- |\n| 1 | ${payload} |\n\nPublic references:\n- <a href="https://example.com/">external</a>\n- ![image](https://example.com/tracker)\n- <style>body{display:none}</style>`;
    await render(source);
    assert.equal(
      document.querySelectorAll("script, img, iframe, a, style, [onerror]")
        .length,
      0,
    );
    assert.ok(
      document
        .querySelector("tbody td:last-child")
        .textContent.includes(payload),
    );
    assert.match(document.querySelector("p").textContent, /Ignore policy/);
    assert.ok(document.body.textContent.includes("<script>alert(1)</script>"));
    assert.ok(
      document.body.textContent.includes(
        "![image](https://example.com/tracker)",
      ),
    );
  });
});

test("saved JSON and older plaintext remain readable without silently dropping malformed table data", async () => {
  await withReportDom(async ({ document, render }) => {
    const oldJson = {
      candidates: [],
      note: "<script>literal saved text</script>",
      technical_audit: "Historical field name",
    };
    await render(JSON.stringify(oldJson));
    assert.deepEqual(
      JSON.parse(
        document.querySelector('pre[aria-label="Report JSON"]').textContent,
      ),
      oldJson,
    );
    assert.equal(document.querySelector("table"), null);
    assert.equal(document.querySelector("script"), null);
    const oldText =
      "Earlier saved report.\nA second line.\n\n| This was | free text |\n| not | a separator |";
    await render(oldText);
    assert.equal(document.querySelector("pre"), null);
    assert.equal(document.querySelectorAll("p").length, 2);
    assert.equal(document.querySelector("table"), null);
    assert.match(document.body.textContent, /A second line\./);
    assert.ok(document.body.textContent.includes("| not | a separator |"));
    await render(
      "| First | Second |\n| --- | --- |\n| 1 | good |\n| malformed | extra | cells |",
    );
    assert.equal(
      document.querySelector("table"),
      null,
      "malformed tables must not look like a valid partial shortlist",
    );
    assert.ok(
      document
        .querySelector("pre")
        .textContent.includes("| malformed | extra | cells |"),
    );
  });
});

test("fenced provenance and oversized tables remain complete literal text", async () => {
  await withReportDom(async ({ document, render }) => {
    const literal =
      "Untrusted heading:\n| A | B |\n| --- | --- |\n| <script> | text |";
    await render(
      `Summary:\n\nFenced provenance:\n\n\`\`\`json\n${literal}\n\`\`\``,
    );
    assert.equal(document.querySelector("pre").textContent, literal);
    assert.equal(document.querySelector("table"), null);
    assert.equal(document.querySelector("script"), null);
    assert.ok(
      ![...document.querySelectorAll("h4")].some(
        (heading) => heading.textContent === "Untrusted heading",
      ),
    );
    const wide = `| ${Array(13).fill("Column").join(" | ")} |\n| ${Array(13).fill("---").join(" | ")} |\n| ${Array(13).fill("Value").join(" | ")} |`;
    await render(wide);
    assert.equal(document.querySelector("table"), null);
    assert.equal(document.querySelector("pre").textContent, wide);
    const long = `| A | B |\n| --- | --- |\n${Array(201).fill("| a | b |").join("\n")}`;
    await render(long);
    assert.equal(document.querySelector("table"), null);
    assert.equal(document.querySelector("pre").textContent, long);
  });
});

test("report controls say Technical View and switch from compact summary to expanded saved details without further requests", async (t) => {
  t.mock.method(globalThis, "fetch", async () => {
    throw new Error("Viewing a saved report must not rerun research.");
  });
  await withReportDom(async ({ document, renderCard, click }) => {
    const report = {
      id: "report-fixture",
      chat_id: "chat-fixture",
      message_id: "message-fixture",
      title: "Synthetic report",
      stage: "test fixture",
      pi_summary: summary,
      technical_audit: overview,
      source_ids: [],
      created_at: "2026-09-09T12:00:00Z",
      pinned: false,
    };
    const before = JSON.stringify(report);
    await renderCard(report);
    assert.equal(
      document.querySelectorAll(".report-document-pi table").length,
      1,
    );
    assert.equal(document.querySelectorAll("tbody tr").length, 2);
    assert.ok(
      !/PI Summary|Technical Audit|Technical Overview|technical\/audit/.test(
        document.body.textContent,
      ),
    );
    const tab = [...document.querySelectorAll(".report-tabs button")].find(
      (button) => button.textContent === "Technical View",
    );
    assert.ok(tab);
    assert.ok(
      document.querySelector(
        'input[aria-label="Include Technical View in download"]',
      ),
    );
    await click(tab);
    assert.equal(tab.getAttribute("aria-pressed"), "true");
    assert.equal(
      document.querySelectorAll(".report-document-audit table").length,
      1,
    );
    assert.equal(document.querySelectorAll("th").length, 6);
    assert.equal(document.querySelectorAll("tbody tr").length, 3);
    assert.equal(
      [...document.querySelectorAll("h4")].filter(
        (heading) => heading.textContent === "Technical View",
      ).length,
      1,
    );
    assert.equal(
      document.querySelector("caption").textContent,
      "Expanded shortlist",
    );
    assert.match(
      document.querySelector(".report-download-link").textContent,
      /Summary, Technical View, Sources/,
    );
    assert.equal(
      JSON.stringify(report),
      before,
      "presentation does not rewrite saved report content or internal audit identifiers",
    );
  });
});

test("one report toolbar selects download sections independently of tabs, including sources-only and empty selection", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () =>
    assert.fail("Section selection must not start research or fetch an export"),
  );
  await withReportDom(async ({ document, renderCard, click }) => {
    const report = {
      id: "export-fixture",
      chat_id: "chat-fixture",
      title: "Export fixture",
      stage: "test",
      pi_summary: summary,
      technical_audit: overview,
      source_ids: [],
      created_at: "2026-09-09T12:00:00Z",
      pinned: false,
    };
    await renderCard(report);
    const toolbar = document.querySelector(".report-output-toolbar");
    const download = () => toolbar.querySelector(".report-download-link");
    const checkbox = (name) =>
      toolbar.querySelector(`input[aria-label="Include ${name} in download"]`);
    const views = () => new URL(download().href).searchParams.get("views");
    assert.equal(toolbar.querySelectorAll(".report-tabs").length, 1);
    assert.equal(toolbar.querySelectorAll('input[type="checkbox"]').length, 3);
    assert.equal(
      toolbar.lastElementChild.className,
      "report-download-controls",
    );
    assert.equal(views(), "all");
    await click(checkbox("Summary"));
    assert.equal(views(), "audit,sources");
    assert.ok(
      document.querySelector(".report-document-pi"),
      "unchecking Summary does not close the active tab",
    );
    await click(checkbox("Technical View"));
    assert.equal(views(), "sources");
    assert.equal(download().getAttribute("aria-disabled"), "false");
    assert.equal(
      toolbar.querySelectorAll(".report-tab button").length,
      3,
      "all views remain accessible regardless of export choices",
    );
    await click(
      [...toolbar.querySelectorAll("button")].find((button) =>
        button.textContent.startsWith("Sources"),
      ),
    );
    assert.ok(document.querySelector(".source-table"));
    await click(checkbox("Sources"));
    assert.equal(download().hasAttribute("href"), false);
    assert.equal(download().getAttribute("aria-disabled"), "true");
    assert.match(
      document.querySelector(".report-footer").textContent,
      /Select at least one section/,
    );
    assert.ok(
      document.querySelector(".source-table"),
      "even the last unchecked section remains viewable",
    );
    await click(checkbox("Summary"));
    assert.equal(views(), "pi");
    assert.equal(download().getAttribute("aria-disabled"), "false");
    assert.ok(
      document.querySelector(".source-table"),
      "selecting a download section does not switch tabs",
    );
    assert.equal(
      fetch.mock.calls.length,
      1,
      "only the initial read-only presentation request runs",
    );
    assert.match(
      fetch.mock.calls[0].arguments[0],
      /presentation\?format_source=current$/,
    );
  });
});

function structuredReport(propertyCount = 2) {
  const columns = [
    { id: "rank", label: "Rank", kind: "rank" },
    { id: "material", label: "Material (record)", kind: "identity" },
    { id: "score", label: "Overall utility", kind: "score" },
  ];
  const attributes = Array.from({ length: propertyCount }, (_, index) => ({
    id: `field_${index}`,
    label: `Test property ${index}`,
    kind: "property",
    unit: "test-unit",
  }));
  const weight = 1 / propertyCount;
  const row = {
    rank: 1,
    material_id: "fixture-record",
    formula: "Fixture",
    material: "Renderer fixture [R1]",
    score: 0.1,
    score_color: "#F9DCCE",
    score_band: "low",
    properties: Object.fromEntries(
      attributes.map(({ id }, index) => [
        id,
        {
          value: index === 0 ? 1 : null,
          unit: "test-unit",
          status: index === 0 ? "available" : "unknown",
          display: index === 0 ? "1 [R1]" : "unknown",
          utility: index === 0 ? 0.2 : 0,
          contribution: index === 0 ? 0.2 * weight : 0,
          weight,
          citation_ids: index === 0 ? ["R1"] : [],
        },
      ]),
    ),
    citation_ids: ["R1"],
    rationale: "Synthetic renderer rationale only.",
    caveats: ["Evidence gap fixture, not a scientific result."],
    missing_criteria: attributes.slice(1).map(({ id }) => id),
    selected_weight_coverage: weight,
    leading: "Test criterion",
    caveat: "Fixture evidence gap",
  };
  const summary = {
    columns: [
      ...columns,
      { id: "leading", label: "Leading criteria", kind: "text" },
      { id: "caveat", label: "Key caveat", kind: "text" },
    ],
    rows: [row],
  };
  const technical = { columns: [...columns, ...attributes], rows: [row] };
  const prose = (title, table) =>
    `${title}:\n\nSynthetic renderer fixture.\n\nShortlist:\n| ${table.columns.map(({ label }) => label).join(" | ")} |\n| ${table.columns.map(() => "---").join(" | ")} |\n| ${table.columns.map(({ id }) => ({ rank: "1", material: row.material, score: "0.1000", leading: row.leading, caveat: row.caveat })[id] ?? row.properties[id].display).join(" | ")} |\n\nCaveats:\n\n${row.caveats[0]}`;
  return {
    id: "structured-report",
    chat_id: "chat-fixture",
    message_id: "message-fixture",
    title: "Saved fixture",
    stage: "test",
    pi_summary: prose("Summary", summary),
    technical_audit: prose("Technical View", technical),
    source_ids: [],
    created_at: "2026-09-09T12:00:00Z",
    pinned: false,
    result: {
      report_tables: { schema: "ranking-tables-v1", summary, technical },
      execution: {
        ranking_profile: {
          name: "Submitted profile",
          material_class: "test",
          application: "test",
          importance: Object.fromEntries([
            ...attributes.map(({ id }) => [id, 0.5]),
            ["excluded_zero_weight", 0],
          ]),
          normalized_weights: Object.fromEntries(
            attributes.map(({ id }) => [id, weight]),
          ),
        },
        presentation: {
          style: "audit",
          outputs: ["pi", "audit"],
          format: "json",
          terminology: "general",
          verbosity: "standard",
        },
      },
    },
  };
}

test("historical technical table preserves scores and columns while showing explicit coverage without physical performance claims", async (t) => {
  t.mock.method(globalThis, "fetch", async () => {
    throw new Error(
      "Saved reports cannot fetch current ranking settings or rerun research.",
    );
  });
  await withReportDom(async ({ document, renderCard }) => {
    const report = structuredReport(14);
    report.pin = { id: "snapshot-fixture", mode: "snapshot" };
    const before = JSON.stringify(report);
    await renderCard(report, {
      style: "pi",
      outputs: ["pi"],
      format: "text",
      terminology: "general",
      verbosity: "concise",
    });
    assert.equal(
      document.querySelector('.report-tabs [aria-pressed="true"]').textContent,
      "Technical View",
      "saved presentation overrides new workspace defaults",
    );
    assert.equal(
      document.querySelector('select[id^="download-format"]').value,
      "json",
    );
    assert.equal(document.querySelectorAll("table").length, 1);
    assert.deepEqual(
      [...document.querySelectorAll("thead th")].map(
        (element) => element.textContent,
      ),
      report.result.report_tables.technical.columns.map(({ label, kind }) =>
        kind === "score" ? "Supported score" : label,
      ),
    );
    assert.equal(document.querySelector("thead th").textContent, "Rank");
    assert.equal(
      document.querySelectorAll("td.report-column-property").length,
      14,
    );
    assert.equal(
      document.querySelectorAll(".report-property-unknown").length,
      13,
    );
    assert.match(
      document.querySelectorAll("td.report-column-property")[1].textContent,
      /unknownUnscored/,
    );
    assert.equal(
      document.querySelector(".report-utility strong").textContent,
      "0.1000",
    );
    assert.match(
      document.querySelector(".report-utility").getAttribute("aria-label"),
      /Supported score 0.1000; 7.1% evidence coverage; Historical contribution; not confidence or predicted performance/,
    );
    assert.match(
      document.querySelector(".report-rank-badge").title,
      /Rank 1; supported score 0.1000; 7.1% evidence coverage/,
    );
    assert.equal(
      document.querySelector(".report-rank-badge").style.backgroundColor,
      "",
    );
    assert.ok(
      document
        .querySelector(".report-rank-badge")
        .classList.contains("report-score-neutral"),
    );
    assert.equal(
      document.querySelector(".report-score-coverage").textContent,
      "7.1% coverage",
    );
    assert.equal(
      document.querySelector(".report-historical-score").textContent,
      "Historical contribution",
    );
    assert.match(
      document.querySelector(".report-score-details").textContent,
      /saved score and order are unchanged/,
    );
    assert.equal(document.querySelector(".report-score-details").open, false);
    assert.doesNotMatch(
      document.querySelector(".report-ranked-table").textContent,
      /low utility|overall utility|Fit on known criteria/i,
    );
    assert.match(
      document.querySelector(".report-profile-snapshot").textContent,
      /Submitted profile/,
    );
    assert.doesNotMatch(
      document.querySelector(".report-profile-snapshot").textContent,
      /excluded_zero_weight/,
    );
    assert.equal(
      document.querySelectorAll(".report-profile-snapshot dt").length,
      14,
    );
    assert.match(
      document.querySelector(".report-candidate-notes").textContent,
      /Evidence gap fixture/,
    );
    assert.equal(
      JSON.stringify(report),
      before,
      "viewing does not mutate a report snapshot",
    );
  });
});

test("malformed table metadata falls back to saved prose and cannot inject styling or active content", async () => {
  await withReportDom(async ({ document, renderCard }) => {
    const report = structuredReport();
    report.result.report_tables.technical.rows[0].score_color =
      "url(https://example.com/tracker)";
    report.result.execution.ranking_profile.name =
      "<img src=x onerror=alert(1)>";
    await renderCard(report);
    assert.equal(document.querySelector(".report-ranked-table"), null);
    assert.equal(
      document.querySelectorAll("table").length,
      1,
      "original saved prose table remains readable",
    );
    assert.match(
      document.querySelector(".report-profile-snapshot").textContent,
      /<img src=x onerror=alert\(1\)>/,
    );
    assert.equal(document.querySelectorAll("img, script, [onerror]").length, 0);
    assert.equal(
      document.querySelector('[style*="url("]'),
      null,
      "untrusted metadata never becomes CSS",
    );
    assert.equal(
      document
        .querySelector(".report-document")
        .style.getPropertyValue("--report-text-size"),
      "11pt",
    );
  });
});

test("legacy report headings receive current visible names without rewriting saved content", async () => {
  await withReportDom(async ({ document, render }) => {
    const saved = "Technical Overview:\n\nHistorical recorded prose.";
    await render(saved, "audit");
    assert.equal(document.querySelector("h4").textContent, "Technical View");
    assert.match(
      document.querySelector("p").textContent,
      /Historical recorded prose/,
    );
    assert.equal(saved, "Technical Overview:\n\nHistorical recorded prose.");
  });
});

test("structured metadata cannot silently replace a conflicting saved scientific value", async () => {
  await withReportDom(async ({ document, renderCard }) => {
    const report = structuredReport();
    report.result.report_tables.technical.rows[0].properties.field_0.display =
      "999 [R1]";
    await renderCard(report);
    assert.equal(document.querySelector(".report-ranked-table"), null);
    assert.equal(document.querySelectorAll("table").length, 1);
    assert.match(document.querySelector("tbody").textContent, /1 \[R1\]/);
    assert.doesNotMatch(document.querySelector("tbody").textContent, /999/);
  });
});

test("detailed property navigation provides explicit buttons and keyboard scrolling without new requests", async () => {
  await withReportDom(async ({ document, renderCard, click, key }) => {
    await renderCard(structuredReport(14));
    const region = document.querySelector(
        '.ranked-table-block [role="region"]',
      ),
      movements = [];
    region.scrollBy = (options) => movements.push(options);
    Object.defineProperty(region, "clientWidth", { value: 700 });
    await click(
      document.querySelector('[aria-label="Show later ranking properties"]'),
    );
    await click(
      document.querySelector('[aria-label="Show earlier ranking properties"]'),
    );
    await key(region, "ArrowRight");
    assert.equal(movements.length, 3);
    assert.ok(
      movements[0].left > 0 && movements[1].left < 0 && movements[2].left > 0,
    );
    assert.ok(movements.every(({ behavior }) => behavior === "auto"));
  });
});

function presentationFixture(report, formatSource = "saved") {
  return {
    version: "report-presentation-v2",
    chat_id: report.chat_id,
    report_id: report.id,
    format_source: formatSource,
    settings_source:
      formatSource === "current" ? "current-settings" : "saved-report",
    presentation: {
      ...report.result.execution.presentation,
      layout: {
        page_size: "letter",
        font_family: formatSource === "current" ? "sans" : "serif",
        font_size: formatSource === "current" ? 12 : 10,
        line_spacing: "compact",
        accent: formatSource === "current" ? "slate" : "teal",
        table_style: "grid",
        page_numbers: true,
        text_width: 88,
        json_indent: 2,
      },
    },
    pi_summary: report.pi_summary,
    technical_audit: report.technical_audit,
    report_tables: report.result.report_tables,
    references: [
      {
        id: "R1",
        title: "Synthetic public source for renderer testing",
        url: "https://example.com/synthetic-source",
        source_name: "Test registry",
        kind: "material_evidence",
      },
    ],
    legacy: false,
  };
}

test("reports automatically use current Report Format without a report-level switch or archive mutation", async (t) => {
  const report = structuredReport(),
    before = JSON.stringify(report),
    calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    assert.match(path, /\/presentation\?format_source=current$/);
    return Response.json(presentationFixture(report, "current"));
  });
  await withReportDom(async ({ document, renderCard, click }) => {
    const current = {
      style: "pi",
      outputs: ["pi"],
      format: "pdf",
      terminology: "general",
      verbosity: "concise",
    };
    await renderCard(report, current);
    const doc = () => document.querySelector(".report-document");
    assert.ok(doc().classList.contains("report-font-sans"));
    assert.ok(doc().classList.contains("report-accent-slate"));
    assert.equal(doc().style.getPropertyValue("--report-text-size"), "12pt");
    assert.equal(
      document.querySelector('.report-tabs [aria-pressed="true"]').textContent,
      "Summary",
    );
    assert.equal(
      document.querySelector(
        'input[aria-label="Include Technical View in download"]',
      ).checked,
      false,
    );
    assert.equal(document.querySelector(".report-display-settings"), null);
    assert.doesNotMatch(
      document.body.textContent,
      /Use (saved report format|current Report Format)|Report display settings/,
    );
    assert.equal(
      document
        .querySelector(".report-material-citations a")
        .getAttribute("href"),
      "https://example.com/synthetic-source",
    );
    const archive = [
      ...document.querySelectorAll(".report-audit-disclosure"),
    ].find(
      (item) =>
        item.querySelector("summary").textContent ===
        "Full saved audit & original report",
    );
    assert.equal(archive.open, false);
    assert.match(archive.textContent, /fixture-record/);
    await click(
      document.querySelector('input[aria-label="Include Sources in download"]'),
    );
    await renderCard(report, { ...current, verbosity: "detailed" });
    assert.match(
      document
        .querySelector(".report-download-controls a")
        .getAttribute("href"),
      /&format_source=current$/,
    );
    assert.equal(
      document.querySelector('input[aria-label="Include Sources in download"]')
        .checked,
      false,
      "refreshing format preserves chosen export sections",
    );
    assert.equal(calls.length, 2);
    assert.ok(
      calls.every(({ options }) => !options.method || options.method === "GET"),
    );
    assert.ok(
      calls.every(
        ({ options }) =>
          options.credentials === "same-origin" && options.redirect === "error",
      ),
    );
    assert.equal(JSON.stringify(report), before);
  });
});

test("project snapshot pins retain their saved format while tracking pins follow current preferences", async (t) => {
  const report = structuredReport();
  report.pin = { id: "pin-fixture", mode: "snapshot" };
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path) => {
    calls.push(path);
    return Response.json(
      presentationFixture(
        report,
        path.endsWith("current") ? "current" : "saved",
      ),
    );
  });
  await withReportDom(async ({ document, renderCard }) => {
    await renderCard(report);
    assert.ok(
      document
        .querySelector(".report-document")
        .classList.contains("report-font-serif"),
    );
    assert.doesNotMatch(
      document.querySelector(".report-download-link").href,
      /format_source=current/,
    );
    assert.equal(document.querySelector(".report-display-settings"), null);
    await renderCard({ ...report, pin: { ...report.pin, mode: "latest" } });
    assert.ok(
      document
        .querySelector(".report-document")
        .classList.contains("report-font-sans"),
    );
    assert.match(
      document.querySelector(".report-download-link").href,
      /format_source=current/,
    );
    assert.equal(calls.length, 2);
  });
});

test("format failure retains saved report and matching downloads; retry also formats legacy prose", async (t) => {
  const report = structuredReport();
  delete report.result;
  const response = {
    ...presentationFixture(structuredReport(), "current"),
    report_tables: null,
    legacy: true,
  };
  let calls = 0;
  t.mock.method(globalThis, "fetch", async (path) => {
    assert.match(path, /presentation\?format_source=current$/);
    if (++calls === 1) throw new Error("offline");
    return Response.json(response);
  });
  await withReportDom(async ({ document, renderCard, click }) => {
    await renderCard(report);
    assert.match(
      document.querySelector(".report-document").textContent,
      /Synthetic renderer fixture/,
    );
    assert.equal(
      document
        .querySelector(".report-download-link")
        .getAttribute("aria-disabled"),
      "false",
    );
    assert.doesNotMatch(
      document.querySelector(".report-download-link").href,
      /format_source=current/,
    );
    assert.match(
      document.querySelector('[role="status"]').textContent,
      /original saved report remains visible/,
    );
    await click(
      [...document.querySelectorAll("button")].find(
        (button) => button.textContent === "Retry report layout",
      ),
    );
    assert.equal(document.querySelector('[role="status"]'), null);
    assert.ok(
      document
        .querySelector(".report-document")
        .classList.contains("report-font-sans"),
    );
    assert.match(
      document.querySelector(".report-download-link").href,
      /format_source=current/,
    );
    assert.equal(calls, 2);
  });
});

test("a legacy snapshot cancels pending current formatting and remains downloadable", async (t) => {
  const report = structuredReport();
  delete report.result;
  let finish, signal;
  t.mock.method(globalThis, "fetch", async (_path, options) => {
    signal = options.signal;
    return new Promise((resolve) => {
      finish = resolve;
    });
  });
  await withReportDom(async ({ document, renderCard }) => {
    await renderCard(report);
    assert.equal(
      document
        .querySelector(".report-download-link")
        .getAttribute("aria-disabled"),
      "true",
    );
    await renderCard({
      ...report,
      pin: { id: "snapshot-legacy", mode: "snapshot" },
    });
    assert.equal(signal.aborted, true);
    assert.equal(
      document
        .querySelector(".report-download-link")
        .getAttribute("aria-disabled"),
      "false",
    );
    assert.doesNotMatch(
      document.querySelector(".report-download-link").href,
      /format_source=current/,
    );
    const { act } = await import("react");
    await act(async () =>
      finish(Response.json(presentationFixture(structuredReport(), "current"))),
    );
    assert.equal(document.querySelector(".report-reformat-note"), null);
    assert.doesNotMatch(
      document.querySelector(".report-download-link").href,
      /format_source=current/,
    );
  });
});

test("late report presentation responses cannot replace another report or its references", async (t) => {
  const first = structuredReport(),
    second = structuredReport();
  second.id = "second-report";
  second.technical_audit = second.technical_audit.replace(
    "Synthetic renderer fixture.",
    "Second saved report.",
  );
  let resolveOld, oldSignal;
  t.mock.method(globalThis, "fetch", async (path, options) => {
    if (path.includes("/structured-report/")) {
      oldSignal = options.signal;
      return new Promise((resolve) => {
        resolveOld = resolve;
      });
    }
    return Response.json(presentationFixture(second, "current"));
  });
  await withReportDom(async ({ document, renderCard }) => {
    await renderCard(first);
    await renderCard(second);
    assert.equal(oldSignal.aborted, true);
    assert.match(
      document.querySelector(".report-document").textContent,
      /Second saved report/,
    );
    const { act } = await import("react");
    await act(async () =>
      resolveOld(Response.json(presentationFixture(first, "current"))),
    );
    assert.match(
      document.querySelector(".report-document").textContent,
      /Second saved report/,
    );
    assert.doesNotMatch(
      document.querySelector(".report-document").textContent,
      /Synthetic renderer fixture\./,
    );
  });
});

test("report presentation transport rejects foreign report identity, unsafe citations and inconsistent tables", async () => {
  const { parsePresentedReport } = await import(
    pathToFileURL(join(output, "reportPresentationApi.js")).href
  );
  const report = structuredReport(),
    value = presentationFixture(report);
  assert.equal(
    parsePresentedReport(value, report.chat_id, report.id, "saved").report_id,
    report.id,
  );
  for (const url of [
    "javascript:alert(1)",
    "https://localhost/data",
    "http://127.0.0.1/private",
    "https://user:password@example.com/",
  ]) {
    assert.throws(
      () =>
        parsePresentedReport(
          { ...value, references: [{ ...value.references[0], url }] },
          report.chat_id,
          report.id,
          "saved",
        ),
      /report layout/,
    );
  }
  assert.throws(
    () =>
      parsePresentedReport(
        { ...value, report_id: "wrong-report" },
        report.chat_id,
        report.id,
        "saved",
      ),
    /report layout/,
  );
  assert.throws(
    () =>
      parsePresentedReport(
        { ...value, report_tables: { schema: "invented-table" } },
        report.chat_id,
        report.id,
        "saved",
      ),
    /report layout/,
  );
  assert.throws(
    () =>
      parsePresentedReport(
        { ...value, references: [value.references[0], value.references[0]] },
        report.chat_id,
        report.id,
        "saved",
      ),
    /report layout/,
  );
});

test("display formula uses server spelling while the exact source formula stays in a closed audit note", async () => {
  const report = structuredReport();
  const row = report.result.report_tables.technical.rows[0];
  Object.assign(row, {
    formula: "SiO2",
    source_formula: "O2Si",
    material: "SiO2 [R1]",
    rationale: "",
    caveats: [],
  });
  const content = report.technical_audit.replace(
    "Renderer fixture [R1]",
    "SiO2 [R1]",
  );
  const before = JSON.stringify(report);
  await withReportDom(async ({ document, render }) => {
    await render(content, "audit", {
      table: report.result.report_tables.technical,
    });
    const identity = document.querySelector("td.report-column-identity");
    const formula = identity.querySelector(".material-formula");
    assert.equal(formula.textContent, "SiO2");
    assert.equal(formula.getAttribute("aria-label"), "SiO2");
    assert.equal(formula.querySelector("sub").textContent, "2");
    const details = identity.querySelector(".report-candidate-notes");
    assert.ok(
      details,
      "a changed source spelling alone is enough to retain its audit disclosure",
    );
    assert.equal(details.open, false);
    assert.equal(
      details.querySelector(".report-source-formula").textContent,
      "O2Si",
    );
    assert.match(details.textContent, /Source record: fixture-record/);
    assert.equal(
      JSON.stringify(report),
      before,
      "display never rewrites report snapshots or record identities",
    );
    const unchanged = structuredClone(report.result.report_tables.technical);
    unchanged.rows[0].source_formula = "SiO2";
    await render(content, "audit", { table: unchanged });
    assert.equal(
      document.querySelector(".report-source-formula"),
      null,
      "identical formula spelling adds no redundant audit note",
    );
    assert.equal(document.querySelector(".report-candidate-notes"), null);
  });
});

test("optional source formula accepts bounded literal text without weakening saved table validation", async () => {
  const { savedReportTables } = await import(
    pathToFileURL(join(output, "reportTables.js")).href
  );
  const report = structuredReport();
  assert.ok(
    savedReportTables(report.result),
    "older reports without source_formula remain supported",
  );
  report.result.report_tables.technical.rows[0].source_formula = "O2Si";
  assert.equal(
    savedReportTables(report.result).technical.rows[0].source_formula,
    "O2Si",
  );
  for (const source_formula of [null, 123, {}, "A".repeat(257)]) {
    report.result.report_tables.technical.rows[0].source_formula =
      source_formula;
    assert.equal(savedReportTables(report.result), null);
  }
});

test("only source-backed formula tokens receive chemical subscripts in report prose and material citations", async () => {
  const report = structuredReport();
  const table = report.result.report_tables.technical;
  Object.assign(table.rows[0], { formula: "SiO2", material: "SiO2 [R1]" });
  const content =
    "Summary:\n\nSiO2 has a source-backed display label [R1]. Compare SiO2.\nMeasurements 2.5 eV and 300 K, unknown TiO2, prefixXSiO2suffix, ID:SiO2, https://example.org/SiO2 and 10.1234/SiO2 remain literal.\n\nPublic references:\n- [R1] Material SiO2\n- [S1] Publication discussing SiO2";
  const references = [
    {
      id: "R1",
      title: "Material SiO2",
      url: "https://example.org/material",
      source_name: "Synthetic material source",
      kind: "material_evidence",
    },
    {
      id: "S1",
      title: "Publication discussing SiO2",
      url: "https://example.org/publication",
      source_name: "Synthetic publication",
      kind: "discovery_reference",
    },
  ];
  await withReportDom(async ({ document, render }) => {
    await render(content, "pi", { table, references });
    const paragraph = document.querySelector(".report-document > p");
    assert.equal(paragraph.querySelectorAll("sub").length, 2);
    assert.ok(
      [...paragraph.querySelectorAll("sub")].every(
        (element) => element.textContent === "2",
      ),
    );
    assert.match(
      paragraph.textContent,
      /Measurements 2.5 eV and 300 K, unknown TiO2/,
    );
    assert.match(
      paragraph.textContent,
      /https:\/\/example.org\/SiO2 and 10.1234\/SiO2/,
    );
    assert.equal(
      document.querySelector(".report-citation").getAttribute("title"),
      "Material SiO2 · Synthetic material source",
    );
    const referenceLinks = document.querySelectorAll(
      ".report-reference-list a",
    );
    assert.equal(referenceLinks[0].querySelectorAll("sub").length, 1);
    assert.equal(
      referenceLinks[1].querySelectorAll("sub").length,
      0,
      "publication titles remain literal",
    );
    assert.equal(table.rows[0].formula, "SiO2");
  });
});

test("ambiguous chemical notation and all property values remain literal", async () => {
  const { createElement } = await import("react");
  const { renderToStaticMarkup } = await import("react-dom/server");
  const { MaterialFormula } = await import(
    pathToFileURL(join(output, "ReportContent.js")).href
  );
  for (const formula of [
    "Fe3+",
    "CuSO4·5H2O",
    "Ca(OH)2",
    "Ba0.5Sr0.5TiO3",
    "H2OH",
    "O02Si",
  ]) {
    const html = renderToStaticMarkup(
      createElement(MaterialFormula, { formula }),
    );
    assert.doesNotMatch(html, /<sub>/, formula);
    assert.ok(html.includes(formula));
  }
  const report = structuredReport();
  const table = report.result.report_tables.technical;
  const row = table.rows[0];
  Object.assign(row, { formula: "SiO2", material: "SiO2 [R1]" });
  row.properties.field_0.display = "SiO2";
  const content = report.technical_audit
    .replace("Renderer fixture [R1]", "SiO2 [R1]")
    .replace("1 [R1]", "SiO2");
  await withReportDom(async ({ document, render }) => {
    await render(content, "audit", { table });
    assert.equal(
      document
        .querySelector("td.report-column-property")
        .querySelectorAll("sub").length,
      0,
    );
    assert.equal(
      document.querySelector("td.report-column-identity .material-formula")
        .textContent,
      "SiO2",
    );
  });
});

function withScoreAnalysis(report = structuredReport()) {
  const row = report.result.report_tables.technical.rows[0];
  row.score_analysis = {
    observed_fit: 0.2,
    coverage: 0.5,
    possible_upper_score: 0.6,
    required_criteria: ["band_gap", "dielectric_total"],
    missing_required_criteria: ["dielectric_total"],
    status: "needs_evidence",
  };
  row.missing_criteria = ["dielectric_total"];
  return report;
}

test("missing required evidence is neutral with visible coverage and an explicit partial fit explanation", async () => {
  const report = withScoreAnalysis();
  const table = report.result.report_tables.technical;
  Object.assign(table.rows[0], {
    formula: "SiO2",
    source_formula: "O2Si",
    material: "SiO2 [R1]",
  });
  const content = report.technical_audit.replace(
    "Renderer fixture [R1]",
    "SiO2 [R1]",
  );
  const before = JSON.stringify(report);
  await withReportDom(async ({ document, render, click }) => {
    await render(content, "audit", { table });
    assert.equal(
      document.querySelector(".report-utility strong").textContent,
      "0.1000",
    );
    assert.equal(
      document.querySelector(".report-score-coverage").textContent,
      "50.0% coverage",
    );
    assert.equal(
      document.querySelector(".report-evidence-status").textContent,
      "Needs total dielectric scalar evidence",
    );
    for (const badge of document.querySelectorAll(
      ".report-utility, .report-rank-badge",
    )) {
      assert.ok(badge.classList.contains("report-score-neutral"));
      assert.equal(
        badge.style.backgroundColor,
        "",
        "low supported contribution must not color incomplete evidence as a poor material",
      );
    }
    const details = document.querySelector(".report-score-details");
    assert.equal(details.open, false);
    await click(details.querySelector("summary"));
    assert.equal(details.open, true);
    assert.match(details.textContent, /Fit on known criteria: 0.2000/);
    assert.match(
      details.textContent,
      /partial fit, not predicted material performance/,
    );
    assert.match(details.textContent, /Missing-criterion range: 0.1000–0.6000/);
    assert.match(details.textContent, /Holding observed property scores fixed/);
    assert.match(details.textContent, /not a confidence interval/);
    assert.equal(
      document.querySelector("td.report-column-identity .material-formula")
        .textContent,
      "SiO2",
    );
    assert.equal(
      document.querySelector("td.report-column-identity .material-formula sub")
        .textContent,
      "2",
    );
    assert.equal(
      document.querySelector(".report-source-formula").textContent,
      "O2Si",
    );
    assert.equal(document.querySelector(".report-source-formula sub"), null);
    assert.doesNotMatch(
      document.querySelector(".report-ranked-table").textContent,
      /low utility/i,
    );
    assert.equal(JSON.stringify(report), before);
  });
});

test("score color is used only for complete comparable evidence while summary coverage remains visible", async () => {
  const partial = withScoreAnalysis();
  partial.result.report_tables.summary.rows[0].score_analysis = {
    observed_fit: 0.2,
    coverage: 0.5,
    possible_upper_score: 0.6,
    required_criteria: [],
    missing_required_criteria: [],
    status: "comparable",
  };
  const complete = structuredReport(1),
    row = complete.result.report_tables.technical.rows[0];
  row.score = 0.2;
  row.score_analysis = {
    observed_fit: 0.2,
    coverage: 1,
    possible_upper_score: 0.2,
    required_criteria: [],
    missing_required_criteria: [],
    status: "comparable",
  };
  await withReportDom(async ({ document, render }) => {
    await render(partial.pi_summary, "pi", {
      table: partial.result.report_tables.summary,
    });
    assert.equal(
      document.querySelector(".report-score-coverage").textContent,
      "50.0% coverage",
    );
    assert.equal(
      document.querySelector(".report-evidence-status"),
      null,
      "no application-specific requirement is invented",
    );
    assert.ok(
      document
        .querySelector(".report-utility")
        .classList.contains("report-score-neutral"),
    );
    assert.match(
      document.querySelector(".report-utility").getAttribute("aria-label"),
      /Partial evidence/,
    );
    await render(
      complete.technical_audit.replace("0.1000", "0.2000"),
      "audit",
      { table: complete.result.report_tables.technical },
    );
    assert.equal(
      document.querySelector(".report-score-coverage").textContent,
      "100.0% coverage",
    );
    assert.equal(
      document
        .querySelector(".report-utility")
        .classList.contains("report-score-neutral"),
      false,
    );
    assert.equal(
      document.querySelector(".report-utility").style.backgroundColor,
      "rgb(249, 220, 206)",
    );
    assert.equal(document.querySelector(".report-rank-badge").textContent, "1");
    assert.match(
      document.querySelector(".report-score-details").textContent,
      /Missing-criterion range: 0.2000–0.2000/,
    );
  });
});

test("optional score analysis rejects malformed or contradictory diagnostics and tolerates saved-score rounding", async () => {
  const { savedReportTables } = await import(
    pathToFileURL(join(output, "reportTables.js")).href
  );
  const report = withScoreAnalysis(),
    valid = report.result.report_tables.technical.rows[0].score_analysis;
  assert.ok(savedReportTables(report.result));
  for (const score_analysis of [
    null,
    {},
    { ...valid, observed_fit: "0.2" },
    { ...valid, coverage: NaN },
    { ...valid, observed_fit: Infinity },
    { ...valid, observed_fit: 1.01 },
    { ...valid, possible_upper_score: -0.1 },
    { ...valid, status: "good_material" },
    { ...valid, required_criteria: ["dielectric_total", "dielectric_total"] },
    { ...valid, required_criteria: ["<img>"] },
    { ...valid, required_criteria: ["x".repeat(65)] },
    { ...valid, missing_required_criteria: ["absent_requirement"] },
    { ...valid, missing_required_criteria: [] },
    { ...valid, status: "comparable" },
    { ...valid, confidence: 1 },
    { ...valid, coverage: 0.7 },
    { ...valid, observed_fit: 0.8 },
    { ...valid, possible_upper_score: 0.9 },
  ]) {
    const result = structuredClone(report.result);
    result.report_tables.technical.rows[0].score_analysis = score_analysis;
    assert.equal(
      savedReportTables(result),
      null,
      `invalid diagnostics: ${JSON.stringify(score_analysis)}`,
    );
  }
  const rounded = structuredClone(report.result),
    row = rounded.report_tables.technical.rows[0];
  row.score = 0.00000001;
  row.selected_weight_coverage = 0.00000001;
  row.score_analysis = {
    ...valid,
    observed_fit: 0.7,
    coverage: 0.00000001,
    possible_upper_score: 0.999999997,
  };
  assert.ok(
    savedReportTables(rounded),
    "very small valid importance must tolerate the server’s eight-place score rounding",
  );
});

test("saved profile minimum-gap preference stays separate from weights and is rendered without applying current settings", async () => {
  const { savedProfileSnapshot } = await import(
    pathToFileURL(join(output, "reportTables.js")).href
  );
  const report = structuredReport(),
    profile = report.result.execution.ranking_profile;
  assert.equal(
    Object.hasOwn(savedProfileSnapshot(report.result), "minimum_band_gap_ev"),
    false,
  );
  profile.minimum_band_gap_ev = 2;
  assert.equal(savedProfileSnapshot(report.result).minimum_band_gap_ev, 2);
  const before = JSON.stringify(report);
  await withReportDom(async ({ document, renderCard }) => {
    await renderCard(report);
    assert.match(
      document.querySelector(".report-profile-snapshot").textContent,
      /Minimum band gap: 2 eV · Inactive; Band gap importance is zero or unselected/,
    );
    assert.equal(
      document.querySelectorAll(".report-profile-snapshot dt").length,
      2,
      "the floor is not a normalized importance",
    );
    assert.equal(JSON.stringify(report), before);
  });
  for (const value of [-1, 101, true, "2", NaN, Infinity]) {
    profile.minimum_band_gap_ev = value;
    assert.equal(
      savedProfileSnapshot(report.result),
      null,
      "invalid saved preference cannot be presented as a screening condition",
    );
  }
  profile.minimum_band_gap_ev = null;
  assert.equal(savedProfileSnapshot(report.result).minimum_band_gap_ev, null);
});

test("saved target-gap preferences are displayed from the run snapshot without inventing measurements or defaults", async () => {
  const { savedProfileSnapshot } = await import(
    pathToFileURL(join(output, "reportTables.js")).href
  );
  const report = structuredReport(),
    profile = report.result.execution.ranking_profile;
  assert.equal(
    Object.hasOwn(savedProfileSnapshot(report.result), "target_band_gap_ev"),
    false,
  );
  profile.target_band_gap_ev = 1.78;
  profile.band_gap_tolerance_ev = 0.2;
  const before = JSON.stringify(report);
  await withReportDom(async ({ document, renderCard }) => {
    await renderCard(report);
    const note = document.querySelector(
      ".report-target-preference",
    ).textContent;
    assert.match(
      note,
      /Target band gap: 1\.78 eV · Ranking preference for this report/,
    );
    assert.match(
      note,
      /Preference tolerance: 0\.2 eV, used as a soft ranking scale/,
    );
    assert.match(note, /separate from measured material properties/);
    assert.equal(
      JSON.stringify(report),
      before,
      "rendering preserves the saved result",
    );
  });
  delete profile.band_gap_tolerance_ev;
  assert.equal(
    Object.hasOwn(savedProfileSnapshot(report.result), "band_gap_tolerance_ev"),
    false,
    "missing historical tolerance is not reconstructed from current defaults",
  );
  for (const patch of [
    { target_band_gap_ev: -1 },
    { target_band_gap_ev: "1.78" },
    { target_band_gap_ev: null, band_gap_tolerance_ev: 0.2 },
    { band_gap_tolerance_ev: 0 },
    { band_gap_tolerance_ev: 101 },
  ]) {
    const value = structuredClone(report.result);
    Object.assign(value.execution.ranking_profile, patch);
    assert.equal(savedProfileSnapshot(value), null);
  }
});

test("provisional literature shortlist retains ranked rows, uncertainty and safe source links", async () => {
  const fixture = await leadFixture();
  const reference = fixture.references[0];
  // Synthetic display data: these judgments are not materials evidence.
  const content = `Summary:\n\nProvisional literature shortlist:\n\n| Provisional rank | Material | Literature fit | Selected criterion assessments | Assessment coverage | Stability & uncertainty |\n| --- | --- | --- | --- | --- | --- |\n| 1 | Fixture-A [${reference.id}] | 0.400 supported; known fit 0.800 | Test criterion: supports | 50% | Operational stability unknown; range 0.400–0.900 |\n| 1 | Fixture-B [${reference.id}] | 0.400 supported; known fit 0.500 | Test criterion: mixed | 80% | Phase stability concern; range 0.400–0.600 |`;
  await withReportDom(async ({ document, render }) => {
    await render(content, "pi", { references: [reference] });
    assert.equal(
      document.querySelectorAll(".report-literature-table tbody tr").length,
      2,
    );
    assert.equal(
      document.querySelectorAll(".report-literature-rank").length,
      2,
    );
    assert.deepEqual(
      [...document.querySelectorAll(".report-literature-rank")].map(
        (cell) => cell.textContent,
      ),
      ["1", "1"],
    );
    assert.equal(
      document.querySelectorAll(".report-utility, .report-score-gradient")
        .length,
      0,
      "provisional judgments do not become measured performance badges",
    );
    assert.equal(
      document.querySelector(".report-literature-table a").href,
      reference.url,
    );
    assert.match(document.body.textContent, /Operational stability unknown/);
    assert.match(document.body.textContent, /Phase stability concern/);
    assert.match(
      document.body.textContent,
      /Public literature; assessments cite source passages/,
    );
    assert.ok(
      document.querySelector(
        '[aria-label="Provisional literature shortlist, scroll horizontally if needed"][tabindex="0"]',
      ),
    );
    await render(content.replace("Fixture-A", "<img src=x onerror=alert(1)>"));
    assert.equal(document.querySelectorAll("img, script").length, 0);
    assert.match(document.body.textContent, /<img src=x onerror=alert\(1\)>/);
    await render(content.replace("Literature fit", "Unrecognized score"));
    assert.equal(
      document.querySelectorAll(".report-literature-table").length,
      0,
    );
    assert.equal(
      document.querySelectorAll("tbody tr").length,
      2,
      "unrecognized tables preserve literal contents",
    );
  });
});

test("preliminary shortlist preserves unknown-only ties, source links and bounded chemical typography", async () => {
  const fixture = await leadFixture();
  const leads = structuredClone(fixture.leads.slice(0, 2));
  leads[0].name = "O2Si";
  leads[1].name = "PM6";
  const reference = fixture.references.find(
    (item) => item.url === leads[0].url,
  );
  // Synthetic display fixture only; no material suitability is asserted.
  const content = `Summary:\n\nSiO2 and PM6 require review.\n\nCandidate shortlist:\n\n| Rank | Material | Screening priority | Why considered | Attribute evidence | Stability / key caveat |\n| --- | --- | --- | --- | --- | --- |\n| 1 | SiO2 [${reference.id}] | 0.225 · preliminary | Application unknown; literal quote O2Si | 0% · all unknown | Stability unknown |\n| 1 | PM6 [${reference.id}] | 0.225 · preliminary | Mention only | 0% · all unknown | Stability unknown |`;
  await withReportDom(async ({ document, render }) => {
    await render(content, "pi", {
      candidateLeads: leads,
      references: fixture.references,
      afterShortlist: "Structure controls fixture",
    });
    assert.deepEqual(
      [...document.querySelectorAll(".report-literature-rank")].map(
        (cell) => cell.textContent,
      ),
      ["1", "1"],
    );
    assert.equal(
      document.querySelectorAll(".report-literature-table tbody tr").length,
      2,
    );
    assert.match(
      document.querySelector("caption").textContent,
      /Application evidence and attribute refinement/,
    );
    assert.equal(
      document.querySelector("tbody td:nth-child(2) sub").textContent,
      "2",
    );
    assert.equal(
      document.querySelectorAll("tbody tr:nth-child(2) sub").length,
      0,
      "a product name is not an elemental formula",
    );
    assert.equal(
      document.querySelectorAll("tbody td:nth-child(4) sub").length,
      0,
      "source excerpts stay literal",
    );
    assert.equal(
      document.querySelector(".report-literature-table a").href,
      reference.url,
    );
    assert.match(
      document.querySelector(".report-literature-rank").title,
      /tied ranks cannot be distinguished/,
    );
    assert.equal(
      document.querySelectorAll(".report-utility, .report-score-gradient")
        .length,
      0,
    );
    assert.ok(
      document.querySelector(
        '[aria-label="Candidate shortlist, scroll horizontally if needed"][tabindex="0"]',
      ),
    );
    assert.match(document.body.textContent, /Structure controls fixture/);
    await render(content, "pi", { references: fixture.references });
    assert.equal(
      document.querySelectorAll("sub").length,
      0,
      "unbound candidate names do not authorize chemistry formatting",
    );
  });
});

test("current preliminary priority badges separate unknown priors, assessed values and adverse tiers", async () => {
  // Synthetic status/percentage pairs exercise presentation only.
  const content = `Candidate shortlist:
| Rank | Material | Screening priority | Why considered | Attribute evidence | Stability / key caveat |
| --- | --- | --- | --- | --- | --- |
| 1 | Fixture-A | 100% · Assessed review priority | Test assessment | Test coverage | Stability unknown |
| 2 | Fixture-B | 60% · Assessed review priority | Test assessment | Test coverage | Stability unknown |
| 3 | Fixture-C | 22% · Unassessed review prior | Unassessed | 0% assessed | Stability unknown |
| 4 | Fixture-D | 0% · Assessed review priority | Test assessment | Test coverage | Stability unknown |
| 5 | Fixture-E | 95% · Mixed evidence | Test mixed assessment | Test coverage | Mixed stability assessment |
| 6 | Fixture-F | 99% · Concern reported | Test concern | Test coverage | Application concern |`;
  await withReportDom(async ({ document, render }) => {
    for (const view of ["pi", "audit"]) {
      await render(content, view);
      const badges = [
        ...document.querySelectorAll(".report-screening-priority"),
      ];
      assert.equal(badges.length, 6);
      assert.deepEqual(
        badges.map((badge) => badge.querySelector("strong").textContent),
        ["100%", "60%", "22%", "0%", "95%", "99%"],
      );
      assert.equal(badges[0].style.backgroundColor, "rgb(213, 237, 221)");
      assert.equal(badges[2].style.backgroundColor, "rgb(237, 240, 242)");
      assert.equal(badges[3].style.backgroundColor, "rgb(255, 240, 194)");
      assert.equal(badges[4].style.backgroundColor, "rgb(255, 224, 178)");
      assert.equal(badges[5].style.backgroundColor, "rgb(248, 215, 218)");
      assert.notEqual(
        badges[0].style.backgroundColor,
        badges[1].style.backgroundColor,
      );
      assert.match(badges[2].textContent, /Unassessed review prior/);
      assert.match(
        badges[2].getAttribute("aria-label"),
        /not evidence of suitability or a favorable finding/,
      );
      assert.match(badges[5].title, /caution takes precedence/);
      assert.ok(
        badges.every((badge) =>
          /not a success rate or confidence/.test(
            badge.getAttribute("aria-label"),
          ),
        ),
      );
      const ranks = [...document.querySelectorAll(".report-literature-rank")];
      assert.deepEqual(
        ranks.map((rank) => rank.style.backgroundColor),
        badges.map((badge) => badge.style.backgroundColor),
      );
      const legend = document.querySelector(
        '[aria-label="Screening priority color key"]',
      );
      assert.ok(legend);
      const details = legend.closest(".report-method-disclosure");
      assert.ok(details, "score explanation belongs to the bottom appendix");
      assert.equal(details.open, false);
      assert.equal(
        document.querySelector(".report-document").lastElementChild,
        details,
      );
      assert.ok(
        document
          .querySelector(".report-screening-order")
          .closest(".report-method-disclosure"),
      );
      assert.equal(
        document
          .querySelector(".report-literature-table")
          .closest(".report-method-disclosure"),
        null,
      );
      for (const label of [
        "Unassessed prior",
        "Mixed evidence",
        "Concern reported",
        "not a favorable finding",
      ])
        assert.ok(legend.textContent.includes(label));
      assert.equal(
        document.querySelectorAll(".report-utility").length,
        0,
        "review priorities remain distinct from quantitative utilities",
      );
    }
  });
});

test("historical and malformed priority labels cannot imply favorable color assessments", async () => {
  const cells = [
    "22% · No adverse assessment",
    "101% · Assessed review priority",
    "-1% · Assessed review priority",
    "99% · <style>green</style>",
    "0.225 · preliminary",
  ];
  const content = `Candidate shortlist:
| Rank | Material | Screening priority | Why considered | Attribute evidence | Stability / key caveat |
| --- | --- | --- | --- | --- | --- |
${cells.map((cell, index) => `| ${index + 1} | Fixture | ${cell} | Test reason | Unknown | Unknown |`).join("\n")}`;
  await withReportDom(async ({ document, render }) => {
    await render(content);
    assert.equal(
      document.querySelectorAll(
        ".report-screening-priority, .report-screening-legend, style",
      ).length,
      0,
    );
    assert.deepEqual(
      [...document.querySelectorAll("tbody td:nth-child(3)")].map(
        (cell) => cell.textContent,
      ),
      cells,
    );
    assert.ok(
      [...document.querySelectorAll(".report-literature-rank")].every(
        (rank) => rank.style.backgroundColor === "",
      ),
    );
    assert.equal(
      document.querySelectorAll(
        ".report-screening-group, .report-screening-order, .report-rank-tie",
      ).length,
      0,
    );
  });
});

test("concern groups explain apparent score increases while preserving rows, skipped ranks and real ties", async () => {
  // Synthetic analogue of the reported group transition, not scientific evidence.
  const content = `Candidate shortlist:
| Rank | Material | Screening priority | Why considered | Attribute evidence | Stability / key caveat |
| --- | --- | --- | --- | --- | --- |
| 1 | Fixture-A | 78% · Assessed review priority | Test assessment | Unknown | Unknown |
| 2 | Fixture-B | 22% · Unassessed review prior | Unassessed | Unknown | Unknown |
| 2 | Fixture-C | 22% · Unassessed review prior | Unassessed | Unknown | Unknown |
| 2 | Fixture-D | 22% · Unassessed review prior | Unassessed | Unknown | Unknown |
| 5 | Fixture-E | 43% · Mixed evidence | Test mixed assessment | Unknown | Mixed application evidence |
| 6 | Fixture-F | 80% · Concern reported | Test concern | Unknown | Application concern |`;
  await withReportDom(async ({ document, render }) => {
    for (const view of ["pi", "audit"]) {
      await render(content, view);
      assert.deepEqual(
        [...document.querySelectorAll(".report-screening-group strong")].map(
          (item) => item.textContent,
        ),
        ["First review group", "Mixed evidence", "Reported concerns"],
      );
      assert.deepEqual(
        [...document.querySelectorAll("tbody")].map(
          (group) =>
            group.querySelectorAll("tr:not(.report-screening-group)").length,
        ),
        [4, 1, 1],
      );
      assert.ok(
        [...document.querySelectorAll(".report-screening-group th")].every(
          (cell) => cell.scope === "rowgroup" && cell.colSpan === 6,
        ),
      );
      assert.match(
        document.querySelector(".report-screening-group").textContent,
        /includes unassessed candidates; it does not establish suitability/,
      );
      assert.match(
        document.querySelectorAll(".report-screening-group")[1].textContent,
        /regardless of percentage/,
      );
      assert.match(
        document.querySelector('[aria-label="Shortlist ordering"]').textContent,
        /highest to lowest within each group/,
      );
      assert.match(
        document.querySelector('[aria-label="Shortlist ordering"]').textContent,
        /later rank numbers may be skipped/,
      );
      assert.deepEqual(
        [...document.querySelectorAll("tbody td:nth-child(2)")].map(
          (cell) => cell.textContent,
        ),
        [
          "Fixture-A",
          "Fixture-B",
          "Fixture-C",
          "Fixture-D",
          "Fixture-E",
          "Fixture-F",
        ],
      );
      assert.deepEqual(
        [...document.querySelectorAll(".report-screening-priority strong")].map(
          (item) => item.textContent,
        ),
        ["78%", "22%", "22%", "22%", "43%", "80%"],
      );
      assert.deepEqual(
        [...document.querySelectorAll(".report-literature-rank")].map(
          (item) => item.textContent,
        ),
        ["1", "2", "2", "2", "5", "6"],
      );
      assert.equal(document.querySelectorAll(".report-rank-tie").length, 3);
      assert.equal(
        document.querySelectorAll(
          '[aria-label="Rank 2, tied with 2 other candidates"]',
        ).length,
        3,
      );
    }
  });
});

test("ties come from retained ranks rather than equal rounded percentages", async () => {
  const content = `Candidate shortlist:
| Rank | Material | Screening priority | Why considered | Attribute evidence | Stability / key caveat |
| --- | --- | --- | --- | --- | --- |
| 1 | Fixture-A | 22% · Assessed review priority | Test assessment | Unknown | Unknown |
| 2 | Fixture-B | 22% · Assessed review priority | Test assessment | Unknown | Unknown |
| 3 | Fixture-C | 22% · Unassessed review prior | Unassessed | Unknown | Unknown |
| 3 | Fixture-D | 22% · Unassessed review prior | Unassessed | Unknown | Unknown |`;
  await withReportDom(async ({ document, render }) => {
    await render(content);
    assert.equal(
      document.querySelectorAll(".report-screening-group").length,
      0,
      "one group needs no repeated group heading",
    );
    assert.deepEqual(
      [...document.querySelectorAll("tbody td:first-child")].map(
        (cell) => cell.textContent,
      ),
      ["1", "2", "3tie", "3tie"],
    );
    assert.equal(
      document.querySelectorAll(
        '[aria-label="Rank 3, tied with 1 other candidate"]',
      ).length,
      2,
    );
    assert.match(
      document.querySelector('[aria-label="Shortlist ordering"]').textContent,
      /Rounded percentages can look equal even when ranks differ/,
    );
  });
});

test("unrecognized ordering is retained without claiming new concern groups or changing rank values", async () => {
  const content = `Candidate shortlist:
| Rank | Material | Screening priority | Why considered | Attribute evidence | Stability / key caveat |
| --- | --- | --- | --- | --- | --- |
| 1 | Fixture-A | 80% · Concern reported | Test concern | Unknown | Concern |
| 2 | Fixture-B | 22% · Unassessed review prior | Unassessed | Unknown | Unknown |`;
  await withReportDom(async ({ document, render }) => {
    await render(content);
    assert.equal(
      document.querySelectorAll(
        ".report-screening-group, .report-screening-order",
      ).length,
      0,
    );
    assert.deepEqual(
      [...document.querySelectorAll(".report-literature-rank")].map(
        (item) => item.textContent,
      ),
      ["1", "2"],
    );
    assert.deepEqual(
      [...document.querySelectorAll("tbody td:nth-child(2)")].map(
        (item) => item.textContent,
      ),
      ["Fixture-A", "Fixture-B"],
    );
  });
});

test("structure controls remain mounted after saved JSON and the first source candidate shortlist", async () => {
  const fixture = await leadFixture();
  const afterShortlist = "UNIQUE STRUCTURE CONTROLS FIXTURE";
  await withReportDom(async ({ document, render }) => {
    const archived = { historical: true, candidates: ["Fixture-A"] };
    await render(JSON.stringify(archived), "audit", { afterShortlist });
    assert.deepEqual(
      JSON.parse(
        document.querySelector('[aria-label="Report JSON"]').textContent,
      ),
      archived,
    );
    assert.equal(document.body.textContent.split(afterShortlist).length - 1, 1);
    assert.ok(
      document
        .querySelector(".report-json")
        .textContent.endsWith(afterShortlist),
    );
    await render(
      fixture.technical +
        "\n\nOther table:\n| A | B |\n| --- | --- |\n| C | D |",
      "audit",
      {
        candidateLeads: fixture.leads,
        references: fixture.references,
        afterShortlist,
      },
    );
    assert.equal(document.querySelectorAll(".report-lead-table").length, 1);
    assert.equal(document.body.textContent.split(afterShortlist).length - 1, 1);
    assert.ok(
      document
        .querySelector(".report-lead-table")
        .parentElement.parentElement.textContent.endsWith(afterShortlist),
    );
    for (const [view, content] of [
      ["pi", fixture.summary],
      ["audit", fixture.technical],
    ]) {
      await render(
        content +
          "\n\nSearch and analysis details:\n\nOther table:\n| A | B |\n| --- | --- |\n| C | D |",
        view,
        {
          candidateLeads: fixture.leads,
          references: fixture.references,
          afterShortlist,
        },
      );
      const details = document.querySelector(".report-method-disclosure");
      assert.equal(
        document.querySelectorAll(".report-lead-table").length,
        1,
        "the exact saved lead table keeps its enhancement",
      );
      assert.equal(
        document.body.textContent.split(afterShortlist).length - 1,
        1,
      );
      assert.ok(
        document
          .querySelector(".report-lead-table")
          .parentElement.parentElement.textContent.endsWith(afterShortlist),
      );
      assert.ok(!details.textContent.includes(afterShortlist));
      assert.equal(details.querySelectorAll("table").length, 1);
      assert.equal(details.querySelector(".report-lead-table"), null);
    }
  });
});

test("technical candidate headings and comparisons remain separate from supporting record details", async () => {
  await withReportDom(async ({ render, document }) => {
    await render(
      `Technical View:

Interpretation and tradeoffs:

Candidate 1 — Test material A:

Test material A has a source-backed application observation.

Its leakage evidence remains incomplete.

Candidate 2 — Test material B:

Test material B has a different reported processing condition.

Comparison of the leading candidates:

Test material A compared with Test material B: this is the first synthetic comparison.

Test material A compared with Test material C: this is the second synthetic comparison.

Search and analysis details:

Supporting property records:

These are supporting database records, not a second application ranking.

| Rank | Material | Supported score |
| --- | --- | --- |
| 1 | Test record | 0.5 |
`,
      "audit",
    );
    const headings = [...document.querySelectorAll("h4")].map(
      (node) => node.textContent,
    );
    assert.ok(headings.includes("Candidate 1 — Test material A"));
    assert.ok(headings.includes("Candidate 2 — Test material B"));
    const paragraphs = [...document.querySelectorAll("p")];
    assert.equal(
      paragraphs.filter((node) =>
        node.textContent.includes("synthetic comparison"),
      ).length,
      2,
    );
    const appendix = [...document.querySelectorAll("details")].find((node) =>
      node.textContent.includes("Supporting property records"),
    );
    assert.ok(appendix);
    assert.equal(appendix.open, false);
    assert.ok(appendix.querySelector("table"));
  });
});

// Chemical names below are synthetic display fixtures, never scientific evidence.
const chemicalNameFixture = (patch = {}) => ({
  kind: "material",
  id: "fixture-record",
  formula: "O2Si",
  name: "Synthetic silica name",
  url: "https://example.com/name-source",
  source_name: "Synthetic name source",
  ...patch,
});
function namedReport() {
  const report = structuredReport();
  report.result.report_tables.technical.rows[0].formula = "SiO2";
  return report;
}

test("optional chemical name metadata has bounded text, exact IDs, flat formulas and public HTTPS provenance", async () => {
  const {
    parseMaterialNames,
    parseChemicalNamesResponse,
    chemicalFormulaSignature,
  } = await import(pathToFileURL(join(output, "chemicalNamesApi.js")).href);
  const { parsePresentedReport } = await import(
    pathToFileURL(join(output, "reportPresentationApi.js")).href
  );
  const name = chemicalNameFixture(),
    report = namedReport();
  assert.deepEqual(parseMaterialNames([name]), [name]);
  assert.equal(
    chemicalFormulaSignature("SiO2"),
    chemicalFormulaSignature("O2Si1"),
  );
  assert.notEqual(
    chemicalFormulaSignature("SiO2"),
    chemicalFormulaSignature("Si2O4"),
    "do not reduce distinct saved compositions",
  );
  for (const patch of [
    { kind: "rank" },
    { kind: "lead", id: "1" },
    { id: "" },
    { id: "x".repeat(161) },
    { name: "" },
    { name: "x".repeat(201) },
    { name: "name\nsecond line" },
    { name: "name\u202Ehidden" },
    { source_name: "x".repeat(121) },
    { formula: "Ca(OH)2" },
    { formula: "H0O" },
    { formula: "XxO2" },
    { formula: "SiO2·H2O" },
    { extra: true },
  ]) {
    assert.throws(
      () => parseMaterialNames([{ ...name, ...patch }]),
      /unavailable/,
    );
  }
  for (const url of [
    "javascript:alert(1)",
    "http://example.com/name",
    "https://localhost/name",
    "https://127.0.0.1/name",
    "https://10.0.0.1/name",
    "https://[::ffff:127.0.0.1]/name",
    "https://user:pass@example.com/",
    "https://example.com:8443/name",
  ]) {
    assert.throws(() => parseMaterialNames([{ ...name, url }]), /unavailable/);
  }
  assert.throws(() => parseMaterialNames([name, name]), /unavailable/);
  assert.throws(() => parseMaterialNames(Array(113).fill(name)), /unavailable/);
  assert.throws(
    () =>
      parseChemicalNamesResponse(
        { chat_id: report.chat_id, report_id: "other", material_names: [name] },
        report.chat_id,
        report.id,
      ),
    /unavailable/,
  );
  const presentation = presentationFixture(report);
  const parsed = parsePresentedReport(
    { ...presentation, material_names: [{ ...name, url: "javascript:bad" }] },
    report.chat_id,
    report.id,
    "saved",
  );
  assert.deepEqual(parsed.material_names, []);
  assert.equal(
    parsed.pi_summary,
    report.pi_summary,
    "bad optional names never hide the report",
  );
});

test("chemical names appear beneath the same typed formulas in both views without changing saved data", async () => {
  const report = namedReport(),
    before = JSON.stringify(report),
    name = chemicalNameFixture();
  await withReportDom(async ({ document, render }) => {
    for (const view of ["pi", "audit"]) {
      await render(
        view === "pi" ? report.pi_summary : report.technical_audit,
        view,
        {
          table:
            report.result.report_tables[
              view === "pi" ? "summary" : "technical"
            ],
          materialNames: [name],
          structureScope: { chatId: report.chat_id, reportId: report.id },
        },
      );
      const cell = document.querySelector("td.report-column-identity"),
        label = cell.querySelector(".report-chemical-name");
      assert.equal(
        cell.querySelector(".material-formula").getAttribute("aria-label"),
        "SiO2",
      );
      assert.match(label.textContent, /^Synthetic silica name/);
      assert.equal(label.querySelector("a").href, name.url);
      assert.match(label.querySelector("a").title, /does not verify the phase/);
      assert.equal(label.querySelector("a").rel, "noopener noreferrer");
      assert.equal(
        document.querySelectorAll(".report-chemical-name").length,
        1,
      );
    }
    for (const metadata of [
      [{ ...name, id: "foreign-record" }],
      [{ ...name, formula: "Si2O4" }],
      [{ ...name, name: "SiO2" }],
      [],
    ]) {
      await render(report.pi_summary, "pi", {
        table: report.result.report_tables.summary,
        materialNames: metadata,
      });
      assert.equal(document.querySelector(".report-chemical-name"), null);
    }
  });
  assert.equal(JSON.stringify(report), before);
});

test("literature names require the cited saved lead identity, independent of tied ranks and formula order", async () => {
  const fixture = await leadFixture(),
    lead = structuredClone(fixture.leads[0]);
  lead.name = "O2Si";
  const reference = fixture.references.find((item) => item.url === lead.url);
  const header =
    "| Rank | Material | Screening priority | Why considered | Attribute evidence | Stability / key caveat |\n| --- | --- | --- | --- | --- | --- |";
  const content = `Candidate shortlist:\n${header}\n| 1 | SiO2 [${reference.id}] | 50% · Assessed review priority | Synthetic fixture | Unknown | Unknown |`;
  const name = chemicalNameFixture({ kind: "lead", id: lead.id });
  await withReportDom(async ({ document, render }) => {
    for (const view of ["pi", "audit"]) {
      await render(content, view, {
        candidateLeads: [lead],
        references: fixture.references,
        materialNames: [name],
        structureScope: { chatId: "fixture-chat", reportId: "fixture-report" },
      });
      assert.equal(
        document.querySelectorAll(".report-chemical-name").length,
        1,
      );
      assert.equal(
        document.querySelector("td:nth-child(2) .material-formula").textContent,
        "SiO2",
      );
    }
    await render(content, "pi", {
      candidateLeads: [lead],
      references: fixture.references,
      materialNames: [{ ...name, id: "lead-" + "f".repeat(24) }],
    });
    assert.equal(document.querySelector(".report-chemical-name"), null);
    await render(content, "pi", {
      candidateLeads: [lead, { ...lead, id: "lead-" + "f".repeat(24) }],
      references: fixture.references,
      materialNames: [name],
    });
    assert.equal(
      document.querySelector(".report-chemical-name"),
      null,
      "ambiguous identical cited formulas never choose a lead ID",
    );
  });
});

test("lead table names render escaped source text without changing strict saved lead metadata", async () => {
  const fixture = await leadFixture(),
    leads = structuredClone(fixture.leads.slice(0, 1));
  leads[0].name = "SiO2";
  const { candidateLeadCells } = await import(
    pathToFileURL(join(output, "CandidateLeadTable.js")).href
  );
  const headers = [
    "Review order",
    "Candidate",
    "Source",
    "Supporting quote",
    "Missing measurements",
  ];
  const payload = "<img src=x onerror=alert(1)> name";
  const metadata = [
    chemicalNameFixture({
      kind: "lead",
      id: leads[0].id,
      name: payload,
      source_name: "<script>literal source</script>",
    }),
  ];
  const before = JSON.stringify(leads);
  await withReportDom(async ({ document, render }) => {
    for (const view of ["pi", "audit"]) {
      const cells = candidateLeadCells(leads, view, fixture.references);
      const content = `| ${headers.join(" | ")} |\n| ${headers.map(() => "---").join(" | ")} |\n${cells.map((row) => "| " + row.join(" | ") + " |").join("\n")}`;
      await render(content, view, {
        candidateLeads: leads,
        references: fixture.references,
        materialNames: metadata,
      });
      assert.ok(document.querySelector(".report-lead-table"));
      assert.ok(
        document
          .querySelector(".report-chemical-name")
          .textContent.includes(payload),
      );
      assert.equal(
        document.querySelectorAll("img, script, [onerror]").length,
        0,
      );
    }
  });
  assert.equal(JSON.stringify(leads), before);
});

test("ReportCard shows offline names immediately and reuses one bounded CSRF lookup across view switches", async (t) => {
  const report = namedReport(),
    before = JSON.stringify(report),
    name = chemicalNameFixture(),
    calls = [];
  let finish;
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    if (path.includes("/presentation?"))
      return Response.json({
        ...presentationFixture(report, "current"),
        material_names: [name],
      });
    if (path === "/api/session")
      return Response.json({ csrf_token: "TEST_CHEMICAL_NAME_CSRF_TOKEN" });
    assert.ok(path.endsWith("/chemical-names"));
    return new Promise((resolve) => {
      finish = resolve;
    });
  });
  await withReportDom(async ({ document, renderCard, click }) => {
    await renderCard(report);
    assert.match(
      document.querySelector(".report-chemical-name").textContent,
      /Synthetic silica name/,
    );
    assert.equal(
      document.querySelector(".report-reformat-note"),
      null,
      "optional name lookup never delays report rendering",
    );
    assert.equal(
      document
        .querySelector(".report-download-link")
        .getAttribute("aria-disabled"),
      "false",
    );
    for (const name of ["Summary", "Technical View", "Summary"])
      await click(
        [...document.querySelectorAll(".report-tabs button")].find(
          (button) => button.textContent === name,
        ),
      );
    const lookups = calls.filter(({ path }) =>
      path.endsWith("/chemical-names"),
    );
    assert.equal(lookups.length, 1);
    assert.equal(lookups[0].options.method, "POST");
    assert.deepEqual(JSON.parse(lookups[0].options.body), {});
    assert.equal(
      lookups[0].options.headers["X-CSRF-Token"],
      "TEST_CHEMICAL_NAME_CSRF_TOKEN",
    );
    const { act } = await import("react");
    await act(async () =>
      finish(
        Response.json({
          chat_id: report.chat_id,
          report_id: report.id,
          material_names: [{ ...name, name: "Synthetic resolved name" }],
        }),
      ),
    );
    assert.match(
      document.querySelector(".report-chemical-name").textContent,
      /Synthetic resolved name/,
    );
    await click(
      [...document.querySelectorAll(".report-tabs button")].find(
        (button) => button.textContent === "Technical View",
      ),
    );
    assert.match(
      document.querySelector(".report-chemical-name").textContent,
      /Synthetic resolved name/,
    );
    assert.equal(
      calls.filter(({ path }) => path.endsWith("/chemical-names")).length,
      1,
    );
  });
  assert.equal(JSON.stringify(report), before);
});

test("late chemical names are aborted and cannot leak into another report with the same candidate ID", async (t) => {
  const first = namedReport(),
    second = namedReport();
  second.id = "second-names-report";
  let finish, oldSignal;
  t.mock.method(globalThis, "fetch", async (path, options) => {
    if (path === "/api/session")
      return Response.json({ csrf_token: "TEST_CHEMICAL_NAME_CSRF_TOKEN" });
    const report = path.includes("/second-names-report/") ? second : first;
    if (path.includes("/presentation?"))
      return Response.json({
        ...presentationFixture(report, "current"),
        material_names: [
          chemicalNameFixture({
            name:
              report === first ? "First offline name" : "Second offline name",
          }),
        ],
      });
    if (report === first) {
      oldSignal = options.signal;
      return new Promise((resolve) => {
        finish = resolve;
      });
    }
    return Response.json({
      chat_id: second.chat_id,
      report_id: second.id,
      material_names: [],
    });
  });
  await withReportDom(async ({ document, renderCard }) => {
    await renderCard(first);
    assert.match(
      document.querySelector(".report-chemical-name").textContent,
      /First offline/,
    );
    await renderCard(second);
    assert.equal(oldSignal.aborted, true);
    assert.match(
      document.querySelector(".report-chemical-name").textContent,
      /Second offline/,
    );
    const { act } = await import("react");
    await act(async () =>
      finish(
        Response.json({
          chat_id: first.chat_id,
          report_id: first.id,
          material_names: [
            chemicalNameFixture({ name: "Forbidden late name" }),
          ],
        }),
      ),
    );
    assert.match(
      document.querySelector(".report-chemical-name").textContent,
      /Second offline/,
    );
    assert.doesNotMatch(document.body.textContent, /Forbidden late name/);
  });
});

test("failed optional name lookup silently preserves offline labels and usable report controls", async (t) => {
  const report = namedReport();
  let lookupCount = 0;
  t.mock.method(globalThis, "fetch", async (path) => {
    if (path.includes("/presentation?"))
      return Response.json({
        ...presentationFixture(report, "current"),
        material_names: [chemicalNameFixture()],
      });
    if (path === "/api/session")
      return Response.json({ csrf_token: "TEST_CHEMICAL_NAME_CSRF_TOKEN" });
    lookupCount++;
    return Response.json({}, { status: 503 });
  });
  await withReportDom(async ({ document, renderCard, click }) => {
    await renderCard(report);
    assert.match(
      document.querySelector(".report-chemical-name").textContent,
      /Synthetic silica name/,
    );
    assert.equal(
      document.querySelector('[role="alert"], .report-reformat-note'),
      null,
    );
    assert.equal(
      document
        .querySelector(".report-download-link")
        .getAttribute("aria-disabled"),
      "false",
    );
    await click(
      [...document.querySelectorAll(".report-tabs button")].find(
        (button) => button.textContent === "Summary",
      ),
    );
    assert.equal(lookupCount, 1);
  });
});

test("name transport has a total 20-second abort deadline and sends nothing after pre-abort or invalid CSRF", async (t) => {
  const { chemicalNamesApi } = await import(
    pathToFileURL(join(output, "chemicalNamesApi.js")).href
  );
  await withReportDom(async () => {
    let timeout,
      cleared = 0;
    t.mock.method(window, "setTimeout", (callback, milliseconds) => {
      assert.equal(milliseconds, 20000);
      timeout = callback;
      return 17;
    });
    t.mock.method(window, "clearTimeout", (id) => {
      assert.equal(id, 17);
      cleared++;
    });
    const calls = [];
    t.mock.method(globalThis, "fetch", async (path, options) => {
      calls.push(path);
      return new Promise((_resolve, reject) =>
        options.signal.addEventListener(
          "abort",
          () => reject(new Error("aborted")),
          { once: true },
        ),
      );
    });
    const pending = chemicalNamesApi.load(
      "chat-a",
      "report-a",
      new AbortController().signal,
    );
    timeout();
    await assert.rejects(pending, /aborted/);
    assert.equal(cleared, 1);
    assert.deepEqual(
      calls,
      ["/api/session"],
      "timeout during session read prevents POST",
    );
    const controller = new AbortController();
    controller.abort();
    await assert.rejects(
      chemicalNamesApi.load("chat-a", "report-a", controller.signal),
    );
    assert.equal(calls.length, 1);
    globalThis.fetch = async (path) => {
      calls.push(path);
      return Response.json({ csrf_token: "bad" });
    };
    await assert.rejects(
      chemicalNamesApi.load("chat-a", "report-a", new AbortController().signal),
    );
    assert.deepEqual(calls, ["/api/session", "/api/session"]);
  });
});

test("closed earlier-report history does not start optional lookups until opened", async (t) => {
  const report = namedReport();
  let lookups = 0;
  t.mock.method(globalThis, "fetch", async (path) => {
    if (path.includes("/presentation?"))
      return Response.json({
        ...presentationFixture(report, "current"),
        material_names: [],
      });
    if (path === "/api/session")
      return Response.json({ csrf_token: "TEST_CHEMICAL_NAME_CSRF_TOKEN" });
    lookups++;
    return Response.json({
      chat_id: report.chat_id,
      report_id: report.id,
      material_names: [chemicalNameFixture()],
    });
  });
  await withReportDom(async ({ document, renderHiddenCard }) => {
    await renderHiddenCard(report);
    assert.equal(lookups, 0);
    const history = document.querySelector(".earlier-history");
    const { act } = await import("react");
    await act(async () => {
      history.open = true;
      history.dispatchEvent(new window.Event("toggle"));
    });
    assert.equal(lookups, 1);
    assert.ok(document.querySelector(".report-chemical-name"));
    await act(async () => {
      history.open = false;
      history.dispatchEvent(new window.Event("toggle"));
    });
    await act(async () => {
      history.open = true;
      history.dispatchEvent(new window.Event("toggle"));
    });
    assert.equal(lookups, 1, "reopening the same report reuses its names");
  });
});

test("technical properties retain compact shortlist dimensions, exact source context and missing values", async () => {
  const fixture = await leadFixture();
  const reference = fixture.references[0];
  const quote =
    "TEST ONLY: Fixture-A has a measured optical band gap of 1.72 eV, while its simulated device efficiency is 34%. " +
    "Synthetic context is preserved for reviewing sample and method. ".repeat(
      4,
    );
  const properties = `Band gap — Source passage: “${quote}” [${reference.id}] ▪ Operational stability — Not reported ▪ Density — Not reported`;
  const content = `Candidate shortlist:
| Rank | Material | Screening priority | Why considered | Relevant properties | Stability / key caveat |
| --- | --- | --- | --- | --- | --- |
| 1 | Fixture-A [${reference.id}] | 78% · Assessed review priority | Source discussion | ${properties} | Stability unknown |`;
  await withReportDom(async ({ document, render }) => {
    await render(content, "audit", { references: [reference] });
    const table = document.querySelector(".report-literature-table");
    assert.ok(table);
    assert.equal(table.querySelectorAll("thead th").length, 6);
    assert.equal(table.querySelectorAll("tbody td").length, 6);
    assert.equal(
      table.querySelectorAll(".report-relevant-properties li").length,
      3,
    );
    assert.deepEqual(
      [
        ...table.querySelectorAll(".report-relevant-properties li > strong"),
      ].map((x) => x.textContent),
      ["Band gap", "Operational stability", "Density"],
    );
    assert.match(
      table.querySelector(".report-property-excerpt").textContent,
      /1.72 eV/,
    );
    const details = table.querySelector(".report-relevant-properties details");
    assert.equal(details.open, false);
    assert.ok(details.textContent.includes(quote));
    assert.equal(details.querySelector("a").href, reference.url);
    assert.equal(
      table.querySelectorAll(".report-screening-priority").length,
      1,
    );
    assert.equal(
      table.querySelectorAll(".report-relevant-properties li").item(1)
        .textContent,
      "Operational stabilityNot reported",
    );
    const className = table.className;
    await render(
      content
        .replace("Relevant properties", "Attribute evidence")
        .replace(properties, "0% assessed"),
      "pi",
    );
    assert.equal(
      document.querySelector(".report-literature-table").className,
      className,
    );
    assert.equal(
      document.querySelectorAll(".report-relevant-properties").length,
      0,
    );
    await render(
      content.replace(quote, "<img src=x onerror=alert(1)>"),
      "audit",
    );
    assert.equal(document.querySelectorAll("img, script").length, 0);
    assert.match(document.body.textContent, /<img src=x onerror=alert/);
  });
});

test("fractional composition stays intact in candidate headings", async () => {
  const formula = "Cs0.22FA0.78Pb(I0.85Br0.15)3";
  await withReportDom(async ({ document, render }) => {
    await render(
      `Candidate 1 — ${formula}:\n\nSource-bound discussion.`,
      "audit",
    );
    assert.equal(
      document.querySelector("h4").textContent,
      `Candidate 1 — ${formula}`,
    );
  });
});

test("component name metadata retains separate citations and rejects mismatched parent positions", async () => {
  const { parseMaterialNames, chemicalComponentFormulas } = await import(
    pathToFileURL(join(output, "chemicalNamesApi.js")).href
  );
  const first = chemicalNameFixture({
    kind: "lead",
    id: "lead-" + "a".repeat(24),
    formula: "InAs",
    name: "Fixture arsenide",
    parent_formula: "InAs/ZnSe",
    component_index: 1,
  });
  const second = {
    ...first,
    formula: "ZnSe",
    name: "Fixture selenide",
    component_index: 2,
    url: "https://example.com/second-name-source",
  };
  assert.deepEqual(parseMaterialNames([first, second]), [first, second]);
  assert.deepEqual(chemicalComponentFormulas("CuInS ₂∕ZnS"), ["CuInS2", "ZnS"]);
  for (const formula of ["CdSe/C", "PI/ZnS", "NO/ZnS", "CDs/ZnS"])
    assert.deepEqual(chemicalComponentFormulas(formula), []);
  for (const patch of [
    { component_index: 0 },
    { component_index: 3 },
    { component_index: 1.5 },
    { component_index: "1" },
    { parent_formula: "ZnSe/InAs" },
    { parent_formula: "InAs/C" },
    { kind: "material" },
    { parent_formula: undefined },
  ]) {
    assert.throws(
      () => parseMaterialNames([{ ...first, ...patch }]),
      /unavailable/,
    );
  }
  assert.throws(() => parseMaterialNames([first, first]), /unavailable/);
});

test("compound shortlist rows show independently sourced component names with partial lookup support", async () => {
  const fixture = await leadFixture(),
    lead = structuredClone(fixture.leads[0]);
  lead.name = "InAs/ZnSe";
  const reference = fixture.references.find((item) => item.url === lead.url);
  const header =
    "| Rank | Material | Screening priority | Why considered | Attribute evidence | Stability / key caveat |\n| --- | --- | --- | --- | --- | --- |";
  const content = `Candidate shortlist:\n${header}\n| 1 | InAs/ZnSe [${reference.id}] | 50% · Assessed review priority | Synthetic fixture | Unknown | Unknown |`;
  const first = chemicalNameFixture({
    kind: "lead",
    id: lead.id,
    formula: "InAs",
    name: "Fixture arsenide",
    parent_formula: lead.name,
    component_index: 1,
  });
  const second = {
    ...first,
    formula: "ZnSe",
    name: "Fixture selenide",
    component_index: 2,
    url: "https://example.com/second-name-source",
  };
  await withReportDom(async ({ document, render }) => {
    for (const view of ["pi", "audit"]) {
      await render(content, view, {
        candidateLeads: [lead],
        references: fixture.references,
        materialNames: [second, first],
        structureScope: { chatId: "fixture-chat", reportId: "fixture-report" },
      });
      const labels = [...document.querySelectorAll(".report-chemical-name")];
      assert.equal(labels.length, 2);
      assert.match(labels[0].textContent, /^InAs: Fixture arsenide/);
      assert.match(labels[1].textContent, /^ZnSe: Fixture selenide/);
      assert.equal(labels[0].querySelector("a").href, first.url);
      assert.equal(labels[1].querySelector("a").href, second.url);
      assert.match(labels[0].querySelector("a").title, /component composition/);
      assert.doesNotMatch(
        labels.map((label) => label.textContent).join(" "),
        /core|shell/i,
      );
    }
    await render(content, "pi", {
      candidateLeads: [lead],
      references: fixture.references,
      materialNames: [second],
    });
    assert.equal(document.querySelectorAll(".report-chemical-name").length, 1);
    for (const bad of [
      { ...first, parent_formula: "ZnSe/InAs" },
      { ...first, id: "lead-" + "f".repeat(24) },
      { ...first, formula: "CdS" },
    ]) {
      await render(content, "pi", {
        candidateLeads: [lead],
        references: fixture.references,
        materialNames: [bad],
      });
      assert.equal(document.querySelector(".report-chemical-name"), null);
    }
  });
});
