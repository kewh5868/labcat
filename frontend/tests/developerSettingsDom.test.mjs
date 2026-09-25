import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

async function environment() {
  const output = await mkdtemp(join(tmpdir(), "labcat-developer-controls-"));
  const code = ts
    .transpileModule(
      await readFile(
        new URL("../src/DeveloperSettings.tsx", import.meta.url),
        "utf8",
      ),
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
      (_match, _quote, specifier) => `from '${import.meta.resolve(specifier)}'`,
    );
  await writeFile(join(output, "DeveloperSettings.mjs"), code);
  const dom = new JSDOM('<div id="root"></div>', {
    url: "http://127.0.0.1:8123/",
  });
  const keys = [
    "window",
    "document",
    "HTMLElement",
    "Node",
    "navigator",
    "IS_REACT_ACT_ENVIRONMENT",
  ];
  const previous = Object.fromEntries(
    keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]),
  );
  for (const key of keys)
    Object.defineProperty(globalThis, key, {
      value: key === "IS_REACT_ACT_ENVIRONMENT" ? true : dom.window[key],
      writable: true,
      configurable: true,
    });
  const react = await import("react");
  const { createRoot } = await import("react-dom/client");
  const root = createRoot(document.getElementById("root"));
  const { default: DeveloperSettings } = await import(
    pathToFileURL(join(output, "DeveloperSettings.mjs")).href
  );
  return {
    ...react,
    root,
    dom,
    DeveloperSettings,
    async close() {
      await react.act(async () => root.unmount());
      dom.window.close();
      for (const key of keys) {
        if (previous[key])
          Object.defineProperty(globalThis, key, previous[key]);
        else delete globalThis[key];
      }
      await rm(output, { recursive: true, force: true });
    },
  };
}

const defaults = {
  reference_search: true,
  literature_followup: true,
  allow_preprints: true,
  include_history: true,
  viewer_enabled: true,
  max_reference_results: 10,
  max_attribute_queries: 3,
  max_article_downloads: 6,
  literature_timeout_seconds: 15,
  max_agent_tool_calls: 8,
  default_model_account_id: null,
};
const status = (settings) => ({
  settings,
  defaults,
  limits: {
    max_reference_results: [1, 10],
    max_attribute_queries: [1, 3],
    max_article_downloads: [1, 6],
    literature_timeout_seconds: [3, 15],
    max_agent_tool_calls: [2, 8],
  },
  immutable_boundaries: ["Fixture immutable boundary"],
  model_accounts: [],
});
const viewerInput = () =>
  [...document.querySelectorAll('input[type="checkbox"]')].find((input) =>
    input
      .closest("label")
      .textContent.includes("Enable interactive structure viewer"),
  );

test("developer viewer switch persists exact boolean without changing installed research controls", async (t) => {
  const env = await environment();
  const { root, createElement, act, dom, DeveloperSettings } = env;
  let saved = {
    ...defaults,
    reference_search: false,
    max_attribute_queries: 1,
    max_article_downloads: 2,
  };
  const original = { ...saved };
  const writes = [];
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    if (url === "/api/session")
      return Response.json({ csrf_token: "fixture-session-token" });
    assert.equal(url, "/api/developer-settings");
    if (options.method === "PUT") {
      assert.equal(options.headers["X-CSRF-Token"], "fixture-session-token");
      assert.equal(options.credentials, "same-origin");
      assert.equal(options.redirect, "error");
      saved = JSON.parse(options.body);
      writes.push(saved);
    }
    return Response.json(status(saved));
  });
  try {
    await act(async () => root.render(createElement(DeveloperSettings)));
    assert.equal(viewerInput().checked, true);
    assert.match(
      viewerInput().closest("label").textContent,
      /downloads remain available/,
    );
    assert.equal(document.querySelector("iframe"), null);
    await act(async () => viewerInput().click());
    await act(async () =>
      document
        .querySelector("form")
        .dispatchEvent(
          new dom.window.Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
    assert.deepEqual(writes, [{ ...original, viewer_enabled: false }]);
    assert.match(
      document.querySelector(".settings-saved").textContent,
      /controls saved/,
    );
    await act(async () =>
      root.render(createElement(DeveloperSettings, { key: "reopen" })),
    );
    assert.equal(viewerInput().checked, false);
    assert.equal(document.querySelector("iframe"), null);
    await act(async () =>
      [...document.querySelectorAll("button")]
        .find((button) => button.textContent === "Reset form to defaults")
        .click(),
    );
    assert.equal(viewerInput().checked, true);
    assert.equal(
      writes.length,
      1,
      "reset edits only the form until explicitly saved",
    );
  } finally {
    await env.close();
  }
});

test("failed viewer setting save retains editable draft and reports failure without a success message", async (t) => {
  const env = await environment();
  const { root, createElement, act, dom, DeveloperSettings } = env;
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    if (url === "/api/session")
      return Response.json({ csrf_token: "fixture-session-token" });
    assert.equal(url, "/api/developer-settings");
    return options.method === "PUT"
      ? Response.json({}, { status: 503 })
      : Response.json(status(defaults));
  });
  try {
    await act(async () => root.render(createElement(DeveloperSettings)));
    await act(async () => viewerInput().click());
    await act(async () =>
      document
        .querySelector("form")
        .dispatchEvent(
          new dom.window.Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
    assert.equal(viewerInput().checked, false);
    assert.equal(viewerInput().disabled, false);
    assert.match(
      document.querySelector('[role="alert"]').textContent,
      /could not be loaded or saved/,
    );
    assert.equal(document.querySelector(".settings-saved"), null);
  } finally {
    await env.close();
  }
});

test("non-boolean viewer availability is rejected instead of creating an enabled control", async (t) => {
  const env = await environment();
  const { root, createElement, act, DeveloperSettings } = env;
  t.mock.method(globalThis, "fetch", async () =>
    Response.json(status({ ...defaults, viewer_enabled: "false" })),
  );
  try {
    await act(async () => root.render(createElement(DeveloperSettings)));
    assert.equal(document.querySelector("form"), null);
    assert.equal(document.querySelector("iframe"), null);
    assert.match(
      document.querySelector('[role="alert"]').textContent,
      /settings are incomplete/,
    );
  } finally {
    await env.close();
  }
});
