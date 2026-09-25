import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

const initialSettings = {
  search_public_references: false,
  enabled_sources: ["arxiv"],
  materials_project_mode: "off",
  max_results_per_source: 3,
};
const sources = ["arxiv", "nomad"].map((id) => ({
  id,
  name: id === "arxiv" ? "arXiv" : "NOMAD",
  description: "Public research records.",
  homepage: `https://${id}.org/`,
  documentation_url: `https://${id}.org/api`,
  requires_credentials: false,
  kind: "references",
  scope: "public",
}));
sources.unshift({
  ...sources[0],
  id: "public_dielectric",
  name: "Public dielectric dataset",
  description: "Backend dielectric reference.",
  homepage: "https://doi.org/10.6084/m9.figshare.7108790.v2",
  documentation_url: "https://www.nature.com/articles/sdata2016134",
});
function registry(status = "ready") {
  return {
    sources,
    connected_sources: [
      {
        id: "materials_project",
        name: "Materials Project",
        description: "Public property records and crystal structures.",
        homepage: "https://next-gen.materialsproject.org/",
        documentation_url: "https://next-gen.materialsproject.org/api",
        requires_credentials: true,
        kind: "properties",
        availability: {
          requires_credentials: true,
          selectable: status === "ready",
          status,
          message:
            status === "ready"
              ? "Verified."
              : "Verify this database in Connections.",
        },
      },
    ],
  };
}

async function withPanel(t, options, check) {
  const output = await mkdtemp(join(tmpdir(), "labcat-source-dom-"));
  for (const name of ["PublicSources.tsx", "publicSourcesApi.ts"]) {
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
  const { default: PublicSources } = await import(
    pathToFileURL(join(output, "PublicSources.js")).href
  );
  let settings = { ...initialSettings, ...options.settings };
  let catalog = registry(options.status);
  const writes = [];
  let settingsReads = 0;
  t.mock.method(globalThis, "fetch", async (path, request = {}) => {
    if (path === "/api/public-sources") return Response.json(catalog);
    assert.equal(path, "/api/source-settings");
    if (request.method === "PUT") {
      settings = JSON.parse(request.body);
      writes.push(settings);
    } else settingsReads++;
    return Response.json(settings);
  });
  const root = createRoot(document.getElementById("root"));
  const render = async (props = {}) => {
    await act(async () =>
      root.render(createElement(PublicSources, { ...options.props, ...props })),
    );
  };
  const add = async (id) => {
    await act(async () => {
      const select = document.getElementById("settings-add-source");
      select.value = id;
      select.dispatchEvent(new window.Event("change", { bubbles: true }));
    });
  };
  const save = async () => {
    await act(async () =>
      document
        .querySelector("form")
        .dispatchEvent(
          new window.Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
  };
  const remove = async (id) => {
    await act(async () =>
      [
        ...document
          .querySelector(`[data-source-id="${id}"]`)
          .querySelectorAll("button"),
      ]
        .find((button) => button.textContent === "Remove database")
        .click(),
    );
  };
  try {
    await render();
    await check({
      writes,
      render,
      add,
      save,
      remove,
      act,
      createElement,
      setRegistry: (value) => {
        catalog = value;
      },
      settingsReads: () => settingsReads,
    });
  } finally {
    await act(async () => root.unmount());
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
    await rm(output, { recursive: true, force: true });
  }
}

const selectedMp = () =>
  document.querySelector('[data-source-id="materials_project"]');

test("verified Materials Project uses the shared add/remove database controls", async (t) => {
  await withPanel(t, {}, async ({ add, save, remove, writes }) => {
    assert.equal(document.getElementById("settings-mp-mode"), null);
    assert.ok(!document.body.textContent.includes("Connected property API"));
    assert.equal(selectedMp(), null);
    assert.equal(document.querySelector('input[type="password"]'), null);
    await add("materials_project");
    assert.match(selectedMp().textContent, /Verified property API/);
    assert.equal(
      document.querySelector('option[value="materials_project"]').disabled,
      true,
    );
    await save();
    assert.deepEqual(writes[0], {
      ...initialSettings,
      materials_project_mode: "api",
    });
    await remove("materials_project");
    assert.equal(selectedMp(), null);
    assert.equal(
      document.querySelector('option[value="materials_project"]').disabled,
      false,
    );
    await save();
    assert.deepEqual(writes[1], initialSettings);
    assert.equal(
      document.querySelector('button[type="submit"]').disabled,
      true,
    );
  });
});

test("unverified APIs cannot be enabled while keyless databases remain selectable", async (t) => {
  for (const status of [
    "not_configured",
    "locked",
    "verification_required",
    "error",
  ]) {
    await t.test(status, async (t) =>
      withPanel(t, { status }, async ({ add, save, writes }) => {
        assert.equal(
          document.querySelector('option[value="materials_project"]').disabled,
          true,
        );
        await add("materials_project");
        assert.equal(
          selectedMp(),
          null,
          "a dispatched change cannot bypass verification gating",
        );
        await add("nomad");
        await save();
        assert.deepEqual(writes[0], {
          ...initialSettings,
          enabled_sources: ["arxiv", "nomad"],
        });
      }),
    );
  }
});

test("previously selected API remains visible when its connection expires and can be removed", async (t) => {
  await withPanel(
    t,
    {
      settings: { materials_project_mode: "api" },
      status: "verification_required",
    },
    async ({ remove, save, writes }) => {
      assert.match(
        selectedMp().textContent,
        /Unavailable · Verification required/,
      );
      await remove("materials_project");
      await save();
      assert.deepEqual(writes[0], initialSettings);
    },
  );
});

test("legacy automatic source use matches the visible selection and saves explicit choices", async (t) => {
  for (const status of ["ready", "not_configured"]) {
    await t.test(status, async (t) =>
      withPanel(
        t,
        { settings: { materials_project_mode: "auto" }, status },
        async ({ add, save, writes }) => {
          assert.equal(Boolean(selectedMp()), status === "ready");
          assert.equal(
            writes.length,
            0,
            "reading legacy choices must not write settings",
          );
          await add("nomad");
          await save();
          assert.deepEqual(writes[0], {
            ...initialSettings,
            enabled_sources: ["arxiv", "nomad"],
            materials_project_mode: status === "ready" ? "api" : "off",
          });
        },
      ),
    );
  }
});

test("credential availability refreshes preserve unsaved database edits", async (t) => {
  await withPanel(
    t,
    { settings: { materials_project_mode: "auto" }, status: "not_configured" },
    async ({ add, render, setRegistry, settingsReads, save, writes }) => {
      await add("nomad");
      setRegistry(registry("ready"));
      await render({ refreshKey: "verified" });
      assert.equal(
        settingsReads(),
        1,
        "credential refresh does not reload preferences over unsaved edits",
      );
      assert.ok(document.querySelector('[data-source-id="nomad"]'));
      assert.ok(
        selectedMp(),
        "legacy auto reflects current verified availability",
      );
      await save();
      assert.deepEqual(writes[0], {
        ...initialSettings,
        enabled_sources: ["arxiv", "nomad"],
        materials_project_mode: "api",
      });
    },
  );
});

test("registry includes the supplied credentials card alongside keyless databases", async (t) => {
  await withPanel(
    t,
    { props: { context: "connections" } },
    async ({ render, createElement }) => {
      await render({
        context: "connections",
        materialsProjectCard: createElement(
          "article",
          {
            className: "selected-public-source",
            "data-source-id": "materials_project",
          },
          "Materials Project credential controls",
        ),
      });
      assert.equal(
        document.querySelector(".selected-public-sources").firstElementChild,
        selectedMp(),
      );
      assert.equal(
        document.querySelectorAll(".selected-public-source").length,
        3,
      );
      assert.ok(
        !document.body.textContent.includes("Public dielectric dataset"),
      );
      assert.equal(
        document.querySelector("form"),
        null,
        "injected card can own its credential form",
      );
      assert.ok(
        !/credentials are managed above|These public services need no account/.test(
          document.body.textContent,
        ),
      );
    },
  );
});

test("hidden backend source is never selectable and survives visible database edits", async (t) => {
  for (const enabled_sources of [["public_dielectric"], []]) {
    await t.test(
      enabled_sources.length ? "previously enabled" : "previously disabled",
      async (t) =>
        withPanel(
          t,
          { settings: { enabled_sources } },
          async ({ add, save, remove, writes }) => {
            assert.equal(
              document.querySelector('option[value="public_dielectric"]'),
              null,
            );
            assert.ok(
              !document.body.textContent.includes("Public dielectric dataset"),
            );
            assert.equal(
              document.querySelectorAll(".selected-public-source").length,
              0,
            );
            assert.match(
              document.querySelector(".field-help").textContent,
              /Add supported databases/,
            );
            assert.equal(
              writes.length,
              0,
              "opening the page does not alter saved backend source use",
            );
            await add("nomad");
            await save();
            assert.deepEqual(writes[0].enabled_sources, [
              ...enabled_sources,
              "nomad",
            ]);
            await remove("nomad");
            await save();
            assert.deepEqual(writes[1].enabled_sources, enabled_sources);
          },
        ),
    );
  }
});

test("historical output mode does not silently enable a connected API or network searches", async (t) => {
  await withPanel(
    t,
    { settings: { materials_project_mode: "snapshot" } },
    async ({ save, writes }) => {
      assert.equal(selectedMp(), null);
      assert.equal(
        document.querySelector('input[type="checkbox"]').checked,
        false,
      );
      assert.equal(writes.length, 0);
      await save();
      assert.deepEqual(writes, [initialSettings]);
    },
  );
});
