import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, before, test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

let output;
before(async () => {
  output = await mkdtemp(join(tmpdir(), "labcat-running-indicator-"));
  const source = await readFile(
    new URL("../src/RunningResearchIndicator.tsx", import.meta.url),
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
      (_match, _quote, specifier) => `from '${import.meta.resolve(specifier)}'`,
    );
  await writeFile(join(output, "RunningResearchIndicator.mjs"), compiled);
});
after(async () => {
  await rm(output, { recursive: true, force: true });
});

async function withIndicator(check) {
  const css = await readFile(
    new URL("../src/runningResearchIndicator.css", import.meta.url),
    "utf8",
  );
  const dom = new JSDOM(`<style>${css}</style><div id="root"></div>`);
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
  const { default: Indicator } = await import(
    pathToFileURL(join(output, "RunningResearchIndicator.mjs"))
  );
  const root = createRoot(document.getElementById("root"));
  try {
    await check({
      dom,
      createElement,
      Indicator,
      render: async (element) => act(async () => root.render(element)),
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

test("the compact flask exposes one stable research label with no focusable or remote content", async () => {
  await withIndicator(async ({ dom, createElement, Indicator, render }) => {
    await render(
      createElement(
        "button",
        { type: "button" },
        createElement(
          "span",
          { className: "sidebar-chat-identity-line" },
          "Saved chat",
          createElement(Indicator),
        ),
      ),
    );
    const indicator = document.querySelector('[role="img"]');
    assert.equal(indicator.getAttribute("aria-label"), "Research running");
    assert.equal(
      indicator.title,
      "Research continues when you open another chat",
    );
    const svg = indicator.querySelector("svg");
    assert.equal(svg.getAttribute("aria-hidden"), "true");
    assert.equal(svg.getAttribute("focusable"), "false");
    assert.equal(
      indicator.querySelectorAll(
        "button, a, [tabindex], image, img, animate, script",
      ).length,
      0,
    );
    assert.equal(indicator.querySelectorAll("circle").length, 3);
    const style = dom.window.getComputedStyle(indicator);
    assert.equal(style.width, "16px");
    assert.equal(style.height, "20px");
    assert.equal(style.flexShrink, "0");
    await render(
      createElement(Indicator, {
        label: "<img onerror=alert(1)> research running",
      }),
    );
    assert.equal(
      document.querySelector('[role="img"]').getAttribute("aria-label"),
      "<img onerror=alert(1)> research running",
    );
    assert.equal(document.querySelectorAll("img, [onerror]").length, 0);
  });
});

test("running markers can accompany general and project chats independently of selected chat", async () => {
  await withIndicator(async ({ createElement, Indicator, render }) => {
    // Synthetic parent state: the workspace supplies authoritative running IDs.
    const rows = [
      { id: "general-running", scope: "general" },
      { id: "project-running", scope: "project" },
      { id: "idle", scope: "general" },
    ];
    const list = (selected, running) =>
      createElement(
        "nav",
        null,
        rows.map((row) =>
          createElement(
            "button",
            {
              key: row.id,
              id: row.id,
              "data-scope": row.scope,
              "aria-current": row.id === selected ? "page" : undefined,
            },
            row.id,
            running.has(row.id) && createElement(Indicator),
          ),
        ),
      );
    await render(list("idle", new Set(["general-running", "project-running"])));
    assert.equal(document.querySelectorAll('[role="img"]').length, 2);
    assert.equal(
      document.querySelector('[aria-current="page"] [role="img"]'),
      null,
    );
    await render(
      list("project-running", new Set(["general-running", "project-running"])),
    );
    assert.ok(document.querySelector('#general-running [role="img"]'));
    assert.ok(document.querySelector('#project-running [role="img"]'));
    await render(list("project-running", new Set(["general-running"])));
    assert.ok(document.querySelector('#general-running [role="img"]'));
    assert.equal(document.querySelector('#project-running [role="img"]'), null);
  });
});

test("reduced motion keeps a visible static flask and bubbles without a separate interaction or JavaScript clock", async () => {
  await withIndicator(async ({ createElement, Indicator, render }) => {
    await render(createElement(Indicator));
    const rules = [...document.styleSheets[0].cssRules];
    const reduced = rules.find(
      (rule) => rule.conditionText === "(prefers-reduced-motion: reduce)",
    );
    assert.ok(reduced, "reduced-motion rule exists");
    const bubble = [...reduced.cssRules].find(
      (rule) => rule.selectorText === ".research-flask-bubble",
    );
    assert.equal(bubble.style.animation, "none");
    assert.equal(bubble.style.transform, "none");
    assert.ok(
      Number(bubble.style.opacity) > 0,
      "the static status does not disappear",
    );
    assert.ok(document.querySelector(".research-flask-glass"));
    assert.equal(document.querySelectorAll('[role="img"]').length, 1);
  });
});
