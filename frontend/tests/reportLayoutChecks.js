/* Runs only inside the separate synthetic layout-check page. No app API calls. */
const fixtures = JSON.parse(document.getElementById("fixtures").textContent);
const status = document.getElementById("status");
const resultsElement = document.getElementById("results");
const frame = document.getElementById("test-frame");
const preview = document.getElementById("preview-frame");
const picker = document.getElementById("case-picker");
const button = document.getElementById("rerun");
const browserLabel = document.createElement("p");
browserLabel.textContent = `Browser: ${navigator.userAgent}`;
status.before(browserLabel);
const combinations = fixtures.flatMap((fixture) =>
  [320, 600, 1100].flatMap((width) =>
    [9, 14].flatMap((font) =>
      ["striped", "grid", "minimal"].map((style) => ({
        fixture,
        width,
        font,
        style,
        name: `${fixture.name} / ${width}px / ${font}pt / ${style}`,
      })),
    ),
  ),
);
const escapeAttribute = (text) =>
  text.replaceAll("&", "&amp;").replaceAll('"', "&quot;");
function frameDocument(item) {
  const css = ["styles.css", "workspace.css", "reportContent.css"]
    .map(
      (name) =>
        `<link rel="stylesheet" href="${escapeAttribute(new URL(name, location.href).href)}">`,
    )
    .join("");
  const html = item.fixture.html
    .replace("report-table-striped", `report-table-${item.style}`)
    .replace(/--report-text-size:[^;"]+/, `--report-text-size:${item.font}pt`);
  return `<!doctype html><html lang="en"><meta charset="utf-8">${css}<style>html,body{margin:0;padding:0;width:100%;min-width:0}body{display:block}#fixture-root{width:100%;min-width:0}</style><div id="fixture-root">${html}</div></html>`;
}
function loadFrame(target, item) {
  target.style.width = `${item.width}px`;
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error("Fixture frame did not load within 5 seconds.")),
      5000,
    );
    target.onload = () => {
      clearTimeout(timeout);
      resolve();
    };
    target.srcdoc = frameDocument(item);
  });
}
function inspectViewParity(table, check) {
  const report = table.closest(".report-document");
  check(
    !!report,
    "Table has no report container for Summary/Technical View comparison.",
  );
  if (!report) return null;
  const originalClassName = report.className;
  // Retain exactly the same rendered content, including the technical columns.
  // Only the view class changes: different prose must not imply equal row heights.
  const region = table.closest(".report-shortlist-scroll");
  const elements = [
    region,
    table,
    ...table.querySelectorAll("caption, tr, th, td, th *, td *"),
  ];
  const cells = [...table.querySelectorAll("thead th, tbody th, tbody td")];
  const properties = [
    "minWidth",
    "maxWidth",
    "paddingTop",
    "paddingRight",
    "paddingBottom",
    "paddingLeft",
    "fontFamily",
    "fontSize",
    "fontWeight",
    "fontStyle",
    "fontVariantNumeric",
    "lineHeight",
    "letterSpacing",
    "textAlign",
    "verticalAlign",
    "whiteSpace",
    "overflowWrap",
    "color",
    "backgroundColor",
    "boxShadow",
    "borderTop",
    "borderRight",
    "borderBottom",
    "borderLeft",
    "borderRadius",
    "position",
    "left",
  ];
  const measure = (view) => {
    report.classList.remove("report-document-pi", "report-document-audit");
    report.classList.add(`report-document-${view}`);
    region.scrollLeft = 0;
    const measuredElements = elements.map((element) => {
      const bounds = element.getBoundingClientRect();
      const style = frame.contentWindow.getComputedStyle(element);
      return {
        width: bounds.width,
        height: bounds.height,
        styles: properties.map((property) => style[property]),
      };
    });
    region.scrollLeft = region.scrollWidth;
    const visible = region.getBoundingClientRect();
    const scrolledPositions = cells.map(
      (cell) => cell.getBoundingClientRect().left - visible.left,
    );
    for (const rank of table.querySelectorAll("tbody .report-column-rank")) {
      const identity = rank.parentElement.querySelector(
        ".report-column-identity",
      );
      if (
        identity &&
        frame.contentWindow.getComputedStyle(rank).position === "sticky"
      ) {
        check(
          rank.getBoundingClientRect().right <=
            identity.getBoundingClientRect().left + 0.5,
          `${view} sticky rank and identity columns overlap when scrolled.`,
        );
      }
    }
    const firstDataRow = [...table.querySelectorAll("tbody tr")].find((row) =>
      row.querySelector(":scope > td"),
    );
    const last = firstDataRow?.lastElementChild.getBoundingClientRect();
    check(
      last && last.right <= visible.right + 3 && last.right > visible.left,
      `${view} last column cannot be reached by horizontal scrolling.`,
    );
    return { elements: measuredElements, scrolledPositions };
  };
  try {
    const summary = measure("pi"),
      technical = measure("audit");
    let maxDimensionDelta = 0;
    const dimensionDifferences = [],
      styleDifferences = [];
    for (const [index, expected] of summary.elements.entries()) {
      const actual = technical.elements[index],
        label = `${elements[index].tagName.toLowerCase()} ${index + 1}`;
      for (const dimension of ["width", "height"]) {
        const difference = Math.abs(expected[dimension] - actual[dimension]);
        maxDimensionDelta = Math.max(maxDimensionDelta, difference);
        if (difference > 0.5)
          dimensionDifferences.push(
            `${label} ${dimension}: ${expected[dimension].toFixed(2)}px vs ${actual[dimension].toFixed(2)}px`,
          );
      }
      for (const [propertyIndex, property] of properties.entries()) {
        if (expected.styles[propertyIndex] !== actual.styles[propertyIndex]) {
          styleDifferences.push(
            `${label} ${property}: ${expected.styles[propertyIndex]} vs ${actual.styles[propertyIndex]}`,
          );
        }
      }
    }
    const maxScrolledPositionDelta = Math.max(
      ...summary.scrolledPositions.map((position, index) =>
        Math.abs(position - technical.scrolledPositions[index]),
      ),
    );
    check(
      dimensionDifferences.length === 0,
      `Summary/Technical View dimensions differ for identical content (${dimensionDifferences.length} differences): ${dimensionDifferences.slice(0, 4).join("; ")}.`,
    );
    check(
      styleDifferences.length === 0,
      `Summary/Technical View formatting differs for identical content (${styleDifferences.length} differences): ${styleDifferences.slice(0, 4).join("; ")}.`,
    );
    check(
      maxScrolledPositionDelta <= 0.5,
      `Summary/Technical View column positions differ by up to ${maxScrolledPositionDelta.toFixed(2)}px when horizontally scrolled.`,
    );
    return {
      checkedElements: elements.length,
      maxDimensionDelta,
      maxScrolledPositionDelta,
      dimensionDifferences: dimensionDifferences.length,
      styleDifferences: styleDifferences.length,
    };
  } finally {
    report.className = originalClassName;
    region.scrollLeft = 0;
  }
}
function inspect(item) {
  const doc = frame.contentDocument,
    errors = [],
    table = doc.querySelector(item.fixture.selector);
  const check = (condition, message) => {
    if (!condition) errors.push(message);
  };
  check(
    !!table,
    `Expected renderer ${item.fixture.selector} was not selected.`,
  );
  if (item.fixture.excluded)
    check(
      !doc.querySelector(item.fixture.excluded),
      "Historical fixture unexpectedly bypassed the fallback renderer.",
    );
  if (!table) return { name: item.name, passed: false, errors };
  const region = table.closest(".report-shortlist-scroll");
  const rect = (element) => element.getBoundingClientRect();
  const headers = [...table.querySelectorAll("thead th")];
  const rows = [...table.querySelectorAll("tbody tr")];
  const headerHeight = rect(table.querySelector("thead")).height;
  const rowHeight = Math.max(...rows.map((row) => rect(row).height));
  // Semantic row-group headings contain only a spanning th. Measure columns
  // from a data row, while retaining every group row in the height check above.
  const firstDataRow = rows.find((row) => row.querySelector(":scope > td"));
  check(!!firstDataRow, "Table contains no data row to measure.");
  if (!firstDataRow) return { name: item.name, passed: false, errors };
  const firstRow = [...firstDataRow.querySelectorAll(":scope > td")];
  const contentWidths = firstRow.map((cell) => {
    const style = frame.contentWindow.getComputedStyle(cell);
    return (
      rect(cell).width -
      parseFloat(style.paddingLeft) -
      parseFloat(style.paddingRight)
    );
  });
  for (const index of item.fixture.proseColumns) {
    const width = contentWidths[index];
    check(
      Number.isFinite(width),
      `Prose column ${index + 1} has no measurable data cell.`,
    );
    if (Number.isFinite(width))
      check(
        width >= 72,
        `Prose column ${index + 1} collapsed to ${width.toFixed(1)}px of content width.`,
      );
  }
  check(
    headerHeight <= 140,
    `Header is ${headerHeight.toFixed(1)}px tall (limit 140px).`,
  );
  check(
    rowHeight <= 800,
    `Synthetic row is ${rowHeight.toFixed(1)}px tall (limit 800px).`,
  );
  check(
    doc.documentElement.scrollWidth <= item.width + 2,
    `Table escaped the document width (${doc.documentElement.scrollWidth}px vs ${item.width}px).`,
  );
  check(
    region.clientWidth <= rect(doc.querySelector(".report-document")).width + 2,
    "Scroll region escaped the report container.",
  );
  check(
    region.getAttribute("tabindex") === "0",
    "Table scroll region is not keyboard-focusable.",
  );
  check(
    !firstRow.some((cell) => cell.scrollWidth > cell.clientWidth + 2),
    "Cell text horizontally overflows its column.",
  );
  region.scrollLeft = region.scrollWidth;
  const last = rect(firstRow.at(-1)),
    visible = rect(region);
  check(
    last.right <= visible.right + 3 && last.right > visible.left,
    "Last column cannot be reached by horizontal scrolling.",
  );
  const bodyText = table.textContent;
  check(
    bodyText.includes("TEST ONLY") || bodyText.includes("Synthetic"),
    "Synthetic fixture text unexpectedly disappeared.",
  );
  region.scrollLeft = 0;
  const viewParity = inspectViewParity(table, check);
  return {
    name: item.name,
    passed: errors.length === 0,
    errors,
    columns: headers.length,
    headerHeight,
    rowHeight,
    contentWidths,
    regionWidth: region.clientWidth,
    scrollWidth: region.scrollWidth,
    viewParity,
  };
}
async function run() {
  button.disabled = true;
  const cases = [];
  resultsElement.textContent = "";
  for (const [index, item] of combinations.entries()) {
    status.textContent = `Checking ${index + 1} of ${combinations.length}: ${item.name}`;
    try {
      await loadFrame(frame, item);
      cases.push(inspect(item));
    } catch (error) {
      cases.push({
        name: item.name,
        passed: false,
        errors: [String(error.message ?? error)],
      });
    }
  }
  const result = {
    passed: cases.every((item) => item.passed),
    userAgent: navigator.userAgent,
    generatedAt: new Date().toISOString(),
    cases,
  };
  window.reportLayoutResults = result;
  const failures = cases.filter((item) => !item.passed);
  status.textContent = failures.length
    ? `FAIL: ${failures.length} of ${cases.length} layout cases failed.`
    : `PASS: all ${cases.length} layout cases passed.`;
  status.style.background = failures.length ? "#fae8df" : "#e7f2e6";
  resultsElement.textContent = failures.length
    ? failures
        .map(({ name, errors }) => `${name}\n  ${errors.join("\n  ")}`)
        .join("\n\n")
    : `${cases.length} cases checked: historical missing/mismatched metadata, enhanced leads, provisional literature, ranked Summary/Technical View, and generic 2/12-column tables.\nWidths: 320, 600, 1100px. Fonts: 9, 14pt. Styles: striped, grid, minimal.\nMeasured prose width, header and row height, text overflow, document containment, keyboard focus and last-column scroll reach.\nIdentical table content also retains dimensions, cell padding, typography, borders and colors in Summary and Technical View.\nBrowser: ${navigator.userAgent}`;
  button.disabled = false;
  try {
    await fetch("/results", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(result),
    });
  } catch {
    resultsElement.textContent +=
      "\nCould not send results to the local runner; window.reportLayoutResults still contains them.";
  }
}
for (const [index, item] of combinations.entries()) {
  const option = document.createElement("option");
  option.value = String(index);
  option.textContent = item.name;
  picker.append(option);
}
picker.addEventListener("change", () =>
  loadFrame(preview, combinations[Number(picker.value)]),
);
button.addEventListener("click", run);
loadFrame(preview, combinations[0]);
run();
