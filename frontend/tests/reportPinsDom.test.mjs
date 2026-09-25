import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, before, test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

let output;
before(async () => {
  output = await mkdtemp(join(tmpdir(), "labcat-report-pins-"));
  for (const name of await readdir(new URL("../src/", import.meta.url))) {
    if (!/\.tsx?$/.test(name)) continue;
    const compiled = ts
      .transpileModule(
        await readFile(new URL(`../src/${name}`, import.meta.url), "utf8"),
        {
          compilerOptions: {
            target: ts.ScriptTarget.ES2022,
            module: ts.ModuleKind.ES2022,
            jsx: ts.JsxEmit.ReactJSX,
          },
        },
      )
      .outputText.replace(/import ['"][^'"]+\.css['"];?/g, "")
      .replace(
        /from (['"])([^'"]+)\1/g,
        (_match, _quote, specifier) =>
          `from '${specifier.startsWith(".") ? `${specifier}.js` : import.meta.resolve(specifier)}'`,
      );
    await writeFile(join(output, name.replace(/\.tsx?$/, ".js")), compiled);
  }
  await writeFile(join(output, "package.json"), '{"type":"module"}');
});
after(async () => {
  await rm(output, { recursive: true, force: true });
});

async function environment(check) {
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
      configurable: true,
      writable: true,
    });
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const root = createRoot(document.getElementById("root"));
  try {
    await check({
      dom,
      act,
      root,
      createElement,
      module: (name) => import(pathToFileURL(join(output, `${name}.js`)).href),
      click: async (element) => {
        assert.ok(element);
        await act(async () => element.click());
      },
      button: (name, parent = document) =>
        [...parent.querySelectorAll("button")].find(
          (button) => button.textContent.replace("⌑", "") === name,
        ),
    });
  } finally {
    await act(async () => root.unmount());
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
  }
}

const date = "2026-09-10T12:00:00Z";
const snapshot = {
  id: "snapshot-one",
  project_id: "project-one",
  mode: "snapshot",
  chat_id: "chat-one",
  report_id: "report-one",
  created_at: date,
  updated_at: date,
};
const first = {
  id: "report-one",
  project_id: "project-one",
  chat_id: "chat-one",
  message_id: "message-one",
  title: "Fixture report",
  stage: "complete",
  pi_summary: "Summary:\n\nSaved first fixture report.",
  technical_audit: "Technical View:\n\nSaved first fixture overview.",
  source_ids: [],
  pinned: true,
  created_at: date,
  snapshot_pin: snapshot,
  tracking_pin: null,
  latest_report_id: "report-two",
};
const second = {
  ...first,
  id: "report-two",
  message_id: "message-two",
  pi_summary: "Summary:\n\nSaved second fixture report.",
  pinned: false,
  snapshot_pin: null,
};

test("snapshot and tracking are two directly available independent pin buttons", async () =>
  environment(async ({ module, root, createElement, act, click, button }) => {
    const { default: Controls } = await module("ReportPinControls");
    const calls = [];
    let snapshots = 0;
    const props = {
      report: second,
      snapshots: [snapshot],
      trackingPin: null,
      onSnapshot: async () => {
        snapshots += 1;
      },
      onAction: async (action) => calls.push(action),
    };
    await act(async () => root.render(createElement(Controls, props)));
    assert.equal(
      document.querySelectorAll("button").length,
      2,
      "older snapshots do not add a third pin choice to the current report",
    );
    assert.equal(
      document.querySelector("details, summary, select"),
      null,
      "pin choices have no dropdown",
    );
    assert.match(button("Pin snapshot").title, /Later prompts will not change/);
    assert.match(
      button("Pin tracking").title,
      /automatically shows this chat’s newest completed report/,
    );
    await click(button("Pin tracking"));
    assert.deepEqual(calls[0], {
      type: "tracking",
      chatId: "chat-one",
      tracking: true,
    });
    await click(button("Pin snapshot"));
    assert.equal(snapshots, 1, "new snapshot is a separate action");
    const tracking = {
      ...snapshot,
      id: "tracking-one",
      mode: "latest",
      report_id: second.id,
    };
    await act(async () =>
      root.render(createElement(Controls, { ...props, trackingPin: tracking })),
    );
    assert.equal(button("Unpin tracking").getAttribute("aria-pressed"), "true");
    assert.equal(button("Pin snapshot").getAttribute("aria-pressed"), "false");
    await click(button("Unpin tracking"));
    assert.deepEqual(calls.at(-1), {
      type: "tracking",
      chatId: "chat-one",
      tracking: false,
    });
    await act(async () =>
      root.render(createElement(Controls, { ...props, requiresProject: true })),
    );
    assert.equal(document.querySelectorAll("button").length, 2);
    assert.match(button("Pin snapshot").title, /Choose a project first/);
    assert.match(button("Pin tracking").title, /Choose a project first/);
    assert.match(
      document.querySelector(".report-pin-project-hint").textContent,
      /Choose a project/,
    );
    await click(button("Pin snapshot"));
    assert.equal(
      snapshots,
      2,
      "general chats reach the existing project chooser through their normal handler",
    );
    await click(button("Pin tracking"));
    assert.deepEqual(calls.at(-1), {
      type: "tracking",
      chatId: "chat-one",
      tracking: true,
    });
  }));

test("an outdated project snapshot keeps its explicit replacement action separate from the two pin choices", async () =>
  environment(async ({ module, root, createElement, act, click, button }) => {
    const { default: Controls } = await module("ReportPinControls");
    const calls = [];
    const props = {
      report: { ...first, pin: snapshot },
      snapshots: [snapshot],
      onSnapshot: async () => {},
      onAction: async (action) => calls.push(action),
    };
    await act(async () => root.render(createElement(Controls, props)));
    assert.equal(
      document.querySelectorAll(".report-pin-actions button").length,
      2,
    );
    assert.equal(document.querySelector("details, summary, select"), null);
    assert.match(
      button("Update this snapshot to latest").title,
      /earlier report stays in chat history/,
    );
    await click(button("Update this snapshot to latest"));
    assert.deepEqual(calls, [
      { type: "update_snapshot", pin: snapshot, reportId: "report-two" },
    ]);
    await act(async () =>
      root.render(
        createElement(Controls, {
          ...props,
          snapshots: [
            snapshot,
            { ...snapshot, id: "snapshot-two", report_id: second.id },
          ],
        }),
      ),
    );
    assert.equal(
      button("Update this snapshot to latest"),
      undefined,
      "the current revision cannot replace another snapshot when it is already saved",
    );
  }));

test("pin mutations prevent duplicate actions and expose a recoverable conflict without changing pin state", async () =>
  environment(async ({ module, root, createElement, act, click, button }) => {
    const { default: Controls } = await module("ReportPinControls");
    let calls = 0,
      reject;
    const request = new Promise((_resolve, rejectRequest) => {
      reject = rejectRequest;
    });
    await act(async () =>
      root.render(
        createElement(Controls, {
          report: second,
          snapshots: [snapshot],
          onSnapshot: async () => {
            calls += 1;
          },
          onAction: async () => {
            calls += 1;
            return request;
          },
        }),
      ),
    );
    const tracking = button("Pin tracking");
    await act(async () => {
      tracking.click();
      tracking.click();
      button("Pin snapshot").click();
    });
    assert.equal(calls, 1);
    assert.equal(tracking.disabled, true);
    assert.equal(button("Pin snapshot").disabled, true);
    assert.equal(
      document.querySelector("[aria-busy]").getAttribute("aria-busy"),
      "true",
    );
    await act(async () =>
      reject(
        new Error(
          "The workspace pin changed. Reload project contents before trying again.",
        ),
      ),
    );
    assert.match(
      document.querySelector('[role="alert"]').textContent,
      /Reload project contents/,
    );
    assert.ok(button("Pin snapshot"));
    assert.equal(calls, 1, "conflicts are not retried automatically");
  }));

test("project contents show separate snapshot and live cards for one revision with unique control identities", async (t) =>
  environment(async ({ module, root, createElement, act, click, button }) => {
    const { Contents } = await module("ProjectWorkspace");
    const { workspaceApi, defaultSettings } = await module("workspaceApi");
    const tracking = { ...snapshot, id: "tracking-one", mode: "latest" };
    const report = {
      ...first,
      latest_report_id: first.id,
      tracking_pin: tracking,
    };
    const project = {
      id: "project-one",
      name: "Fixture project",
      pin_counts: { reports: 2, sources: 0 },
    };
    let result = {
      chats: [],
      reports: [
        { ...report, pin: snapshot },
        { ...report, pin: tracking },
      ],
      sources: [],
    };
    t.mock.method(workspaceApi, "contents", async () => result);
    const actions = [],
      removals = [];
    const props = {
      project,
      revision: 0,
      presentation: defaultSettings.presentation,
      onPin: async (...args) => removals.push(args),
      onReportPin: async (action) => actions.push(action),
      onOpenChat: () => {},
    };
    await act(async () => root.render(createElement(Contents, props)));
    const cards = [
      ...document.querySelectorAll(".pinned-reports > .research-report"),
    ];
    assert.equal(cards.length, 2);
    assert.match(cards[0].textContent, /Snapshot ·/);
    assert.match(cards[1].textContent, /Tracking latest ·/);
    const ids = [...document.querySelectorAll("[id]")].map((node) => node.id);
    assert.equal(
      new Set(ids).size,
      ids.length,
      "duplicate report revisions retain unique form labels",
    );
    await click(button("Unpin tracking", cards[1]));
    assert.deepEqual(actions, [
      { type: "tracking", chatId: "chat-one", tracking: false },
    ]);
    assert.equal(
      removals.length,
      0,
      "stopping a tracked card does not remove its snapshot",
    );
    await click(button("Unpin snapshot", cards[1]));
    assert.deepEqual(
      removals,
      [["report", first.id, true]],
      "snapshot and tracking remain independently removable from the same revision",
    );
    result = {
      ...result,
      reports: [
        { ...first, pin: snapshot },
        {
          ...second,
          pin: { ...tracking, report_id: second.id },
          tracking_pin: { ...tracking, report_id: second.id },
        },
      ],
    };
    await act(async () =>
      root.render(createElement(Contents, { ...props, revision: 1 })),
    );
    const current = [
      ...document.querySelectorAll(".pinned-reports > .research-report"),
    ];
    assert.match(current[0].textContent, /Saved first fixture report/);
    assert.match(current[1].textContent, /Saved second fixture report/);
  }));
