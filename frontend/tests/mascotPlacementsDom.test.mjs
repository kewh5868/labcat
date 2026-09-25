import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

const at = "2026-09-22T12:00:00Z";
const chat = {
  id: "chat-one",
  project_id: null,
  title: "Test research",
  chat_number: 1,
  display_title: "Test research · #1",
  created_at: at,
  updated_at: at,
  message_count: 0,
  pin_counts: { reports: 0, sources: 0 },
};
function response(stage = "complete", id = "report-new") {
  const message = {
    id: `message-${id}`,
    chat_id: chat.id,
    role: "assistant",
    content: "Saved findings.",
    report_id: id,
    created_at: at,
  };
  return {
    chat,
    messages: [
      {
        id: `question-${id}`,
        chat_id: chat.id,
        role: "user",
        content: "Compare materials.",
        report_id: null,
        created_at: at,
      },
      message,
    ],
    reports: [
      {
        id,
        project_id: null,
        chat_id: chat.id,
        message_id: message.id,
        title: "Findings",
        stage,
        pi_summary: "Summary.",
        technical_audit: "Details.",
        source_ids: [],
        created_at: at,
        pinned: false,
      },
    ],
    sources: [],
  };
}
const empty = () => ({ chat, messages: [], reports: [], sources: [] });

async function harness(t) {
  const output = await mkdtemp(join(tmpdir(), "labcat-mascot-placement-"));
  for (const name of await readdir(new URL("../src/", import.meta.url))) {
    if (!/\.tsx?$/.test(name)) continue;
    let source = await readFile(
      new URL(`../src/${name}`, import.meta.url),
      "utf8",
    );
    // Test real submit/navigation bindings without adding public component exports.
    if (name === "ProjectWorkspace.tsx")
      source += "\nexport { DraftChat, ChatView, completedResearchKey };";
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
  const react = import.meta.resolve("react");
  // Animation behavior has its own tests; this probe records exactly which
  // scene/completion signal the real request handlers pass to that boundary.
  await writeFile(
    join(output, "LabcatMascot.js"),
    `import {createElement as h} from '${react}';
    export default function Mascot({scene,completed}) { return h('div',{'data-scene':scene,'data-completed':String(Boolean(completed)),'aria-hidden':'true'}); }
    export function ResearchCompletionMascot({completionKey}) { return h('div',{'data-chat-mascot':'','data-completion-key':completionKey || '', 'aria-hidden':'true'}); }`,
  );
  await writeFile(
    join(output, "Connections.js"),
    `export const useConnections=()=>({loading:false,busy:false,error:'',status:null}); export const ConnectionNotice=()=>null; export const ConnectionsPanel=()=>null;`,
  );
  await writeFile(
    join(output, "SetupWizard.js"),
    `export const useSetup=()=>({loading:false,busy:false,error:'',status:{can_research:true},refresh:async()=>{}}); export default ()=>null;`,
  );
  await writeFile(
    join(output, "ComposerControls.js"),
    "export default ()=>null;",
  );
  await writeFile(join(output, "MaterialsFact.js"), "export default ()=>null;");
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
  const module = await import(
    pathToFileURL(join(output, "ProjectWorkspace.js")).href
  );
  const { defaultSettings } = await import(
    pathToFileURL(join(output, "workspaceApi.js")).href
  );
  const { useResearchRuns } = await import(
    pathToFileURL(join(output, "useResearchRuns.js")).href
  );
  const root = createRoot(document.getElementById("root"));
  const noOp = () => {};
  let currentResearch;
  // Keep submission ownership mounted while the direct child switches between
  // DraftChat and ChatView, matching ProjectWorkspace's navigation boundary.
  function ResearchHarness({ component: Component, properties }) {
    const research = useResearchRuns(noOp);
    currentResearch = research;
    return createElement(Component, { ...properties, research });
  }
  const common = {
    onOpenSettings: noOp,
    onOpenConnections: noOp,
    onRequireSetup: noOp,
  };
  const chatProps = {
    ...common,
    chatId: chat.id,
    projects: [],
    presentation: defaultSettings.presentation,
    initialDraft: "",
    initialResearchError: "",
    initialCompletionKey: "",
    onCompletionConsumed: noOp,
    initialRankingProfileId: "infer",
    onChanged: noOp,
    onMoveRequested: noOp,
    sidebarMoving: false,
    sidebarMoveRevision: 0,
    onBusyChange: noOp,
    searchMatch: null,
  };
  const draftProps = {
    ...common,
    project: null,
    onCreated: noOp,
    onOpen: noOp,
    onReload: noOp,
    loadingHistory: false,
  };
  t.after(async () => {
    await act(async () => root.unmount());
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
    await rm(output, { recursive: true, force: true });
  });
  return {
    ...module,
    act,
    dom,
    chatProps,
    draftProps,
    get research() {
      return currentResearch;
    },
    render: async (component, props) =>
      act(async () =>
        root.render(
          createElement(ResearchHarness, { component, properties: props }),
        ),
      ),
    submit: async () => {
      await act(async () => {
        const textarea = document.querySelector("textarea");
        Object.getOwnPropertyDescriptor(
          dom.window.HTMLTextAreaElement.prototype,
          "value",
        ).set.call(textarea, "Compare materials.");
        textarea.dispatchEvent(
          new dom.window.Event("input", { bubbles: true }),
        );
      });
      await act(async () =>
        document
          .querySelector("form")
          .dispatchEvent(
            new dom.window.Event("submit", { bubbles: true, cancelable: true }),
          ),
      );
    },
  };
}

test("completion is eligible only for a new complete or partial report linked to this response", async (t) => {
  const h = await harness(t);
  assert.equal(h.completedResearchKey(response()), "report-new");
  assert.equal(h.completedResearchKey(response("partial")), "report-new");
  for (const stage of ["failed", "running", "refused"])
    assert.equal(h.completedResearchKey(response(stage)), "");
  assert.equal(
    h.completedResearchKey(response(), response().reports),
    "",
    "an old saved report cannot trigger completion",
  );
  const clarification = response();
  clarification.messages.at(-1).report_id = null;
  assert.equal(h.completedResearchKey(clarification), "");
  const mismatched = response();
  mismatched.reports[0].message_id = "unrelated";
  assert.equal(h.completedResearchKey(mismatched), "");
  const userOnly = response();
  userOnly.messages.pop();
  assert.equal(h.completedResearchKey(userOnly), "");
});

test("first-chat submission opens immediately and consumes workspace completion once without navigating again", async (t) => {
  const h = await harness(t);
  let finish,
    loaded = empty();
  const opens = [];
  const writes = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    if (path === "/api/research-runs") return Response.json({ runs: [] });
    if (path === "/api/chats") {
      writes.push(path);
      return Response.json(chat);
    }
    if (path === "/api/chats/chat-one") return Response.json(loaded);
    if (path.endsWith("/messages")) {
      writes.push(path);
      await new Promise((resolve) => {
        finish = resolve;
      });
      loaded = response();
      return Response.json(loaded);
    }
    if (path.includes("/research-status?"))
      return Response.json({
        run_id: new URL(path, "http://localhost").searchParams.get("run_id"),
        status: "running",
        phase: "retrieving_evidence",
        message: "Looking for evidence.",
        started_at: at,
        updated_at: at,
        sequence: 1,
      });
    if (path.includes("/presentation?"))
      return Response.json({}, { status: 503 });
    throw new Error(`Unexpected request ${options?.method} ${path}`);
  });
  await h.render(h.DraftChat, {
    ...h.draftProps,
    onOpen: (...args) => opens.push(args),
  });
  await h.submit();
  assert.equal(
    opens.length,
    1,
    "the saved chat opens while its response is still pending",
  );
  assert.equal(opens[0][0], chat.id);
  assert.equal(
    opens[0][4],
    undefined,
    "navigation does not fabricate an early completion token",
  );
  assert.equal(
    document.querySelector('[data-scene="beaker"]').dataset.completed,
    "false",
  );
  await h.render(h.ChatView, h.chatProps);
  assert.equal(
    document.querySelector("[data-chat-mascot]").dataset.completionKey,
    "",
  );
  await h.act(async () => finish());
  assert.equal(opens.length, 1, "completion must not navigate a second time");
  assert.equal(
    document.querySelector("[data-chat-mascot]").dataset.completionKey,
    "report-new",
  );
  assert.ok(
    !h.research.runs[chat.id].completionKey,
    "the mounted view consumes the workspace completion token",
  );
  assert.equal(
    document.querySelector('[aria-label="Research progress"]'),
    null,
  );
  await h.render(() => null, {});
  await h.render(h.ChatView, h.chatProps);
  assert.equal(
    document.querySelector("[data-chat-mascot]").dataset.completionKey,
    "",
    "returning to saved history does not repeat the celebration",
  );
  assert.deepEqual(writes, ["/api/chats", "/api/chats/chat-one/messages"]);
});

test("saved-chat loading does not celebrate; successful send does, and next failed send clears it", async (t) => {
  const h = await harness(t);
  let loaded = response("complete", "report-old"),
    fail = false;
  let sends = 0;
  t.mock.method(globalThis, "fetch", async (path) => {
    if (path === "/api/research-runs") return Response.json({ runs: [] });
    if (path === "/api/chats/chat-one") return Response.json(loaded);
    if (path.includes("/presentation?"))
      return Response.json({}, { status: 503 });
    if (path.endsWith("/messages")) {
      sends++;
      if (fail)
        return Response.json(
          { detail: { code: "model_execution_failed", setup_required: false } },
          { status: 502 },
        );
      loaded = response();
      return Response.json(loaded);
    }
    if (path.includes("/research-status?"))
      return Response.json({
        run_id: new URL(path, "http://localhost").searchParams.get("run_id"),
        status: "running",
        phase: "retrieving_evidence",
        message: "Looking for evidence.",
        started_at: at,
        updated_at: at,
        sequence: 1,
      });
    throw new Error(`Unexpected request ${path}`);
  });
  await h.render(h.ChatView, h.chatProps);
  const key = () =>
    document.querySelector("[data-chat-mascot]").dataset.completionKey;
  assert.equal(key(), "", "history is not a newly completed request");
  await h.submit();
  assert.equal(sends, 1);
  assert.equal(key(), "report-new");
  assert.equal(document.querySelector("textarea").value, "");
  fail = true;
  await h.submit();
  assert.equal(sends, 2);
  assert.equal(key(), "");
  assert.match(
    document.body.textContent,
    /could not complete this research request/,
  );
  assert.equal(
    document.querySelector("textarea").value,
    "Compare materials.",
    "recognized research failure preserves the prompt for an explicit retry",
  );
});

test("navigation consumes a first-chat completion token once without modifying saved history", async (t) => {
  const h = await harness(t);
  let consumed = 0;
  const requests = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    if (path === "/api/research-runs") return Response.json({ runs: [] });
    requests.push(options.method);
    assert.equal(path, "/api/chats/chat-one");
    return Response.json(empty());
  });
  await h.render(h.ChatView, {
    ...h.chatProps,
    initialCompletionKey: "new-response",
    onCompletionConsumed: () => consumed++,
  });
  assert.equal(consumed, 1);
  assert.equal(
    document.querySelector("[data-chat-mascot]").dataset.completionKey,
    "new-response",
  );
  await h.render(h.ChatView, {
    ...h.chatProps,
    initialCompletionKey: "",
    onCompletionConsumed: () => consumed++,
  });
  assert.equal(consumed, 1);
  assert.deepEqual(requests, ["GET"]);
});
