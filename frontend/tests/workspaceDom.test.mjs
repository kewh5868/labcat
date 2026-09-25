import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

// Exercise React's reconciliation in a real DOM without requiring a browser.
// Duplicate sibling keys previously left orphaned project composers on switches.
async function compileComponents() {
  const output = await mkdtemp(join(tmpdir(), "labcat-react-test-"));
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
  return output;
}

test("project, new chat and Connections switches never leave duplicate prompt fields", async (t) => {
  const output = await compileComponents();
  const dom = new JSDOM('<div id="root"></div>', { url: "http://localhost/" });
  const globals = [
    "window",
    "document",
    "HTMLElement",
    "HTMLDialogElement",
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
  dom.window.HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { default: Workspace } = await import(
    pathToFileURL(join(output, "ProjectWorkspace.js")).href
  );
  const { ConnectionsProvider } = await import(
    pathToFileURL(join(output, "Connections.js")).href
  );
  const { SetupProvider } = await import(
    pathToFileURL(join(output, "SetupWizard.js")).href
  );
  const { defaultSettings } = await import(
    pathToFileURL(join(output, "workspaceApi.js")).href
  );
  const at = "2026-09-09T12:00:00Z";
  const project = {
    id: "project-one",
    name: "Oxide research",
    description: "",
    created_at: at,
    updated_at: at,
    chat_count: 1,
    pin_counts: { reports: 0, sources: 0 },
  };
  const chat = {
    id: "chat-one",
    project_id: project.id,
    title: "Untitled chat",
    chat_number: 1,
    display_title: "Untitled chat · #1",
    created_at: at,
    updated_at: at,
    message_count: 0,
    pin_counts: { reports: 0, sources: 0 },
  };
  const messageRequests = [],
    messages = [],
    reports = [],
    progressRequests = [];
  let pauseMessage = false,
    finishMessage;
  const rankingProfile = (id, name, preset) => ({
    id,
    name,
    preset,
    material_class: "oxide_dielectrics",
    application: "thin_film_insulation",
    importance: { band_gap: 1 },
    normalized_weights: { band_gap: 1 },
    created_at: at,
    updated_at: at,
  });
  const rankingProfiles = {
    active_profile_id: "profile-active",
    profiles: [
      rankingProfile("profile-active", "Preset priorities", true),
      rankingProfile("profile-custom", "Custom priorities", false),
    ],
    catalog: {
      attributes: [
        {
          id: "band_gap",
          label: "Band gap",
          category: "Electronic",
          description: "Preference only.",
          source_field: "band_gap",
          supported: true,
          availability_note: "Requires evidence.",
        },
      ],
      material_classes: [
        {
          id: "oxide_dielectrics",
          label: "Oxide dielectrics",
          scope: "Preference only.",
        },
      ],
      applications: [
        {
          id: "thin_film_insulation",
          label: "Thin-film insulation",
          scope: "Preference only.",
        },
      ],
    },
  };
  let status = {
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
  let sourceSettings = {
    search_public_references: false,
    enabled_sources: [],
    materials_project_mode: "auto",
    max_results_per_source: 5,
  };
  let modelCatalogRequests = 0;
  let setupCompletions = 0;
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    if (path === "/api/chats/chat-one/messages") {
      const value = JSON.parse(options.body);
      messageRequests.push(value);
      if (pauseMessage)
        await new Promise((resolve) => {
          finishMessage = resolve;
        });
      messages.push({
        id: `message-${messages.length}`,
        chat_id: chat.id,
        role: "user",
        content: value.content,
        report_id: null,
        created_at: at,
      });
      const clarification = messageRequests.length !== 2;
      messages.push({
        id: `message-${messages.length}`,
        chat_id: chat.id,
        role: "assistant",
        content: clarification
          ? "Please narrow the materials research question.\n\n1. Which material class?\n2. What application should the search support?"
          : "I can help research public materials evidence within this workspace’s constraints.",
        report_id: null,
        created_at: at,
        intake: {
          status: clarification ? "clarification_required" : "refused",
          reason_code: "fixture",
          questions: clarification
            ? [
                "Which material class?",
                "What application should the search support?",
              ]
            : [],
        },
      });
      chat.message_count = messages.length;
      return Response.json({ chat, messages, reports, sources: [] });
    }
    if (path.startsWith("/api/chats/chat-one/research-status?")) {
      const run_id = new URL(path, "http://localhost").searchParams.get(
        "run_id",
      );
      progressRequests.push(run_id);
      assert.equal(run_id, messageRequests.at(-1).run_id);
      return Response.json({
        run_id,
        status: "running",
        phase: "discovery",
        message: "Searching approved public indexes.",
        started_at: at,
        updated_at: at,
        sequence: 2,
      });
    }
    if (path === "/api/projects/project-one" && options.method === "PATCH") {
      project.name = JSON.parse(options.body).name;
      return Response.json(project);
    }
    // This navigation test uses an explicitly verified synthetic model session.
    if (
      path === "/api/connections/setup" ||
      path === "/api/connections/setup/complete"
    ) {
      if (path.endsWith("/complete")) {
        assert.equal(options.method, "POST");
        setupCompletions++;
      }
      return Response.json({
        version: 1,
        required: true,
        completed: true,
        current_step: "review",
        can_research: true,
        model: {
          status: "ready",
          provider: "openai",
          model: "test-navigation-model",
          account_id: "test-navigation-account",
          message: "Simulated verified connection for navigation testing.",
          checked_at: at,
        },
        optional: {
          compute: "local",
          aws_required: false,
          data_apis_required: false,
        },
      });
    }
    if (path === "/api/session")
      return Response.json({ csrf_token: "TEST_DOM_SESSION_TOKEN_123456" });
    if (
      path === "/api/connections/accounts" ||
      path === "/api/connections/accounts/account-one"
    ) {
      const value = JSON.parse(options.body);
      status = {
        ...status,
        using_local_defaults: false,
        profile: value.profile,
        active_account_id: "account-one",
        credentials: {
          ...status.credentials,
          openai: value.api_key ? "session" : status.credentials.openai,
        },
        accounts: [
          {
            id: "account-one",
            label: value.label,
            profile: value.profile,
            credential_state: value.api_key ? "session" : "missing",
          },
        ],
      };
      return Response.json(status);
    }
    if (path === "/api/connections/test")
      return Response.json({
        target: JSON.parse(options.body).target,
        status: "ok",
        message: "Test metadata response.",
        billable: false,
        inference_tested: false,
      });
    if (path === "/api/connections/models") {
      modelCatalogRequests += 1;
      return Response.json({
        provider: "openai",
        models: [{ id: "model-one", label: "Model one" }],
        message: "Available model metadata.",
        inference_tested: false,
      });
    }
    if (path === "/api/source-settings" && options.method === "PUT")
      sourceSettings = JSON.parse(options.body);
    const responses = {
      "/api/projects": { projects: [project] },
      "/api/chats": { chats: [chat] },
      "/api/settings": defaultSettings,
      "/api/connections": status,
      "/api/projects/project-one/contents": {
        chats: [chat],
        reports: [],
        sources: [],
      },
      "/api/connections/agent": {
        engine: "goose",
        available: true,
        version: "TEST",
        tools: ["search_public_references", "generate_ranked_report"],
        message: "Test runtime metadata only.",
      },
      "/api/chats/chat-one": { chat, messages, reports, sources: [] },
      "/api/ranking-profiles": rankingProfiles,
      "/api/public-sources": {
        sources: [
          {
            id: "hybrid3",
            name: "HybriD3",
            description: "Public materials database.",
            homepage: "https://materials.hybrid3.duke.edu/",
            documentation_url: "https://materials.hybrid3.duke.edu/",
            requires_credentials: false,
            kind: "database",
            scope: "public",
          },
        ],
      },
      "/api/source-settings": sourceSettings,
    };
    assert.ok(Object.hasOwn(responses, path), `unexpected request ${path}`);
    return Response.json(responses[path]);
  });
  const errors = [];
  t.mock.method(console, "error", (...args) => errors.push(args.join(" ")));
  const root = createRoot(document.getElementById("root"));
  try {
    await act(async () => {
      root.render(
        createElement(
          ConnectionsProvider,
          null,
          createElement(
            SetupProvider,
            null,
            createElement(Workspace, {
              connectionOverview: createElement(
                "div",
                null,
                "Workspace services",
              ),
            }),
          ),
        ),
      );
    });
    const buttons = () => [...document.querySelectorAll("button")];
    const namedButton = (name) =>
      buttons().find((button) => button.textContent.trim().endsWith(name));
    const click = async (element) => {
      assert.ok(element, "navigation target exists");
      await act(async () => {
        element.dispatchEvent(
          new dom.window.MouseEvent("click", { bubbles: true }),
        );
      });
    };
    const change = async (element, value) => {
      assert.ok(element, "form field exists");
      await act(async () => {
        const prototype =
          element instanceof dom.window.HTMLSelectElement
            ? dom.window.HTMLSelectElement.prototype
            : element instanceof dom.window.HTMLTextAreaElement
              ? dom.window.HTMLTextAreaElement.prototype
              : dom.window.HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(prototype, "value").set.call(
          element,
          value,
        );
        element.dispatchEvent(
          new dom.window.Event(
            element instanceof dom.window.HTMLSelectElement
              ? "change"
              : "input",
            { bubbles: true },
          ),
        );
      });
    };
    const sections = document.querySelectorAll(".sidebar-history-section");
    assert.equal(sections.length, 2);
    for (const section of sections) {
      const list = section.querySelector("nav");
      assert.equal(
        list.tabIndex,
        0,
        "each named scroll area is keyboard accessible",
      );
      assert.ok(list.getAttribute("aria-label"));
      assert.equal(
        list.contains(section.querySelector(".project-list-heading")),
        false,
      );
    }
    await click(
      document.querySelector(".sidebar-project-row .sidebar-menu-trigger"),
    );
    assert.ok(document.querySelector(".sidebar-item-menu"));
    await act(async () =>
      document
        .querySelector(".project-list")
        .dispatchEvent(new dom.window.Event("scroll")),
    );
    assert.equal(
      document.querySelector(".sidebar-item-menu"),
      null,
      "scrolling dismisses a menu positioned for the previous row location",
    );
    const composers = () =>
      document.querySelectorAll('textarea[maxlength="20000"]');
    assert.equal(composers().length, 1);
    const structureChoice = () =>
      document.querySelector(".composer-structure-option input");
    assert.equal(
      structureChoice().checked,
      true,
      "new searches find reference structures by default",
    );
    await click(structureChoice());
    assert.equal(
      structureChoice().checked,
      false,
      "structure lookup can be disabled without submitting",
    );
    assert.equal(messageRequests.length, 0);
    const curiosity = () =>
      document.querySelector(".materials-fact-copy").textContent;
    const initialFact = curiosity();
    await change(composers()[0], "A draft should keep its fact");
    assert.equal(curiosity(), initialFact);
    await click(document.querySelector(".sidebar-new-chat"));
    assert.notEqual(
      curiosity(),
      initialFact,
      "New chat resets the fact even while already on the welcome screen",
    );
    assert.equal(composers()[0].value, "");
    assert.equal(
      structureChoice().checked,
      true,
      "a new chat starts with structure search enabled",
    );
    const totals = document.querySelector(".project-counts");
    assert.equal(totals.textContent, "1 chat·0 reports·0 sources");
    assert.equal(totals.title, totals.getAttribute("aria-label"));
    assert.equal(document.querySelector(".project-nav-item .pin-totals"), null);
    assert.match(
      document.querySelector(".composer-ranking-button").textContent,
      /Infer from prompt/,
    );
    for (let index = 0; index < 6; index += 1) {
      await click(document.querySelector(".project-nav-item"));
      assert.equal(composers().length, 1, "project has one composer");
      assert.equal(
        document.querySelectorAll(".project-inline-composer").length,
        1,
      );
      assert.equal(document.querySelector(".project-composer-heading"), null);
      assert.ok(
        document.querySelector(".nested-chat-list .global-chat-item"),
        "project conversations appear in sidebar",
      );
      await click(document.querySelector(".sidebar-new-chat"));
      assert.equal(composers().length, 1, "new chat has one composer");
      assert.equal(
        document.querySelectorAll(".project-inline-composer").length,
        0,
        "project composer unmounts",
      );
      await click(namedButton("Connections"));
      assert.equal(
        composers().length,
        0,
        "Connections has no research composer",
      );
      await click(namedButton("Chat"));
      assert.equal(
        composers().length,
        1,
        "returning to Chat restores one composer",
      );
      await click(
        document.querySelector(".nested-chat-list .global-chat-item"),
      );
      assert.equal(composers().length, 1, "saved chat has one composer");
    }
    await change(composers()[0], "Keep this draft through settings");
    await click(document.querySelector(".composer-ranking-button"));
    await click(
      [
        ...document.querySelectorAll(
          ".composer-ranking-popover .composer-choice",
        ),
      ].find((button) => button.textContent.includes("Custom priorities")),
    );
    assert.match(
      document.querySelector(".composer-ranking-button").textContent,
      /Custom priorities/,
    );
    await click(document.querySelector(".composer-model-button"));
    await click(
      [
        ...document.querySelectorAll(".composer-model-popover footer button"),
      ].find((button) =>
        button.textContent.includes("Connect or manage providers"),
      ),
    );
    assert.ok(document.querySelector(".composer-settings-dialog").open);
    assert.equal(
      document.querySelector(".composer-picker-popover"),
      null,
      "picker closes before opening connection settings",
    );
    assert.equal(
      composers().length,
      1,
      "connection setup leaves one underlying composer mounted",
    );
    assert.equal(composers()[0].value, "Keep this draft through settings");
    await click(document.querySelector(".composer-settings-header button"));
    await click(document.querySelector(".composer-ranking-button"));
    await click(
      document.querySelector(".composer-ranking-popover footer button"),
    );
    assert.ok(
      document.querySelector(
        ".composer-settings-dialog .ranking-profile-editor",
      ),
    );
    assert.equal(composers()[0].value, "Keep this draft through settings");
    await click(document.querySelector(".composer-settings-header button"));
    pauseMessage = true;
    await click(document.querySelector('[aria-label="Send message"]'));
    assert.match(
      document.querySelector(".research-progress-panel").textContent,
      /Searching approved public indexes/,
    );
    assert.ok(document.querySelector('[role="timer"]'));
    assert.equal(
      progressRequests.length,
      1,
      "saved chat progress belongs to the active submission",
    );
    pauseMessage = false;
    await act(async () => finishMessage());
    assert.equal(
      document.querySelector(".research-progress-panel"),
      null,
      "completed request stops progress polling",
    );
    assert.deepEqual(messageRequests.at(-1), {
      content: "Keep this draft through settings",
      ranking_profile_id: "profile-custom",
      run_id: messageRequests.at(-1).run_id,
      search_reference_structures: true,
    });
    assert.match(messageRequests.at(-1).run_id, /^[a-f0-9-]{36}$/);
    assert.equal(rankingProfiles.active_profile_id, "profile-active");
    assert.match(
      document.querySelector(".composer-ranking-button").textContent,
      /Custom priorities/,
    );
    assert.equal(
      document.querySelector(".research-report"),
      null,
      "clarification is a conversation reply, not a scored report",
    );
    const clarification = document.querySelector(".message-assistant");
    assert.match(clarification.textContent, /Which material class\?/);
    assert.equal(
      clarification.closest("details"),
      null,
      "guiding questions are visible without opening history",
    );
    assert.equal(
      clarification.textContent.match(/Which material class\?/g).length,
      1,
      "questions are not duplicated from intake metadata",
    );
    await click(structureChoice());
    await change(composers()[0], "Infer preferences for this question");
    await click(document.querySelector(".composer-ranking-button"));
    await click(
      [
        ...document.querySelectorAll(
          ".composer-ranking-popover .composer-choice",
        ),
      ].find((button) => button.textContent.includes("Infer from prompt")),
    );
    await click(document.querySelector('[aria-label="Send message"]'));
    assert.deepEqual(messageRequests.at(-1), {
      content: "Infer preferences for this question",
      ranking_profile_id: "infer",
      run_id: messageRequests.at(-1).run_id,
      search_reference_structures: false,
    });
    assert.notEqual(
      messageRequests.at(-1).run_id,
      messageRequests.at(-2).run_id,
      "each submission receives a distinct progress identity",
    );
    assert.equal(
      document.querySelector(".research-report"),
      null,
      "refusal does not create a report",
    );
    assert.match(
      [...document.querySelectorAll(".message-assistant")].at(-1).textContent,
      /within this workspace’s constraints/,
    );

    // A later clarification must remain visible after an existing saved report.
    messages.push({
      id: "saved-request",
      chat_id: chat.id,
      role: "user",
      content: "A completed fixture request.",
      report_id: null,
      created_at: at,
    });
    messages.push({
      id: "saved-response",
      chat_id: chat.id,
      role: "assistant",
      content: "Saved fixture response.",
      report_id: "saved-report",
      created_at: at,
    });
    reports.push({
      id: "saved-report",
      project_id: project.id,
      chat_id: chat.id,
      message_id: "saved-response",
      title: "Synthetic saved report",
      stage: "fixture",
      pi_summary: "Saved renderer fixture without scientific data.",
      technical_audit: "Saved renderer fixture without scientific data.",
      source_ids: [],
      created_at: at,
      pinned: false,
    });
    await click(document.querySelector(".project-nav-item"));
    await click(document.querySelector(".nested-chat-list .global-chat-item"));
    assert.equal(document.querySelectorAll(".research-report").length, 1);
    await change(composers()[0], "Follow up without enough detail");
    await click(document.querySelector('[aria-label="Send message"]'));
    const followup = [...document.querySelectorAll(".message-assistant")].at(
      -1,
    );
    assert.match(followup.textContent, /Which material class\?/);
    assert.equal(
      followup.closest("details"),
      null,
      "clarification after a report stays in the active conversation",
    );
    assert.equal(
      document.querySelectorAll(".research-report").length,
      1,
      "the existing report is retained without fabricating another",
    );
    assert.equal(composers().length, 1);
    await click(document.querySelector(".project-nav-item"));
    assert.equal(
      document.querySelectorAll(".sidebar-menu-trigger").length,
      2,
      "each project and chat has its own menu",
    );
    await click(
      document.querySelector(
        '[aria-label="Actions for project Oxide research"]',
      ),
    );
    await click(namedButton("Rename project"));
    project.chat_count = 999999;
    project.pin_counts = { reports: Number.MAX_SAFE_INTEGER, sources: 1234 };
    await change(document.getElementById("item-name"), "Oxide thin films");
    await click(namedButton("Save name"));
    assert.equal(project.name, "Oxide thin films");
    const largeTotals = document.querySelector(".project-counts");
    assert.equal(largeTotals.textContent, "1M chats·9Q reports·1.2k sources");
    assert.equal(
      largeTotals.title,
      "999,999 chats · 9,007,199,254,740,991 reports · 1,234 sources",
    );
    assert.equal(largeTotals.getAttribute("aria-label"), largeTotals.title);
    assert.equal(
      document.querySelector(".project-heading h1").textContent,
      "Oxide thin films",
    );
    assert.equal(
      document.querySelector("dialog"),
      null,
      "rename dialog closes after a successful save",
    );

    await click(namedButton("Connections"));
    assert.equal(composers().length, 0);
    await change(document.getElementById("model-provider"), "openai");
    assert.equal(
      document.getElementById("model-choice").tagName,
      "SELECT",
      "models use a selection field",
    );
    await change(
      document.getElementById("provider-key"),
      "TEST_DOM_WRITE_ONLY_KEY",
    );
    await click(namedButton("Save and test connections"));
    assert.equal(
      status.accounts.length,
      1,
      "new account is saved before model selection",
    );
    assert.equal(status.accounts[0].profile.model, "");
    assert.equal(
      document.getElementById("provider-key").value,
      "",
      "submitted keys leave the form",
    );
    assert.equal(
      modelCatalogRequests,
      1,
      "available models load automatically after saving credentials",
    );
    await click(namedButton("Refresh models"));
    assert.equal(modelCatalogRequests, 2);
    await change(document.getElementById("model-choice"), "model-one");
    await click(namedButton("Save and test connections"));
    assert.equal(
      status.accounts.length,
      1,
      "editing a connection updates its existing account",
    );
    assert.equal(status.profile.model, "model-one");
    assert.equal(
      document.getElementById("connections-add-source"),
      null,
      "Connections holds credentials, not source-selection preferences",
    );
    await click(namedButton("Open setup"));
    assert.ok(document.querySelector(".setup-window"));
    assert.match(
      document.querySelector("#setup-heading").textContent,
      /workspace is ready to connect/,
    );
    assert.equal(namedButton("Finish setup").disabled, false);
    await click(namedButton("Finish setup"));
    assert.equal(setupCompletions, 1);
    assert.equal(
      document.querySelector(".setup-window"),
      null,
      "successful setup closes the dialog",
    );
    assert.equal(
      composers().length,
      1,
      "finishing setup from Connections opens the main chat workspace",
    );
    assert.match(
      document.querySelector(".workspace-breadcrumb").textContent,
      /\/Chat$/,
    );
    assert.equal(
      document.querySelectorAll(".research-report").length,
      1,
      "returning to chat preserves the current report",
    );
    await click(namedButton("Search Criterion"));
    assert.equal(
      document.getElementById("setting-verbosity"),
      null,
      "Report presentation is in Report Format",
    );
    assert.equal(
      document.querySelector('input[type="password"]'),
      null,
      "Search Criterion has no credentials",
    );
    await change(document.getElementById("settings-add-source"), "hybrid3");
    assert.equal(
      document.querySelectorAll(".selected-public-source").length,
      1,
    );
    await click(namedButton("Save source preferences"));
    assert.deepEqual(sourceSettings.enabled_sources, ["hybrid3"]);
    assert.equal(
      composers().length,
      0,
      "Connections remains free of research composers after its controls change",
    );
    assert.ok(
      !document.body.textContent.includes(
        "Messages guide the task. They are never evidence.",
      ),
    );
    assert.ok(
      !errors.some((message) =>
        /same key|unique.*key|not wrapped in act/i.test(message),
      ),
      errors.join("\n"),
    );
  } finally {
    await act(async () => {
      root.unmount();
    });
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
    await rm(output, { recursive: true, force: true });
  }
});
