# Real-browser report layout regression checks

Run `npm run test:report-layout --prefix frontend` from the repository root and
open the printed loopback URL in the browser being checked. No extra dependency
or authenticated application session is required. The page runs automatically;
**Run again** reloads the current application CSS. Stop the local runner with
Ctrl+C after inspecting it.

Set `LABCAT_LAYOUT_PORT=61937` before the command when a native test app needs
a fixed loopback port; otherwise the operating system assigns an available port.

The 162 cases use the actual React report renderer and application CSS, with
synthetic text only. They cover historical tables without metadata or with
mismatched metadata, enhanced candidate leads, provisional literature tables,
preliminary candidate shortlists with review-group headings, ranked Summary and
Technical View tables, and generic two/twelve-column tables.
Each runs at 320, 600 and 1100px, at 9 and 14pt, in striped/grid/minimal styles.

Checks use real DOM geometry for useful prose column widths, bounded header and
row heights, text and page overflow, keyboard-focusable scroll regions, and
access to the last column. Column widths are measured from data cells; row-height
checks also include semantic review-group headings. The page displays pass/fail
details and its browser user agent. **Inspect a case** previews any fixture. The latest complete result
is available at `/results` on the same server and as `window.reportLayoutResults`.

Each case also retains the exact rendered table markup while switching between
the Summary and Technical View classes. At the same viewport and appearance
settings, the table, columns and cells must retain their dimensions (within
0.5px), padding, typography, borders, colors and sticky-column styling. Scrolled
column positions must match, sticky rank/identity cells must not overlap, and
the last column must remain reachable in both views. This
isolates view-specific CSS regressions across every table renderer, including
historical reports. It does not require tables with different columns or prose
to have equal widths or row heights; the Technical View keeps its extra content.

These checks deliberately include the historical fallback renderer and the
last prose column: the regression involved a nowrap source title and columns
shrinking toward one-character widths, inflating every cell's row height.
The usual jsdom tests check structure and behavior but do not perform layout.

Run this page separately in the supported browser engines, especially the
native application's WebKit engine. A Chrome pass does not establish WebKit
coverage. Fixed synthetic height limits are regression guards, not a promise
that every arbitrarily long valid report row fits in the viewport.
