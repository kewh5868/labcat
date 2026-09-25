import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { afterEach, mock, test } from "node:test";
import ts from "typescript";
const source = await readFile(
  new URL("../src/connectionsApi.ts", import.meta.url),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
  },
}).outputText;
const { connectionsApi } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);
globalThis.window = { setTimeout, clearTimeout };
afterEach(() => mock.restoreAll());
const status = {
  configured: false,
  profile: {
    provider: "none",
    model: "",
    ollama_url: "http://127.0.0.1:11434",
    aws_profile: "",
    aws_region: "",
    allow_paid_inference: false,
  },
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
  accounts: [],
  active_account_id: null,
};
const token = "TEST_SESSION_TOKEN_123456";
function safeServer(result = status) {
  return mock.method(globalThis, "fetch", async (path) =>
    Response.json(path === "/api/session" ? { csrf_token: token } : result),
  );
}
test("connection status accepts only safe profile and credential metadata", async () => {
  const fetch = safeServer();
  assert.deepEqual(await connectionsApi.status(), status);
  assert.equal(fetch.mock.calls[0].arguments[1].credentials, "same-origin");
  assert.equal(fetch.mock.calls[0].arguments[1].redirect, "error");
  for (const response of [
    { ...status, api_key: "UNEXPECTED_KEY" },
    { ...status, credentials: { ...status.credentials, openai: "RAW_SECRET" } },
    { ...status, profile: { ...status.profile, password: "UNEXPECTED_KEY" } },
  ]) {
    fetch.mock.mockImplementation(async () => Response.json(response));
    await assert.rejects(connectionsApi.status(), /unsupported response/);
  }
});
test("saving keys uses fresh CSRF session and omits empty keys without persisting anything to browser storage", async () => {
  const fetch = safeServer();
  await connectionsApi.save({
    profile: status.profile,
    secret_storage: "session",
    secrets: { openai: "TEST_WRITE_ONLY_KEY", materials_project: "" },
  });
  assert.equal(fetch.mock.calls.length, 2);
  assert.equal(fetch.mock.calls[0].arguments[0], "/api/session");
  const [path, request] = fetch.mock.calls[1].arguments;
  assert.equal(path, "/api/connections");
  assert.equal(request.method, "PUT");
  assert.equal(request.headers["X-CSRF-Token"], token);
  assert.deepEqual(JSON.parse(request.body), {
    profile: status.profile,
    secret_storage: "session",
    secrets: { openai: "TEST_WRITE_ONLY_KEY" },
  });
  assert.equal(globalThis.window.localStorage, undefined);
  assert.equal(globalThis.window.sessionStorage, undefined);
});
test("blank key retention and explicit forgetting are distinct requests", async () => {
  const fetch = safeServer();
  await connectionsApi.save({
    profile: status.profile,
    secret_storage: "session",
    secrets: { materials_project: "" },
    forget_secrets: ["openai"],
  });
  assert.deepEqual(JSON.parse(fetch.mock.calls[1].arguments[1].body), {
    profile: status.profile,
    secret_storage: "session",
    forget_secrets: ["openai"],
  });
});
test("Materials Project keys use a source-only endpoint and cannot submit the active model profile", async () => {
  const fetch = safeServer();
  const update = {
    secret_storage: "encrypted",
    api_key: "SYNTHETIC-WRITE-ONLY-SOURCE-KEY",
  };
  assert.deepEqual(await connectionsApi.saveMaterialsProject(update), status);
  const [path, request] = fetch.mock.calls[1].arguments;
  assert.equal(fetch.mock.calls[0].arguments[0], "/api/session");
  assert.equal(path, "/api/connections/sources/materials_project");
  assert.equal(request.method, "PUT");
  assert.equal(request.headers["X-CSRF-Token"], token);
  assert.equal(request.credentials, "same-origin");
  assert.equal(request.cache, "no-store");
  assert.equal(request.redirect, "error");
  assert.deepEqual(JSON.parse(request.body), update);
  assert.equal(Object.hasOwn(JSON.parse(request.body), "profile"), false);
  assert.equal(Object.hasOwn(JSON.parse(request.body), "accounts"), false);
  for (const change of [
    { secret_storage: "encrypted" },
    { secret_storage: "session" },
    { forget: true },
  ]) {
    await connectionsApi.saveMaterialsProject(change);
    assert.deepEqual(
      JSON.parse(fetch.mock.calls.at(-1).arguments[1].body),
      change,
      "storage-only changes and explicit forgetting do not resend a credential",
    );
  }
  assert.equal(globalThis.window.localStorage, undefined);
  assert.equal(globalThis.window.sessionStorage, undefined);
});
test("Materials Project key failures hide reflected secrets and reject secret-bearing responses without retry", async () => {
  const fetch = mock.method(globalThis, "fetch", async (path) =>
    path === "/api/session"
      ? Response.json({ csrf_token: token })
      : Response.json(
          { detail: { input: "SYNTHETIC-PRIVATE-SOURCE-KEY" } },
          { status: 422 },
        ),
  );
  await assert.rejects(
    connectionsApi.saveMaterialsProject({
      secret_storage: "session",
      api_key: "SYNTHETIC-PRIVATE-SOURCE-KEY",
    }),
    (error) => {
      assert.match(error.message, /not completed \(422\)/);
      assert.doesNotMatch(error.message, /SYNTHETIC-PRIVATE/);
      return true;
    },
  );
  assert.equal(
    fetch.mock.calls.length,
    2,
    "a failed mutation is never automatically retried",
  );
  fetch.mock.mockImplementation(async (path) =>
    Response.json(
      path === "/api/session"
        ? { csrf_token: token }
        : { ...status, api_key: "SYNTHETIC-PRIVATE-SOURCE-KEY" },
    ),
  );
  await assert.rejects(
    connectionsApi.saveMaterialsProject({ forget: true }),
    /unsupported response/,
  );
  assert.equal(fetch.mock.calls.length, 4);
});
test("local defaults never authorize cloud inference or erase credentials by implication", async () => {
  const fetch = safeServer();
  await connectionsApi.localDefaults(false);
  assert.deepEqual(JSON.parse(fetch.mock.calls[1].arguments[1].body), {
    persist: false,
  });
  await connectionsApi.localDefaults(true);
  assert.deepEqual(JSON.parse(fetch.mock.calls[3].arguments[1].body), {
    persist: true,
  });
});
test("vault writes carry only action and passphrase then return safe metadata", async () => {
  const fetch = safeServer();
  const result = await connectionsApi.vault({
    action: "create",
    passphrase: "TEST_VAULT_PASSPHRASE",
  });
  assert.deepEqual(result, status);
  assert.ok(!JSON.stringify(result).includes("TEST_VAULT_PASSPHRASE"));
  assert.deepEqual(JSON.parse(fetch.mock.calls[1].arguments[1].body), {
    action: "create",
    passphrase: "TEST_VAULT_PASSPHRASE",
  });
  await connectionsApi.vault({ action: "reset", confirm: true });
  assert.deepEqual(JSON.parse(fetch.mock.calls[3].arguments[1].body), {
    action: "reset",
    confirm: true,
  });
});
test("credential errors never display reflected input and never retry mutations automatically", async () => {
  const fetch = mock.method(globalThis, "fetch", async (path) =>
    path === "/api/session"
      ? Response.json({ csrf_token: token })
      : Response.json(
          { detail: [{ input: "TEST_PRIVATE_SECRET" }] },
          { status: 422 },
        ),
  );
  await assert.rejects(
    connectionsApi.vault({
      action: "unlock",
      passphrase: "TEST_PRIVATE_SECRET",
    }),
    (error) => {
      assert.match(error.message, /not completed/);
      assert.ok(!error.message.includes("TEST_PRIVATE_SECRET"));
      return true;
    },
  );
  assert.equal(fetch.mock.calls.length, 2);
});
test("busy connections show fixed waiting guidance without reflecting diagnostics or retrying", async () => {
  const fetch = mock.method(globalThis, "fetch", async (path) =>
    path === "/api/session"
      ? Response.json({ csrf_token: token })
      : Response.json({ detail: "TEST_PRIVATE_ACCESS_TOKEN" }, { status: 409 }),
  );
  await assert.rejects(connectionsApi.test("model"), (error) => {
    assert.match(
      error.message,
      /^Connection is busy.*Wait.*try this action again/,
    );
    assert.doesNotMatch(
      error.message,
      /TEST_PRIVATE|reload|passphrase|sign.in/i,
    );
    return true;
  });
  assert.equal(
    fetch.mock.calls.length,
    2,
    "one CSRF request and one explicit account check; no retry",
  );
  assert.equal(fetch.mock.calls[1].arguments[0], "/api/connections/test");
});
test("busy guidance is not applied to unrelated session conflicts", async () => {
  const fetch = mock.method(globalThis, "fetch", async () =>
    Response.json({ detail: "TEST_PRIVATE_ACCESS_TOKEN" }, { status: 409 }),
  );
  await assert.rejects(connectionsApi.test("model"), (error) => {
    assert.match(error.message, /Connection request was not completed \(409\)/);
    assert.doesNotMatch(error.message, /TEST_PRIVATE|Connection is busy/);
    return true;
  });
  assert.equal(
    fetch.mock.calls.length,
    1,
    "a failed session check prevents the account action",
  );
});
test("reviewed ChatGPT setup failures show fixed deployment guidance without reflecting backend secrets", async () => {
  const fetch = safeServer();
  for (const [code, guidance] of [
    [
      "chatgpt_storage_unavailable",
      /protected temporary storage.*Docker launcher/,
    ],
    [
      "chatgpt_helper_unavailable",
      /sign-in helper.*Update or rebuild.*Docker image/,
    ],
    [
      "chatgpt_callback_unavailable",
      /local port 1455.*Free that port.*restart.*LABCAT_OAUTH_CALLBACK_PORT=1455.*Other providers remain usable/,
    ],
  ]) {
    fetch.mock.mockImplementation(async (path) =>
      path === "/api/session"
        ? Response.json({ csrf_token: token })
        : Response.json(
            {
              detail: {
                code,
                message: "TEST_PRIVATE_ACCESS_TOKEN sk-test-do-not-display",
                path: "/private/credential-file",
              },
            },
            { status: 503 },
          ),
    );
    await assert.rejects(
      connectionsApi.startLogin("account", "session"),
      (error) => {
        assert.match(error.message, /^Connection setup needs attention\./);
        assert.match(error.message, guidance);
        assert.doesNotMatch(
          error.message,
          /TEST_PRIVATE|sk-test|credential-file|vault passphrase/,
        );
        return true;
      },
    );
  }
  assert.equal(
    fetch.mock.calls.length,
    6,
    "deployment errors are not retried automatically",
  );
});
test("unreviewed or malformed setup diagnostics stay generic and never expose server text", async () => {
  const fetch = safeServer();
  for (const detail of [
    { code: "unknown_TEST_PRIVATE_ACCESS_TOKEN" },
    { code: { secret: "TEST_PRIVATE_ACCESS_TOKEN" } },
    "TEST_PRIVATE_ACCESS_TOKEN",
    ["TEST_PRIVATE_ACCESS_TOKEN"],
  ]) {
    fetch.mock.mockImplementation(async (path) =>
      path === "/api/session"
        ? Response.json({ csrf_token: token })
        : Response.json({ detail }, { status: 503 }),
    );
    await assert.rejects(
      connectionsApi.startLogin("account", "session"),
      (error) => {
        assert.match(
          error.message,
          /Connection request was not completed \(503\)/,
        );
        assert.doesNotMatch(
          error.message,
          /TEST_PRIVATE|setup needs attention/,
        );
        return true;
      },
    );
  }
});
test("failed CSRF initialization prevents any credential mutation", async () => {
  const fetch = mock.method(globalThis, "fetch", async () =>
    Response.json({ csrf_token: "short" }),
  );
  await assert.rejects(
    connectionsApi.save({
      profile: status.profile,
      secret_storage: "session",
      secrets: { openai: "TEST_SECRET" },
    }),
    /unsupported response/,
  );
  assert.equal(fetch.mock.calls.length, 1);
});
test("connection tests must report nonbillable readiness, not inference", async () => {
  const result = {
    target: "model",
    status: "ok",
    message: "Readiness confirmed.",
    billable: false,
    inference_tested: false,
  };
  const fetch = safeServer(result);
  assert.deepEqual(await connectionsApi.test("model"), result);
  for (const bad of [
    { ...result, billable: true },
    { ...result, inference_tested: true },
    { ...result, target: "aws" },
  ]) {
    fetch.mock.mockImplementation(async (path) =>
      Response.json(path === "/api/session" ? { csrf_token: token } : bad),
    );
    await assert.rejects(connectionsApi.test("model"), /unsupported response/);
  }
});

test("named accounts expose only credential state and keep new and existing keys distinct", async () => {
  const profile = { ...status.profile, provider: "openai", model: "" };
  const account = {
    id: "account-a",
    label: "Research account",
    profile,
    credential_state: "missing",
  };
  const saved = {
    ...status,
    profile,
    accounts: [account],
    active_account_id: account.id,
  };
  const fetch = safeServer(saved);
  assert.deepEqual(
    await connectionsApi.saveAccount({
      label: account.label,
      profile,
      secret_storage: "session",
      api_key: "",
    }),
    saved,
  );
  assert.deepEqual(JSON.parse(fetch.mock.calls[1].arguments[1].body), {
    label: account.label,
    profile,
    secret_storage: "session",
  });
  await connectionsApi.saveAccount(
    {
      label: account.label,
      profile,
      secret_storage: "encrypted",
      api_key: "TEST_WRITE_ONLY_ACCOUNT_KEY",
    },
    account.id,
  );
  assert.equal(
    fetch.mock.calls[3].arguments[0],
    "/api/connections/accounts/account-a",
  );
  assert.equal(fetch.mock.calls[3].arguments[1].method, "PUT");
  assert.equal(
    JSON.parse(fetch.mock.calls[3].arguments[1].body).api_key,
    "TEST_WRITE_ONLY_ACCOUNT_KEY",
  );
  await connectionsApi.selectAccount(account.id);
  assert.equal(
    fetch.mock.calls[5].arguments[0],
    "/api/connections/accounts/account-a/select",
  );
  assert.deepEqual(JSON.parse(fetch.mock.calls[5].arguments[1].body), {});
  for (const bad of [
    { ...saved, accounts: [{ ...account, api_key: "UNEXPECTED_SECRET" }] },
    { ...saved, active_account_id: "wrong-account" },
    { ...saved, accounts: [account, account] },
  ]) {
    fetch.mock.mockImplementation(async () => Response.json(bad));
    await assert.rejects(connectionsApi.status(), /unsupported response/);
  }
});

test("model catalog is explicit metadata-only and carries no prompt or credentials in its body", async () => {
  const result = {
    provider: "openai",
    models: [{ id: "available-model", label: "Available model" }],
    message: "Available models.",
    inference_tested: false,
  };
  const fetch = safeServer(result);
  assert.deepEqual(await connectionsApi.models(), result);
  assert.equal(fetch.mock.calls[1].arguments[0], "/api/connections/models");
  assert.deepEqual(JSON.parse(fetch.mock.calls[1].arguments[1].body), {});
  fetch.mock.mockImplementation(async (path) =>
    Response.json(
      path === "/api/session"
        ? { csrf_token: token }
        : { ...result, inference_tested: true },
    ),
  );
  await assert.rejects(connectionsApi.models(), /unsupported response/);
});

test("AWS selection exposes profile names and official sign-in instructions only", async () => {
  const result = {
    profiles: ["research"],
    regions: ["us-west-2"],
    setup: {
      commands: ["aws configure sso", "aws sso login --profile research"],
      message: "Sign in on this machine.",
      documentation_url:
        "https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html",
    },
  };
  const fetch = safeServer(result);
  assert.deepEqual(await connectionsApi.awsProfiles(), result);
  assert.equal(fetch.mock.calls.length, 1);
  assert.equal(
    fetch.mock.calls[0].arguments[0],
    "/api/connections/aws-profiles",
  );
  fetch.mock.mockImplementation(async () =>
    Response.json({ ...result, access_key: "UNEXPECTED_SECRET" }),
  );
  await assert.rejects(connectionsApi.awsProfiles(), /unsupported response/);
});

test("ChatGPT account sign-in exposes a provider device challenge and never accepts token responses", async () => {
  const flow = {
    flow_id: "flow-fixture",
    status: "pending",
    verification_url: "https://auth.openai.com/codex/device",
    user_code: "ABCD-1234",
    message: "Complete provider sign-in.",
  };
  const fetch = safeServer(flow);
  assert.deepEqual(
    await connectionsApi.startLogin("chatgpt-account", "encrypted"),
    flow,
  );
  assert.equal(
    fetch.mock.calls[1].arguments[0],
    "/api/connections/accounts/chatgpt-account/login",
  );
  assert.deepEqual(JSON.parse(fetch.mock.calls[1].arguments[1].body), {
    secret_storage: "encrypted",
  });
  await connectionsApi.pollLogin("chatgpt-account", flow.flow_id);
  assert.deepEqual(JSON.parse(fetch.mock.calls[3].arguments[1].body), {});
  assert.match(fetch.mock.calls[3].arguments[0], /\/flow-fixture\/poll$/);
  await connectionsApi.cancelLogin("chatgpt-account", flow.flow_id);
  assert.match(fetch.mock.calls[5].arguments[0], /\/flow-fixture\/cancel$/);
  for (const invalid of [
    { ...flow, access_token: "UNEXPECTED_SECRET" },
    {
      ...flow,
      verification_url: "https://auth.openai.com.evil.invalid/codex/device",
    },
    { ...flow, verification_url: "javascript:alert(1)" },
    {
      ...flow,
      verification_url:
        "https://auth.openai.com/codex/device?redirect=http://localhost",
    },
    { ...flow, user_code: "<script>" },
  ]) {
    fetch.mock.mockImplementation(async (path) =>
      Response.json(path === "/api/session" ? { csrf_token: token } : invalid),
    );
    await assert.rejects(
      connectionsApi.startLogin("account", "session"),
      /unsupported response/,
    );
  }
});

test("browser sign-in accepts only the reviewed Goose PKCE client, callback and unique bounded parameters", async () => {
  const params = {
    client_id: "app_EMoamEEZ73f0CkXaXp7hrann",
    redirect_uri: "http://localhost:1455/auth/callback",
    response_type: "code",
    code_challenge_method: "S256",
    state: "SYNTHETIC_state_1234567890",
    code_challenge: "SYNTHETIC_challenge_1234567890",
    scope: "openid profile email offline_access",
    originator: "goose",
  };
  const authorize = (changes = {}) =>
    `https://auth.openai.com/oauth/authorize?${new URLSearchParams({ ...params, ...changes })}`;
  const flow = {
    flow_id: "browser-fixture",
    status: "pending",
    method: "browser",
    verification_url: authorize(),
    user_code: null,
  };
  const fetch = safeServer(flow);
  assert.deepEqual(await connectionsApi.startLogin("account", "session"), flow);
  for (const status of [
    "complete",
    "expired",
    "cancelled",
    "error",
    "consumed",
  ]) {
    for (const verification_url of [authorize(), null, undefined]) {
      const terminal = { ...flow, status, verification_url };
      fetch.mock.mockImplementation(async (path) =>
        Response.json(
          path === "/api/session" ? { csrf_token: token } : terminal,
        ),
      );
      assert.deepEqual(
        await connectionsApi.pollLogin("account", flow.flow_id),
        JSON.parse(JSON.stringify(terminal)),
      );
    }
  }
  const badUrls = [
    authorize({ client_id: "another-client" }),
    authorize({ redirect_uri: "http://127.0.0.1:1455/auth/callback" }),
    authorize({ redirect_uri: "https://outside.example/callback" }),
    authorize({ response_type: "token" }),
    authorize({ code_challenge_method: "plain" }),
    authorize({ state: "" }),
    authorize({ state: "s".repeat(19) }),
    authorize({ code_challenge: "c".repeat(257) }),
    authorize({ state: "bad state with spaces" }),
    `${authorize()}&state=${params.state}`,
    `${authorize()}&%73tate=${params.state}`,
    `${authorize()}&originator=duplicate`,
    `${authorize()}&empty`,
    `${authorize()}&`,
    `${authorize()}#`,
    `${authorize()}#fragment`,
    authorize().replace("/oauth/authorize?", "/oauth/other?"),
    authorize().replace("auth.openai.com", "auth.openai.com.evil.example"),
    authorize().replace("https://", "http://"),
    authorize().replace("auth.openai.com", "user@auth.openai.com"),
    authorize().replace("auth.openai.com", "auth.openai.com:443"),
    authorize().replace("auth.openai.com", "auth.openai.com:444"),
    ` ${authorize()}`,
    `${authorize()}\n`,
    authorize({ extra: "x".repeat(8192) }),
    "https://auth.openai.com/codex/device",
    "javascript:alert(1)",
    null,
  ];
  for (const verification_url of badUrls) {
    fetch.mock.mockImplementation(async (path) =>
      Response.json(
        path === "/api/session"
          ? { csrf_token: token }
          : { ...flow, verification_url },
      ),
    );
    await assert.rejects(
      connectionsApi.startLogin("account", "session"),
      /unsupported response/,
    );
  }
  for (const invalid of [
    { ...flow, method: undefined },
    { ...flow, method: "device" },
    { ...flow, method: "arbitrary" },
    { ...flow, user_code: "CODE-1234" },
    { ...flow, user_code: undefined },
    { ...flow, access_token: "UNEXPECTED_SECRET" },
  ]) {
    fetch.mock.mockImplementation(async (path) =>
      Response.json(path === "/api/session" ? { csrf_token: token } : invalid),
    );
    await assert.rejects(
      connectionsApi.startLogin("account", "session"),
      /unsupported response/,
    );
  }
});

test("usage accepts unavailable allowance and measured token metadata without inventing balances", async () => {
  const usage = {
    account_id: "chatgpt-account",
    provider: "chatgpt",
    rate_limits: [
      {
        id: "test",
        label: "Test account window",
        primary: {
          used_percent: 20,
          remaining_percent: 80,
          window_minutes: 300,
          resets_at: 1800000000,
        },
        secondary: null,
      },
    ],
    token_activity: null,
    last_run: {
      provider: "chatgpt",
      model: "test-model",
      recorded_at: "2026-09-09T12:00:00Z",
      status: "complete",
      usage: { input_tokens: 100, output_tokens: 25, total_tokens: 125 },
    },
    notices: ["Provider metadata only."],
    inference_tested: false,
  };
  const fetch = safeServer(usage);
  assert.deepEqual(await connectionsApi.usage(), usage);
  assert.deepEqual(JSON.parse(fetch.mock.calls[1].arguments[1].body), {});
  assert.equal(fetch.mock.calls[1].arguments[0], "/api/connections/usage");
  for (const bad of [
    { ...usage, inference_tested: true },
    { ...usage, token_activity: { access_token: "UNEXPECTED_SECRET" } },
    {
      ...usage,
      rate_limits: [
        {
          ...usage.rate_limits[0],
          primary: { ...usage.rate_limits[0].primary, remaining_percent: 101 },
        },
      ],
    },
  ]) {
    fetch.mock.mockImplementation(async (path) =>
      Response.json(path === "/api/session" ? { csrf_token: token } : bad),
    );
    await assert.rejects(connectionsApi.usage(), /unsupported response/);
  }
  const unavailable = {
    ...usage,
    rate_limits: null,
    last_run: null,
    token_activity: null,
  };
  fetch.mock.mockImplementation(async (path) =>
    Response.json(
      path === "/api/session" ? { csrf_token: token } : unavailable,
    ),
  );
  assert.deepEqual(await connectionsApi.usage(), unavailable);
  const manyWindows = {
    ...usage,
    rate_limits: Array.from({ length: 32 }, (_, index) => ({
      ...usage.rate_limits[0],
      id: `bucket-${index}`,
    })),
  };
  fetch.mock.mockImplementation(async (path) =>
    Response.json(
      path === "/api/session" ? { csrf_token: token } : manyWindows,
    ),
  );
  assert.equal(
    (await connectionsApi.usage()).rate_limits.length,
    32,
    "accept the complete bounded provider bucket catalog",
  );
});

test("Goose runtime and actual research plan are read-only metadata", async () => {
  const runtime = {
    engine: "goose",
    available: true,
    version: "TEST-VERSION",
    tools: ["search_public_references", "generate_ranked_report"],
    message: "Configured research tools only.",
  };
  const fetch = safeServer(runtime);
  assert.deepEqual(await connectionsApi.agent(), runtime);
  assert.equal(fetch.mock.calls.length, 1);
  assert.equal(fetch.mock.calls[0].arguments[0], "/api/connections/agent");
  const plan = {
    version: "test-plan",
    steps: ["Validate public evidence.", "Apply saved ranking preferences."],
    ranking_profile: null,
  };
  fetch.mock.mockImplementation(async () => Response.json(plan));
  assert.deepEqual(await connectionsApi.researchPlan(), plan);
  assert.equal(fetch.mock.calls[1].arguments[0], "/api/research-plan");
});
test("source readiness is verified metadata, not the presence of a stored API key", async () => {
  const source = {
    status: "verification_required",
    selectable: false,
    requires_credentials: true,
    verified_at: null,
    message: "Test the saved source connection.",
  };
  const fetch = safeServer({
    ...status,
    credentials: { ...status.credentials, materials_project: "session" },
    source_connections: { materials_project: source },
  });
  assert.equal(
    (await connectionsApi.status()).source_connections.materials_project
      .selectable,
    false,
  );
  fetch.mock.mockImplementation(async () =>
    Response.json({
      ...status,
      source_connections: {
        materials_project: {
          ...source,
          status: "ready",
          selectable: true,
          verified_at: "2026-09-09T12:00:00Z",
        },
      },
    }),
  );
  assert.equal(
    (await connectionsApi.status()).source_connections.materials_project
      .selectable,
    true,
  );
  fetch.mock.mockImplementation(async () =>
    Response.json({
      ...status,
      source_connections: {
        materials_project: { ...source, selectable: true },
      },
    }),
  );
  await assert.rejects(connectionsApi.status(), /unsupported response/);
});
