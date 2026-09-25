import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, before, test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

let output;
let defaultTarget = { kind: "material", id: "mp-1" };
before(async () => {
  output = await mkdtemp(join(tmpdir(), "labcat-structure-ui-"));
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
});
after(async () => {
  await rm(output, { recursive: true, force: true });
});

async function withDom(check) {
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
  const { default: StructureViewer } = await import(
    pathToFileURL(join(output, "StructureViewer.js")).href
  );
  const { ReportCard } = await import(
    pathToFileURL(join(output, "ProjectWorkspace.js")).href
  );
  const { structureApi } = await import(
    pathToFileURL(join(output, "structureApi.js")).href
  );
  const root = createRoot(document.getElementById("root"));
  const flush = async () => {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  };
  try {
    await check({
      document: dom.window.document,
      window: dom.window,
      structureApi,
      flush,
      render: async (
        reportId = "report-a",
        target = defaultTarget,
        autoLoad = false,
      ) => {
        await act(async () => {
          root.render(
            createElement(StructureViewer, {
              chatId: "chat-a",
              reportId,
              target,
              autoLoad,
            }),
          );
        });
      },
      renderCard: async (report) => {
        await act(async () => {
          root.render(
            createElement(ReportCard, {
              report,
              sources: [],
              onPin: async () => {},
            }),
          );
        });
      },
      click: async (element) => {
        assert.ok(element);
        await act(async () => {
          element.dispatchEvent(
            new dom.window.MouseEvent("click", { bubbles: true }),
          );
        });
      },
      select: async (element, value) => {
        assert.ok(element);
        await act(async () => {
          element.value = value;
          element.dispatchEvent(
            new dom.window.Event("change", { bubbles: true }),
          );
        });
      },
      message: async (
        frame,
        data,
        origin = "null",
        source = frame.contentWindow,
      ) => {
        await act(async () => {
          dom.window.dispatchEvent(
            new dom.window.MessageEvent("message", { data, origin, source }),
          );
        });
      },
    });
  } finally {
    await act(async () => {
      root.unmount();
    });
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
  }
}

// Synthetic interface fixtures only. No material property or scientific result is asserted.
const base = "/api/chats/chat-a/reports/report-a/structures";
const first = {
  material_id: "mp-1",
  formula: "Test A",
  source_name: "Materials Project",
  source_url: "https://materialsproject.org/materials/mp-1",
  status: "not_loaded",
  caveats: ["Synthetic interface fixture; no scientific evidence."],
};
const second = {
  material_id: "nomad:test_B",
  formula: "Test B",
  source_name: "NOMAD",
  source_url: "https://nomad-lab.eu/prod/v1/gui/search/entries/entry/id/test_B",
  status: "not_loaded",
  caveats: ["Synthetic interface fixture."],
};
const ready = (item, report = "report-a") => ({
  ...item,
  status: "ready",
  filename: "test-structure.cif",
  download_url: `/api/chats/chat-a/reports/${report}/structures/${encodeURIComponent(item.material_id)}/download`,
  sha256: "a".repeat(64),
  retrieved_at: "2026-09-10T00:00:00Z",
  n_sites: 1,
});
const response = (value, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const cif =
  "# Labcat derived structure file\n# Synthetic interface fixture; not scientific evidence.\ndata_synthetic_interface_fixture\n";
const button = (document, label) =>
  [...document.querySelectorAll("button")].find(
    (entry) => entry.textContent === label,
  );

function mockApi(
  t,
  { enabled = true, initial = [first, second], contentResponse, failure } = {},
) {
  defaultTarget = { kind: "material", id: initial[0]?.material_id ?? "mp-1" };
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    if (path === "/api/session")
      return response({ csrf_token: "synthetic_csrf_token_at_least_20_chars" });
    if (path.endsWith("/content"))
      return contentResponse
        ? contentResponse(path, options)
        : new Response(cif, { headers: { "Content-Type": "chemical/x-cif" } });
    if (options.method === "POST")
      return failure
        ? response({ detail: "<script>untrusted error</script>" }, failure)
        : response(
            ready(
              initial.find((item) =>
                path.endsWith(encodeURIComponent(item.material_id)),
              ),
            ),
          );
    return response({ viewer_enabled: enabled, structures: initial });
  });
  return calls;
}

test("structures load only public metadata until requested, retain exact candidate scope, and offer local CIF downloads", async (t) => {
  const calls = mockApi(t);
  await withDom(async ({ document, render, click, select }) => {
    await render();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].path, base);
    assert.equal(document.querySelector("iframe"), null);
    assert.equal(
      document.querySelector("select"),
      null,
      "there is no global candidate selector",
    );
    assert.match(
      document.querySelector(".structure-record-heading").textContent,
      /Test A/,
    );
    await click(button(document, "Retrieve and view structure"));
    assert.deepEqual(
      calls.map(({ path }) => path),
      [base, "/api/session", `${base}/mp-1`, `${base}/mp-1/content`],
    );
    assert.equal(calls[2].options.method, "POST");
    assert.equal(
      calls[2].options.headers["X-CSRF-Token"],
      "synthetic_csrf_token_at_least_20_chars",
    );
    assert.ok(
      calls.every(
        ({ options }) =>
          options.credentials === "same-origin" &&
          options.redirect === "error" &&
          options.cache === "no-store",
      ),
    );
    assert.equal(
      document.querySelector("a[download]").getAttribute("href"),
      `${base}/mp-1/download`,
    );
    assert.match(
      document.body.textContent,
      /Synthetic interface fixture; no scientific evidence/,
    );
    assert.equal(document.querySelectorAll("iframe").length, 1);
    await render("report-a", { kind: "material", id: second.material_id });
    assert.equal(
      document.querySelector("iframe"),
      null,
      "switching selection destroys the former viewer",
    );
    await click(button(document, "Retrieve and view structure"));
    assert.equal(calls.at(-1).path, `${base}/nomad%3Atest_B/content`);
    assert.equal(document.querySelectorAll("iframe").length, 1);
    assert.match(document.querySelector("iframe").title, /Test B/);
  });
});

test("disabled viewer still retrieves and downloads CIF without loading content or JSmol", async (t) => {
  const calls = mockApi(t, { enabled: false });
  await withDom(async ({ document, render, click }) => {
    await render();
    assert.match(document.body.textContent, /interactive viewer is turned off/);
    await click(button(document, "Retrieve CIF"));
    assert.ok(document.querySelector("a[download]"));
    assert.equal(document.querySelector("iframe, script"), null);
    assert.ok(!calls.some(({ path }) => path.endsWith("/content")));
    assert.equal(button(document, "View structure"), undefined);
  });
});

test("display formula labels retain source ordering in provenance without changing structure identity or CIF", async (t) => {
  const item = ready({ ...second, formula: "SiO2", source_formula: "O2Si" });
  const calls = mockApi(t, { initial: [item] });
  await withDom(async ({ document, render, click, message }) => {
    await render();
    assert.equal(document.querySelector("select"), null);
    assert.equal(
      document
        .querySelector(".structure-record-heading .material-formula")
        .getAttribute("aria-label"),
      "SiO2",
    );
    assert.equal(
      document.querySelector(".structure-record-heading sub").textContent,
      "2",
    );
    assert.match(
      document.querySelector(".structure-provenance").textContent,
      /Original source formulaO2Si/,
    );
    assert.equal(document.querySelector(".structure-provenance").open, false);
    assert.equal(
      document.querySelector("a[download]").getAttribute("href"),
      `${base}/nomad%3Atest_B/download`,
    );
    await click(button(document, "View structure"));
    const frame = document.querySelector("iframe"),
      sent = [];
    frame.contentWindow.postMessage = (payload) => sent.push(payload);
    await message(frame, { type: "labcat-jsmol-ready" });
    assert.equal(frame.title, "JSmol structure for SiO2 (nomad:test_B)");
    assert.equal(
      sent[0].cif,
      cif,
      "display ordering does not rewrite file contents",
    );
    assert.equal(calls.at(-1).path, `${base}/nomad%3Atest_B/content`);
    assert.ok(
      !calls.some(({ options }) => options.method === "POST"),
      "cached metadata needs no new retrieval",
    );
  });
});

test("structure provenance rejects malformed or oversized source formulas", async (t) => {
  await withDom(async ({ structureApi }) => {
    for (const source_formula of [{ text: "O2Si" }, "x".repeat(257)]) {
      t.mock.method(globalThis, "fetch", async () =>
        response({
          viewer_enabled: true,
          structures: [{ ...first, source_formula }],
        }),
      );
      await assert.rejects(
        structureApi.list("chat-a", "report-a", new AbortController().signal),
        /unsupported response/,
      );
    }
  });
});

test("versioned public-dataset structures retain their namespace and exact source link", async (t) => {
  const item = {
    ...first,
    material_id: "dielectric:mp-123",
    formula: "SiO2",
    source_name: "Public dielectric dataset",
    source_url: "https://doi.org/10.6084/m9.figshare.7108790.v2",
  };
  const calls = mockApi(t, { initial: [item] });
  await withDom(async ({ document, render, click, structureApi }) => {
    await render();
    await click(button(document, "Retrieve and view structure"));
    assert.equal(
      document.querySelector("a[download]").getAttribute("href"),
      `${base}/dielectric%3Amp-123/download`,
    );
    assert.equal(calls.at(-1).path, `${base}/dielectric%3Amp-123/content`);
    assert.equal(document.querySelectorAll("iframe").length, 1);
    for (const source_url of [
      "https://doi.org/10.6084/m9.figshare.7108790.v3",
      "https://doi.org/10.6084/m9.figshare.7108790.v2?redirect=other",
      "https://doi.org.evil.example/10.6084/m9.figshare.7108790.v2",
    ]) {
      t.mock.method(globalThis, "fetch", async () =>
        response({
          viewer_enabled: true,
          structures: [{ ...ready(item), source_url }],
        }),
      );
      await assert.rejects(
        structureApi.list("chat-a", "report-a", new AbortController().signal),
        /unsupported response/,
      );
    }
  });
});

test("Hybrid3 structures preserve exact system, dataset and subset identity with a matching public dataset link", async (t) => {
  const item = {
    ...first,
    material_id: "hybrid3:12:dataset34:subset56",
    formula: "Test hybrid",
    source_name: "HybriD3",
    source_url: "https://materials.hybrid3.duke.edu/materials/dataset/34",
  };
  const calls = mockApi(t, { initial: [item] });
  await withDom(async ({ document, render, click, structureApi }) => {
    await render();
    await click(button(document, "Retrieve and view structure"));
    assert.equal(
      document.querySelector("a[download]").getAttribute("href"),
      `${base}/hybrid3%3A12%3Adataset34%3Asubset56/download`,
    );
    assert.equal(
      calls.at(-1).path,
      `${base}/hybrid3%3A12%3Adataset34%3Asubset56/content`,
    );
    assert.equal(document.querySelectorAll("iframe").length, 1);
    for (const patch of [
      { material_id: "hybrid3:012:dataset34:subset56" },
      { material_id: "hybrid3:12:dataset34:subset0" },
      { material_id: "hybrid3:12:dataset34" },
      { source_url: "https://materials.hybrid3.duke.edu/materials/dataset/35" },
      {
        source_url:
          "https://materials.hybrid3.duke.edu/materials/dataset/34?redirect=other",
      },
      {
        source_url:
          "https://materials.hybrid3.duke.edu.evil.example/materials/dataset/34",
      },
    ]) {
      t.mock.method(globalThis, "fetch", async () =>
        response({
          viewer_enabled: true,
          structures: [{ ...ready(item), ...patch }],
        }),
      );
      await assert.rejects(
        structureApi.list("chat-a", "report-a", new AbortController().signal),
        /unsupported response/,
      );
    }
  });
});

test("retrieval errors do not create a viewer or invent a downloadable structure", async (t) => {
  mockApi(t, { failure: 422 });
  await withDom(async ({ document, render, click }) => {
    await render();
    await click(button(document, "Retrieve and view structure"));
    assert.match(
      document.querySelector('[role="alert"]').textContent,
      /supported, validated structure could not be obtained/,
    );
    assert.equal(document.querySelector("iframe, script, a[download]"), null);
    assert.ok(button(document, "Retrieve and view structure"));
  });
});

test("iframe handoff validates window, opaque origin and channel; rendering errors retain downloads", async (t) => {
  mockApi(t);
  await withDom(async ({ document, window, render, click, message }) => {
    await render();
    await click(button(document, "Retrieve and view structure"));
    const frame = document.querySelector("iframe"),
      sent = [];
    frame.contentWindow.postMessage = (payload, target) =>
      sent.push({ payload, target });
    assert.equal(frame.getAttribute("sandbox"), "allow-scripts");
    assert.equal(frame.getAttribute("src"), "/structure-viewer/index.html");
    assert.equal(frame.getAttribute("referrerpolicy"), "no-referrer");
    await message(frame, { type: "labcat-jsmol-ready" }, "http://localhost");
    await message(frame, { type: "labcat-jsmol-ready" }, "null", window);
    assert.equal(sent.length, 0);
    await message(frame, { type: "labcat-jsmol-ready" });
    assert.equal(sent.length, 1);
    assert.equal(sent[0].target, "*");
    assert.equal(sent[0].payload.cif, cif);
    assert.match(sent[0].payload.channel, /^[0-9a-f-]{36}$/);
    await message(frame, {
      type: "labcat-jsmol-loaded",
      channel: "stale-channel",
    });
    assert.equal(button(document, "Reset view").disabled, true);
    await message(frame, {
      type: "labcat-jsmol-loaded",
      channel: sent[0].payload.channel,
    });
    assert.equal(button(document, "Reset view").disabled, false);
    await click(button(document, "Reset view"));
    assert.deepEqual(sent.at(-1).payload, {
      type: "labcat-jsmol-command",
      channel: sent[0].payload.channel,
      command: "reset",
    });
    await message(frame, {
      type: "labcat-jsmol-error",
      channel: sent[0].payload.channel,
      detail: "<img onerror=alert(1)>",
    });
    assert.match(
      document.querySelector('[role="alert"]').textContent,
      /CIF file remains available/,
    );
    assert.ok(document.querySelector("a[download]"));
    assert.equal(document.querySelector("img"), null);
  });
});

test("changing the selected material cancels pending content and ignores its late response", async (t) => {
  let resolveContent, contentSignal;
  mockApi(t, {
    contentResponse: (_path, options) => {
      contentSignal = options.signal;
      return new Promise((resolve) => {
        resolveContent = resolve;
      });
    },
  });
  await withDom(async ({ document, render, click, select, flush }) => {
    await render();
    await click(button(document, "Retrieve and view structure"));
    assert.ok(contentSignal && !contentSignal.aborted);
    await render("report-a", { kind: "material", id: second.material_id });
    assert.equal(contentSignal.aborted, true);
    resolveContent(
      new Response(cif, { headers: { "Content-Type": "chemical/x-cif" } }),
    );
    await flush();
    assert.equal(document.querySelector("iframe"), null);
    assert.match(
      document.querySelector(".structure-record-heading").textContent,
      /Test B/,
    );
  });
});

test("switching saved reports removes the previous viewer and its file link", async (t) => {
  const calls = mockApi(t);
  await withDom(async ({ document, render, click }) => {
    await render();
    await click(button(document, "Retrieve and view structure"));
    assert.ok(document.querySelector("iframe"));
    await render("report-b");
    assert.equal(
      calls.at(-1).path,
      "/api/chats/chat-a/reports/report-b/structures",
    );
    assert.equal(document.querySelector("iframe, a[download]"), null);
  });
});

test("API rejects cross-report download URLs and active content masquerading as CIF", async (t) => {
  mockApi(t, { initial: [ready(first, "another-report")] });
  await withDom(async ({ document, render, structureApi }) => {
    await render();
    assert.match(
      document.querySelector('[role="alert"]').textContent,
      /unsupported response/,
    );
    assert.equal(document.querySelector("a[download]"), null);
    t.mock.method(
      globalThis,
      "fetch",
      async () =>
        new Response("<script>alert(1)</script>", {
          headers: { "Content-Type": "text/html" },
        }),
    );
    await assert.rejects(
      structureApi.content(
        "chat-a",
        "report-a",
        "mp-1",
        new AbortController().signal,
      ),
      /unsupported response/,
    );
  });
});

test("reports without identifiable shortlist rows do not mount a global structure panel", async (t) => {
  const calls = mockApi(t);
  await withDom(async ({ document, renderCard, click }) => {
    const report = {
      id: "report-a",
      chat_id: "chat-a",
      message_id: "message-a",
      project_id: null,
      title: "Synthetic interface report",
      stage: "test",
      pi_summary: "Summary:\n\nSynthetic interface fixture.",
      technical_audit: "Technical View:\n\nSynthetic interface fixture.",
      source_ids: [],
      created_at: "2026-09-10T00:00:00Z",
      pinned: false,
      result: { candidates: [{ material_id: "mp-1" }] },
    };
    await renderCard(report);
    assert.equal(
      calls.filter(({ path }) => path.includes("/structures")).length,
      0,
    );
    assert.equal(document.querySelector(".report-structures"), null);
    await click(button(document, "Technical View"));
    assert.equal(document.querySelector(".report-structures"), null);
    assert.equal(
      calls.filter(({ path }) => path.includes("/structures")).length,
      0,
    );
    await click(button(document, "Summary"));
    assert.equal(document.querySelector(".report-structures"), null);
  });
});

test("a shortlist row request selects its exact material and retrieves only that structure", async (t) => {
  const calls = mockApi(t);
  await withDom(async ({ document, render }) => {
    await render();
    assert.equal(calls.length, 1);
    await render(
      "report-a",
      { kind: "material", id: second.material_id },
      true,
    );
    assert.equal(document.querySelector("select"), null);
    assert.deepEqual(
      calls
        .filter(({ options }) => options.method === "POST")
        .map(({ path }) => path),
      [`${base}/nomad%3Atest_B`],
    );
    assert.equal(
      document.querySelector("a[download]").getAttribute("href"),
      `${base}/nomad%3Atest_B/download`,
    );
    assert.equal(document.querySelectorAll("iframe").length, 1);
    assert.doesNotMatch(
      document.querySelector(".structure-record-heading").textContent,
      /nomad:/,
    );
    assert.match(
      document.querySelector(".structure-provenance").textContent,
      /nomad:test_B/,
    );
  });
});

test("structure failures use fixed actionable messages and discard arbitrary server diagnostics", async (t) => {
  await withDom(async ({ structureApi }) => {
    for (const [code, expected] of [
      ["structure_access_unverified", /did not confirm open access/],
      ["structure_source_unavailable", /temporarily unavailable/],
      ["structure_busy", /already handling/],
      ["structure_missing", /no atomic-structure datasets/],
      ["structure_ambiguous", /several equally close/],
      ["structure_search_incomplete", /matching remains incomplete/],
      ["structure_invalid", /validated structure/],
      ["unknown", /validated structure/],
    ]) {
      t.mock.method(globalThis, "fetch", async (path) =>
        path === "/api/session"
          ? response({ csrf_token: "synthetic_csrf_token_at_least_20_chars" })
          : response(
              { detail: { code, message: "PRIVATE-LOOKING-DIAGNOSTIC" } },
              422,
            ),
      );
      await assert.rejects(
        structureApi.retrieve(
          "chat-a",
          "report-a",
          "mp-1",
          new AbortController().signal,
        ),
        (error) =>
          expected.test(error.message) &&
          !error.message.includes("PRIVATE-LOOKING"),
      );
    }
  });
});

test("canonical CIF provenance comments before the data block are preserved for the viewer", async (t) => {
  mockApi(t);
  await withDom(async ({ structureApi }) => {
    const content = await structureApi.content(
      "chat-a",
      "report-a",
      "mp-1",
      new AbortController().signal,
    );
    assert.equal(content, cif);
    assert.ok(content.startsWith("# Labcat derived structure file\n"));
  });
});

test("reference CIFs distinguish crystallography from the property record and keep original attachments out of the viewer", async (t) => {
  const item = {
    ...ready(first),
    material_id: "hybrid3:12:dataset34:subset56",
    formula: "Test hybrid",
    source_name: "HybriD3",
    source_url: "https://materials.hybrid3.duke.edu/materials/dataset/34",
    download_url: `${base}/hybrid3%3A12%3Adataset34%3Asubset56/download`,
    structure_match: "composition_reference",
    structure_source_url:
      "https://materials.hybrid3.duke.edu/materials/dataset/35",
    structure_differences: ["Experimental structure; calculated property."],
    source_cif: {
      filename: "test-original.cif",
      block: "TEST_ONLY",
      sha256: "b".repeat(64),
      archive_sha256: "c".repeat(64),
      download_url: `${base}/hybrid3%3A12%3Adataset34%3Asubset56/original`,
    },
  };
  const calls = mockApi(t, { initial: [item] });
  await withDom(async ({ document, render, click, message, structureApi }) => {
    await render();
    assert.match(
      document.querySelector(".structure-reference-notice").textContent,
      /Reference structure.*composition.*Experimental structure; calculated property/s,
    );
    assert.ok(
      document.querySelector(
        'a[href="https://materials.hybrid3.duke.edu/materials/dataset/35"]',
      ),
    );
    assert.equal(document.querySelectorAll("a[download]").length, 2);
    assert.equal(
      document
        .querySelector('a[download="test-original.cif"]')
        .getAttribute("href"),
      item.source_cif.download_url,
    );
    assert.match(document.body.textContent, /Displayed blockTEST_ONLY/);
    await click(button(document, "View structure"));
    const frame = document.querySelector("iframe"),
      messages = [];
    frame.contentWindow.postMessage = (value) => messages.push(value);
    await message(frame, { type: "labcat-jsmol-ready" });
    assert.equal(messages[0].cif, cif);
    assert.ok(
      !calls.some(({ path }) => path.endsWith("/original")),
      "original source file is download-only",
    );
    for (const patch of [
      { status: "not_loaded" },
      { structure_source_url: "http://127.0.0.1/private" },
      {
        structure_source_url:
          "https://materials.hybrid3.duke.edu/materials/dataset/35?next=evil",
      },
      { structure_match: "exact_phase" },
      { structure_match: "source_metadata_match" },
      {
        source_cif: {
          ...item.source_cif,
          download_url: `${base}/another-record/original`,
        },
      },
      { source_cif: { ...item.source_cif, filename: "../../outside.cif" } },
      { source_cif: { ...item.source_cif, block: "<script>" } },
      { source_cif: { ...item.source_cif, sha256: "corrupted" } },
    ]) {
      t.mock.method(globalThis, "fetch", async () =>
        response({ viewer_enabled: true, structures: [{ ...item, ...patch }] }),
      );
      await assert.rejects(
        structureApi.list("chat-a", "report-a", new AbortController().signal),
        /unsupported response/,
      );
    }
  });
});

test("historical JSON without identifiable shortlist rows does not mount a global structure panel", async (t) => {
  const calls = mockApi(t, { initial: [] });
  await withDom(async ({ document, renderCard, click }) => {
    const report = {
      id: "report-a",
      chat_id: "chat-a",
      message_id: "message-a",
      project_id: null,
      title: "Interface fixture",
      stage: "test",
      pi_summary: "Summary:\n\nFixture.",
      technical_audit: '{"fixture":"historical JSON"}',
      source_ids: [],
      created_at: "2026-09-10T00:00:00Z",
      pinned: false,
      result: {
        candidates: [],
        candidate_leads: [{ id: "lead-" + "a".repeat(24) }],
      },
    };
    await renderCard(report);
    assert.equal(document.querySelector(".report-structures"), null);
    await click(button(document, "Technical View"));
    assert.equal(document.querySelectorAll(".report-structures").length, 0);
    assert.equal(calls.filter(({ path }) => path === base).length, 0);
  });
});

test("viewer retry reuses the validated CIF and negotiates readiness with a new frame", async (t) => {
  const calls = mockApi(t);
  await withDom(async ({ document, render, click, message }) => {
    await render();
    await click(button(document, "Retrieve and view structure"));
    const oldFrame = document.querySelector("iframe"),
      sent = [];
    oldFrame.contentWindow.postMessage = (payload) => sent.push(payload);
    oldFrame.dispatchEvent(new document.defaultView.Event("load"));
    assert.equal(sent[0].type, "labcat-jsmol-hello");
    await message(oldFrame, { type: "labcat-jsmol-ready" });
    const oldChannel = sent.find(
      (payload) => payload.type === "labcat-jsmol-load",
    ).channel;
    await message(oldFrame, {
      type: "labcat-jsmol-error",
      channel: oldChannel,
    });
    const fetchCount = calls.length;
    await click(button(document, "Retry viewer"));
    const frame = document.querySelector("iframe"),
      next = [];
    assert.notEqual(frame, oldFrame);
    frame.contentWindow.postMessage = (payload) => next.push(payload);
    await message(frame, { type: "labcat-jsmol-ready" });
    assert.equal(next[0].cif, cif);
    assert.notEqual(next[0].channel, oldChannel);
    await message(frame, { type: "labcat-jsmol-loaded", channel: oldChannel });
    assert.equal(button(document, "Reset view").disabled, true);
    await message(frame, {
      type: "labcat-jsmol-loaded",
      channel: next[0].channel,
    });
    assert.equal(button(document, "Reset view").disabled, false);
    assert.equal(
      calls.length,
      fetchCount,
      "retry never repeats source retrieval or CIF download",
    );
    assert.ok(document.querySelector("a[download]"));
  });
});

const literatureLead = {
  lead_id: "lead-" + "a".repeat(24),
  name: "SiO2",
  rank: 2,
  status: "reference_lookup_available",
};
const association = {
  relation: "composition_reference",
  phase_match: "unverified",
  lead_ids: [literatureLead.lead_id],
  lead_names: [literatureLead.name],
};
const referenceRecord = {
  ...second,
  formula: "SiO2",
  literature_association: association,
};

test("reference lookup stays inside its candidate row and requires choosing among multiple records", async (t) => {
  const calls = [];
  const another = { ...referenceRecord, material_id: "nomad:test_C" };
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    if (path === "/api/session")
      return response({ csrf_token: "synthetic_csrf_token_at_least_20_chars" });
    if (path === `${base}/references/${literatureLead.lead_id}`)
      return response({
        viewer_enabled: true,
        structures: [referenceRecord, another],
        literature_candidates: [
          { ...literatureLead, status: "references_found" },
        ],
      });
    if (path.endsWith("/content"))
      return new Response(cif, {
        headers: { "Content-Type": "chemical/x-cif" },
      });
    if (options.method === "POST") return response(ready(referenceRecord));
    return response({
      viewer_enabled: true,
      structures: [],
      literature_candidates: [literatureLead],
    });
  });
  await withDom(async ({ document, render, click }) => {
    await render(
      "report-a",
      { kind: "lead", id: literatureLead.lead_id },
      true,
    );
    assert.equal(calls.length, 1);
    assert.equal(document.querySelector("select"), null);
    await click(button(document, "Find reference structures"));
    assert.equal(
      calls.at(-1).path,
      `${base}/references/${literatureLead.lead_id}`,
    );
    assert.equal(calls.at(-1).options.method, "POST");
    assert.equal(
      calls.at(-1).options.headers["X-CSRF-Token"],
      "synthetic_csrf_token_at_least_20_chars",
    );
    assert.equal(document.querySelector("iframe"), null);
    assert.equal(
      document.querySelectorAll(".structure-record-options button").length,
      2,
    );
    await click(document.querySelector(".structure-record-options button"));
    assert.match(
      document.querySelector(".structure-reference-notice").textContent,
      /Phase match unverified/,
    );
    assert.match(
      document.querySelector(".structure-reference-notice").textContent,
      /does not change the ranking/,
    );
    assert.equal(calls.at(-1).path, `${base}/nomad%3Atest_B/content`);
    assert.ok(document.querySelector("iframe"));
    assert.ok(document.querySelector("a[download]"));
    assert.ok(!calls.some(({ path }) => path.includes("test_C/")));
  });
});

test("unavailable reference search does not invent records, and unverified phase metadata cannot claim a match", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    response({
      viewer_enabled: true,
      structures: [],
      literature_candidates: [
        {
          ...literatureLead,
          status: "unsupported",
          reason: "The source name does not identify a complete composition.",
        },
      ],
    }),
  );
  await withDom(async ({ document, render, structureApi }) => {
    await render("report-a", { kind: "lead", id: literatureLead.lead_id });
    assert.equal(button(document, "Find reference structures"), undefined);
    assert.equal(document.querySelector("iframe, a[download]"), null);
    for (const patch of [
      { phase_match: "verified" },
      { lead_ids: ["arbitrary-link"] },
      { lead_names: [] },
    ]) {
      t.mock.method(globalThis, "fetch", async () =>
        response({
          viewer_enabled: true,
          structures: [
            {
              ...referenceRecord,
              literature_association: { ...association, ...patch },
            },
          ],
          literature_candidates: [literatureLead],
        }),
      );
      await assert.rejects(
        structureApi.list("chat-a", "report-a", new AbortController().signal),
        /unsupported response/,
      );
    }
  });
});

test("cached unresolved public name remains explicitly retryable after passive refresh", async (t) => {
  const calls = [];
  const unresolved = {
    ...literatureLead,
    status: "no_reference_matches",
    reason:
      "The bounded public name lookup did not establish one exact compound composition. Retry the public lookup to check again; no name or phase was guessed.",
  };
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    if (path === "/api/session")
      return response({ csrf_token: "synthetic_csrf_token_at_least_20_chars" });
    if (path === `${base}/references/${literatureLead.lead_id}`)
      return response({
        viewer_enabled: true,
        structures: [referenceRecord],
        literature_candidates: [
          { ...literatureLead, status: "references_found" },
        ],
      });
    return response({
      viewer_enabled: true,
      structures: [],
      literature_candidates: [unresolved],
    });
  });
  await withDom(async ({ document, render, click }) => {
    await render("report-a", { kind: "lead", id: literatureLead.lead_id });
    assert.ok(button(document, "Retry reference lookup"));
    assert.match(
      document.body.textContent,
      /public name lookup did not establish/,
    );
    await click(button(document, "Refresh availability"));
    assert.ok(button(document, "Retry reference lookup"));
    assert.equal(
      calls.filter(({ path }) => path.includes("/references/")).length,
      0,
    );
    await click(button(document, "Retry reference lookup"));
    const searches = calls.filter(({ path }) => path.includes("/references/"));
    assert.equal(searches.length, 1);
    assert.equal(searches[0].options.method, "POST");
    assert.equal(button(document, "Retry reference lookup"), undefined);
    assert.match(
      document.querySelector(".structure-provenance").textContent,
      /nomad:test_B/,
    );
  });
});

test("reference rows show only records explicitly associated with their saved lead ID", async (t) => {
  const otherLead = { ...literatureLead, lead_id: "lead-" + "b".repeat(24) };
  const unrelated = {
    ...referenceRecord,
    material_id: "nomad:test_C",
    literature_association: { ...association, lead_ids: [otherLead.lead_id] },
  };
  t.mock.method(globalThis, "fetch", async () =>
    response({
      viewer_enabled: true,
      structures: [first, referenceRecord, unrelated],
      literature_candidates: [literatureLead, otherLead],
    }),
  );
  await withDom(async ({ document, render }) => {
    await render("report-a", { kind: "lead", id: literatureLead.lead_id });
    assert.match(
      document.querySelector(".structure-provenance").textContent,
      /nomad:test_B/,
    );
    assert.doesNotMatch(document.body.textContent, /mp-1|test_C/);
    assert.equal(document.querySelector("select"), null);
    await render("report-a", { kind: "lead", id: "lead-" + "c".repeat(24) });
    assert.equal(
      document.querySelector(".structure-selected"),
      null,
      "an unknown ID cannot fall back to a similar composition or the first record",
    );
  });
});

test("refresh availability retains a concurrently completed structure and its viewer", async (t) => {
  let finishRefresh,
    finishRetrieval,
    listCount = 0;
  t.mock.method(globalThis, "fetch", async (path, options) => {
    if (path === "/api/session")
      return response({ csrf_token: "synthetic_csrf_token_at_least_20_chars" });
    if (path.endsWith("/content"))
      return new Response(cif, {
        headers: { "Content-Type": "chemical/x-cif" },
      });
    if (options.method === "POST")
      return new Promise((resolve) => {
        finishRetrieval = resolve;
      });
    if (++listCount > 1)
      return new Promise((resolve) => {
        finishRefresh = resolve;
      });
    return response({
      viewer_enabled: true,
      structures: [first],
      literature_candidates: [literatureLead],
    });
  });
  await withDom(async ({ document, render, click, flush }) => {
    await render();
    await click(button(document, "Retrieve and view structure"));
    await click(button(document, "Refresh availability"));
    assert.ok(finishRefresh && finishRetrieval);
    finishRetrieval(response(ready(first)));
    await flush();
    assert.ok(
      document.querySelector("a[download]"),
      "refresh must not cancel the active record retrieval",
    );
    const frame = document.querySelector("iframe");
    assert.ok(frame);
    finishRefresh(
      response({
        viewer_enabled: true,
        structures: [first],
        literature_candidates: [literatureLead],
      }),
    );
    await flush();
    assert.ok(document.querySelector("a[download]"));
    assert.equal(
      document.querySelector("iframe"),
      frame,
      "refresh preserves the current ready record and viewer",
    );
  });
});

test("closing or changing a candidate cancels its reference lookup and ignores late results", async (t) => {
  let finishLookup, lookupSignal;
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push(path);
    if (path === "/api/session")
      return response({ csrf_token: "synthetic_csrf_token_at_least_20_chars" });
    if (path.includes("/references/")) {
      lookupSignal = options.signal;
      return new Promise((resolve) => {
        finishLookup = resolve;
      });
    }
    return response({
      viewer_enabled: true,
      structures: [first],
      literature_candidates: [literatureLead],
    });
  });
  await withDom(async ({ document, render, click, flush }) => {
    await render("report-a", { kind: "lead", id: literatureLead.lead_id });
    await click(button(document, "Find reference structures"));
    assert.ok(finishLookup);
    await render("report-a", { kind: "material", id: first.material_id });
    assert.equal(lookupSignal.aborted, true);
    finishLookup(
      response({
        viewer_enabled: true,
        structures: [referenceRecord],
        literature_candidates: [literatureLead],
      }),
    );
    await flush();
    assert.match(
      document.querySelector(".structure-record-heading").textContent,
      /Test A/,
    );
    assert.equal(document.querySelector(".structure-reference-notice"), null);
    assert.ok(!calls.some((path) => path.endsWith("/content")));
  });
});

const compositeLead = {
  ...literatureLead,
  name: "CuInS2/ZnS",
  status: "references_found",
  components: [
    {
      component_id: "component-" + "1".repeat(24),
      formula: "CuInS2",
      label: "Component 1",
      status: "references_found",
    },
    {
      component_id: "component-" + "2".repeat(24),
      formula: "ZnS",
      label: "Component 2",
      status: "reference_lookup_available",
    },
  ],
};
const componentRecord = (index, record = first) => ({
  ...record,
  formula: compositeLead.components[index].formula,
  literature_association: {
    ...association,
    relation: "component_reference",
    lead_names: [compositeLead.name],
    components: [
      {
        lead_id: compositeLead.lead_id,
        ...Object.fromEntries(
          Object.entries(compositeLead.components[index]).filter(
            ([key]) => key !== "status",
          ),
        ),
      },
    ],
  },
});

test("component lookup remains available beside a found reference and each selected component uses its own CIF", async (t) => {
  const core = componentRecord(0),
    shell = componentRecord(1, second),
    calls = [];
  const completed = {
    ...compositeLead,
    components: compositeLead.components.map((component) => ({
      ...component,
      status: "references_found",
    })),
  };
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    if (path === "/api/session")
      return response({ csrf_token: "synthetic_csrf_token_at_least_20_chars" });
    if (path.includes("/references/"))
      return response({
        viewer_enabled: true,
        structures: [core, shell],
        literature_candidates: [completed],
      });
    if (path.endsWith("/content"))
      return new Response(cif, {
        headers: { "Content-Type": "chemical/x-cif" },
      });
    if (options.method === "POST")
      return response(ready(path.endsWith("mp-1") ? core : shell));
    return response({
      viewer_enabled: true,
      structures: [core],
      literature_candidates: [compositeLead],
    });
  });
  await withDom(async ({ document, render, click }) => {
    await render("report-a", { kind: "lead", id: compositeLead.lead_id }, true);
    assert.match(
      document.querySelector(".structure-components").textContent,
      /Component 1 · CuInS2Reference records found/,
    );
    assert.match(
      document.querySelector(".structure-components").textContent,
      /Component 2 · ZnSNot searched yet/,
    );
    assert.match(
      document.querySelector(".structure-reference-notice").textContent,
      /independent bulk reference for Component 1 \(CuInS2\)/,
    );
    assert.match(
      document.querySelector(".structure-reference-notice").textContent,
      /does not represent the assembled interface/,
    );
    const retainedFrame = document.querySelector("iframe");
    assert.ok(retainedFrame);
    await click(button(document, "Find reference structures"));
    assert.equal(button(document, "Find reference structures"), undefined);
    const choices = [
      ...document.querySelectorAll(".structure-record-options button"),
    ];
    assert.equal(choices.length, 2);
    assert.equal(
      document.querySelector("iframe"),
      retainedFrame,
      "finding a second component preserves the current loaded viewer",
    );
    assert.match(
      choices[0].textContent,
      /Component 1 · CuInS2Materials Project/,
    );
    assert.match(choices[1].textContent, /Component 2 · ZnSNOMAD/);
    await click(choices[1]);
    assert.equal(calls.at(-1).path, `${base}/nomad%3Atest_B/content`);
    assert.equal(
      document.querySelector("a[download]").getAttribute("href"),
      `${base}/nomad%3Atest_B/download`,
    );
    assert.match(
      document.querySelector("iframe").title,
      /ZnS \(nomad:test_B\)/,
    );
    assert.notEqual(document.querySelector("iframe"), retainedFrame);
    assert.match(
      document.querySelector(".structure-reference-notice").textContent,
      /Component 2 \(ZnS\)/,
    );
    assert.doesNotMatch(
      document.querySelector(".structure-reference-notice").textContent,
      /Component 1/,
    );
    assert.equal(
      calls.filter(({ path }) => path.includes("/references/")).length,
      1,
    );
  });
});

test("whole-candidate records remain selectable while failed and unsupported components stay explicit", async (t) => {
  const lead = {
    ...compositeLead,
    status: "unsupported",
    components: [
      {
        ...compositeLead.components[0],
        status: "reference_lookup_failed",
        reason: "Public source unavailable.",
      },
      {
        ...compositeLead.components[1],
        status: "unsupported",
        reason: "No complete composition was resolved.",
      },
    ],
  };
  const whole = {
    ...referenceRecord,
    formula: "CuInS2/ZnS",
    literature_association: { ...association, lead_names: [lead.name] },
  };
  t.mock.method(globalThis, "fetch", async () =>
    response({
      viewer_enabled: true,
      structures: [whole],
      literature_candidates: [lead],
    }),
  );
  await withDom(async ({ document, render }) => {
    await render("report-a", { kind: "lead", id: lead.lead_id });
    assert.ok(
      button(document, "Retry reference lookup"),
      "a failed component is retryable even with a whole-candidate record",
    );
    assert.match(
      document.querySelector(".structure-components").textContent,
      /Lookup incomplete — retry availablePublic source unavailable/,
    );
    assert.match(
      document.querySelector(".structure-components").textContent,
      /Composition not resolvedNo complete composition was resolved/,
    );
    assert.match(
      document.querySelector(".structure-provenance").textContent,
      /nomad:test_B/,
    );
    assert.equal(document.querySelector("iframe"), null);
  });
});

test("component metadata rejects duplicate, foreign or mismatched identities and requires explicit component association", async (t) => {
  const valid = {
    viewer_enabled: true,
    structures: [componentRecord(0)],
    literature_candidates: [compositeLead],
  };
  await withDom(async ({ structureApi }) => {
    t.mock.method(globalThis, "fetch", async () => response(valid));
    const parsed = await structureApi.list(
      "chat-a",
      "report-a",
      new AbortController().signal,
    );
    assert.equal(
      parsed.structures[0].literature_association.components[0].formula,
      "CuInS2",
    );
    const corruptions = [
      (data) => {
        data.structures[0].literature_association.components[0].lead_id =
          "lead-" + "b".repeat(24);
      },
      (data) => {
        data.structures[0].literature_association.components[0].formula = "ZnS";
      },
      (data) => {
        data.structures[0].literature_association.components[0].label = "Core";
      },
      (data) => {
        data.structures[0].literature_association.components = [];
      },
      (data) => {
        delete data.structures[0].literature_association.components;
      },
      (data) => {
        data.structures[0].literature_association.components.push(
          data.structures[0].literature_association.components[0],
        );
      },
      (data) => {
        data.literature_candidates[0].components[0].component_id =
          "https://untrusted.example/";
      },
      (data) => {
        data.literature_candidates[0].components[0].status = "verified";
      },
      (data) => {
        data.literature_candidates[0].components.push(
          data.literature_candidates[0].components[0],
        );
      },
      (data) => {
        data.literature_candidates[0].components = [];
      },
    ];
    for (const corrupt of corruptions) {
      const data = structuredClone(valid);
      corrupt(data);
      t.mock.method(globalThis, "fetch", async () => response(data));
      await assert.rejects(
        structureApi.list("chat-a", "report-a", new AbortController().signal),
        /unsupported response/,
      );
    }
  });
});

test("shared component records retain parent-specific labels without leaking another candidate into the row", async (t) => {
  const otherLead = {
    ...compositeLead,
    lead_id: "lead-" + "b".repeat(24),
    name: "ZnS/CuInS2",
    components: [
      {
        ...compositeLead.components[0],
        component_id: "component-" + "3".repeat(24),
        label: "Component 2",
      },
    ],
  };
  const shared = componentRecord(0);
  shared.literature_association.lead_ids.push(otherLead.lead_id);
  shared.literature_association.lead_names.push(otherLead.name);
  shared.literature_association.components.push({
    lead_id: otherLead.lead_id,
    ...Object.fromEntries(
      Object.entries(otherLead.components[0]).filter(
        ([key]) => key !== "status",
      ),
    ),
  });
  t.mock.method(globalThis, "fetch", async () =>
    response({
      viewer_enabled: true,
      structures: [shared],
      literature_candidates: [compositeLead, otherLead],
    }),
  );
  await withDom(async ({ document, render }) => {
    await render("report-a", { kind: "lead", id: compositeLead.lead_id });
    assert.match(
      document.querySelector(".structure-reference-notice").textContent,
      /Component 1 \(CuInS2\)/,
    );
    assert.doesNotMatch(
      document.querySelector(".structure-reference-notice").textContent,
      /Component 2/,
    );
    await render("report-a", { kind: "lead", id: otherLead.lead_id });
    assert.match(
      document.querySelector(".structure-reference-notice").textContent,
      /Component 2 \(CuInS2\)/,
    );
    assert.doesNotMatch(
      document.querySelector(".structure-reference-notice").textContent,
      /Component 1/,
    );
  });
});
