/* Labcat's fixed JSmol host. This file runs only in an opaque, no-network sandbox. */
(() => {
  "use strict";
  const parentOrigin = new URL(location.href).origin;
  const status = document.getElementById("status");
  let applet,
    channel,
    initialized = false,
    loaded = false,
    spinning = false;
  function tell(type) {
    parent.postMessage({ type, channel }, parentOrigin);
  }
  function fail() {
    status.textContent =
      "Unable to display this structure. Use the CIF download in the report.";
    tell("labcat-jsmol-error");
  }

  // Accept only the canonical coordinate-only CIF produced by our adapter. Drop
  // provenance comments before parsing; no scripts, filenames, URLs or HTML enter Jmol.
  function coordinateCif(input) {
    if (
      typeof input !== "string" ||
      input.length > 500000 ||
      /[^\x09\x0a\x0d\x20-\x7e]/.test(input)
    )
      throw Error("Invalid CIF");
    const lines = input
      .split(/\r?\n/)
      .filter((line) => line && !line.startsWith("#"));
    // Older cached exports keep their original bytes and provenance. Normalize
    // only this exact historical data-block name before the same strict checks.
    if (lines[0] === "data_labagent_structure")
      lines[0] = "data_labcat_structure";
    const head = [
      "data_labcat_structure",
      "_symmetry_space_group_name_H-M 'P 1'",
      "_symmetry_Int_Tables_number 1",
    ];
    if (!head.every((line, i) => lines[i] === line))
      throw Error("Invalid CIF header");
    const numeric = "(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+)(?:[eE][+-]?[0-9]+)?";
    const fields = [
      "length_a",
      "length_b",
      "length_c",
      "angle_alpha",
      "angle_beta",
      "angle_gamma",
    ];
    fields.forEach((field, i) => {
      if (!new RegExp(`^_cell_${field} ${numeric}$`).test(lines[i + 3] || ""))
        throw Error("Invalid cell");
      const value = Number(lines[i + 3].split(" ")[1]);
      if (!Number.isFinite(value) || value <= 0 || value > (i < 3 ? 1000 : 180))
        throw Error("Invalid cell");
    });
    const loop = [
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
    ];
    if (!loop.every((line, i) => lines[i + 9] === line))
      throw Error("Invalid atom loop");
    const atoms = lines.slice(19);
    if (!atoms.length || atoms.length > 2000) throw Error("Invalid site count");
    atoms.forEach((line, i) => {
      const parts = line.split(" ");
      if (
        parts.length !== 6 ||
        !/^[A-Z][a-z]?$/.test(parts[1]) ||
        parts[0] !== parts[1] + (i + 1) ||
        parts[5] !== "1" ||
        !parts
          .slice(2, 5)
          .every((value) => /^[01]\.\d{12}$/.test(value) && Number(value) <= 1)
      )
        throw Error("Invalid coordinates");
    });
    return lines.join("\n") + "\n";
  }

  function show(cif) {
    const fixed =
      "set allowEmbeddedScripts false; set disablePopupMenu true; set frank off; set antialiasDisplay true; set perspectiveDepth false; background [xF6F8F3];";
    Jmol.setDocument(0);
    applet = Jmol.getApplet("labcatCrystal", {
      width: "100%",
      height: "100%",
      use: "HTML5",
      color: "#F6F8F3",
      j2sPath: new URL("vendor/j2s", location.href).href,
      serverURL: "",
      allowJavaScript: false,
      addSelectionOptions: false,
      disableInitialConsole: true,
      disableJ2SLoadMonitor: true,
      debug: false,
      language: "en",
      script: fixed,
      readyFunction: () => {
        try {
          Jmol.scriptWait(
            applet,
            fixed +
              '\nload DATA "model"\n' +
              cif +
              'END "model"; unitcell on; axes off; spacefill 23%; wireframe 0.12; zoom 80;',
          );
          const count = Number(Jmol.evaluateVar(applet, "{*}.count"));
          if (!Number.isFinite(count) || count < 1) {
            fail();
            return;
          }
          loaded = true;
          status.textContent = "";
          tell("labcat-jsmol-loaded");
        } catch {
          fail();
        }
      },
    });
    document.getElementById("viewer").innerHTML = Jmol.getAppletHtml(applet);
  }

  addEventListener("message", (event) => {
    if (
      parent === window ||
      event.source !== parent ||
      event.origin !== parentOrigin ||
      !event.data ||
      typeof event.data !== "object"
    )
      return;
    const data = event.data;
    if (data.type === "labcat-jsmol-hello" && !initialized) {
      tell("labcat-jsmol-ready");
    } else if (
      data.type === "labcat-jsmol-load" &&
      !initialized &&
      typeof data.channel === "string" &&
      /^[a-zA-Z0-9-]{16,64}$/.test(data.channel)
    ) {
      initialized = true;
      channel = data.channel;
      try {
        show(coordinateCif(data.cif));
      } catch {
        fail();
      }
    } else if (
      loaded &&
      data.channel === channel &&
      data.type === "labcat-jsmol-command"
    ) {
      if (data.command === "reset") {
        spinning = false;
        Jmol.script(applet, "spin off; reset; zoom 80;");
      }
      if (data.command === "spin") {
        spinning = !spinning;
        Jmol.script(applet, spinning ? "spin on" : "spin off");
      }
    }
  });
  for (const name of ["drop", "dragover", "contextmenu"])
    document.addEventListener(
      name,
      (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
      },
      true,
    );
  document.addEventListener(
    "keydown",
    (event) => {
      // Jmol's console/model-kit keyboard shortcuts are outside this viewer's UI.
      if (
        event.ctrlKey ||
        event.metaKey ||
        event.altKey ||
        event.key === "F1"
      ) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    },
    true,
  );
  if (parent !== window) tell("labcat-jsmol-ready");
})();
