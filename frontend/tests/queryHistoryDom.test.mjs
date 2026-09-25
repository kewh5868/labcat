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
  output = await mkdtemp(join(tmpdir(), "labcat-query-history-"));
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

const module = (name) => import(pathToFileURL(join(output, `${name}.js`)).href);
// Synthetic renderer and lifecycle fixtures only; these establish no scientific facts.
const times = [
  "2026-09-23T11:00:00Z",
  "2026-09-23T11:03:00Z",
  "2026-09-23T11:09:00Z",
];
const message = (id, role, content, index = 0, report_id = null) => ({
  id,
  role,
  content,
  chat_id: "synthetic-chat",
  created_at: times[index],
  report_id,
});
const headers = [
  "Rank",
  "Material",
  "Screening priority",
  "Why considered",
  "Attribute evidence",
  "Stability / key caveat",
];
const table = (names, ranks = names.map((_name, index) => String(index + 1))) =>
  [
    `| ${headers.join(" | ")} |`,
    `| ${headers.map(() => "---").join(" | ")} |`,
    ...names.map(
      (name, index) =>
        `| ${ranks[index]} | ${name} | ${90 - index * 10}% · Assessed review priority | Synthetic context | Not reported | Test-only caveat |`,
    ),
  ].join("\n");
const report = (id, assistantId, content, index = 0) => ({
  id,
  message_id: assistantId,
  chat_id: "synthetic-chat",
  project_id: null,
  title: `Synthetic report ${id}`,
  stage: "partial",
  pi_summary: content,
  technical_audit: `Technical View:\n\n${content}`,
  source_ids: [],
  created_at: times[index],
  pinned: false,
});
const firstQuestion = message(
  "question-one",
  "user",
  "First synthetic question: compare fixture candidates.",
);
const secondQuestion = message(
  "question-two",
  "user",
  "Follow-up: change the synthetic priorities.",
  1,
);
const thirdQuestion = message(
  "question-three",
  "user",
  "Another follow-up: review the latest fixture only.",
  2,
);
const firstAnswer = message(
  "answer-one",
  "assistant",
  "Original first response fixture.",
  0,
  "report-one",
);
const secondAnswer = message(
  "answer-two",
  "assistant",
  "Original second response fixture.",
  1,
  "report-two",
);
const thirdAnswer = message(
  "answer-three",
  "assistant",
  "Original third response fixture.",
  2,
  "report-three",
);
const firstReport = report(
  "report-one",
  firstAnswer.id,
  table(
    ["Earlier-A [S1]", "Earlier-B [S2]", "Earlier-C [S3]", "Earlier-D [S4]"],
    ["1", "1", "3", "4"],
  ),
);
const secondReport = report(
  "report-two",
  secondAnswer.id,
  table(["Middle-A [S1]", "Middle-B [S2]"]),
  1,
);
const thirdReport = report(
  "report-three",
  thirdAnswer.id,
  table(["Latest-only-A [S1]"]),
  2,
);
const allMessages = [
  firstQuestion,
  firstAnswer,
  secondQuestion,
  secondAnswer,
  thirdQuestion,
  thirdAnswer,
];
const allReports = [firstReport, secondReport, thirdReport];

async function environment(check) {
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
  const { default: QueryHistory, queryHistory } = await module("QueryHistory");
  let root = createRoot(document.getElementById("root"));
  const reportsRendered = [],
    messagesRendered = [];
  const renderReport = (value) => {
    reportsRendered.push(value.id);
    return createElement(
      "section",
      { "data-full-report": value.id },
      value.pi_summary,
    );
  };
  const renderMessage = (value) => {
    messagesRendered.push(value.id);
    return createElement(
      "p",
      { "data-original-message": value.id },
      value.content,
    );
  };
  const render = async (turns, options = {}) =>
    act(async () =>
      root.render(
        createElement(QueryHistory, {
          turns,
          renderReport,
          renderMessage,
          ...options,
        }),
      ),
    );
  try {
    await check({
      dom,
      act,
      createElement,
      queryHistory,
      render,
      reportsRendered,
      messagesRendered,
      renderNode: async (node) => act(async () => root.render(node)),
      remountNode: async (node) => {
        await act(async () => root.unmount());
        root = createRoot(document.getElementById("root"));
        await act(async () => root.render(node));
      },
      click: async (element) => {
        assert.ok(element, "disclosure exists");
        await act(async () => {
          element.click();
        });
      },
      toggle: async (details, open) => {
        assert.ok(details, "disclosure exists");
        await act(async () => {
          details.open = open;
          details.dispatchEvent(new dom.window.Event("toggle"));
        });
      },
      remount: async (turns, options = {}) => {
        await act(async () => root.unmount());
        root = createRoot(document.getElementById("root"));
        await render(turns, options);
      },
    });
  } finally {
    await act(async () => root.unmount());
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
  }
}

test("query turns retain each original question, assistant exchange and own saved report in message order", async () => {
  const { queryHistory } = await module("QueryHistory");
  const untouched = JSON.stringify({
    messages: allMessages,
    reports: allReports,
  });
  const turns = queryHistory(allMessages, [...allReports].reverse());
  assert.deepEqual(
    turns.map((turn) => turn.question.id),
    ["question-one", "question-two", "question-three"],
  );
  assert.deepEqual(
    turns.map((turn) => turn.responses.map((response) => response.id)),
    [["answer-one"], ["answer-two"], ["answer-three"]],
  );
  assert.deepEqual(
    turns.map((turn) => turn.reports.map((value) => value.id)),
    [["report-one"], ["report-two"], ["report-three"]],
  );
  assert.equal(
    JSON.stringify({ messages: allMessages, reports: allReports }),
    untouched,
    "grouping leaves saved state intact",
  );
});

test("report association requires the saved assistant link and report message ownership", async () => {
  const { queryHistory } = await module("QueryHistory");
  const orphan = message(
    "orphan-answer",
    "assistant",
    "Unattached response.",
    0,
    "orphan-report",
  );
  const mismatch = { ...firstReport, message_id: secondAnswer.id };
  const turns = queryHistory(
    [orphan, firstQuestion, firstAnswer, secondQuestion, secondAnswer],
    [
      report("orphan-report", orphan.id, table(["Orphan"])),
      mismatch,
      secondReport,
      report("unlinked", firstAnswer.id, table(["Unlinked"])),
    ],
  );
  assert.equal(
    turns.length,
    2,
    "orphan assistant content is not invented into a user question",
  );
  assert.deepEqual(
    turns[0].reports,
    [],
    "a matching report id alone is insufficient",
  );
  assert.deepEqual(
    turns[1].reports.map((value) => value.id),
    ["report-two"],
  );
  assert.deepEqual(
    turns[0].responses.map((value) => value.id),
    ["answer-one"],
  );
});

test("foreign-chat responses and reports cannot attach their findings to this chat question", async () => {
  const { queryHistory } = await module("QueryHistory");
  const foreignAnswer = { ...secondAnswer, chat_id: "different-chat" };
  const foreignReport = { ...secondReport, chat_id: "different-chat" };
  const turns = queryHistory(
    [firstQuestion, foreignAnswer, firstAnswer],
    [foreignReport, { ...firstReport, chat_id: "different-chat" }],
  );
  assert.equal(turns.length, 1);
  assert.deepEqual(
    turns[0].responses.map((value) => value.id),
    [firstAnswer.id],
  );
  assert.deepEqual(turns[0].reports, []);
});

test("shortlist previews preserve source order, rank ties and total count without mixing later tables", async () => {
  const { shortlistPreview } = await module("ReportContent");
  const preview = shortlistPreview(
    `${firstReport.pi_summary}\n\nLater shortlist:\n${thirdReport.pi_summary}`,
  );
  assert.ok(preview);
  assert.equal(preview.total, 4);
  assert.deepEqual(preview.headers.slice(0, 2), ["Rank", "Material"]);
  assert.deepEqual(
    preview.rows.map((row) => row.slice(0, 2)),
    [
      ["1", "Earlier-A [S1]"],
      ["1", "Earlier-B [S2]"],
      ["3", "Earlier-C [S3]"],
    ],
  );
  const unsorted = shortlistPreview(
    table(["Saved-first", "Saved-second"], ["2", "1"]),
  );
  assert.deepEqual(
    unsorted.rows.map((row) => row[1]),
    ["Saved-first", "Saved-second"],
    "history must not recalculate the saved order",
  );
});

test("previews accept supported report formats and reject unrelated or malformed tables", async () => {
  const { shortlistPreview } = await module("ReportContent");
  for (const [header, cells] of [
    [
      [
        "Provisional rank",
        "Material",
        "Literature fit",
        "Selected criterion assessments",
        "Assessment coverage",
        "Stability & uncertainty",
      ],
      [
        "1",
        "Literature fixture",
        "Supported fit",
        "Test assessment",
        "0%",
        "Unknown",
      ],
    ],
    [
      ["Rank", "Material (record)", "Score", "Leading criteria", "Key caveat"],
      ["1", "Supported fixture", "0.5", "Test criterion", "Unknown"],
    ],
    [
      [
        "Review order",
        "Candidate",
        "Source",
        "Supporting quote",
        "Missing measurements",
      ],
      ["1", "Lead fixture", "Synthetic source", "Literal quote", "Unknown"],
    ],
  ]) {
    const text = `| ${header.join(" | ")} |\n| ${header.map(() => "---").join(" | ")} |\n| ${cells.join(" | ")} |`;
    const preview = shortlistPreview(text);
    assert.ok(preview, `saved format ${header[0]} is supported`);
    assert.equal(preview.total, 1);
    assert.deepEqual(preview.rows[0].slice(0, 2), cells.slice(0, 2));
  }
  for (const text of [
    "No saved shortlist for this exchange.",
    "| Step | Result |\n| --- | --- |\n| Retrieve | No evidence |",
    `${table(["Fixture"])}\n| malformed |`,
    `\`\`\`text\n${table(["Literal-only"])}\n\`\`\``,
  ])
    assert.equal(
      shortlistPreview(text),
      null,
      "non-shortlist text must not become candidate evidence",
    );
});

test("earlier questions keep timestamps and compact original shortlists after follow-ups and remount", async () =>
  environment(async ({ queryHistory, render, remount, reportsRendered }) => {
    await render(queryHistory(allMessages.slice(0, 4), allReports.slice(0, 2)));
    assert.match(document.body.textContent, /First synthetic question/);
    assert.match(document.body.textContent, /Follow-up: change/);
    await render(queryHistory(allMessages, allReports));
    for (const question of [firstQuestion, secondQuestion, thirdQuestion]) {
      assert.ok(document.body.textContent.includes(question.content));
      assert.ok(
        [...document.querySelectorAll("time")].some(
          (time) => time.getAttribute("datetime") === question.created_at,
        ),
        "query timestamp is machine-readable and visible",
      );
    }
    assert.deepEqual(
      [...document.querySelectorAll("tbody")].map((body) =>
        [...body.querySelectorAll("tr")].map(
          (row) => row.querySelectorAll("td")[1]?.textContent,
        ),
      ),
      [
        ["Earlier-A [S1]", "Earlier-B [S2]", "Earlier-C [S3]"],
        ["Middle-A [S1]", "Middle-B [S2]"],
        ["Latest-only-A [S1]"],
      ],
    );
    assert.ok(
      !document.body.textContent.includes("Earlier-D"),
      "a small preview does not render every older candidate",
    );
    assert.deepEqual(
      reportsRendered,
      [],
      "collapsed history never loads full report controls",
    );
    await remount(queryHistory(allMessages, allReports));
    assert.equal(
      document.querySelectorAll("tbody").length,
      3,
      "stored queries reappear after returning to the chat",
    );
    assert.equal(document.querySelectorAll("time").length, 3);
    assert.deepEqual(reportsRendered, []);
  }));

test("opening a saved report mounts only that original report and retains its original response", async () =>
  environment(async ({ queryHistory, render, toggle, reportsRendered }) => {
    await render(queryHistory(allMessages, allReports));
    const disclosures = document.querySelectorAll(".query-full-report");
    assert.equal(disclosures.length, 3);
    assert.deepEqual(reportsRendered, []);
    await toggle(disclosures[0], true);
    assert.equal(
      document.querySelector('[data-full-report="report-one"]')?.textContent,
      firstReport.pi_summary,
    );
    assert.equal(
      document.querySelector('[data-original-message="answer-one"]')
        ?.textContent,
      firstAnswer.content,
    );
    assert.equal(
      document.querySelector('[data-full-report="report-two"]'),
      null,
    );
    assert.equal(
      document.querySelector('[data-full-report="report-three"]'),
      null,
    );
    assert.ok(
      !disclosures[0].textContent.includes("Latest-only-A"),
      "latest findings never leak into an old question",
    );
    assert.ok(reportsRendered.every((id) => id === "report-one"));
    await toggle(disclosures[0], false);
    assert.equal(
      document.querySelector("[data-full-report]"),
      null,
      "closing the exchange releases inactive full report controls",
    );
  }));

test("searching an archived report opens the matching exchange without opening unrelated reports", async () =>
  environment(async ({ queryHistory, render }) => {
    await render(queryHistory(allMessages, allReports), {
      searchReportId: secondReport.id,
    });
    assert.equal(
      document.querySelector('[data-full-report="report-two"]')?.textContent,
      secondReport.pi_summary,
    );
    assert.equal(
      document.querySelector('[data-full-report="report-one"]'),
      null,
    );
    assert.equal(
      document.querySelector('[data-full-report="report-three"]'),
      null,
    );
    const opened = [...document.querySelectorAll("details")].filter(
      (details) => details.open,
    );
    assert.equal(opened.length, 1);
    assert.ok(opened[0].textContent.includes(secondReport.pi_summary));
  }));

test("clarification, no-result and unfinished queries retain their own question without invented candidate rows", async () =>
  environment(async ({ queryHistory, render, toggle }) => {
    const question = message(
      "clarification-question",
      "user",
      "A synthetic request needing clarification.",
    );
    const answer = message(
      "clarification-answer",
      "assistant",
      "Which synthetic application should be compared?",
    );
    const noResultQuestion = message(
      "empty-question",
      "user",
      "Synthetic empty retrieval.",
      1,
    );
    const noResultAnswer = message(
      "empty-answer",
      "assistant",
      "No accepted candidates from this synthetic fixture.",
      1,
      "empty-report",
    );
    const unfinished = message(
      "pending-question",
      "user",
      "Synthetic question still running.",
      2,
    );
    await render(
      queryHistory(
        [question, answer, noResultQuestion, noResultAnswer, unfinished],
        [
          report(
            "empty-report",
            noResultAnswer.id,
            "Summary:\n\nNo candidates in this synthetic test.",
            1,
          ),
        ],
      ),
    );
    assert.equal(document.querySelector("tbody"), null);
    for (const item of [question, noResultQuestion, unfinished])
      assert.ok(document.body.textContent.includes(item.content));
    const details = [...document.querySelectorAll(".query-original-messages")];
    await toggle(details[0], true);
    assert.match(document.body.textContent, /Which synthetic application/);
    assert.ok(!document.body.textContent.includes("Earlier-A"));
  }));

test("question and saved preview markup stays literal without scripts, links or injected elements", async () =>
  environment(async ({ queryHistory, render }) => {
    const payload = '<img src=x onerror="alert(1)"> <script>danger()</script>';
    const question = message(
      "literal-question",
      "user",
      `Synthetic literal request ${payload}`,
    );
    const answer = message(
      "literal-answer",
      "assistant",
      "Synthetic safe response.",
      0,
      "literal-report",
    );
    const saved = report(
      "literal-report",
      answer.id,
      table([`${payload} [S1] [click](javascript:alert(1))`]),
    );
    await render(queryHistory([question, answer], [saved]));
    assert.ok(document.body.textContent.includes(payload));
    assert.equal(
      document.querySelector('script, img, iframe, a[href^="javascript:"]'),
      null,
    );
    assert.equal(
      document.querySelector("tbody td:nth-child(2)").textContent,
      `${payload} [S1] [click](javascript:alert(1))`,
    );
  }));

test("workspace follow-ups replace the main report while keeping prior query previews after navigation and reload", async (t) =>
  environment(
    async ({
      dom,
      act,
      createElement,
      renderNode,
      remountNode,
      click,
      toggle,
    }) => {
      const { default: Workspace } = await module("ProjectWorkspace");
      const { ConnectionsProvider } = await module("Connections");
      const { SetupProvider } = await module("SetupWizard");
      const { defaultSettings } = await module("workspaceApi");
      const chat = {
        id: "synthetic-chat",
        project_id: null,
        title: "Synthetic query history",
        chat_number: 1,
        display_title: "Synthetic query history · #1",
        created_at: times[0],
        updated_at: times[0],
        message_count: 2,
        pin_counts: { reports: 0, sources: 0 },
      };
      const messages = structuredClone(allMessages.slice(0, 2));
      const reports = structuredClone(allReports.slice(0, 1));
      const detail = () => ({ chat, messages, reports, sources: [] });
      const connection = {
        configured: true,
        using_local_defaults: true,
        profile: {
          provider: "none",
          model: "",
          ollama_url: "http://localhost:11434",
          aws_profile: "",
          aws_region: "",
          allow_paid_inference: false,
        },
        credentials: {
          materials_project: "missing",
          openai: "missing",
          anthropic: "missing",
          kimi: "missing",
          gemini: "missing",
          deepseek: "missing",
          xai: "missing",
          openrouter: "missing",
        },
        vault: {
          available: false,
          locked: false,
          exists: false,
          can_create: true,
          key_source: "unavailable",
        },
        warnings: [],
        accounts: [],
        active_account_id: null,
      };
      const setup = {
        version: 1,
        required: true,
        completed: true,
        current_step: "review",
        can_research: true,
        model: {
          status: "ready",
          provider: "openai",
          model: "synthetic-history-model",
          account_id: "synthetic-account",
          message: "Synthetic verified session.",
          checked_at: times[0],
        },
        optional: {
          compute: "local",
          aws_required: false,
          data_apis_required: false,
        },
      };
      const presentations = [],
        submissions = [],
        unexpected = [],
        errors = [];
      t.mock.method(console, "error", (...args) => errors.push(args.join(" ")));
      t.mock.method(globalThis, "fetch", async (path, options = {}) => {
        if (path === "/api/session")
          return Response.json({ csrf_token: "TEST_QUERY_HISTORY_SESSION" });
        if (path === "/api/projects") return Response.json({ projects: [] });
        if (path === "/api/chats") return Response.json({ chats: [chat] });
        if (path === "/api/settings") return Response.json(defaultSettings);
        if (path === "/api/connections") return Response.json(connection);
        if (path === "/api/connections/setup") return Response.json(setup);
        if (path === "/api/research-runs") return Response.json({ runs: [] });
        if (path === "/api/ranking-profiles")
          return Response.json({
            active_profile_id: null,
            profiles: [],
            catalog: { attributes: [], material_classes: [], applications: [] },
          });
        if (path === "/api/public-sources")
          return Response.json({ sources: [], connected_sources: [] });
        if (path === "/api/source-settings")
          return Response.json({
            search_public_references: false,
            enabled_sources: [],
            materials_project_mode: "off",
            max_results_per_source: 5,
          });
        if (path === "/api/connections/agent")
          return Response.json({
            engine: "goose",
            available: true,
            version: "TEST",
            tools: [],
            message: "Synthetic runtime.",
          });
        if (path === `/api/chats/${chat.id}`) return Response.json(detail());
        if (path === `/api/chats/${chat.id}/messages`) {
          const submitted = JSON.parse(options.body);
          submissions.push(submitted);
          const index = submissions.length;
          assert.equal(submitted.content, allMessages[index * 2].content);
          messages.push(
            ...structuredClone(allMessages.slice(index * 2, index * 2 + 2)),
          );
          reports.push({
            ...structuredClone(allReports[index]),
            result: {
              execution: { presentation: defaultSettings.presentation },
            },
          });
          chat.message_count = messages.length;
          chat.updated_at = times[index];
          return Response.json(detail());
        }
        if (path.startsWith(`/api/chats/${chat.id}/research-status?`))
          return Response.json({
            run_id: new URL(path, "http://localhost").searchParams.get(
              "run_id",
            ),
            status: "completed",
            phase: "complete",
            message: "Synthetic run completed.",
            started_at: times[0],
            updated_at: times[1],
            sequence: 1,
          });
        const presentation = path.match(
          /^\/api\/chats\/synthetic-chat\/reports\/([^/]+)\/presentation\?format_source=(current|saved)$/,
        );
        if (presentation) {
          const [, id, source] = presentation;
          presentations.push({ id, source });
          const saved = reports.find((value) => value.id === id);
          assert.ok(saved);
          return Response.json({
            version: "report-presentation-v2",
            chat_id: chat.id,
            report_id: id,
            format_source: source,
            settings_source:
              source === "current" ? "current-settings" : "saved-report",
            presentation: defaultSettings.presentation,
            pi_summary: saved.pi_summary,
            technical_audit: saved.technical_audit,
            report_tables: null,
            references: [],
            legacy: false,
          });
        }
        unexpected.push(path);
        throw new Error(`Unexpected synthetic history request ${path}`);
      });
      // A structured archive exercises the saved-format API instead of the legacy-text shortcut.
      reports[0].result = {
        execution: { presentation: defaultSettings.presentation },
      };
      const workspace = () =>
        createElement(
          ConnectionsProvider,
          null,
          createElement(SetupProvider, null, createElement(Workspace)),
        );
      const openChat = () => click(document.querySelector(".global-chat-item"));
      const latest = () => document.querySelector(".latest-report-section");
      const earlier = () => [
        ...document.querySelectorAll(".query-history-card"),
      ];
      const submit = async (question) => {
        const composer = document.querySelector('textarea[maxlength="20000"]');
        assert.ok(composer);
        await act(async () => {
          Object.getOwnPropertyDescriptor(
            dom.window.HTMLTextAreaElement.prototype,
            "value",
          ).set.call(composer, question.content);
          composer.dispatchEvent(
            new dom.window.Event("input", { bubbles: true }),
          );
        });
        await act(async () =>
          composer.form.dispatchEvent(
            new dom.window.Event("submit", { bubbles: true, cancelable: true }),
          ),
        );
      };
      await renderNode(workspace());
      await openChat();
      assert.ok(latest().textContent.includes(firstQuestion.content));
      assert.equal(earlier().length, 0);
      await submit(secondQuestion);
      assert.ok(latest().textContent.includes(secondQuestion.content));
      assert.ok(latest().textContent.includes("Middle-A"));
      assert.ok(!latest().textContent.includes("Earlier-A"));
      assert.equal(earlier().length, 1);
      assert.ok(earlier()[0].textContent.includes(firstQuestion.content));
      assert.ok(earlier()[0].textContent.includes("Earlier-A"));
      assert.ok(!earlier()[0].textContent.includes("Middle-A"));
      assert.equal(
        earlier()[0].querySelector(".research-report"),
        null,
        "closed archive does not mount report actions",
      );
      await submit(thirdQuestion);
      assert.ok(latest().textContent.includes(thirdQuestion.content));
      assert.ok(latest().textContent.includes("Latest-only-A"));
      assert.equal(earlier().length, 2);
      assert.deepEqual(
        earlier().map(
          (card) => card.querySelector(".query-history-question").textContent,
        ),
        [firstQuestion.content, secondQuestion.content],
      );
      assert.deepEqual(
        earlier().map((card) =>
          card.querySelector("header time").getAttribute("datetime"),
        ),
        times.slice(0, 2),
      );
      assert.ok(
        !document
          .querySelector(".query-history")
          .textContent.includes("Latest-only-A"),
      );
      assert.equal(
        document.querySelectorAll(".research-report").length,
        1,
        "only the newest full report mounts by default",
      );
      await click(document.querySelector(".query-history-link"));
      assert.equal(
        document.activeElement,
        document.querySelector(".query-history"),
        "the header shortcut moves keyboard focus to prior queries",
      );
      await click(document.querySelector(".sidebar-new-chat"));
      await openChat();
      assert.equal(
        earlier().length,
        2,
        "chat navigation preserves both earlier queries",
      );
      await remountNode(workspace());
      await openChat();
      assert.equal(
        earlier().length,
        2,
        "reload restores previous query snapshots from saved chat data",
      );
      assert.ok(latest().textContent.includes(thirdQuestion.content));
      assert.equal(
        submissions.length,
        2,
        "viewing history does not resubmit research",
      );
      const beforeOpening = presentations.length;
      await toggle(earlier()[0].querySelector(".query-full-report"), true);
      assert.equal(document.querySelectorAll(".research-report").length, 2);
      assert.ok(
        earlier()[0]
          .querySelector(".research-report")
          .textContent.includes("Earlier-D"),
        "expanded report retains candidates beyond the small preview",
      );
      assert.deepEqual(
        presentations.slice(beforeOpening),
        [{ id: firstReport.id, source: "saved" }],
        "history asks for the archived presentation, not a fresh interpretation",
      );
      assert.deepEqual(unexpected, []);
      assert.deepEqual(errors, []);
    },
  ));
