import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtemp, readFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { JSDOM } from "jsdom";
import ts from "typescript";
const runId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const at = "2026-09-23T12:00:00Z";
const status = (state = "running") => ({
  run_id: runId,
  status: state,
  phase: state === "running" ? "discovery" : state,
  message: "Reported progress.",
  started_at: at,
  updated_at: at,
  sequence: 2,
});
const detail = {
  chat: { id: "chat-one", title: "Named from prompt" },
  messages: [],
  reports: [],
  sources: [],
};
async function harness(t) {
  const output = await mkdtemp(join(tmpdir(), "labcat-run-test-"));
  for (const name of ["useResearchRuns.ts", "workspaceApi.ts"]) {
    const code = ts
      .transpileModule(
        await readFile(new URL(`../src/${name}`, import.meta.url), "utf8"),
        {
          compilerOptions: {
            target: ts.ScriptTarget.ES2022,
            module: ts.ModuleKind.ES2022,
          },
        },
      )
      .outputText.replace(
        /from (['"])([^'"]+)\1/g,
        (_m, _q, s) =>
          `from '${s.startsWith(".") ? `${s}.js` : import.meta.resolve(s)}'`,
      );
    await writeFile(join(output, name.replace(".ts", ".js")), code);
  }
  await writeFile(join(output, "package.json"), '{"type":"module"}');
  const dom = new JSDOM('<div id="root"></div>', { url: "http://localhost/" });
  const keys = ["window", "document", "navigator", "IS_REACT_ACT_ENVIRONMENT"];
  const before = Object.fromEntries(
    keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]),
  );
  for (const key of keys)
    Object.defineProperty(globalThis, key, {
      value: key === "IS_REACT_ACT_ENVIRONMENT" ? true : dom.window[key],
      writable: true,
      configurable: true,
    });
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { useResearchRuns } = await import(
    pathToFileURL(join(output, "useResearchRuns.js")).href
  );
  const { workspaceApi, ResearchRequestError } = await import(
    pathToFileURL(join(output, "workspaceApi.js")).href
  );
  const timers = new Map();
  let timerId = 0,
    research;
  const changed = [];
  t.mock.method(window, "setTimeout", (fn, delay) => {
    const id = ++timerId;
    timers.set(id, { fn, delay });
    return id;
  });
  t.mock.method(window, "clearTimeout", (id) => timers.delete(id));
  let active = [];
  t.mock.method(workspaceApi, "activeResearch", async () => active);
  t.mock.method(workspaceApi, "chat", async () => detail);
  t.mock.method(workspaceApi, "researchStatus", async () =>
    status("completed"),
  );
  function Host() {
    research = useResearchRuns((chat) => changed.push(chat));
    return createElement(
      "div",
      null,
      Object.entries(research.runs)
        .map(([id, run]) => `${id}:${run.status}`)
        .join(","),
    );
  }
  const root = createRoot(document.getElementById("root"));
  await act(async () => root.render(createElement(Host)));
  return {
    act,
    workspaceApi,
    ResearchRequestError,
    changed,
    get research() {
      return research;
    },
    set active(value) {
      active = value;
    },
    start: () =>
      research.start(
        "chat-one",
        "First prompt",
        "infer",
        { runId, startedAt: Date.parse(at) },
        true,
      ),
    tick: () =>
      act(async () => {
        for (const [id, timer] of [...timers])
          if (timer.delay === 2000) {
            timers.delete(id);
            timer.fn();
          }
      }),
    unmount: () => act(async () => root.unmount()),
    close: async () => {
      await act(async () => root.unmount());
      dom.window.close();
      for (const key of keys) {
        if (before[key]) Object.defineProperty(globalThis, key, before[key]);
        else delete globalThis[key];
      }
      await rm(output, { recursive: true, force: true });
    },
  };
}

test("workspace owns one submission until it finishes, independent of progress views", async (t) => {
  const h = await harness(t);
  let release;
  let calls = 0;
  t.mock.method(h.workspaceApi, "message", async () => {
    calls++;
    await new Promise((resolve) => (release = resolve));
    return detail;
  });
  try {
    let pending;
    await h.act(async () => {
      pending = h.start();
    });
    assert.equal(h.research.runs["chat-one"].status, "running");
    await assert.rejects(h.start(), /still researching/);
    assert.equal(calls, 1);
    h.active = [{ chat_id: "chat-one", ...status() }];
    await h.tick();
    assert.equal(
      h.changed.at(-1).title,
      "Named from prompt",
      "title refresh occurs while POST is pending",
    );
    await h.act(async () => {
      release();
      await pending;
    });
    assert.equal(h.research.runs["chat-one"].status, "completed");
    assert.equal(calls, 1);
  } finally {
    await h.close();
  }
});

test("workspace discovers hidden work after reload and refreshes its result on completion", async (t) => {
  const h = await harness(t);
  let posts = 0;
  t.mock.method(h.workspaceApi, "message", async () => {
    posts++;
    return detail;
  });
  try {
    h.active = [{ chat_id: "chat-one", ...status() }];
    await h.tick();
    assert.equal(h.research.runs["chat-one"].status, "running");
    assert.equal(
      h.research.runs["chat-one"].submission.startedAt,
      Date.parse(at),
    );
    h.active = [];
    await h.tick();
    assert.equal(h.research.runs["chat-one"].status, "completed");
    assert.equal(posts, 0);
    assert.equal(h.research.runs["chat-one"].revision, 1);
  } finally {
    await h.close();
  }
});

test("failed HTTP response never cancels running server research or replays a message", async (t) => {
  const h = await harness(t);
  let posts = 0;
  t.mock.method(h.workspaceApi, "message", async () => {
    posts++;
    throw new Error("network");
  });
  try {
    h.active = [{ chat_id: "chat-one", ...status() }];
    await h.act(async () => {
      await assert.rejects(h.start(), /network/);
    });
    await h.tick();
    assert.equal(h.research.runs["chat-one"].status, "running");
    h.active = [];
    await h.tick();
    assert.equal(h.research.runs["chat-one"].status, "completed");
    assert.equal(posts, 1);
  } finally {
    await h.close();
  }
});

test("progress outages retain the last known run", async (t) => {
  const h = await harness(t);
  try {
    h.active = [{ chat_id: "chat-one", ...status() }];
    await h.tick();
    t.mock.method(h.workspaceApi, "activeResearch", async () => {
      throw new Error("offline");
    });
    await h.tick();
    assert.equal(h.research.runs["chat-one"].status, "running");
  } finally {
    await h.close();
  }
});

test("unmount does not cancel the submitted message", async (t) => {
  const h = await harness(t);
  let release, options;
  t.mock.method(h.workspaceApi, "message", async (...args) => {
    options = args;
    await new Promise((resolve) => (release = resolve));
    return detail;
  });
  try {
    let pending;
    await h.act(async () => {
      pending = h.start();
    });
    await h.unmount();
    release();
    await pending;
    assert.equal(options.length, 5);
    assert.equal(options[3], runId);
    assert.equal(h.changed.length, 0);
  } finally {
    await h.close();
  }
});

test("active-run transport validates run IDs, scope and full status schema", async (t) => {
  const h = await harness(t);
  // Restore this method so the production parser is exercised.
  h.workspaceApi.activeResearch.mock.restore();
  let value = { runs: [{ chat_id: "chat-one", ...status() }] };
  t.mock.method(globalThis, "fetch", async () => Response.json(value));
  try {
    assert.equal(
      (await h.workspaceApi.activeResearch())[0].chat_id,
      "chat-one",
    );
    for (const bad of [
      { ...status(), chat_id: "bad/path" },
      { ...status("completed"), chat_id: "chat-one" },
      { ...status(), chat_id: "chat-one", prompt: "private" },
      { ...status(), chat_id: "chat-one", run_id: "bad" },
    ]) {
      value = { runs: [bad] };
      await assert.rejects(h.workspaceApi.activeResearch(), /unsupported/);
    }
  } finally {
    await h.close();
  }
});
