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

async function harness() {
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
  const root = createRoot(document.getElementById("root"));
  return {
    dom,
    root,
    createElement,
    act,
    load: (name) => import(pathToFileURL(join(output, `${name}.js`)).href),
    click: async (element) => {
      assert.ok(element);
      await act(async () =>
        element.dispatchEvent(
          new dom.window.MouseEvent("click", { bubbles: true }),
        ),
      );
    },
    async close() {
      await act(async () => root.unmount());
      dom.window.close();
      for (const key of globals) {
        if (previous[key])
          Object.defineProperty(globalThis, key, previous[key]);
        else delete globalThis[key];
      }
      await rm(output, { recursive: true, force: true });
    },
  };
}

const namedButton = (name, scope = document) =>
  [...scope.querySelectorAll("button")].find(
    (item) => item.textContent.trim() === name,
  );
const createDestination = () =>
  [...document.querySelectorAll(".move-chat-dialog label")]
    .find((label) => label.textContent.includes("Create new project"))
    ?.querySelector('input[type="radio"]');
const fieldNamed = (name) => {
  const label = [...document.querySelectorAll(".move-chat-dialog label")].find(
    (item) => item.textContent.trim().startsWith(name),
  );
  assert.ok(label, `missing ${name} field`);
  return label.htmlFor
    ? document.getElementById(label.htmlFor)
    : label.querySelector("input, textarea");
};
async function typeValue(h, input, value) {
  assert.ok(input);
  await h.act(async () => {
    const prototype =
      input.tagName === "TEXTAREA"
        ? h.dom.window.HTMLTextAreaElement.prototype
        : h.dom.window.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(input, value);
    input.dispatchEvent(new h.dom.window.Event("input", { bubbles: true }));
  });
}

test("chat numbers distinguish duplicates and moving from the menu preserves drafts, history and explicit pins", async (t) => {
  const h = await harness();
  const { root, act, createElement, click } = h;
  const { default: Workspace } = await h.load("ProjectWorkspace");
  const { ConnectionsProvider } = await h.load("Connections");
  const { SetupProvider } = await h.load("SetupWizard");
  const { defaultSettings } = await h.load("workspaceApi");
  const at = "2026-09-10T00:00:00Z";
  const project = (id, name) => ({
    id,
    name,
    description: "",
    created_at: at,
    updated_at: at,
    chat_count: 1,
    pin_counts: { reports: 0, sources: 0 },
  });
  const projects = [
    project("project-a", "Project A"),
    project("project-b", "Project B"),
  ];
  const chat = (id, title, number, project_id = null) => ({
    id,
    title,
    chat_number: number,
    display_title: `${title} · #${number}`,
    project_id,
    created_at: at,
    updated_at: at,
    pin_counts: { reports: 0, sources: 0 },
    message_count: 2,
  });
  const longTitle =
    "A long research conversation name that should remain available in full on hover while the stable number stays visible";
  const chats = [
    chat("chat-one", "Same question", 11),
    chat("chat-two", "Same question", 12, "project-a"),
    chat("chat-large", longTitle, Number.MAX_SAFE_INTEGER),
  ];
  const messages = [
    {
      id: "request",
      chat_id: "chat-one",
      role: "user",
      content: "Synthetic navigation question.",
      report_id: null,
      created_at: at,
    },
    {
      id: "response",
      chat_id: "chat-one",
      role: "assistant",
      content: "Synthetic navigation response without research.",
      report_id: "report-one",
      created_at: at,
    },
  ];
  const report = {
    id: "report-one",
    project_id: null,
    chat_id: "chat-one",
    message_id: "response",
    title: "Navigation test report",
    stage: "complete",
    pi_summary: "Synthetic rendering text, not scientific evidence.",
    technical_audit: "Synthetic rendering text, not scientific evidence.",
    source_ids: [],
    created_at: at,
    pinned: false,
  };
  const detail = (id) => ({
    chat: chats.find((item) => item.id === id),
    messages: id === "chat-one" ? messages : [],
    reports: id === "chat-one" ? [report] : [],
    sources: [],
  });
  const status = {
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
  const moves = [],
    renames = [],
    pins = [],
    creations = [];
  let finishMove,
    finishCreate,
    deferMove = true,
    deferCreate = false,
    failMove = false;
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    if (path === "/api/projects") {
      if (options.method === "POST") {
        const body = JSON.parse(options.body);
        creations.push(body);
        if (deferCreate)
          await new Promise((resolve) => {
            finishCreate = resolve;
          });
        const created = {
          ...project(`created-${creations.length}`, body.name),
          description: body.description,
          chat_count: 0,
        };
        projects.push(created);
        return Response.json(created);
      }
      return Response.json({ projects });
    }
    if (path === "/api/chats") return Response.json({ chats });
    if (path === "/api/settings") return Response.json(defaultSettings);
    if (path === "/api/connections") return Response.json(status);
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
          model: "test-model",
          account_id: "test-account",
          message: "Synthetic navigation session.",
          checked_at: at,
        },
        optional: {
          compute: "local",
          aws_required: false,
          data_apis_required: false,
        },
      });
    if (path === "/api/projects/project-a/pins") {
      pins.push(JSON.parse(options.body));
      report.pinned = true;
      return Response.json({});
    }
    const id = /^\/api\/chats\/([^/]+)$/.exec(path)?.[1];
    if (id) {
      const item = chats.find((chat) => chat.id === id);
      if (options.method === "PATCH") {
        const body = JSON.parse(options.body);
        if (Object.hasOwn(body, "title")) {
          renames.push(body);
          item.title = body.title;
          item.display_title = `${item.title} · #${item.chat_number}`;
        } else {
          moves.push({ id, body });
          if (failMove)
            return Response.json(
              { detail: "Synthetic interrupted move." },
              { status: 503 },
            );
          if (deferMove)
            await new Promise((resolve) => {
              finishMove = resolve;
            });
          item.project_id = body.project_id;
          report.project_id = body.project_id;
          report.pinned = false;
        }
      }
      return Response.json(detail(id));
    }
    assert.fail(`unexpected request ${path}`);
  });
  const render = async () =>
    act(async () =>
      root.render(
        createElement(
          ConnectionsProvider,
          null,
          createElement(SetupProvider, null, createElement(Workspace)),
        ),
      ),
    );
  const menu = async (number, action) => {
    await click(
      [...document.querySelectorAll(".sidebar-menu-trigger")].find((item) =>
        item.getAttribute("aria-label").endsWith(`#${number}`),
      ),
    );
    await click(namedButton(action));
  };
  try {
    await render();
    const large = [...document.querySelectorAll(".global-chat-item")].find(
      (item) => item.textContent.includes(`#${Number.MAX_SAFE_INTEGER}`),
    );
    assert.equal(
      large.querySelector(".chat-identity").title,
      `${longTitle} · #${Number.MAX_SAFE_INTEGER}`,
    );
    assert.equal(
      large.querySelector(".chat-number").getAttribute("aria-hidden"),
      null,
    );
    assert.equal(
      large.querySelector(".chat-identity-title").textContent,
      longTitle,
    );
    await click(document.querySelector('[aria-label="Expand Project A"]'));
    const duplicates = [
      ...document.querySelectorAll(".global-chat-item"),
    ].filter((item) => item.textContent.includes("Same question"));
    assert.equal(duplicates.length, 2);
    assert.notEqual(duplicates[0].textContent, duplicates[1].textContent);
    await click(duplicates.find((item) => item.textContent.includes("#11")));
    const composer = document.querySelector('textarea[maxlength="20000"]');
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        h.dom.window.HTMLTextAreaElement.prototype,
        "value",
      ).set.call(composer, "Preserve this unsent draft");
      composer.dispatchEvent(
        new h.dom.window.Event("input", { bubbles: true }),
      );
    });
    assert.equal(document.querySelector("#chat-project"), null);
    assert.equal(document.querySelector(".chat-project-control"), null);
    assert.ok(document.querySelector(".composer-model-button"));
    assert.equal(
      document.querySelector(".chat-scope-label").textContent,
      "General Chats",
    );
    await menu(11, "Rename chat");
    assert.equal(
      document.querySelector("#item-name").value,
      "Same question",
      "number is never inserted into editable name",
    );
    assert.match(
      document.querySelector("dialog").textContent,
      /Chat #11 keeps this number/,
    );
    await act(async () => {
      const input = document.querySelector("#item-name");
      Object.getOwnPropertyDescriptor(
        h.dom.window.HTMLInputElement.prototype,
        "value",
      ).set.call(input, "Renamed question");
      input.dispatchEvent(new h.dom.window.Event("input", { bubbles: true }));
    });
    await click(namedButton("Save name", document.querySelector("dialog")));
    assert.deepEqual(renames, [{ title: "Renamed question" }]);
    assert.match(
      document.querySelector(".conversation-header h1").textContent,
      /Renamed question · #11/,
    );
    await click(namedButton("⌑Pin tracking"));
    assert.match(
      document.querySelector(".move-chat-dialog").textContent,
      /After moving, select Pin/,
    );
    await click(namedButton("Cancel", document.querySelector("dialog")));
    assert.equal(
      moves.length,
      0,
      "tracking in a general chat also asks for a project without moving or pinning automatically",
    );
    await click(namedButton("⌑Pin snapshot"));
    assert.match(
      document.querySelector(".move-chat-dialog").textContent,
      /After moving, select Pin/,
    );
    await click(
      document.querySelector(
        'input[name="chat-destination"][value="project-a"]',
      ),
    );
    await click(namedButton("Move chat", document.querySelector("dialog")));
    assert.ok(
      [...document.querySelectorAll(".sidebar-menu-trigger")].every(
        (button) => button.disabled,
      ),
      "project and chat mutations stay disabled during a move",
    );
    assert.equal(moves.length, 1);
    assert.deepEqual(moves[0], {
      id: "chat-one",
      body: { project_id: "project-a" },
    });
    await act(async () =>
      document
        .querySelector("dialog form")
        .dispatchEvent(
          new h.dom.window.Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
    assert.equal(moves.length, 1, "repeated submit while moving is ignored");
    await act(async () => finishMove());
    deferMove = false;
    assert.equal(document.querySelector("dialog"), null);
    assert.equal(
      document.querySelector(".chat-scope-label").textContent,
      "Project A",
    );
    assert.equal(composer.value, "Preserve this unsent draft");
    assert.equal(
      document.querySelector('textarea[maxlength="20000"]'),
      composer,
    );
    assert.equal(
      document.querySelectorAll('textarea[maxlength="20000"]').length,
      1,
    );
    assert.equal(pins.length, 0, "moving never implicitly pins a report");
    await click(namedButton("⌑Pin snapshot"));
    assert.deepEqual(pins, [{ kind: "report", target_id: "report-one" }]);
    await menu(11, "Move chat");
    assert.equal(
      document.querySelector('input[value="project-a"]').checked,
      true,
    );
    await click(
      document.querySelector('input[name="chat-destination"][value=""]'),
    );
    assert.match(
      document.querySelector(".move-chat-note").textContent,
      /report pins are cleared/,
    );
    await click(namedButton("Move chat", document.querySelector("dialog")));
    assert.deepEqual(moves.at(-1), {
      id: "chat-one",
      body: { project_id: null },
    });
    assert.equal(
      document.querySelector(".chat-scope-label").textContent,
      "General Chats",
    );
    assert.equal(report.pinned, false);
    assert.equal(composer.value, "Preserve this unsent draft");
    assert.equal(chats[0].chat_number, 11);
    assert.ok(document.querySelector(".composer-model-button"));
    assert.equal(document.querySelector("#chat-project"), null);
    await menu(11, "Move chat");
    await click(namedButton("Cancel", document.querySelector("dialog")));
    assert.equal(moves.length, 2);
    // Create and move are one user action, retaining the open chat and report.
    await menu(11, "Move chat");
    await click(createDestination());
    await typeValue(h, fieldNamed("Project name"), "  New investigation  ");
    await typeValue(
      h,
      fieldNamed("Description"),
      "  Organize this saved conversation.  ",
    );
    deferCreate = true;
    await click(
      namedButton(
        "Create project and move chat",
        document.querySelector("dialog"),
      ),
    );
    assert.equal(creations.length, 1);
    assert.equal(moves.length, 2, "move waits for the new project");
    assert.ok(
      [...document.querySelectorAll(".sidebar-menu-trigger")].every(
        (button) => button.disabled,
      ),
      "both stages lock workspace mutations",
    );
    await act(async () =>
      document
        .querySelector("dialog form")
        .dispatchEvent(
          new h.dom.window.Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
    assert.equal(
      creations.length,
      1,
      "repeated submit cannot create a second project",
    );
    await act(async () => finishCreate());
    deferCreate = false;
    assert.deepEqual(creations[0], {
      name: "New investigation",
      description: "Organize this saved conversation.",
    });
    assert.deepEqual(moves.at(-1), {
      id: "chat-one",
      body: { project_id: "created-1" },
    });
    assert.equal(document.querySelector("dialog"), null);
    assert.equal(
      document.querySelector(".chat-scope-label").textContent,
      "New investigation",
    );
    assert.equal(
      document.querySelector('textarea[maxlength="20000"]'),
      composer,
    );
    assert.equal(composer.value, "Preserve this unsent draft");
    assert.ok(
      document.querySelector('[aria-label="Collapse New investigation"]'),
      "new project is expanded in the sidebar",
    );
    assert.ok(
      document.querySelector(
        '.research-report[aria-label="Navigation test report"]',
      ),
      "existing saved report remains in the conversation",
    );
    assert.equal(chats[0].chat_number, 11);
    assert.equal(report.id, "report-one");
    assert.equal(
      pins.length,
      1,
      "creating a project never implicitly pins the report",
    );

    // A successful create followed by an interrupted move must not lose the
    // project, retry either write automatically, or clear the conversation.
    await menu(11, "Move chat");
    await click(createDestination());
    await typeValue(
      h,
      fieldNamed("Project name"),
      "Keep after interrupted move",
    );
    failMove = true;
    await click(
      namedButton(
        "Create project and move chat",
        document.querySelector("dialog"),
      ),
    );
    assert.equal(creations.length, 2);
    assert.equal(moves.length, 4);
    assert.ok(document.querySelector('dialog [role="alert"]'));
    assert.match(document.querySelector("dialog").textContent, /Close/);
    await act(async () =>
      document
        .querySelector("dialog form")
        .dispatchEvent(
          new h.dom.window.Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
    assert.equal(creations.length, 2);
    assert.equal(
      moves.length,
      4,
      "uncertain failure never repeats either write",
    );
    assert.ok(
      document.querySelector(
        '[aria-label="Expand Keep after interrupted move"], [aria-label="Collapse Keep after interrupted move"]',
      ),
      "created project remains available after a failed move",
    );
    await click(namedButton("Close", document.querySelector("dialog")));
    failMove = false;
    await click(namedButton("Check saved project"));
    assert.equal(
      document.querySelector(".chat-scope-label").textContent,
      "New investigation",
    );
    assert.equal(composer.value, "Preserve this unsent draft");
    await menu(11, "Move chat");
    await click(
      document.querySelector(
        'input[name="chat-destination"][value="created-2"]',
      ),
    );
    await click(namedButton("Move chat", document.querySelector("dialog")));
    assert.equal(
      creations.length,
      2,
      "recovery can use the existing project without making a duplicate",
    );
    assert.deepEqual(moves.at(-1), {
      id: "chat-one",
      body: { project_id: "created-2" },
    });
    assert.equal(
      document.querySelector(".chat-scope-label").textContent,
      "Keep after interrupted move",
    );
  } finally {
    await h.close();
  }
});

const moveChatFixture = {
  id: "chat-dialog",
  title: "Saved investigation",
  chat_number: 17,
  display_title: "Saved investigation · #17",
  project_id: null,
  created_at: "2026-09-23T00:00:00Z",
  updated_at: "2026-09-23T00:00:00Z",
  pin_counts: { reports: 0, sources: 0 },
  message_count: 2,
};

test("empty workspace can create a project in Move chat with trimmed fields and no duplicate submission", async () => {
  const h = await harness();
  const { default: Dialog } = await h.load("MoveChatDialog");
  const calls = [],
    moves = [];
  let finish,
    cancels = 0;
  try {
    await h.act(async () =>
      h.root.render(
        h.createElement(Dialog, {
          chat: moveChatFixture,
          projects: [],
          forPin: true,
          onCancel: () => {
            cancels += 1;
          },
          onMove: async (...args) => moves.push(args),
          onCreateAndMove: async (...args) => {
            calls.push(args);
            await new Promise((resolve) => {
              finish = resolve;
            });
          },
        }),
      ),
    );
    assert.ok(
      createDestination(),
      "create option is available before any project exists",
    );
    assert.doesNotMatch(
      document.querySelector("dialog").textContent,
      /Create a project from the sidebar/,
    );
    assert.ok(
      namedButton("Move chat").disabled,
      "unchanged General Chats is not an actionable move",
    );
    await h.click(createDestination());
    const name = fieldNamed("Project name"),
      description = fieldNamed("Description");
    assert.equal(name.maxLength, 120);
    assert.equal(name.required, true);
    assert.equal(description.maxLength, 2000);
    assert.ok(namedButton("Create project and move chat").disabled);
    await typeValue(h, name, "   ");
    await h.act(async () =>
      document
        .querySelector("dialog form")
        .dispatchEvent(
          new h.dom.window.Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
    assert.equal(
      calls.length,
      0,
      "whitespace cannot create a project even with a programmatic submit",
    );
    await typeValue(h, name, "  Thin films  ");
    await typeValue(h, description, "  Compare questions  ");
    await h.click(namedButton("Create project and move chat"));
    assert.deepEqual(calls, [
      [moveChatFixture, "Thin films", "Compare questions"],
    ]);
    assert.deepEqual(moves, []);
    assert.ok(name.disabled || name.closest("fieldset")?.disabled);
    assert.ok(namedButton("Cancel").disabled);
    const cancelEvent = new h.dom.window.Event("cancel", { cancelable: true });
    await h.act(async () =>
      document.querySelector("dialog").dispatchEvent(cancelEvent),
    );
    assert.equal(
      cancelEvent.defaultPrevented,
      true,
      "native dialog cancellation is prevented",
    );
    assert.equal(cancels, 0, "Escape cannot close an in-flight operation");
    await h.act(async () =>
      document
        .querySelector("dialog form")
        .dispatchEvent(
          new h.dom.window.Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
    assert.equal(calls.length, 1);
    await h.act(async () => finish());
  } finally {
    await h.close();
  }
});

test("Move chat keeps create drafts when switching destinations and cancel performs no writes", async () => {
  const h = await harness();
  const { default: Dialog } = await h.load("MoveChatDialog");
  const writes = [];
  let cancels = 0;
  const project = {
    id: "existing",
    name: "Existing project",
    description: "",
    created_at: "2026-09-23T00:00:00Z",
    updated_at: "2026-09-23T00:00:00Z",
    chat_count: 0,
    pin_counts: { reports: 0, sources: 0 },
  };
  try {
    await h.act(async () =>
      h.root.render(
        h.createElement(Dialog, {
          chat: moveChatFixture,
          projects: [project],
          onCancel: () => {
            cancels += 1;
          },
          onMove: async (...args) => writes.push(args),
          onCreateAndMove: async (...args) => writes.push(args),
        }),
      ),
    );
    await h.click(createDestination());
    await typeValue(h, fieldNamed("Project name"), "Draft project");
    await typeValue(h, fieldNamed("Description"), "Keep this description");
    await h.click(
      document.querySelector(
        'input[name="chat-destination"][value="existing"]',
      ),
    );
    assert.ok(!namedButton("Move chat").disabled);
    await h.click(createDestination());
    assert.equal(fieldNamed("Project name").value, "Draft project");
    assert.equal(fieldNamed("Description").value, "Keep this description");
    await h.click(namedButton("Cancel"));
    assert.equal(cancels, 1);
    assert.deepEqual(writes, []);
    await h.click(
      document.querySelector(
        'input[name="chat-destination"][value="existing"]',
      ),
    );
    await h.click(namedButton("Move chat"));
    assert.deepEqual(
      writes,
      [[moveChatFixture, "existing"]],
      "existing project uses only the normal move callback",
    );
  } finally {
    await h.close();
  }
});

test("create-and-move failure requires closing and checking saved state before retrying", async () => {
  const h = await harness();
  const { default: Dialog } = await h.load("MoveChatDialog");
  let calls = 0,
    cancels = 0;
  try {
    await h.act(async () =>
      h.root.render(
        h.createElement(Dialog, {
          chat: moveChatFixture,
          projects: [],
          onCancel: () => {
            cancels += 1;
          },
          onMove: async () => assert.fail("normal move must not run"),
          onCreateAndMove: async () => {
            calls += 1;
            throw new Error("Connection interrupted");
          },
        }),
      ),
    );
    await h.click(createDestination());
    await typeValue(h, fieldNamed("Project name"), "Possibly saved");
    await h.click(namedButton("Create project and move chat"));
    assert.match(
      document.querySelector('[role="alert"]').textContent,
      /request could not be completed/,
    );
    assert.match(
      document.querySelector('[role="alert"]').textContent,
      /Close.*check/i,
    );
    assert.ok(document.querySelector('dialog button[type="submit"]').disabled);
    await h.act(async () =>
      document
        .querySelector("dialog form")
        .dispatchEvent(
          new h.dom.window.Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
    assert.equal(calls, 1);
    await h.click(namedButton("Close"));
    assert.equal(cancels, 1);
  } finally {
    await h.close();
  }
});
