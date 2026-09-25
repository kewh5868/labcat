import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

async function compileRankingEditor() {
  const output = await mkdtemp(join(tmpdir(), "labcat-ranking-dom-"));
  for (const name of [
    "RankingProfiles.tsx",
    "rankingProfilesApi.ts",
    "RankingProfileHelp.tsx",
  ]) {
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

// These are form preferences and API fixtures, not scientific observations.
function fixture() {
  const at = "2026-09-09T12:00:00Z";
  const profile = (id, name, material_class, application, importance) => ({
    id,
    name,
    material_class,
    application,
    importance,
    normalized_weights: Object.fromEntries(
      Object.keys(importance).map((key) => [key, 1]),
    ),
    preset: true,
    created_at: at,
    updated_at: at,
  });
  return {
    catalog: {
      attributes: [
        {
          id: "band_gap",
          label: "Band gap",
          category: "Electronic properties",
          description: "Test ranking preference.",
          source_field: "band_gap",
          supported: true,
          availability_note: "Evidence required.",
        },
        {
          id: "conductivity",
          label: "Conductivity",
          category: "Electronic properties",
          description: "Test ranking preference.",
          source_field: "test_source_field",
          supported: false,
          availability_note: "Not scored by this fixture.",
        },
        {
          id: "bulk_modulus",
          label: "Bulk modulus",
          category: "Mechanical properties",
          description: "Test ranking preference.",
          source_field: null,
          supported: false,
          availability_note: "Not scored by this fixture.",
        },
      ],
      material_classes: [
        { id: "oxide", label: "Oxides", scope: "Test context" },
        { id: "ceramic", label: "Ceramics", scope: "Test context" },
      ],
      applications: [
        {
          id: "dielectric",
          label: "Dielectric screening",
          scope: "Test context",
        },
        { id: "wide_gap", label: "Wide gap screening", scope: "Test context" },
        {
          id: "mechanical",
          label: "Mechanical screening",
          scope: "Test context",
        },
      ],
    },
    profiles: [
      {
        ...profile("preset-oxide", "Oxide priorities", "oxide", "dielectric", {
          band_gap: 0.8,
        }),
        minimum_band_gap_ev: 2,
      },
      {
        ...profile(
          "preset-wide-gap",
          "Wide gap priorities",
          "oxide",
          "wide_gap",
          { band_gap: 0.9 },
        ),
        target_band_gap_ev: 4.2,
        band_gap_tolerance_ev: 0.2,
      },
      profile("preset-ceramic", "Ceramic priorities", "ceramic", "mechanical", {
        bulk_modulus: 0.7,
      }),
    ],
    active_profile_id: "preset-oxide",
  };
}

test("ranking profiles support new drafts, custom context, updates and explicit activation across reloads", async (t) => {
  const output = await compileRankingEditor();
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
  const { default: RankingProfiles } = await import(
    pathToFileURL(join(output, "RankingProfiles.js")).href
  );
  const data = fixture();
  const mutations = [];
  let nextId = 1;
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    const method = options.method ?? "GET";
    if (method === "GET" && path === "/api/ranking-profiles")
      return Response.json(data);
    const body = JSON.parse(options.body);
    mutations.push({ path, method, body });
    const activateId = /^\/api\/ranking-profiles\/([^/]+)\/activate$/.exec(
      path,
    )?.[1];
    if (method === "POST" && activateId) {
      const profile = data.profiles.find((item) => item.id === activateId);
      assert.ok(profile, "only a saved ranking profile can be activated");
      data.active_profile_id = profile.id;
      return Response.json({ active_profile_id: profile.id, profile });
    }
    const existingId = /^\/api\/ranking-profiles\/([^/]+)$/.exec(path)?.[1];
    assert.ok(
      (method === "POST" && path === "/api/ranking-profiles") ||
        (method === "PUT" && existingId),
      `unexpected request ${method} ${path}`,
    );
    const existing = data.profiles.find((item) => item.id === existingId);
    if (method === "PUT")
      assert.ok(
        existing && !existing.preset,
        "edits update an existing custom profile",
      );
    const total = Object.values(body.importance).reduce(
      (sum, value) => sum + value,
      0,
    );
    const profile = {
      ...body,
      id: existingId ?? `saved-${nextId++}`,
      preset: false,
      normalized_weights: Object.fromEntries(
        Object.entries(body.importance).map(([key, value]) => [
          key,
          value / total,
        ]),
      ),
      created_at: existing?.created_at ?? "2026-09-09T12:00:00Z",
      updated_at: "2026-09-09T12:00:00Z",
    };
    if (existing) data.profiles[data.profiles.indexOf(existing)] = profile;
    else data.profiles.push(profile);
    return Response.json(profile);
  });
  const errors = [];
  t.mock.method(console, "error", (...args) => errors.push(args.join(" ")));
  let root = createRoot(document.getElementById("root"));
  const field = (id) => {
    const element = document.getElementById(id);
    assert.ok(element, `field ${id} exists`);
    return element;
  };
  const button = (name) => {
    const element = [...document.querySelectorAll("button")].find(
      (item) => item.textContent.trim() === name,
    );
    assert.ok(element, `button ${name} exists`);
    return element;
  };
  const click = async (element) => {
    assert.ok(!element.disabled, "requested control is enabled");
    await act(async () => {
      element.dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true }),
      );
    });
  };
  const change = async (id, value) => {
    const element = field(id);
    assert.ok(!element.disabled, `field ${id} is editable`);
    await act(async () => {
      const select = element instanceof dom.window.HTMLSelectElement;
      const prototype = select
        ? dom.window.HTMLSelectElement.prototype
        : dom.window.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, "value").set.call(
        element,
        value,
      );
      element.dispatchEvent(
        new dom.window.Event(select ? "change" : "input", { bubbles: true }),
      );
    });
  };
  const render = async () => {
    await act(async () => {
      root.render(createElement(RankingProfiles));
    });
  };
  const remount = async () => {
    await act(async () => {
      root.unmount();
    });
    root = createRoot(document.getElementById("root"));
    await render();
  };
  const activationCount = () =>
    mutations.filter((item) => item.path.endsWith("/activate")).length;
  try {
    await render();
    assert.equal(
      document.getElementById("ranking-profile-heading").textContent,
      "Ranking profiles",
    );
    assert.equal(
      document.querySelector('label[for="ranking-profile"]').textContent,
      "Ranking profile",
    );
    assert.equal(
      document.querySelector('label[for="profile-name"]').textContent,
      "Ranking profile name",
    );
    assert.equal(field("ranking-profile").value, "preset-oxide");
    assert.equal(field("minimum-band-gap").value, "2");
    assert.equal(field("band-gap-preference").value, "wider");
    assert.equal(
      document.getElementById("target-band-gap"),
      null,
      "profiles without a target do not invent one",
    );
    assert.match(
      document.querySelector('label[for="minimum-band-gap"]').textContent,
      /Minimum band gap \(eV\)/,
    );
    assert.match(
      document.getElementById("minimum-band-gap-help").textContent,
      /Only validated source values are compared; unknown band gaps remain unknown/,
    );
    const categories = () => [
      ...document.querySelectorAll(".attribute-categories > details"),
    ];
    const category = (name) =>
      categories().find(
        (item) => item.querySelector("summary").firstChild.textContent === name,
      );
    assert.equal(
      document.querySelector(".available-attributes"),
      null,
      "the property categories have no extra outer disclosure",
    );
    assert.equal(categories().length, 2, "each category appears once");
    assert.equal(
      category("Electronic properties").open,
      true,
      "categories with selected properties open initially",
    );
    assert.equal(
      category("Mechanical properties").open,
      false,
      "other category headings are directly available",
    );
    assert.equal(
      category("Electronic properties").querySelectorAll(".attribute-row")
        .length,
      2,
      "selected and available properties share one category",
    );
    assert.equal(
      document.querySelectorAll(".attribute-row").length,
      3,
      "properties never appear in duplicate groups",
    );
    assert.equal(field("importance-number-conductivity").disabled, true);
    assert.ok(
      !document
        .querySelector(".attribute-catalog")
        .textContent.includes("Materials Project"),
    );
    assert.ok(
      !document.body.textContent.includes("MP field:"),
      "source implementation field names are not ranking requirements",
    );
    assert.match(
      document.querySelector(".attribute-catalog header p").textContent,
      /0\.5 importance/,
    );
    await click(button("New ranking profile"));
    assert.deepEqual(
      [...document.querySelectorAll(".profile-comparison h3")].map(
        (item) => item.textContent,
      ),
      ["Active ranking profile", "Editing preview"],
      "the active chart stays above editing changes",
    );
    assert.equal(
      field("ranking-profile").value,
      "",
      "new ranking profile starts as an unsaved draft",
    );
    assert.ok(field("profile-name").value.trim());
    assert.notEqual(
      field("profile-name").value,
      "Oxide priorities",
      "the new draft receives its own name",
    );
    assert.equal(
      field("importance-number-band_gap").value,
      "0.8",
      "new draft starts with current priorities",
    );
    assert.equal(
      field("minimum-band-gap").value,
      "2",
      "a new profile preserves the independent floor preference",
    );
    assert.equal(data.active_profile_id, "preset-oxide");
    assert.equal(
      mutations.length,
      0,
      "starting a draft neither saves nor activates it",
    );
    assert.ok(
      button("Use ranking profile").disabled,
      "an unsaved draft cannot be activated",
    );

    await change("profile-name", "Trial ranking profile");
    await change("material-class", "ceramic");
    assert.equal(
      field("profile-name").value,
      "Trial ranking profile",
      "class selection preserves the draft name",
    );
    assert.equal(
      field("ranking-profile").value,
      "",
      "class selection preserves draft identity",
    );
    assert.equal(field("importance-number-bulk_modulus").value, "0.7");
    assert.equal(
      document.getElementById("minimum-band-gap"),
      null,
      "a different preset does not inherit the oxide floor",
    );
    assert.equal(
      category("Mechanical properties").open,
      true,
      "changing the material preset reveals its selected category",
    );
    await change("material-class", "oxide");
    assert.equal(
      field("minimum-band-gap").value,
      "2",
      "matching preset restores its own floor preference",
    );
    await change("profile-application", "wide_gap");
    assert.equal(
      field("minimum-band-gap").value,
      "",
      "a preset with no minimum is not assigned the previous minimum",
    );
    await change("minimum-band-gap", "101");
    assert.ok(button("Save ranking profile").disabled);
    assert.equal(
      field("minimum-band-gap").getAttribute("aria-invalid"),
      "true",
    );
    assert.match(
      document.querySelector('.profile-minimum-gap [role="alert"]').textContent,
      /0 to 100 eV/,
    );
    await change("minimum-band-gap", "3.25");
    assert.equal(
      field("profile-name").value,
      "Trial ranking profile",
      "application selection preserves the draft name",
    );
    assert.equal(field("ranking-profile").value, "");
    assert.equal(
      field("importance-number-band_gap").value,
      "0.9",
      "matching application supplies its priorities",
    );
    await click(button("Save ranking profile"));
    assert.equal(mutations.at(-1).method, "POST");
    assert.equal(mutations.at(-1).body.minimum_band_gap_ev, 3.25);
    assert.equal(
      mutations.at(-1).body.target_band_gap_ev,
      4.2,
      "copying preset preferences preserves its target",
    );
    assert.equal(mutations.at(-1).body.band_gap_tolerance_ev, 0.2);
    assert.deepEqual(
      mutations.at(-1).body.importance,
      { band_gap: 0.9 },
      "minimum is not another importance weight",
    );
    assert.equal(data.profiles.length, 4);
    assert.equal(field("ranking-profile").value, "saved-1");
    assert.equal(
      data.active_profile_id,
      "preset-oxide",
      "saving a ranking profile does not activate it",
    );
    assert.equal(activationCount(), 0);

    await change("importance-number-band_gap", "0.43");
    assert.ok(
      button("Use ranking profile").disabled,
      "unsaved edits cannot be activated",
    );
    await click(button("Save ranking profile"));
    assert.equal(mutations.at(-1).method, "PUT");
    assert.equal(mutations.at(-1).path, "/api/ranking-profiles/saved-1");
    assert.equal(
      data.profiles.length,
      4,
      "updating a custom ranking profile does not create a duplicate",
    );
    assert.equal(
      data.profiles.find((item) => item.id === "saved-1").importance.band_gap,
      0.43,
    );
    assert.equal(
      data.profiles.find((item) => item.id === "saved-1").minimum_band_gap_ev,
      3.25,
    );
    assert.equal(
      data.profiles.find((item) => item.id === "saved-1").target_band_gap_ev,
      4.2,
      "editing custom profile importance preserves its target",
    );
    assert.equal(
      data.profiles.find((item) => item.id === "saved-1").band_gap_tolerance_ev,
      0.2,
    );
    await click(button("Use ranking profile"));
    assert.equal(data.active_profile_id, "saved-1");
    assert.equal(activationCount(), 1);

    await click(button("New ranking profile"));
    await change("profile-name", "Custom laboratory priorities");
    await change("material-class", "__custom__");
    await change("custom-material-class", "Custom material family");
    await change("custom-application", "Custom research application");
    const bulkCheckbox = [...document.querySelectorAll(".attribute-row label")]
      .find((label) => label.textContent.trim() === "Bulk modulus")
      ?.querySelector('input[type="checkbox"]');
    assert.ok(
      bulkCheckbox && !bulkCheckbox.checked,
      "an additional catalog attribute can be selected",
    );
    const bulkRow = bulkCheckbox.closest(".attribute-row");
    await click(category("Mechanical properties").querySelector("summary"));
    assert.equal(category("Mechanical properties").open, true);
    await click(bulkCheckbox);
    await change("importance-number-band_gap", "0");
    assert.equal(
      field("minimum-band-gap").value,
      "3.25",
      "inactive thresholds remain editable instead of hidden",
    );
    assert.match(
      document.querySelector(".profile-constraint-inactive").textContent,
      /Inactive while Band gap importance is zero or unselected/,
    );
    await change("minimum-band-gap", "");
    assert.equal(
      document.getElementById("minimum-band-gap"),
      null,
      "clearing an inactive threshold leaves no hidden constraint",
    );
    assert.equal(
      field("importance-number-bulk_modulus").value,
      "0.5",
      "newly checked properties start at 0.5",
    );
    assert.equal(
      field("importance-bulk_modulus").value,
      "0.5",
      "the slider has the same initial importance",
    );
    assert.equal(
      field("importance-bulk_modulus").closest(".attribute-row"),
      bulkRow,
      "selecting an attribute keeps it in place",
    );
    assert.equal(categories().length, 2);
    assert.equal(
      document.querySelectorAll("#importance-number-bulk_modulus").length,
      1,
    );
    assert.ok(
      !document
        .querySelector('[aria-label="Active ranking profile"]')
        .textContent.includes("Bulk modulus"),
      "editing a profile does not change the active chart",
    );
    await change("importance-number-band_gap", "0.4");
    await change("importance-bulk_modulus", "0.6");
    assert.equal(
      field("importance-number-bulk_modulus").value,
      "0.6",
      "sliders and manual values stay synchronized",
    );
    await click(button("Save ranking profile"));
    assert.equal(mutations.at(-1).method, "POST");
    assert.equal(data.profiles.length, 5);
    const custom = data.profiles.find((item) => item.id === "saved-2");
    assert.equal(custom.name, "Custom laboratory priorities");
    assert.equal(custom.material_class, "Custom material family");
    assert.equal(custom.application, "Custom research application");
    assert.deepEqual(custom.importance, { band_gap: 0.4, bulk_modulus: 0.6 });
    assert.equal(
      custom.minimum_band_gap_ev,
      null,
      "blank explicitly disables the saved minimum",
    );
    assert.equal(data.active_profile_id, "saved-1");
    assert.equal(
      activationCount(),
      1,
      "saving custom labels and priorities leaves the active profile unchanged",
    );

    await remount();
    assert.equal(
      field("ranking-profile").value,
      "saved-1",
      "opening Search Criterion loads the saved active profile",
    );
    assert.ok(
      [...field("ranking-profile").options].some(
        (option) =>
          option.value === "saved-2" &&
          option.textContent.includes("Custom laboratory priorities"),
      ),
      "saved custom ranking profiles remain available after reload",
    );
    await change("ranking-profile", "saved-2");
    assert.equal(
      field("custom-material-class").value,
      "Custom material family",
    );
    assert.equal(
      field("custom-application").value,
      "Custom research application",
    );
    assert.equal(field("importance-number-band_gap").value, "0.4");
    assert.equal(field("importance-number-bulk_modulus").value, "0.6");
    assert.equal(
      field("minimum-band-gap").value,
      "",
      "the cleared custom minimum survives reload",
    );
    assert.equal(
      data.active_profile_id,
      "saved-1",
      "selecting a saved ranking profile only loads its editor",
    );
    await click(button("Use ranking profile"));
    await remount();
    assert.equal(field("ranking-profile").value, "saved-2");
    assert.equal(field("profile-name").value, "Custom laboratory priorities");
    assert.equal(activationCount(), 2);
    assert.equal(field("band-gap-preference").value, "target");
    assert.equal(field("target-band-gap").value, "4.2");
    assert.equal(field("band-gap-tolerance").value, "0.2");
    assert.match(
      document.getElementById("target-band-gap-help").textContent,
      /separate from measurement uncertainty/,
    );
    await change("band-gap-preference", "wider");
    assert.equal(document.getElementById("target-band-gap"), null);
    assert.equal(document.getElementById("band-gap-tolerance"), null);
    await click(button("Save ranking profile"));
    assert.equal(
      mutations.at(-1).body.target_band_gap_ev,
      null,
      "disabling the target clears it",
    );
    assert.equal(
      mutations.at(-1).body.band_gap_tolerance_ev,
      null,
      "disabling the target also clears its tolerance",
    );
    await change("band-gap-preference", "target");
    assert.equal(
      field("target-band-gap").value,
      "",
      "choosing target mode does not choose a numeric target",
    );
    assert.equal(field("band-gap-tolerance").disabled, true);
    assert.equal(button("Save ranking profile").disabled, true);
    await change("target-band-gap", "1.78");
    assert.equal(
      field("band-gap-tolerance").value,
      "0.2",
      "new explicit target starts with the disclosed soft preference scale",
    );
    await change("band-gap-tolerance", "0");
    assert.equal(button("Save ranking profile").disabled, true);
    await change("band-gap-tolerance", "0.15");
    await click(button("Save ranking profile"));
    assert.equal(mutations.at(-1).body.target_band_gap_ev, 1.78);
    assert.equal(mutations.at(-1).body.band_gap_tolerance_ev, 0.15);
    await remount();
    assert.equal(field("target-band-gap").value, "1.78");
    assert.equal(field("band-gap-tolerance").value, "0.15");
    await change("target-band-gap", "");
    assert.equal(field("band-gap-tolerance").value, "");
    assert.equal(field("band-gap-tolerance").disabled, true);
    assert.equal(
      button("Save ranking profile").disabled,
      true,
      "clearing a target requires choosing a new target or wider-gap mode",
    );
    assert.ok(
      !errors.some((message) =>
        /same key|unique.*key|not wrapped in act/i.test(message),
      ),
      errors.join("\n"),
    );
  } finally {
    await act(async () => {
      root.unmount();
    });
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
    await rm(output, { recursive: true, force: true });
  }
});

async function withImportanceDom(t, check, inDialog = false) {
  const output = await compileRankingEditor();
  const dom = new JSDOM(
    inDialog
      ? '<dialog open><div id="root"></div></dialog>'
      : '<div id="root"></div>',
    { url: "http://localhost/" },
  );
  const observers = new Set();
  class TestResizeObserver {
    constructor(callback) {
      this.callback = callback;
      this.elements = new Set();
      observers.add(this);
    }
    observe(element) {
      this.elements.add(element);
    }
    disconnect() {
      observers.delete(this);
    }
  }
  const globals = [
    "window",
    "document",
    "HTMLElement",
    "Node",
    "navigator",
    "ResizeObserver",
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
      value:
        key === "IS_REACT_ACT_ENVIRONMENT"
          ? true
          : key === "ResizeObserver"
            ? TestResizeObserver
            : dom.window[key],
      writable: true,
      configurable: true,
    });
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { default: RankingProfiles } = await import(
    pathToFileURL(join(output, "RankingProfiles.js")).href
  );
  const data = fixture();
  data.profiles[0].importance = { band_gap: 0.75, conductivity: 0.25 };
  data.profiles[0].normalized_weights = { band_gap: 0.75, conductivity: 0.25 };
  const requests = [];
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    requests.push({ path, method: options.method ?? "GET" });
    assert.equal(path, "/api/ranking-profiles");
    assert.equal(options.method ?? "GET", "GET");
    return Response.json(data);
  });
  const root = createRoot(document.getElementById("root"));
  const rectangles = new Map();
  const box = (left, top, width, height) => ({
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
    x: left,
    y: top,
    toJSON() {
      return {};
    },
  });
  t.mock.method(
    dom.window.HTMLElement.prototype,
    "getBoundingClientRect",
    function () {
      if (this.classList.contains("importance-tooltip"))
        return box(
          Number.parseFloat(this.style.left) || 0,
          Number.parseFloat(this.style.top) || 0,
          Number.parseFloat(this.style.width) || 300,
          180,
        );
      return rectangles.get(this) ?? box(40, 300, 160, 22);
    },
  );
  const click = async (element) => {
    assert.ok(element);
    await act(async () => {
      element.dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true }),
      );
    });
  };
  const pointer = async (
    element,
    type,
    relatedTarget = null,
    pointerType = "mouse",
  ) => {
    await act(async () => {
      const event = new dom.window.MouseEvent(type, {
        bubbles: true,
        relatedTarget,
      });
      Object.defineProperty(event, "pointerType", { value: pointerType });
      element.dispatchEvent(event);
    });
  };
  const segment = (label, preview = false) =>
    [
      ...document.querySelectorAll(
        `[aria-label="${preview ? "Editing preview" : "Active ranking profile"}"] .importance-segment`,
      ),
    ].find((element) =>
      element.getAttribute("aria-label").startsWith(label + ":"),
    );
  const tooltip = () => document.querySelector('[role="tooltip"]');
  const change = async (element, value) => {
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        dom.window.HTMLInputElement.prototype,
        "value",
      ).set.call(element, value);
      element.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
  };
  try {
    await act(async () => {
      root.render(createElement(RankingProfiles));
    });
    await check({
      document: dom.window.document,
      window: dom.window,
      act,
      click,
      pointer,
      segment,
      tooltip,
      change,
      requests,
      rectangles,
      box,
      observers,
      focus: async (element) => {
        await act(async () => {
          element.focus();
        });
      },
      settleLeave: async () => {
        await act(async () => {
          await new Promise((resolve) => setTimeout(resolve, 170));
        });
      },
    });
  } finally {
    await act(async () => {
      root.unmount();
    });
    assert.equal(
      dom.window.document.querySelector('[role="tooltip"]'),
      null,
      "portaled tooltip is removed on unmount",
    );
    assert.equal(
      observers.size,
      0,
      "size observers are disconnected on unmount",
    );
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
    await rm(output, { recursive: true, force: true });
  }
}

test("ranking segments expose visible details by focus and tap with unsupported shares retained in both charts", async (t) => {
  await withImportanceDom(
    t,
    async ({ document, click, focus, segment, tooltip, change, requests }) => {
      assert.equal(tooltip(), null);
      const gap = segment("Band gap");
      assert.equal(gap.tagName, "BUTTON");
      assert.equal(gap.type, "button");
      assert.equal(gap.tabIndex, 0);
      assert.equal(gap.closest('[aria-hidden="true"]'), null);
      assert.equal(gap.hasAttribute("title"), false);
      await focus(gap);
      assert.match(
        tooltip().textContent,
        /Band gap75\.0%of all selected importance/,
      );
      assert.match(tooltip().textContent, /Independent importance 0\.75 \/ 1/);
      assert.equal(gap.getAttribute("aria-describedby"), tooltip().id);
      await click(segment("Conductivity"));
      assert.equal(
        document.activeElement,
        segment("Conductivity"),
        "click/tap explicitly focuses the segment",
      );
      assert.match(tooltip().textContent, /Conductivity25\.0%/);
      assert.match(
        tooltip().textContent,
        /Not yet scored\. This share stays in the total as an evidence gap/,
      );
      assert.equal(
        segment("Conductivity").style.flexGrow,
        "0.25",
        "unsupported importance is not redistributed",
      );
      await click(
        [...document.querySelectorAll("button")].find(
          (element) => element.textContent === "New ranking profile",
        ),
      );
      await click(segment("Conductivity", true));
      assert.match(tooltip().textContent, /^Editing preview/);
      await change(
        document.getElementById("importance-number-band_gap"),
        ".25",
      );
      assert.match(tooltip().textContent, /Conductivity50\.0%/);
      assert.match(tooltip().textContent, /Independent importance 0\.25 \/ 1/);
      await focus(segment("Conductivity"));
      assert.match(
        tooltip().textContent,
        /^Active ranking profileConductivity25\.0%/,
      );
      await click(segment("Conductivity", true));
      await change(
        document.getElementById("importance-number-conductivity"),
        ".004",
      );
      assert.match(
        tooltip().textContent,
        /Independent importance 0\.004 \/ 1/,
        "positive raw values never round down to zero",
      );
      assert.deepEqual(
        requests,
        [{ path: "/api/ranking-profiles", method: "GET" }],
        "chart exploration neither saves nor activates preferences",
      );
    },
  );
});

test("one tooltip survives pointer transfer and focus, dismisses with Escape/outside, and clears removed segments", async (t) => {
  await withImportanceDom(
    t,
    async ({
      document,
      window,
      act,
      pointer,
      focus,
      click,
      segment,
      tooltip,
      settleLeave,
    }) => {
      const gap = segment("Band gap"),
        conductivity = segment("Conductivity");
      await pointer(gap, "pointerover");
      assert.match(tooltip().textContent, /Band gap/);
      await pointer(gap, "pointerout", tooltip());
      await pointer(tooltip(), "pointerover", gap);
      await settleLeave();
      assert.ok(tooltip(), "pointer can reach the tooltip and read it");
      await pointer(tooltip(), "pointerout", document.body);
      await settleLeave();
      assert.equal(tooltip(), null);
      await pointer(conductivity, "pointerover");
      await focus(gap);
      assert.match(
        tooltip().textContent,
        /Band gap/,
        "new keyboard focus wins over a stationary pointer on another segment",
      );
      assert.equal(gap.getAttribute("aria-describedby"), tooltip().id);
      assert.equal(conductivity.hasAttribute("aria-describedby"), false);
      await focus(gap);
      await pointer(conductivity, "pointerover");
      assert.equal(document.querySelectorAll('[role="tooltip"]').length, 1);
      assert.match(tooltip().textContent, /Conductivity/);
      await pointer(conductivity, "pointerout");
      await settleLeave();
      assert.match(
        tooltip().textContent,
        /Band gap/,
        "leaving hover restores details for the focused segment",
      );
      const escape = new window.KeyboardEvent("keydown", {
        key: "Escape",
        bubbles: true,
        cancelable: true,
      });
      await act(async () => {
        gap.dispatchEvent(escape);
      });
      assert.equal(
        escape.defaultPrevented,
        true,
        "Escape is consumed before a containing dialog can cancel",
      );
      assert.equal(tooltip(), null);
      assert.equal(document.activeElement, gap);
      await settleLeave();
      assert.equal(
        tooltip(),
        null,
        "unchanged focus does not reopen a dismissed tooltip",
      );
      assert.equal(gap.hasAttribute("aria-describedby"), false);
      await click(gap);
      assert.ok(tooltip(), "click can deliberately reopen after Escape");
      await pointer(document.body, "pointerdown");
      assert.equal(tooltip(), null);
      await pointer(conductivity, "pointerover", null, "touch");
      assert.equal(
        tooltip(),
        null,
        "touch entry does not leave a simulated hover pinned",
      );
      await click(conductivity);
      assert.ok(tooltip());
      await click(
        [...document.querySelectorAll("button")].find(
          (element) => element.textContent === "New ranking profile",
        ),
      );
      await focus(segment("Conductivity", true));
      const checkbox = [
        ...document.querySelectorAll(".attribute-description label"),
      ]
        .find((element) => element.textContent === "Conductivity")
        .querySelector("input");
      await click(checkbox);
      assert.equal(segment("Conductivity", true), undefined);
      assert.equal(tooltip(), null);
    },
  );
});

test("tooltips use the dialog top layer, fit viewport edges, and follow scroll and resize geometry", async (t) => {
  await withImportanceDom(
    t,
    async ({
      document,
      window,
      act,
      focus,
      segment,
      tooltip,
      rectangles,
      box,
      observers,
    }) => {
      window.innerWidth = 320;
      window.innerHeight = 600;
      const gap = segment("Band gap");
      rectangles.set(gap, box(300, 20, 18, 22));
      await focus(gap);
      assert.equal(
        tooltip().parentElement,
        document.querySelector("dialog"),
        "portal remains in the native dialog top layer",
      );
      assert.equal(
        tooltip().closest(".importance-chart"),
        null,
        "chart overflow cannot clip the overlay",
      );
      assert.equal(tooltip().style.visibility, "visible");
      assert.equal(tooltip().style.width, "296px");
      assert.equal(tooltip().style.left, "12px");
      assert.equal(tooltip().style.top, "52px");
      assert.equal(tooltip().dataset.side, "below");
      rectangles.set(gap, box(0, 565, 20, 22));
      await act(async () => {
        document
          .querySelector("dialog")
          .dispatchEvent(new window.Event("scroll"));
      });
      assert.equal(tooltip().style.left, "12px");
      assert.equal(tooltip().style.top, "375px");
      assert.equal(tooltip().dataset.side, "above");
      window.innerWidth = 240;
      await act(async () => {
        window.dispatchEvent(new window.Event("resize"));
      });
      assert.equal(tooltip().style.width, "216px");
      assert.equal(tooltip().style.left, "12px");
      assert.ok(
        [...observers].some(
          (observer) =>
            observer.elements.has(gap) && observer.elements.has(tooltip()),
        ),
      );
      rectangles.set(gap, box(0, -40, 20, 22));
      await act(async () => {
        for (const observer of [...observers]) observer.callback();
      });
      assert.equal(
        tooltip(),
        null,
        "a scrolled-away segment cannot leave a floating detached tooltip",
      );
    },
    true,
  );
});
