import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

async function environment() {
  const output = await mkdtemp(join(tmpdir(), "labcat-model-onboarding-"));
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
  const root = createRoot(document.getElementById("root"));
  const { ConnectionsProvider, ConnectionsPanel } = await import(
    pathToFileURL(join(output, "Connections.js")).href
  );
  return {
    dom,
    act,
    render: (props = {}) =>
      act(async () =>
        root.render(
          createElement(
            ConnectionsProvider,
            null,
            createElement(ConnectionsPanel, { section: "model", ...props }),
          ),
        ),
      ),
    button(name) {
      const item = [...document.querySelectorAll("button")].find(
        (entry) => entry.textContent === name,
      );
      assert.ok(item, name);
      return item;
    },
    click: (item) =>
      act(async () => {
        assert.ok(item && !item.disabled);
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
      for (const key of globals) {
        if (previous[key])
          Object.defineProperty(globalThis, key, previous[key]);
        else delete globalThis[key];
      }
      await rm(output, { recursive: true, force: true });
    },
  };
}
const baseProfile = {
  provider: "none",
  model: "",
  allow_paid_inference: false,
  ollama_url: "http://localhost:11434",
  aws_profile: "",
  aws_region: "",
};
const baseStatus = () => ({
  configured: false,
  using_local_defaults: true,
  profile: { ...baseProfile },
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

test("new ChatGPT connection starts browser sign-in in one action, retries safely and loads models only after confirmation", async (t) => {
  const env = await environment();
  let status = baseStatus(),
    complete = false,
    flow = 0;
  const calls = [];
  const authorize = () =>
    `https://auth.openai.com/oauth/authorize?${new URLSearchParams({ client_id: "app_EMoamEEZ73f0CkXaXp7hrann", redirect_uri: "http://localhost:1455/auth/callback", response_type: "code", code_challenge_method: "S256", state: `SYNTHETIC_state_for_flow_${flow}`, code_challenge: "SYNTHETIC_challenge_1234567890" })}`;
  const timeout = env.dom.window.setTimeout.bind(env.dom.window);
  t.mock.method(env.dom.window, "setTimeout", (callback, delay) =>
    delay === 2000 ? 999999 : timeout(callback, delay),
  );
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({ path, body, method: options.method });
    if (path === "/api/session")
      return Response.json({ csrf_token: "SYNTHETIC-CSRF-AT-LEAST-20" });
    if (path === "/api/connections") return Response.json(status);
    if (path === "/api/connections/accounts") {
      assert.equal(body.label, "ChatGPT");
      assert.equal(body.profile.model, "");
      assert.equal(body.profile.allow_paid_inference, false);
      assert.equal(body.secret_storage, "session");
      const account = {
        id: "new-chatgpt",
        label: body.label,
        profile: body.profile,
        credential_state: "missing",
      };
      status = {
        ...status,
        configured: true,
        using_local_defaults: false,
        accounts: [account],
        active_account_id: account.id,
        profile: body.profile,
      };
      return Response.json(status);
    }
    if (path.endsWith("/login")) {
      flow++;
      return Response.json({
        flow_id: `flow-${flow}`,
        status: "pending",
        method: "browser",
        verification_url: authorize(),
        user_code: null,
      });
    }
    if (path.endsWith("/cancel"))
      return Response.json({
        flow_id: `flow-${flow}`,
        status: "cancelled",
        method: "browser",
        user_code: null,
      });
    if (path.endsWith("/poll")) {
      if (complete) status.accounts[0].credential_state = "session";
      return Response.json({
        flow_id: `flow-${flow}`,
        status: complete ? "complete" : "pending",
        method: "browser",
        user_code: null,
        verification_url: authorize(),
      });
    }
    if (path === "/api/connections/models") {
      assert.equal(status.accounts[0].credential_state, "session");
      return Response.json({
        provider: "chatgpt",
        models: [{ id: "returned-small", label: "Returned small model" }],
        message: "Provider model metadata.",
        inference_tested: false,
      });
    }
    if (path === "/api/connections/accounts/new-chatgpt") {
      status.profile = body.profile;
      status.accounts[0].profile = body.profile;
      return Response.json(status);
    }
    if (path === "/api/connections/test")
      return Response.json({
        target: "model",
        status: "ok",
        message: "Readiness only.",
        billable: false,
        inference_tested: false,
      });
    assert.fail(`Unexpected request ${path}`);
  });
  try {
    await env.render({ onboarding: true });
    assert.equal(document.querySelector(".advanced-credentials").open, false);
    assert.equal(
      document.querySelector(".vault-card").closest("details"),
      document.querySelector(".advanced-credentials"),
    );
    assert.equal(
      document.querySelector('input[name="secret-storage"]:checked').value,
      "session",
    );
    assert.equal(document.querySelector("#saved-model-account"), null);
    await env.change(document.querySelector("#model-provider"), "chatgpt");
    assert.equal(document.querySelector("#model-account-name"), null);
    assert.equal(document.querySelector(".model-advanced").open, false);
    assert.equal(
      document.querySelector(".agent-device-prerequisite"),
      null,
      "new connections do not require device-code settings",
    );
    await env.click(env.button("Sign in with ChatGPT"));
    assert.equal(status.accounts.length, 1);
    assert.equal(document.querySelector(".agent-device-code"), null);
    assert.equal(document.querySelector(".agent-device-prerequisite"), null);
    assert.equal(
      document.querySelector(".agent-device-flow a").href,
      authorize(),
    );
    assert.match(
      document.querySelector(".agent-device-flow").textContent,
      /Keep Labcat running/,
    );
    assert.equal(
      calls.filter(({ path }) => path.endsWith("/models")).length,
      0,
    );
    assert.equal(document.querySelector("#model-choice").disabled, true);
    assert.equal(
      document.querySelector("#model-provider").value,
      "chatgpt",
      "provider choice remains discoverable after starting sign-in",
    );
    const firstUrl = authorize();
    await env.click(env.button("Start new sign-in"));
    assert.equal(
      document.querySelector(".agent-device-flow a").href,
      authorize(),
    );
    assert.notEqual(authorize(), firstUrl);
    assert.ok(calls.some(({ path }) => path.endsWith("/flow-1/cancel")));
    assert.equal(
      status.accounts[0].credential_state,
      "missing",
      "new authorization request is not completed login",
    );
    complete = true;
    await env.click(env.button("Check sign-in status"));
    assert.equal(
      calls.filter(({ path }) => path.endsWith("/models")).length,
      1,
    );
    assert.ok(
      [...document.querySelector("#model-choice").options].some(
        (item) => item.value === "returned-small",
      ),
    );
    assert.equal(
      status.profile.model,
      "",
      "automatic discovery does not choose a model",
    );
    await env.change(document.querySelector("#model-choice"), "returned-small");
    await env.click(env.button("Save and test connections"));
    assert.equal(status.accounts.length, 1);
    assert.equal(status.accounts[0].label, "ChatGPT");
    assert.equal(status.profile.model, "returned-small");
    assert.equal(status.profile.allow_paid_inference, false);
    assert.ok(!calls.some(({ path }) => /research|messages/.test(path)));
  } finally {
    await env.close();
  }
});

test("unlock loads models automatically and switching accounts discards stale results without loops", async (t) => {
  const env = await environment();
  const a = {
    id: "account-a",
    label: "Existing named account",
    profile: { ...baseProfile, provider: "openai", model: "old-saved-model" },
    credential_state: "locked",
  };
  const b = {
    id: "account-b",
    label: "Anthropic API connection",
    profile: { ...baseProfile, provider: "anthropic" },
    credential_state: "session",
  };
  let status = {
    ...baseStatus(),
    configured: true,
    using_local_defaults: false,
    profile: a.profile,
    accounts: [a, b],
    active_account_id: a.id,
    vault: {
      available: true,
      locked: true,
      exists: true,
      can_create: false,
      key_source: "passphrase",
    },
  };
  const calls = [];
  let resolveOld,
    oldSignal,
    models = 0,
    unlockAttempts = 0;
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    calls.push(path);
    if (path === "/api/session")
      return Response.json({ csrf_token: "SYNTHETIC-CSRF-AT-LEAST-20" });
    if (path === "/api/connections") return Response.json(status);
    if (path === "/api/connections/vault") {
      unlockAttempts++;
      if (unlockAttempts === 1)
        return Response.json(
          { detail: "SYNTHETIC-VAULT-PASSPHRASE" },
          { status: 422 },
        );
      a.credential_state = "encrypted";
      status.vault.locked = false;
      return Response.json(status);
    }
    if (path === "/api/connections/accounts/account-b/select") {
      status = { ...status, profile: b.profile, active_account_id: b.id };
      return Response.json(status);
    }
    if (path === "/api/connections/models") {
      models++;
      if (models === 1) {
        oldSignal = options.signal;
        return new Promise((resolve) => {
          resolveOld = resolve;
        });
      }
      return Response.json({
        provider: "anthropic",
        models: [
          { id: "correct-new-model", label: "Correct current account model" },
        ],
        message: "Test model metadata.",
        inference_tested: false,
      });
    }
    assert.fail(`Unexpected request ${path}`);
  });
  try {
    await env.render();
    assert.equal(models, 0, "locked credentials cannot fetch model metadata");
    assert.equal(
      document.querySelector(".advanced-credentials").open,
      true,
      "required unlock controls are revealed automatically",
    );
    assert.ok(document.querySelector(".credential-unlock-notice"));
    assert.equal(
      document.querySelector("#vault-unlock").closest("form"),
      null,
      "Enter in the vault does not submit connection settings",
    );
    assert.equal(document.querySelector("#saved-model-account"), null);
    assert.match(
      document.querySelector('#model-provider option[value="anthropic"]')
        .textContent,
      /Anthropic/,
    );
    const advanced = document.querySelector(".advanced-credentials");
    await env.click(advanced.querySelector("summary"));
    await env.flush();
    assert.equal(advanced.open, false);
    let revealed = false;
    advanced.scrollIntoView = () => {
      revealed = true;
    };
    await env.click(env.button("Review saved credentials"));
    await env.flush();
    assert.equal(advanced.open, true);
    assert.equal(revealed, true);
    assert.equal(document.activeElement, advanced.querySelector("summary"));
    await env.change(
      document.querySelector("#vault-unlock"),
      "SYNTHETIC-VAULT-PASSPHRASE",
    );
    await env.click(env.button("Unlock credentials"));
    assert.equal(models, 0);
    assert.equal(advanced.open, true);
    assert.equal(
      document.querySelector("#vault-unlock").value,
      "",
      "failed unlock clears the submitted passphrase",
    );
    assert.match(
      document.querySelector(".workspace-error").textContent,
      /not completed/,
    );
    assert.doesNotMatch(
      document.body.textContent,
      /SYNTHETIC-VAULT-PASSPHRASE/,
    );
    await env.change(
      document.querySelector("#vault-unlock"),
      "SYNTHETIC-VAULT-PASSPHRASE",
    );
    await env.click(env.button("Unlock credentials"));
    assert.equal(models, 1);
    assert.equal(document.querySelector(".credential-unlock-notice"), null);
    assert.equal(document.querySelector("#vault-unlock"), null);
    assert.equal(
      document.querySelector('input[name="secret-storage"]:checked').value,
      "encrypted",
    );
    assert.equal(document.querySelector("#model-choice").disabled, true);
    await env.change(document.querySelector("#model-provider"), "anthropic");
    assert.equal(models, 2);
    assert.equal(oldSignal.aborted, true);
    resolveOld(
      Response.json({
        provider: "openai",
        models: [{ id: "stale-model", label: "Stale wrong-account model" }],
        message: "Old request.",
        inference_tested: false,
      }),
    );
    await env.flush();
    assert.deepEqual(
      [...document.querySelector("#model-choice").options].map(
        (item) => item.value,
      ),
      ["", "correct-new-model"],
    );
    await env.flush();
    assert.equal(models, 2, "settling renders do not repeat discovery");
    assert.equal(
      b.label,
      "Anthropic API connection",
      "display cleanup does not rewrite stored account metadata",
    );
    assert.equal(a.label, "Existing named account");
    assert.equal(a.profile.model, "old-saved-model");
    assert.equal(status.profile.allow_paid_inference, false);
    assert.equal(
      calls.filter((path) => path === "/api/connections/accounts").length,
      0,
      "existing identities are retained",
    );
  } finally {
    await env.close();
  }
});

test("sign-in deployment failures explain the installation fix without vault advice or a false pending challenge", async (t) => {
  const env = await environment();
  const account = {
    id: "test-chatgpt",
    label: "ChatGPT",
    profile: { ...baseProfile, provider: "chatgpt" },
    credential_state: "missing",
  };
  const status = {
    ...baseStatus(),
    configured: true,
    using_local_defaults: false,
    profile: account.profile,
    accounts: [account],
    active_account_id: account.id,
  };
  t.mock.method(globalThis, "fetch", async (path) => {
    if (path === "/api/session")
      return Response.json({ csrf_token: "SYNTHETIC-CSRF-AT-LEAST-20" });
    if (path === "/api/connections") return Response.json(status);
    if (path.endsWith("/login"))
      return Response.json(
        {
          detail: {
            code: "chatgpt_storage_unavailable",
            message: "TEST_PRIVATE_ACCESS_TOKEN",
          },
        },
        { status: 503 },
      );
    assert.fail(`Unexpected request ${path}`);
  });
  try {
    await env.render();
    await env.click(env.button("Sign in with ChatGPT"));
    const error = document.querySelector('.agent-sign-in [role="alert"]');
    assert.match(
      error.textContent,
      /protected temporary storage.*Docker launcher/,
    );
    assert.doesNotMatch(
      error.textContent,
      /vault passphrase|TEST_PRIVATE|Reload the saved connection|challenge is retained/,
    );
    assert.equal(document.querySelector(".agent-device-code"), null);
    assert.equal(
      document.querySelector(".agent-sign-in .credential-badge"),
      null,
      "failed setup does not show Connected",
    );
  } finally {
    await env.close();
  }
});

test("advanced credentials are collapsed after reconnecting an unlocked vault and saving a key keeps encrypted storage", async (t) => {
  const env = await environment();
  const profile = { ...baseProfile, provider: "openai" };
  const account = {
    id: "saved-account",
    label: "Preserved custom name",
    profile,
    credential_state: "encrypted",
  };
  const status = {
    ...baseStatus(),
    configured: true,
    using_local_defaults: false,
    profile,
    accounts: [account],
    active_account_id: account.id,
    credentials: { ...baseStatus().credentials, openai: "encrypted" },
    vault: {
      available: true,
      locked: false,
      exists: true,
      can_create: false,
      key_source: "passphrase",
    },
  };
  const mutations = [];
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    if (path === "/api/session")
      return Response.json({ csrf_token: "SYNTHETIC-CSRF-AT-LEAST-20" });
    if (path === "/api/connections") return Response.json(status);
    if (path === "/api/connections/models")
      return Response.json({
        provider: "openai",
        models: [],
        message: "Synthetic metadata only.",
        inference_tested: false,
      });
    if (path === "/api/connections/accounts/saved-account") {
      mutations.push(JSON.parse(options.body));
      return Response.json(status);
    }
    assert.fail(`Unexpected request ${path}`);
  });
  try {
    await env.render();
    const advanced = document.querySelector(".advanced-credentials");
    assert.equal(advanced.open, false);
    assert.equal(
      advanced.querySelector("summary").textContent,
      "Advanced credential options",
    );
    assert.equal(document.querySelector(".credential-unlock-notice"), null);
    assert.equal(
      advanced.querySelector('input[name="secret-storage"]:checked').value,
      "encrypted",
    );
    await env.click(advanced.querySelector("summary"));
    await env.flush();
    assert.equal(
      advanced.open,
      true,
      "native details disclosure opens from its summary",
    );
    assert.match(
      advanced.textContent,
      /credentials are kept out of chat and session history/,
    );
    assert.equal(
      document.querySelectorAll('input[name="secret-storage"]').length,
      2,
      "only session memory and encrypted vault choices exist",
    );
    await env.change(
      document.querySelector("#provider-key"),
      "SYNTHETIC-REPLACEMENT-KEY",
    );
    await env.click(env.button("Save API key"));
    assert.deepEqual(mutations, [
      {
        label: "Preserved custom name",
        profile,
        secret_storage: "encrypted",
        api_key: "SYNTHETIC-REPLACEMENT-KEY",
      },
    ]);
    assert.equal(document.querySelector("#provider-key").value, "");
    assert.doesNotMatch(document.body.textContent, /SYNTHETIC-REPLACEMENT-KEY/);
    assert.equal(env.dom.window.localStorage.length, 0);
    assert.equal(env.dom.window.sessionStorage.length, 0);
    assert.equal(status.vault.locked, false);
    assert.equal(account.credential_state, "encrypted");
    await env.click(advanced.querySelector("summary"));
    await env.flush();
    assert.equal(advanced.open, false, "user can collapse advanced controls");
  } finally {
    await env.close();
  }
});

test("Connections groups the Materials Project card with research databases before advanced credentials without saving on disclosure", async (t) => {
  const env = await environment();
  const status = baseStatus();
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    calls.push({ path, method: options.method });
    const responses = {
      "/api/connections": status,
      "/api/connections/agent": {
        engine: "goose",
        available: true,
        version: "TEST",
        tools: ["search_public_references", "generate_ranked_report"],
        message: "Synthetic runtime metadata only.",
      },
      "/api/public-sources": { sources: [] },
      "/api/source-settings": {
        search_public_references: false,
        enabled_sources: [],
        materials_project_mode: "auto",
        max_results_per_source: 5,
      },
    };
    assert.ok(Object.hasOwn(responses, path), path);
    return Response.json(responses[path]);
  });
  try {
    await env.render({ section: "all" });
    assert.deepEqual(
      [...document.querySelectorAll(".connections-page h2")].map(
        (item) => item.textContent,
      ),
      [
        "Goose research agent.",
        "Language model provider",
        "Supported research databases.",
        "Choose how to remember credentials.",
        "Choose whether to remember keys.",
      ],
    );
    const sourceCard = document.querySelector(
      '[aria-label="Materials Project connection"]',
    );
    assert.equal(
      sourceCard.querySelector("h3").textContent,
      "Materials Project",
    );
    assert.ok(
      sourceCard.closest(".public-sources-panel"),
      "the source credential card is inside the database registry",
    );
    assert.equal(
      sourceCard.querySelectorAll('input[type="password"]').length,
      1,
    );
    assert.equal(
      sourceCard.querySelector("form").parentElement,
      sourceCard,
      "the source form is independent of the model form",
    );
    const advanced = document.querySelector(".advanced-credentials");
    assert.equal(advanced.open, false);
    assert.equal(
      document.querySelector(".storage-options").closest("details"),
      advanced,
    );
    assert.equal(
      document.querySelector(".vault-card").closest("details"),
      advanced,
    );
    await env.click(advanced.querySelector("summary"));
    await env.flush();
    assert.equal(advanced.open, true);
    assert.ok(
      calls.every(({ method }) => method === undefined || method === "GET"),
      "opening options does not save or initialize a vault",
    );
    assert.equal(
      document.querySelector('input[name="secret-storage"]:checked').value,
      "session",
    );
  } finally {
    await env.close();
  }
});
