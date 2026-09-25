import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { afterEach, mock, test } from "node:test";
import ts from "typescript";
const source = await readFile(
  new URL("../src/publicSourcesApi.ts", import.meta.url),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
  },
}).outputText;
const { publicSourcesApi } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);
globalThis.window = { setTimeout, clearTimeout };
afterEach(() => mock.restoreAll());
const settings = {
  search_public_references: false,
  enabled_sources: ["hybrid3", "nomad", "europe_pmc", "arxiv"],
  materials_project_mode: "auto",
  max_results_per_source: 5,
};
const sourceRecord = {
  id: "hybrid3",
  name: "HybriD3",
  description: "Public materials database.",
  homepage: "https://materials.hybrid3.duke.edu/",
  documentation_url: "https://materials.hybrid3.duke.edu/",
  requires_credentials: false,
  kind: "database",
  scope: "public",
};
test("public database catalog permits only approved keyless adapters", async () => {
  const fetch = mock.method(globalThis, "fetch", async () =>
    Response.json({ sources: [sourceRecord] }),
  );
  assert.deepEqual(await publicSourcesApi.catalog(), [sourceRecord]);
  for (const altered of [
    { ...sourceRecord, requires_credentials: true },
    { ...sourceRecord, id: "private_lab" },
    { ...sourceRecord, homepage: "javascript:alert(1)" },
  ]) {
    fetch.mock.mockImplementation(async () =>
      Response.json({ sources: [altered] }),
    );
    await assert.rejects(publicSourcesApi.catalog(), /unsupported response/);
  }
});
test("source choices are explicit preferences and accept no arbitrary URLs or evidence", async () => {
  const fetch = mock.method(globalThis, "fetch", async () =>
    Response.json(settings),
  );
  assert.deepEqual(await publicSourcesApi.settings(), settings);
  await publicSourcesApi.save(settings);
  assert.deepEqual(JSON.parse(fetch.mock.calls[1].arguments[1].body), settings);
  for (const altered of [
    { ...settings, enabled_sources: ["private_lab"] },
    { ...settings, enabled_sources: ["arxiv", "arxiv"] },
    { ...settings, url: "https://example.org" },
    { ...settings, max_results_per_source: 11 },
    { ...settings, max_results_per_source: 0.5 },
  ]) {
    await assert.rejects(
      publicSourcesApi.save(altered),
      /unsupported response/,
    );
  }
  assert.equal(fetch.mock.calls.length, 2);
});
test("failed source saves remain explicit and are never retried automatically", async () => {
  const fetch = mock.method(globalThis, "fetch", async () =>
    Response.json({ detail: "PRIVATE_INPUT" }, { status: 422 }),
  );
  await assert.rejects(publicSourcesApi.save(settings), (error) => {
    assert.match(error.message, /Public source request failed/);
    assert.ok(!error.message.includes("PRIVATE_INPUT"));
    return true;
  });
  assert.equal(fetch.mock.calls.length, 1);
});
test("connected APIs require verified readiness while keyless services remain selectable", async () => {
  const availability = {
    status: "ready",
    selectable: true,
    requires_credentials: true,
    verified_at: "2026-09-09T12:00:00Z",
    message: "Public API verified.",
  };
  const mp = {
    id: "materials_project",
    name: "Materials Project",
    description: "Public properties.",
    homepage: "https://materialsproject.org/",
    documentation_url: "https://docs.materialsproject.org/",
    kind: "materials_database",
    requires_credentials: true,
    availability,
  };
  let result = {
    sources: [
      {
        ...sourceRecord,
        availability: {
          status: "ready",
          selectable: true,
          requires_credentials: false,
        },
      },
    ],
    connected_sources: [mp],
  };
  mock.method(globalThis, "fetch", async () => Response.json(result));
  assert.equal(
    (await publicSourcesApi.registry()).connected_sources[0].availability
      .selectable,
    true,
  );
  result = {
    ...result,
    connected_sources: [
      {
        ...mp,
        availability: {
          ...availability,
          status: "locked",
          selectable: false,
          verified_at: null,
        },
      },
    ],
  };
  assert.equal(
    (await publicSourcesApi.registry()).connected_sources[0].availability
      .selectable,
    false,
  );
  result = {
    ...result,
    connected_sources: [
      {
        ...mp,
        availability: { ...availability, status: "locked", selectable: true },
      },
    ],
  };
  await assert.rejects(publicSourcesApi.registry(), /unsupported response/);
});
test("backend dielectric source remains in saved choices but is absent from UI catalogs", async () => {
  const expanded = {
    ...settings,
    enabled_sources: [
      ...settings.enabled_sources,
      "wikipedia",
      "openalex",
      "chemrxiv",
      "public_dielectric",
    ],
  };
  const fetch = mock.method(globalThis, "fetch", async () =>
    Response.json(expanded),
  );
  assert.deepEqual(await publicSourcesApi.save(expanded), expanded);
  assert.deepEqual(JSON.parse(fetch.mock.calls[0].arguments[1].body), expanded);
  fetch.mock.mockImplementation(async () =>
    Response.json({
      sources: expanded.enabled_sources.map((id) => ({ ...sourceRecord, id })),
    }),
  );
  const catalog = await publicSourcesApi.catalog();
  assert.equal(catalog.length, 7);
  assert.equal(
    catalog.some((item) => item.id === "public_dielectric"),
    false,
  );
  assert.equal(
    (await publicSourcesApi.registry()).sources.some(
      (item) => item.id === "public_dielectric",
    ),
    false,
  );
});
