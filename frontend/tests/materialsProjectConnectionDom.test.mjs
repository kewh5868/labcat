import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

const endpoint = "/api/connections/sources/materials_project";
const keyFixture = "SYNTHETIC-WRITE-ONLY-MATERIALS-KEY";
const readiness = (status = "not_configured") => ({
  status,
  selectable: status === "ready",
  requires_credentials: true,
  verified_at: status === "ready" ? "2026-09-10T12:00:00Z" : null,
  message: "Synthetic source connection metadata.",
});
function fixture(credential = "missing") {
  const profile = {
    provider: "openai",
    model: "saved-model",
    allow_paid_inference: true,
    ollama_url: "http://localhost:11434",
  };
  return {
    configured: true,
    using_local_defaults: false,
    profile,
    credentials: {
      materials_project: credential,
      openai: "session",
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
    accounts: [
      {
        id: "saved-model-account",
        label: "My research account",
        profile,
        credential_state: "session",
      },
    ],
    active_account_id: "saved-model-account",
    source_connections: {
      materials_project: readiness(
        credential === "missing" ? "not_configured" : "verification_required",
      ),
    },
  };
}
const unlockedVault = {
  available: true,
  locked: false,
  exists: true,
  can_create: false,
  key_source: "passphrase",
};

async function environment(t, initialStatus = fixture(), options = {}) {
  const output = await mkdtemp(join(tmpdir(), "labcat-materials-key-ui-"));
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
    globals.map((name) => [
      name,
      Object.getOwnPropertyDescriptor(globalThis, name),
    ]),
  );
  for (const name of globals)
    Object.defineProperty(globalThis, name, {
      value: name === "IS_REACT_ACT_ENVIRONMENT" ? true : dom.window[name],
      configurable: true,
      writable: true,
    });
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { ConnectionsProvider, ConnectionsPanel, useConnections } =
    await import(pathToFileURL(join(output, "Connections.js")).href);
  const { default: MaterialsProjectConnection } = await import(
    pathToFileURL(join(output, "MaterialsProjectConnection.js")).href
  );
  dom.window.HTMLElement.prototype.scrollIntoView = () => {};
  const root = createRoot(document.getElementById("root"));
  const status = structuredClone(initialStatus),
    calls = [],
    errors = [],
    states = [];
  let revealCount = 0;
  const changed = (state) => states.push(state);
  t.mock.method(console, "error", (...args) => errors.push(args.join(" ")));
  t.mock.method(globalThis, "fetch", async (path, request = {}) => {
    const body = request.body ? JSON.parse(request.body) : null;
    calls.push({ path, body, method: request.method ?? "GET" });
    if (path === "/api/session")
      return Response.json({ csrf_token: "SYNTHETIC-CSRF-AT-LEAST-20" });
    if (path === "/api/connections") {
      assert.equal(
        request.method ?? "GET",
        "GET",
        "source changes must never write the model profile",
      );
      return Response.json(status);
    }
    if (path === endpoint) {
      assert.equal(request.method, "PUT");
      if (options.save) {
        const response = await options.save(body, status);
        if (response) return response;
      }
      status.credentials.materials_project = body.forget
        ? "missing"
        : body.secret_storage;
      status.source_connections.materials_project = readiness(
        body.forget ? "not_configured" : "verification_required",
      );
      return Response.json(status);
    }
    if (path === "/api/connections/test") {
      if (body.target === "model")
        return Response.json({
          target: "model",
          status: "ok",
          message: "Synthetic model readiness.",
          billable: false,
          inference_tested: false,
        });
      assert.deepEqual(body, { target: "materials_project" });
      if (options.verify) {
        const response = await options.verify(status);
        if (response) return response;
      }
      status.source_connections.materials_project = readiness("ready");
      return Response.json({
        target: "materials_project",
        status: "ok",
        message: "Synthetic readiness only.",
        billable: false,
        inference_tested: false,
      });
    }
    if (path === "/api/connections/vault") {
      if (options.vault) {
        const response = await options.vault(body, status);
        if (response) return response;
      }
      if (body.action === "reset") {
        status.vault = {
          available: false,
          locked: false,
          exists: false,
          can_create: true,
          key_source: "unavailable",
        };
        for (const name of Object.keys(status.credentials))
          status.credentials[name] = "missing";
        for (const account of status.accounts)
          account.credential_state = "missing";
        status.source_connections.materials_project = readiness();
      } else {
        assert.ok(
          ["create", "unlock", "change_passphrase"].includes(body.action),
        );
        status.vault = { ...unlockedVault };
        for (const [name, value] of Object.entries(status.credentials))
          if (value === "locked") status.credentials[name] = "encrypted";
        for (const account of status.accounts)
          if (account.credential_state === "locked")
            account.credential_state = "encrypted";
        if (status.source_connections.materials_project.status === "locked")
          status.source_connections.materials_project = readiness(
            "verification_required",
          );
      }
      return Response.json(status);
    }
    if (path.startsWith("/api/connections/accounts/")) {
      assert.equal(request.method, "PUT");
      status.profile = structuredClone(body.profile);
      status.accounts[0].profile = structuredClone(body.profile);
      if (body.api_key || body.secret_storage === "encrypted") {
        status.accounts[0].credential_state = body.secret_storage;
        status.credentials.openai = body.secret_storage;
      }
      return Response.json(status);
    }
    if (path === "/api/connections/models")
      return Response.json({
        provider: "openai",
        models: [
          { id: "saved-model", label: "Saved model" },
          { id: "draft-model", label: "Unsaved model choice" },
        ],
        message: "Synthetic metadata only.",
        inference_tested: false,
      });
    if (path === "/api/connections/agent")
      return Response.json({
        engine: "goose",
        available: true,
        version: "test",
        tools: ["search_public_references"],
        message: "Synthetic runtime metadata.",
      });
    if (path === "/api/public-sources")
      return Response.json({
        sources: [],
        connected_sources: [
          {
            id: "materials_project",
            name: "Materials Project",
            description: "Synthetic public database.",
            homepage: "https://next-gen.materialsproject.org/",
            documentation_url: "https://next-gen.materialsproject.org/api",
            requires_credentials: true,
            kind: "materials",
            availability: status.source_connections.materials_project,
          },
        ],
      });
    if (path === "/api/source-settings")
      return Response.json({
        search_public_references: true,
        enabled_sources: [],
        materials_project_mode: "off",
        max_results_per_source: 5,
      });
    assert.fail(`Unexpected request ${path}`);
  });
  function Reload() {
    const connection = useConnections();
    return createElement(
      "button",
      { onClick: () => void connection.reload() },
      "Reload test metadata",
    );
  }
  const env = {
    dom,
    act,
    status,
    calls,
    errors,
    states,
    get revealCount() {
      return revealCount;
    },
    render: (full = false) =>
      act(async () =>
        root.render(
          createElement(
            ConnectionsProvider,
            null,
            full
              ? createElement(ConnectionsPanel)
              : createElement(MaterialsProjectConnection, {
                  onCredentialOptions: () => {
                    revealCount++;
                  },
                  onStateChange: changed,
                }),
            createElement(Reload),
          ),
        ),
      ),
    button(name) {
      const item = [...document.querySelectorAll("button")].find(
        (entry) => entry.textContent.trim() === name,
      );
      assert.ok(item, `button ${name}`);
      return item;
    },
    card: () =>
      document.querySelector('[aria-label="Materials Project connection"]'),
    key: () => env.card().querySelector('input[type="password"]'),
    remember: () => env.card().querySelector('input[type="checkbox"]'),
    submit: () => env.card().querySelector('button[type="submit"]'),
    click: (item) =>
      act(async () => {
        assert.ok(item && !item.disabled, `${item?.textContent} enabled`);
        item.dispatchEvent(
          new dom.window.MouseEvent("click", { bubbles: true }),
        );
      }),
    change: (item, value) =>
      act(async () => {
        const type =
          item.tagName === "SELECT"
            ? dom.window.HTMLSelectElement
            : dom.window.HTMLInputElement;
        Object.getOwnPropertyDescriptor(type.prototype, "value").set.call(
          item,
          value,
        );
        item.dispatchEvent(
          new dom.window.Event(item.tagName === "SELECT" ? "change" : "input", {
            bubbles: true,
          }),
        );
      }),
    flush: () =>
      act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      }),
    async close() {
      await act(async () => root.unmount());
      dom.window.close();
      for (const name of globals) {
        if (previous[name])
          Object.defineProperty(globalThis, name, previous[name]);
        else delete globalThis[name];
      }
      await rm(output, { recursive: true, force: true });
    },
  };
  return env;
}

test("source key submission clears the password while pending, verifies once and refreshes source readiness", async (t) => {
  let finishSave;
  const env = await environment(t, fixture(), {
    save: () =>
      new Promise((resolve) => {
        finishSave = resolve;
      }),
  });
  const originalModel = structuredClone({
    profile: env.status.profile,
    accounts: env.status.accounts,
    active_account_id: env.status.active_account_id,
  });
  try {
    await env.render();
    assert.equal(env.key().type, "password");
    assert.equal(env.key().autocomplete, "off");
    assert.equal(
      env.remember().checked,
      false,
      "remembering is optional, not enabled by an existing model credential",
    );
    assert.equal(env.submit().disabled, true);
    await env.change(env.key(), keyFixture);
    assert.equal(env.states.at(-1).dirty, true);
    await env.act(async () => {
      const form = env.card().querySelector("form");
      form.dispatchEvent(
        new env.dom.window.Event("submit", { bubbles: true, cancelable: true }),
      );
      form.dispatchEvent(
        new env.dom.window.Event("submit", { bubbles: true, cancelable: true }),
      );
    });
    assert.equal(
      env.key().value,
      "",
      "write-only input clears before the network completes",
    );
    assert.equal(env.submit().disabled, true);
    assert.equal(env.states.at(-1).busy, true);
    assert.deepEqual(
      env.calls
        .filter((call) => call.path === endpoint)
        .map((call) => call.body),
      [{ secret_storage: "session", api_key: keyFixture }],
    );
    assert.equal(
      env.calls.filter((call) => call.path === "/api/connections/test").length,
      0,
      "verification waits for the source-only save",
    );
    await env.act(async () => finishSave());
    await env.flush();
    assert.equal(
      env.calls.filter((call) => call.path === "/api/connections/test").length,
      1,
    );
    assert.match(
      env.card().querySelector(".selected-source-heading").textContent,
      /Verified/,
    );
    assert.match(
      env.card().querySelector('[role="status"]').textContent,
      /Verified/,
    );
    assert.deepEqual(
      {
        profile: env.status.profile,
        accounts: env.status.accounts,
        active_account_id: env.status.active_account_id,
      },
      originalModel,
    );
    assert.equal(env.dom.window.localStorage.length, 0);
    assert.equal(env.dom.window.sessionStorage.length, 0);
    assert.doesNotMatch(document.body.textContent, /SYNTHETIC-WRITE-ONLY/);
    assert.deepEqual(env.states.at(-1), { dirty: false, busy: false });
    assert.deepEqual(env.errors, []);
  } finally {
    await env.close();
  }
});

for (const failure of ["save", "verification"])
  test(`failed ${failure} clears the key, hides reflected secrets and refreshes metadata without retry`, async (t) => {
    const options = {
      [failure === "save" ? "save" : "verify"]: () =>
        Response.json({ detail: { input: keyFixture } }, { status: 422 }),
    };
    const env = await environment(t, fixture(), options);
    try {
      await env.render();
      await env.change(env.key(), keyFixture);
      await env.click(env.submit());
      assert.equal(env.key().value, "");
      assert.match(
        env.card().querySelector('[role="alert"]').textContent,
        /not completed \(422\)/,
      );
      assert.doesNotMatch(document.body.textContent, /SYNTHETIC-WRITE-ONLY/);
      assert.equal(
        env.calls.filter((call) => call.path === endpoint).length,
        1,
        "credential writes are never automatically retried",
      );
      assert.equal(
        env.calls.filter((call) => call.path === "/api/connections/test")
          .length,
        failure === "save" ? 0 : 1,
      );
      assert.equal(
        env.calls.filter((call) => call.path === "/api/connections").length,
        2,
        "uncertain operation reloads credential metadata",
      );
      assert.equal(
        env.status.credentials.materials_project,
        failure === "save" ? "missing" : "session",
      );
      assert.equal(
        env.submit().disabled,
        failure === "save",
        "a stored key can be verified again without requesting it from the user",
      );
      assert.deepEqual(env.errors, []);
    } finally {
      await env.close();
    }
  });

test("remembering a new source key requires an unlocked vault and never silently falls back to session storage", async (t) => {
  const env = await environment(t);
  try {
    await env.render();
    await env.change(env.key(), keyFixture);
    await env.click(env.remember());
    assert.equal(env.submit().disabled, true);
    assert.match(env.card().textContent, /Create or unlock your local vault/);
    await env.click(env.button("Set up secure storage"));
    assert.equal(env.revealCount, 1);
    await env.act(async () =>
      env
        .card()
        .querySelector("form")
        .dispatchEvent(
          new env.dom.window.Event("submit", {
            bubbles: true,
            cancelable: true,
          }),
        ),
    );
    assert.equal(env.calls.filter((call) => call.path === endpoint).length, 0);
    assert.equal(
      env.key().value,
      keyFixture,
      "unsubmitted credentials remain editable while the vault is configured",
    );
    env.status.vault = { ...unlockedVault };
    await env.click(env.button("Reload test metadata"));
    assert.equal(
      env.remember().checked,
      true,
      "unlocking does not silently change the requested storage choice",
    );
    await env.click(env.submit());
    assert.deepEqual(
      env.calls
        .filter((call) => call.path === endpoint)
        .map((call) => call.body),
      [{ secret_storage: "encrypted", api_key: keyFixture }],
    );
    assert.equal(env.key().value, "");
    assert.equal(env.remember().checked, true);
    assert.deepEqual(env.errors, []);
  } finally {
    await env.close();
  }
});

test("an existing source key can move between encrypted and session storage without re-entering it", async (t) => {
  const status = fixture("session");
  status.vault = { ...unlockedVault };
  const env = await environment(t, status);
  try {
    await env.render();
    await env.click(env.remember());
    await env.click(env.submit());
    assert.equal(env.status.credentials.materials_project, "encrypted");
    assert.equal(env.remember().checked, true);
    await env.click(env.remember());
    assert.match(
      env.card().textContent,
      /Saving this choice removes the saved encrypted copy/,
    );
    assert.match(env.card().textContent, /enter it again after restarting/);
    assert.equal(
      env.key().value,
      "",
      "the storage change reuses the available key",
    );
    await env.click(env.submit());
    assert.equal(env.status.credentials.materials_project, "session");
    assert.equal(env.remember().checked, false);
    assert.deepEqual(
      env.calls
        .filter((call) => call.path === endpoint)
        .map((call) => call.body),
      [{ secret_storage: "encrypted" }, { secret_storage: "session" }],
    );
    await env.click(env.submit());
    assert.equal(
      env.calls.filter((call) => call.path === endpoint).length,
      2,
      "verifying an unchanged key does not rewrite storage",
    );
    assert.equal(
      env.calls.filter((call) => call.path === "/api/connections/test").length,
      3,
    );
    assert.deepEqual(env.errors, []);
  } finally {
    await env.close();
  }
});

test("locked source keys accept explicit session overrides while saved-key use and forgetting still need unlock", async (t) => {
  const status = fixture("locked");
  status.vault = { ...unlockedVault, locked: true };
  status.source_connections.materials_project = readiness("locked");
  const env = await environment(t, status);
  try {
    await env.render();
    assert.equal(env.remember().checked, true);
    assert.equal(env.submit().disabled, true);
    await env.click(env.button("Unlock secure storage"));
    assert.equal(env.revealCount, 1);
    await env.click(env.button("Use a key for this session"));
    assert.equal(env.remember().checked, false);
    assert.equal(document.activeElement, env.key());
    assert.equal(
      env.submit().disabled,
      true,
      "a blank field cannot read a locked saved key",
    );
    await env.change(env.key(), keyFixture);
    assert.equal(env.submit().disabled, false);
    assert.match(env.card().textContent, /saved encrypted keys stay unchanged/);
    assert.doesNotMatch(
      env.card().textContent,
      /removes the saved encrypted copy/,
    );
    assert.equal(
      env.button("Forget key").disabled,
      true,
      "forgetting a locked encrypted slot requires vault access",
    );
    assert.equal(env.calls.filter((call) => call.path === endpoint).length, 0);
    await env.click(env.submit());
    assert.equal(env.status.credentials.materials_project, "session");
    assert.equal(env.status.vault.locked, true);
    assert.equal(env.key().value, "");
    assert.equal(env.button("Forget key").disabled, true);
    env.status.vault = { ...unlockedVault };
    env.status.credentials.materials_project = "encrypted";
    env.status.source_connections.materials_project = readiness(
      "verification_required",
    );
    await env.click(env.button("Reload test metadata"));
    await env.click(env.button("Forget key"));
    assert.deepEqual(
      env.calls
        .filter((call) => call.path === endpoint)
        .map((call) => call.body),
      [{ secret_storage: "session", api_key: keyFixture }, { forget: true }],
    );
    assert.equal(env.key().value, "");
    assert.equal(env.remember().checked, false);
    assert.equal(env.status.credentials.materials_project, "missing");
    assert.equal(env.status.credentials.openai, "session");
    assert.match(
      env.card().querySelector('[role="status"]').textContent,
      /key removed/,
    );
    assert.equal(env.submit().disabled, true);
    assert.deepEqual(env.errors, []);
  } finally {
    await env.close();
  }
});

test("source-card verification in Connections preserves an unsaved model selection and model API-key draft", async (t) => {
  const env = await environment(t);
  try {
    await env.render(true);
    await env.flush();
    await env.change(document.querySelector("#model-choice"), "draft-model");
    await env.change(
      document.querySelector("#provider-key"),
      "SYNTHETIC-UNSAVED-MODEL-KEY",
    );
    await env.change(env.key(), keyFixture);
    await env.click(env.submit());
    await env.flush();
    assert.equal(document.querySelector("#model-choice").value, "draft-model");
    assert.equal(
      document.querySelector("#provider-key").value,
      "SYNTHETIC-UNSAVED-MODEL-KEY",
    );
    assert.equal(env.status.profile.model, "saved-model");
    assert.equal(env.status.accounts[0].profile.model, "saved-model");
    assert.equal(env.calls.filter((call) => call.method === "PUT").length, 1);
    assert.deepEqual(env.calls.find((call) => call.method === "PUT").body, {
      secret_storage: "session",
      api_key: keyFixture,
    });
    assert.match(
      env.card().querySelector(".selected-source-heading").textContent,
      /Verified/,
    );
    assert.deepEqual(
      env.errors,
      [],
      "no nested-form or reconciliation warnings",
    );
  } finally {
    await env.close();
  }
});

for (const action of ["create", "unlock"])
  test(`vault ${action} preserves pending source and model drafts before source-only saving`, async (t) => {
    const initialStatus = fixture();
    if (action === "unlock")
      initialStatus.vault = { ...unlockedVault, locked: true };
    const env = await environment(t, initialStatus);
    const modelKey = "SYNTHETIC-UNSAVED-MODEL-KEY",
      passphrase = "SYNTHETIC-VAULT-PASSPHRASE";
    const scrolled = [];
    env.dom.window.HTMLElement.prototype.scrollIntoView = function (options) {
      scrolled.push({ element: this, options });
    };
    try {
      await env.render(true);
      await env.flush();
      await env.change(document.querySelector("#model-choice"), "draft-model");
      await env.change(document.querySelector("#provider-key"), modelKey);
      await env.change(env.key(), keyFixture);
      await env.click(env.remember());
      assert.equal(
        env.submit().disabled,
        true,
        "remembering remains blocked until the vault is ready",
      );
      await env.click(
        env.button(
          action === "create"
            ? "Set up secure storage"
            : "Unlock secure storage",
        ),
      );
      await env.flush();
      const advanced = document.querySelector(".advanced-credentials");
      assert.equal(advanced.open, true);
      assert.equal(document.activeElement, advanced.querySelector("summary"));
      assert.equal(scrolled.at(-1).element, advanced);
      await env.change(
        document.querySelector(
          action === "create" ? "#vault-passphrase" : "#vault-unlock",
        ),
        passphrase,
      );
      if (action === "create")
        await env.change(document.querySelector("#vault-confirm"), passphrase);
      await env.click(
        env.button(
          action === "create"
            ? "Create credential vault"
            : "Unlock credentials",
        ),
      );
      await env.flush();
      assert.deepEqual(
        env.calls
          .filter((call) => call.path === "/api/connections/vault")
          .map((call) => call.body),
        [{ action, passphrase }],
      );
      assert.equal(
        env.key().value,
        keyFixture,
        "preparing secure storage does not discard the pending source key",
      );
      assert.equal(
        env.remember().checked,
        true,
        "the requested secure storage preference survives vault setup",
      );
      assert.equal(
        document.querySelector("#provider-key").value,
        modelKey,
        "preparing the vault does not discard an unrelated model key draft",
      );
      assert.equal(
        document.querySelector("#model-choice").value,
        "draft-model",
      );
      assert.equal(
        [...document.querySelectorAll('input[type="password"]')].some(
          (input) => input.value === passphrase,
        ),
        false,
        "the submitted vault passphrase is cleared",
      );
      assert.equal(
        env.calls.filter((call) => call.path === endpoint).length,
        0,
        "vault preparation does not save the pending source key",
      );
      await env.click(env.submit());
      await env.flush();
      assert.deepEqual(
        env.calls
          .filter((call) => call.path === endpoint)
          .map((call) => call.body),
        [{ secret_storage: "encrypted", api_key: keyFixture }],
      );
      assert.equal(env.key().value, "");
      assert.equal(env.remember().checked, true);
      assert.equal(document.querySelector("#provider-key").value, modelKey);
      assert.equal(
        document.querySelector("#model-choice").value,
        "draft-model",
      );
      assert.equal(env.status.profile.model, "saved-model");
      assert.equal(env.status.accounts[0].profile.model, "saved-model");
      assert.equal(
        env.calls.filter((call) => call.method === "PUT").length,
        1,
        "only the source connection is saved",
      );
      assert.equal(env.dom.window.localStorage.length, 0);
      assert.equal(env.dom.window.sessionStorage.length, 0);
      assert.deepEqual(env.errors, []);
    } finally {
      await env.close();
    }
  });

function lockedFixture() {
  const status = fixture("locked");
  status.vault = { ...unlockedVault, available: false, locked: true };
  status.credentials.openai = "locked";
  status.accounts[0].credential_state = "locked";
  status.source_connections.materials_project = readiness("locked");
  return status;
}

test("unlocking remembered keys once restores model and source access without re-entering or returning API keys", async (t) => {
  let rejectPassword = true;
  const env = await environment(t, lockedFixture(), {
    vault: () =>
      rejectPassword
        ? Response.json(
            { detail: "SYNTHETIC-PRIVATE-PASSWORD" },
            { status: 422 },
          )
        : undefined,
  });
  try {
    await env.render(true);
    await env.click(env.button("Unlock saved credentials"));
    assert.equal(document.querySelector(".advanced-credentials").open, true);
    assert.match(
      document.querySelector(".vault-card").textContent,
      /without entering them again/,
    );
    assert.equal(env.key().value, "");
    assert.equal(document.querySelector("#provider-key").value, "");
    await env.change(
      document.querySelector("#vault-unlock"),
      "SYNTHETIC-PRIVATE-PASSWORD",
    );
    await env.click(env.button("Unlock credentials"));
    assert.equal(document.querySelector("#vault-unlock").value, "");
    assert.equal(env.status.vault.locked, true);
    assert.doesNotMatch(document.body.textContent, /SYNTHETIC-PRIVATE/);
    assert.equal(
      env.calls.filter((call) => call.path.endsWith("/vault")).length,
      1,
    );
    rejectPassword = false;
    await env.change(
      document.querySelector("#vault-unlock"),
      "SYNTHETIC-CORRECT-PASSWORD",
    );
    await env.click(env.button("Unlock credentials"));
    await env.flush();
    assert.equal(env.status.vault.locked, false);
    assert.equal(env.status.credentials.openai, "encrypted");
    assert.equal(env.status.credentials.materials_project, "encrypted");
    assert.equal(document.querySelector("#provider-key").value, "");
    assert.equal(env.key().value, "");
    await env.click(env.submit());
    assert.equal(
      env.calls.filter((call) => call.path === endpoint).length,
      0,
      "the saved source key is verified without resubmitting it",
    );
    await env.click(env.button("Save and test connections"));
    const saved = env.calls.find((call) =>
      call.path.startsWith("/api/connections/accounts/"),
    );
    assert.equal(saved.body.secret_storage, "encrypted");
    assert.equal(Object.hasOwn(saved.body, "api_key"), false);
    assert.equal(env.dom.window.localStorage.length, 0);
    assert.equal(env.dom.window.sessionStorage.length, 0);
    assert.deepEqual(env.errors, []);
  } finally {
    await env.close();
  }
});

for (const locked of [false, true])
  test(`vault password change ${locked ? "while locked" : "while unlocked"} requires matching confirmation, clears submitted passwords and preserves credentials`, async (t) => {
    const initial = locked ? lockedFixture() : fixture("encrypted");
    if (!locked) initial.vault = { ...unlockedVault };
    let finishChange;
    const env = await environment(t, initial, {
      vault: () =>
        new Promise((resolve) => {
          finishChange = resolve;
        }),
    });
    const current = "SYNTHETIC-CURRENT-PASSWORD",
      next = "SYNTHETIC-NEW-PASSWORD";
    try {
      await env.render(true);
      const button = env.button("Change vault password");
      assert.equal(button.disabled, true);
      await env.change(
        document.querySelector("#vault-current-password"),
        current,
      );
      await env.change(document.querySelector("#vault-new-password"), next);
      await env.change(
        document.querySelector("#vault-new-password-confirm"),
        "SYNTHETIC-MISMATCH",
      );
      assert.equal(button.disabled, true);
      await env.change(
        document.querySelector("#vault-new-password-confirm"),
        next,
      );
      await env.click(button);
      assert.equal(button.disabled, true);
      for (const id of [
        "vault-current-password",
        "vault-new-password",
        "vault-new-password-confirm",
      ])
        assert.equal(document.getElementById(id).value, "");
      assert.deepEqual(
        env.calls
          .filter((call) => call.path.endsWith("/vault"))
          .map((call) => call.body),
        [
          {
            action: "change_passphrase",
            current_passphrase: current,
            new_passphrase: next,
          },
        ],
      );
      await env.act(async () => finishChange());
      await env.flush();
      assert.equal(env.status.vault.locked, false);
      assert.equal(env.status.credentials.materials_project, "encrypted");
      assert.equal(
        env.status.credentials.openai,
        locked ? "encrypted" : "session",
      );
      assert.equal(env.status.accounts[0].profile.model, "saved-model");
      assert.match(
        document.querySelector(".connection-saved").textContent,
        /password changed/,
      );
      assert.equal(
        env.calls.filter(
          (call) => call.path === endpoint || call.path.includes("/accounts/"),
        ).length,
        0,
      );
      assert.equal(env.dom.window.localStorage.length, 0);
      assert.equal(env.dom.window.sessionStorage.length, 0);
      assert.deepEqual(env.errors, []);
    } finally {
      await env.close();
    }
  });

test("forgotten vault password reset needs confirmation, explains all credential loss and clears pending key drafts", async (t) => {
  const initial = lockedFixture();
  initial.credentials.anthropic = "session";
  const env = await environment(t, initial);
  try {
    await env.render(true);
    assert.ok(
      [...document.querySelectorAll("summary")].some(
        (item) => item.textContent === "Forgot password? Reset vault",
      ),
    );
    const reset = env.button("Reset vault and clear credentials");
    assert.equal(reset.disabled, true);
    assert.match(
      reset.closest("details").textContent,
      /encrypted and session-only credentials/,
    );
    assert.match(reset.closest("details").textContent, /account sign-ins/);
    assert.match(
      reset.closest("details").textContent,
      /projects, chats and reports are kept/,
    );
    await env.change(env.key(), keyFixture);
    await env.change(
      document.querySelector("#provider-key"),
      "SYNTHETIC-MODEL-DRAFT",
    );
    assert.equal(
      env.calls.filter((call) => call.path.endsWith("/vault")).length,
      0,
    );
    await env.click(document.querySelector(".reset-confirm input"));
    await env.click(reset);
    await env.flush();
    assert.deepEqual(
      env.calls
        .filter((call) => call.path.endsWith("/vault"))
        .map((call) => call.body),
      [{ action: "reset", confirm: true }],
    );
    assert.equal(env.status.vault.can_create, true);
    assert.ok(
      Object.values(env.status.credentials).every(
        (state) => state === "missing",
      ),
    );
    assert.equal(env.status.profile.model, "saved-model");
    assert.equal(env.status.accounts.length, 1);
    assert.ok(
      [...document.querySelectorAll('input[type="password"]')].every(
        (input) => input.value === "",
      ),
    );
    assert.match(
      document.querySelector(".connection-saved").textContent,
      /session-only credentials were cleared/,
    );
    assert.equal(
      env.calls.filter(
        (call) => call.path === endpoint || call.path.includes("/accounts/"),
      ).length,
      0,
    );
    assert.deepEqual(env.errors, []);
  } finally {
    await env.close();
  }
});

test("locked model credentials accept a new session key and keep the saved account identity", async (t) => {
  const env = await environment(t, lockedFixture());
  try {
    await env.render(true);
    const key = document.querySelector("#provider-key");
    assert.equal(key.disabled, false);
    assert.match(
      key.parentElement.textContent,
      /same or a different API key for this server session/,
    );
    await env.change(key, "SYNTHETIC-SESSION-MODEL-KEY");
    await env.click(env.button("Save API key"));
    await env.flush();
    const request = env.calls.find((call) =>
      call.path.startsWith("/api/connections/accounts/"),
    );
    assert.equal(request.path, "/api/connections/accounts/saved-model-account");
    assert.equal(request.body.secret_storage, "session");
    assert.equal(request.body.api_key, "SYNTHETIC-SESSION-MODEL-KEY");
    assert.equal(env.status.vault.locked, true);
    assert.equal(env.status.credentials.openai, "session");
    assert.equal(env.status.credentials.materials_project, "locked");
    assert.equal(key.value, "");
    assert.equal(
      env.calls.filter((call) => call.path.endsWith("/vault")).length,
      0,
    );
    assert.deepEqual(env.errors, []);
  } finally {
    await env.close();
  }
});

test("remembering an available model key uses encrypted storage without asking for the key again", async (t) => {
  const initial = fixture();
  initial.vault = { ...unlockedVault };
  const env = await environment(t, initial);
  try {
    await env.render(true);
    assert.equal(document.querySelector("#provider-key").value, "");
    assert.equal(
      document.querySelector('input[name="secret-storage"][value="encrypted"]')
        .checked,
      true,
    );
    await env.click(env.button("Save and test connections"));
    const request = env.calls.find((call) =>
      call.path.startsWith("/api/connections/accounts/"),
    );
    assert.equal(request.body.secret_storage, "encrypted");
    assert.equal(Object.hasOwn(request.body, "api_key"), false);
    assert.equal(env.status.credentials.openai, "encrypted");
    assert.deepEqual(env.errors, []);
  } finally {
    await env.close();
  }
});

test("a rejected password change clears sensitive fields, preserves the locked vault and never retries automatically", async (t) => {
  const env = await environment(t, lockedFixture(), {
    vault: () =>
      Response.json(
        { detail: "SYNTHETIC-PRIVATE-ROTATION-INPUT" },
        { status: 422 },
      ),
  });
  try {
    await env.render(true);
    await env.change(
      document.querySelector("#vault-current-password"),
      "SYNTHETIC-WRONG-PASSWORD",
    );
    await env.change(
      document.querySelector("#vault-new-password"),
      "SYNTHETIC-NEW-PASSWORD",
    );
    await env.change(
      document.querySelector("#vault-new-password-confirm"),
      "SYNTHETIC-NEW-PASSWORD",
    );
    await env.click(env.button("Change vault password"));
    assert.equal(env.status.vault.locked, true);
    assert.equal(env.status.credentials.openai, "locked");
    assert.equal(env.status.credentials.materials_project, "locked");
    assert.equal(
      env.calls.filter((call) => call.path.endsWith("/vault")).length,
      1,
    );
    assert.ok(
      [...document.querySelectorAll('input[type="password"]')].every(
        (input) => input.value === "",
      ),
    );
    assert.match(
      document.querySelector(".workspace-error").textContent,
      /not completed \(422\)/,
    );
    assert.doesNotMatch(
      document.body.textContent,
      /SYNTHETIC-PRIVATE|SYNTHETIC-WRONG|SYNTHETIC-NEW/,
    );
    assert.equal(env.button("Change vault password").disabled, true);
    assert.deepEqual(env.errors, []);
  } finally {
    await env.close();
  }
});

test("deployment-supplied vault keys show administrator guidance instead of a password-change form", async (t) => {
  const initial = lockedFixture();
  initial.vault.key_source = "environment";
  const env = await environment(t, initial);
  try {
    await env.render(true);
    assert.ok(env.button("Review credential storage"));
    assert.match(
      document.querySelector(".credential-unlock-notice").textContent,
      /administrator/,
    );
    assert.equal(document.querySelector("#vault-current-password"), null);
    assert.equal(document.querySelector("#vault-unlock"), null);
    assert.ok(
      [...document.querySelectorAll("summary")].some(
        (item) => item.textContent === "Reset credential vault",
      ),
    );
    assert.equal(document.querySelector("#provider-key").disabled, false);
    assert.deepEqual(env.errors, []);
  } finally {
    await env.close();
  }
});
