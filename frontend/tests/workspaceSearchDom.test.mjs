import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, before, test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

// Synthetic navigation/search data only. The API is stubbed and network access
// fails this harness; these tests do not inspect a real saved workspace.
let compiled;
before(async () => {
  compiled = await mkdtemp(join(tmpdir(), "labcat-workspace-search-dom-"));
  for (const name of [
    "WorkspaceSearch.tsx",
    "ChatIdentity.tsx",
    "workspaceApi.ts",
  ]) {
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
      .outputText.replace(
        /from (['"])([^'"]+)\1/g,
        (_match, _quote, specifier) =>
          `from '${specifier.startsWith(".") ? `${specifier}.js` : import.meta.resolve(specifier)}'`,
      );
    await writeFile(join(compiled, name.replace(/\.tsx?$/, ".js")), output);
  }
  await writeFile(join(compiled, "package.json"), '{"type":"module"}');
});
after(async () => {
  if (compiled) await rm(compiled, { recursive: true, force: true });
});

const at = "2026-09-22T15:00:00Z";
const project = {
  id: "project-fixture",
  name: "Search fixture project",
  description: "Saved sample description",
  chat_count: 3,
  pin_counts: { reports: 0, sources: 0 },
  created_at: at,
  updated_at: at,
};
const chat = (id, project_id = project.id) => ({
  id,
  project_id,
  title: `Saved ${id}`,
  chat_number: id === "chat-general" ? 8 : 7,
  display_title: `Saved ${id}`,
  message_count: 2,
  pin_counts: { reports: 0, sources: 0 },
  created_at: at,
  updated_at: at,
});
const empty = (query) => ({ query, projects: [], chats: [], has_more: false });
const results = (query, has_more = false) => ({
  query,
  has_more,
  projects: [
    {
      project,
      match_field: "description",
      snippet: "A matching sample in the saved project description.",
    },
  ],
  chats: [
    {
      chat: chat("chat-message"),
      project_name: project.name,
      match_field: "message",
      snippet: "A matching sample in an older saved message.",
      message_id: "message-fixture",
      report_id: null,
    },
    {
      chat: chat("chat-report"),
      project_name: project.name,
      match_field: "report",
      snippet: "A matching sample in a saved report.",
      message_id: "report-message-fixture",
      report_id: "report-fixture",
    },
    {
      chat: chat("chat-general", null),
      project_name: null,
      match_field: "title",
      snippet: "Saved chat-general",
      message_id: null,
      report_id: null,
    },
  ],
});
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

async function harness(t, search = async (query) => empty(query)) {
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
  const { default: WorkspaceSearch } = await import(
    pathToFileURL(join(compiled, "WorkspaceSearch.js"))
  );
  const { workspaceApi } = await import(
    pathToFileURL(join(compiled, "workspaceApi.js"))
  );
  const calls = [],
    opened = [],
    timers = new Map();
  let clock = 0,
    timerId = 0;
  t.mock.method(globalThis, "fetch", async () => {
    throw new Error("Unexpected network access in isolated search test");
  });
  t.mock.method(workspaceApi, "search", (query, signal) => {
    calls.push({ query, signal });
    return search(query, signal);
  });
  t.mock.method(dom.window, "setTimeout", (callback, delay) => {
    const id = ++timerId;
    timers.set(id, { at: clock + delay, callback });
    return id;
  });
  t.mock.method(dom.window, "clearTimeout", (id) => timers.delete(id));
  const root = createRoot(document.getElementById("root"));
  const render = async (revision = 0) =>
    act(async () =>
      root.render(
        createElement(
          WorkspaceSearch,
          {
            revision,
            onProject: (item) => opened.push({ type: "project", item }),
            onChat: (item) => opened.push({ type: "chat", item }),
          },
          createElement(
            "div",
            { id: "normal-sidebar" },
            "Normal project and general chat lists",
          ),
        ),
      ),
    );
  const input = () => document.querySelector('input[type="search"]');
  const type = async (value) =>
    act(async () => {
      const field = input();
      Object.getOwnPropertyDescriptor(
        dom.window.HTMLInputElement.prototype,
        "value",
      ).set.call(field, value);
      field.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
  const click = async (element) => {
    assert.ok(element, "search control exists");
    await act(async () =>
      element.dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true }),
      ),
    );
  };
  const key = async (value) =>
    act(async () =>
      input().dispatchEvent(
        new dom.window.KeyboardEvent("keydown", {
          key: value,
          bubbles: true,
          cancelable: true,
        }),
      ),
    );
  const advance = async (milliseconds = 200) =>
    act(async () => {
      clock += milliseconds;
      for (const [id, timer] of [...timers])
        if (timer.at <= clock && timers.delete(id)) timer.callback();
    });
  return {
    dom,
    act,
    calls,
    opened,
    render,
    input,
    type,
    click,
    key,
    advance,
    async close() {
      await act(async () => root.unmount());
      dom.window.close();
      for (const key of globals) {
        if (previous[key])
          Object.defineProperty(globalThis, key, previous[key]);
        else delete globalThis[key];
      }
    },
  };
}
const status = () => document.querySelector('[role="status"]')?.textContent;
const matchingButtons = (label) => [
  ...document.querySelectorAll(`[aria-label="${label}"] button`),
];
const clearButton = () =>
  document.querySelector('[aria-label="Clear workspace search"]');
const normalSidebar = () => document.getElementById("normal-sidebar");

test("blank and whitespace search keep normal lists visible without querying saved data", async (t) => {
  const h = await harness(t);
  try {
    await h.render();
    assert.ok(normalSidebar());
    assert.equal(clearButton(), null);
    assert.equal(h.input().maxLength, 200);
    assert.equal(
      document.querySelector(`label[for="${h.input().id}"]`).textContent,
      "Search chats and projects",
    );
    await h.advance(1000);
    assert.deepEqual(h.calls, []);
    await h.type("   ");
    await h.advance(1000);
    assert.ok(normalSidebar());
    assert.equal(
      document.querySelector('[aria-label="Workspace search results"]'),
      null,
    );
    assert.deepEqual(h.calls, []);
  } finally {
    await h.close();
  }
});

test("search displays project descriptions, scoped chat messages and reports, and opens exact matches", async (t) => {
  const found = results("sample", true),
    h = await harness(t, async () => found);
  try {
    await h.render();
    await h.type("sample");
    assert.equal(normalSidebar(), null);
    assert.match(status(), /Searching/);
    assert.equal(
      document
        .querySelector('[aria-label="Workspace search results"]')
        .getAttribute("aria-busy"),
      "true",
    );
    await h.advance(199);
    assert.equal(h.calls.length, 0);
    await h.advance(1);
    assert.equal(h.calls.length, 1);
    assert.equal(h.calls[0].query, "sample");
    assert.equal(h.calls[0].signal.aborted, false);
    assert.equal(status(), "1 projects · 3 chats");
    assert.equal(
      document
        .querySelector('[aria-label="Workspace search results"]')
        .getAttribute("aria-busy"),
      "false",
    );
    const projects = matchingButtons("Project search results"),
      chats = matchingButtons("Chat search results");
    assert.equal(projects.length, 1);
    assert.equal(chats.length, 3);
    assert.match(
      projects[0].textContent,
      /matching sample in the saved project description/,
    );
    assert.match(projects[0].textContent, /3 chats/);
    assert.match(
      chats[0].textContent,
      /Search fixture project · Message match/,
    );
    assert.match(chats[0].textContent, /older saved message/);
    assert.match(chats[1].textContent, /Search fixture project · Report match/);
    assert.match(chats[1].textContent, /saved report/);
    assert.match(chats[2].textContent, /General Chats/);
    assert.match(chats[0].textContent, /#7/);
    assert.match(
      document.body.textContent,
      /More matches available\. Add more words/,
    );
    await h.click(projects[0]);
    await h.click(chats[0]);
    await h.click(chats[1]);
    await h.click(chats[2]);
    assert.equal(h.opened[0].item, project);
    for (let index = 0; index < found.chats.length; index++) {
      assert.equal(h.opened[index + 1].type, "chat");
      assert.equal(h.opened[index + 1].item, found.chats[index]);
    }
  } finally {
    await h.close();
  }
});

test("saved titles and snippets render as text rather than active markup", async (t) => {
  const hostile =
    '<img src=x onerror="window.searchInjection=true"><script>window.searchInjection=true</script>';
  const found = results("fixture");
  found.projects[0] = {
    ...found.projects[0],
    project: { ...project, name: hostile },
    snippet: hostile,
  };
  found.chats[0] = {
    ...found.chats[0],
    chat: { ...found.chats[0].chat, title: hostile },
    project_name: hostile,
    snippet: hostile,
  };
  const h = await harness(t, async () => found);
  try {
    await h.render();
    await h.type("fixture");
    await h.advance();
    assert.ok(document.body.textContent.includes(hostile));
    assert.equal(document.querySelector("img, script, [onerror]"), null);
    assert.equal(h.dom.window.searchInjection, undefined);
    await h.click(matchingButtons("Chat search results")[0]);
    assert.equal(h.opened[0].item, found.chats[0]);
  } finally {
    await h.close();
  }
});

test("typing is debounced and trimmed before local search", async (t) => {
  const h = await harness(t);
  try {
    await h.render();
    await h.type("s");
    await h.advance(100);
    await h.type("sam");
    await h.advance(100);
    await h.type("  sample  ");
    await h.advance(199);
    assert.equal(h.calls.length, 0);
    await h.advance(1);
    assert.deepEqual(
      h.calls.map(({ query }) => query),
      ["sample"],
    );
    assert.match(document.body.textContent, /No matching projects/);
    assert.match(document.body.textContent, /No matching chats/);
  } finally {
    await h.close();
  }
});

test("late results cannot overwrite a newer query or reappear after clearing search", async (t) => {
  const pending = new Map(),
    h = await harness(t, (query) => {
      const task = deferred();
      pending.set(query, task);
      return task.promise;
    });
  try {
    await h.render();
    await h.type("old");
    await h.advance();
    await h.type("new");
    assert.equal(h.calls[0].signal.aborted, true);
    await h.advance();
    await h.act(async () => pending.get("new").resolve(results("new")));
    assert.equal(status(), "1 projects · 3 chats");
    await h.act(async () => pending.get("old").resolve(empty("old")));
    assert.equal(status(), "1 projects · 3 chats");
    assert.equal(h.input().value, "new");
    await h.type("cleared");
    await h.advance();
    await h.click(clearButton());
    assert.equal(h.calls[2].signal.aborted, true);
    assert.ok(normalSidebar());
    await h.act(async () => pending.get("cleared").resolve(results("cleared")));
    assert.ok(normalSidebar());
    assert.equal(status(), undefined);
    assert.equal(h.input().value, "");
  } finally {
    await h.close();
  }
});

test("failed search offers retry without exposing raw errors and clears stale failure on success", async (t) => {
  let attempts = 0;
  const h = await harness(t, async (query) => {
    attempts += 1;
    if (attempts === 1) throw new Error("Private diagnostic must not be shown");
    return results(query);
  });
  try {
    await h.render();
    await h.type("sample");
    await h.advance();
    assert.equal(status(), "Search is unavailable.");
    assert.doesNotMatch(document.body.textContent, /Private diagnostic/);
    const retry = [...document.querySelectorAll("button")].find(
      (item) => item.textContent === "Try search again",
    );
    await h.click(retry);
    assert.match(status(), /Searching/);
    await h.advance();
    assert.equal(h.calls.length, 2);
    assert.equal(status(), "1 projects · 3 chats");
    assert.doesNotMatch(
      document.body.textContent,
      /Try search again|Search is unavailable/,
    );
  } finally {
    await h.close();
  }
});

test("Escape and clear restore normal lists and return focus to the search field", async (t) => {
  const h = await harness(t, async (query) => results(query));
  try {
    await h.render();
    for (const clear of [() => h.key("Escape"), () => h.click(clearButton())]) {
      await h.type("sample");
      await h.advance();
      assert.equal(normalSidebar(), null);
      await clear();
      assert.ok(normalSidebar());
      assert.equal(h.input().value, "");
      assert.equal(document.activeElement, h.input());
      assert.equal(clearButton(), null);
    }
    assert.equal(h.calls.length, 2);
  } finally {
    await h.close();
  }
});

test("workspace revision refreshes an active query but never performs a blank search", async (t) => {
  let count = 0;
  const h = await harness(t, async (query) =>
    count++ ? empty(query) : results(query),
  );
  try {
    await h.render();
    await h.render(1);
    await h.advance();
    assert.equal(h.calls.length, 0);
    await h.type("sample");
    await h.advance();
    assert.equal(status(), "1 projects · 3 chats");
    await h.render(2);
    assert.match(status(), /Searching/);
    assert.equal(h.calls[0].signal.aborted, true);
    await h.advance();
    assert.deepEqual(
      h.calls.map(({ query }) => query),
      ["sample", "sample"],
    );
    assert.equal(status(), "0 projects · 0 chats");
    await h.click(clearButton());
    await h.render(3);
    await h.advance();
    assert.equal(h.calls.length, 2);
  } finally {
    await h.close();
  }
});
