import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

async function environment() {
  const output = await mkdtemp(join(tmpdir(), "labcat-provider-picker-"));
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

const providers = [
  "chatgpt",
  "openai",
  "anthropic",
  "kimi",
  "bedrock",
  "gemini",
  "deepseek",
  "xai",
  "openrouter",
];
const providerPicker = () => document.querySelector("#model-provider");
const consent = () => document.querySelector(".cloud-consent input");
const account = (
  provider,
  id = `${provider}-account`,
  credential = "session",
) => ({
  id,
  label: `Existing ${provider} connection`,
  profile: {
    ...baseProfile,
    provider,
    model: `${provider}-saved-model`,
    allow_paid_inference: true,
  },
  credential_state: credential,
});
const stateWith = (accounts, active = accounts[0]) => ({
  ...baseStatus(),
  configured: true,
  using_local_defaults: false,
  accounts,
  profile: active.profile,
  active_account_id: active.id,
});
const catalog = (provider) => ({
  provider,
  models: [
    { id: `${provider}-saved-model`, label: `Returned ${provider} model` },
  ],
  message: "Synthetic provider metadata.",
  inference_tested: false,
});
function assertNoSavedAccountControls() {
  assert.equal(document.querySelector("#saved-model-account"), null);
  assert.equal(document.querySelector("#model-account-name"), null);
  assert.ok(
    ![...document.querySelectorAll("button")].some((item) =>
      /^(Add connection|Delete connection|Remove connection)$/.test(
        item.textContent.trim(),
      ),
    ),
  );
}

test("a connected ChatGPT account still exposes every provider, and browsing unsaved providers retains its login without leaking draft keys", async (t) => {
  const env = await environment();
  const chatgpt = account("chatgpt");
  const status = stateWith([chatgpt]);
  const before = structuredClone(status);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    calls.push({ path, method: options.method ?? "GET", body: options.body });
    if (path === "/api/session")
      return Response.json({ csrf_token: "SYNTHETIC-CSRF-AT-LEAST-20" });
    if (path === "/api/connections") return Response.json(status);
    if (path === "/api/connections/models")
      return Response.json(catalog("chatgpt"));
    if (path === "/api/connections/aws-profiles")
      return Response.json({
        profiles: ["test-profile"],
        regions: ["us-east-1"],
        setup: {
          commands: [],
          documentation_url:
            "https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html",
          message: "Synthetic profile metadata.",
        },
      });
    assert.fail(`Unexpected request ${path}`);
  });
  try {
    await env.render();
    assert.equal(providerPicker().value, "chatgpt");
    assert.deepEqual(
      [...providerPicker().options].map((option) => option.value).sort(),
      [...providers].sort(),
    );
    assertNoSavedAccountControls();
    assert.ok(
      document.querySelector(".agent-sign-in"),
      "the existing account sign-in/logout component is retained",
    );
    for (const provider of providers.filter((value) => value !== "chatgpt")) {
      await env.change(providerPicker(), provider);
      assert.equal(providerPicker().value, provider);
      assert.equal(document.querySelector("#model-choice").value, "");
      assert.equal(consent().checked, false);
      assert.equal(
        status.active_account_id,
        chatgpt.id,
        "browsing an unconnected provider does not switch the active account",
      );
      if (provider === "bedrock") {
        assert.equal(document.querySelector("#provider-key"), null);
        assert.ok(document.querySelector("#aws-profile"));
      } else {
        const key = document.querySelector("#provider-key");
        assert.equal(key.value, "");
        assert.equal(key.type, "password");
        await env.change(key, `SYNTHETIC-${provider}-DRAFT-SECRET`);
        await env.click(consent());
      }
    }
    await env.change(providerPicker(), "chatgpt");
    assert.equal(document.querySelector("#provider-key"), null);
    assert.equal(
      document.querySelector("#model-choice").value,
      chatgpt.profile.model,
    );
    assert.equal(
      consent().checked,
      true,
      "the original account consent is retained",
    );
    assert.equal(document.querySelector(".connection-unsaved"), null);
    assert.deepEqual(status, before);
    assert.ok(
      calls.every(
        ({ path, method }) =>
          method === "GET" || path === "/api/connections/models",
      ),
      "picker browsing never creates or edits an account",
    );
    assert.doesNotMatch(document.body.textContent, /SYNTHETIC-.*-DRAFT-SECRET/);
    assert.equal(env.dom.window.localStorage.length, 0);
    assert.equal(env.dom.window.sessionStorage.length, 0);
  } finally {
    await env.close();
  }
});

test("connecting an API provider saves only its key, returns provider models, and reuses both provider accounts on later switches", async (t) => {
  const env = await environment();
  const chatgpt = account("chatgpt");
  let status = stateWith([chatgpt]);
  const originalChatGPT = structuredClone(chatgpt);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({ path, method: options.method ?? "GET", body });
    if (path === "/api/session")
      return Response.json({ csrf_token: "SYNTHETIC-CSRF-AT-LEAST-20" });
    if (path === "/api/connections") return Response.json(status);
    if (path === "/api/connections/models")
      return Response.json(catalog(status.profile.provider));
    if (path === "/api/connections/accounts") {
      const created = {
        id: "new-openai",
        label: body.label,
        profile: body.profile,
        credential_state: "session",
      };
      status = {
        ...status,
        accounts: [...status.accounts, created],
        active_account_id: created.id,
        profile: created.profile,
        credentials: { ...status.credentials, openai: "session" },
      };
      return Response.json(status);
    }
    if (path === "/api/connections/accounts/new-openai") {
      const saved = status.accounts.find((item) => item.id === "new-openai");
      saved.profile = body.profile;
      status = { ...status, profile: saved.profile };
      return Response.json(status);
    }
    if (path.endsWith("/select")) {
      const selected = status.accounts.find(
        (item) => path === `/api/connections/accounts/${item.id}/select`,
      );
      assert.ok(selected);
      status = {
        ...status,
        active_account_id: selected.id,
        profile: selected.profile,
      };
      return Response.json(status);
    }
    if (path === "/api/connections/test")
      return Response.json({
        target: "model",
        status: "ok",
        message: "Synthetic readiness only.",
        billable: false,
        inference_tested: false,
      });
    assert.fail(`Unexpected request ${path}`);
  });
  try {
    await env.render();
    await env.change(providerPicker(), "anthropic");
    await env.change(
      document.querySelector("#provider-key"),
      "SYNTHETIC-UNSAVED-ANTHROPIC",
    );
    await env.change(providerPicker(), "openai");
    assert.equal(document.querySelector("#provider-key").value, "");
    await env.change(
      document.querySelector("#provider-key"),
      "SYNTHETIC-OPENAI-ONLY",
    );
    await env.click(env.button("Connect OpenAI"));
    const created = calls.find(
      ({ path }) => path === "/api/connections/accounts",
    );
    assert.equal(created.body.profile.provider, "openai");
    assert.equal(created.body.api_key, "SYNTHETIC-OPENAI-ONLY");
    assert.equal(created.body.profile.model, "");
    assert.equal(created.body.profile.allow_paid_inference, false);
    assert.equal(created.body.secret_storage, "session");
    assert.doesNotMatch(JSON.stringify(calls), /SYNTHETIC-UNSAVED-ANTHROPIC/);
    assert.equal(document.querySelector("#provider-key").value, "");
    assert.equal(providerPicker().value, "openai");
    assert.ok(
      [...document.querySelector("#model-choice").options].some(
        (item) => item.value === "openai-saved-model",
      ),
    );
    await env.change(
      document.querySelector("#model-choice"),
      "openai-saved-model",
    );
    await env.click(consent());
    await env.click(env.button("Save and test connections"));
    assert.equal(status.accounts.length, 2);
    assert.equal(status.profile.model, "openai-saved-model");
    assert.equal(status.profile.allow_paid_inference, true);
    const saved = calls.find(
      ({ path }) => path === "/api/connections/accounts/new-openai",
    );
    assert.equal(
      Object.hasOwn(saved.body, "api_key"),
      false,
      "saving model preferences does not replay the previous key",
    );
    await env.change(providerPicker(), "chatgpt");
    assert.equal(status.active_account_id, chatgpt.id);
    assert.deepEqual(chatgpt, originalChatGPT);
    assert.equal(
      document.querySelector("#model-choice").value,
      chatgpt.profile.model,
    );
    await env.change(providerPicker(), "openai");
    assert.equal(status.active_account_id, "new-openai");
    assert.equal(consent().checked, true);
    assert.equal(
      document.querySelector("#model-choice").value,
      "openai-saved-model",
    );
    assert.equal(
      calls.filter(({ path }) => path === "/api/connections/accounts").length,
      1,
    );
    assert.ok(
      !calls.some(({ path }) => /login|logout|research|messages/.test(path)),
    );
    assertNoSavedAccountControls();
  } finally {
    await env.close();
  }
});

test("reload abandons an unsaved provider draft and restores the active account even when its server identity never changed", async (t) => {
  const env = await environment();
  const chatgpt = account("chatgpt");
  const status = stateWith([chatgpt]);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    calls.push({ path, method: options.method ?? "GET" });
    if (path === "/api/session")
      return Response.json({ csrf_token: "SYNTHETIC-CSRF-AT-LEAST-20" });
    if (path === "/api/connections") return Response.json(status);
    if (path === "/api/connections/models")
      return Response.json(catalog("chatgpt"));
    assert.fail(`Unexpected request ${path}`);
  });
  try {
    await env.render();
    await env.change(providerPicker(), "gemini");
    await env.change(
      document.querySelector("#provider-key"),
      "SYNTHETIC-ABANDONED-KEY",
    );
    await env.click(env.button("Reload saved settings"));
    assert.equal(providerPicker().value, "chatgpt");
    assert.equal(document.querySelector("#provider-key"), null);
    assert.equal(
      document.querySelector("#model-choice").value,
      chatgpt.profile.model,
    );
    assert.equal(document.querySelector(".connection-unsaved"), null);
    assert.ok(document.querySelector(".agent-sign-in"));
    assert.ok(
      calls.every(
        ({ path, method }) =>
          method === "GET" || path === "/api/connections/models",
      ),
    );
  } finally {
    await env.close();
  }
});

test("a failed provider switch retains the original account and clears draft secrets without retrying or showing private diagnostics", async (t) => {
  const env = await environment();
  const chatgpt = account("chatgpt"),
    anthropic = account("anthropic");
  const status = stateWith([chatgpt, anthropic]);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    calls.push({ path, method: options.method ?? "GET" });
    if (path === "/api/session")
      return Response.json({ csrf_token: "SYNTHETIC-CSRF-AT-LEAST-20" });
    if (path === "/api/connections") return Response.json(status);
    if (path === "/api/connections/models")
      return Response.json(catalog("chatgpt"));
    if (path === "/api/connections/accounts/anthropic-account/select")
      return Response.json(
        { detail: "SYNTHETIC-PRIVATE-SERVER-DIAGNOSTIC" },
        { status: 503 },
      );
    assert.fail(`Unexpected request ${path}`);
  });
  try {
    await env.render();
    await env.change(providerPicker(), "openai");
    await env.change(
      document.querySelector("#provider-key"),
      "SYNTHETIC-DRAFT-KEY",
    );
    await env.change(providerPicker(), "anthropic");
    assert.equal(status.active_account_id, chatgpt.id);
    assert.match(document.body.textContent, /not completed/);
    assert.doesNotMatch(
      document.body.textContent,
      /SYNTHETIC-PRIVATE-SERVER-DIAGNOSTIC|SYNTHETIC-DRAFT-KEY/,
    );
    if (document.querySelector("#provider-key"))
      assert.equal(document.querySelector("#provider-key").value, "");
    await env.flush();
    assert.equal(
      calls.filter(({ path }) => path.endsWith("/select")).length,
      1,
    );
    await env.click(env.button("Reload saved settings"));
    assert.equal(providerPicker().value, "chatgpt");
    assert.equal(
      document.querySelector("#model-choice").value,
      chatgpt.profile.model,
    );
    assert.equal(document.querySelector(".connection-unsaved"), null);
  } finally {
    await env.close();
  }
});

test("switching providers returns to the previously active ChatGPT session when a legacy workspace has duplicate accounts", async (t) => {
  const env = await environment();
  const oldChatGPT = account("chatgpt", "old-chatgpt", "missing"),
    currentChatGPT = account("chatgpt", "current-chatgpt");
  const unusedAnthropic = account("anthropic", "old-anthropic", "missing"),
    currentAnthropic = account("anthropic", "current-anthropic");
  let status = stateWith(
    [oldChatGPT, currentChatGPT, unusedAnthropic, currentAnthropic],
    currentChatGPT,
  );
  const originalAccounts = structuredClone(status.accounts);
  const selected = [],
    requests = [];
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    requests.push(path);
    if (path === "/api/session")
      return Response.json({ csrf_token: "SYNTHETIC-CSRF-AT-LEAST-20" });
    if (path === "/api/connections") return Response.json(status);
    if (path === "/api/connections/models")
      return Response.json(catalog(status.profile.provider));
    if (path.endsWith("/select")) {
      const match = status.accounts.find(
        (item) => path === `/api/connections/accounts/${item.id}/select`,
      );
      assert.ok(match);
      selected.push(match.id);
      status = {
        ...status,
        active_account_id: match.id,
        profile: match.profile,
      };
      return Response.json(status);
    }
    assert.fail(`Unexpected request ${path} ${options.method}`);
  });
  try {
    await env.render();
    await env.change(providerPicker(), "anthropic");
    assert.equal(
      status.active_account_id,
      currentAnthropic.id,
      "a usable provider connection wins over an unused legacy entry",
    );
    await env.change(providerPicker(), "chatgpt");
    assert.equal(
      status.active_account_id,
      currentChatGPT.id,
      "returning to ChatGPT preserves the previously active login",
    );
    await env.change(providerPicker(), "anthropic");
    await env.change(providerPicker(), "chatgpt");
    assert.deepEqual(selected, [
      currentAnthropic.id,
      currentChatGPT.id,
      currentAnthropic.id,
      currentChatGPT.id,
    ]);
    assert.deepEqual(
      status.accounts,
      originalAccounts,
      "legacy accounts, credential state, saved model and consent are preserved",
    );
    assert.ok(
      !requests.some(
        (path) =>
          path === "/api/connections/accounts" || /login|logout/.test(path),
      ),
    );
  } finally {
    await env.close();
  }
});

test("late ChatGPT catalog results cannot populate an unconnected API draft", async (t) => {
  const env = await environment();
  const status = stateWith([account("chatgpt")]);
  let resolveCatalog, catalogSignal;
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    calls.push(path);
    if (path === "/api/session")
      return Response.json({ csrf_token: "SYNTHETIC-CSRF-AT-LEAST-20" });
    if (path === "/api/connections") return Response.json(status);
    if (path === "/api/connections/models") {
      catalogSignal = options.signal;
      return new Promise((resolve) => {
        resolveCatalog = resolve;
      });
    }
    assert.fail(`Unexpected request ${path}`);
  });
  try {
    await env.render();
    assert.ok(resolveCatalog);
    assert.equal(
      providerPicker().disabled,
      false,
      "a slow model list does not hide other provider options",
    );
    await env.change(providerPicker(), "deepseek");
    assert.equal(catalogSignal.aborted, true);
    resolveCatalog(Response.json(catalog("chatgpt")));
    await env.flush();
    assert.equal(providerPicker().value, "deepseek");
    assert.equal(document.querySelector("#model-choice").disabled, true);
    assert.deepEqual(
      [...document.querySelector("#model-choice").options].map(
        (item) => item.value,
      ),
      [""],
    );
    assert.equal(consent().checked, false);
    assert.equal(
      calls.filter((path) => path === "/api/connections/models").length,
      1,
      "the unconnected draft cannot list the previous account models",
    );
    assert.equal(status.active_account_id, "chatgpt-account");
  } finally {
    await env.close();
  }
});

test("provider selection is serial while an existing account switch is in flight", async (t) => {
  const env = await environment();
  const chatgpt = account("chatgpt"),
    anthropic = account("anthropic");
  let status = stateWith([chatgpt, anthropic]);
  let finishSelect;
  const selected = [];
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    if (path === "/api/session")
      return Response.json({ csrf_token: "SYNTHETIC-CSRF-AT-LEAST-20" });
    if (path === "/api/connections") return Response.json(status);
    if (path === "/api/connections/models")
      return Response.json(catalog(status.profile.provider));
    if (path.endsWith("/select")) {
      selected.push(path);
      return new Promise((resolve) => {
        finishSelect = () => {
          status = {
            ...status,
            profile: anthropic.profile,
            active_account_id: anthropic.id,
          };
          resolve(Response.json(status));
        };
      });
    }
    assert.fail(`Unexpected request ${path} ${options.method}`);
  });
  try {
    await env.render();
    await env.change(providerPicker(), "anthropic");
    assert.equal(providerPicker().disabled, true);
    assert.ok(finishSelect);
    await env.change(providerPicker(), "openai");
    assert.equal(
      selected.length,
      1,
      "even a programmatic event cannot issue overlapping account mutations",
    );
    await env.act(async () => finishSelect());
    assert.equal(providerPicker().value, "anthropic");
    assert.equal(providerPicker().disabled, false);
    assert.equal(
      document.querySelector("#model-choice").value,
      anthropic.profile.model,
    );
    assert.equal(status.active_account_id, anthropic.id);
  } finally {
    await env.close();
  }
});

test("a lost account-selection response blocks further connection changes until reload reconciles the server-selected provider", async (t) => {
  const env = await environment();
  const chatgpt = account("chatgpt"),
    anthropic = account("anthropic");
  let status = stateWith([chatgpt, anthropic]);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    calls.push({ path, method: options.method ?? "GET" });
    if (path === "/api/session")
      return Response.json({ csrf_token: "SYNTHETIC-CSRF-AT-LEAST-20" });
    if (path === "/api/connections") return Response.json(status);
    if (path === "/api/connections/models")
      return Response.json(catalog(status.profile.provider));
    if (path === "/api/connections/accounts/anthropic-account/select") {
      status = {
        ...status,
        profile: anthropic.profile,
        active_account_id: anthropic.id,
      };
      throw new TypeError("SYNTHETIC-LOST-RESPONSE");
    }
    assert.fail(`Unexpected request ${path}`);
  });
  try {
    await env.render();
    await env.change(providerPicker(), "anthropic");
    assert.equal(providerPicker().disabled, true);
    assert.equal(env.button("Verify connection").disabled, true);
    assert.equal(env.button("Save and test connections").disabled, true);
    assert.equal(document.querySelector("#model-choice").disabled, true);
    assert.equal(
      env.button("Reload saved settings").disabled,
      false,
      "reload remains available for reconciliation",
    );
    assert.doesNotMatch(document.body.textContent, /SYNTHETIC-LOST-RESPONSE/);
    assert.ok(document.querySelector(".workspace-error"));
    await env.change(providerPicker(), "openai");
    assert.equal(
      document.querySelector("#provider-key"),
      null,
      "an ambiguous account mutation cannot be followed by a new credential draft",
    );
    assert.equal(
      calls.filter(({ path }) => path.endsWith("/select")).length,
      1,
    );
    await env.click(env.button("Reload saved settings"));
    assert.equal(providerPicker().value, "anthropic");
    assert.equal(providerPicker().disabled, false);
    assert.equal(
      document.querySelector("#model-choice").value,
      anthropic.profile.model,
    );
    assert.equal(document.querySelector(".workspace-error"), null);
    assert.equal(document.querySelector(".connection-unsaved"), null);
    assert.equal(
      calls.filter(
        ({ path, method }) =>
          method === "POST" && path !== "/api/connections/models",
      ).length,
      1,
      "recovery only reads authoritative state and metadata; it never repeats the mutation",
    );
  } finally {
    await env.close();
  }
});
