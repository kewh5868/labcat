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
const button = (name, scope = document) =>
  [...scope.querySelectorAll("button")].find(
    (item) => item.textContent.trim() === name,
  );
const row = (name) =>
  [...document.querySelectorAll(".removed-item")].find(
    (item) =>
      (
        item.querySelector(".chat-identity-title") ??
        item.querySelector("strong")
      ).textContent === name,
  );

test("removed panel loads real backend records, refreshes in place, restores and requires explicit permanent deletion", async (t) => {
  const h = await harness();
  const { root, act, createElement, click } = h;
  const { default: Panel } = await h.load("RemovedItems");
  const { workspaceApi } = await h.load("workspaceApi");
  const fixture = JSON.parse(
    await readFile(
      new URL("./fixtures/removed-items.json", import.meta.url),
      "utf8",
    ),
  );
  let items = structuredClone(fixture),
    preferences = { confirm_removal: false },
    projects = [],
    revision = 0,
    failDelete = false,
    finishDelete;
  const mutations = [],
    reads = [];
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    if (path === "/api/removed") {
      reads.push(path);
      return Response.json(items);
    }
    if (path === "/api/workspace/preferences") {
      if (options.method === "PUT") preferences = JSON.parse(options.body);
      return Response.json(preferences);
    }
    if (path === "/api/session")
      return Response.json({ csrf_token: "TEST_REMOVAL_DOM_SESSION_TOKEN" });
    if (path.startsWith("/api/removed/") && options.method === "DELETE") {
      mutations.push({
        path,
        body: JSON.parse(options.body),
        token: options.headers["X-CSRF-Token"],
      });
      if (failDelete) return Response.json({}, { status: 500 });
      await new Promise((resolve) => {
        finishDelete = resolve;
      });
      const id = path.split("/").at(-1);
      items.chats = items.chats.filter((item) => item.id !== id);
      return new Response(null, { status: 204 });
    }
    assert.fail(`unexpected request ${path}`);
  });
  const render = async () =>
    act(async () =>
      root.render(
        createElement(Panel, {
          projects,
          revision,
          workspaceBusy: false,
          onRestore: async (item) => {
            if (item.kind === "project") {
              projects.push(
                items.projects.find((project) => project.id === item.id),
              );
              items.projects = items.projects.filter(
                (project) => project.id !== item.id,
              );
            } else
              items.chats = items.chats.filter((chat) => chat.id !== item.id);
            revision++;
            await render();
          },
          onPermanentlyDelete: async (item) =>
            workspaceApi.permanentlyDelete(item.kind, item.id, true),
          onPermanentlyDeleteAll: async (snapshot) =>
            workspaceApi.permanentlyDeleteAll(snapshot, true),
        }),
      ),
    );
  try {
    await render();
    const panel = document.querySelector(".removed-items-page");
    assert.equal(document.querySelectorAll(".removed-item").length, 3);
    assert.match(
      document.querySelector(".removed-count").textContent,
      /1 project · 2 individually removed chats/,
    );
    const child = fixture.chats[1];
    assert.equal(
      button("Restore", row(child.title)).disabled,
      true,
      "removed parent must be restored first",
    );
    const preference = document.querySelector(".removal-preferences input");
    assert.equal(preference.checked, false);
    await click(preference);
    assert.equal(preferences.confirm_removal, true);
    const added = {
      ...fixture.chats[0],
      id: "additional-removed-chat",
      title: "Additional removed chat",
      chat_number: 900,
      display_title: "Additional removed chat · #900",
    };
    items.chats.push(added);
    revision++;
    await render();
    assert.equal(
      document.querySelector(".removed-items-page"),
      panel,
      "refresh does not remount the panel",
    );
    assert.ok(row(added.title));
    await click(button("Restore", row(fixture.projects[0].name)));
    assert.equal(row(fixture.projects[0].name), undefined);
    assert.equal(button("Restore", row(child.title)).disabled, false);
    await click(button("Restore", row(child.title)));
    assert.equal(row(child.title), undefined);
    assert.match(
      document.querySelector(".removed-operation-notice").textContent,
      /restored/,
    );
    await click(button("Permanently delete", row(added.title)));
    const dialog = document.querySelector(".permanent-delete-dialog");
    assert.match(dialog.textContent, /cannot be undone/);
    assert.equal(button("Permanently delete chat", dialog).disabled, true);
    assert.equal(
      dialog.querySelectorAll("input").length,
      1,
      "no skip-confirmation setting for irreversible deletion",
    );
    await click(button("Cancel", dialog));
    assert.equal(mutations.length, 0);
    await click(button("Permanently delete", row(added.title)));
    await click(document.querySelector(".permanent-delete-dialog input"));
    await click(
      button("Permanently delete chat", document.querySelector("dialog")),
    );
    assert.equal(
      button("Cancel", document.querySelector("dialog")).disabled,
      true,
    );
    await act(async () =>
      document
        .querySelector("dialog form")
        .dispatchEvent(
          new h.dom.window.Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
    assert.equal(
      mutations.length,
      1,
      "duplicate submissions do not issue duplicate deletions",
    );
    assert.deepEqual(mutations[0].body, { confirm: true });
    assert.equal(mutations[0].token, "TEST_REMOVAL_DOM_SESSION_TOKEN");
    await act(async () => finishDelete());
    assert.equal(document.querySelector("dialog"), null);
    assert.equal(row(added.title), undefined);
    assert.match(
      document.querySelector(".removed-operation-notice").textContent,
      /permanently deleted/,
    );
    assert.match(
      document.querySelector(".removed-count").textContent,
      /0 projects · 1 individually removed chat$/,
    );
    failDelete = true;
    await click(button("Permanently delete", row(fixture.chats[0].title)));
    assert.equal(
      document.querySelector("dialog input").checked,
      false,
      "every purge starts unconfirmed",
    );
    await click(document.querySelector("dialog input"));
    await click(
      button("Permanently delete chat", document.querySelector("dialog")),
    );
    assert.match(
      document.querySelector(".dialog-error").textContent,
      /check the saved list/,
    );
    assert.equal(
      button("Permanently delete chat", document.querySelector("dialog"))
        .disabled,
      true,
    );
    assert.equal(mutations.length, 2, "failure is not retried");
    const before = reads.length;
    await click(button("Close", document.querySelector("dialog")));
    assert.ok(reads.length > before);
    assert.ok(row(fixture.chats[0].title));
  } finally {
    await h.close();
  }
});

test("bulk confirmation uses its reviewed snapshot, refreshes conflicts and never retries a deletion", async (t) => {
  const h = await harness();
  const { root, act, createElement, click } = h;
  const { default: Panel } = await h.load("RemovedItems");
  const { workspaceApi } = await h.load("workspaceApi");
  const fixture = JSON.parse(
    await readFile(
      new URL("./fixtures/removed-items.json", import.meta.url),
      "utf8",
    ),
  );
  fixture.chats[0].expires_at = null;
  fixture.chats[1].expires_at = "2026-09-11T01:00:00+00:00";
  let items = structuredClone(fixture),
    revision = 0,
    workspaceBusy = false,
    finishRead,
    finishDelete,
    tick;
  let pauseRead = true;
  const reads = [],
    mutations = [];
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "visible",
  });
  t.mock.method(window, "setInterval", (callback, milliseconds) => {
    assert.equal(milliseconds, 60_000);
    tick = callback;
    return 909;
  });
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    if (path === "/api/workspace/preferences")
      return Response.json({ confirm_removal: false });
    if (path === "/api/session")
      return Response.json({ csrf_token: "TEST_BULK_DOM_SESSION_TOKEN" });
    if (path === "/api/removed" && options.method === "GET") {
      reads.push(path);
      const value = structuredClone(items);
      if (pauseRead)
        await new Promise((resolve) => {
          finishRead = resolve;
        });
      return Response.json(value);
    }
    if (path === "/api/removed" && options.method === "DELETE") {
      const body = JSON.parse(options.body);
      mutations.push(body);
      if (body.snapshot !== items.snapshot)
        return Response.json(
          { detail: "PRIVATE_SERVER_DETAIL" },
          { status: 409 },
        );
      await new Promise((resolve) => {
        finishDelete = resolve;
      });
      items = {
        projects: [],
        chats: [],
        retention_days: 30,
        snapshot: "c".repeat(64),
      };
      return new Response(null, { status: 204 });
    }
    assert.fail(`unexpected request ${path}`);
  });
  const render = async () =>
    act(async () =>
      root.render(
        createElement(Panel, {
          projects: [],
          revision,
          workspaceBusy,
          onRestore: async () => assert.fail("bulk test must not restore"),
          onPermanentlyDelete: async () =>
            assert.fail("bulk test must not delete individually"),
          onPermanentlyDeleteAll: async (snapshot) =>
            workspaceApi.permanentlyDeleteAll(snapshot, true),
        }),
      ),
    );
  const refresh = async () =>
    act(async () => {
      tick();
      window.dispatchEvent(new h.dom.window.Event("focus"));
    });
  try {
    await render();
    assert.equal(
      button("Permanently delete all").disabled,
      true,
      "loading cannot open confirmation",
    );
    await refresh();
    assert.equal(
      reads.length,
      1,
      "no overlapping refresh while a read is in flight",
    );
    pauseRead = false;
    await act(async () => finishRead());
    assert.match(
      document.querySelector(".settings-intro").textContent,
      /kept for 30 days/,
    );
    assert.match(
      document.querySelector(".settings-intro").textContent,
      /the next time it starts/,
    );
    assert.match(
      row(fixture.chats[0].title).textContent,
      /Automatic deletion date unavailable/,
    );
    assert.equal(
      row(fixture.chats[1].title).querySelector("time").dateTime,
      fixture.chats[1].expires_at,
      "shows the server deadline without recomputing from the chat timestamp",
    );
    workspaceBusy = true;
    await render();
    assert.equal(button("Permanently delete all").disabled, true);
    const busyReads = reads.length;
    await refresh();
    assert.equal(reads.length, busyReads);
    workspaceBusy = false;
    await render();
    await click(button("Permanently delete all"));
    let dialog = document.querySelector(".bulk-permanent-delete-dialog");
    assert.equal(
      dialog.getAttribute("aria-labelledby"),
      "bulk-permanent-delete-title",
    );
    assert.match(
      dialog.querySelector(".bulk-deletion-count").textContent,
      /1 project · 2 individually removed chats/,
    );
    assert.match(dialog.textContent, /chats, reports, pins and resources/);
    assert.match(dialog.textContent, /cannot be undone/);
    assert.equal(button("Permanently delete all", dialog).disabled, true);
    assert.equal(
      dialog.querySelectorAll("input").length,
      1,
      "recoverable-removal preference cannot bypass this confirmation",
    );
    await click(button("Cancel", dialog));
    assert.equal(mutations.length, 0);
    await click(button("Permanently delete all"));
    const reviewedReads = reads.length;
    items.chats.push({
      ...fixture.chats[0],
      id: "newly-removed",
      title: "Newly removed",
      chat_number: 901,
      display_title: "Newly removed · #901",
    });
    items.snapshot = "b".repeat(64);
    revision++;
    await render();
    await refresh();
    assert.equal(
      reads.length,
      reviewedReads,
      "confirmation pauses polling and external revision refreshes",
    );
    assert.match(
      document.querySelector(".bulk-deletion-count").textContent,
      /2 individually removed chats/,
    );
    await click(document.querySelector("dialog input"));
    await click(
      button("Permanently delete all", document.querySelector("dialog")),
    );
    assert.deepEqual(
      mutations,
      [{ confirm: true, snapshot: fixture.snapshot }],
      "submits exactly the original reviewed snapshot",
    );
    assert.equal(
      document.querySelector("dialog"),
      null,
      "stale confirmation is discarded",
    );
    assert.ok(row("Newly removed"));
    assert.match(
      document.querySelector(".removed-operation-notice").textContent,
      /Review the updated list and confirm again/,
    );
    assert.ok(!document.body.textContent.includes("PRIVATE_SERVER_DETAIL"));
    await click(button("Permanently delete all"));
    dialog = document.querySelector("dialog");
    assert.equal(
      dialog.querySelector("input").checked,
      false,
      "changed list requires fresh explicit confirmation",
    );
    assert.match(
      dialog.querySelector(".bulk-deletion-count").textContent,
      /3 individually removed chats/,
    );
    await click(dialog.querySelector("input"));
    await click(button("Permanently delete all", dialog));
    assert.equal(button("Cancel", dialog).disabled, true);
    const deletingReads = reads.length;
    await act(async () =>
      dialog
        .querySelector("form")
        .dispatchEvent(
          new h.dom.window.Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
    await refresh();
    assert.equal(
      reads.length,
      deletingReads,
      "no refresh while deletion is in flight",
    );
    assert.equal(
      mutations.length,
      2,
      "duplicate submission never repeats a deletion",
    );
    assert.deepEqual(mutations[1], { confirm: true, snapshot: "b".repeat(64) });
    await act(async () => finishDelete());
    assert.equal(document.querySelector("dialog"), null);
    assert.equal(document.querySelectorAll(".removed-item").length, 0);
    assert.equal(
      button("Permanently delete all").disabled,
      true,
      "empty list cannot open bulk confirmation",
    );
    assert.match(
      document.querySelector(".removed-operation-notice").textContent,
      /permanently deleted/,
    );
  } finally {
    await h.close();
  }
});

test("removed refresh follows focus and time but preserves mutation and loading errors for explicit review", async (t) => {
  const h = await harness();
  const { root, act, createElement, click } = h;
  const { default: Panel } = await h.load("RemovedItems");
  const { workspaceApi } = await h.load("workspaceApi");
  let items = JSON.parse(
    await readFile(
      new URL("./fixtures/removed-items.json", import.meta.url),
      "utf8",
    ),
  );
  let tick,
    reads = 0,
    mutations = 0,
    failRead = false,
    pauseRead = false,
    finishRead;
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "visible",
  });
  t.mock.method(window, "setInterval", (callback) => {
    tick = callback;
    return 910;
  });
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    if (path === "/api/workspace/preferences")
      return Response.json({ confirm_removal: true });
    if (path === "/api/session")
      return Response.json({ csrf_token: "TEST_BULK_ERROR_SESSION_TOKEN" });
    if (path === "/api/removed" && options.method === "DELETE") {
      mutations++;
      return Response.json({}, { status: 500 });
    }
    if (path === "/api/removed") {
      reads++;
      const value = structuredClone(items);
      if (pauseRead)
        await new Promise((resolve) => {
          finishRead = resolve;
        });
      return failRead
        ? Response.json({}, { status: 500 })
        : Response.json(value);
    }
    assert.fail(`unexpected request ${path}`);
  });
  const refresh = async () =>
    act(async () => {
      tick();
      window.dispatchEvent(new h.dom.window.Event("focus"));
    });
  try {
    await act(async () =>
      root.render(
        createElement(Panel, {
          projects: [],
          revision: 0,
          workspaceBusy: false,
          onRestore: async () => {},
          onPermanentlyDelete: async () => {},
          onPermanentlyDeleteAll: async (snapshot) =>
            workspaceApi.permanentlyDeleteAll(snapshot, true),
        }),
      ),
    );
    await click(button("Permanently delete all"));
    await click(document.querySelector("dialog input"));
    await click(
      button("Permanently delete all", document.querySelector("dialog")),
    );
    const failedReads = reads;
    assert.match(
      document.querySelector(".dialog-error").textContent,
      /check the saved list/,
    );
    assert.equal(
      button("Permanently delete all", document.querySelector("dialog"))
        .disabled,
      true,
    );
    await refresh();
    assert.equal(
      reads,
      failedReads,
      "polling cannot clear an ambiguous deletion error",
    );
    assert.equal(mutations, 1);
    await click(button("Close", document.querySelector("dialog")));
    assert.ok(
      reads > failedReads,
      "closing requests a fresh list before another confirmation",
    );
    pauseRead = true;
    const previousCount = document.querySelectorAll(".removed-item").length;
    items.chats = [];
    items.snapshot = "d".repeat(64);
    await act(async () =>
      window.dispatchEvent(new h.dom.window.Event("focus")),
    );
    const inFlightReads = reads;
    await refresh();
    assert.equal(reads, inFlightReads);
    assert.equal(
      button("Permanently delete all").disabled,
      true,
      "refreshing the list prevents reviewing stale counts",
    );
    assert.equal(
      document.querySelectorAll(".removed-item").length,
      previousCount,
    );
    pauseRead = false;
    await act(async () => finishRead());
    assert.equal(
      document.querySelectorAll(".removed-item").length,
      1,
      "focus refresh removes expired rows",
    );
    failRead = true;
    await act(async () => tick());
    const failureReads = reads;
    assert.match(
      document.querySelector(".workspace-error").textContent,
      /workspace request failed/,
    );
    assert.equal(button("Permanently delete all").disabled, true);
    await refresh();
    assert.equal(
      reads,
      failureReads,
      "background refresh does not hide a list error",
    );
    failRead = false;
    await click(button("Check removed items"));
    assert.ok(reads > failureReads);
    assert.equal(document.querySelector(".workspace-error"), null);
    assert.equal(button("Permanently delete all").disabled, false);
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    const hiddenReads = reads;
    await refresh();
    assert.equal(reads, hiddenReads, "hidden pages do not poll");
  } finally {
    await h.close();
  }
});

test("recoverable removal preference is saved only on confirmation and recalled after a workspace remount", async (t) => {
  const h = await harness();
  const { root, act, createElement, click } = h;
  const { default: Workspace } = await h.load("ProjectWorkspace");
  const { ConnectionsProvider } = await h.load("Connections");
  const { SetupProvider } = await h.load("SetupWizard");
  const { defaultSettings } = await h.load("workspaceApi");
  const fixture = JSON.parse(
    await readFile(
      new URL("./fixtures/removed-items.json", import.meta.url),
      "utf8",
    ),
  );
  let activeProjects = [
    { ...fixture.projects[0], id: "project-active", name: "Active project" },
  ];
  let activeChats = [
    {
      ...fixture.chats[0],
      id: "chat-active",
      title: "Active chat",
      chat_number: 91,
      display_title: "Active chat · #91",
    },
    {
      ...fixture.chats[0],
      id: "chat-next",
      title: "Next chat",
      chat_number: 92,
      display_title: "Next chat · #92",
    },
  ];
  const removed = {
      projects: [],
      chats: [],
      retention_days: 30,
      snapshot: "a".repeat(64),
    },
    preferences = { confirm_removal: true },
    mutations = [];
  let projectRead = 0,
    finishStaleProjects;
  const at = fixture.projects[0].created_at;
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
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    if (path === "/api/projects") {
      projectRead++;
      if (projectRead === 2) {
        const snapshot = structuredClone(activeProjects);
        await new Promise((resolve) => {
          finishStaleProjects = resolve;
        });
        return Response.json({ projects: snapshot });
      }
      return Response.json({ projects: activeProjects });
    }
    if (path === "/api/chats") return Response.json({ chats: activeChats });
    if (path === "/api/settings") return Response.json(defaultSettings);
    if (path === "/api/session")
      return Response.json({ csrf_token: "TEST_BULK_DELETE_SESSION_TOKEN" });
    if (path === "/api/removed") {
      if (options.method === "DELETE") {
        mutations.push("bulk-delete");
        removed.projects = [];
        removed.chats = [];
        return new Response(null, { status: 204 });
      }
      return Response.json(removed);
    }
    if (path === "/api/workspace/preferences") {
      if (options.method === "PUT") {
        mutations.push("preference");
        Object.assign(preferences, JSON.parse(options.body));
      }
      return Response.json(preferences);
    }
    if (options.method === "DELETE") {
      mutations.push(path);
      if (path.startsWith("/api/projects/")) {
        removed.projects.push(activeProjects[0]);
        activeProjects = [];
      } else {
        const id = path.split("/").at(-1);
        removed.chats.push(activeChats.find((chat) => chat.id === id));
        activeChats = activeChats.filter((chat) => chat.id !== id);
      }
      return new Response(null, { status: 204 });
    }
    if (path.endsWith("/restore")) {
      const id = path.split("/").at(-2);
      const chat = removed.chats.find((item) => item.id === id);
      removed.chats = removed.chats.filter((item) => item.id !== id);
      activeChats.push(chat);
      return Response.json({ chat, messages: [], reports: [], sources: [] });
    }
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
          message: "Simulated navigation session.",
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
  const render = async (key = "first") =>
    act(async () =>
      root.render(
        createElement(
          ConnectionsProvider,
          null,
          createElement(SetupProvider, null, createElement(Workspace, { key })),
        ),
      ),
    );
  const remove = async (kind, name) => {
    await click(
      [...document.querySelectorAll("[aria-label]")].find((element) =>
        element
          .getAttribute("aria-label")
          .startsWith(`Actions for ${kind} ${name}`),
      ),
    );
    const action = button(`Remove ${kind}`);
    // WebKit can blur the keyboard-focused first item without focusing the
    // mouse-clicked button. The action must survive until its click arrives.
    await act(async () =>
      document.activeElement.dispatchEvent(
        new h.dom.window.FocusEvent("focusout", {
          bubbles: true,
          relatedTarget: null,
        }),
      ),
    );
    assert.ok(
      action.isConnected,
      "a null focus destination must not discard the pending menu action",
    );
    await click(action);
  };
  try {
    await render();
    await click(button("Removed items"));
    const trigger = [...document.querySelectorAll("[aria-label]")].find(
      (element) =>
        element
          .getAttribute("aria-label")
          .startsWith("Actions for chat Active chat"),
    );
    await click(trigger);
    await act(async () =>
      button("Removed items").dispatchEvent(
        new h.dom.window.MouseEvent("pointerdown", { bubbles: true }),
      ),
    );
    assert.equal(
      document.querySelector(".sidebar-item-menu"),
      null,
      "outside pointer still dismisses the menu",
    );
    await click(trigger);
    await act(async () =>
      document.activeElement.dispatchEvent(
        new h.dom.window.FocusEvent("focusout", {
          bubbles: true,
          relatedTarget: button("Removed items"),
        }),
      ),
    );
    assert.equal(
      document.querySelector(".sidebar-item-menu"),
      null,
      "keyboard focus outside still dismisses the menu",
    );
    assert.equal(mutations.length, 0);
    await remove("chat", "Active chat");
    await click(
      document.querySelector(".workspace-dialog .removal-checkbox input"),
    );
    await click(button("Cancel", document.querySelector("dialog")));
    assert.equal(preferences.confirm_removal, true);
    assert.equal(mutations.length, 0);
    await remove("chat", "Active chat");
    await click(
      document.querySelector(".workspace-dialog .removal-checkbox input"),
    );
    await click(button("Remove chat", document.querySelector("dialog")));
    assert.equal(preferences.confirm_removal, false);
    assert.equal(document.querySelector("dialog"), null);
    assert.ok(
      row("Active chat"),
      "newly removed chat appears while Removed items stays mounted",
    );
    assert.equal(
      document.querySelector(".removal-preferences input").checked,
      false,
    );
    await remove("project", "Active project");
    assert.equal(
      document.querySelector("dialog"),
      null,
      "saved preference skips only recoverable confirmation",
    );
    assert.ok(row("Active project"));
    await act(async () => finishStaleProjects());
    assert.equal(
      document.querySelector(".project-nav-item"),
      null,
      "stale refresh cannot reintroduce a removed project",
    );
    await render("restarted");
    await click(button("Removed items"));
    await remove("chat", "Next chat");
    assert.equal(document.querySelector("dialog"), null);
    assert.ok(row("Next chat"));
    await click(button("Restore", row("Next chat")));
    assert.equal(
      document.querySelector(".removal-notice"),
      null,
      "restoring the last removed item clears its undo notice",
    );
    await click(document.querySelector(".removal-preferences input"));
    assert.equal(preferences.confirm_removal, true);
    await remove("chat", "Next chat");
    assert.ok(
      document.querySelector(".workspace-dialog"),
      "confirmation can be turned back on",
    );
    await click(button("Remove chat", document.querySelector("dialog")));
    assert.ok(document.querySelector(".removal-notice"));
    const previousReads = projectRead;
    await click(button("Permanently delete all"));
    assert.equal(
      document.querySelector("dialog input").checked,
      false,
      "bulk deletion remains a separate explicit confirmation",
    );
    await click(document.querySelector("dialog input"));
    await click(
      button("Permanently delete all", document.querySelector("dialog")),
    );
    assert.equal(mutations.filter((item) => item === "bulk-delete").length, 1);
    assert.equal(
      document.querySelector(".removal-notice"),
      null,
      "bulk purge clears any stale Undo notice",
    );
    assert.equal(document.querySelectorAll(".removed-item").length, 0);
    assert.ok(projectRead > previousReads, "bulk purge refreshes the sidebar");
  } finally {
    await h.close();
  }
});
