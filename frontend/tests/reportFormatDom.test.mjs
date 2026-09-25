import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

async function environment() {
  const output = await mkdtemp(join(tmpdir(), "labcat-report-format-"));
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
  const dom = new JSDOM('<div id="root"></div>', {
    url: "http://localhost/?edition=developer",
  });
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
  const react = await import("react");
  const { createRoot } = await import("react-dom/client");
  const root = createRoot(document.getElementById("root"));
  return {
    ...react,
    root,
    dom,
    module: (name) => import(pathToFileURL(join(output, `${name}.js`)).href),
    async close() {
      await react.act(async () => root.unmount());
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

test("report format previews and saves appearance without research, preserving ranking and sandboxing documents", async (t) => {
  const env = await environment();
  const { root, createElement, act, dom } = env;
  const { default: ReportFormat } = await env.module("ReportFormat");
  const { defaultSettings, workspaceApi } = await env.module("workspaceApi");
  const { reportFormatApi } = await env.module("reportFormatApi");
  const calls = [],
    saves = [],
    downloads = [],
    clicked = [];
  t.mock.method(reportFormatApi, "preview", async (presentation, views) => {
    calls.push({ presentation, views });
    return {
      render_url: `/api/report-preview/render/${"a".repeat(32)}`,
      label: "Template preview — no research performed",
      presentation,
      text: "Summary: [material] <script>literal</script>",
      json: '{"template":"[material]"}',
      html: "<p>[material]</p>",
      documents: {
        pi_summary: "Summary:\n\n[Report conclusion placeholder]",
        technical_audit: "Technical View:\n\n[Property comparison placeholder]",
      },
      layout_note: "Representative Word layout; pagination may vary.",
    };
  });
  t.mock.method(
    reportFormatApi,
    "download",
    async () => new Blob(["%PDF-fixture"], { type: "application/pdf" }),
  );
  t.mock.method(reportFormatApi, "downloadLink", async (...args) => {
    downloads.push(args);
    return {
      url: `/api/report-preview/download/${"a".repeat(32)}?format=docx`,
      filename: "labcat-template-pi.docx",
    };
  });
  t.mock.method(workspaceApi, "saveSettings", async (value) => {
    saves.push(value);
    return value;
  });
  t.mock.method(dom.window.HTMLAnchorElement.prototype, "click", function () {
    clicked.push({ href: this.getAttribute("href"), download: this.download });
  });
  t.mock.method(globalThis, "fetch", async () =>
    assert.fail(
      "Format controls do not run research or other network requests",
    ),
  );
  const change = async (element, value) =>
    act(async () => {
      Object.getOwnPropertyDescriptor(
        dom.window.HTMLSelectElement.prototype,
        "value",
      ).set.call(element, value);
      element.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
  const settle = () =>
    act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 220));
    });
  try {
    await act(async () =>
      root.render(
        createElement(ReportFormat, { initial: defaultSettings, onSaved() {} }),
      ),
    );
    await change(
      document.querySelector('[aria-label="Preview format"]'),
      "text",
    );
    await settle();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].views, "pi");
    assert.equal(document.querySelector("script"), null);
    assert.match(
      document.querySelector("pre").textContent,
      /<script>literal<\/script>/,
    );
    assert.equal(document.querySelectorAll("textarea").length, 0);
    await change(
      document.querySelector('[aria-label="Preview report view"]'),
      "audit",
    );
    await settle();
    assert.equal(calls.at(-1).views, "audit");
    await change(
      document.querySelector('[aria-label="Preview format"]'),
      "json",
    );
    assert.match(document.querySelector("pre").textContent, /"template"/);
    await change(
      document.querySelector('[aria-label="Preview format"]'),
      "docx",
    );
    const iframe = document.querySelector("iframe");
    assert.equal(iframe.getAttribute("sandbox"), "allow-same-origin");
    assert.equal(iframe.getAttribute("referrerpolicy"), "no-referrer");
    assert.match(
      iframe.getAttribute("src"),
      /^\/api\/report-preview\/render\/[a-f0-9]{32}$/,
    );
    assert.equal(iframe.srcdoc, "");
    assert.match(iframe.title, /Technical View/);
    await change(document.getElementById("report-font"), "serif");
    await change(document.getElementById("report-accent"), "teal");
    await change(document.getElementById("report-page-size"), "a4");
    await settle();
    await change(
      document.querySelector('[aria-label="Preview format"]'),
      "screen",
    );
    await settle();
    assert.ok(document.querySelector(".report-screen-previews"));
    assert.match(
      document.querySelector(".report-screen-previews").textContent,
      /Property comparison placeholder/,
    );
    assert.equal(document.querySelector("iframe"), null);
    await change(
      document.querySelector('[aria-label="Preview format"]'),
      "docx",
    );
    await settle();
    await act(async () =>
      document
        .querySelector("form")
        .dispatchEvent(
          new dom.window.Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
    assert.equal(saves.length, 1);
    assert.equal(saves[0].presentation.layout.font_family, "serif");
    assert.equal(saves[0].presentation.layout.accent, "teal");
    assert.deepEqual(saves[0].ranking, defaultSettings.ranking);
    await settle();
    await act(async () =>
      [...document.querySelectorAll("button")]
        .find((button) => button.textContent === "Download Word template")
        .click(),
    );
    assert.equal(downloads.length, 1);
    assert.equal(downloads[0][1], "audit");
    assert.equal(downloads[0][2], "docx");
    assert.match(
      clicked[0].href,
      /^\/api\/report-preview\/download\/[a-f0-9]{32}\?format=docx$/,
    );
  } finally {
    await env.close();
  }
});

test("server edition alone enables Developer Settings, below Connections, with no user-edition developer request", async (t) => {
  const env = await environment();
  const { root, createElement, act } = env;
  const { default: App } = await env.module("App");
  const { defaultSettings } = await env.module("workspaceApi");
  let runtime = { edition: "user", developer_settings_available: false };
  const requests = [];
  const profile = {
    provider: "none",
    model: "",
    ollama_url: "http://localhost:11434",
    aws_profile: "",
    aws_region: "",
    allow_paid_inference: false,
  };
  window.localStorage.setItem("edition", "developer");
  t.mock.method(globalThis, "fetch", async (path) => {
    requests.push(path);
    if (path === "/api/runtime") return Response.json(runtime);
    if (path === "/api/projects") return Response.json({ projects: [] });
    if (path === "/api/chats") return Response.json({ chats: [] });
    if (path === "/api/settings") return Response.json(defaultSettings);
    if (path === "/api/connections")
      return Response.json({
        configured: true,
        using_local_defaults: true,
        profile,
        credentials: {
          materials_project: "missing",
          openai: "missing",
          anthropic: "missing",
          kimi: "missing",
          gemini: "missing",
          deepseek: "missing",
          xai: "missing",
          openrouter: "missing",
        },
        vault: {
          available: false,
          locked: false,
          exists: false,
          can_create: true,
          key_source: "unavailable",
        },
        warnings: [],
        accounts: [],
        active_account_id: null,
      });
    if (path === "/api/connections/setup")
      return Response.json({
        version: 1,
        required: true,
        completed: true,
        current_step: "review",
        can_research: true,
        model: {
          status: "ready",
          provider: "openai",
          model: "fixture",
          account_id: "fixture",
          message: "Fixture verification.",
          checked_at: "2026-09-09T12:00:00Z",
        },
        optional: {
          compute: "local",
          aws_required: false,
          data_apis_required: false,
        },
      });
    if (path === "/api/ranking-profiles")
      return Response.json({
        active_profile_id: null,
        profiles: [],
        catalog: { attributes: [], applications: [], material_classes: [] },
      });
    if (path === "/api/developer-settings")
      return Response.json({}, { status: 404 });
    assert.fail(`unexpected request ${path}`);
  });
  try {
    await act(async () => root.render(createElement(App, { key: "user" })));
    assert.deepEqual(
      [...document.querySelectorAll(".sidebar-bottom-nav button")].map(
        (button) => button.textContent.slice(1),
      ),
      ["Chat", "Report Format", "Search Criterion", "Connections"],
    );
    assert.equal(requests.includes("/api/developer-settings"), false);
    runtime = { edition: "user", developer_settings_available: true };
    await act(async () => root.render(createElement(App, { key: "invalid" })));
    assert.ok(
      !document
        .querySelector(".sidebar-bottom-nav")
        .textContent.includes("Developer Settings"),
    );
    runtime = { edition: "developer", developer_settings_available: true };
    await act(async () =>
      root.render(createElement(App, { key: "developer" })),
    );
    const buttons = [
      ...document.querySelectorAll(".sidebar-bottom-nav button"),
    ];
    assert.match(buttons.at(-1).textContent, /Developer Settings/);
    assert.match(buttons.at(-2).textContent, /Connections/);
    assert.equal(
      requests.includes("/api/developer-settings"),
      false,
      "developer controls are fetched only when opened",
    );
    await act(async () => buttons.at(-1).click());
    assert.equal(
      requests.filter((path) => path === "/api/developer-settings").length,
      1,
    );
    assert.equal(document.querySelector("textarea"), null);
  } finally {
    await env.close();
  }
});
