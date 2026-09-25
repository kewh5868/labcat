import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import vm from "node:vm";

const script = await readFile(
  new URL("../public/structure-viewer/viewer.js", import.meta.url),
  "utf8",
);
// Coordinate-only protocol fixture. These numbers are not scientific evidence.
const cif = [
  "# Fixture, never a product result",
  "data_labcat_structure",
  "_symmetry_space_group_name_H-M 'P 1'",
  "_symmetry_Int_Tables_number 1",
  "_cell_length_a 1",
  "_cell_length_b 1",
  "_cell_length_c 1",
  "_cell_angle_alpha 90",
  "_cell_angle_beta 90",
  "_cell_angle_gamma 90",
  "loop_",
  "_symmetry_equiv_pos_as_xyz",
  "'x,y,z'",
  "loop_",
  "_atom_site_label",
  "_atom_site_type_symbol",
  "_atom_site_fract_x",
  "_atom_site_fract_y",
  "_atom_site_fract_z",
  "_atom_site_occupancy",
  "Si1 Si 0.000000000000 0.000000000000 1.000000000000 1",
  "",
].join("\n");

function runtime() {
  const messages = [],
    commands = [],
    handlers = {},
    nodes = {},
    info = {};
  const parent = { postMessage: (message) => messages.push(message) };
  const context = {
    URL,
    parent,
    window: {},
    location: { href: "http://127.0.0.1:8000/structure-viewer/index.html" },
    addEventListener: (type, handler) => {
      handlers[type] = handler;
    },
    document: {
      getElementById: (id) => (nodes[id] ??= {}),
      addEventListener: () => {},
    },
    Jmol: {
      setDocument: () => {},
      getApplet: (_name, options) => {
        Object.assign(info, options);
        return {};
      },
      getAppletHtml: () => {
        info.readyFunction();
        return "<canvas></canvas>";
      },
      scriptWait: (_applet, value) => commands.push(value),
      script: (_applet, value) => commands.push(value),
      evaluateVar: () => 1,
    },
  };
  vm.runInNewContext(script, context);
  const send = (data, options = {}) =>
    handlers.message({
      data,
      source: parent,
      origin: "http://127.0.0.1:8000",
      ...options,
    });
  return { send, info, messages, commands };
}
const channel = "01234567-89ab-cdef-0123-456789abcdef";

test("opaque viewer accepts only coordinate CIF and fixed authenticated controls", () => {
  const run = runtime();
  run.send({ type: "labcat-jsmol-load", channel, cif });
  assert.equal(run.info.allowJavaScript, false);
  assert.equal(run.info.serverURL, "");
  assert.equal(run.info.use, "HTML5");
  assert.ok(
    run.messages.some(
      (item) => item.type === "labcat-jsmol-loaded" && item.channel === channel,
    ),
  );
  assert.ok(run.commands[0].includes("set allowEmbeddedScripts false"));
  assert.ok(!run.commands[0].includes("# Fixture"));
  const before = run.commands.length;
  for (const command of [
    "load https://attacker.invalid/a",
    "javascript alert(1)",
    "console",
    "write /private/file",
  ])
    run.send({ type: "labcat-jsmol-command", channel, command });
  run.send({ type: "labcat-jsmol-command", channel: "wrong", command: "spin" });
  assert.equal(run.commands.length, before);
  run.send({ type: "labcat-jsmol-command", channel, command: "spin" });
  assert.equal(run.commands.at(-1), "spin on");
});

test("viewer rejects forged parent messages, scripts, malformed cell and coordinate payloads", () => {
  const forged = runtime();
  forged.send(
    { type: "labcat-jsmol-load", channel, cif },
    { origin: "https://attacker.invalid" },
  );
  forged.send({ type: "labcat-jsmol-load", channel, cif }, { source: {} });
  assert.equal(forged.commands.length, 0);
  for (const bad of [
    cif + 'END "model"; javascript alert(1)',
    cif.replace("90", "NaN"),
    cif.replace("0.000000000000", "https://attacker.invalid"),
    cif.replace("_atom_site_label", "<script>"),
    "A".repeat(500001),
  ]) {
    const run = runtime();
    run.send({ type: "labcat-jsmol-load", channel, cif: bad });
    assert.equal(run.commands.length, 0);
    assert.equal(run.messages.at(-1).type, "labcat-jsmol-error");
  }
});

test("cached coordinate exports retain support without allowing arbitrary data blocks", () => {
  const legacy = cif.replace(
    "data_labcat_structure",
    "data_labagent_structure",
  );
  const run = runtime();
  run.send({ type: "labcat-jsmol-load", channel, cif: legacy });
  assert.ok(run.messages.some((item) => item.type === "labcat-jsmol-loaded"));
  assert.ok(run.commands[0].includes("data_labcat_structure"));
  assert.ok(!run.commands[0].includes("data_labagent_structure"));
  assert.ok(
    legacy.includes("data_labagent_structure"),
    "the saved input stays unchanged",
  );
  for (const header of [
    "data_other",
    "data_labagent_structure extra",
    "data_labagent_structure; script evil",
  ]) {
    const invalid = runtime();
    invalid.send({
      type: "labcat-jsmol-load",
      channel,
      cif: cif.replace("data_labcat_structure", header),
    });
    assert.equal(invalid.commands.length, 0);
    assert.equal(invalid.messages.at(-1).type, "labcat-jsmol-error");
  }
});

test("readiness can be replayed for a late parent listener without loading a structure", () => {
  const run = runtime();
  const before = run.messages.length;
  run.send(
    { type: "labcat-jsmol-hello" },
    { origin: "https://attacker.invalid" },
  );
  run.send({ type: "labcat-jsmol-hello" }, { source: {} });
  assert.equal(run.messages.length, before);
  run.send({ type: "labcat-jsmol-hello" });
  assert.equal(run.messages.at(-1).type, "labcat-jsmol-ready");
  assert.equal(run.commands.length, 0);
  run.send({ type: "labcat-jsmol-load", channel, cif });
  const loaded = run.messages.length;
  run.send({ type: "labcat-jsmol-hello" });
  assert.equal(
    run.messages.length,
    loaded,
    "an initialized frame is not loaded twice",
  );
});
