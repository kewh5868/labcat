import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

async function compile() {
  const output = await mkdtemp(join(tmpdir(), "labcat-agent-ui-"));
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

for (const method of ["device", "browser"])
  test(`${method} sign-in retains a pending challenge after an interrupted poll and usage stays explicit`, async (t) => {
    const output = await compile();
    const dom = new JSDOM('<div id="root"></div>', {
      url: "http://localhost/",
    });
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
    const { ConnectionsProvider } = await import(
      pathToFileURL(join(output, "Connections.js")).href
    );
    const { ChatGPTSignIn, AccountUsageView, ResearchPlanCard } = await import(
      pathToFileURL(join(output, "AgentConnections.js")).href
    );
    const profile = {
      provider: "chatgpt",
      model: "test-model",
      allow_paid_inference: false,
      ollama_url: "http://localhost:11434",
      aws_profile: "",
      aws_region: "",
    };
    const account = {
      id: "test-account",
      label: "Test subscription",
      profile,
      credential_state: "missing",
    };
    const status = {
      configured: true,
      using_local_defaults: false,
      profile,
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
    const browserUrl = `https://auth.openai.com/oauth/authorize?${new URLSearchParams({ client_id: "app_EMoamEEZ73f0CkXaXp7hrann", redirect_uri: "http://localhost:1455/auth/callback", response_type: "code", code_challenge_method: "S256", state: "SYNTHETIC_state_1234567890", code_challenge: "SYNTHETIC_challenge_1234567890" })}`;
    const challenge = {
      flow_id: "flow-test",
      status: "pending",
      ...(method === "browser"
        ? { method, verification_url: browserUrl, user_code: null }
        : {
            verification_url: "https://auth.openai.com/codex/device",
            user_code: "TEST-1234",
          }),
      message: "TEST challenge only.",
    };
    const calls = [],
      polls = new Map(),
      errors = [];
    let rejectPoll = true,
      signedIn = false,
      nextTimer = 100000;
    const nativeTimeout = dom.window.setTimeout.bind(dom.window),
      nativeClear = dom.window.clearTimeout.bind(dom.window);
    t.mock.method(dom.window, "setTimeout", (callback, delay) => {
      if (delay === 2000) {
        const id = nextTimer++;
        polls.set(id, callback);
        return id;
      }
      return nativeTimeout(callback, delay);
    });
    t.mock.method(dom.window, "clearTimeout", (id) => {
      if (id >= 100000) polls.delete(id);
      else nativeClear(id);
    });
    t.mock.method(console, "error", (...args) => errors.push(args.join(" ")));
    t.mock.method(globalThis, "fetch", async (path, options = {}) => {
      const body = options.body ? JSON.parse(options.body) : null;
      calls.push({ path, method: options.method ?? "GET", body });
      if (path === "/api/session")
        return Response.json({ csrf_token: "TEST-CSRF-LONG-ENOUGH" });
      if (path === "/api/connections") return Response.json(status);
      if (path === "/api/research-plan")
        return Response.json({
          version: "test-plan",
          steps: [
            "Validate approved public evidence.",
            "Apply the selected ranking profile.",
          ],
        });
      if (path === "/api/connections/accounts/test-account/login")
        return Response.json(challenge);
      if (
        path === "/api/connections/accounts/test-account/login/flow-test/poll"
      ) {
        if (rejectPoll)
          return Response.json(
            { detail: "TEST_PRIVATE_ACCESS_TOKEN" },
            { status: 503 },
          );
        signedIn = true;
        account.credential_state = "encrypted";
        return Response.json({
          flow_id: "flow-test",
          status: "complete",
          ...(method === "browser"
            ? { method, user_code: null, verification_url: browserUrl }
            : {}),
          message: "Connected.",
        });
      }
      if (path === "/api/connections/usage")
        return Response.json({
          account_id: account.id,
          provider: "chatgpt",
          rate_limits: [
            {
              id: "window-test",
              label: "Test allowance",
              primary: {
                used_percent: 12,
                remaining_percent: 88,
                window_minutes: 300,
                resets_at: 1800000000,
              },
              secondary: null,
            },
          ],
          token_activity: {
            unfamiliar_telemetry: "DO_NOT_RENDER_RAW_TELEMETRY",
          },
          last_run: {
            provider: "chatgpt",
            model: "test-model",
            recorded_at: "2026-09-09T00:00:00Z",
            status: "complete",
            usage: { input_tokens: 100, output_tokens: 40, total_tokens: 140 },
          },
          notices: ["Test metadata only, no provider call."],
          inference_tested: false,
        });
      if (path === "/api/connections/accounts/test-account/logout") {
        account.credential_state = "missing";
        signedIn = false;
        return Response.json(status);
      }
      assert.fail(`Unexpected request ${path}`);
    });
    const root = createRoot(document.getElementById("root"));
    const tree = (storage = "encrypted") =>
      createElement(
        ConnectionsProvider,
        null,
        createElement(ChatGPTSignIn, {
          accountId: account.id,
          saved: true,
          storage,
          disabled: false,
        }),
        createElement(AccountUsageView),
        createElement(ResearchPlanCard),
      );
    const button = (name) => {
      const found = [...document.querySelectorAll("button")].find(
        (item) => item.textContent.trim() === name,
      );
      assert.ok(found, `button ${name}`);
      return found;
    };
    const click = async (item) => {
      assert.ok(!item.disabled, `${item.textContent} enabled`);
      await act(async () =>
        item.dispatchEvent(
          new dom.window.MouseEvent("click", { bubbles: true }),
        ),
      );
    };
    try {
      await act(async () => root.render(tree()));
      assert.equal(
        document.querySelectorAll('input[type="password"]').length,
        0,
        "provider passwords are never collected",
      );
      assert.equal(
        calls.filter((item) => item.path === "/api/connections/usage").length,
        0,
        "usage does not contact the provider without an explicit request",
      );
      assert.match(
        document.querySelector(".agent-build-plan").textContent,
        /Validate approved public evidence/,
      );
      assert.equal(
        document.querySelector(".agent-device-prerequisite"),
        null,
        "device help is not displayed before the method is known",
      );
      await click(button("Sign in with ChatGPT"));
      const link = document.querySelector(".agent-device-flow a");
      assert.equal(link.href, challenge.verification_url);
      assert.equal(link.rel, "noopener noreferrer");
      if (method === "device") {
        assert.equal(
          document.querySelector(".agent-device-code").textContent,
          challenge.user_code,
        );
        assert.match(
          document.querySelector(".agent-device-prerequisite").textContent,
          /Settings → Security/,
        );
        assert.equal(
          document.querySelector(".agent-device-prerequisite a").href,
          "https://learn.chatgpt.com/docs/auth#login-on-headless-devices",
        );
      } else {
        assert.equal(document.querySelector(".agent-device-code"), null);
        assert.equal(
          document.querySelector(".agent-device-prerequisite"),
          null,
        );
      }
      assert.deepEqual(
        calls.find((item) => item.path.endsWith("/login")).body,
        { secret_storage: "encrypted" },
      );
      await act(async () => root.render(tree("session")));
      assert.match(
        document.querySelector(".agent-sign-in").textContent,
        /Sign-in tokens use the encrypted credential vault/,
        "editing the next storage choice cannot relabel the pending sign-in",
      );
      assert.equal(polls.size, 1);
      const poll = [...polls.values()][0];
      polls.clear();
      await act(async () => poll());
      assert.equal(signedIn, false);
      assert.equal(
        document.querySelector(".agent-device-flow a").href,
        challenge.verification_url,
        "uncertain mutation retains the reviewed challenge",
      );
      if (method === "device")
        assert.equal(
          document.querySelector(".agent-device-code").textContent,
          challenge.user_code,
        );
      assert.equal(polls.size, 0, "failed polls are not retried automatically");
      assert.match(document.body.textContent, /Automatic checks paused/);
      assert.doesNotMatch(
        document.body.textContent,
        /TEST_PRIVATE_ACCESS_TOKEN/,
      );
      rejectPoll = false;
      await click(button("Check sign-in status"));
      assert.equal(signedIn, true);
      assert.equal(
        document.querySelector(".agent-device-code"),
        null,
        "completed challenge is no longer displayed",
      );
      assert.equal(document.querySelector(".agent-device-prerequisite"), null);
      assert.equal(
        profile.allow_paid_inference,
        false,
        "sign-in does not enable cloud research consent",
      );
      assert.match(
        document.querySelector(".agent-sign-in").textContent,
        /Connected/,
      );
      await click(button("Check usage"));
      assert.equal(document.querySelector("progress").value, 88);
      assert.match(
        document.querySelector(".agent-token-counts").textContent,
        /Total tokens140/,
      );
      assert.doesNotMatch(
        document.body.textContent,
        /DO_NOT_RENDER_RAW_TELEMETRY/,
      );
      assert.ok(
        calls
          .filter((item) => item.path.includes("/usage"))
          .every((item) => JSON.stringify(item.body) === "{}"),
      );
      await click(button("Sign out this account"));
      assert.equal(signedIn, false);
      assert.equal(profile.allow_paid_inference, false);
      assert.deepEqual(
        errors,
        [],
        "no React reconciliation or lifecycle warnings",
      );
    } finally {
      await act(async () => root.unmount());
      dom.window.close();
      for (const key of globals) {
        if (previous[key])
          Object.defineProperty(globalThis, key, previous[key]);
        else delete globalThis[key];
      }
      await rm(output, { recursive: true, force: true });
    }
  });
