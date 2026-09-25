import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, before, test } from "node:test";
import ts from "typescript";

let output, summarize;
before(async () => {
  output = await mkdtemp(join(tmpdir(), "labcat-model-summary-"));
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
  ({ modelConnectionSummary: summarize } = await import(
    pathToFileURL(join(output, "modelConnectionSummary.js")).href
  ));
});
after(async () => {
  if (output) await rm(output, { recursive: true, force: true });
});

function fixture(provider = "chatgpt", credential = "session") {
  const profile = {
    provider,
    model: "fixture-selected-model",
    allow_paid_inference: true,
    ollama_url: "http://localhost:11434",
    aws_profile: "fixture-profile",
    aws_region: "us-west-2",
  };
  const account = {
    id: "fixture-account",
    label: "Fixture account",
    profile: { ...profile },
    credential_state: credential,
  };
  return {
    status: {
      configured: true,
      using_local_defaults: false,
      profile,
      credentials: {
        materials_project: "missing",
        openai: provider === "openai" ? credential : "missing",
        anthropic: provider === "anthropic" ? credential : "missing",
        kimi: provider === "kimi" ? credential : "missing",
        gemini: provider === "gemini" ? credential : "missing",
        deepseek: provider === "deepseek" ? credential : "missing",
        xai: provider === "xai" ? credential : "missing",
        openrouter: provider === "openrouter" ? credential : "missing",
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
    },
    readiness: {
      version: 1,
      completed: true,
      current_step: "review",
      required: true,
      can_research: true,
      model: {
        status: "ready",
        provider,
        model: profile.model,
        account_id: account.id,
        message: "Account and model verified. No inference was run.",
        checked_at: "2026-09-11T12:00:00Z",
      },
      optional: {
        compute: provider === "bedrock" ? "aws_bedrock" : "local",
        aws_required: false,
        data_apis_required: false,
      },
    },
  };
}
function assertUnconfirmed(summary, message) {
  assert.equal(summary.available, false, message);
  assert.doesNotMatch(summary.title, /· (?:Signed in|Connected)$/, message);
}

test("a matching verified ChatGPT session clearly confirms sign-in and the selected model", () => {
  for (const credential of ["session", "encrypted"]) {
    const input = fixture("chatgpt", credential),
      snapshot = structuredClone(input);
    const summary = summarize(input);
    assert.equal(summary.title, "ChatGPT · Signed in");
    assert.equal(summary.available, true);
    assert.match(summary.note, /fixture-selected-model/);
    assert.deepEqual(
      input,
      snapshot,
      "displaying readiness cannot mutate connection or setup state",
    );
  }
});

test("verified API and AWS connections use connected wording without claiming browser sign-in", () => {
  for (const [provider, label, credential] of [
    ["openai", "OpenAI", "encrypted"],
    ["anthropic", "Anthropic", "session"],
    ["kimi", "Kimi", "session"],
    ["gemini", "Google Gemini", "session"],
    ["deepseek", "DeepSeek", "encrypted"],
    ["xai", "xAI", "session"],
    ["openrouter", "OpenRouter", "encrypted"],
    ["bedrock", "Amazon Bedrock", "not_required"],
  ]) {
    const input = fixture(provider, credential);
    const summary = summarize(input);
    assert.equal(summary.title, `${label} · Connected`);
    assert.equal(summary.available, true);
    assert.match(summary.note, /fixture-selected-model/);
    input.readiness = {
      ...input.readiness,
      can_research: false,
      model: {
        ...input.readiness.model,
        status: "verification_required",
        checked_at: null,
      },
    };
    assertUnconfirmed(
      summarize(input),
      "stored API credentials alone do not verify a provider",
    );
  }
});

test("saved and expired verification states remain actionable without claiming logout or current readiness", () => {
  const input = fixture();
  input.readiness = {
    ...input.readiness,
    can_research: false,
    model: {
      ...input.readiness.model,
      status: "verification_required",
      checked_at: null,
    },
  };
  const summary = summarize(input);
  assert.equal(summary.title, "ChatGPT · Check connection");
  assert.match(summary.note, /fixture-selected-model/);
  assertUnconfirmed(
    summary,
    "completed setup does not mean its expired verification is current",
  );
  for (const state of ["model_required", "consent_required"]) {
    const incomplete = structuredClone(input);
    incomplete.readiness.model.status = state;
    if (state === "model_required") {
      incomplete.status.profile.model = "";
      incomplete.status.accounts[0].profile.model = "";
      incomplete.readiness.model.model = "";
    } else {
      incomplete.status.profile.allow_paid_inference = false;
      incomplete.status.accounts[0].profile.allow_paid_inference = false;
    }
    const action = summarize(incomplete);
    assertUnconfirmed(action, `${state} cannot claim readiness`);
    assert.match(
      `${action.title} ${action.note}`,
      state === "model_required" ? /choose.*model/i : /allow.*research/i,
    );
  }
  input.readiness = null;
  assertUnconfirmed(
    summarize(input),
    "an unread setup state cannot confirm a saved account",
  );
});

test("missing and locked credentials override stale ready metadata", () => {
  for (const [credential, title] of [
    ["missing", "ChatGPT · Not signed in"],
    ["locked", "ChatGPT · Connection locked"],
  ]) {
    const input = fixture("chatgpt", credential);
    const summary = summarize(input);
    assert.equal(summary.title, title);
    assertUnconfirmed(
      summary,
      "stored verification must not override missing or locked credentials",
    );
  }
  for (const provider of [
    "openai",
    "anthropic",
    "kimi",
    "gemini",
    "deepseek",
    "xai",
    "openrouter",
  ]) {
    for (const credential of ["missing", "locked", "not_required"])
      assertUnconfirmed(
        summarize(fixture(provider, credential)),
        "API providers require actual usable saved credentials",
      );
  }
  const withoutAccount = fixture();
  withoutAccount.status.accounts = [];
  assertUnconfirmed(
    summarize(withoutAccount),
    "an absent active account cannot be reported signed in",
  );
});

test("stale account, provider, model, and consent states cannot inherit another verification", () => {
  const cases = [
    (input) => {
      input.readiness.model.account_id = "different-account";
    },
    (input) => {
      input.readiness.model.provider = "anthropic";
    },
    (input) => {
      input.readiness.model.model = "previous-model";
    },
    (input) => {
      input.status.active_account_id = "different-account";
    },
    (input) => {
      input.status.accounts[0].profile.provider = "anthropic";
    },
    (input) => {
      input.status.accounts[0].profile.model = "another-model";
    },
    (input) => {
      input.status.accounts[0].profile.allow_paid_inference = false;
    },
    (input) => {
      input.status.accounts[0].profile.aws_region = "another-region";
    },
    (input) => {
      input.status.profile.model = "";
    },
    (input) => {
      input.status.profile.allow_paid_inference = false;
    },
    (input) => {
      input.readiness.can_research = false;
    },
    (input) => {
      input.readiness.model.status = "verification_required";
    },
    (input) => {
      input.readiness.model.checked_at = null;
    },
  ];
  for (const change of cases) {
    const input = fixture();
    change(input);
    assertUnconfirmed(
      summarize(input),
      "success must be bound to the selected usable account and exact model",
    );
  }
});

test("legacy API credentials can be verified without incorrectly granting an accountless ChatGPT sign-in", () => {
  const input = fixture("openai", "encrypted");
  input.status.accounts = [];
  input.status.active_account_id = null;
  input.readiness.model.account_id = null;
  const verified = summarize(input);
  assert.equal(verified.title, "OpenAI · Connected");
  assert.equal(verified.available, true);
  input.status.credentials.openai = "locked";
  assertUnconfirmed(summarize(input));
  input.status.credentials.openai = "missing";
  assertUnconfirmed(summarize(input));
  const chatgpt = fixture();
  chatgpt.status.accounts = [];
  chatgpt.status.active_account_id = null;
  chatgpt.readiness.model.account_id = null;
  assertUnconfirmed(
    summarize(chatgpt),
    "ChatGPT sign-in must belong to a saved OAuth account",
  );
});

test("pending reads and errors suppress stale success and provide clear status labels", () => {
  const input = fixture();
  const pending = summarize({ ...input, checking: true });
  assert.equal(pending.title, "ChatGPT · Checking connection…");
  assertUnconfirmed(pending);
  const unavailable = summarize({ ...input, unavailable: true });
  assert.equal(unavailable.title, "ChatGPT · Status unavailable");
  assertUnconfirmed(unavailable);
  input.readiness.model.status = "error";
  input.readiness.can_research = false;
  const failed = summarize(input);
  assert.equal(failed.title, "ChatGPT · Connection needs attention");
  assertUnconfirmed(failed);
  for (const value of [
    { status: null, readiness: null },
    { status: null, readiness: null, checking: true },
    { status: null, readiness: null, unavailable: true },
  ]) {
    const result = summarize(value);
    assertUnconfirmed(
      result,
      "an unavailable connection has no success indicator",
    );
    assert.equal(typeof result.title, "string");
    assert.ok(result.title.length > 0);
    assert.equal(typeof result.note, "string");
  }
});
