import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { before, after, test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

// Synthetic workspace/lifecycle fixtures only. All requests and clocks are
// controlled; these tests never access a real workspace, provider or network.
let compiled;
before(async () => {
  compiled = await mkdtemp(join(tmpdir(), "labcat-background-research-dom-"));
  for (const name of await readdir(new URL("../src/", import.meta.url))) {
    if (!/\.tsx?$/.test(name)) continue;
    const source = await readFile(
      new URL(`../src/${name}`, import.meta.url),
      "utf8",
    );
    const output = ts
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
    await writeFile(join(compiled, name.replace(/\.tsx?$/, ".js")), output);
  }
  await writeFile(join(compiled, "package.json"), '{"type":"module"}');
});
after(async () => {
  await rm(compiled, { recursive: true, force: true });
});

const at = "2026-09-23T12:00:00Z";
const externalGeneralRun = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const externalProjectRun = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const runStatus = (run_id, status = "running") => ({
  run_id,
  status,
  phase: status === "running" ? "retrieving_public_evidence" : "completed",
  message: "Synthetic lifecycle status only.",
  started_at: at,
  updated_at: at,
  sequence: status === "running" ? 1 : 2,
});

async function withWorkspace(t, check, { external = false } = {}) {
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
    pathToFileURL(join(compiled, "ProjectWorkspace.js"))
  );
  const { ConnectionsProvider } = await import(
    pathToFileURL(join(compiled, "Connections.js"))
  );
  const { SetupProvider } = await import(
    pathToFileURL(join(compiled, "SetupWizard.js"))
  );
  const { defaultSettings } = await import(
    pathToFileURL(join(compiled, "workspaceApi.js"))
  );
  let timerId = 0;
  const timers = new Map(),
    intervals = new Map();
  t.mock.method(window, "setTimeout", (callback, delay) => {
    const id = ++timerId;
    timers.set(id, { callback, delay });
    return id;
  });
  t.mock.method(window, "clearTimeout", (id) => timers.delete(id));
  t.mock.method(window, "setInterval", (callback, delay) => {
    const id = ++timerId;
    intervals.set(id, { callback, delay });
    return id;
  });
  t.mock.method(window, "clearInterval", (id) => intervals.delete(id));
  const counts = { reports: 0, sources: 0 };
  const project = {
    id: "project-one",
    name: "Synthetic project",
    description: "",
    created_at: at,
    updated_at: at,
    chat_count: 1,
    pin_counts: counts,
  };
  const makeChat = (id, project_id, title, number) => ({
    id,
    project_id,
    title,
    chat_number: number,
    display_title: `${title} · #${number}`,
    created_at: at,
    updated_at: at,
    message_count: 0,
    pin_counts: counts,
  });
  const chats = [
    makeChat("project-chat", project.id, "Project saved question", 1),
    makeChat("general-chat", null, "General saved question", 2),
    makeChat("quiet-chat", null, "Other saved question", 3),
  ];
  const messages = new Map(),
    states = new Map(),
    pending = new Map();
  const getChat = (id) => {
    const chat = chats.find((item) => item.id === id);
    assert.ok(chat, `synthetic chat ${id} exists`);
    return chat;
  };
  const rename = (id, title) => {
    const chat = getChat(id);
    chat.title = title;
    chat.display_title = `${title} · #${chat.chat_number}`;
  };
  const detail = (id) => ({
    chat: getChat(id),
    messages: messages.get(id) ?? [],
    reports: [],
    sources: [],
  });
  if (external) {
    states.set("general-chat", runStatus(externalGeneralRun));
    states.set("project-chat", runStatus(externalProjectRun));
    rename("general-chat", "Server-named general research");
    rename("project-chat", "Server-named project research");
  }
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
  const calls = [],
    unexpected = [],
    consoleErrors = [];
  let failAggregate = false;
  t.mock.method(console, "error", (...args) =>
    consoleErrors.push(args.join(" ")),
  );
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    const method = options.method ?? "GET",
      body = options.body ? JSON.parse(options.body) : null;
    calls.push({ path, method, body, signal: options.signal });
    if (path === "/api/session")
      return Response.json({ csrf_token: "TEST_BACKGROUND_RESEARCH_CSRF" });
    if (path === "/api/connections") return Response.json(connection);
    if (path === "/api/connections/setup")
      return Response.json({
        version: 1,
        required: true,
        completed: true,
        current_step: "review",
        can_research: true,
        model: {
          status: "ready",
          provider: "openai",
          model: "synthetic-lifecycle-model",
          account_id: "synthetic-account",
          message: "Synthetic readiness only.",
          checked_at: at,
        },
        optional: {
          compute: "local",
          aws_required: false,
          data_apis_required: false,
        },
      });
    if (path === "/api/projects") return Response.json({ projects: [project] });
    if (path === "/api/settings") return Response.json(defaultSettings);
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
    if (path === "/api/research-runs") {
      if (failAggregate) return Response.json({}, { status: 503 });
      return Response.json({
        runs: [...states]
          .filter(([, state]) => state.status === "running")
          .map(([chat_id, state]) => ({ chat_id, ...state })),
      });
    }
    if (path === "/api/projects/project-one/contents")
      return Response.json({
        chats: chats.filter((chat) => chat.project_id === project.id),
        reports: [],
        sources: [],
      });
    if (path === "/api/projects/project-one/draft-chat" && method === "POST") {
      const chat = makeChat(
        "new-project-chat",
        project.id,
        "Untitled project chat",
        4,
      );
      chats.push(chat);
      return Response.json(chat);
    }
    if (path === "/api/chats") {
      if (method === "POST") {
        const chat = makeChat(
          "new-general-chat",
          body.project_id,
          body.title,
          4,
        );
        chats.push(chat);
        return Response.json(chat);
      }
      return Response.json({ chats });
    }
    const message = path.match(/^\/api\/chats\/([^/]+)\/messages$/);
    if (message && method === "POST") {
      const id = message[1],
        chat = getChat(id);
      assert.ok(!pending.has(id), "one pending message request per chat");
      rename(
        id,
        chat.project_id
          ? "Early saved project title"
          : "Early saved general title",
      );
      messages.set(id, [
        {
          id: `question-${id}`,
          chat_id: id,
          role: "user",
          content: body.content,
          report_id: null,
          created_at: at,
        },
      ]);
      chat.message_count = 1;
      states.set(id, runStatus(body.run_id));
      return new Promise((resolve, reject) =>
        pending.set(id, { resolve, reject, signal: options.signal }),
      );
    }
    const statusPath = path.match(
      /^\/api\/chats\/([^/]+)\/research-status\?run_id=([^&]+)$/,
    );
    if (statusPath)
      return Response.json(
        states.get(statusPath[1]) ?? {
          run_id: null,
          status: "idle",
          phase: "idle",
          message: "No synthetic run.",
          started_at: null,
          updated_at: null,
          sequence: 0,
        },
      );
    const chatPath = path.match(/^\/api\/chats\/([^/]+)$/);
    if (chatPath && method === "GET") return Response.json(detail(chatPath[1]));
    unexpected.push(`${method} ${path}`);
    throw new Error(`Unexpected synthetic request: ${method} ${path}`);
  });
  const root = createRoot(document.getElementById("root"));
  const click = async (element) => {
    assert.ok(element, "control exists");
    await act(async () =>
      element.dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true }),
      ),
    );
  };
  const chatButton = (id) =>
    [...document.querySelectorAll(".global-chat-item")].find(
      (button) =>
        button.querySelector(".chat-number")?.textContent.trim() ===
        `· #${getChat(id).chat_number}`,
    );
  const openProject = async () =>
    click(document.querySelector(".project-nav-item"));
  const openChat = async (id) => {
    const chat = getChat(id);
    if (chat.project_id && !chatButton(id))
      await click(
        document.querySelector('[aria-label="Expand Synthetic project"]'),
      );
    await click(chatButton(id));
  };
  const composer = () => {
    const field = document.querySelector('textarea[maxlength="20000"]');
    assert.ok(field);
    return field;
  };
  const type = async (value) =>
    act(async () => {
      const field = composer();
      Object.getOwnPropertyDescriptor(
        dom.window.HTMLTextAreaElement.prototype,
        "value",
      ).set.call(field, value);
      field.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
  const submit = async () =>
    act(async () =>
      composer().form.dispatchEvent(
        new dom.window.Event("submit", { bubbles: true, cancelable: true }),
      ),
    );
  const tickAggregate = async () =>
    act(async () => {
      const scheduled = [...timers].filter(([, timer]) => timer.delay === 2000);
      assert.ok(scheduled.length, "aggregate polling is scheduled");
      for (const [id, timer] of scheduled) {
        timers.delete(id);
        timer.callback();
      }
    });
  const finish = async (id) =>
    act(async () => {
      const state = states.get(id);
      assert.ok(state);
      states.set(id, runStatus(state.run_id, "completed"));
      const list = messages.get(id) ?? [];
      messages.set(id, [
        ...list,
        {
          id: `answer-${id}`,
          chat_id: id,
          role: "assistant",
          content: `Saved synthetic response for ${id}.`,
          report_id: null,
          created_at: at,
        },
      ]);
      getChat(id).message_count = list.length + 1;
      const request = pending.get(id);
      if (request) {
        pending.delete(id);
        request.resolve(Response.json(detail(id)));
      }
    });
  const postCount = () =>
    calls.filter(
      (call) => call.method === "POST" && call.path.endsWith("/messages"),
    ).length;
  try {
    await act(async () =>
      root.render(
        createElement(
          ConnectionsProvider,
          null,
          createElement(SetupProvider, null, createElement(Workspace)),
        ),
      ),
    );
    await check({
      act,
      dom,
      click,
      openChat,
      openProject,
      chatButton,
      composer,
      type,
      submit,
      tickAggregate,
      finish,
      pending,
      calls,
      postCount,
      setAggregateFailure: (value) => {
        failAggregate = value;
      },
    });
    assert.deepEqual(unexpected, []);
    assert.deepEqual(consoleErrors, []);
  } finally {
    await act(async () => root.unmount());
    // Unmount owns polling, but never aborts the already-submitted research request.
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
  }
}

for (const id of ["general-chat", "project-chat"]) {
  test(`${id} keeps researching when another chat is selected and its saved completion does not navigate`, async (t) => {
    await withWorkspace(
      t,
      async ({
        openChat,
        chatButton,
        type,
        submit,
        tickAggregate,
        finish,
        pending,
        postCount,
        composer,
        calls,
      }) => {
        await openChat(id);
        await type("Synthetic background lifecycle request.");
        await submit();
        assert.equal(postCount(), 1);
        assert.ok(pending.has(id));
        const signal = pending.get(id).signal;
        assert.ok(
          chatButton(id).querySelector('[aria-label="Research running"]'),
        );
        await openChat("quiet-chat");
        assert.equal(
          signal.aborted,
          false,
          "navigation must not cancel the submitted request",
        );
        assert.ok(
          chatButton(id).querySelector('[aria-label="Research running"]'),
        );
        assert.equal(
          chatButton("quiet-chat").querySelector(
            '[aria-label="Research running"]',
          ),
          null,
          "ordinary chat loading does not show research",
        );
        const readsBefore = calls.filter(
          (call) => call.method === "GET" && call.path === `/api/chats/${id}`,
        ).length;
        await tickAggregate();
        assert.equal(
          calls.filter(
            (call) => call.method === "GET" && call.path === `/api/chats/${id}`,
          ).length,
          readsBefore + 1,
          "first aggregate observation reads the running chat identity even while another chat is selected",
        );
        assert.match(
          chatButton(id).textContent,
          id === "project-chat"
            ? /Early saved project title/
            : /Early saved general title/,
          "aggregate reconciliation fetches the server title before research completes",
        );
        assert.match(
          document.querySelector(".conversation-header h1").textContent,
          /Other saved question/,
        );
        await openChat(id);
        assert.equal(composer().disabled, true);
        assert.ok(document.querySelector('[aria-label="Research progress"]'));
        await submit();
        assert.equal(
          postCount(),
          1,
          "reentry does not submit the pending question again",
        );
        await openChat("quiet-chat");
        await finish(id);
        assert.equal(signal.aborted, false);
        assert.match(
          document.querySelector(".conversation-header h1").textContent,
          /Other saved question/,
          "completion must not force navigation",
        );
        assert.equal(
          chatButton(id).querySelector('[aria-label="Research running"]'),
          null,
        );
        await openChat(id);
        assert.match(
          document.querySelector(".message-history").textContent,
          new RegExp(`Saved synthetic response for ${id}`),
        );
        assert.equal(composer().disabled, false);
        assert.equal(postCount(), 1);
      },
    );
  });
}

test("aggregate server runs restore markers for inactive general and project chats without sending messages", async (t) => {
  await withWorkspace(
    t,
    async ({
      openChat,
      chatButton,
      tickAggregate,
      finish,
      postCount,
      composer,
      setAggregateFailure,
    }) => {
      assert.ok(
        chatButton("general-chat").querySelector(
          '[aria-label="Research running"]',
        ),
      );
      assert.ok(
        chatButton("project-chat").querySelector(
          '[aria-label="Research running"]',
        ),
      );
      await openChat("general-chat");
      assert.equal(composer().disabled, true);
      await openChat("quiet-chat");
      setAggregateFailure(true);
      await tickAggregate();
      assert.ok(
        chatButton("general-chat").querySelector(
          '[aria-label="Research running"]',
        ),
        "temporary status outage preserves last-known running state",
      );
      setAggregateFailure(false);
      await finish("general-chat");
      await tickAggregate();
      assert.equal(
        chatButton("general-chat").querySelector(
          '[aria-label="Research running"]',
        ),
        null,
      );
      assert.ok(
        chatButton("project-chat").querySelector(
          '[aria-label="Research running"]',
        ),
      );
      assert.match(
        document.querySelector(".conversation-header h1").textContent,
        /Other saved question/,
      );
      await openChat("general-chat");
      assert.match(
        document.querySelector(".message-history").textContent,
        /Saved synthetic response for general-chat/,
      );
      assert.equal(
        postCount(),
        0,
        "restoring existing runs only reads status and saved responses",
      );
      await finish("project-chat");
      await tickAggregate();
    },
    { external: true },
  );
});

for (const project of [false, true]) {
  test(`a new ${project ? "project" : "general"} chat opens immediately and its deferred response survives leaving the view`, async (t) => {
    await withWorkspace(
      t,
      async ({
        click,
        openProject,
        openChat,
        chatButton,
        type,
        submit,
        finish,
        pending,
        postCount,
      }) => {
        if (project) await openProject();
        const id = project ? "new-project-chat" : "new-general-chat";
        await type("Synthetic first message in a new chat.");
        await submit();
        assert.equal(postCount(), 1);
        assert.ok(pending.has(id));
        assert.match(
          document.querySelector(".conversation-header h1").textContent,
          /Early saved (general|project) title/,
          "server-persisted first title is visible before the deferred response",
        );
        assert.ok(
          chatButton(id).querySelector('[aria-label="Research running"]'),
        );
        await openChat("quiet-chat");
        await finish(id);
        assert.match(
          document.querySelector(".conversation-header h1").textContent,
          /Other saved question/,
        );
        await openChat(id);
        assert.match(
          document.querySelector(".message-history").textContent,
          new RegExp(`Saved synthetic response for ${id}`),
        );
        assert.equal(postCount(), 1);
      },
    );
  });
}
