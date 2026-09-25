import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

async function compile() {
  const output = await mkdtemp(join(tmpdir(), "labcat-setup-review-dom-"));
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

async function harness(t, provider = "chatgpt", credentialState = "session") {
  const output = await compile();
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
  const { createElement, act, useState } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { ConnectionsProvider, useConnections } = await import(
    pathToFileURL(join(output, "Connections.js")).href
  );
  const { default: SetupReviewModel } = await import(
    pathToFileURL(join(output, "SetupReviewModel.js")).href
  );
  const account = {
    id: "review-account",
    label: "Research account",
    profile: {
      provider,
      model: "current-model",
      allow_paid_inference: true,
      ollama_url: "http://localhost:11434",
      aws_profile: "saved-profile",
      aws_region: "us-west-2",
    },
    credential_state: credentialState,
  };
  const state = {
    configured: true,
    using_local_defaults: false,
    profile: { ...account.profile },
    credentials: {
      materials_project: "session",
      openai: provider === "openai" ? credentialState : "missing",
      anthropic: "missing",
      kimi: "missing",
      gemini: "missing",
      deepseek: "missing",
      xai: "missing",
      openrouter: "missing",
    },
    vault: {
      available: true,
      locked: false,
      exists: true,
      can_create: false,
      key_source: "passphrase",
    },
    warnings: [],
    accounts: [account],
    active_account_id: account.id,
  };
  const controls = {
    deferCatalog: false,
    rejectCatalog: false,
    emptyCatalog: false,
    holdVerify: false,
    rejectVerify: false,
    mismatchVerify: false,
    verificationReady: true,
    rejectSave: false,
    disabled: false,
    shown: true,
  };
  const calls = [],
    verifications = [],
    catalogs = [],
    errors = [];
  let reloadOutside,
    releaseVerify,
    managed = 0;
  t.mock.method(console, "error", (...args) => errors.push(args.join(" ")));
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    const method = options.method ?? "GET",
      body = options.body ? JSON.parse(options.body) : undefined;
    calls.push({ path, method, body });
    if (path === "/api/session")
      return Response.json({ csrf_token: "REVIEW-FIXTURE-CSRF-LONG-ENOUGH" });
    if (path === "/api/connections" && method === "GET")
      return Response.json(state);
    if (path === "/api/connections/models") {
      const catalog = {
        provider: state.profile.provider,
        models: controls.emptyCatalog
          ? []
          : [
              { id: "current-model", label: "Current model" },
              { id: "next-model", label: "Next model" },
            ],
        message: "Returned fixture models; no inference was run.",
        inference_tested: false,
      };
      if (controls.rejectCatalog)
        return Response.json(
          { detail: "PRIVATE-CATALOG-DIAGNOSTIC" },
          { status: 503 },
        );
      if (controls.deferCatalog)
        return new Promise((resolve) => {
          catalogs.push({
            signal: options.signal,
            finish: () => resolve(Response.json(catalog)),
          });
        });
      return Response.json(catalog);
    }
    if (
      path === `/api/connections/accounts/${account.id}` &&
      method === "PUT"
    ) {
      assert.deepEqual(
        Object.keys(body).sort(),
        ["label", "profile", "secret_storage"],
        "saving a model never sends a credential",
      );
      assert.equal(body.label, account.label);
      assert.deepEqual(
        body.profile,
        { ...account.profile, model: body.profile.model },
        "only the model preference may change",
      );
      assert.equal(
        body.secret_storage,
        account.credential_state === "encrypted" ? "encrypted" : "session",
        "existing storage mode is preserved",
      );
      account.profile = { ...body.profile };
      state.profile = { ...body.profile };
      return controls.rejectSave
        ? Response.json({ detail: "PRIVATE-SAVE-DIAGNOSTIC" }, { status: 500 })
        : Response.json(state);
    }
    assert.fail(`Unexpected request ${method} ${path}`);
  });
  async function verify(saved) {
    verifications.push(structuredClone(saved));
    if (controls.holdVerify)
      await new Promise((resolve) => {
        releaseVerify = resolve;
      });
    if (controls.rejectVerify) throw new Error("PRIVATE-VERIFY-DIAGNOSTIC");
    return {
      version: 1,
      completed: false,
      current_step: "review",
      required: true,
      can_research: controls.verificationReady,
      model: {
        status: controls.verificationReady ? "ready" : "error",
        provider: saved.profile.provider,
        model: controls.mismatchVerify ? "another-model" : saved.profile.model,
        account_id: controls.mismatchVerify
          ? "another-account"
          : saved.active_account_id,
        message: controls.verificationReady
          ? "Selected model verified without inference."
          : "The saved model needs another connection check.",
        checked_at: controls.verificationReady ? "2026-09-11T12:00:00Z" : null,
      },
      optional: {
        compute: "local",
        aws_required: false,
        data_apis_required: false,
      },
    };
  }
  function Review() {
    const [form, setForm] = useState({ dirty: false, busy: false });
    reloadOutside = useConnections().reload;
    return createElement(
      "section",
      null,
      createElement("output", {
        id: "review-state",
        "data-busy": String(form.busy),
        "data-dirty": String(form.dirty),
      }),
      controls.shown &&
        createElement(SetupReviewModel, {
          disabled: controls.disabled,
          onStateChange: setForm,
          onVerify: verify,
          onManage: () => {
            managed++;
          },
        }),
    );
  }
  const root = createRoot(document.getElementById("root"));
  const render = () =>
    act(async () => {
      root.render(
        createElement(ConnectionsProvider, null, createElement(Review)),
      );
    });
  const button = (name) => {
    const found = [...document.querySelectorAll("button")].find(
      (item) => item.textContent.trim() === name,
    );
    assert.ok(found, `${name} exists`);
    return found;
  };
  const select = () => document.querySelector("#setup-review-model");
  const report = () => ({
    busy: document.querySelector("#review-state").dataset.busy === "true",
    dirty: document.querySelector("#review-state").dataset.dirty === "true",
  });
  const click = async (item) => {
    assert.ok(!item.disabled, `${item.textContent} is enabled`);
    await act(async () =>
      item.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })),
    );
  };
  const change = async (value) =>
    act(async () => {
      const item = select();
      Object.getOwnPropertyDescriptor(
        dom.window.HTMLSelectElement.prototype,
        "value",
      ).set.call(item, value);
      item.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
  const saves = () => calls.filter((item) => item.method === "PUT");
  t.after(async () => {
    await act(async () => root.unmount());
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
    await rm(output, { recursive: true, force: true });
    assert.deepEqual(
      errors,
      [],
      "review model actions produce no React errors",
    );
  });
  await render();
  return {
    act,
    account,
    state,
    controls,
    calls,
    verifications,
    catalogs,
    render,
    button,
    select,
    report,
    click,
    change,
    saves,
    reload: () =>
      act(async () => {
        await reloadOutside();
      }),
    resolveVerification: () => act(async () => releaseVerify()),
    managed: () => managed,
  };
}

test("review model changes preserve ChatGPT session credentials and serialize save with verification", async (t) => {
  const h = await harness(t);
  assert.equal(
    document.querySelector('label[for="setup-review-model"]').textContent,
    "Active model",
  );
  assert.equal(h.select().value, "current-model");
  assert.equal(h.select().disabled, false);
  assert.equal(
    h.verifications.length,
    0,
    "catalog discovery does not run verification",
  );
  assert.equal(h.saves().length, 0);
  h.controls.holdVerify = true;
  await h.change("next-model");
  assert.equal(h.saves().length, 1);
  assert.equal(
    h.verifications[0].profile.model,
    "next-model",
    "verification receives the saved selection",
  );
  assert.equal(
    h.report().busy,
    true,
    "parent can disable Finish until verification completes",
  );
  assert.equal(h.select().disabled, true);
  await h.change("current-model");
  assert.equal(
    h.saves().length,
    1,
    "a second change cannot race pending verification",
  );
  h.controls.holdVerify = false;
  await h.resolveVerification();
  assert.deepEqual(h.report(), { busy: false, dirty: false });
  assert.equal(h.select().value, "next-model");
  assert.equal(h.select().disabled, false);
  assert.deepEqual(h.state.credentials, {
    materials_project: "session",
    openai: "missing",
    anthropic: "missing",
    kimi: "missing",
    gemini: "missing",
    deepseek: "missing",
    xai: "missing",
    openrouter: "missing",
  });
  assert.equal(h.account.credential_state, "session");
  assert.equal(window.localStorage.length, 0);
  assert.equal(window.sessionStorage.length, 0);
});

test("review model failure recovery retains encrypted credentials and does not repeat a confirmed save", async (t) => {
  const h = await harness(t, "openai", "encrypted");
  h.controls.rejectVerify = true;
  await h.change("next-model");
  assert.equal(
    h.select().value,
    "next-model",
    "failed verification retains the confirmed model save",
  );
  assert.deepEqual(
    h.report(),
    { busy: false, dirty: true },
    "parent must not finish with a failed check",
  );
  assert.doesNotMatch(document.body.textContent, /PRIVATE-/);
  const saveCount = h.saves().length;
  h.controls.rejectVerify = false;
  await h.click(h.button("Retry connection check"));
  assert.equal(
    h.saves().length,
    saveCount,
    "retry checks the saved account without resaving it",
  );
  assert.deepEqual(h.report(), { busy: false, dirty: false });
  h.controls.mismatchVerify = true;
  await h.change("current-model");
  assert.deepEqual(
    h.report(),
    { busy: false, dirty: true },
    "another account or model verification cannot mark this selection ready",
  );
  h.controls.mismatchVerify = false;
  await h.click(h.button("Retry connection check"));
  h.controls.verificationReady = false;
  await h.change("next-model");
  assert.deepEqual(
    h.report(),
    { busy: false, dirty: true },
    "a completed negative check also keeps Finish gated",
  );
  h.controls.verificationReady = true;
  await h.click(h.button("Retry connection check"));
  h.controls.rejectSave = true;
  await h.change("current-model");
  assert.equal(
    h.state.profile.model,
    "current-model",
    "simulate a committed write followed by a failed response",
  );
  assert.equal(h.select().disabled, true);
  assert.deepEqual(h.report(), { busy: false, dirty: true });
  assert.doesNotMatch(document.body.textContent, /PRIVATE-/);
  const uncertainSaveCount = h.saves().length;
  h.controls.rejectSave = false;
  await h.click(h.button("Reload saved connection"));
  assert.equal(
    h.saves().length,
    uncertainSaveCount,
    "uncertain save recovery only reloads state",
  );
  assert.equal(h.select().value, "current-model");
  assert.equal(h.account.credential_state, "encrypted");
});

test("review catalogs discard stale credential responses and recover from unavailable or empty lists", async (t) => {
  const h = await harness(t);
  h.controls.deferCatalog = true;
  await h.click(h.button("Refresh models"));
  const stale = h.catalogs.at(-1);
  assert.equal(h.select().disabled, true);
  assert.equal(
    h.report().busy,
    true,
    "parent cannot finish setup while account metadata is loading",
  );
  assert.equal(
    h.button("Change connection").disabled,
    true,
    "connection management cannot race metadata loading",
  );
  h.account.credential_state = "encrypted";
  await h.reload();
  assert.equal(
    stale.signal.aborted,
    true,
    "changed credentials invalidate the old lookup even for the same account and model",
  );
  assert.equal(h.catalogs.length, 2);
  await h.act(async () => stale.finish());
  assert.equal(
    h.select().disabled,
    true,
    "late results cannot populate the replacement connection",
  );
  h.controls.deferCatalog = false;
  await h.act(async () => h.catalogs.at(-1).finish());
  assert.equal(h.select().disabled, false);
  h.controls.rejectCatalog = true;
  await h.click(h.button("Refresh models"));
  assert.equal(h.select().disabled, true);
  assert.equal(
    h.select().value,
    "current-model",
    "catalog outage keeps the saved model visible",
  );
  assert.doesNotMatch(document.body.textContent, /PRIVATE-/);
  const failedReads = h.calls.filter(
    (item) => item.path === "/api/connections/models",
  ).length;
  await h.render();
  assert.equal(
    h.calls.filter((item) => item.path === "/api/connections/models").length,
    failedReads,
    "catalog failure has no automatic retry loop",
  );
  h.controls.rejectCatalog = false;
  h.controls.emptyCatalog = true;
  await h.click(h.button("Refresh models"));
  assert.equal(h.select().value, "current-model");
  assert.equal(h.select().disabled, true);
  h.controls.emptyCatalog = false;
  await h.click(h.button("Refresh models"));
  assert.equal(h.select().disabled, false);
  h.controls.deferCatalog = true;
  h.controls.rejectVerify = true;
  await h.change("next-model");
  assert.equal(
    h.button("Retry connection check").disabled,
    true,
    "verification cannot race the refreshed account catalog",
  );
  assert.deepEqual(h.report(), { busy: true, dirty: true });
  h.controls.deferCatalog = false;
  await h.act(async () => h.catalogs.at(-1).finish());
  h.controls.rejectVerify = false;
  await h.click(h.button("Retry connection check"));
  assert.deepEqual(h.report(), { busy: false, dirty: false });
  h.controls.deferCatalog = true;
  await h.click(h.button("Refresh models"));
  const closing = h.catalogs.at(-1);
  h.controls.shown = false;
  await h.render();
  assert.equal(
    closing.signal.aborted,
    true,
    "leaving review cancels consumption of its catalog",
  );
  await h.act(async () => closing.finish());
});

test("review keeps connection management reachable and cannot choose models without credentials", async (t) => {
  const h = await harness(t, "chatgpt", "missing");
  assert.equal(h.select().disabled, true);
  assert.equal(
    h.calls.filter((item) => item.path === "/api/connections/models").length,
    0,
    "signed-out review does not start model discovery",
  );
  await h.click(h.button("Change connection"));
  assert.equal(h.managed(), 1);
  assert.equal(
    h.saves().length,
    0,
    "opening connection management does not change settings",
  );
  h.account.credential_state = "locked";
  await h.reload();
  assert.equal(h.select().disabled, true);
  assert.equal(
    h.calls.filter((item) => item.path === "/api/connections/models").length,
    0,
    "locked credentials never start discovery",
  );
  h.account.credential_state = "session";
  await h.reload();
  assert.equal(h.select().disabled, false);
  await h.change("not-a-provider-model");
  assert.equal(
    h.saves().length,
    0,
    "only returned model identifiers can be selected",
  );
  h.controls.disabled = true;
  await h.render();
  assert.equal(h.select().disabled, true);
  assert.equal(h.button("Change connection").disabled, true);
  await h.change("next-model");
  assert.equal(
    h.saves().length,
    0,
    "parent-disabled controls cannot mutate model preferences",
  );
});
