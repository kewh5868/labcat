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

test("workspace shell preserves clipped keyboard access and never trusts browser edition preferences", async (t) => {
  const h = await harness();
  window.localStorage.setItem("edition", "developer");
  t.mock.method(globalThis, "fetch", async (url) => {
    if (String(url).startsWith("/api/status"))
      return Response.json({
        application: "Labcat",
        version: "0.1.0",
        stage: "test",
        style: "audit",
        message: "Test status response",
        compute: "local",
        provider: "none",
        constraints: ["Public sources only"],
        candidates: [],
        limitations: [],
        implemented: [],
        next_steps: [],
      });
    if (url === "/api/runtime")
      return Response.json({
        edition: "user",
        developer_settings_available: true,
      });
    return Response.json({}, { status: 503 });
  });
  try {
    const { default: App } = await h.load("App");
    await h.act(async () => h.root.render(h.createElement(App)));
    const link = document.querySelector(".skip-link");
    assert.equal(link.getAttribute("href"), "#project-main");
    assert.equal(document.querySelector("main").id, "project-main");
    assert.equal(document.querySelector("main").tabIndex, -1);
    assert.match(document.querySelector(".brand").textContent, /Labcat/);
    assert.ok(
      !document
        .querySelector(".sidebar")
        .textContent.includes("Developer Settings"),
    );
    const css = await readFile(
      new URL("../src/styles.css", import.meta.url),
      "utf8",
    );
    assert.match(css, /\.skip-link\s*\{[^}]*clip-path:\s*inset\(50%\)/s);
    assert.match(css, /\.skip-link:focus\s*\{[^}]*clip-path:\s*none/s);
    link.focus();
    assert.equal(document.activeElement, link);
  } finally {
    await h.close();
  }
});
