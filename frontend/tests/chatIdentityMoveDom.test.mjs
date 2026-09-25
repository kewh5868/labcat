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
