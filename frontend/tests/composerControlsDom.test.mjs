import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

async function compileControls() {
  const output = await mkdtemp(join(tmpdir(), "labcat-composer-dom-"));
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

const profile = (
  provider = "none",
  model = "",
  allow_paid_inference = false,
) => ({
  provider,
  model,
  allow_paid_inference,
  ollama_url: "http://localhost:11434",
  aws_profile: "",
  aws_region: "",
});
function statusFixture(accounts = []) {
  return {
    configured: true,
    profile: profile(),
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
    using_local_defaults: true,
    warnings: [],
    accounts,
    active_account_id: null,
  };
}
function rankingFixture() {
  const base = {
    material_class: "oxide",
    application: "dielectric",
    importance: { band_gap: 0.5 },
    normalized_weights: { band_gap: 1 },
    created_at: "2026-09-09",
    updated_at: "2026-09-09",
  };
  return {
    active_profile_id: "preset-oxide",
    catalog: {
      attributes: [
        {
          id: "band_gap",
          label: "Band gap",
          category: "Electronic",
          description: "Test preference only.",
          source_field: null,
          supported: false,
          availability_note: "Not a scientific fixture.",
        },
      ],
      material_classes: [{ id: "oxide", label: "Oxides", scope: "" }],
      applications: [{ id: "dielectric", label: "Dielectric", scope: "" }],
    },
    profiles: [
      { ...base, id: "preset-oxide", name: "Oxide priorities", preset: true },
      { ...base, id: "custom-one", name: "My ranking profile", preset: false },
    ],
  };
}

test("composer profiles are per-request and model changes retain credentials and consent with uncertain-save recovery", async (t) => {
  const output = await compileControls();
  const dom = new JSDOM(
    '<div id="root"></div><button id="outside">Outside</button>',
    { url: "http://localhost/" },
  );
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
  const { createElement, act, useState } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { default: ComposerControls } = await import(
    pathToFileURL(join(output, "ComposerControls.js")).href
  );
  const { ConnectionsProvider, useConnections } = await import(
    pathToFileURL(join(output, "Connections.js")).href
  );
  const { SetupProvider, useSetup } = await import(
    pathToFileURL(join(output, "SetupWizard.js")).href
  );
  const cloud = {
    id: "cloud",
    label: "Research account",
    profile: profile("openai", "saved-model"),
    credential_state: "encrypted",
  };
  const locked = {
    id: "locked",
    label: "Locked account",
    profile: profile("anthropic", "other-model", true),
    credential_state: "locked",
  };
  const state = statusFixture([cloud, locked]);
  const rankings = rankingFixture();
  const calls = [],
    changes = [],
    setupObservations = [];
  let settingsOpened = 0,
    connectionsOpened = 0,
    rejectSave = false,
    rejectProfiles = false,
    disabled = false,
    harnessKey = 0,
    initialProfile = "infer";
  let deferCatalog = false,
    rejectCatalog = false,
    reloadOutside,
    holdVerify = false,
    rejectVerify = false,
    mismatchVerify = false,
    finishVerify;
  const catalogs = [];
  let verified = null;
  const fingerprint = () =>
    JSON.stringify([
      state.active_account_id,
      state.profile,
      state.accounts.find((item) => item.id === state.active_account_id)
        ?.credential_state,
    ]);
  function setupState() {
    const account = state.accounts.find(
      (item) => item.id === state.active_account_id,
    );
    const modelStatus =
      !account || account.credential_state === "missing"
        ? "not_connected"
        : account.credential_state === "locked"
          ? "credentials_locked"
          : !state.profile.allow_paid_inference
            ? "consent_required"
            : verified === fingerprint()
              ? "ready"
              : "verification_required";
    return {
      version: 1,
      completed: true,
      current_step: "review",
      required: true,
      can_research: modelStatus === "ready",
      model: {
        status: modelStatus,
        provider: state.profile.provider,
        model: state.profile.model,
        account_id: state.active_account_id,
        message:
          modelStatus === "ready"
            ? "Metadata verified without inference."
            : "Check the saved connection.",
        checked_at: modelStatus === "ready" ? "2026-09-10T12:00:00Z" : null,
      },
      optional: {
        compute: "local",
        aws_required: false,
        data_apis_required: false,
      },
    };
  }
  const errors = [];
  t.mock.method(console, "error", (...args) => errors.push(args.join(" ")));
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    const method = options.method ?? "GET",
      body = options.body ? JSON.parse(options.body) : undefined;
    calls.push({ path, method, body });
    if (path === "/api/session")
      return Response.json({
        csrf_token: "csrf-fixture-at-least-sixteen-characters",
      });
    if (path === "/api/connections" && method === "GET")
      return Response.json(state);
    if (path === "/api/connections/setup") return Response.json(setupState());
    if (path === "/api/connections/setup/verify") {
      if (rejectVerify)
        return Response.json(
          { detail: "private diagnostic credential marker" },
          { status: 503 },
        );
      if (mismatchVerify) {
        const wrong = setupState();
        wrong.can_research = true;
        wrong.model = {
          ...wrong.model,
          status: "ready",
          account_id: "different-account",
          model: "different-model",
        };
        return Response.json(wrong);
      }
      const expected = fingerprint();
      if (holdVerify)
        await new Promise((resolve) => {
          finishVerify = resolve;
        });
      verified = expected;
      return Response.json(setupState());
    }
    if (path === "/api/ranking-profiles" && method === "GET")
      return rejectProfiles
        ? new Response("private diagnostic", { status: 500 })
        : Response.json(rankings);
    if (path === "/api/connections/models") {
      const catalog = {
        provider: state.profile.provider,
        models: [
          { id: "saved-model", label: "Saved model" },
          { id: "next-model", label: "Next model" },
        ],
        message: "Catalog lookup only; inference was not tested.",
        inference_tested: false,
      };
      if (rejectCatalog)
        return Response.json(
          { detail: "private diagnostic credential marker" },
          { status: 503 },
        );
      if (deferCatalog)
        return new Promise((resolve) => {
          catalogs.push({
            signal: options.signal,
            finish: () => resolve(Response.json(catalog)),
          });
        });
      return Response.json(catalog);
    }
    if (path === "/api/connections/local-defaults") {
      state.profile = profile();
      state.active_account_id = null;
      state.using_local_defaults = true;
      return Response.json(state);
    }
    const selectId = /^\/api\/connections\/accounts\/([^/]+)\/select$/.exec(
      path,
    )?.[1];
    if (selectId) {
      const saved = state.accounts.find((item) => item.id === selectId);
      assert.ok(saved);
      state.profile = { ...saved.profile };
      state.active_account_id = saved.id;
      state.using_local_defaults = false;
      return Response.json(state);
    }
    const saveId = /^\/api\/connections\/accounts\/([^/]+)$/.exec(path)?.[1];
    if (saveId && method === "PUT") {
      const saved = state.accounts.find((item) => item.id === saveId);
      assert.ok(saved);
      assert.ok(
        !Object.hasOwn(body, "api_key"),
        "model changes never submit credentials",
      );
      assert.equal(
        body.profile.allow_paid_inference,
        saved.profile.allow_paid_inference,
        "model changes preserve existing consent",
      );
      assert.equal(
        body.secret_storage,
        saved.credential_state === "encrypted" ? "encrypted" : "session",
      );
      assert.deepEqual(Object.keys(body).sort(), [
        "label",
        "profile",
        "secret_storage",
      ]);
      assert.deepEqual(
        body.profile,
        { ...saved.profile, model: body.profile.model },
        "only the chosen model preference changes",
      );
      saved.profile = { ...body.profile };
      state.profile = { ...body.profile };
      verified = null;
      return rejectSave
        ? new Response("private diagnostic", { status: 500 })
        : Response.json(state);
    }
    assert.fail(`Unexpected request: ${method} ${path}`);
  });
  function ConnectionProbe() {
    reloadOutside = useConnections().reload;
    const setup = useSetup();
    setupObservations.push({
      ready: Boolean(setup.status?.can_research),
      model: setup.status?.model.model,
    });
    return createElement("output", {
      id: "setup-probe",
      "data-ready": String(
        Boolean(setup.status?.can_research) &&
          !setup.error &&
          !setup.busy &&
          !setup.loading,
      ),
      "data-model": setup.status?.model.model ?? "",
    });
  }
  function Harness() {
    const [selected, setSelected] = useState(initialProfile);
    return createElement(
      ConnectionsProvider,
      null,
      createElement(
        SetupProvider,
        null,
        createElement(ConnectionProbe),
        createElement(ComposerControls, {
          rankingProfileId: selected,
          onRankingProfileChange: (next) => {
            changes.push(next);
            setSelected(next);
          },
          disabled,
          onOpenSettings: () => {
            settingsOpened++;
          },
          onOpenConnections: () => {
            connectionsOpened++;
          },
        }),
      ),
    );
  }
  const root = createRoot(document.getElementById("root"));
  const render = async () => {
    await act(async () => {
      root.render(createElement(Harness, { key: harnessKey }));
    });
  };
  const button = (name) => {
    const found = [...document.querySelectorAll("button")].find(
      (item) => item.textContent.trim() === name,
    );
    assert.ok(found, `button ${name} exists`);
    return found;
  };
  const trigger = (kind) => {
    const found = document.querySelector(`.composer-${kind}-button`);
    assert.ok(found);
    return found;
  };
  const choice = (name) => {
    const found = [...document.querySelectorAll(".composer-choice")].find(
      (item) => item.querySelector("strong")?.textContent === name,
    );
    assert.ok(found, `choice ${name} exists`);
    return found;
  };
  const click = async (element) => {
    assert.ok(!element.disabled, `${element.textContent} is enabled`);
    await act(async () => {
      element.dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true }),
      );
    });
  };
  const change = async (element, value) => {
    await act(async () => {
      const select = element instanceof dom.window.HTMLSelectElement;
      Object.getOwnPropertyDescriptor(
        select
          ? dom.window.HTMLSelectElement.prototype
          : dom.window.HTMLInputElement.prototype,
        "value",
      ).set.call(element, value);
      element.dispatchEvent(
        new dom.window.Event(select ? "change" : "input", { bubbles: true }),
      );
    });
  };
  const escape = async () => {
    await act(async () => {
      document.dispatchEvent(
        new dom.window.KeyboardEvent("keydown", {
          key: "Escape",
          bubbles: true,
        }),
      );
    });
  };
  try {
    await render();
    assert.equal(
      calls.filter((item) => item.path === "/api/ranking-profiles").length,
      0,
      "default infer mode loads saved profiles only on opening",
    );
    assert.deepEqual(
      [...document.querySelector(".composer-controls").children].map((item) =>
        item.className.includes("ranking"),
      ),
      [true, false],
      "ranking selector precedes model selector",
    );
    assert.match(trigger("ranking").textContent, /Infer from prompt/);
    await click(trigger("ranking"));
    assert.equal(
      document.querySelector('[role="dialog"]').parentElement,
      document.body,
      "popup escapes any composer clipping",
    );
    const help = document.querySelector(
      '[aria-label="About ranking profiles"]',
    );
    await click(help);
    assert.equal(help.getAttribute("aria-expanded"), "true");
    assert.match(
      document.querySelector('[aria-label="How ranking profiles work"]')
        .textContent,
      /previous reports keep their saved criteria/,
    );
    await act(async () => {
      help.dispatchEvent(
        new dom.window.KeyboardEvent("keydown", {
          key: "Escape",
          bubbles: true,
          cancelable: true,
        }),
      );
    });
    assert.equal(help.getAttribute("aria-expanded"), "false");
    assert.ok(
      document.querySelector('[role="dialog"]'),
      "Escape closes inline help before its containing selector",
    );
    assert.equal(document.activeElement, help);
    assert.equal(
      choice("Infer from prompt").getAttribute("aria-pressed"),
      "true",
    );
    assert.match(
      choice("Oxide priorities").textContent,
      /Active in Search Criterion/,
    );
    await change(
      document.querySelector(".composer-profile-search"),
      "My ranking",
    );
    assert.equal(
      document.querySelectorAll(".composer-profile-list .composer-choice")
        .length,
      1,
    );
    await click(choice("My ranking profile"));
    assert.deepEqual(changes, ["custom-one"]);
    assert.match(trigger("ranking").textContent, /My ranking profile/);
    assert.equal(document.querySelector('[role="dialog"]'), null);
    assert.equal(document.activeElement, trigger("ranking"));
    assert.equal(
      calls.filter(
        (item) =>
          item.path.includes("ranking-profiles") && item.method !== "GET",
      ).length,
      0,
      "choosing a request profile never activates global settings",
    );
    await click(trigger("ranking"));
    await click(choice("Infer from prompt"));
    assert.deepEqual(changes, ["custom-one", "infer"]);
    await click(trigger("ranking"));
    await escape();
    assert.equal(document.querySelector('[role="dialog"]'), null);
    await click(trigger("ranking"));
    await click(button("Manage in Search Criterion ↗"));
    assert.equal(settingsOpened, 1);
    assert.equal(document.querySelector('[role="dialog"]'), null);
    rejectProfiles = true;
    await click(trigger("ranking"));
    assert.ok(document.querySelector(".composer-picker-error"));
    assert.ok(choice("Infer from prompt").disabled);
    assert.doesNotMatch(document.body.textContent, /private diagnostic/);
    rejectProfiles = false;
    await click(button("Reload ranking profiles"));
    assert.ok(!choice("Infer from prompt").disabled);
    await escape();

    assert.equal(
      calls.filter((item) => item.path === "/api/connections/models").length,
      0,
      "the closed model popup does not fetch a catalog",
    );
    await click(trigger("model"));
    await click(choice("OpenAI API (ChatGPT models)"));
    assert.equal(state.active_account_id, "cloud");
    const legacyDuplicate = {
      id: "legacy-openai",
      label: "Older private account label",
      profile: profile("openai", "legacy-model"),
      credential_state: "missing",
    };
    state.accounts.unshift(legacyDuplicate);
    await act(async () => {
      await reloadOutside();
    });
    assert.deepEqual(
      [...document.querySelectorAll(".composer-account-list strong")].map(
        (item) => item.textContent,
      ),
      ["OpenAI API (ChatGPT models)", "Anthropic (Claude) API"],
      "one provider choice is shown, with the active account first even when a legacy duplicate precedes it",
    );
    assert.equal(
      choice("OpenAI API (ChatGPT models)").getAttribute("aria-pressed"),
      "true",
    );
    assert.match(
      choice("OpenAI API (ChatGPT models)").textContent,
      /saved-model/,
    );
    assert.doesNotMatch(
      document.querySelector(".composer-account-list").textContent,
      /Research account|Locked account|Older private account label|legacy-model/,
      "internal saved account names and duplicate rows are not shown",
    );
    const beforeCurrentClick = calls.length;
    await click(choice("OpenAI API (ChatGPT models)"));
    assert.equal(
      calls.length,
      beforeCurrentClick,
      "choosing the active provider does not save, select, or reauthenticate it",
    );
    assert.match(
      document.querySelector(".composer-model-paused").textContent,
      /Cloud planning is paused/,
    );
    assert.equal(
      state.profile.allow_paid_inference,
      false,
      "account selection does not enable paid inference",
    );
    assert.match(
      document.querySelector(".composer-active-model").textContent,
      /inference was not tested/,
    );
    assert.ok(
      !document.querySelector(".composer-active-model select").disabled,
      "catalog loads automatically for the selected account",
    );
    const firstModels = calls.filter(
      (item) => item.path === "/api/connections/models",
    ).length;
    await render();
    assert.equal(
      calls.filter((item) => item.path === "/api/connections/models").length,
      firstModels,
      "an unchanged open popup does not loop metadata requests",
    );
    assert.equal(
      calls.filter((item) => item.path === "/api/connections/setup/verify")
        .length,
      0,
      "metadata discovery does not grant consent or verify an unconsented account",
    );
    await change(
      document.querySelector(".composer-active-model select"),
      "next-model",
    );
    assert.equal(cloud.profile.model, "next-model");
    assert.equal(cloud.profile.allow_paid_inference, false);
    assert.equal(
      calls.filter((item) => item.path === "/api/connections/setup/verify")
        .length,
      0,
    );
    assert.equal(document.querySelector("#setup-probe").dataset.ready, "false");

    deferCatalog = true;
    cloud.credential_state = "session";
    state.credentials.openai = "session";
    await act(async () => {
      await reloadOutside();
    });
    assert.equal(
      catalogs.length,
      1,
      "a changed credential state automatically reloads its catalog",
    );
    const oldCatalog = catalogs[0];
    assert.ok(document.querySelector(".composer-active-model select").disabled);
    cloud.credential_state = "encrypted";
    state.credentials.openai = "encrypted";
    await act(async () => {
      await reloadOutside();
    });
    assert.equal(
      oldCatalog.signal.aborted,
      true,
      "the old credential lookup is aborted",
    );
    assert.equal(catalogs.length, 2);
    await act(async () => oldCatalog.finish());
    assert.ok(
      document.querySelector(".composer-active-model select").disabled,
      "late metadata cannot populate the newer connection",
    );
    assert.doesNotMatch(
      document.querySelector(".composer-active-model").textContent,
      /inference was not tested/,
    );
    await act(async () => catalogs[1].finish());
    assert.ok(
      !document.querySelector(".composer-active-model select").disabled,
    );

    await click(button("Refresh models"));
    const closingCatalog = catalogs.at(-1);
    await escape();
    assert.equal(
      closingCatalog.signal.aborted,
      true,
      "closing cancels client catalog consumption",
    );
    deferCatalog = false;
    await act(async () => closingCatalog.finish());
    await click(trigger("model"));
    assert.ok(
      !document.querySelector(".composer-active-model select").disabled,
      "reopening can obtain a fresh catalog",
    );
    rejectCatalog = true;
    await click(button("Refresh models"));
    assert.ok(document.querySelector(".composer-picker-error"));
    assert.ok(document.querySelector(".composer-active-model select").disabled);
    const failedCatalogCount = calls.filter(
      (item) => item.path === "/api/connections/models",
    ).length;
    await render();
    assert.equal(
      calls.filter((item) => item.path === "/api/connections/models").length,
      failedCatalogCount,
      "failed metadata has no automatic retry loop",
    );
    rejectCatalog = false;
    await click(button("Refresh models"));
    assert.ok(
      !document.querySelector(".composer-active-model select").disabled,
    );

    cloud.profile.allow_paid_inference = true;
    state.profile.allow_paid_inference = true;
    await act(async () => {
      await reloadOutside();
    });
    holdVerify = true;
    const beforeVerifyModels = calls.filter(
      (item) => item.path === "/api/connections/models",
    ).length;
    await change(
      document.querySelector(".composer-active-model select"),
      "saved-model",
    );
    assert.equal(typeof finishVerify, "function");
    assert.equal(
      document.querySelector("#setup-probe").dataset.ready,
      "false",
      "new requests remain blocked while selected-model verification is pending",
    );
    assert.equal(
      calls.filter((item) => item.path === "/api/connections/models").length,
      beforeVerifyModels,
      "catalog refresh cannot overlap saved-model verification",
    );
    holdVerify = false;
    await act(async () => finishVerify());
    assert.equal(
      document.querySelector("#setup-probe").dataset.ready,
      "true",
      "successful verification enables the next research request",
    );
    assert.equal(
      document.querySelector("#setup-probe").dataset.model,
      "saved-model",
    );
    assert.match(trigger("model").textContent, /saved-model/);
    assert.equal(
      calls.filter((item) => item.path === "/api/connections/test").length,
      0,
      "uses setup readiness rather than the unrelated model test route",
    );

    rejectVerify = true;
    deferCatalog = true;
    await change(
      document.querySelector(".composer-active-model select"),
      "next-model",
    );
    assert.equal(
      cloud.profile.model,
      "next-model",
      "a failed check does not roll back a confirmed model save",
    );
    assert.match(trigger("model").textContent, /next-model/);
    assert.equal(document.querySelector("#setup-probe").dataset.ready, "false");
    assert.doesNotMatch(
      document.body.textContent,
      /private diagnostic|credential marker/,
    );
    const savesBeforeRetry = calls.filter(
      (item) => item.method === "PUT",
    ).length;
    assert.equal(
      button("Retry connection check").disabled,
      true,
      "verification cannot race an active catalog request",
    );
    deferCatalog = false;
    await act(async () => catalogs.at(-1).finish());
    rejectVerify = false;
    await click(button("Retry connection check"));
    assert.equal(document.querySelector("#setup-probe").dataset.ready, "true");
    assert.equal(
      calls.filter((item) => item.method === "PUT").length,
      savesBeforeRetry,
      "a check retry never repeats the saved model mutation",
    );

    mismatchVerify = true;
    await change(
      document.querySelector(".composer-active-model select"),
      "saved-model",
    );
    assert.equal(
      document.querySelector("#setup-probe").dataset.ready,
      "false",
      "verification for a different account/model never readies this composer",
    );
    assert.notEqual(
      document.querySelector("#setup-probe").dataset.model,
      "different-model",
    );
    assert.ok(
      !setupObservations.some(
        (item) => item.ready && item.model === "different-model",
      ),
      "no intermediate render may adopt another model verification",
    );
    assert.ok(button("Retry connection check"));
    mismatchVerify = false;
    await click(button("Retry connection check"));
    assert.equal(document.querySelector("#setup-probe").dataset.ready, "true");

    rejectSave = true;
    await change(
      document.querySelector(".composer-active-model select"),
      "next-model",
    );
    assert.ok(document.querySelector(".composer-picker-error"));
    assert.doesNotMatch(document.body.textContent, /private diagnostic/);
    assert.ok(choice("Anthropic (Claude) API").disabled);
    const saves = calls.filter((item) => item.method === "PUT").length;
    await click(button("Reload saved connection"));
    assert.equal(
      calls.filter((item) => item.method === "PUT").length,
      saves,
      "recovery only reads saved state",
    );
    assert.match(
      trigger("model").textContent,
      /next-model/,
      "recovery accepts the model actually committed before the error",
    );
    assert.ok(!choice("Anthropic (Claude) API").disabled);
    rejectSave = false;
    await click(choice("Anthropic (Claude) API"));
    assert.equal(connectionsOpened, 1, "locked account opens secure setup");
    assert.equal(state.active_account_id, "locked");
    assert.equal(document.querySelector('[role="dialog"]'), null);
    await click(trigger("model"));
    assert.ok(
      button("Refresh models").disabled,
      "locked credentials cannot load provider models",
    );
    assert.ok(
      !document
        .querySelector(".composer-model-popover")
        .textContent.includes("Local defaults"),
      "required-login UI has no unauthenticated research choice",
    );
    assert.equal(
      calls.filter((item) => item.path === "/api/connections/local-defaults")
        .length,
      0,
    );
    await act(async () => {
      document
        .getElementById("outside")
        .dispatchEvent(new dom.window.Event("pointerdown", { bubbles: true }));
    });
    assert.equal(
      document.querySelector('[role="dialog"]'),
      null,
      "outside interaction closes popup",
    );
    disabled = true;
    await render();
    assert.ok(trigger("ranking").disabled && trigger("model").disabled);
    disabled = false;
    initialProfile = "custom-one";
    state.accounts = [];
    state.active_account_id = null;
    state.using_local_defaults = true;
    state.profile = { ...state.profile, provider: "none", model: "" };
    harnessKey++;
    await render();
    assert.match(
      trigger("ranking").textContent,
      /My ranking profile/,
      "remount restores an explicitly selected profile label",
    );
    assert.match(trigger("model").textContent, /Connect model/);
    await click(trigger("model"));
    assert.match(
      document.querySelector('[role="dialog"]').textContent,
      /Connect or manage providers/,
    );
    await click(button("Connect or manage providers ↗"));
    assert.equal(
      connectionsOpened,
      2,
      "without an account the popup opens secure connection setup",
    );
    assert.deepEqual(errors, [], "no React warnings");
  } finally {
    await act(async () => root.unmount());
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
    await rm(output, { recursive: true, force: true });
  }
});
