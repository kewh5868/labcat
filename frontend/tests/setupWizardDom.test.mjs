import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

async function compile() {
  const output = await mkdtemp(join(tmpdir(), "labcat-setup-ui-"));
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
const setupFixture = () => ({
  version: 1,
  completed: false,
  current_step: "model",
  required: true,
  can_research: false,
  model: {
    status: "verification_required",
    provider: "chatgpt",
    model: "fixture-model",
    account_id: "fixture-account",
    message: "Check the selected connection.",
    checked_at: null,
  },
  optional: {
    compute: "local",
    aws_required: false,
    data_apis_required: false,
  },
});

test("required model verification gates setup, optional services skip without writes, and a locked restart returns to sign-in", async (t) => {
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
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { ConnectionsProvider } = await import(
    pathToFileURL(join(output, "Connections.js")).href
  );
  const { default: SetupWizard, SetupProvider } = await import(
    pathToFileURL(join(output, "SetupWizard.js")).href
  );
  const profile = {
    provider: "chatgpt",
    model: "fixture-model",
    allow_paid_inference: true,
    ollama_url: "http://localhost:11434",
    aws_profile: "",
    aws_region: "",
  };
  const account = {
    id: "fixture-account",
    label: "Fixture account",
    profile,
    credential_state: "encrypted",
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
  let setup = setupFixture(),
    allowVerify = false,
    completed = 0,
    closed = 0;
  let holdVerification = false,
    finishVerification,
    verificationUnavailable = false;
  const calls = [],
    errors = [];
  t.mock.method(console, "error", (...args) => errors.push(args.join(" ")));
  t.mock.method(globalThis, "fetch", async (path, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({ path, method: options.method ?? "GET", body });
    if (path === "/api/session")
      return Response.json({ csrf_token: "FIXTURE-CSRF-LONG-ENOUGH" });
    if (path === "/api/connections") return Response.json(status);
    if (path === "/api/connections/models")
      return Response.json({
        provider: "chatgpt",
        models: [
          { id: "fixture-model", label: "Fixture model" },
          { id: "fixture-other", label: "Other fixture model" },
        ],
        message: "Returned test models only.",
        inference_tested: false,
      });
    if (
      path === "/api/connections/accounts/fixture-account" &&
      options.method === "PUT"
    ) {
      Object.assign(profile, body.profile);
      setup = {
        ...setup,
        can_research: false,
        model: {
          ...setup.model,
          status: "verification_required",
          model: profile.model,
        },
      };
      return Response.json(status);
    }
    if (path === "/api/connections/setup") {
      if (options.method === "PUT") setup.current_step = body.current_step;
      return Response.json(setup);
    }
    if (path === "/api/connections/setup/verify") {
      if (verificationUnavailable)
        return Response.json(
          { detail: "Synthetic unavailable service." },
          { status: 503 },
        );
      if (holdVerification)
        await new Promise((resolve) => {
          finishVerification = resolve;
        });
      setup = {
        ...setup,
        can_research: allowVerify,
        model: {
          ...setup.model,
          status: allowVerify ? "ready" : "error",
          message: allowVerify
            ? "Connection verified without inference."
            : "Provider check failed. Try again.",
          checked_at: "2026-09-10T12:00:00Z",
        },
      };
      return Response.json(setup);
    }
    if (path === "/api/connections/setup/complete") {
      assert.equal(setup.can_research, true);
      setup.completed = true;
      return Response.json(setup);
    }
    if (path === "/api/connections/aws-profiles")
      return Response.json({
        profiles: ["fixture-research"],
        regions: ["us-west-2"],
        setup: {
          commands: [],
          documentation_url:
            "https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html",
          message: "Fixture installation profiles only.",
        },
      });
    if (path === "/api/public-sources") return Response.json({ sources: [] });
    if (path === "/api/source-settings")
      return Response.json({
        search_public_references: true,
        enabled_sources: ["arxiv"],
        materials_project_mode: "auto",
        max_results_per_source: 3,
      });
    assert.fail(`Unexpected request ${path}`);
  });
  const root = createRoot(document.getElementById("root"));
  const tree = (key = "initial", open = true) =>
    createElement(
      ConnectionsProvider,
      { key },
      createElement(
        SetupProvider,
        null,
        createElement(SetupWizard, {
          open,
          onClose: () => {
            closed++;
          },
          onComplete: () => {
            completed++;
          },
        }),
      ),
    );
  const button = (name) => {
    const result = [...document.querySelectorAll("button")].find(
      (item) => item.textContent.trim() === name,
    );
    assert.ok(result, name);
    return result;
  };
  const primary = () => document.querySelector(".setup-footer .primary-button");
  const click = async (item) => {
    assert.equal(item.disabled, false, `${item.textContent} enabled`);
    await act(async () =>
      item.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })),
    );
  };
  try {
    await act(async () => root.render(tree()));
    assert.equal(document.querySelectorAll('[role="dialog"]').length, 1);
    assert.equal(
      document.querySelectorAll("textarea").length,
      0,
      "setup does not create a research composer",
    );
    assert.equal(
      document.getElementById("root").inert,
      true,
      "background workspace is inert while setup is open",
    );
    assert.equal(
      document.querySelector("#setup-heading"),
      document.activeElement,
    );
    assert.equal(
      button("Verify and continue").disabled,
      false,
      "a saved account can be verified from the footer",
    );
    assert.equal(
      primary().getAttribute("aria-busy"),
      "false",
      "an idle action is not a busy operation",
    );
    assert.match(
      document.querySelector(".setup-footer").textContent,
      /No inference is run/,
    );
    assert.match(
      document.querySelector(".setup-readiness strong").textContent,
      /ready to check/,
    );
    assert.equal(
      [...document.querySelectorAll("button")].filter(
        (item) => item.textContent === "Verify connection",
      ).length,
      1,
      "the model card retains its standalone verification action",
    );
    assert.doesNotMatch(
      document.body.textContent,
      /No model account required|Start with local defaults/,
    );
    assert.equal(
      document.querySelector("#model-provider").value,
      "chatgpt",
      "connected users can still choose another provider",
    );
    assert.match(
      document.querySelector("#model-provider option:checked").textContent,
      /ChatGPT/,
    );
    assert.equal(document.querySelector("#model-account-name"), null);
    assert.equal(
      calls.filter((item) => item.path.endsWith("/verify")).length,
      0,
      "opening does not contact a provider",
    );
    await click(button("Verify connection"));
    assert.match(
      document.querySelector(".setup-readiness").textContent,
      /Provider check failed/,
    );
    assert.equal(
      setup.current_step,
      "model",
      "failed metadata check cannot advance",
    );
    await click(button("Verify and continue"));
    assert.equal(
      setup.current_step,
      "model",
      "footer verification failure also stays on the model step",
    );
    assert.match(
      document.querySelector(".setup-footer").textContent,
      /Provider check failed/,
    );
    assert.match(
      document.querySelector(".setup-readiness strong").textContent,
      /needs attention/,
    );
    assert.equal(
      calls.filter(
        (item) =>
          item.path === "/api/connections/setup" && item.method === "PUT",
      ).length,
      0,
      "failed checks never save progress",
    );
    verificationUnavailable = true;
    const footerSetupReads = calls.filter(
      (item) => item.path === "/api/connections/setup" && item.method === "GET",
    ).length;
    await click(button("Verify and continue"));
    assert.equal(setup.current_step, "model");
    assert.match(
      document.querySelector(".setup-footer").textContent,
      /503/,
      "transport errors are visible beside the action",
    );
    assert.equal(
      button("Verify and continue").disabled,
      false,
      "a failed footer request can be explicitly retried",
    );
    assert.equal(
      calls.filter(
        (item) =>
          item.path === "/api/connections/setup" && item.method === "GET",
      ).length,
      footerSetupReads,
      "retry does not restore stale readiness by reloading",
    );
    verificationUnavailable = false;
    allowVerify = true;
    holdVerification = true;
    const footerVerifications = calls.filter((item) =>
      item.path.endsWith("/verify"),
    ).length;
    const footerAction = button("Verify and continue");
    await act(async () => {
      footerAction.dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true }),
      );
      footerAction.dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true }),
      );
    });
    assert.equal(
      calls.filter((item) => item.path.endsWith("/verify")).length,
      footerVerifications + 1,
      "rapid duplicate clicks start one verification",
    );
    assert.equal(primary().disabled, true);
    assert.equal(primary().getAttribute("aria-busy"), "true");
    assert.equal(
      document.querySelector("#model-choice").matches(":disabled"),
      true,
      "the model cannot change during footer verification",
    );
    assert.equal(
      document.querySelector(".cloud-consent input").matches(":disabled"),
      true,
      "consent cannot change during footer verification",
    );
    assert.equal(
      setup.current_step,
      "model",
      "verification must resolve before progress",
    );
    holdVerification = false;
    await act(async () => finishVerification());
    assert.equal(
      setup.current_step,
      "compute",
      "footer advances after successful verification",
    );
    await click(button("Back"));
    const verifiedCount = calls.filter((item) =>
      item.path.endsWith("/verify"),
    ).length;
    await click(button("Continue"));
    assert.equal(setup.current_step, "compute");
    assert.equal(
      calls.filter((item) => item.path.endsWith("/verify")).length,
      verifiedCount,
      "ready Continue reuses the successful verification",
    );
    await click(button("Back"));
    allowVerify = true;
    await click(button("Verify connection"));
    assert.equal(
      button("Continue").disabled,
      false,
      "successful card verification updates setup readiness",
    );
    verificationUnavailable = true;
    const setupReads = calls.filter(
      (item) => item.path === "/api/connections/setup" && item.method === "GET",
    ).length;
    await click(button("Verify connection"));
    assert.equal(
      button("Continue").disabled,
      true,
      "a failed verification request cannot restore an older ready state",
    );
    assert.match(document.querySelector(".workspace-error").textContent, /503/);
    assert.equal(
      calls.filter(
        (item) =>
          item.path === "/api/connections/setup" && item.method === "GET",
      ).length,
      setupReads,
      "automatic refresh does not erase a failed verification",
    );
    verificationUnavailable = false;
    await click(button("Verify connection"));
    assert.equal(
      button("Continue").disabled,
      false,
      "explicit retry can recover after a failed verification request",
    );
    const catalogCalls = calls.filter(
      (item) => item.path === "/api/connections/models",
    ).length;
    await act(async () => {
      const model = document.querySelector("#model-choice");
      model.value = "fixture-other";
      model.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    holdVerification = true;
    await click(button("Save and test connections"));
    assert.equal(primary().disabled, true);
    assert.equal(primary().getAttribute("aria-busy"), "true");
    assert.equal(
      calls.filter((item) => item.path === "/api/connections/models").length,
      catalogCalls,
      "automatic catalog refresh cannot overlap save/verification",
    );
    assert.equal(
      calls.filter((item) => item.path === "/api/connections/test").length,
      0,
      "onboarding never substitutes a generic test for setup verification",
    );
    assert.equal(typeof finishVerification, "function");
    holdVerification = false;
    await act(async () => finishVerification());
    assert.equal(
      button("Continue").disabled,
      false,
      "Save and test now enables Continue with no redundant verification",
    );
    assert.equal(button("Continue").getAttribute("aria-busy"), "false");
    assert.match(
      document.querySelector(".connection-test-results").textContent,
      /Model connection · Ready/,
    );
    assert.equal(
      calls.filter((item) => item.path === "/api/connections/models").length,
      catalogCalls + 1,
      "changed saved settings refresh models once after verification",
    );
    await act(async () => {
      const model = document.querySelector("#model-choice");
      model.value = "";
      model.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    assert.equal(
      button("Continue").disabled,
      true,
      "unsaved model edits cannot use the saved connection verification",
    );
    assert.match(
      document.querySelector(".setup-footer").textContent,
      /Save and test your connection changes/,
    );
    assert.equal(
      button("Verify connection").disabled,
      true,
      "verification checks the saved selection only",
    );
    await click(button("Reload saved settings"));
    await click(button("Continue"));
    assert.equal(setup.current_step, "compute");
    assert.match(
      document.body.textContent,
      /does not move the application or deploy cloud infrastructure/,
    );
    assert.equal(
      document.querySelector(".setup-optional-toggle input").checked,
      false,
    );
    assert.ok(
      button("Skip for now"),
      "AWS has an explicit skip action before editing",
    );
    await click(document.querySelector(".setup-optional-toggle input"));
    assert.equal(document.querySelector("#model-provider").value, "bedrock");
    const awsProfile = document.querySelector("#aws-profile");
    assert.equal(awsProfile.value, "");
    assert.equal(awsProfile.options[0].disabled, true);
    assert.doesNotMatch(awsProfile.textContent, /Default credential chain/);
    assert.equal(
      button("Save and test connections").disabled,
      true,
      "AWS save needs an installed named profile and region",
    );
    assert.equal(
      profile.provider,
      "chatgpt",
      "merely opening optional AWS cannot change the active model",
    );
    await click(document.querySelector(".setup-optional-toggle input"));
    await click(button("Continue"));
    assert.equal(setup.current_step, "sources");
    assert.match(
      document.body.textContent,
      /NOMAD, HybriD³, Europe PMC and arXiv/,
    );
    assert.equal(
      document.querySelector("#model-provider"),
      null,
      "source step contains no duplicate model form",
    );
    assert.ok(
      document.querySelector(
        '[aria-label="Materials Project connection"] input[type="password"]',
      ),
    );
    const ids = [...document.querySelectorAll("[id]")].map((item) => item.id);
    assert.equal(
      ids.length,
      new Set(ids).size,
      "each form field has a unique accessible label target",
    );
    assert.equal(
      document.querySelector(".public-search-toggle"),
      null,
      "source selection lives in Search Criterion, not credential setup",
    );
    await click(button("Skip for now"));
    assert.equal(setup.current_step, "review");
    const reviewModel = document.querySelector("#setup-review-model");
    assert.ok(reviewModel, "the final review has an inline model selector");
    assert.equal(reviewModel.value, "fixture-other");
    assert.equal(reviewModel.disabled, false);
    holdVerification = true;
    await act(async () => {
      reviewModel.value = "fixture-model";
      reviewModel.dispatchEvent(
        new dom.window.Event("change", { bubbles: true }),
      );
    });
    assert.equal(
      button("Verifying…").disabled,
      true,
      "Finish waits for the newly selected model verification",
    );
    assert.equal(document.querySelector("#setup-review-model").disabled, true);
    assert.equal(
      setup.current_step,
      "review",
      "changing a model stays on the review page",
    );
    holdVerification = false;
    await act(async () => finishVerification());
    assert.equal(
      document.querySelector("#setup-review-model").value,
      "fixture-model",
    );
    assert.equal(button("Finish setup").disabled, false);
    assert.match(
      document.querySelector(".setup-review-model").textContent,
      /fixture-model is selected and ready/,
    );
    allowVerify = false;
    await act(async () => {
      reviewModel.value = "fixture-other";
      reviewModel.dispatchEvent(
        new dom.window.Event("change", { bubbles: true }),
      );
    });
    assert.equal(
      button("Finish setup").disabled,
      true,
      "failed review verification cannot reuse old readiness",
    );
    assert.equal(
      profile.model,
      "fixture-other",
      "a saved model is retained when verification fails",
    );
    assert.equal(setup.current_step, "review");
    const reviewWrites = calls.filter(
      (item) => item.path.includes("/accounts/") && item.method === "PUT",
    ).length;
    allowVerify = true;
    await click(button("Retry connection check"));
    assert.equal(button("Finish setup").disabled, false);
    assert.equal(
      calls.filter(
        (item) => item.path.includes("/accounts/") && item.method === "PUT",
      ).length,
      reviewWrites,
      "retrying verification does not resave credentials",
    );
    const finishButton = button("Finish setup");
    await act(async () => {
      finishButton.dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true }),
      );
      finishButton.dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true }),
      );
    });
    assert.equal(completed, 1);
    assert.equal(
      calls.filter((item) => item.path === "/api/connections/setup/complete")
        .length,
      1,
      "rapid Finish clicks complete setup only once",
    );
    assert.deepEqual(
      calls.filter(
        (item) => item.method !== "GET" && item.path === "/api/source-settings",
      ),
      [],
      "skipping does not change source preferences",
    );
    assert.ok(
      !calls.some(
        (item) =>
          (item.path.includes("aws") && item.method !== "GET") ||
          item.path.includes("local-defaults"),
      ),
      "skipping AWS does not provision or change compute",
    );
    assert.equal(window.localStorage.length, 0);
    assert.equal(window.sessionStorage.length, 0);
    profile.allow_paid_inference = false;
    setup = {
      ...setup,
      can_research: false,
      model: {
        ...setup.model,
        status: "consent_required",
        message: "Allow this provider to receive research context first.",
        checked_at: null,
      },
    };
    await act(async () => root.render(tree("no-consent")));
    assert.equal(
      button("Continue").disabled,
      true,
      "missing cloud consent cannot use the footer verification shortcut",
    );
    assert.match(
      document.querySelector(".setup-readiness strong").textContent,
      /Allow this provider/,
    );
    assert.match(
      document.querySelector(".setup-footer").textContent,
      /Allow this provider to receive research context/,
    );
    const gatedChecks = calls.filter((item) =>
      item.path.endsWith("/verify"),
    ).length;
    await act(async () =>
      primary().dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true }),
      ),
    );
    assert.equal(
      calls.filter((item) => item.path.endsWith("/verify")).length,
      gatedChecks,
    );
    profile.allow_paid_inference = true;
    const savedModel = profile.model;
    for (const [modelStatus, credentialState, message] of [
      ["model_required", "encrypted", "Choose a model for this connection."],
      [
        "not_connected",
        "missing",
        "Sign in or add the selected provider's API credential.",
      ],
    ]) {
      profile.model = modelStatus === "model_required" ? "" : savedModel;
      account.credential_state = credentialState;
      setup = {
        ...setup,
        can_research: false,
        model: {
          ...setup.model,
          status: modelStatus,
          model: profile.model,
          message,
          checked_at: null,
        },
      };
      await act(async () => root.render(tree(modelStatus)));
      assert.equal(
        button("Continue").disabled,
        true,
        `${modelStatus} cannot use the footer verification shortcut`,
      );
      assert.ok(
        document.querySelector(".setup-footer").textContent.includes(message),
      );
      await act(async () =>
        primary().dispatchEvent(
          new dom.window.MouseEvent("click", { bubbles: true }),
        ),
      );
      assert.equal(
        calls.filter((item) => item.path.endsWith("/verify")).length,
        gatedChecks,
      );
    }
    profile.model = savedModel;
    setup = {
      ...setup,
      can_research: false,
      model: {
        ...setup.model,
        status: "credentials_locked",
        message: "Unlock your encrypted credentials.",
        checked_at: null,
      },
    };
    status.vault.locked = true;
    status.vault.available = false;
    account.credential_state = "locked";
    await act(async () => root.render(tree("restart")));
    assert.match(
      document.querySelector(".setup-readiness").textContent,
      /Unlock your saved connection/,
    );
    assert.equal(document.querySelector("#vault-unlock")?.type, "password");
    assert.equal(button("Continue").disabled, true);
    assert.match(
      document.querySelector(".setup-footer").textContent,
      /Unlock your encrypted credentials/,
    );
    const first = document.querySelector(".setup-topline button");
    first.focus();
    await act(async () =>
      document.dispatchEvent(
        new dom.window.KeyboardEvent("keydown", {
          key: "Tab",
          shiftKey: true,
          bubbles: true,
          cancelable: true,
        }),
      ),
    );
    assert.notEqual(
      document.activeElement,
      first,
      "focus wraps around disabled Continue",
    );
    assert.ok(
      document
        .querySelector('[role="dialog"]')
        .contains(document.activeElement),
    );
    await act(async () =>
      document.dispatchEvent(
        new dom.window.KeyboardEvent("keydown", {
          key: "Escape",
          bubbles: true,
          cancelable: true,
        }),
      ),
    );
    assert.equal(
      closed,
      1,
      "history access is available without marking setup complete",
    );
    await act(async () => root.render(tree("restart", false)));
    assert.equal(document.querySelector('[role="dialog"]'), null);
    assert.equal(document.getElementById("root").inert, undefined);
    await act(async () => root.render(tree("restart", true)));
    assert.equal(document.querySelectorAll('[role="dialog"]').length, 1);
    assert.equal(button("Continue").disabled, true);
    assert.deepEqual(errors, []);
  } finally {
    await act(async () => root.unmount());
    assert.equal(document.getElementById("root").inert, undefined);
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
    await rm(output, { recursive: true, force: true });
  }
});

for (const scenario of [
  "committed response lost",
  "uncommitted response lost",
  "readiness rejected",
  "completed but readiness lost",
  "recovery unavailable",
]) {
  test(`Finish setup recovers correctly when ${scenario}`, async (t) => {
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
    const { createElement, act, useState } = await import("react");
    const { createRoot } = await import("react-dom/client");
    const { ConnectionsProvider } = await import(
      pathToFileURL(join(output, "Connections.js")).href
    );
    const { default: SetupWizard, SetupProvider } = await import(
      pathToFileURL(join(output, "SetupWizard.js")).href
    );
    const profile = {
      provider: "chatgpt",
      model: "fixture-model",
      allow_paid_inference: true,
      ollama_url: "http://localhost:11434",
      aws_profile: "",
      aws_region: "",
    };
    const account = {
      id: "fixture-account",
      label: "Fixture account",
      profile,
      credential_state: "session",
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
        available: false,
        locked: false,
        exists: false,
        can_create: true,
        key_source: "unavailable",
      },
      warnings: [],
      accounts: [account],
      active_account_id: account.id,
    };
    let setup = {
      ...setupFixture(),
      current_step: "review",
      can_research: true,
      model: {
        ...setupFixture().model,
        status: "ready",
        message: "Saved model connection verified.",
        checked_at: "2026-09-11T12:00:00Z",
      },
    };
    let completed = 0,
      attempted = false,
      retryWorks = false;
    const calls = [],
      errors = [];
    t.mock.method(console, "error", (...args) => errors.push(args.join(" ")));
    t.mock.method(globalThis, "fetch", async (path, options = {}) => {
      calls.push({ path, method: options.method ?? "GET" });
      if (path === "/api/session")
        return Response.json({ csrf_token: "FIXTURE-CSRF-LONG-ENOUGH" });
      if (path === "/api/connections") return Response.json(status);
      if (path === "/api/connections/models")
        return Response.json({
          provider: "chatgpt",
          models: [{ id: "fixture-model", label: "Fixture model" }],
          message: "Fixture metadata only.",
          inference_tested: false,
        });
      if (
        path === "/api/connections/setup" &&
        (!options.method || options.method === "GET")
      ) {
        if (attempted && scenario === "recovery unavailable")
          return Response.json(
            { detail: "PRIVATE-RECOVERY-DIAGNOSTIC" },
            { status: 503 },
          );
        return Response.json(setup);
      }
      if (path === "/api/connections/setup/complete") {
        attempted = true;
        if (retryWorks) {
          setup = { ...setup, completed: true, current_step: "review" };
          return Response.json(setup);
        }
        if (scenario === "committed response lost")
          setup = { ...setup, completed: true, current_step: "review" };
        if (
          scenario === "readiness rejected" ||
          scenario === "completed but readiness lost"
        ) {
          setup = {
            ...setup,
            completed: scenario === "completed but readiness lost",
            can_research: false,
            model: {
              ...setup.model,
              status: "error",
              message: "The connection needs a fresh verification.",
              checked_at: null,
            },
          };
          return Response.json(
            { detail: "PRIVATE-READINESS-DIAGNOSTIC" },
            { status: 422 },
          );
        }
        throw new TypeError("PRIVATE-COMPLETE-NETWORK-DIAGNOSTIC");
      }
      assert.fail(`Unexpected request ${options.method ?? "GET"} ${path}`);
    });
    function Harness() {
      const [open, setOpen] = useState(true);
      return createElement(
        ConnectionsProvider,
        null,
        createElement(
          SetupProvider,
          null,
          createElement(SetupWizard, {
            open,
            onClose: () => setOpen(false),
            onComplete: () => {
              completed++;
              setOpen(false);
            },
          }),
        ),
      );
    }
    const root = createRoot(document.getElementById("root"));
    const button = (name) => {
      const found = [...document.querySelectorAll("button")].find(
        (item) => item.textContent.trim() === name,
      );
      assert.ok(found, `${name} exists`);
      return found;
    };
    const click = async (item) => {
      assert.equal(item.disabled, false, `${item.textContent} is enabled`);
      await act(async () =>
        item.dispatchEvent(
          new dom.window.MouseEvent("click", { bubbles: true }),
        ),
      );
    };
    try {
      await act(async () => root.render(createElement(Harness)));
      assert.match(
        document.querySelector("#setup-heading").textContent,
        /workspace is ready to connect/,
      );
      const beforeReads = calls.filter(
        (item) => item.path === "/api/connections/setup",
      ).length;
      await click(button("Finish setup"));
      assert.equal(
        calls.filter((item) => item.path === "/api/connections/setup/complete")
          .length,
        1,
        "an uncertain completion is not automatically repeated",
      );
      assert.ok(
        calls.filter((item) => item.path === "/api/connections/setup").length >
          beforeReads,
        "completion recovery reads authoritative saved setup",
      );
      assert.equal(
        calls.filter((item) => item.path === "/api/connections/setup/verify")
          .length,
        0,
        "recovery does not create an extra verification request",
      );
      assert.doesNotMatch(document.body.textContent, /PRIVATE-/);
      if (scenario === "committed response lost") {
        assert.equal(
          completed,
          1,
          "authoritative completed and ready state exits setup despite a lost response",
        );
        assert.equal(
          document.querySelector(".setup-window"),
          null,
          "recovery cannot bounce back to Model after completion",
        );
      } else if (
        scenario === "readiness rejected" ||
        scenario === "completed but readiness lost"
      ) {
        assert.equal(
          completed,
          0,
          "completion requires both persisted completion and current readiness",
        );
        assert.match(
          document.querySelector("#setup-heading").textContent,
          /Connect your research model/,
        );
        assert.match(
          document.querySelector(".setup-readiness").textContent,
          /fresh verification/,
        );
      } else {
        assert.equal(
          completed,
          0,
          "unconfirmed completion never opens the research workspace as ready",
        );
        assert.match(
          document.querySelector("#setup-heading").textContent,
          /workspace is ready to connect/,
          "an uncertain response alone does not require a new sign-in",
        );
        if (scenario === "uncommitted response lost") {
          retryWorks = true;
          await click(button("Finish setup"));
          assert.equal(
            completed,
            1,
            "an explicit retry may complete an uncommitted operation",
          );
          assert.equal(
            calls.filter(
              (item) => item.path === "/api/connections/setup/complete",
            ).length,
            2,
          );
        } else {
          assert.ok(
            button("Reload setup"),
            "unavailable recovery has a read-only retry action",
          );
        }
      }
      assert.deepEqual(
        calls.filter(
          (item) =>
            item.path.includes("/accounts/") || item.path.includes("/login"),
        ),
        [],
        "completion recovery neither changes credentials nor starts login",
      );
      assert.deepEqual(errors, []);
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
}

test("setup transport rejects secret-bearing and inconsistent readiness and writes only CSRF-protected progress", async (t) => {
  const output = await compile();
  const previous = globalThis.window;
  globalThis.window = { setTimeout, clearTimeout };
  const { parseSetup, setupApi } = await import(
    pathToFileURL(join(output, "setupApi.js")).href
  );
  const state = setupFixture();
  const calls = [];
  try {
    assert.deepEqual(parseSetup(state), state);
    assert.equal(
      parseSetup({
        ...state,
        optional: { ...state.optional, compute: "aws_bedrock" },
      }).optional.compute,
      "aws_bedrock",
    );
    for (const invalid of [
      { ...state, access_token: "FIXTURE_SECRET" },
      { ...state, model: { ...state.model, api_key: "FIXTURE_SECRET" } },
      { ...state, can_research: true },
      { ...state, required: false },
    ])
      assert.throws(() => parseSetup(invalid), /unsupported response/);
    t.mock.method(globalThis, "fetch", async (path, options) => {
      calls.push({ path, options });
      return Response.json(
        path === "/api/session"
          ? { csrf_token: "FIXTURE-CSRF-LONG-ENOUGH" }
          : state,
      );
    });
    await setupApi.progress("sources");
    assert.equal(calls[0].path, "/api/session");
    assert.deepEqual(JSON.parse(calls[1].options.body), {
      current_step: "sources",
    });
    assert.equal(
      calls[1].options.headers["X-CSRF-Token"],
      "FIXTURE-CSRF-LONG-ENOUGH",
    );
    assert.equal(calls[1].options.credentials, "same-origin");
    assert.equal(calls[1].options.redirect, "error");
    await setupApi.verify();
    await setupApi.complete();
    assert.ok(
      calls
        .filter(
          (item) =>
            item.path.endsWith("/verify") || item.path.endsWith("/complete"),
        )
        .every((item) => item.options.body === "{}"),
    );
  } finally {
    globalThis.window = previous;
    await rm(output, { recursive: true, force: true });
  }
});

test("busy Verify and Continue actions show fixed waiting guidance without retry or sign-in reset", async (t) => {
  const output = await compile();
  const previous = globalThis.window;
  globalThis.window = { setTimeout, clearTimeout };
  const { setupApi, setupError } = await import(
    pathToFileURL(join(output, "setupApi.js")).href
  );
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return path === "/api/session"
      ? Response.json({ csrf_token: "FIXTURE-CSRF-LONG-ENOUGH" })
      : Response.json(
          { detail: "PRIVATE_PROVIDER_DIAGNOSTIC" },
          { status: 409 },
        );
  });
  try {
    for (const action of ["verify", "complete"]) {
      await assert.rejects(setupApi[action](), (error) => {
        assert.match(
          setupError(error),
          /^Setup cannot continue while another account check or research request is running\. Wait.*try this step again/,
        );
        assert.doesNotMatch(
          setupError(error),
          /PRIVATE_PROVIDER|reload|sign.in/i,
        );
        return true;
      });
    }
    assert.deepEqual(
      calls.map(({ path }) => path),
      [
        "/api/session",
        "/api/connections/setup/verify",
        "/api/session",
        "/api/connections/setup/complete",
      ],
      "only the two user-requested actions run",
    );
    assert.ok(
      calls
        .filter(({ path }) => path !== "/api/session")
        .every(
          ({ options }) => options.method === "POST" && options.body === "{}",
        ),
    );
  } finally {
    globalThis.window = previous;
    await rm(output, { recursive: true, force: true });
  }
});
