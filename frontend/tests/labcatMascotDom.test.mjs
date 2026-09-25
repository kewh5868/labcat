import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

const activityEvents = [
  "pointerdown",
  "pointermove",
  "keydown",
  "wheel",
  "touchstart",
  "focusin",
];

async function fixture(
  t,
  {
    enabled = true,
    buildSetting,
    reduced = false,
    chat = false,
    props = {},
  } = {},
) {
  const directory = await mkdtemp(join(tmpdir(), "labcat-mascot-"));
  let config = await readFile(
    new URL("../src/labcatMascotConfig.ts", import.meta.url),
    "utf8",
  );
  if (!enabled)
    config = config.replace(
      "ENABLE_LABCAT_MASCOTS = true",
      "ENABLE_LABCAT_MASCOTS = false",
    );
  if (buildSetting !== undefined)
    config = config.replace(
      "import.meta.env?.VITE_LABCAT_MASCOTS",
      JSON.stringify(buildSetting),
    );
  const source = await readFile(
    new URL("../src/LabcatMascot.tsx", import.meta.url),
    "utf8",
  );
  for (const [name, input] of [
    ["labcatMascotConfig", config],
    ["LabcatMascot", source],
  ]) {
    const output = ts
      .transpileModule(input, {
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
          `from '${specifier.startsWith("./") ? `${specifier}.mjs` : import.meta.resolve(specifier)}'`,
      );
    await writeFile(join(directory, `${name}.mjs`), output);
  }
  const dom = new JSDOM(
    '<div id="root"></div><input id="draft" value="Keep this draft">',
    { url: "http://localhost/", pretendToBeVisual: true },
  );
  const style = dom.window.document.createElement("style");
  style.textContent = await readFile(
    new URL("../src/labcatMascot.css", import.meta.url),
    "utf8",
  );
  dom.window.document.head.append(style);
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
      configurable: true,
      writable: true,
    });
  const mediaListeners = new Set();
  const media = {
    matches: reduced,
    addEventListener: (_event, callback) => mediaListeners.add(callback),
    removeEventListener: (_event, callback) => mediaListeners.delete(callback),
  };
  Object.defineProperty(window, "matchMedia", { value: () => media });
  const activityListeners = new Map(
    activityEvents.map((event) => [event, new Set()]),
  );
  const addEventListener = window.addEventListener.bind(window);
  const removeEventListener = window.removeEventListener.bind(window);
  t.mock.method(window, "addEventListener", (event, callback, options) => {
    if (activityListeners.has(event)) {
      assert.equal(
        options.passive,
        true,
        "presence listeners cannot cancel input",
      );
      activityListeners.get(event).add(callback);
    }
    addEventListener(event, callback, options);
  });
  t.mock.method(window, "removeEventListener", (event, callback, options) => {
    activityListeners.get(event)?.delete(callback);
    removeEventListener(event, callback, options);
  });
  const timers = new Map();
  let serial = 0;
  t.mock.method(window, "setTimeout", (callback, delay) => {
    const id = ++serial;
    timers.set(id, { callback, delay });
    return id;
  });
  t.mock.method(window, "clearTimeout", (id) => timers.delete(id));
  t.mock.method(globalThis, "fetch", () =>
    assert.fail(
      "mascots cannot call research, accounts, or other network APIs",
    ),
  );
  const { act, createElement } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const module = await import(
    pathToFileURL(join(directory, "LabcatMascot.mjs")).href
  );
  const Component = chat ? module.ResearchCompletionMascot : module.default;
  const root = createRoot(document.getElementById("root"));
  const render = async (next = props) =>
    act(async () =>
      root.render(
        createElement(Component, chat ? next : { scene: "beaker", ...next }),
      ),
    );
  await render();
  t.after(async () => {
    await act(async () => root.unmount());
    assert.equal(timers.size, 0, "all timers are cleaned up");
    assert.equal(mediaListeners.size, 0, "preference listeners are cleaned up");
    assert.equal(
      [...activityListeners.values()].reduce(
        (count, listeners) => count + listeners.size,
        0,
      ),
      0,
      "activity listeners are cleaned up",
    );
    assert.equal(
      document.getElementById("draft").value,
      "Keep this draft",
      "decoration never modifies user content",
    );
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
    await rm(directory, { recursive: true, force: true });
  });
  return {
    dom,
    act,
    render,
    timers,
    mediaListeners,
    activityListeners,
    mascot: () => document.querySelector(".labcat-mascot"),
    activityCount: () =>
      [...activityListeners.values()].reduce(
        (count, listeners) => count + listeners.size,
        0,
      ),
    tick: async (expectedDelay) => {
      assert.equal(timers.size, 1);
      const [id, timer] = timers.entries().next().value;
      assert.equal(timer.delay, expectedDelay);
      timers.delete(id);
      await act(async () => timer.callback());
    },
    motion: async (value) => {
      media.matches = value;
      await act(async () => {
        for (const listener of mediaListeners) listener();
      });
    },
    visibility: async (hidden) => {
      Object.defineProperty(document, "hidden", {
        value: hidden,
        configurable: true,
      });
      await act(async () =>
        document.dispatchEvent(new dom.window.Event("visibilitychange")),
      );
    },
  };
}

test("the source switch removes images, timers and activity listeners entirely", async (t) => {
  const view = await fixture(t, {
    enabled: false,
    chat: true,
    props: { completionKey: "new-report" },
  });
  assert.equal(view.mascot(), null);
  assert.equal(document.querySelector("img"), null);
  assert.equal(view.timers.size, 0);
  assert.equal(view.mediaListeners.size, 0);
  assert.equal(view.activityCount(), 0);
});

test("the build switch disables standard scenes without requiring browser environment injection", async (t) => {
  const view = await fixture(t, {
    buildSetting: "false",
    props: { scene: "wires" },
  });
  assert.equal(view.mascot(), null);
  assert.equal(view.timers.size, 0);
  assert.equal(view.mediaListeners.size, 0);
});

test("sprite decoration has no controls or announcements and completion is explicit", async (t) => {
  const view = await fixture(t);
  assert.equal(view.mascot().getAttribute("aria-hidden"), "true");
  assert.equal(view.mascot().querySelector("img").alt, "");
  assert.equal(view.mascot().querySelector("img").draggable, false);
  assert.equal(
    view
      .mascot()
      .querySelectorAll(
        'button, input, [tabindex], [role="status"], [role="alert"]',
      ).length,
    0,
  );
  assert.equal(view.mascot().dataset.animation, "beaker");
  assert.equal(
    view.timers.size,
    0,
    "CSS advances frames without per-frame JavaScript",
  );
  await view.render({ completed: true });
  assert.equal(view.mascot().dataset.animation, "beaker-complete");
  await view.render({ completed: false });
  assert.equal(
    view.mascot().dataset.animation,
    "beaker",
    "elapsed time or render count cannot imply success",
  );
});

test("loading holds the cat and vessel in a single pose while only the clipped liquid changes color", async (t) => {
  const view = await fixture(t);
  const base = view.mascot().querySelector(".labcat-mascot-sheet");
  const liquid = view.mascot().querySelector(".labcat-mascot-liquid-sheet");
  assert.ok(liquid, "the liquid has an independent decorative layer");
  assert.equal(
    liquid.src,
    base.src,
    "both layers use the same existing frame geometry",
  );
  assert.equal(view.dom.window.getComputedStyle(base).animation, "none");
  assert.equal(
    view.dom.window.getComputedStyle(base).transform,
    "translate(0, 0)",
  );
  assert.equal(
    view.dom.window.getComputedStyle(liquid).transform,
    "translate(0, 0)",
  );
  assert.match(
    view.dom.window.getComputedStyle(liquid).animation,
    /^labcat-liquid-color /,
  );
  assert.match(
    view.dom.window.getComputedStyle(liquid.parentElement).clipPath,
    /^polygon\(/,
  );
  assert.equal(view.timers.size, 0);
  await view.visibility(true);
  assert.equal(
    view.dom.window.getComputedStyle(liquid).animationPlayState,
    "paused",
  );
  await view.motion(true);
  assert.equal(view.dom.window.getComputedStyle(liquid).animation, "none");
  assert.equal(view.dom.window.getComputedStyle(liquid).filter, "none");
  await view.render({ completed: true });
  assert.equal(
    view.mascot().querySelector(".labcat-mascot-liquid"),
    null,
    "only processing adds the color layer",
  );
});

test("a failed liquid overlay quietly removes the entire processing decoration", async (t) => {
  const view = await fixture(t);
  await view.act(async () =>
    view
      .mascot()
      .querySelector(".labcat-mascot-liquid-sheet")
      .dispatchEvent(new view.dom.window.Event("error")),
  );
  assert.equal(view.mascot(), null);
  assert.equal(view.mediaListeners.size, 0);
  assert.equal(view.timers.size, 0);
});

test("reduced motion suppresses the completion flourish without timers", async (t) => {
  const view = await fixture(t, {
    chat: true,
    reduced: true,
    props: { completionKey: "success" },
  });
  assert.equal(view.mascot(), null);
  assert.equal(view.timers.size, 0);
  assert.equal(view.activityCount(), 0);
  await view.motion(false);
  assert.equal(
    view.mascot(),
    null,
    "changing motion preferences cannot replay an old completion",
  );
  assert.equal(view.timers.size, 0);
});

test("background tabs pause remaining standard sprites without activity monitoring", async (t) => {
  const view = await fixture(t);
  assert.equal(view.timers.size, 0);
  await view.visibility(true);
  assert.equal(view.mascot().dataset.paused, "true");
  assert.equal(view.timers.size, 0);
  assert.equal(view.activityCount(), 0);
  await view.visibility(false);
  assert.equal(view.mascot().dataset.paused, "false");
});

test("dormant chats have no desk image, timers or activity listeners", async (t) => {
  const view = await fixture(t, { chat: true });
  assert.equal(view.mascot(), null);
  assert.equal(document.querySelector("img"), null);
  assert.equal(view.timers.size, 0);
  assert.equal(view.mediaListeners.size, 0);
  assert.equal(view.activityCount(), 0);
  await view.act(async () =>
    window.dispatchEvent(
      new view.dom.window.KeyboardEvent("keydown", { key: "a", bubbles: true }),
    ),
  );
  await view.render({ key: "different-chat" });
  assert.equal(view.mascot(), null);
  assert.equal(view.timers.size, 0);
});

test("new successful report keys briefly celebrate without delaying or calling the research system", async (t) => {
  const view = await fixture(t, { chat: true });
  await view.render({ completionKey: "report-a" });
  assert.equal(view.mascot().dataset.animation, "beaker-complete");
  const timer = [...view.timers.keys()][0];
  await view.render({ completionKey: "report-a" });
  assert.equal(
    [...view.timers.keys()][0],
    timer,
    "unrelated rerenders never restart a celebration",
  );
  await view.visibility(true);
  assert.equal(view.timers.size, 0);
  await view.visibility(false);
  await view.tick(2_400);
  assert.equal(view.mascot(), null);
  assert.equal(view.timers.size, 0);
  assert.equal(view.activityCount(), 0);
  assert.equal(view.mediaListeners.size, 0);
  await view.render({ completionKey: "report-a" });
  assert.equal(
    view.mascot(),
    null,
    "rerendering the same report cannot restart a finished flourish",
  );
  await view.render({ completionKey: "report-b" });
  assert.equal(view.mascot().dataset.animation, "beaker-complete");
  await view.tick(2_400);
  assert.equal(
    view.mascot(),
    null,
    "the finite flourish disappears after completion",
  );
  assert.equal(view.timers.size, 0);
});

test("a missing sprite fails quietly and removes optional listeners and timers", async (t) => {
  const view = await fixture(t, {
    chat: true,
    props: { completionKey: "new-report" },
  });
  await view.act(async () =>
    view
      .mascot()
      .querySelector("img")
      .dispatchEvent(new view.dom.window.Event("error")),
  );
  assert.equal(view.mascot(), null);
  assert.equal(view.timers.size, 0);
  assert.equal(view.mediaListeners.size, 0);
  assert.equal(view.activityCount(), 0);
  assert.equal(document.querySelector('[role="alert"]'), null);
});
