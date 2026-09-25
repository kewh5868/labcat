import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

async function compile() {
  const output = await mkdtemp(join(tmpdir(), "labcat-setup-workspace-"));
  for (const name of await readdir(new URL("../src/", import.meta.url))) {
    if (!/\.tsx?$/.test(name)) continue;
    const source = await readFile(
      new URL(`../src/${name}`, import.meta.url),
      "utf8",
    );
    const result = ts
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
    await writeFile(join(output, name.replace(/\.tsx?$/, ".js")), result);
  }
  await writeFile(join(output, "package.json"), '{"type":"module"}');
  return output;
}

test("workspace requires first-run setup and preserves drafts and chat identity on model failures", async (t) => {
  const output = await compile();
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
  const { ConnectionsProvider } = await import(
    pathToFileURL(join(output, "Connections.js")).href
  );
  const { SetupProvider } = await import(
    pathToFileURL(join(output, "SetupWizard.js")).href
  );
  const { default: Workspace } = await import(
    pathToFileURL(join(output, "ProjectWorkspace.js")).href
  );
  const { defaultSettings } = await import(
    pathToFileURL(join(output, "workspaceApi.js")).href
  );
  const at = "2026-09-10T12:00:00Z";
  const profile = {
    provider: "chatgpt",
    model: "fixture-model",
    allow_paid_inference: true,
    ollama_url: "http://localhost:11434",
    aws_profile: "",
    aws_region: "",
  };
  const status = {
    configured: true,
    using_local_defaults: false,
    profile,
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
      available: true,
      locked: false,
      exists: true,
      can_create: false,
      key_source: "passphrase",
    },
    warnings: [],
    accounts: [
      {
        id: "fixture-account",
        label: "Fixture account",
        profile,
        credential_state: "encrypted",
      },
    ],
    active_account_id: "fixture-account",
  };
  const setupState = (ready) => ({
    version: 1,
    required: true,
    completed: ready,
    current_step: ready ? "review" : "model",
    can_research: ready,
    model: {
      status: ready ? "ready" : "verification_required",
      provider: profile.provider,
      model: profile.model,
      account_id: "fixture-account",
      message: ready
        ? "Verified fixture metadata."
        : "Verify the saved connection before research.",
      checked_at: ready ? at : null,
    },
    optional: {
      compute: "local",
      aws_required: false,
      data_apis_required: false,
    },
  });
  let setup = setupState(false),
    failCode = 409,
    releaseHistory;
  const historyLoaded = new Promise((resolve) => {
    releaseHistory = resolve;
  });
  const savedChat = {
    id: "saved-chat",
    project_id: null,
    title: "Saved research history",
    chat_number: 1,
    display_title: "Saved research history · #1",
    message_count: 1,
    created_at: at,
    updated_at: at,
    pin_counts: { reports: 0, sources: 0 },
  };
  const newChat = {
    ...savedChat,
    id: "new-chat",
    title: "Untitled chat",
    chat_number: 2,
    display_title: "Untitled chat · #2",
    message_count: 0,
  };
  const chats = [savedChat],
    calls = [],
    errors = [];
  const detail = (chat) => ({
    chat,
    messages:
      chat.id === savedChat.id
        ? [
            {
              id: "saved-message",
              chat_id: chat.id,
              role: "user",
              content: "A previous materials research question.",
              report_id: null,
              created_at: at,
            },
          ]
        : [],
    reports: [],
    sources: [],
  });
  t.mock.method(console, "error", (...args) => errors.push(args.join(" ")));
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    calls.push({
      path,
      method: options.method ?? "GET",
      body: options.body ? JSON.parse(options.body) : null,
    });
    if (path === "/api/research-runs") return Response.json({ runs: [] });
    if (path === "/api/connections") return Response.json(status);
    if (path === "/api/connections/setup") return Response.json(setup);
    if (path === "/api/session")
      return Response.json({ csrf_token: "FIXTURE-CSRF-LONG-ENOUGH" });
    if (path === "/api/connections/setup/verify") {
      setup = setupState(true);
      return Response.json(setup);
    }
    if (path === "/api/projects") {
      await historyLoaded;
      return Response.json({ projects: [] });
    }
    if (path === "/api/settings") {
      await historyLoaded;
      return Response.json(defaultSettings);
    }
    if (path === "/api/chats") {
      if (options.method === "POST") {
        assert.equal(
          chats.includes(newChat),
          false,
          "a failed prompt must reuse its saved chat",
        );
        chats.push(newChat);
        return Response.json(newChat);
      }
      await historyLoaded;
      return Response.json({ chats });
    }
    if (path === "/api/chats/saved-chat")
      return Response.json(detail(savedChat));
    if (path === "/api/chats/new-chat") return Response.json(detail(newChat));
    if (path === "/api/ranking-profiles")
      return Response.json({
        active_profile_id: null,
        profiles: [],
        catalog: { attributes: [], material_classes: [], applications: [] },
      });
    if (path === "/api/chats/new-chat/messages") {
      setup = setupState(false);
      return Response.json(
        {
          detail: {
            code:
              failCode === 409
                ? "model_setup_required"
                : "model_execution_failed",
            setup_required: failCode === 409,
            message: "FIXTURE_PRIVATE_ERROR_NEVER_RENDERED",
          },
        },
        { status: failCode },
      );
    }
    assert.fail(`Unexpected request ${path}`);
  });
  const root = createRoot(document.getElementById("root"));
  const render = () =>
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
  const composer = () => {
    const fields = document.querySelectorAll('textarea[maxlength="20000"]');
    assert.equal(fields.length, 1, "exactly one research composer");
    return fields[0];
  };
  const button = (name) => {
    const item = [...document.querySelectorAll("button")].find(
      (element) => element.textContent.trim() === name,
    );
    assert.ok(item, name);
    return item;
  };
  const click = async (item) => {
    assert.ok(item);
    await act(async () =>
      item.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })),
    );
  };
  const type = async (text) => {
    await act(async () => {
      const field = composer();
      Object.getOwnPropertyDescriptor(
        dom.window.HTMLTextAreaElement.prototype,
        "value",
      ).set.call(field, text);
      field.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
  };
  const submitCount = () =>
    calls.filter((item) => item.path.endsWith("/messages")).length;
  try {
    await act(async () => render());
    assert.equal(
      document.querySelectorAll(".setup-window").length,
      1,
      "setup opens before optional history loading completes",
    );
    assert.equal(
      document.activeElement,
      document.getElementById("setup-heading"),
    );
    await act(async () => releaseHistory());
    assert.equal(
      document.activeElement,
      document.getElementById("setup-heading"),
      "late composer autofocus cannot steal setup focus",
    );
    composer();
    await click(button("View workspace ×"));
    assert.equal(document.querySelector(".setup-window"), null);
    await type("Keep this draft until a model is connected.");
    assert.equal(
      document.querySelector('[aria-label="Send message"]').disabled,
      true,
    );
    await act(async () =>
      composer().dispatchEvent(
        new dom.window.KeyboardEvent("keydown", {
          key: "Enter",
          ctrlKey: true,
          bubbles: true,
          cancelable: true,
        }),
      ),
    );
    assert.equal(submitCount(), 0);
    assert.equal(
      calls.filter(
        (item) => item.path === "/api/chats" && item.method === "POST",
      ).length,
      0,
      "keyboard cannot create a chat while setup is required",
    );
    assert.equal(
      composer().value,
      "Keep this draft until a model is connected.",
    );
    await click(document.querySelector(".global-chat-item"));
    assert.match(
      document.querySelector(".message-history").textContent,
      /previous materials research question/,
    );
    await click(document.querySelector(".sidebar-new-chat"));
    await type("Traceable public evidence for this new material question.");
    await click(button("Open setup"));
    await click(button("Verify connection"));
    await click(button("View workspace ×"));
    assert.equal(
      composer().value,
      "Traceable public evidence for this new material question.",
    );
    assert.equal(
      document.querySelector('[aria-label="Send message"]').disabled,
      false,
    );
    await click(document.querySelector('[aria-label="Send message"]'));
    assert.equal(submitCount(), 1);
    assert.equal(
      calls.filter(
        (item) => item.path === "/api/chats" && item.method === "POST",
      ).length,
      1,
    );
    assert.equal(
      document.querySelectorAll(".setup-window").length,
      1,
      "409 reopens required setup",
    );
    assert.equal(
      composer().value,
      "Traceable public evidence for this new material question.",
    );
    assert.equal(
      composer().id,
      "prompt-new-chat",
      "new chat identity is retained after failure",
    );
    await click(button("View workspace ×"));
    assert.equal(
      document.querySelector('[aria-label="Send message"]').disabled,
      true,
    );
    await click(button("Open setup"));
    await click(button("Verify connection"));
    await click(button("View workspace ×"));
    failCode = 502;
    await click(document.querySelector('[aria-label="Send message"]'));
    assert.equal(submitCount(), 2, "only explicit user sends invoke research");
    assert.equal(
      calls.filter(
        (item) => item.path === "/api/chats" && item.method === "POST",
      ).length,
      1,
      "retry reuses the existing chat",
    );
    assert.equal(
      document.querySelector(".setup-window"),
      null,
      "provider execution failure does not automatically reopen setup",
    );
    assert.equal(
      document.querySelector('[aria-label="Send message"]').disabled,
      true,
      "failed provider readiness is refreshed before another send",
    );
    assert.equal(
      composer().value,
      "Traceable public evidence for this new material question.",
    );
    assert.match(
      document.querySelector(".message-history").textContent,
      /No report was saved; your draft is still here/,
    );
    assert.doesNotMatch(
      document.body.textContent,
      /FIXTURE_PRIVATE_ERROR_NEVER_RENDERED/,
    );
    await act(async () => Promise.resolve());
    assert.equal(
      submitCount(),
      2,
      "provider errors are not retried automatically",
    );
    assert.deepEqual(errors, []);
  } finally {
    await act(async () => root.unmount());
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
    await rm(output, { recursive: true, force: true });
  }
});

test("completed setup can submit with expired verification while missing readiness and explicit errors remain gated", async (t) => {
  const output = await compile();
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
  const { ConnectionsProvider } = await import(
    pathToFileURL(join(output, "Connections.js")).href
  );
  const { SetupProvider, useSetup } = await import(
    pathToFileURL(join(output, "SetupWizard.js")).href
  );
  const { default: Workspace } = await import(
    pathToFileURL(join(output, "ProjectWorkspace.js")).href
  );
  const { defaultSettings } = await import(
    pathToFileURL(join(output, "workspaceApi.js")).href
  );
  const at = "2026-09-10T12:00:00Z";
  const profile = {
    provider: "chatgpt",
    model: "fixture-model",
    allow_paid_inference: true,
    ollama_url: "http://localhost:11434",
    aws_profile: "",
    aws_region: "",
  };
  const connection = {
    configured: true,
    using_local_defaults: false,
    profile,
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
      available: true,
      locked: false,
      exists: true,
      can_create: false,
      key_source: "passphrase",
    },
    warnings: [],
    accounts: [
      {
        id: "fixture-account",
        label: "Fixture account",
        profile,
        credential_state: "encrypted",
      },
    ],
    active_account_id: "fixture-account",
  };
  const expired = () => ({
    version: 1,
    required: true,
    completed: true,
    current_step: "review",
    can_research: false,
    model: {
      status: "verification_required",
      provider: profile.provider,
      model: profile.model,
      account_id: "fixture-account",
      message: "Verify this account and selected model to continue.",
      checked_at: null,
    },
    optional: {
      compute: "local",
      aws_required: false,
      data_apis_required: false,
    },
  });
  let setup = expired(),
    rejectMessage = false,
    failSetupRead = false,
    failConnectionRead = false,
    renderId = 0;
  const chat = {
    id: "expiry-chat",
    project_id: null,
    title: "Untitled chat",
    chat_number: 1,
    display_title: "Untitled chat · #1",
    message_count: 0,
    created_at: at,
    updated_at: at,
    pin_counts: { reports: 0, sources: 0 },
  };
  const detail = { chat, messages: [], reports: [], sources: [] },
    calls = [],
    unknownRequests = [];
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    const call = {
      path,
      method: options.method ?? "GET",
      body: options.body ? JSON.parse(options.body) : null,
    };
    calls.push(call);
    if (path === "/api/research-runs") return Response.json({ runs: [] });
    if (path === "/api/connections")
      return failConnectionRead
        ? Response.json(
            { detail: "PRIVATE_CONNECTION_DETAIL" },
            { status: 503 },
          )
        : Response.json(connection);
    if (path === "/api/connections/setup")
      return failSetupRead
        ? Response.json({ detail: "PRIVATE_SETUP_DETAIL" }, { status: 503 })
        : Response.json(setup);
    if (path === "/api/session")
      return Response.json({ csrf_token: "FIXTURE-CSRF-LONG-ENOUGH" });
    if (path === "/api/connections/models")
      return Response.json({
        provider: "chatgpt",
        models: [{ id: "fixture-model", label: "Fixture model" }],
        message: "Synthetic model catalog.",
        inference_tested: false,
      });
    if (path === "/api/projects") return Response.json({ projects: [] });
    if (path === "/api/settings") return Response.json(defaultSettings);
    if (path === "/api/chats")
      return Response.json(call.method === "POST" ? chat : { chats: [chat] });
    if (path === "/api/chats/expiry-chat") return Response.json(detail);
    if (path.startsWith("/api/chats/expiry-chat/research-status?"))
      return Response.json({
        run_id: null,
        status: "idle",
        phase: "idle",
        message: "Waiting for this request.",
        started_at: null,
        updated_at: null,
        sequence: 0,
      });
    if (path === "/api/chats/expiry-chat/messages") {
      if (!rejectMessage) return Response.json(detail);
      setup = {
        ...expired(),
        model: {
          ...expired().model,
          status: "error",
          message: "The connection needs a fresh sign-in.",
        },
      };
      return Response.json(
        {
          detail: {
            code: "model_setup_required",
            setup_required: true,
            message: "PRIVATE_SERVER_FAILURE",
          },
        },
        { status: 409 },
      );
    }
    if (path === "/api/ranking-profiles")
      return Response.json({
        active_profile_id: null,
        profiles: [],
        catalog: { attributes: [], material_classes: [], applications: [] },
      });
    unknownRequests.push(path);
    throw new Error(`Unexpected request ${path}`);
  });
  function RefreshSetup() {
    const value = useSetup();
    return createElement(
      "button",
      { onClick: () => void value.refresh().catch(() => undefined) },
      "Refresh fixture readiness",
    );
  }
  const root = createRoot(document.getElementById("root"));
  const render = async () =>
    act(async () =>
      root.render(
        createElement(
          ConnectionsProvider,
          { key: ++renderId },
          createElement(
            SetupProvider,
            null,
            createElement(Workspace),
            createElement(RefreshSetup),
          ),
        ),
      ),
    );
  const composer = () => document.querySelector('textarea[maxlength="20000"]');
  const send = () => document.querySelector('[aria-label="Send message"]');
  const button = (label) =>
    [...document.querySelectorAll("button")].find(
      (item) => item.textContent.trim() === label,
    );
  const click = async (item) => {
    assert.ok(item);
    await act(async () =>
      item.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })),
    );
  };
  const type = async (text) =>
    act(async () => {
      const field = composer();
      Object.getOwnPropertyDescriptor(
        dom.window.HTMLTextAreaElement.prototype,
        "value",
      ).set.call(field, text);
      field.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
  const submits = () =>
    calls.filter((item) => item.path.endsWith("/messages")).length;
  try {
    await render();
    assert.equal(
      document.querySelector(".setup-window"),
      null,
      "expired verification alone does not force completed setup to reopen",
    );
    await type("A new materials question with a saved connection.");
    assert.equal(send().disabled, false);
    assert.match(
      document.querySelector(".connection-notice").textContent,
      /Check connection.*when you send a research request/,
    );
    assert.doesNotMatch(
      document.querySelector(".connection-notice").textContent,
      /· Signed in/,
      "expired verification cannot claim a confirmed sign-in",
    );
    await click(send());
    assert.equal(
      submits(),
      1,
      "draft chat may submit for the server readiness check",
    );
    assert.equal(composer().id, "prompt-expiry-chat");
    assert.equal(
      calls.filter((item) => item.path.endsWith("/verify")).length,
      0,
      "the UI does not silently perform setup writes",
    );
    await type("Keep this draft if the server rejects its connection.");
    rejectMessage = true;
    assert.equal(
      send().disabled,
      false,
      "saved chat uses the same expired-verification eligibility",
    );
    await click(send());
    assert.equal(submits(), 2);
    assert.ok(
      document.querySelector(".setup-window"),
      "server readiness rejection still opens setup",
    );
    await click(button("View workspace ×"));
    assert.equal(
      composer().value,
      "Keep this draft if the server rejects its connection.",
    );
    assert.equal(send().disabled, true);
    assert.match(
      document.querySelector(".message-history").textContent,
      /Your prompt has not been submitted/,
    );
    assert.ok(!document.body.textContent.includes("PRIVATE_SERVER_FAILURE"));
    assert.equal(
      calls.filter(
        (item) => item.path === "/api/chats" && item.method === "POST",
      ).length,
      1,
      "server rejection never duplicates the saved chat",
    );
    for (const state of [
      "not_connected",
      "model_required",
      "consent_required",
      "credentials_locked",
      "error",
    ]) {
      setup = { ...expired(), model: { ...expired().model, status: state } };
      await render();
      assert.ok(document.querySelector(".setup-window"));
      await click(button("View workspace ×"));
      await type("This must remain unsent.");
      assert.equal(send().disabled, true, `${state} remains gated`);
      await act(async () =>
        composer().dispatchEvent(
          new dom.window.KeyboardEvent("keydown", {
            key: "Enter",
            ctrlKey: true,
            bubbles: true,
            cancelable: true,
          }),
        ),
      );
      assert.equal(submits(), 2);
    }
    setup = expired();
    await render();
    await type("Retain draft during a readiness read failure.");
    assert.equal(send().disabled, false);
    failSetupRead = true;
    await click(button("Refresh fixture readiness"));
    assert.equal(send().disabled, true);
    assert.match(
      document.querySelector(".connection-notice").textContent,
      /Setup could not complete this step/,
    );
    assert.equal(
      composer().value,
      "Retain draft during a readiness read failure.",
    );
    failSetupRead = false;
    failConnectionRead = true;
    await render();
    await type("Connection errors also remain gated.");
    assert.equal(send().disabled, true);
    assert.ok(document.querySelector(".connection-error-text"));
    assert.ok(
      !/PRIVATE_SETUP_DETAIL|PRIVATE_CONNECTION_DETAIL/.test(
        document.body.textContent,
      ),
    );
    assert.equal(submits(), 2);
    assert.deepEqual(unknownRequests, []);
  } finally {
    await act(async () => root.unmount());
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
    await rm(output, { recursive: true, force: true });
  }
});
