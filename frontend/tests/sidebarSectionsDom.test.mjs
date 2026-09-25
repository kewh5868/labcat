import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

const preferenceKey = "labcat-sidebar-sections-v1";
async function harness({ saved, storageUnavailable = false } = {}) {
  const output = await mkdtemp(join(tmpdir(), "labcat-sidebar-sections-test-"));
  const source = await readFile(
    new URL("../src/SidebarSections.tsx", import.meta.url),
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
    .outputText.replace(
      /from (['"])([^'"]+)\1/g,
      (_match, _quote, specifier) => `from '${import.meta.resolve(specifier)}'`,
    );
  await writeFile(join(output, "SidebarSections.mjs"), compiled);
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
  const captures = new WeakMap();
  const captured = [],
    released = [];
  dom.window.HTMLElement.prototype.setPointerCapture = function (pointerId) {
    captures.set(this, pointerId);
    captured.push(pointerId);
  };
  dom.window.HTMLElement.prototype.hasPointerCapture = function (pointerId) {
    return captures.get(this) === pointerId;
  };
  dom.window.HTMLElement.prototype.releasePointerCapture = function (
    pointerId,
  ) {
    if (captures.get(this) === pointerId) captures.delete(this);
    released.push(pointerId);
  };
  if (saved !== undefined)
    dom.window.localStorage.setItem(preferenceKey, saved);
  if (storageUnavailable)
    Object.defineProperty(dom.window, "localStorage", {
      get() {
        throw new Error("Storage unavailable");
      },
    });
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { default: SidebarSections } = await import(
    pathToFileURL(join(output, "SidebarSections.mjs"))
  );
  let projectChatsCreated = 0;
  function Layout({ visible = true }) {
    return createElement(
      "div",
      null,
      visible &&
        createElement(SidebarSections, {
          projectAction: createElement(
            "button",
            {
              type: "button",
              id: "new-project-chat",
              "aria-label": "New chat in selected project",
              onClick: () => {
                projectChatsCreated += 1;
              },
            },
            "+",
          ),
          projects: createElement(
            "nav",
            { "aria-label": "Projects", tabIndex: 0 },
            createElement("button", { type: "button" }, "Example project"),
          ),
          chats: createElement(
            "nav",
            { "aria-label": "General chats", tabIndex: 0 },
            createElement("button", { type: "button" }, "Example chat"),
          ),
        }),
    );
  }
  const root = createRoot(document.getElementById("root"));
  return {
    dom,
    act,
    captured,
    released,
    get projectChatsCreated() {
      return projectChatsCreated;
    },
    render: async ({ visible = true, key = "first" } = {}) =>
      act(async () => root.render(createElement(Layout, { visible, key }))),
    click: async (element) => {
      assert.ok(element);
      await act(async () =>
        element.dispatchEvent(
          new dom.window.MouseEvent("click", { bubbles: true }),
        ),
      );
    },
    key: async (element, key, options = {}) => {
      assert.ok(element);
      const event = new dom.window.KeyboardEvent("keydown", {
        key,
        bubbles: true,
        cancelable: true,
        ...options,
      });
      await act(async () => element.dispatchEvent(event));
      return event;
    },
    pointer: async (
      element,
      type,
      clientY,
      { pointerId = 5, button = 0 } = {},
    ) => {
      assert.ok(element);
      const event = new dom.window.MouseEvent(type, {
        bubbles: true,
        cancelable: true,
        button,
        clientY,
      });
      Object.defineProperty(event, "pointerId", { value: pointerId });
      if (type === "lostpointercapture") captures.delete(element);
      await act(async () => element.dispatchEvent(event));
      return event;
    },
    geometry: ({ height = 418, dividerHeight = 18, projectsHeight } = {}) => {
      // JSDOM has no layout engine: supply only the measured geometry used by dragging.
      panels().getBoundingClientRect = () => ({ height });
      separator().getBoundingClientRect = () => ({ height: dividerHeight });
      panels().firstElementChild.getBoundingClientRect = () => ({
        height: projectsHeight ?? ((height - dividerHeight) * share()) / 100,
      });
    },
    windowEvent: async (type) =>
      act(async () => dom.window.dispatchEvent(new dom.window.Event(type))),
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
const panels = () => document.querySelector(".sidebar-history-panels");
const separator = () =>
  document.querySelector(
    '[role="separator"][aria-label="Resize projects and general chats"]',
  );
const share = () => Number(separator().getAttribute("aria-valuenow"));
const heading = (section) =>
  document.querySelectorAll(".sidebar-section-heading")[
    section === "projects" ? 0 : 1
  ];
const isResizing = () => panels().classList.contains("is-resizing");

test("section headings give either list more space and restore a custom split without invoking the project action", async () => {
  const h = await harness({
    saved: JSON.stringify({ version: 1, split: 65, focused: null }),
  });
  try {
    await h.render();
    assert.equal(share(), 65);
    assert.equal(separator().getAttribute("aria-orientation"), "horizontal");
    assert.equal(
      separator().getAttribute("aria-valuetext"),
      "Projects 65%, general chats 35%",
    );
    const controlled = separator().getAttribute("aria-controls").split(" ");
    for (const id of controlled)
      assert.equal(document.getElementById(id).tagName, "SECTION");
    assert.equal(
      heading("projects").getAttribute("aria-controls"),
      controlled[0],
    );
    assert.equal(heading("chats").getAttribute("aria-controls"), controlled[1]);
    assert.equal(
      document.querySelector("#new-project-chat").parentElement,
      heading("projects").parentElement,
    );
    assert.equal(
      document
        .querySelector("#new-project-chat")
        .closest(".sidebar-section-heading"),
      null,
    );
    await h.click(heading("projects"));
    assert.equal(share(), 80);
    assert.equal(heading("projects").getAttribute("aria-pressed"), "true");
    assert.equal(heading("chats").getAttribute("aria-pressed"), "false");
    await h.click(document.querySelector("#new-project-chat"));
    assert.equal(h.projectChatsCreated, 1);
    assert.equal(
      share(),
      80,
      "the project action must not toggle section focus",
    );
    await h.click(heading("projects"));
    assert.equal(share(), 65);
    await h.click(heading("chats"));
    assert.equal(share(), 20);
    await h.click(heading("projects"));
    assert.equal(share(), 80);
    await h.click(heading("projects"));
    assert.equal(
      share(),
      65,
      "switching focused sections retains the original custom split",
    );
    assert.equal(
      h.projectChatsCreated,
      1,
      "section headings must not create chats",
    );
    assert.equal(
      panels().style.getPropertyValue("--sidebar-projects-share"),
      "65fr",
    );
    assert.equal(
      panels().style.getPropertyValue("--sidebar-chats-share"),
      "35fr",
    );
    assert.ok(document.querySelector('nav[aria-label="Projects"]'));
    assert.ok(document.querySelector('nav[aria-label="General chats"]'));
  } finally {
    await h.close();
  }
});

test("section divider supports keyboard bounds and reset, including leaving heading focus", async () => {
  const h = await harness();
  try {
    await h.render();
    assert.equal(share(), 50);
    assert.equal(separator().tabIndex, 0);
    assert.equal(separator().getAttribute("aria-valuemin"), "20");
    assert.equal(separator().getAttribute("aria-valuemax"), "80");
    assert.equal(
      (await h.key(separator(), "ArrowDown")).defaultPrevented,
      true,
    );
    assert.equal(share(), 55);
    await h.key(separator(), "ArrowUp", { shiftKey: true });
    assert.equal(share(), 45);
    await h.key(separator(), "Home");
    assert.equal(share(), 20);
    await h.key(separator(), "ArrowUp");
    assert.equal(share(), 20);
    await h.key(separator(), "End");
    assert.equal(share(), 80);
    await h.key(separator(), "ArrowDown");
    assert.equal(share(), 80);
    await h.key(separator(), "Enter");
    assert.equal(share(), 50);
    await h.click(heading("projects"));
    await h.key(separator(), "ArrowUp");
    assert.equal(share(), 75);
    assert.equal(heading("projects").getAttribute("aria-pressed"), "false");
    assert.equal(
      (await h.key(separator(), "ArrowRight")).defaultPrevented,
      false,
    );
    assert.equal(share(), 75);
    await h.act(async () =>
      separator().dispatchEvent(
        new h.dom.window.MouseEvent("dblclick", { bubbles: true }),
      ),
    );
    assert.equal(share(), 50);
    assert.deepEqual(
      JSON.parse(h.dom.window.localStorage.getItem(preferenceKey)),
      { version: 1, split: 50, focused: null },
    );
  } finally {
    await h.close();
  }
});

test("dragging uses visible panel geometry, captures its pointer, and rejects other buttons and pointers", async () => {
  const h = await harness();
  try {
    await h.render();
    h.geometry({ projectsHeight: 240 });
    await h.pointer(separator(), "pointerdown", 100, { button: 2 });
    await h.pointer(separator(), "pointermove", 180);
    assert.equal(share(), 50);
    assert.equal(isResizing(), false);
    assert.deepEqual(h.captured, []);
    await h.pointer(separator(), "pointerdown", 100);
    assert.deepEqual(h.captured, [5]);
    assert.equal(isResizing(), true);
    assert.equal(document.activeElement, separator());
    await h.pointer(separator(), "pointerdown", 200, { pointerId: 9 });
    await h.pointer(separator(), "pointermove", 500, { pointerId: 9 });
    await h.pointer(separator(), "pointerup", 500, { pointerId: 9 });
    assert.equal(share(), 50);
    assert.equal(isResizing(), true);
    assert.deepEqual(h.captured, [5]);
    await h.pointer(separator(), "pointermove", 120);
    assert.equal(
      share(),
      65,
      "drag starts at the measured 60%, not the saved 50%",
    );
    await h.pointer(separator(), "pointermove", 1000);
    assert.equal(share(), 80);
    await h.pointer(separator(), "pointermove", -1000);
    assert.equal(share(), 20);
    await h.pointer(separator(), "pointerup", -1000);
    assert.equal(isResizing(), false);
    assert.deepEqual(h.released, [5]);
    await h.pointer(separator(), "pointermove", 1000);
    assert.equal(share(), 20, "movement after release must not resize");
    h.geometry({ height: 18, dividerHeight: 18 });
    await h.pointer(separator(), "pointerdown", 100);
    assert.equal(isResizing(), false);
    assert.deepEqual(h.captured, [5]);
  } finally {
    await h.close();
  }
});

test("cancelling a drag releases capture and prevents stale movement after keyboard, heading, or window actions", async () => {
  const h = await harness();
  try {
    await h.render();
    h.geometry();
    for (const cancellation of [
      "pointercancel",
      "lostpointercapture",
      "Escape",
      "blur",
      "resize",
      "heading",
      "Enter",
      "double-click",
    ]) {
      await h.key(separator(), "Enter");
      await h.pointer(separator(), "pointerdown", 100);
      await h.pointer(separator(), "pointermove", 140);
      assert.equal(share(), 60);
      const releaseCount = h.released.length;
      if (cancellation === "Escape" || cancellation === "Enter")
        await h.key(separator(), cancellation);
      else if (cancellation === "blur" || cancellation === "resize")
        await h.windowEvent(cancellation);
      else if (cancellation === "heading") await h.click(heading("projects"));
      else if (cancellation === "double-click")
        await h.act(async () =>
          separator().dispatchEvent(
            new h.dom.window.MouseEvent("dblclick", { bubbles: true }),
          ),
        );
      else await h.pointer(separator(), cancellation, 140);
      assert.equal(isResizing(), false, `${cancellation} clears drag styling`);
      assert.equal(
        separator().hasPointerCapture(5),
        false,
        `${cancellation} does not leave the pointer captured`,
      );
      assert.equal(
        h.released.length,
        releaseCount + (cancellation === "lostpointercapture" ? 0 : 1),
        `${cancellation} releases an active capture once`,
      );
      const expectedShare =
        cancellation === "heading"
          ? 80
          : cancellation === "Enter" || cancellation === "double-click"
            ? 50
            : 60;
      await h.pointer(separator(), "pointermove", 220);
      assert.equal(
        share(),
        expectedShare,
        `${cancellation} stops subsequent pointer movement`,
      );
    }
  } finally {
    await h.close();
  }
});

test("section split and focused heading survive removal for search or hidden sidebar and a remount", async () => {
  const h = await harness();
  try {
    await h.render();
    await h.key(separator(), "ArrowDown", { shiftKey: true });
    assert.equal(share(), 60);
    await h.click(heading("chats"));
    assert.equal(share(), 20);
    assert.deepEqual(
      JSON.parse(h.dom.window.localStorage.getItem(preferenceKey)),
      { version: 1, split: 60, focused: "chats" },
    );
    // Workspace search and sidebar hiding both remove this subtree; exercise that lifecycle directly.
    await h.render({ visible: false });
    assert.equal(separator(), null);
    await h.render();
    assert.equal(share(), 20);
    assert.equal(heading("chats").getAttribute("aria-pressed"), "true");
    await h.click(heading("chats"));
    assert.equal(share(), 60);
    h.geometry();
    await h.pointer(separator(), "pointerdown", 100);
    assert.equal(isResizing(), true);
    await h.render({ visible: false });
    await h.windowEvent("resize");
    await h.render({ key: "restart" });
    assert.equal(share(), 60);
    assert.equal(isResizing(), false);
    h.geometry();
    await h.pointer(separator(), "pointermove", 300);
    assert.equal(share(), 60);
    await h.pointer(separator(), "pointerdown", 100);
    await h.pointer(separator(), "pointermove", 140);
    await h.pointer(separator(), "pointerup", 140);
    assert.equal(share(), 70, "a remounted divider starts a fresh drag");
  } finally {
    await h.close();
  }
});

test("malformed, old, and out-of-range section preferences safely fall back or clamp", async () => {
  const cases = [
    ["{broken JSON", 50, false],
    ["null", 50, false],
    [JSON.stringify({ version: 2, split: 70, focused: "projects" }), 50, false],
    [JSON.stringify({ version: 1, split: "70", focused: true }), 50, false],
    ['{"version":1,"split":1e309,"focused":null}', 50, false],
    [JSON.stringify({ version: 1, split: -100, focused: null }), 20, false],
    [
      JSON.stringify({ version: 1, split: 1000, focused: "unknown" }),
      80,
      false,
    ],
    [
      JSON.stringify({ version: 1, split: 62.6, focused: "projects" }),
      80,
      true,
    ],
  ];
  const h = await harness();
  try {
    for (const [index, [saved, expectedShare, focused]] of cases.entries()) {
      h.dom.window.localStorage.setItem(preferenceKey, saved);
      await h.render({ key: `case-${index}` });
      assert.equal(share(), expectedShare, saved);
      assert.equal(
        heading("projects").getAttribute("aria-pressed"),
        String(focused),
        saved,
      );
    }
    await h.click(heading("projects"));
    assert.equal(share(), 63);
  } finally {
    await h.close();
  }
});

test("unavailable browser storage does not block section controls or resizing", async () => {
  const h = await harness({ storageUnavailable: true });
  try {
    await h.render();
    assert.equal(share(), 50);
    await h.key(separator(), "ArrowDown");
    assert.equal(share(), 55);
    await h.click(heading("projects"));
    assert.equal(share(), 80);
    await h.click(heading("projects"));
    assert.equal(share(), 55);
    h.geometry();
    await h.pointer(separator(), "pointerdown", 100);
    await h.pointer(separator(), "pointermove", 120);
    await h.pointer(separator(), "pointerup", 120);
    assert.equal(share(), 60);
  } finally {
    await h.close();
  }
});
