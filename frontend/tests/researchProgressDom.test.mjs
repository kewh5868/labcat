import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

const firstRun = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  secondRun = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const at = "2026-09-10T12:00:00Z";
const state = (phase, sequence, run_id = firstRun, status = "running") => ({
  run_id,
  status,
  phase,
  sequence,
  message: `Reported stage: ${phase}.`,
  started_at: at,
  updated_at: at,
});

async function harness(t) {
  const output = await mkdtemp(join(tmpdir(), "labcat-progress-dom-"));
  for (const name of [
    "ResearchProgress.tsx",
    "workspaceApi.ts",
    "LabcatMascot.tsx",
    "labcatMascotConfig.ts",
  ]) {
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
  const { default: Progress } = await import(
    pathToFileURL(join(output, "ResearchProgress.js")).href
  );
  const root = createRoot(document.getElementById("root"));
  let now = Date.parse(at),
    nextTimer = 0;
  const timers = new Map(),
    intervals = new Map();
  t.mock.method(Date, "now", () => now);
  t.mock.method(window, "setTimeout", (callback, delay) => {
    const id = ++nextTimer;
    timers.set(id, { callback, delay });
    return id;
  });
  t.mock.method(window, "clearTimeout", (id) => timers.delete(id));
  t.mock.method(window, "setInterval", (callback, delay) => {
    const id = ++nextTimer;
    intervals.set(id, { callback, delay });
    return id;
  });
  t.mock.method(window, "clearInterval", (id) => intervals.delete(id));
  return {
    act,
    dom,
    root,
    timers,
    intervals,
    render: async (chatId = "chat-one", runId = firstRun) =>
      act(async () =>
        root.render(
          createElement(Progress, {
            chatId,
            submission: { runId, startedAt: Date.parse(at) },
          }),
        ),
      ),
    tick: async (milliseconds = 1000) =>
      act(async () => {
        now += milliseconds;
        for (const { callback } of intervals.values()) callback();
        for (const [id, { callback, delay }] of [...timers])
          if (delay === 1000) {
            timers.delete(id);
            callback();
          }
      }),
    click: async (element) =>
      act(async () =>
        element.dispatchEvent(
          new dom.window.MouseEvent("click", { bubbles: true }),
        ),
      ),
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

test("research progress shows only reported stages and elapsed time while polling once per second", async (t) => {
  const h = await harness(t);
  let response = state("assessing_request", 1);
  const requests = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    requests.push({ path, options });
    return Response.json(response);
  });
  try {
    await h.render();
    assert.match(
      document.querySelector('[role="status"]').textContent,
      /assessing request/,
    );
    assert.equal(
      document.querySelector('[role="timer"]').textContent,
      "Elapsed 0s",
    );
    assert.equal(
      document.querySelector('[role="timer"]').getAttribute("aria-live"),
      "off",
      "elapsed seconds do not repeatedly interrupt screen readers",
    );
    assert.equal(requests.length, 1);
    response = state("retrieving_public_evidence", 2);
    await h.tick(61_000);
    assert.match(
      document.querySelector('[role="status"]').textContent,
      /retrieving public evidence/,
    );
    assert.equal(
      document.querySelector('[role="timer"]').textContent,
      "Elapsed 1m 01s",
    );
    assert.equal(requests.length, 2);
    response = state("assessing_request", 1);
    await h.tick();
    assert.match(
      document.querySelector('[role="status"]').textContent,
      /retrieving public evidence/,
      "older sequence cannot roll back the latest stage",
    );
    assert.ok(!document.querySelector('[role="progressbar"]'));
    assert.ok(
      !document.body.textContent.includes("%"),
      "elapsed time never invents a completion percentage",
    );
    response = state("completed", 3, firstRun, "completed");
    await h.tick();
    assert.match(
      document.querySelector(".research-last-update").textContent,
      /Waiting for the saved response/,
    );
    assert.equal(
      document.querySelector('[data-scene="beaker"]').dataset.animation,
      "beaker",
      "terminal status alone must not celebrate a clarification or refusal",
    );
    assert.ok(
      requests.every(
        ({ path, options }) =>
          path === `/api/chats/chat-one/research-status?run_id=${firstRun}` &&
          options.method === "GET",
      ),
    );
    await h.act(async () => h.root.unmount());
    assert.equal(h.timers.size, 0);
    assert.equal(h.intervals.size, 0);
  } finally {
    await h.close();
  }
});

test("progress connection failures retain the last stage and retry only status reads", async (t) => {
  const h = await harness(t);
  let fail = false,
    reads = 0;
  t.mock.method(globalThis, "fetch", async (_path, options) => {
    assert.equal(options.method, "GET");
    reads++;
    if (fail) throw new Error("PRIVATE_MODEL_LOG");
    return Response.json(state("preparing_report", reads));
  });
  try {
    await h.render();
    fail = true;
    await h.tick();
    assert.match(
      document.querySelector('[role="status"]').textContent,
      /Waiting for a progress connection/,
    );
    assert.match(
      document.querySelector(".research-last-stage").textContent,
      /preparing report/,
    );
    assert.ok(!document.body.textContent.includes("PRIVATE_MODEL_LOG"));
    assert.match(
      document.querySelector('[role="status"]').textContent,
      /may still be running/,
    );
    const before = reads;
    fail = false;
    await h.click(document.querySelector("button"));
    assert.equal(reads, before + 1);
    assert.equal(document.querySelector("button"), null);
    fail = true;
    await h.tick();
    const failedReads = reads;
    fail = false;
    await h.tick();
    assert.equal(
      reads,
      failedReads + 1,
      "read-only progress automatically reconnects",
    );
    assert.match(
      document.querySelector('[role="status"]').textContent,
      /preparing report/,
    );
  } finally {
    await h.close();
  }
});

test("progress waits for saved chat identity and discards late status after switching submissions or unmounting", async (t) => {
  const h = await harness(t);
  const requests = [];
  let finishOld, finishNew;
  t.mock.method(globalThis, "fetch", async (path, options) => {
    requests.push({ path, options });
    if (path.includes("chat-one")) {
      await new Promise((resolve) => {
        finishOld = resolve;
      });
      return Response.json(state("old_private_stage", 50));
    }
    await new Promise((resolve) => {
      finishNew = resolve;
    });
    return Response.json(state("current_stage", 1, secondRun));
  });
  try {
    await h.render(null);
    assert.equal(requests.length, 0);
    assert.match(document.body.textContent, /Creating your saved chat/);
    await h.render("chat-one");
    assert.equal(requests.length, 1);
    await h.tick();
    assert.equal(
      requests.length,
      1,
      "polls never overlap a pending status read",
    );
    await h.render("chat-two", secondRun);
    assert.equal(requests.length, 2);
    assert.equal(requests[0].options.signal.aborted, true);
    await h.act(async () => finishOld());
    assert.ok(!document.body.textContent.includes("old private stage"));
    await h.act(async () => finishNew());
    assert.match(document.body.textContent, /current stage/);
    await h.tick();
    const count = requests.length;
    await h.act(async () => h.root.unmount());
    assert.equal(requests.at(-1).options.signal.aborted, true);
    await h.act(async () => finishNew());
    await h.tick();
    assert.equal(requests.length, count);
    assert.equal(h.timers.size, 0);
    assert.equal(h.intervals.size, 0);
  } finally {
    await h.close();
  }
});
