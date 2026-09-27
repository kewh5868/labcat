import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

const source = await readFile(
  new URL("../src/chatRankingPreferences.ts", import.meta.url),
  "utf8",
);
const compiled = ts
  .transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ES2022,
    },
  })
  .outputText.replace('from "react"', `from "${import.meta.resolve("react")}"`);
const { useChatRankingPreferences, recordedRankingChoice } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);
const key = "labcat-chat-ranking-v1";
const chatA = "580b51aa-0b53-436c-91d2-14c163b2b001";
const chatB = "580b51aa-0b53-436c-91d2-14c163b2b002";
const report = (selection, created_at = "2026-09-27T12:00:00Z") => ({
  id: "report-default",
  created_at,
  result: { execution: { ranking_selection: selection } },
});

test("saved reports restore the requested selection, never freeze an inferred profile", () => {
  assert.equal(recordedRankingChoice([]), null);
  assert.equal(
    recordedRankingChoice([
      report({ mode: "explicit", requested_profile_id: "profile-custom" }),
    ]),
    "profile-custom",
  );
  for (const mode of [
    "inferred",
    "semantic_inferred",
    "fallback",
    "continued",
  ]) {
    assert.equal(
      recordedRankingChoice([
        report({ mode, selected_profile_id: "preset-oxide" }),
      ]),
      "infer",
      mode,
    );
  }
  assert.equal(
    recordedRankingChoice([
      report({
        mode: "active",
        requested_profile_id: null,
        selected_profile_id: "preset-oxide",
      }),
    ]),
    null,
  );
  assert.equal(
    recordedRankingChoice([
      report({ mode: "explicit", requested_profile_id: "<script>" }),
    ]),
    null,
  );
  assert.equal(
    recordedRankingChoice([
      report({ mode: "explicit", requested_profile_id: "profile-custom" }),
      report(
        { mode: "inferred", requested_profile_id: "infer" },
        "2026-09-27T13:00:00Z",
      ),
    ]),
    "infer",
    "only the latest report controls restoration",
  );
  assert.equal(
    recordedRankingChoice([
      report({ mode: "explicit", requested_profile_id: "profile-custom" }),
      { created_at: "2026-09-27T13:00:00Z", result: {} },
    ]),
    null,
    "missing latest metadata does not resurrect an older manual choice",
  );
  for (const newest of ["infer", "profile-new"]) {
    assert.equal(
      recordedRankingChoice([
        {
          ...report({ mode: "explicit", requested_profile_id: "profile-old" }),
          id: "report-a",
        },
        {
          ...report({ mode: "explicit", requested_profile_id: newest }),
          id: "report-z",
        },
      ]),
      newest,
      "equal timestamps use the server's descending report ID tie-break",
    );
  }
});

test("per-chat choices survive app remounts, keep infer authoritative, and bound optional storage", async (t) => {
  const dom = new JSDOM('<div id="root"></div>', { url: "http://localhost/" });
  const keys = ["window", "document", "navigator", "IS_REACT_ACT_ENVIRONMENT"];
  const previous = Object.fromEntries(
    keys.map((name) => [
      name,
      Object.getOwnPropertyDescriptor(globalThis, name),
    ]),
  );
  for (const name of keys)
    Object.defineProperty(globalThis, name, {
      configurable: true,
      writable: true,
      value: name === "IS_REACT_ACT_ENVIRONMENT" ? true : dom.window[name],
    });
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  let current;
  function Harness() {
    current = useChatRankingPreferences();
    return null;
  }
  let root = createRoot(document.getElementById("root"));
  const mount = () => act(async () => root.render(createElement(Harness)));
  const remount = async () => {
    await act(async () => root.unmount());
    root = createRoot(document.getElementById("root"));
    await mount();
  };
  t.after(async () => {
    await act(async () => root.unmount());
    dom.window.close();
    for (const name of keys) {
      if (previous[name])
        Object.defineProperty(globalThis, name, previous[name]);
      else delete globalThis[name];
    }
  });
  await mount();
  await act(async () => {
    current.select(chatA, "profile-custom");
    current.select(chatB, "preset-other");
  });
  await remount();
  assert.equal(current.choices[chatA], "profile-custom");
  assert.equal(current.choices[chatB], "preset-other");
  await act(async () => {
    current.select(chatA, "infer");
    current.select(chatA, "profile-custom", true);
    current.select(chatB, "infer", true);
  });
  assert.equal(
    current.choices[chatA],
    "infer",
    "late report restoration cannot overwrite explicit infer",
  );
  assert.equal(
    current.choices[chatB],
    "preset-other",
    "other chats remain independent",
  );
  await remount();
  assert.equal(
    current.choices[chatA],
    "infer",
    "infer remains explicit after browser restart",
  );
  await act(async () => current.select("fresh-chat", "profile-restored", true));
  assert.equal(current.choices["fresh-chat"], "profile-restored");
  await act(async () => {
    for (let index = 0; index < 205; index++)
      current.select(`chat-${index}`, "profile-custom");
  });
  assert.equal(Object.keys(current.choices).length, 200);
  assert.equal(
    Object.keys(JSON.parse(window.localStorage.getItem(key))).length,
    200,
  );
  assert.equal(
    current.choices[chatA],
    undefined,
    "older entries are bounded, not accumulated forever",
  );
  window.localStorage.setItem(
    key,
    '{"valid-chat":"infer", "other-chat":42, "malicious-chat":"<html>"}',
  );
  await remount();
  assert.deepEqual(current.choices, { "valid-chat": "infer" });
  window.localStorage.setItem(key, "{");
  await remount();
  assert.deepEqual(current.choices, {});
  window.localStorage.setItem(key, " ".repeat(60_001));
  await remount();
  assert.deepEqual(current.choices, {});
  t.mock.method(dom.window.Storage.prototype, "getItem", () => {
    throw new Error("Storage disabled");
  });
  t.mock.method(dom.window.Storage.prototype, "setItem", () => {
    throw new Error("Storage disabled");
  });
  await remount();
  await act(async () => current.select(chatA, "profile-session"));
  assert.equal(
    current.choices[chatA],
    "profile-session",
    "blocked storage does not disable manual selection",
  );
});
