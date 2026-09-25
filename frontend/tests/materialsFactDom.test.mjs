import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

async function fixture(t, { reduced = false, random = () => 0 } = {}) {
  const output = await mkdtemp(join(tmpdir(), "labcat-materials-fact-"));
  const source = await readFile(
    new URL("../src/MaterialsFact.tsx", import.meta.url),
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
      (_match, _quote, specifier) => `from '${import.meta.resolve(specifier)}'`,
    );
  await writeFile(join(output, "MaterialsFact.mjs"), compiled);
  const dom = new JSDOM(
    '<div id="root"></div><button id="outside">Outside</button>',
    { url: "http://localhost/", pretendToBeVisual: true },
  );
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
  const preferenceListeners = new Set();
  const preference = {
    matches: reduced,
    addEventListener: (_event, callback) => preferenceListeners.add(callback),
    removeEventListener: (_event, callback) =>
      preferenceListeners.delete(callback),
  };
  Object.defineProperty(window, "matchMedia", { value: () => preference });
  const timers = new Map();
  let serial = 0;
  t.mock.method(window, "setTimeout", (callback, delay) => {
    const id = ++serial;
    timers.set(id, { callback, delay });
    return id;
  });
  t.mock.method(window, "clearTimeout", (id) => timers.delete(id));
  t.mock.method(globalThis, "fetch", () => {
    assert.fail(
      "educational facts never fetch research or send workspace requests",
    );
  });
  t.mock.method(Math, "random", random);
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { default: MaterialsFact } = await import(
    pathToFileURL(join(output, "MaterialsFact.mjs")).href
  );
  const root = createRoot(document.getElementById("root"));
  const render = async (key = "first-chat") =>
    act(async () => root.render(createElement(MaterialsFact, { key })));
  await render();
  t.after(async () => {
    await act(async () => root.unmount());
    assert.equal(timers.size, 0, "unmount removes the fact timer");
    assert.equal(
      preferenceListeners.size,
      0,
      "unmount removes the preference listener",
    );
    dom.window.close();
    for (const key of globals) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
    await rm(output, { recursive: true, force: true });
  });
  const click = async (label) => {
    const button = [
      ...document.querySelectorAll(".materials-fact button"),
    ].find(
      (item) =>
        (item.getAttribute("aria-label") ?? item.textContent.trim()) === label,
    );
    assert.ok(button, `button ${label} exists`);
    await act(async () =>
      button.dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true }),
      ),
    );
  };
  return {
    dom,
    timers,
    act,
    click,
    render,
    region: () =>
      document.querySelector('aside[aria-label="Materials science fact"]'),
    copy: () => document.querySelector(".materials-fact-copy").textContent,
    tick: async () => {
      assert.equal(timers.size, 1);
      const [id, timer] = timers.entries().next().value;
      assert.equal(timer.delay, 20_000, "facts rotate slowly");
      timers.delete(id);
      await act(async () => timer.callback());
    },
    motion: async (matches) => {
      preference.matches = matches;
      await act(async () => {
        for (const callback of preferenceListeners) callback();
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

test("each educational fact carries its own primary citation and manual navigation wraps", async (t) => {
  const view = await fixture(t);
  const seen = new Map();
  const first = view.copy();
  const approvedHosts = new Set([
    "www.nobelprize.org",
    "science.nasa.gov",
    "www.nasa.gov",
    "spinoff.nasa.gov",
    "news.mit.edu",
    "www.energy.gov",
    "mooregroup.beckman.illinois.edu",
    "www.cam.ac.uk",
    "www.nist.gov",
    "edu.rsc.org",
  ]);
  for (let index = 0; index < 20; index++) {
    const link = view.region().querySelector("a");
    assert.equal(new URL(link.href).protocol, "https:");
    assert.ok(approvedHosts.has(new URL(link.href).hostname));
    assert.match(link.textContent, /^Source: \S/);
    assert.match(link.getAttribute("aria-label"), /^Read source: \S/);
    assert.equal(link.target, "_blank");
    assert.equal(link.rel, "noopener noreferrer");
    seen.set(view.copy(), link.href);
    await view.click("Next fact →");
  }
  assert.equal(seen.size, 20);
  assert.equal(
    new Set(seen.values()).size,
    19,
    "two polymer demonstrations share their primary source",
  );
  assert.equal(view.copy(), first);
  assert.equal(
    view.region().getAttribute("aria-live"),
    "off",
    "automatic changes do not repeatedly announce to screen readers",
  );
  assert.equal(
    view
      .region()
      .querySelectorAll('form, textarea, [role="status"], [role="alert"]')
      .length,
    0,
  );
});

test("new chats start randomly without repeating the last displayed fact; ordinary renders stay put", async (t) => {
  let sample = 0.99;
  const view = await fixture(t, { random: () => sample });
  assert.match(view.copy(), /Piezoelectric materials/);
  sample = 0;
  await view.render();
  assert.match(
    view.copy(),
    /Piezoelectric materials/,
    "typing and other rerenders must not change the fact",
  );
  await view.render("second-chat");
  assert.match(view.copy(), /adhesive tape/);
  await view.click("Next fact →");
  assert.match(view.copy(), /Stardust/);
  sample = 1 / 19;
  await view.render("third-chat");
  assert.match(
    view.copy(),
    /Quasicrystals/,
    "exclude the last displayed fact, including manual navigation",
  );
  sample = 0.99;
  await view.render("fourth-chat");
  assert.match(
    view.copy(),
    /Piezoelectric materials/,
    "a new chat can sample the far end of the collection",
  );
});

test("rotation stops for user pause, focus, hover and background tabs", async (t) => {
  const view = await fixture(t);
  const first = view.copy();
  await view.tick();
  assert.notEqual(view.copy(), first);
  await view.click("Pause automatic facts");
  assert.equal(view.timers.size, 0);
  await view.click("Next fact →");
  assert.equal(view.timers.size, 0, "manual navigation preserves user pause");
  await view.click("Resume automatic facts");
  assert.equal(view.timers.size, 1);
  await view.act(async () => view.region().querySelector("a").focus());
  assert.equal(view.timers.size, 0);
  await view.act(async () => document.getElementById("outside").focus());
  assert.equal(view.timers.size, 1);
  await view.act(async () =>
    view.region().dispatchEvent(
      new view.dom.window.MouseEvent("mouseover", {
        bubbles: true,
        relatedTarget: document.body,
      }),
    ),
  );
  assert.equal(view.timers.size, 0);
  await view.act(async () =>
    view.region().dispatchEvent(
      new view.dom.window.MouseEvent("mouseout", {
        bubbles: true,
        relatedTarget: document.body,
      }),
    ),
  );
  assert.equal(view.timers.size, 1);
  await view.visibility(true);
  assert.equal(view.timers.size, 0);
  await view.visibility(false);
  assert.equal(view.timers.size, 1);
});

test("reduced motion stays static while keeping manual facts and respects preference changes", async (t) => {
  const view = await fixture(t, { reduced: true });
  assert.equal(view.timers.size, 0);
  assert.equal(view.region().querySelectorAll("button").length, 1);
  const initial = view.copy();
  await view.click("Next fact →");
  assert.notEqual(view.copy(), initial);
  assert.equal(view.timers.size, 0);
  await view.motion(false);
  assert.equal(view.timers.size, 1);
  await view.motion(true);
  assert.equal(view.timers.size, 0);
});
