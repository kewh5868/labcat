import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { afterEach, mock, test } from "node:test";
import ts from "typescript";
const compile = async (name) =>
  ts.transpileModule(
    await readFile(new URL(`../src/${name}.ts`, import.meta.url), "utf8"),
    {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.ES2022,
      },
    },
  ).outputText;
const workspaceURL = `data:text/javascript;base64,${Buffer.from(await compile("workspaceApi")).toString("base64")}`;
const { defaultSettings, validatePresentation } = await import(workspaceURL);
const previewCode = (await compile("reportFormatApi")).replace(
  /(["'])\.\/workspaceApi\1/g,
  JSON.stringify(workspaceURL),
);
const { reportFormatApi } = await import(
  `data:text/javascript;base64,${Buffer.from(previewCode).toString("base64")}`
);
globalThis.window = { setTimeout, clearTimeout };
afterEach(() => mock.restoreAll());
const token = "FIXTURE-PREVIEW-CSRF-TOKEN";
const presentation = defaultSettings.presentation;

test("preview requests preserve exact preferences and require fresh CSRF without starting research", async () => {
  const response = {
    render_url: `/api/report-preview/render/${"a".repeat(32)}`,
    label: "Template preview — no research performed",
    html: "<p>[Material]</p>",
    text: "[Material]",
    json: '{"template":"[Material]"}',
    presentation,
    layout_note: "Representative Word layout; pagination may vary.",
    download_endpoint: "/api/report-preview/download",
  };
  const fetch = mock.method(globalThis, "fetch", async (path) =>
    Response.json(path === "/api/session" ? { csrf_token: token } : response),
  );
  assert.deepEqual(
    await reportFormatApi.preview(presentation, "both"),
    response,
  );
  assert.deepEqual(
    fetch.mock.calls.map((call) => call.arguments[0]),
    ["/api/session", "/api/report-preview"],
  );
  assert.equal(fetch.mock.calls[1].arguments[1].headers["X-CSRF-Token"], token);
  assert.deepEqual(JSON.parse(fetch.mock.calls[1].arguments[1].body), {
    presentation,
    views: "both",
  });
  for (const render_url of [
    "https://example.org/frame",
    "/api/connections",
    "/api/report-preview/render/not-a-ticket",
  ]) {
    fetch.mock.mockImplementation(async (path) =>
      Response.json(
        path === "/api/session"
          ? { csrf_token: token }
          : { ...response, render_url },
      ),
    );
    await assert.rejects(
      reportFormatApi.preview(presentation, "pi"),
      /could not be prepared/,
    );
  }
  const beforeInvalid = fetch.mock.calls.length;
  fetch.mock.mockImplementation(async () =>
    Response.json({ csrf_token: "short" }),
  );
  await assert.rejects(
    reportFormatApi.preview(presentation, "pi"),
    /could not be prepared/,
  );
  assert.equal(
    fetch.mock.calls.length,
    beforeInvalid + 1,
    "no POST follows an invalid session",
  );
});

test("template download tickets allow only matching same-origin attachment routes", async () => {
  const good = {
    url: `/api/report-preview/download/${"a".repeat(32)}?format=pdf`,
    filename: "labcat-template-pi.pdf",
  };
  let result = good;
  const fetch = mock.method(globalThis, "fetch", async (path) =>
    Response.json(path === "/api/session" ? { csrf_token: token } : result),
  );
  assert.deepEqual(
    await reportFormatApi.downloadLink(presentation, "pi", "pdf"),
    good,
  );
  for (const altered of [
    { ...good, url: "https://example.org/download" },
    { ...good, url: good.url.replace("pdf", "docx") },
    { ...good, filename: "../../secret.pdf" },
    { ...good, url: "/api/connections" },
  ]) {
    result = altered;
    await assert.rejects(
      reportFormatApi.downloadLink(presentation, "pi", "pdf"),
      /could not be prepared/,
    );
  }
  assert.equal(
    fetch.mock.calls.filter((call) =>
      call.arguments[0].endsWith("/download-link"),
    ).length,
    5,
  );
});

test("document layout permits fixed appearance choices and remains backward compatible", () => {
  validatePresentation(presentation);
  const { layout, ...legacy } = presentation;
  validatePresentation(legacy);
  for (const value of [
    { ...layout, font_family: "<script>" },
    { ...layout, font_size: 96 },
    { ...layout, text_width: 0 },
    { ...layout, accent: "url(file:///secret)" },
    { ...layout, json_indent: 8 },
    { ...layout, extra: true },
  ])
    assert.throws(
      () => validatePresentation({ ...presentation, layout: value }),
      /unsupported response/,
    );
});
