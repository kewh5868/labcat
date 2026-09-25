import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

const preferenceKey = "labcat-workspace-view-v1";
async function harness({ saved, storageUnavailable = false } = {}) {
  const output = await mkdtemp(join(tmpdir(), "labcat-sidebar-test-"));
  const source = await readFile(
    new URL("../src/SidebarView.tsx", import.meta.url),
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
  await writeFile(join(output, "SidebarView.mjs"), compiled);
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
  dom.window.HTMLElement.prototype.setPointerCapture = function () {};
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
  const { useSidebarView, SidebarViewControls } = await import(
    pathToFileURL(join(output, "SidebarView.mjs"))
  );
  function Layout() {
    const sidebar = useSidebarView();
    return createElement(
      "div",
      { id: "shell", style: sidebar.style },
      !sidebar.hidden &&
        createElement("aside", { id: "workspace-sidebar" }, sidebar.resizer),
      createElement(
        "main",
        null,
        createElement(SidebarViewControls, {
          hidden: sidebar.hidden,
          onToggle: sidebar.toggle,
          onReset: sidebar.reset,
        }),
        createElement("button", { id: "outside" }, "Outside"),
      ),
    );
  }
  const root = createRoot(document.getElementById("root"));
  const click = async (element) => {
    assert.ok(element);
    await act(async () =>
      element.dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true }),
      ),
    );
  };
  const key = async (element, value, options = {}) => {
    assert.ok(element);
    await act(async () =>
      element.dispatchEvent(
        new dom.window.KeyboardEvent("keydown", {
          key: value,
          bubbles: true,
          cancelable: true,
          ...options,
        }),
      ),
    );
  };
  return {
    dom,
    act,
    click,
    key,
    render: async (key = "first") =>
      act(async () => root.render(createElement(Layout, { key }))),
    pointer: async (element, type, clientX) => {
      const event = new dom.window.MouseEvent(type, {
        bubbles: true,
        cancelable: true,
        button: 0,
        clientX,
      });
      Object.defineProperty(event, "pointerId", { value: 5 });
      await act(async () => element.dispatchEvent(event));
    },
    resize: async (width) => {
      dom.window.innerWidth = width;
      await act(async () =>
        dom.window.dispatchEvent(new dom.window.Event("resize")),
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
const button = (name) =>
  [...document.querySelectorAll("button")].find(
    (item) => item.textContent === name,
  );
const resizer = () => document.querySelector('[role="separator"]');
const width = () => Number(resizer().getAttribute("aria-valuenow"));
const view = () => document.querySelector(".workspace-view-trigger");

test("sidebar resizing is bounded, keyboard accessible, resettable and remembered with hidden state", async () => {
  const h = await harness();
  try {
    await h.render();
    assert.equal(width(), 238);
    await h.key(resizer(), "ArrowRight");
    assert.equal(width(), 248);
    await h.key(resizer(), "ArrowLeft", { shiftKey: true });
    assert.equal(width(), 220);
    await h.key(resizer(), "End");
    assert.equal(width(), 430);
    await h.key(resizer(), "ArrowRight");
    assert.equal(width(), 430);
    await h.key(resizer(), "Enter");
    assert.equal(width(), 238);
    await h.pointer(resizer(), "pointerdown", 238);
    await h.pointer(resizer(), "pointermove", 360);
    await h.pointer(resizer(), "pointerup", 360);
    assert.equal(width(), 360);
    assert.equal(
      document
        .querySelector("#shell")
        .style.getPropertyValue("--workspace-sidebar-width"),
      "360px",
    );
    await h.click(view());
    await h.click(button("Hide sidebar"));
    assert.equal(resizer(), null);
    assert.ok(view(), "View stays accessible while navigation is hidden");
    assert.equal(document.activeElement, view());
    await h.render("restart");
    assert.equal(resizer(), null);
    await h.click(view());
    await h.click(button("Show sidebar"));
    assert.equal(width(), 360);
    await h.click(view());
    await h.click(button("Reset sidebar width"));
    assert.equal(width(), 238);
    await h.key(resizer(), "ArrowRight");
    await h.act(async () =>
      resizer().dispatchEvent(
        new h.dom.window.MouseEvent("dblclick", { bubbles: true }),
      ),
    );
    assert.equal(width(), 238);
    assert.deepEqual(
      JSON.parse(h.dom.window.localStorage.getItem(preferenceKey)),
      { version: 1, sidebar_width: 238, sidebar_hidden: false },
    );
  } finally {
    await h.close();
  }
});

test("sidebar adapts to viewport without losing the saved width and safely handles malformed preferences", async () => {
  const h = await harness({
    saved: JSON.stringify({
      version: 1,
      sidebar_width: 10000,
      sidebar_hidden: "true",
    }),
  });
  try {
    await h.resize(1400);
    await h.render();
    assert.equal(width(), 480);
    await h.resize(950);
    assert.equal(width(), 399);
    await h.resize(1400);
    assert.equal(
      width(),
      480,
      "viewport clamping must not overwrite the preferred width",
    );
    await h.resize(700);
    await h.pointer(resizer(), "pointerdown", 200);
    await h.pointer(resizer(), "pointermove", 400);
    await h.pointer(resizer(), "pointerup", 400);
    await h.resize(1400);
    assert.equal(width(), 480, "stacked mobile navigation does not resize");
    h.dom.window.localStorage.setItem(preferenceKey, "{broken JSON");
    await h.render("malformed");
    assert.equal(width(), 238);
    h.dom.window.localStorage.setItem(
      preferenceKey,
      JSON.stringify({ version: 1, sidebar_width: "380", sidebar_hidden: 1 }),
    );
    await h.render("wrong types");
    assert.equal(width(), 238);
  } finally {
    await h.close();
  }
});

test("View options dismiss on Escape, outside pointer and keyboard focus; restricted storage remains usable", async () => {
  const h = await harness({ storageUnavailable: true });
  try {
    await h.render();
    await h.click(view());
    assert.equal(view().getAttribute("aria-expanded"), "true");
    await h.key(button("Hide sidebar"), "Escape");
    assert.equal(view().getAttribute("aria-expanded"), "false");
    assert.equal(document.activeElement, view());
    await h.click(view());
    await h.pointer(button("Outside"), "pointerdown", 600);
    assert.equal(view().getAttribute("aria-expanded"), "false");
    await h.click(view());
    await h.act(async () =>
      view().dispatchEvent(
        new h.dom.window.FocusEvent("focusout", {
          bubbles: true,
          relatedTarget: button("Outside"),
        }),
      ),
    );
    assert.equal(view().getAttribute("aria-expanded"), "false");
    await h.click(view());
    await h.click(button("Hide sidebar"));
    await h.click(view());
    await h.click(button("Show sidebar"));
    assert.equal(width(), 238);
  } finally {
    await h.close();
  }
});
