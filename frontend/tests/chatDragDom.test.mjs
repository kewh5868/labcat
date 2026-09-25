import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

// Exercise the real React drag handlers and asynchronous chat refresh in a DOM.
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

// Synthetic navigation data only; these messages are not scientific evidence.
test("general chat drops move once, preserve drafts and history, and reject unrelated drags", async (t) => {
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
    name: "Research project",
    description: "",
    created_at: at,
    updated_at: at,
    chat_count: 1,
    pin_counts: { reports: 0, sources: 0 },
  };
  let nextChatNumber = 0;
  const chat = (id, title, project_id = null) => ({
    id,
    title,
    project_id,
    chat_number: ++nextChatNumber,
    display_title: `${title} · #${nextChatNumber}`,
    created_at: at,
    updated_at: at,
    message_count: id === "general-one" ? 1 : 0,
    pin_counts: { reports: 0, sources: 0 },
  });
  const chats = [
    chat("starter", "Untitled chat", project.id),
    chat("general-one", "Saved question"),
    chat("general-two", "Other question"),
    chat("general-three", "Additional question"),
    chat("general-four", "Busy question"),
  ];
  const message = {
    id: "message-one",
    chat_id: "general-one",
    role: "user",
    content: "Existing saved question",
    report_id: null,
    created_at: at,
  };
  const detail = (id) => ({
    chat: chats.find((item) => item.id === id),
    messages: id === "general-one" ? [message] : [],
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
  const moves = [];
  const reads = [];
  let finishMove;
  let finishSend;
  let recoveryUnavailable = false;
  let firstRefreshUnavailable = false;
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    if (
      path === "/api/chats/general-four/messages" &&
      options.method === "POST"
    ) {
      await new Promise((resolve) => {
        finishSend = resolve;
      });
      return Response.json(detail("general-four"));
    }
    const id = /^\/api\/chats\/([^/]+)$/.exec(path)?.[1];
    if (id && options.method === "PATCH") {
      const body = JSON.parse(options.body);
      moves.push({ id, body });
      if (id === "general-two") {
        // The server saved the move, but the reply failed. Recovery must read
        // the saved assignment without repeating the mutation.
        chats.find((item) => item.id === id).project_id = body.project_id;
        project.chat_count = chats.filter(
          (item) => item.project_id === project.id,
        ).length;
        recoveryUnavailable = true;
        return Response.json(
          { detail: "PRIVATE_SERVER_DIAGNOSTIC" },
          { status: 500 },
        );
      }
      if (id === "general-one") {
        await new Promise((resolve) => {
          finishMove = resolve;
        });
        firstRefreshUnavailable = true;
      }
      chats.find((item) => item.id === id).project_id = body.project_id;
      project.chat_count = chats.filter(
        (item) => item.project_id === project.id,
      ).length;
      return Response.json(detail(id));
    }
    if (id) reads.push(id);
    if (
      id &&
      (recoveryUnavailable || (id === "general-one" && firstRefreshUnavailable))
    )
      return Response.json(
        { detail: "PRIVATE_SERVER_DIAGNOSTIC" },
        { status: 503 },
      );
    if (id) return Response.json(detail(id));
    if (path === "/api/projects") return Response.json({ projects: [project] });
    if (path === "/api/chats") return Response.json({ chats });
    if (path === "/api/settings") return Response.json(defaultSettings);
    // Explicit simulated verified session; this test covers chat movement.
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
          model: "test-navigation-model",
          account_id: "test-navigation-account",
          message: "Simulated verified navigation session.",
          checked_at: at,
        },
        optional: {
          compute: "local",
          aws_required: false,
          data_apis_required: false,
        },
      });
    if (path === "/api/connections") return Response.json(status);
    assert.fail(`unexpected request ${path}`);
  });
  const errors = [];
  t.mock.method(console, "error", (...args) => errors.push(args.join(" ")));
  const root = createRoot(document.getElementById("root"));
  const transfer = () => {
    const values = new Map();
    return {
      effectAllowed: "none",
      dropEffect: "none",
      files: [],
      items: [],
      get types() {
        return [...values.keys()];
      },
      setData(type, value) {
        values.set(type, value);
      },
      getData(type) {
        return values.get(type) ?? "";
      },
      clearData() {
        values.clear();
      },
      setDragImage() {},
    };
  };
  const emit = (element, type, dataTransfer) => {
    assert.ok(element, `target for ${type}`);
    const event = new dom.window.Event(type, {
      bubbles: true,
      cancelable: true,
    });
    Object.defineProperty(event, "dataTransfer", { value: dataTransfer });
    element.dispatchEvent(event);
    return event;
  };
  const drag = async (element, type, dataTransfer) => {
    let event;
    await act(async () => {
      event = emit(element, type, dataTransfer);
    });
    return event;
  };
  const target = () => document.querySelector(".sidebar-project-row");
  const general = (title) =>
    [...document.querySelectorAll(".all-chat-list .global-chat-item")].find(
      (item) => item.textContent.includes(title),
    );
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
    const first = general("Saved question");
    assert.equal(first.draggable, true);
    const external = transfer();
    external.setData("application/x-labcat-chat-id", "general-one");
    external.setData("text/plain", "general-one");
    assert.equal(
      (await drag(target(), "dragover", external)).defaultPrevented,
      false,
    );
    await drag(target(), "drop", external);
    assert.equal(moves.length, 0, "external payload cannot move a saved chat");
    const canceled = transfer();
    await drag(first, "dragstart", canceled);
    await drag(target(), "dragover", canceled);
    assert.ok(target().classList.contains("is-drop-target"));
    await drag(first, "dragend", canceled);
    assert.ok(!target().classList.contains("is-drop-target"));
    await drag(target(), "drop", canceled);
    assert.equal(moves.length, 0, "canceled drag cannot be replayed");
    await act(async () => {
      first.click();
    });
    const composer = document.querySelector('textarea[maxlength="20000"]');
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        dom.window.HTMLTextAreaElement.prototype,
        "value",
      ).set.call(composer, "Keep this unsent draft");
      composer.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
    const valid = transfer();
    await drag(general("Saved question"), "dragstart", valid);
    const over = await drag(target(), "dragover", valid);
    assert.equal(over.defaultPrevented, true);
    assert.equal(valid.dropEffect, "move");
    await drag(target(), "drop", valid);
    await drag(target(), "drop", valid);
    assert.equal(
      moves.length,
      1,
      "a repeated drop while saving submits only once",
    );
    assert.deepEqual(moves[0], {
      id: "general-one",
      body: { project_id: "project-one" },
    });
    assert.equal(
      document.querySelector('[aria-label="Send message"]').disabled,
      true,
      "sending is disabled while moving the open chat",
    );
    await act(async () => {
      finishMove();
    });
    assert.equal(
      document.querySelector('[aria-label="Send message"]').disabled,
      true,
      "failed follow-up read cannot enable stale chat detail",
    );
    assert.equal(
      document.getElementById("chat-project"),
      null,
      "project selector is no longer inline",
    );
    assert.equal(
      document.querySelector('[aria-label="Send message"]').disabled,
      true,
    );
    assert.equal(
      document.querySelector('textarea[maxlength="20000"]').value,
      "Keep this unsent draft",
    );
    firstRefreshUnavailable = false;
    await act(async () => {
      document
        .querySelector(".message-history .workspace-error button")
        .click();
    });
    assert.equal(general("Saved question"), undefined);
    assert.equal(
      document.querySelectorAll(".nested-chat-list .global-chat-item").length,
      2,
      "project expands with its starter and moved chat",
    );
    assert.ok(
      document
        .querySelector(".nested-chat-list")
        .textContent.includes("Saved question"),
    );
    assert.equal(
      document.querySelector(".chat-scope-label").textContent,
      project.name,
      "open chat membership refreshes",
    );
    assert.equal(
      document.querySelector('textarea[maxlength="20000"]').value,
      "Keep this unsent draft",
    );
    assert.ok(
      document
        .querySelector(".message-history")
        .textContent.includes(message.content),
    );
    assert.equal(
      document.querySelectorAll('textarea[maxlength="20000"]').length,
      1,
    );
    assert.match(
      document.querySelector(".chat-move-status").textContent,
      /Saved question.*Research project/,
    );
    assert.ok(!target().classList.contains("is-drop-target"));
    assert.equal(
      [
        ...document.querySelectorAll(".nested-chat-list .global-chat-item"),
      ].find((item) => item.textContent.includes("Saved question")).draggable,
      false,
      "only general chats are draggable",
    );
    const firstReads = reads.filter((id) => id === "general-one").length;
    const secondSuccess = transfer();
    await drag(general("Additional question"), "dragstart", secondSuccess);
    await drag(target(), "drop", secondSuccess);
    assert.equal(moves.length, 2);
    assert.equal(
      reads.filter((id) => id === "general-one").length,
      firstReads,
      "moving another chat does not reload the open chat",
    );
    assert.equal(
      document.querySelector('textarea[maxlength="20000"]').value,
      "Keep this unsent draft",
    );
    await act(async () => {
      document.querySelector(".sidebar-new-chat").click();
    });
    const unrelatedDraft = document.querySelector(
      'textarea[maxlength="20000"]',
    );
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        dom.window.HTMLTextAreaElement.prototype,
        "value",
      ).set.call(unrelatedDraft, "Another unsent question");
      unrelatedDraft.dispatchEvent(
        new dom.window.Event("input", { bubbles: true }),
      );
    });
    const failed = transfer();
    await drag(general("Other question"), "dragstart", failed);
    await drag(target(), "dragover", failed);
    await drag(target(), "drop", failed);
    assert.equal(moves.length, 3);
    assert.ok(
      general("Other question"),
      "failed move is not optimistically removed",
    );
    assert.ok(document.querySelector(".chat-move-error"));
    assert.ok(!document.body.textContent.includes("PRIVATE_SERVER_DIAGNOSTIC"));
    assert.equal(
      document.querySelector('textarea[maxlength="20000"]').value,
      "Another unsent question",
    );
    assert.ok(!target().classList.contains("is-drop-target"));
    assert.equal(
      general("Other question").draggable,
      false,
      "an uncertain move cannot be repeated",
    );
    const retryDrag = transfer();
    assert.equal(
      (await drag(general("Other question"), "dragstart", retryDrag))
        .defaultPrevented,
      true,
    );
    await drag(target(), "drop", retryDrag);
    assert.equal(moves.length, 3);
    await act(async () => {
      document.querySelector(".chat-move-error button").click();
    });
    assert.match(
      document.querySelector(".chat-move-error").textContent,
      /could not be checked/,
    );
    assert.equal(moves.length, 3, "failed recovery only reads");
    recoveryUnavailable = false;
    await act(async () => {
      document.querySelector(".chat-move-error button").click();
    });
    assert.equal(
      moves.length,
      3,
      "successful recovery does not repeat the move",
    );
    assert.equal(document.querySelector(".chat-move-error"), null);
    assert.equal(general("Other question"), undefined);
    assert.equal(
      document.querySelectorAll(".nested-chat-list .global-chat-item").length,
      4,
    );
    assert.equal(
      document.querySelector('textarea[maxlength="20000"]').value,
      "Another unsent question",
    );
    assert.match(
      document.querySelector(".chat-move-status").textContent,
      /Saved project checked/,
    );
    await act(async () => {
      general("Busy question").click();
    });
    const busyDraft = document.querySelector('textarea[maxlength="20000"]');
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        dom.window.HTMLTextAreaElement.prototype,
        "value",
      ).set.call(busyDraft, "Question in progress");
      busyDraft.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
    await act(async () => {
      document.querySelector('[aria-label="Send message"]').click();
    });
    assert.equal(general("Busy question").draggable, false);
    await act(async () => {
      document.querySelector(".sidebar-new-chat").click();
    });
    assert.equal(
      general("Busy question").draggable,
      false,
      "navigating away cannot unlock a pending request",
    );
    await act(async () => {
      general("Busy question").click();
    });
    assert.equal(
      general("Busy question").draggable,
      false,
      "reopening cannot unlock another view’s pending request",
    );
    const busyDrag = transfer();
    assert.equal(
      (await drag(general("Busy question"), "dragstart", busyDrag))
        .defaultPrevented,
      true,
    );
    await drag(target(), "drop", busyDrag);
    assert.equal(moves.length, 3);
    await act(async () => {
      finishSend();
    });
    assert.equal(
      general("Busy question").draggable,
      true,
      "dragging resumes when the earlier request finishes",
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
