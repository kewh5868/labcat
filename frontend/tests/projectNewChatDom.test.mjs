import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { before, after, test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

// Navigation fixtures only. Every request is intercepted; no real workspace,
// provider, credentials, material evidence, or research engine is accessed.
let compiled;
before(async () => {
  compiled = await mkdtemp(join(tmpdir(), "labcat-project-plus-dom-"));
  for (const name of await readdir(new URL("../src/", import.meta.url))) {
    if (!/\.tsx?$/.test(name)) continue;
    const input = await readFile(
      new URL(`../src/${name}`, import.meta.url),
      "utf8",
    );
    const output = ts
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
    await writeFile(join(compiled, name.replace(/\.tsx?$/, ".js")), output);
  }
  await writeFile(join(compiled, "package.json"), '{"type":"module"}');
});
after(async () => {
  await rm(compiled, { recursive: true, force: true });
});

async function workspace(t, check, options = {}) {
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
  const at = "2026-09-11T12:00:00Z";
  const counts = { reports: 0, sources: 0 };
  let projects = ["Alpha", "Beta"].map((name, index) => ({
    id: `project-${index + 1}`,
    name: `${name} fixture`,
    description: "",
    created_at: at,
    updated_at: at,
    chat_count: 1,
    pin_counts: counts,
  }));
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
  let chats = [
    makeChat("chat-alpha", "project-1", "Alpha saved chat", 1),
    makeChat("chat-beta", "project-2", "Beta saved chat", 2),
    makeChat("chat-general", null, "General saved chat", 3),
  ];
  if (options.extraGeneral)
    chats.push(makeChat("general-second", null, "Second general chat", 4));
  if (options.emptyGeneral)
    chats = chats.filter((chat) => chat.project_id !== null);
  let clearResponse = null,
    failRead = false;
  const messages = new Map();
  const detail = (chat) => ({
    chat,
    messages: messages.get(chat.id) ?? [],
    reports: [],
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
  const calls = [],
    unexpected = [],
    consoleErrors = [];
  t.mock.method(console, "error", (...args) =>
    consoleErrors.push(args.join(" ")),
  );
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    if (path === "/api/research-runs") return Response.json({ runs: [] });
    const method = options.method ?? "GET",
      body = options.body ? JSON.parse(options.body) : null;
    calls.push({ path, method, body });
    if (path === "/api/session")
      return Response.json({ csrf_token: "TEST_PROJECT_NAVIGATION_CSRF" });
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
          model: "synthetic-navigation-model",
          account_id: "synthetic-navigation-account",
          message: "Synthetic navigation readiness only.",
          checked_at: at,
        },
        optional: {
          compute: "local",
          aws_required: false,
          data_apis_required: false,
        },
      });
    if (path === "/api/projects") return Response.json({ projects });
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
        message: "Synthetic runtime metadata.",
      });
    if (path === "/api/workspace/preferences")
      return Response.json({ confirm_removal: false });
    const contents = path.match(/^\/api\/projects\/([^/]+)\/contents$/);
    if (contents)
      return Response.json({
        chats: chats.filter((chat) => chat.project_id === contents[1]),
        reports: [],
        sources: [],
      });
    const removedProject = path.match(/^\/api\/projects\/([^/]+)$/);
    if (removedProject && method === "DELETE") {
      projects = projects.filter(({ id }) => id !== removedProject[1]);
      chats = chats.filter(
        ({ project_id }) => project_id !== removedProject[1],
      );
      return Response.json({});
    }
    const draftProject = path.match(/^\/api\/projects\/([^/]+)\/draft-chat$/);
    if (draftProject && method === "POST") {
      assert.ok(
        projects.some(({ id }) => id === draftProject[1]),
        "new draft belongs to a currently available project",
      );
      const chat = makeChat(
        `created-${chats.length + 1}`,
        draftProject[1],
        "New scoped fixture chat",
        chats.length + 1,
      );
      chats.push(chat);
      return Response.json(chat);
    }
    if (path === "/api/general-chats" && method === "DELETE") {
      assert.equal(
        options.headers["X-CSRF-Token"],
        "TEST_PROJECT_NAVIGATION_CSRF",
      );
      if (clearResponse) return clearResponse(body);
      const current = chats
        .filter((chat) => chat.project_id === null)
        .map((chat) => chat.id)
        .sort();
      if (JSON.stringify(current) !== JSON.stringify([...body.snapshot].sort()))
        return Response.json(
          {
            detail:
              "General chats changed. Review the updated list and try again.",
          },
          { status: 409 },
        );
      chats = chats.filter((chat) => !body.snapshot.includes(chat.id));
      return Response.json({ removed_chats: current.length });
    }
    if (path === "/api/chats") {
      if (failRead && method === "GET")
        return Response.json({}, { status: 500 });
      if (method === "POST") {
        const chat = makeChat(
          `created-${chats.length + 1}`,
          body.project_id,
          body.title,
          chats.length + 1,
        );
        chats.push(chat);
        return Response.json(chat);
      }
      return Response.json({ chats });
    }
    const message = path.match(/^\/api\/chats\/([^/]+)\/messages$/);
    if (message && method === "POST") {
      const chat = chats.find(({ id }) => id === message[1]);
      assert.ok(chat);
      messages.set(chat.id, [
        {
          id: `message-${chat.id}`,
          chat_id: chat.id,
          role: "user",
          content: body.content,
          report_id: null,
          created_at: at,
        },
      ]);
      chat.message_count = 1;
      return Response.json(detail(chat));
    }
    if (/\/research-status\?/.test(path))
      return Response.json({
        run_id: null,
        status: "idle",
        phase: "idle",
        message: "Synthetic navigation test.",
        started_at: null,
        updated_at: null,
        sequence: 0,
      });
    const chatPath = path.match(/^\/api\/chats\/([^/]+)$/);
    if (chatPath) {
      const chat = chats.find(({ id }) => id === chatPath[1]);
      assert.ok(chat);
      return Response.json(detail(chat));
    }
    unexpected.push(`${method} ${path}`);
    throw new Error(`Unexpected synthetic test request: ${path}`);
  });
  const root = createRoot(document.getElementById("root"));
  const click = async (element) => {
    assert.ok(element, "navigation control exists");
    await act(async () =>
      element.dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true }),
      ),
    );
  };
  const project = (name) =>
    [...document.querySelectorAll(".project-nav-item")].find((item) =>
      item.textContent.includes(name),
    );
  const plus = () => {
    const item = document.querySelector(".project-new-chat");
    assert.ok(item, "PROJECTS heading has its scoped new-chat button");
    return item;
  };
  const composer = () => {
    const fields = document.querySelectorAll('textarea[maxlength="20000"]');
    assert.equal(fields.length, 1);
    return fields[0];
  };
  const type = async (value) => {
    await act(async () => {
      const field = composer();
      Object.getOwnPropertyDescriptor(
        dom.window.HTMLTextAreaElement.prototype,
        "value",
      ).set.call(field, value);
      field.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
  };
  const writes = () => calls.filter(({ method }) => method !== "GET");
  const inactive = () => {
    assert.equal(plus().disabled, true);
    assert.equal(
      plus().getAttribute("aria-label"),
      "Select a project to start a chat",
    );
    assert.equal(
      document.querySelectorAll(".project-nav-item.selected").length,
      0,
    );
  };
  const scoped = (name, isPage = false) => {
    assert.equal(plus().disabled, false);
    assert.equal(plus().getAttribute("aria-label"), `New chat in ${name}`);
    assert.deepEqual(
      [...document.querySelectorAll(".project-nav-item.selected")],
      [project(name)],
    );
    assert.equal(
      project(name).getAttribute("aria-current"),
      isPage ? "page" : null,
    );
  };
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
      click,
      project,
      plus,
      composer,
      type,
      writes,
      inactive,
      scoped,
      calls,
      act,
      dom,
      setClearResponse: (value) => {
        clearResponse = value;
      },
      setFailRead: (value) => {
        failRead = value;
      },
      addGeneral: () => {
        chats.push(makeChat("added-general", null, "Later general chat", 9));
      },
    });
    assert.deepEqual(unexpected, []);
    assert.deepEqual(consoleErrors, []);
  } finally {
    await act(async () => root.unmount());
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
  }
}

test("PROJECTS plus starts a focused blank draft in the highlighted project without saving empty chats", async (t) => {
  await workspace(
    t,
    async ({
      click,
      project,
      plus,
      composer,
      type,
      writes,
      inactive,
      scoped,
    }) => {
      inactive();
      assert.ok(plus().closest(".project-list-heading"));
      for (const name of ["Alpha fixture", "Beta fixture"]) {
        await click(project(name));
        scoped(name, true);
        await click(plus());
        scoped(name);
        assert.equal(composer().value, "");
        assert.equal(document.activeElement, composer());
        assert.match(
          document.querySelector(".draft-project-badge").textContent,
          new RegExp(name),
        );
        await type("Unsaved synthetic draft");
        await click(plus());
        assert.equal(composer().value, "");
        assert.equal(document.activeElement, composer());
        scoped(name);
      }
      assert.deepEqual(
        writes(),
        [],
        "opening or resetting scoped drafts must not create empty saved chats",
      );
    },
  );
});

test("a project chat owns the plus target even when another project page was selected previously", async (t) => {
  await workspace(t, async ({ click, project, plus, scoped, writes }) => {
    await click(project("Alpha fixture"));
    await click(document.querySelector('[aria-label="Expand Beta fixture"]'));
    await click(
      [...document.querySelectorAll(".global-chat-item")].find((item) =>
        item.textContent.includes("Beta saved chat"),
      ),
    );
    scoped("Beta fixture");
    assert.equal(
      document
        .querySelector(".global-chat-item.selected")
        .getAttribute("aria-current"),
      "page",
    );
    await click(document.querySelector('[aria-label="Collapse Beta fixture"]'));
    assert.equal(document.getElementById("project-chats-project-2"), null);
    scoped("Beta fixture");
    await click(plus());
    assert.ok(
      document.getElementById("project-chats-project-2"),
      "opening a draft reveals its owning project",
    );
    assert.match(
      document.querySelector(".draft-project-badge").textContent,
      /Beta fixture/,
    );
    scoped("Beta fixture");
    assert.deepEqual(writes(), []);
  });
});

test("general chats and other modes cannot inherit a stale project as the plus target", async (t) => {
  await workspace(
    t,
    async ({ click, project, plus, writes, inactive, scoped }) => {
      await click(project("Alpha fixture"));
      await click(plus());
      scoped("Alpha fixture");
      await click(document.querySelector(".sidebar-new-chat"));
      inactive();
      assert.equal(document.querySelector(".draft-project-badge"), null);
      await click(project("Beta fixture"));
      await click(
        [...document.querySelectorAll(".global-chat-item")].find((item) =>
          item.textContent.includes("General saved chat"),
        ),
      );
      inactive();
      for (const select of [
        () => document.querySelector(".sidebar-create-project"),
        ...["Report Format", "Search Criterion", "Connections"].map(
          (name) => () =>
            [...document.querySelectorAll(".sidebar-bottom-nav button")].find(
              (button) => button.textContent.trim().endsWith(name),
            ),
        ),
      ]) {
        await click(project("Alpha fixture"));
        scoped("Alpha fixture", true);
        await click(select());
        inactive();
      }
      assert.deepEqual(writes(), []);
    },
  );
});

test("first send creates exactly one chat through the chosen project draft endpoint", async (t) => {
  await workspace(t, async ({ click, project, plus, type, writes, scoped }) => {
    await click(project("Alpha fixture"));
    await click(project("Beta fixture"));
    await click(plus());
    await type("Synthetic navigation test request.");
    await click(document.querySelector('[aria-label="Send message"]'));
    assert.equal(writes().length, 2);
    assert.equal(writes()[0].path, "/api/projects/project-2/draft-chat");
    assert.equal(writes()[0].method, "POST");
    assert.equal(writes()[1].path, "/api/chats/created-4/messages");
    assert.equal(
      writes()[1].body.content,
      "Synthetic navigation test request.",
    );
    assert.equal(writes()[1].body.ranking_profile_id, "infer");
    assert.ok(
      !writes().some(
        ({ path }) => path === "/api/chats" || path.includes("/project-1/"),
      ),
    );
    scoped("Beta fixture");
  });
});

test("project removal uses the draft owning scope rather than the last project page", async (t) => {
  await workspace(
    t,
    async ({
      click,
      project,
      plus,
      composer,
      type,
      writes,
      inactive,
      scoped,
    }) => {
      await click(project("Alpha fixture"));
      await click(document.querySelector('[aria-label="Expand Beta fixture"]'));
      await click(
        [...document.querySelectorAll(".global-chat-item")].find((item) =>
          item.textContent.includes("Beta saved chat"),
        ),
      );
      await click(plus());
      await type("Preserve this unsaved Beta fixture draft.");
      await click(
        document.querySelector(
          '[aria-label="Actions for project Alpha fixture"]',
        ),
      );
      await click(
        [...document.querySelectorAll('[role="menuitem"]')].find(
          (button) => button.textContent === "Remove project",
        ),
      );
      assert.equal(project("Alpha fixture"), undefined);
      scoped("Beta fixture");
      assert.equal(
        composer().value,
        "Preserve this unsaved Beta fixture draft.",
        "removing the unrelated previously viewed project preserves the active draft",
      );
      assert.match(
        document.querySelector(".draft-project-badge").textContent,
        /Beta fixture/,
      );
      await click(
        document.querySelector(
          '[aria-label="Actions for project Beta fixture"]',
        ),
      );
      await click(
        [...document.querySelectorAll('[role="menuitem"]')].find(
          (button) => button.textContent === "Remove project",
        ),
      );
      inactive();
      assert.equal(project("Beta fixture"), undefined);
      assert.equal(
        composer().value,
        "",
        "removing the owning project must not turn its typed draft into an unscoped chat",
      );
      assert.equal(document.querySelector(".draft-project-badge"), null);
      assert.deepEqual(
        writes().map(({ path, method }) => ({ path, method })),
        [
          { path: "/api/projects/project-1", method: "DELETE" },
          { path: "/api/projects/project-2", method: "DELETE" },
        ],
      );
    },
  );
});

const clearButton = () => document.querySelector(".general-chats-clear");
const dialogButton = (name) =>
  [...document.querySelectorAll(".clear-general-chats-dialog button")].find(
    (button) => button.textContent === name,
  );
const generalChat = () =>
  document.querySelector(".all-chat-list .global-chat-item");

test("clear all always confirms the reviewed count with Cancel focused and restores removed active general chat to landing", async (t) => {
  await workspace(
    t,
    async ({ click, calls, writes, composer }) => {
      assert.ok(clearButton().closest(".all-chats-heading"));
      await click(generalChat());
      await click(clearButton());
      const dialog = document.querySelector(".clear-general-chats-dialog");
      assert.equal(dialog.querySelector("h2").textContent, "Are you sure?");
      assert.match(dialog.textContent, /2 general chats/);
      assert.match(
        dialog.textContent,
        /restored from Removed items for 30 days/,
      );
      assert.equal(document.activeElement, dialogButton("Cancel"));
      assert.equal(dialog.querySelector('input[type="checkbox"]'), null);
      assert.ok(dialog.getAttribute("aria-labelledby"));
      assert.ok(dialog.getAttribute("aria-describedby"));
      await click(dialogButton("Cancel"));
      assert.equal(document.querySelector("dialog"), null);
      assert.deepEqual(writes(), []);
      await click(clearButton());
      await click(dialogButton("Clear all general chats"));
      assert.equal(document.querySelector("dialog"), null);
      assert.equal(
        document.querySelectorAll(".all-chat-list .global-chat-item").length,
        0,
      );
      assert.equal(clearButton().disabled, true);
      assert.equal(composer().value, "");
      assert.equal(document.querySelectorAll(".project-nav-item").length, 2);
      assert.match(
        document.querySelector(".general-chats-notice").textContent,
        /2 general chats moved to Removed items/,
      );
      assert.deepEqual(
        writes().map(({ path, body }) => ({ path, body })),
        [
          {
            path: "/api/general-chats",
            body: {
              confirm: true,
              snapshot: ["chat-general", "general-second"],
            },
          },
        ],
      );
      assert.ok(
        !calls.some(({ path }) => path === "/api/workspace/preferences"),
        "single-item preference is never consulted",
      );
    },
    { extraGeneral: true },
  );
});

test("bulk clearing preserves the active project and rejects duplicate submits and cancellation while busy", async (t) => {
  await workspace(
    t,
    async ({ click, project, scoped, setClearResponse, writes, act, dom }) => {
      await click(project("Beta fixture"));
      scoped("Beta fixture", true);
      let finish;
      setClearResponse(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      );
      await click(clearButton());
      const dialog = document.querySelector(".clear-general-chats-dialog");
      await act(async () => {
        dialog
          .querySelector("form")
          .dispatchEvent(
            new dom.window.Event("submit", { bubbles: true, cancelable: true }),
          );
        dialog
          .querySelector("form")
          .dispatchEvent(
            new dom.window.Event("submit", { bubbles: true, cancelable: true }),
          );
      });
      assert.equal(writes().length, 1);
      assert.equal(dialogButton("Cancel").disabled, true);
      assert.equal(clearButton().disabled, true);
      await act(async () =>
        dialog.dispatchEvent(
          new dom.window.Event("cancel", { cancelable: true }),
        ),
      );
      assert.equal(document.querySelector("dialog"), dialog);
      await act(async () => finish(Response.json({ removed_chats: 1 })));
      scoped("Beta fixture", true);
      assert.equal(document.querySelector("dialog"), null);
      assert.equal(
        document.querySelector(".project-heading h1").textContent,
        "Beta fixture",
      );
    },
  );
});

test("a changed general chat list refreshes after conflict and requires a new count and confirmation", async (t) => {
  await workspace(t, async ({ click, addGeneral, writes }) => {
    await click(clearButton());
    addGeneral();
    assert.match(
      document.querySelector("dialog").textContent,
      /1 general chat/,
    );
    await click(dialogButton("Clear all general chats"));
    assert.equal(writes().length, 1);
    assert.deepEqual(writes()[0].body.snapshot, ["chat-general"]);
    assert.equal(document.querySelector("dialog"), null);
    assert.equal(
      document.querySelectorAll(".all-chat-list .global-chat-item").length,
      2,
    );
    assert.match(
      document.querySelector(".general-chats-error").textContent,
      /list has been refreshed.*open Clear all again/,
    );
    await click(clearButton());
    assert.match(
      document.querySelector("dialog").textContent,
      /2 general chats/,
    );
    assert.equal(writes().length, 1);
    await click(dialogButton("Clear all general chats"));
    assert.equal(writes().length, 2);
    assert.deepEqual(writes()[1].body.snapshot, [
      "chat-general",
      "added-general",
    ]);
    assert.equal(
      document.querySelectorAll(".all-chat-list .global-chat-item").length,
      0,
    );
  });
});

test("failed clearing keeps chats and requires an explicit successful refresh before a new confirmation", async (t) => {
  await workspace(
    t,
    async ({ click, setClearResponse, setFailRead, writes }) => {
      await click(generalChat());
      setClearResponse(() => Response.json({}, { status: 500 }));
      await click(clearButton());
      await click(dialogButton("Clear all general chats"));
      assert.equal(writes().length, 1);
      assert.ok(generalChat());
      assert.ok(document.querySelector(".global-chat-item.selected"));
      assert.equal(clearButton().disabled, true);
      const refresh = () =>
        [...document.querySelectorAll(".general-chats-error button")].find(
          (button) => button.textContent === "Refresh general chats",
        );
      setFailRead(true);
      await click(refresh());
      assert.equal(clearButton().disabled, true);
      assert.ok(refresh());
      assert.equal(writes().length, 1);
      setFailRead(false);
      await click(refresh());
      assert.equal(clearButton().disabled, false);
      setClearResponse(null);
      await click(clearButton());
      assert.equal(writes().length, 1);
      await click(dialogButton("Cancel"));
    },
  );
});

test("clear all is disabled when General chats is empty", async (t) => {
  await workspace(
    t,
    async ({ click, writes }) => {
      assert.equal(clearButton().disabled, true);
      await click(clearButton());
      assert.equal(document.querySelector("dialog"), null);
      assert.deepEqual(writes(), []);
    },
    { emptyGeneral: true },
  );
});

test("research conflict shows its wait reason and never automatically resubmits removal", async (t) => {
  await workspace(t, async ({ click, setClearResponse, writes }) => {
    setClearResponse(() =>
      Response.json(
        {
          detail:
            "A general chat is still researching. Wait for it to finish, then try again.",
        },
        { status: 409 },
      ),
    );
    await click(clearButton());
    await click(dialogButton("Clear all general chats"));
    assert.equal(writes().length, 1);
    assert.ok(generalChat());
    assert.match(
      document.querySelector(".general-chats-error").textContent,
      /still researching.*Wait for it to finish/,
    );
    assert.equal(document.querySelector("dialog"), null);
    await click(clearButton());
    assert.equal(writes().length, 1);
    await click(dialogButton("Cancel"));
  });
});

test("clearing General chats preserves an open project chat and its project selection", async (t) => {
  await workspace(t, async ({ click, project, scoped, writes }) => {
    await click(project("Alpha fixture"));
    await click(
      document.querySelector("#project-chats-project-1 .global-chat-item"),
    );
    scoped("Alpha fixture");
    const selected = document.querySelector(
      ".global-chat-item.selected",
    ).textContent;
    await click(clearButton());
    await click(dialogButton("Clear all general chats"));
    scoped("Alpha fixture");
    assert.equal(
      document.querySelector(".global-chat-item.selected").textContent,
      selected,
    );
    assert.equal(writes().length, 1);
  });
});
