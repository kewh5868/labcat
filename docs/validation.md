# Validation record — 2026-09-24

Version: `0.1.0.dev0`. The prototype supports public-evidence research across
material classes through the shared Python CLI and FastAPI workflow. Numerical
coverage depends on the connected adapters and reviewed fields; it is not a
validated materials predictor or an exhaustive web search engine.

## Full source preflight — 2026-09-24

The configured scikit-package Level 4 hook family now runs through pre-commit:
YAML/TOML, whitespace, merge/case conflicts, large files, private keys,
docformatter, Black, Flake8, notebook output stripping and Prettier. Ruff lint
remains an additional check. Black is the sole Python formatter. Generated
assets and upstream vendor/font/license files are excluded from formatting;
reviewed runtime artwork has explicit exceptions to the large-file gate.
The same hook configuration is used by CI and the documented developer setup.

The full Python suite passed **5,482 tests and 98 subtests**, with 61 skips
because PowerShell is unavailable on this macOS host. Two dependency deprecation
warnings remain. All **331 frontend tests**, TypeScript checking and the
production build passed using Node 24.13.0. Vite still reports a nonfatal
JavaScript chunk-size warning. These are local source checks, not results from
other operating systems or from GitHub Actions.

Preflight corrected a rejected ranking-profile request changing an untitled
chat's name, and a submission timing issue that could take a context snapshot
before the preceding run completed. An actual Docker smoke also caught model-setup
rejection changing an untitled chat. Admission now reserves the chat, validates
setup and snapshots current inputs before naming or publishing running progress.
Slow account verification runs outside the shared progress lock; reservations
still prevent duplicates and protect pending chats from bulk clearing. Failed
admission releases its reservation without changing chat contents. Local safety
refusals remain available without model setup. Regression tests cover rejected
requests, simultaneous submissions, completion between submissions, capacity,
retry, and another chat's progress during slow verification. The container smoke export validator now includes the
existing chemical-name presentation field and rejects missing or changed names.

All **162 isolated Chrome layout cases** passed with identical table dimensions,
styles and scroll positions for the same Summary/Technical content. No overflow,
sticky-column or keyboard-scroll failures were found. This does not establish
WebKit rendering. A Docker context fixture retained 15 expected public files and
excluded 140 synthetic private files; this checks context filtering, not a full
application image build.

On ARM64 macOS, **25 native tests**, Rust formatting and the Tauri application
build passed. The raw development bundle failed strict signature verification
because its resources are unsealed; it is not a signed/notarized release. It was
not installed or launched for this check. Windows, Linux and Intel native builds
remain untested in this preflight.

Distribution checks now require exactly one wheel and one source archive with
matching package/version metadata, reject unsafe/private members, and support a
build-start marker to reject stale artifacts. CI verifies the installed wheel
from a clean environment outside the checkout. Full-source checks must still be
repeated for each independently assembled intermediate commit; a final-source
pass does not validate an earlier partial tree.

## Timestamped query history — 2026-09-23

Follow-ups keep a compact preview of each earlier question and its saved
shortlist within the chat. Each preview shows up to three materials in their
original order with ranks, scores and caveats. Opening a full revision uses its
saved report format; previewing history performs no new research or ranking.
New saved question timestamps use server acceptance time, while reports retain
their completion timestamps. Historical saved times are not rewritten.

Validation passed 234 focused Python tests and all 322 frontend tests, plus
Ruff, frontend type checking and the production build. Persistence tests cover
an original question and two follow-ups in both standalone and project chats,
including immutable source versions after reopening. Interface tests submit
two follow-ups, navigate away and back, remount the workspace, open a saved
report, and exercise missing-result and malformed-content cases.

The update was installed in the local ARM64 Docker runtime with all three
services healthy. A live follow-up in an existing validation chat retained
its original report, messages, ranking result and source identifiers unchanged;
the new question timestamp preceded report completion by about two minutes.
The Mac desktop history link and compact three-row preview were visually
verified after restarting the native window.
This is a history/persistence check, not validation of the scientific suitability
of either report. No new Windows or AMD64 runtime coverage is claimed.

## Silicon-tandem discovery and adaptive properties — 2026-09-23

Public discovery now preserves silicon-tandem absorber context and can retain
bounded open-access fabrication passages, including their section headings.
Discovery and subsequent property follow-up share the configured article
download allowance. Inferred photovoltaic profiles prioritize band gap and
stability; manual profiles and explicit user goals retain precedence.
Technical View displays at most three relevant properties, with exact cited
assessment text or an explicit missing-assessment label. Decimal fractions in
composition headings are preserved.

An integrated offline run passed 1,114 Python tests. Later focused runs checked
the final passage ordering, section provenance, article budget, explicit-goal
precedence and report changes; their counts overlap and are not added to the
integrated total. The final frontend run passed 311 tests, and the production
frontend build/typecheck and Ruff passed. The update was installed in the
local ARM64 Docker runtime; all three services passed health checks, and the
Mac desktop report was inspected. This entry does not establish new Windows,
Linux desktop or AMD64 runtime coverage.

Live adapter checks for the original silicon-tandem top-cell question and two
ordinary-language paraphrases retrieved mixed-cation absorber compositions.
Two full model runs of the original question exposed and then verified a fix
for useful fabrication passages being lost behind long abstract results.
The final run retained 21 sources and three candidate compositions:

- Cs0.05MA0.15FA0.80Pb(I0.75Br0.25)3, supported by an explicit
  perovskite/silicon tandem fabrication passage.
- Cs0.22FA0.78Pb(I0.85Br0.15)3.
- Cs0.22FA0.78Pb(I0.8Br0.2)3.

The last two share a rank. Differentiated review priorities reflect retained
application and demonstrated-use assessments, not measured efficiency or
validated stability. The final report remains partial: none of its selected
attribute assessments were established. Operational stability, band gap and
room-temperature phase stability therefore remain marked as not reported in
the compact property cells. This means no accepted criterion-bound assessment
was retained, not that the source literature contains no relevant information.

Composition recipes and numerical observations can occur in different sections
without an unambiguous local identity link. Improving that binding remains an
open limitation; these checks do not justify transferring values between
compositions, device layers, phases or processing conditions. The paraphrase
checks tested retrieval only, not complete model-generated reports. See
[literature ranking](literature-ranking.md) for the evidence and display rules.

## Compact sidebar header — 2026-09-23

Reduced desktop logo/header spacing and the New chat/Create project controls,
keeping 36px button heights and the full tagline. The sidebar width, independent
list scrolling and section divider behavior are unchanged. Typical desktop
windows gained 66px of list height; already-compact short windows gained 11px.
The existing stacked mobile layout retains its list space.

Validation: 24 frontend sidebar/workspace/search tests, 35 Python web-security
tests, frontend build/type checking, Ruff and whitespace checks passed. Nine
isolated Chrome before/after cases covered 320–1,440px viewport widths, 700–1,000px
heights, 220/238/480px desktop sidebars and responsive boundaries. Checks verified
reclaimed list height, independent scrolling, keyboard resizing/focus, section
expansion, both creation controls and no horizontal overflow. The desktop result
was visually inspected. No real chats/projects were created or changed. The
source update is ready; installation remains paused under the existing disk
growth safeguard.

## Consistent report tables — 2026-09-23

Summary and Technical View share table widths, cell padding, typography,
borders and pinned rank/material column styling. Removed view-specific compact
spacing and the forced wider Technical View table. A shared rank-column width
keeps pinned columns from overlapping at larger report font sizes. Technical
columns and longer explanations remain available; content is not clipped to
force different tables to have identical heights.

Validation: 74 frontend report/format/pin/structure tests, 35 Python web-security
tests, frontend build/type checking, Ruff and whitespace checks passed. The 162
isolated Chrome layout cases passed at 320, 600 and 1,100px, with 9/14pt fonts
and striped/grid/minimal tables. Each compares identical content in both view
styles, including dimensions, typography, cell padding, colors, borders and
scrolling. A deliberately restored old-style fixture failed the new comparison,
confirming detection of the original inconsistency. Rendered tables were also
visually inspected. No live research or saved-workspace changes were made.
Installation remains paused under the existing disk-growth safeguard; these
results cover the updated source, not the installed native app or WebKit.

## Concise completed-report presentation — 2026-09-23

Completed and partial reports no longer repeat the saved completion message
beneath the report. Saved messages remain intact and their search matches focus
the report itself. Clarifications, refusal replies, errors and blocked/scaffold
report notices remain visible.

Validation: 58 existing frontend tests, 35 Python web-security tests, frontend
build/type checking, Ruff and whitespace checks passed. Ten isolated Chrome
cases checked completed/partial reports at 1,440, 768, 390 and 320px, plus
blocked/scaffold notices at 1,440px. Checks confirmed ordinary replies remain
visible, report-message search focuses the report, both report views omit the
repeated footer, and the aligned disclosures retain their 8px gap. No live
research or workspace changes were made. The tested source update is ready;
installation remains paused under the existing disk-growth safeguard.

## Aligned report disclosures — 2026-09-23

The saved audit and ranking-profile disclosures share responsive gutters,
borders, padding and collapsed row heights, with an 8px gap. Expanded contents
remain independent; native keyboard disclosure behavior is preserved. Profile
names wrap at narrow widths and expanded property columns stay within the card.

Validation: 44 existing frontend tests, 35 Python web-security tests, frontend
build/type checking, Ruff and whitespace checks passed. Eight isolated Chrome
checks covered Summary and Technical View at 1,440, 768, 390 and 320px, checking
equal collapsed dimensions, alignment, spacing, keyboard expansion, retained
audit contents and no page overflow. Sources retains only the profile disclosure.
No live research was run. Installation stopped before restart when the approved
disk-growth limit was exceeded; the prior running version remains unchanged.
The tested update is staged locally.

## Automatic report formatting — 2026-09-23

Removed the report-level display-settings disclosure and saved/current toggle.
Ordinary and tracked reports automatically use Report Format preferences for
viewing and downloading. Project snapshot pins retain their saved format.
Failure to load a current layout keeps the original report and its saved-format
downloads available, with a retry only when needed. No evidence or rank changes.

Validation: 47 focused frontend tests, 202 Python report-export, pin and
web-security tests, frontend build/type checking, Ruff and whitespace checks
passed. Three isolated Chrome checks at 1,440, 390 and 320px confirmed removal of
the extra controls, automatic current-format downloads, retained shortlist rows
and no horizontal page overflow. Regression coverage includes legacy reports,
snapshot versus tracking behavior, failure/retry, and cancelled/late responses.
No live inference was used. The small UI update is installed in the local ARM64
app; all three services are healthy, served assets match the tested build, and
saved workspace/account state is unchanged. The native window was left open
during active use; reopening loads the new interface.

## Consistent settings layout — 2026-09-23

Search Criterion, Report Format and Connections now use the same centered
1,060px maximum page width, card padding and 42px primary form controls.
Explicit select styling prevents native dropdowns from collapsing below text
field height. Responsive grids contain long values and stack on narrow windows.
Compact ranking importance controls and setup dialogs keep their existing sizing.

Validation: 32 existing frontend tests, 35 Python web-security tests, frontend
build/type checking, Ruff and whitespace checks passed. Eighteen isolated Chrome
checks covered all three pages at 1,920, 1,440, 1,024, 768, 390 and 320px. These
verified shared widths, aligned cards, input/select heights, containment and no
horizontal page overflow. No live inference or source retrieval was used.
The small update is installed in the local ARM64 app. All three services are
healthy; saved workspace/account state and served assets were verified. The native
window was left open during active use; reopening loads the new layout. Native
macOS rendering of this particular change has not yet been verified.

## Composer control alignment — 2026-09-23

The ranking selector, model selector, and reference-structure checkbox now share
the bottom-left control group. The checkbox follows the model selector and
matches its typography, with an explicit 9px label gap. Scoped styles prevent
general form labels and inputs from overriding the layout. Small windows wrap
the group without horizontal page overflow; request behavior is unchanged.

Two existing frontend integration tests, 35 Python web-security tests, the
frontend build/type checking, Ruff, and whitespace checks passed. Twelve isolated
Chrome checks covered new, saved, and project chat composers at 1,440, 768, 390,
and 320px. Checks verified control order, equal typography, checkbox spacing,
containment, and toggling. No live inference was used.

The small frontend update was installed in the local ARM64 app; all services
were healthy and saved workspace/account state was preserved. The native window
was left open during active use; reopening loads the updated interface.

## Extended comparisons and inline structures — 2026-09-23

Technical View now discusses all retained candidates, supported selected
criteria, ranking-weight influence, comparative tradeoffs, source conditions,
and validated experimental/computed discrepancies. Summary remains concise.
The prose uses saved evidence and assessments; it does not invent observations
or change the ranking. Reference-structure discovery is enabled by default for
new prompts, optional per request, bounded, and isolated from report saving.
Shortlist rows open JSmol and CIF controls inline in both report views.

Validation: 4,865 Python tests and 98 subtests passed. Two local proxy tests
initially could not open loopback sockets in the sandbox; both passed with
local socket access. The 61 PowerShell-dependent cases were skipped on this
host. All 272 frontend tests, TypeScript checking, frontend build, Ruff, and
whitespace checks passed. Focused coverage includes default-on/explicit-off
submission, source selection, refusals, failed discovery preserving a report,
inline row association, and viewer loading/collapse.

A live public HybriD³ dataset (2942, system 126, subset 3506) supplied a
validated 142-site CIF. The real bundled JSmol rendered that CIF in isolated
Chrome checks at 1,440, 390, and 320px with no page overflow or browser errors.
These checks establish that this file renders, not universal source availability
or phase equivalence. An additional formula lookup for a saved-report example
was blocked by automatic approval review and remains unverified. No live model
inference was used for this change.

The tested update was installed in the local ARM64 application. All three
services are healthy; saved chats, projects, and encrypted account state were
preserved. The build used a small update layer and retained the 20 GiB disk
reserve. No Windows or Linux desktop rendering coverage is claimed.

## Chat mascot refinement — 2026-09-23

Removed the continuous desk/computer mascot and idle nap behavior from chat.
Both sprite sheets, their original generation prompts and nap playback metadata
remain available for future reuse. Processing holds the first beaker pose still;
only a clipped copy of its liquid changes color. Completion keeps its short
bubble-over sequence.

Validation passed: 18 focused frontend tests, 35 Python web-security tests,
frontend build/type checking, Ruff and diff checks. Isolated Chrome checks covered
new/saved chat and the three settings pages at desktop and narrow widths (10
cases), with no desk/nap image requests. Three sampled processing color phases
kept the main image stationary; reduced motion and background pausing passed.
The native app received the updated frontend through a small local ARM64 image
update. All three services are healthy; saved chats, projects and encrypted
account state were preserved. These decoration checks made no live inference
calls and do not extend the research-quality coverage recorded below.

## Optional Labcat animations — 2026-09-22

Six transparent eight-frame sheets add decorative beaker, wires, crystal,
typewriter, computer and idle-nap scenes. The original brand mark is unchanged.
One source switch or frontend build flag disables all mascot mounts, image
requests and activity timers. Reduced-motion and hidden-tab behavior are covered.

Validation: all 267 frontend tests passed, including 12 new focused mascot and
submission/navigation cases; 35 Python web-security tests, frontend build,
TypeScript, Ruff and whitespace checks passed. Twenty isolated Chrome layout
checks covered welcome chat, saved chat, Connections, Search Criterion and Report
Format at 1,440×900, 1,024×720, 390×850 and 320×700. They checked sprite decoding,
page containment, square clipping and no overlap with headings or controls.
Additional browser checks covered reduced motion, print exclusion, idle nap,
trusted pointer wake-up, unchanged draft text and hidden-tab pausing. Frame
inspection covered all eight cells in each sheet. A separate production build
with `VITE_LABCAT_MASCOTS=false` made no sprite requests, rendered no mascots
and reserved no extra header column. The enabled build was then restored.
No native WebKit or other-OS animation coverage is claimed.

Completion requires a new report returned by the current submission and does
not delay displaying results. History, clarification/refusal and failed requests
do not trigger the flourish. This work makes no new scientific-quality claim
and did not use research or provider calls. See
[animation controls and assets](labcat-animations.md).

The tested frontend and six sheets were installed in the local ARM64 application.
All three services were healthy; served JavaScript and sprite bytes matched the
build. Saved chats, projects and encrypted connection state were unchanged.
The native window was left open so a user refresh can load the new interface.

## Adjustable sidebar sections — 2026-09-22

The Projects/General chats divider now supports pointer dragging, keyboard
adjustment and an equal-split reset. Heading buttons give either section more
space, then restore the previous custom split on a second click. The preference
survives sidebar hiding, search and page reloads.

Validation: 25 relevant frontend tests passed, including seven new focused
section-control cases; 35 Python web-security tests, the frontend build, Ruff
and whitespace checks passed. Four isolated Chrome runs with synthetic projects
and chats verified heading toggles, pointer dragging, independent scrolling,
reload persistence and page containment at 1,440×900, 1,100×620 (220px sidebar),
390×850 and 320×700. No native WebKit claim is made.

The small frontend update was installed in the ARM64 application; all three
services were healthy and the served assets matched the tested build. Saved
workspace and connection state were unchanged. No research or provider calls
were made for this interface change.

## Labcat rebrand and interface regression checks — 2026-09-22

This pass checks software behavior after the Labcat rename and the
**Interview Prototype** label update. It does not constitute a new scientific
evaluation or a new live research campaign.

- **4,826 Python tests and 98 subtests passed.** Two local proxy tests initially
  could not bind loopback sockets in the sandbox; both passed when rerun with
  local socket access. The 61 PowerShell-dependent cases were skipped because
  PowerShell is not installed on the test host.
- **248 frontend tests passed**, together with TypeScript checking, the
  production frontend build, Ruff and whitespace checks.
- **162 Chrome report-layout cases passed**, using nine synthetic fixtures at
  three widths, two font sizes and three table styles. Checks cover column
  widths, row heights, text overflow, page containment, keyboard focus and
  access to the final column.
- **Six Chrome branding/setup/welcome checks passed** at 1,440, 390 and 320px.
  These verify the Labcat mark and tagline, exact prototype label, responsive
  layout and absence of browser errors.
- **72 read-only checks of the installed ARM64 app passed.** All three services
  were healthy; all 70 Python/configuration files matched the tested source.
  Saved-report presentation, workspace search, eight downloads (all views and
  Sources-only in TXT, JSON, PDF and DOCX), cached CIF download integrity and
  local viewer assets passed. Saved workspace and account state stayed unchanged.
- The separate offline evaluator passed intake refusal, source-instruction
  rejection, model-connection gating and arithmetic/provenance checks on 11
  historical fixture records. It made no model calls or network requests.

The report-layout harness initially errored in 18 preliminary-shortlist cases:
it mistook a spanning review-group heading for the first data row. The harness
now measures columns from a data row while retaining group headings in its
row-height checks. All 18 affected cases and then the full 162-case matrix
passed. No application layout change was needed for that correction.

These automated checks include ranking-weight sensitivity, prompt/class
inference, stability handling, experimental/computed evidence precedence,
source outages, structure validation and adversarial input fixtures. They do
not establish that every new prompt will retrieve suitable candidates. No
fresh authenticated inference, public-source retrieval, native WebKit layout
run, or Windows/Linux desktop execution was performed in this pass. Chrome
results do not establish WebKit coverage.

The following sections preserve earlier research and deployment checkpoints;
their live results are not new results from the regression pass above.

## Class inference and structure retrieval — 2026-09-10

Automatic profiles now recognize broader class/application phrasing, including
two-dimensional materials, and preserve explicit targets and exclusions. Optical
applications alone no longer imply maximizing the band gap. Existing custom
profiles remain unchanged; only exact untouched optical presets are migrated.
Stability priorities remain present, with missing evidence explicitly unknown.
Chat refinements and initial inference share the `catalog-goals-v3` marker.

An internal composition-sampling preference was leaking into Materials Project
requests and causing HTTP 400 responses. It is now removed from the provider
query while local composition ranking is preserved. A live retest returned 100
validated records and three parseable derived CIF exports. All four implemented
structure adapters had successful bounded live checks; see
[the structure validation scope](structures.md#live-validation-scope).

Validation completed for this update:

- 2,746 Python tests and 98 subtests passed; 48 PowerShell-only tests skipped on
  this Mac. After final inference-boundary changes, 500 surrounding integration
  tests passed; the final shared-version change passed 222 profile/workflow and
  60 continuation/workflow tests.
- All 178 frontend tests, production frontend build, Ruff and changed-file
  formatting checks passed.
- The ARM64 image passed the full disposable-workspace container checks,
  including actual Goose browser-sign-in start/cancel, isolation, exports,
  credential-vault behavior and replacement/restart. The smoke harness's old
  inference-version expectation was corrected before the passing run.
- Installed image:
  `sha256:5af6308eb78e2161666b99c0b675284d973cc6507b77f5f124584a88dc6ba24c`.
  The native Mac test application opened the updated sign-in screen. The active
  projects list remained empty after replacement, as requested.

These checks do not include renewed authenticated model inference. The fresh
cross-model report matrix is paused for application sign-in. No new AMD64 or
native Windows/Linux test result is claimed for this image.

## Current research checkpoint: eight-topic public-source diagnostics

One bounded source-only pass covered halide and oxide perovskites, alloy
stiffness, organic photovoltaics, conjugated polymers, quantum-dot LEDs,
two-dimensional semiconductors and MOF adsorption. With all eight keyless
adapters selected, focused-topic matching and four references per source, all
eight queries returned hits: **122 references**, retained as approved discovery
documents. The per-topic counts and limitations are recorded in
[the materials prompt evaluation](materials-prompt-evaluation.md).

Manual inspection found specific material mentions in at least 21 documents
across all eight topics. Twenty-seven sampled literal name selections passed
exact-source quote validation; two containing chemical subscript markup failed.
These counts include duplicate publication versions and do not establish
application relevance, comparable properties or suitable candidates. Five arXiv
calls hit the local request-spacing guard; one OpenAlex call reported unavailable
or rate limited. No retry was made in this one-pass diagnostic.

The resulting generic abstract normalization preserves chemical adjacency and
block separation while rejecting active, hidden, unsupported or malformed
markup. Full-source instruction checks run before formatting removal and again
after normalization, before any prefix is retained. Source quotes bind to the
normalized text and provenance hashes still bind to the original fetched bytes.
Ruff and 328 focused tests passed, including shared OpenAlex handling, bounded
text, instruction rejection and exact-quote validation. The live diagnostic
counts precede this fix; they are not post-fix coverage results.

**No new Goose/model runs or ranked reports were produced by these diagnostics.**
The new live cross-material and cross-model matrix awaits application sign-in.
At the user's request, seven prior projects were moved to Removed items using
recoverable removal. Future actual evaluations will create fresh labeled
projects and save their chats/reports there. Historical measured results below
remain historical; the frozen held-out prompts were neither read nor changed
for this diagnostic work. This checkpoint adds no deployment or other-platform
test claim.

## Previous research update: source-guided refinement

The resumed live Sol run saved seven materials reports. Three contain twelve
property-backed records each, three contain cited literature leads only, and the
polymer case contains no named candidates. The next organic-photovoltaic case
ended with an HTTP error. These results predate this update; they are recorded
in [the evaluation review](materials-prompt-evaluation.md), including relevance
and stability limitations. No claim of successful cross-model or held-out
coverage is made.

The updated coordinator preserves focused class/application queries, permits one
bounded search refinement and one corrected selector batch, reports exact-source
validation immediately, and retains accepted citations within source/document
limits. Inferred profiles now preserve explicitly requested low density and
solution-processing preferences. Attribute searches preserve combined scope and
recompute literal candidate associations instead of attaching all candidate IDs
to every excerpt. These passages remain unscored and do not establish phase or
property applicability. Per-case evaluation checkpoints preserve partial runs.

Validation completed:

- 2,622 Python tests and 98 subtests passed; 48 PowerShell-only checks skipped on
  this Mac. A subsequent focused run passed 298 tests after the final integration.
- 178 frontend tests, the production frontend build, Ruff and whitespace checks
  passed. Wheel/source builds passed the distribution privacy checks.
- ARM64 full disposable-workspace smoke passed, including required setup,
  source credential storage transitions, actual Goose browser-login start/cancel,
  isolated worker networking, reports, pins, exports, replacement and restart.
  These smoke checks used synthetic credentials and did not run model inference.
- Installed ARM64 image:
  `sha256:03dd5b50443f224ac6de094eed9a7aef0574dfdbe1050a9d754d78a8e4dced36`.
- Native Mac test window opened the updated backend and displayed the model
  sign-in flow. The saved validation project remained present after replacement.
  End-to-end authenticated research still requires the user's renewed sign-in.

The AMD64 build has not yet produced a verified image for this update; earlier
AMD64 results below apply only to their recorded versions. Native Windows/Linux
have not been tested. Do not substitute automated boundary checks for live
scientific evaluation.

## Previous connection update: Materials Project registry card

Materials Project now appears in Supported research databases with its own
write-only key field, verification action and optional encrypted persistence.
Search Criterion adds and removes the verified connection alongside the other
databases; the separate property-API selector and large credential block have
been removed. A dedicated source-credential endpoint leaves model accounts,
model readiness and chat history unchanged.

Completed checks for this update:

- 178 frontend tests, 214 focused Python tests and the production frontend build
  passed. The frontend cases cover password clearing, save/verify sequencing,
  vault prerequisites, storage changes, unavailable-source selection and
  preservation of unsaved model fields while editing the source connection.
- Source API tests cover same-origin/CSRF enforcement, response redaction,
  stale verification invalidation, atomic storage failures, encrypted restart
  persistence and independence from model/account state. These tests use
  synthetic keys and mocked source verification.
- Both images passed the full disposable workspace/container smoke: CRUD,
  report exports, snapshot/live pins, removal and retention, Goose isolation,
  browser-login startup/cancel, credential storage transitions and restart.
  Synthetic source keys stayed unavailable for research until verification;
  no real source probe or model inference was invoked by these smoke checks.
- Installed ARM64: `sha256:02ba3fe2e94e8dd1f14ee8a92070d5f2947a2197c0b6e1a41773faa32e514fad`.
- Emulated AMD64: `sha256:3599012ca932e3de16431e50966262fc382da501a3fcebbfdde4effa485043ed`.

Native Mac visual and interaction review of the new card is still pending at
this checkpoint. AMD64 ran under Docker Desktop emulation on the ARM64 Mac;
native Windows/Linux were not exercised. These connection checks do not
establish improved scientific shortlist coverage. Authenticated cross-material
and cross-model research evaluation is a separate workstream, with results to
be recorded after the actual runs complete.

## Previous UI update: material-property categories

A compact control beside Material properties collapses all categories and changes
to Expand all when none are open. Individual disclosures remain usable. Native
Mac checks covered the main page and chat settings dialog, bulk collapse/expand,
keyboard Enter activation, individual reopening and preservation of an unsaved
weight edit. The test edit was discarded; all 21 saved profiles matched the
pre-update API response exactly.

155 frontend tests, 106 Python ranking-profile tests, the production build, Ruff
and diff checks passed. Both images passed basic disposable-container startup,
API/UI/CLI, setup, Goose isolation and restart checks:

- Installed ARM64: `sha256:c916c21e2c807b6f050c6b52313f9a2690453e1d84ccb671bb1ef44e5ea8c636`.
- Emulated AMD64: `sha256:3028f70103ddeb9524c125f8f1aa21ebb089c67527ce270a51d75ede69c59d9a`.

Live model evaluation remains paused pending user sign-in. This interface update
does not establish additional scientific or native Windows/Linux test coverage.

## Previous UI update: Goose information link

The research-agent card links to the [official Goose homepage](https://goose-docs.ai/),
verified through the former official site's redirect. The rebuilt native Mac
app permits only this exact homepage through its existing external-link guard.
Clicking the link in Connections opened that URL in the system's default browser.
155 frontend tests, 12 Python agent-connection tests, 19 Rust tests, formatting,
Ruff and production frontend/native builds passed. Both Docker images passed
the basic disposable-container startup, API/UI/CLI, setup, isolation and restart
checks:

- Installed ARM64: `sha256:97add74adcf0c10e2567c79e32b6660df1898dbfbceb05357e5c42c55c84c136`.
- Emulated AMD64: `sha256:2ec3eaff1d336f073b44bd579ec0fe0ae766d4e6752fdbd102ca988554c29f42`.

The native app binary SHA-256 is
`021d884d3fccbe05f45a17988c191959db9a80afa19e1497f3083f83a4656462`.
This link does not expand the research adapters or Goose worker's network access.
Live model evaluation still awaits user sign-in.

## Previous UI update: Connections overview

The Compute, Language model and Materials data cards now appear directly below
the Connections introduction, before Goose and the connection forms. The native
Mac app was reopened and visually checked at the top of the updated page.
155 frontend tests, the production build, 45 Python connection/onboarding tests,
Ruff and diff checks passed. Both images passed basic disposable-container
startup, CLI/API/UI, setup, Goose isolation and restart checks:

- Installed ARM64: `sha256:c9be828bff2657079c7e3253bd066220f1a4151b82c921c1c328e0b3a19f3b1e`.
- Emulated AMD64: `sha256:3716713d9f2dda8a1cad5d55bd5bbbd3362ea7cada4c4af2764482b0d28ae299`.

This is a presentation-only change. Live model evaluation remains paused pending
ChatGPT sign-in; no inference or credential import was performed for this check.

## Previous UI update: ranking chart tooltips

Active ranking and editing-preview segments show the criterion name, normalized
share and independent importance through visible hover, focus and tap tooltips.
Unscored criteria retain their evidence-gap label. Escape dismisses the tooltip
without closing its containing settings dialog.

- 155 frontend tests, the production build, 106 Python ranking-profile tests,
  Ruff and diff checks passed. The broader Python suite below belongs to the
  preceding research rollout; this update changes only frontend presentation.
- ARM64 image `sha256:d8de37cdcd0c569e367a6022c205eff0546935fd80e5b54ee4d5e060523ddf9e`
  and AMD64 image `sha256:c87e34b2f528cfef84fa8c311ac6a767f2e0ad8b2eb01d4f1ff10f406172fae6`
  passed the basic disposable-container checks: startup, CLI/API/UI delivery,
  required model setup, Goose browser-login startup/cancel and worker isolation.
  AMD64 ran under Docker Desktop emulation on the ARM64 Mac.
- The ARM64 update is installed. Native Mac checks verified click, Tab, Escape,
  the editing preview, right-edge placement and the chat-accessible settings
  dialog. Tooltips were visually readable above the dialog backdrop. Pointer
  hover transitions and narrow-viewport positioning have DOM regression tests;
  native Windows/Linux checks remain outstanding.
- The complete ranking-profile response matched before and after deployment and
  native interaction, including all 21 saved profiles. The temporary editing
  preview was discarded without saving. Post-update live model evaluation still
  awaits ChatGPT sign-in.

## Research rollout: source-grounded candidates, stability and structures

The current image adds bounded public abstracts, model-selected class/application
search hints, and literal-source candidate selection through isolated Goose.
Named literature leads are kept separate from quantitative candidate records and
performance scores. Summary and Technical View retain linked quotes, missing
criteria and unverified stability/suitability across text, JSON, PDF and Word.
The separately frozen holdout is documented in [holdout evaluation](holdout-evaluation.md).

Validation of the frozen source:

- 2,375 Python tests and 98 subtests passed; 48 Windows-only launcher checks were
  skipped because PowerShell is unavailable on this Mac.
- 152 frontend tests and the production build passed. Ruff, diff checks, source
  and wheel builds, and distribution privacy checks passed.
- ARM64 image `sha256:2a3058c0f7da3ebb01bad828c33c2d704f883b2430e73df411d626f7368adc9c`
  passed the full disposable workspace/container smoke, including Goose isolation,
  browser-login startup/cancel, exports, retention, pins and restart persistence.
- AMD64 image `sha256:fc3f29bc326b12e24c8a8d92c59ea037b495a9c3ec4edd7ca9de4129730813d1`
  passed the same full workspace, isolation, export and restart checks under
  Docker Desktop emulation. Disposable test containers and volumes were removed.
- The ARM64 image is installed locally. Existing 11 projects, 33 chats and 27
  reports remained present; the profile count increased from 20 to 21 for the
  new organic-electronic default. Saved report revisions were not reranked.
- The native Mac app opened the updated backend and correctly required sign-in
  after the previous session-only ChatGPT credential expired with the restart.
  Post-update live model and native research-progress tests are paused for that
  user action. No host credentials were imported.

Before this update, live runs through both GPT-5.6-Sol and GPT-5.6-Luna produced
quantitative candidates for three of nine materials questions; six questions
returned only references. The target-gap comparison also exposed an inference
bug. These were coverage/quality failures, despite successful transport and
honest missing-data handling. They motivated the changes above; the new training
and unseen runs have not yet established that all questions now succeed.

Structure checks identified and fixed the HybriD3 API identifier rejection.
Two previously unavailable public CIFs were retrieved and validated, with original
attachments retained and symmetry-expanded viewer files. They are labelled
composition-matched references because their experimental structure conditions
differ from the calculated property record. A third attachment was rejected
because it described a different composition. Availability remains source- and
record-dependent; this does not establish universal structure coverage.

Checks against the installed container covered nine saved validation records.
Three HybriD3 and three public-dielectric structure paths passed original/derived
download, hash, cache and report-isolation checks. One dielectric structure was
retrieved fresh rather than from cache. One HybriD3 attachment remained rejected
for a composition mismatch, and two NOMAD records remained unavailable because
public source access could not be confirmed or the source failed. Existing chat,
report and pin snapshots remained unchanged. Materials Project was not exercised
in this check because no API key was connected in the running app.

Native Windows and Linux desktop behavior remains untested here. Container
architecture checks are not substitutes for those environments.

## Earlier rollout: setup verification and Continue

The setup footer now offers **Verify and continue** for a saved connection that
needs a readiness check. It verifies and advances in one guarded operation;
failed checks remain on the model step with a message beside the action. Missing
credentials, model selection, consent, locked credentials and unsaved changes
remain gated. Disabled buttons have styling that also applies to the setup
dialog's portal. The sidebar status now reads **Local workspace**.

All 136 frontend tests, the production build, 16 Python onboarding regressions,
Ruff and the diff check passed. The onboarding regression covers footer success,
failure and explicit retry, duplicate clicks, blocked edits while checking,
unchanged ready-state navigation, and missing setup requirements.

Both final Linux images passed the complete disposable workspace smoke:

- ARM64: `sha256:d5d9fa0a608f33ac48a30301a54c126888ef972bb6b83b1c5ed60f8844680a5f`.
- AMD64, emulated on macOS: `sha256:712799c58da12d2fb70631b86a496b654c40740011828622b71c7442f16a9ecd`.

The first AMD64 run passed workspace checks but failed the actual Goose browser
sign-in startup/poll/cancel probe. A separate rerun of the same image passed all
checks. The failure's cause was not established. The smoke now reports its
failing phase and exception type without printing authentication URLs or secrets.

Before installation, a live GPT-5.6-Luna request through the production API and
isolated Goose container completed intent assessment, ranked report generation,
and public-reference search. It returned 12 compositions from 218 public records
and 28 reference leads; the partial result retained its missing-property caveats.
Goose reported 6,425 tokens for that run; cost and account quota were unavailable.
This was authenticated model inference, distinct from the anonymous and synthetic
checks below.

The final ARM64 image was installed and the native macOS app reopened. Its setup
completed with the backend reporting `completed=true`, `can_research=true`, and
model status `ready`. The workspace displayed the shortened footer; all 27
workspace-table row counts matched their pre-update counts. Native Windows and
Linux desktop execution remains untested. Older deployment-status statements
below describe previous checkpoints.

## Prior rollout: broader dielectric retrieval and report display

This checkpoint supersedes deployment-status statements in the historical
sections below. The current update passed **1,898 Python tests and 98 subtests**,
with 48 PowerShell-dependent tests skipped on this Mac, **136 frontend tests**,
the production frontend build, Ruff, and **18 native Rust tests**. Source and
wheel distribution checks passed, including private-file exclusion.

Both Linux images passed the complete disposable `--workspace` Docker smoke:

- ARM64: `sha256:861eac1ae34a90aefa0ae70d7b7deca9cccaa1ef5a6ce1adbbe393916b3e7f96`.
- AMD64, emulated on macOS: `sha256:1af7edc7d8c577989d799f9fcfb3ae2b7accb0851c83b81c3c164796a518d51e`.

For each image, all 1,186 compared source and static files matched the checkout.
The smoke includes workspace and pin lifecycle, exports, isolated Goose browser
flow startup/cancellation, synthetic encrypted credentials and restart behavior.
It does not perform account authorization or model inference.

Anonymous live retrieval inside Docker downloaded the fixed public dielectric
release and returned 218 oxygen-containing records. Ranking the retrieved set
produced a 12-composition shortlist that included ZrO2 and HfO2; a ZrO2 structure
was also retrieved and validated. This is an observed run, not a fixed candidate
list or a claim of experimental suitability. The configurable 2 eV minimum in
the default High-k profile is a screening preference. Missing stability and
other unmeasured properties remain explicit. See the [dataset access and
provenance](public-dielectric-dataset.md) and [ranking algorithm](ranking.md).

The updated ARM64 image and rebuilt macOS ARM64 desktop app were installed.
Comparison of 26 workspace tables found only the intended ranking-profile
changes; all 11 chats and eight reports were preserved. Database integrity and
foreign-key checks passed. The native app displayed the new minimum-gap setting,
proper SiO2 ordering and count subscripts, and the neutral evidence-coverage
presentation for a historical report without changing its saved scores.

JSmol rendered the saved public structure in the native Technical View. Fresh
CIF downloads were 3,368 bytes and matched the cached source-derived file's
SHA-256:
`8da0a52652974f7b9a1b428b49176eace6964aad5198d0f3dea5124252c811ab`.
An accessibility-control request temporarily timed out during the check; a fresh
app handle returned a responsive interface, and both the earlier delayed download
and the repeated download completed. The sampled main thread was idle in the
normal application event loop. These observations do not establish a deadlock.

Native Windows and Linux desktop execution remains untested for this rollout.
ChatGPT is currently disconnected and requires a fresh sign-in. No new
authenticated model inference was run after installation; the historical Goose
tests below do not replace that remaining end-to-end check.

## Active model selection from the chat popup

The Language model popup now loads the active account's model catalog on open.
Selecting a model saves it and verifies connection readiness without running
inference, changing credentials, or enabling cloud consent. Confirmed selections
remain saved if verification fails; retrying checks the connection without
repeating the save. Historical reports retain their original model provenance.

All 123 frontend tests, the production build, and Ruff passed. The expanded
composer regression covers automatic model loading, stale responses after an
account/credential change or popup closure, catalog retry, unchanged credential
storage and consent, blocking new requests during verification, mismatched
verification identity, and recovery after an uncertain save. All 1,565 Python
tests passed across the main run and a permitted loopback-socket rerun; the
restricted environment initially prevented two proxy tests from opening their
local listeners. The 48 PowerShell-dependent tests remain skipped on this Mac.

## Report presentation, chat refinement, and project pins

The report/pinning update passed 1,565 Python tests (48 PowerShell-dependent
tests skipped on this Mac), 123 frontend tests, Ruff, the production frontend
build, and private-file distribution checks. The macOS desktop build succeeded;
18 native Rust tests cover the updated navigation/download boundaries.
No native Windows or Linux desktop execution is implied.

Both images passed the extended Docker workspace smoke, including saved
snapshot export preservation, latest-report tracking, explicit snapshot
replacement, stale-write rejection, removal/restoration and restart persistence:

- ARM64: `sha256:9acf0884f9bc4a02b3f8c2483683717e2e9525e5f556f290493a9a0ddcc9447e`.
- AMD64: `sha256:14be7de2d60bf0fc6b088f686566ad9fbde42002aa44db1dd2dcc0625748e9e2`.

Those Docker runs use source-unavailable fixtures for pin lifecycle checks, not
invented scientific results or real model inference. They also verify Goose
browser-auth startup/cancellation, private worker networking, export formats,
CSRF and synthetic encrypted-vault restart/unlock.

The cleaner document layout was checked against actual earlier saved reports.
All seven pages of a broad-query PDF and Word export were visually reviewed,
including table pagination; the scientific result and original report archive
remained unchanged. Saved-format display and explicit current-format preview
share the same presentation preparation as exports. Reformatting does not rerank
or modify snapshots.

Forty-five offline continuation regressions verify same-chat preference
snapshots, explicit overrides, context isolation, canonical source identities,
public/embargo checks and a shared repository deadline. Anonymous live retrieval
also re-fetched all six earlier NOMAD identities before compiling a revised
ranking. The bounded sample remains a set of composition matches with unresolved
application suitability; even an oxygen-containing bulk structure can be an
inappropriate thin-film candidate. The versioned conservative element policy and
simple-composition sampling preferences are documented in [ranking](ranking.md).

Live anonymous discovery returned Wikipedia background introductions, OpenAlex
open-access metadata and ChemRxiv-indexed preprint references. Preprint-disabled
queries were checked separately. These are unscored review leads; full-text
retrieval and credibility are not inferred from index metadata. See
[public sources](public-sources.md) for supported access and remaining limits.

Authenticated Goose research below predates this update. A new sign-in and live
model run are required to verify the installed update end to end; offline,
container and anonymous source tests do not substitute for that check.

The verified ARM64 image and rebuilt macOS app were installed locally. A private
SQLite backup was checked before migration, and all pre-existing rows in thirteen
workspace/history/settings tables matched after the schema-4 to schema-5 upgrade.
Database integrity and foreign keys passed. The installed service returned both
saved/current presentations and all eight associated format downloads for a real
saved report, preserving its scientific JSON. Its cached structure metadata
remained available. The first native UI check was blocked by the locked Mac.
After unlock, the native application opened saved Summary/Technical View reports,
rendered the cached silica structure in JSmol, and downloaded its CIF through
the native download handler. The downloaded bytes matched the cached structure
hash. No fresh authentication or model call was attempted after replacing the
session-only backend.

## Current Goose browser integration and live public-source diagnostic

The main Docker workflow now uses the native Goose browser OAuth broker. Its
private configure process answers two setup menus and stops at model selection
before inference. The app's callback-only listener forwards the matching active
state to the unexposed worker; session/encrypted-vault storage is retained. Codex
supplies account/model/usage metadata. The older device broker is for legacy
configurations, without automatic fallback. Real account authorization, setup
verification and three authenticated research requests have now completed in the
installed main application, through its isolated Goose worker.

The broker passed **25 offline tests**, plus **46 existing ChatGPT-auth tests**,
and Ruff checks. Real local PTYs with synthetic provider output verified only two
menu answers, termination before inference, temporary-file cleanup, cancellation,
expiry and bounded output. Tests also cover consume-once credentials, ownership,
cache validation, matching callback state and rejection of upstream response
text. These tests do not claim provider authorization. POSIX worker filesystem
and PTY checks are separate from native Windows-host coverage.

### Authenticated main-application research

The following live requests ran on the installed Linux ARM64 Docker backend on
macOS, using ChatGPT account sign-in and keyless public sources. Each saved a
Summary, Technical View, source list and immutable ranking-profile snapshot.

| Model and request                                          | Explicit ranking profile                       | Observed result                                                                                                      | Reported total tokens |
| ---------------------------------------------------------- | ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | --------------------: |
| `gpt-5.6-luna`: compare bulk Si, Ge and GaAs               | Semiconductors · Optoelectronics (exploratory) | Two shortlisted compositions, Ge and Si, from ten NOMAD records; 14 retained sources                                 |                 5,996 |
| `gpt-5.6-terra`: screen oxide dielectrics                  | Oxide dielectrics · High-k screening           | Three shortlisted compositions, O2Si, Al2O3 and HfO2; 13 retained sources                                            |                 9,046 |
| `gpt-5.6-luna`: broad oxide question without formula hints | Oxide dielectrics · High-k screening           | Six oxygen-containing compositions and 16 retained source records; incomplete safety/application screening diagnosed |                 8,078 |

Both runs recorded completed intent-assessment, reference-search and report tools.
The first search stage was executed as a report dependency before the agent's
explicit search call; it ran once. Usage is reported for those requests, not an
account allowance or cost estimate. The previously selected model was restored
after testing without replacing the saved account.

The broad-query diagnostic exposed Pm-, Ac- and Pu-containing records that the
old element-exclusion preference did not cover. Those saved reports retain their
original evidence and scores. The updated conservative policy excludes those
matches when element screening is selected and records its exact version/set;
surviving records remain unassessed for compound safety.

Both reports are **partial scientific results**. The semiconductor ranking lacks
refractive index and stability, with Si gap directness also unknown. Ge ranks first
primarily because its source reports a direct gap; this is an exploratory profile
outcome, not demonstrated application suitability. The oxide run lacks stability
and both dielectric scalars despite the High-k profile. Missing weights remain
in the denominator. Literature passages are attributed review leads and do not
fill these missing properties. General discovery returned some loosely relevant
references, and a bounded literature lookup exhausted its budget.

A read-only audit recomputed retained source-field hashes, NOMAD unit conversions,
weighted scores and table consistency. Selected profile snapshots matched their
recorded weights; public source links and passage/article digests agreed. This
did not independently refetch full HTTP bodies, establish method comparability
or demonstrate exhaustive retrieval. Raw alternate and excluded records are not
retained in the saved report, so the complete original sample cannot be reranked
from that report alone.

Separate server intake checks returned three guiding questions for a vague
request and refused a request for private/paywalled data and fabricated values.
Each retained the conversation with no report or sources. These exercise the
fixed gate before model and retrieval work; they are not evidence of the model's
own resistance to an adversarial prompt.

The audit prompted a source-level clarification separating **supported-field
completeness** (`evidence_quality`) from **selected importance coverage**. Neither
means scientific confidence. The revised report text, catalog label and four
export formats passed 141 focused Python tests, Ruff and a frontend build;
relevant PDF/Word pages were visually checked using the saved public result.
Scoring and saved historical report text were unchanged. This clarification and
the separate discovery-relevance correction have **not yet been deployed or
verified by a new live request**; the two runs above used the prior wording and
retrieval behavior.

### Independent public-source diagnostic

The independent Goose container did perform live public-source requests using an
authorized temporary account. Fixed Europe PMC tools searched public metadata
and retrieved available open-access XML. A first literal-quote test passed for
`gpt-5.6-luna` and `gpt-5.5`, while `gpt-5.6-terra` was rejected with
`quote_not_in_retrieved_fulltext`. The failed quote was not accepted as evidence.

The revised diagnostic has the model select a source ID and quote-span ID.
Application code verifies the IDs against the retrieved response and assembles
the quote/citation itself, preserving its retrieval URL, time and digest.

| Live span-selection model | Result | Reported total tokens |
| ------------------------- | ------ | --------------------: |
| `gpt-5.6-luna`            | Passed |                 3,326 |
| `gpt-5.6-terra`           | Passed |                 3,832 |
| `gpt-5.5`                 | Passed |                 3,844 |

The low-cost clarification check also passed with `gpt-5.6-luna` (465 reported
total tokens). These are observed diagnostic runs, not fixed product results or
an inferred account balance. The diagnostic is a bounded Europe PMC search and
full-text test, not an arbitrary-site crawler or an end-to-end materials-ranking
evaluation. See [the diagnostic and its limits](goose-chatgpt-browser-test.md).

## Final browser-start and workspace deployment checks

The final images passed the full disposable workspace smoke, including actual
installed Goose browser-flow start, validated pending state, polling and
cancellation without account authorization or inference:

- Linux ARM64: `sha256:2c9d2edb600e77fe2f623140cfbe86bd0851cb738ebe8aedb8d1a67789b46fd2`.
- Linux AMD64, emulated on macOS: `sha256:38fe54c7cdcd9b9f3e081be613bb8719d18a515d4d486dd112c16ff1998ae804`.

The live container check caught a helper incorrectly executed from `noexec`
temporary storage. Capture now invokes the installed Python interpreter directly;
the storage restriction remains enabled. The smoke test exercises this actual
Goose path so synthetic PTY tests alone cannot conceal a broken browser helper.
Workspace history, exports, removal/restore, ranking profiles, encrypted test
credentials, restart behavior and network/filesystem isolation passed on both
images. Native Windows and Linux desktop hosts were not exercised.

The updated main installation retained its workspace, exposed its UI and callback
only on loopback, and reported all three services healthy. Its public connection
API reached a native Goose pending flow, rejected a mismatched callback state
without reflecting its query, and cancelled cleanly. The independent diagnostic
was then no longer needed and its temporary login was erased. The subsequent
main-application authorization and research results are recorded above.

The macOS desktop window verified initial setup, collapsed advanced credentials,
one project composer and initial chat, functional Remove chat, visibility in
Removed items, restoration, and sidebar hide/show with View still accessible.
Pointer resizing and other new controls have automated coverage; a native drag
check remains pending. Python tests (1,385), frontend tests (112), native tests
(16), production builds, Ruff, and distribution private-file exclusion checks
passed. The installed local macOS bundle was ad-hoc signed and its signature
verified; release signing/notarization is separate. The 48 PowerShell
checks were skipped because PowerShell is unavailable on this Mac.

A separate packaged-core check queried live public NOMAD records with composition
hints. Ten retrieved records produced two ranked candidates with recorded response
provenance and missing-property caveats. This earlier core-only check is separate
from the subsequently completed authenticated application requests above.

## Retrieval and onboarding correction checks

The onboarding model-card verification now updates the setup readiness state,
including Save and test. A second footer verification is no longer required; an
idle disabled Continue button no longer displays a busy cursor. Automatic model
discovery waits for connection mutations. DOM checks cover success, failed
verification, unsaved changes and model-list request ordering. A transport-error
regression also ensures automatic refresh cannot silently restore an older ready
state after a failed verification.

The final source tree passed 1,423 Python tests and 112 frontend tests, plus
Ruff, the production frontend build, and source/wheel private-file exclusion
checks. Two socket tests initially could not bind loopback ports under the local
test sandbox; both passed with socket access, as did the final full suite. The 48 PowerShell tests
remain skipped on this Mac. No native-shell code changed at this checkpoint.

Both saved live reports were reopened through the main application API and
downloaded as TXT, JSON, PDF and Word. JSON retained the exact saved research
result; the native macOS window displayed the oxide Summary and Technical View.
These checks generated no additional model requests.

## Independent Goose browser-login proof

The [separate Goose-only Docker diagnostic](goose-chatgpt-browser-test.md)
completed native ChatGPT browser OAuth without an API key. Two real
`gpt-5.6-luna` requests returned the exact diagnostic reply, including a second
Goose process reusing the cached login. Each reported 299 total tokens. The
callback relay passed a synthetic host-to-container-loopback transport check.
No Labcat workspace, host credentials or tools were available to the test.

This live proof ran on ARM64 Linux under Docker Desktop on macOS. Actual Goose
configuration also passed with synthetic providers in network-disabled ARM64
and emulated AMD64 containers. Other account providers and native Windows/Linux
browser login remain untested. This diagnostic used its own temporary login;
the main-application integration status is recorded above.

## Earlier public-structure and device-setup checkpoint

Saved shortlisted entries can retrieve compatible public structures through
exact-ID adapters, render them using locally bundled JSmol and download a
derived P1 CIF. Unsupported, missing, disordered or inconsistent structures stay
unavailable. Retrieval preserves provenance and phase/representation caveats;
it does not alter report scores. Developer Settings persistently disables the
viewer while retaining CIF retrieval and downloads. The opaque iframe accepts
only canonical numeric data and fixed viewer commands; its asset-only CORS/CSP
does not grant access to workspace APIs, credentials or external sites.

New model connections use provider names, with existing custom labels and
credential identities preserved. Model catalogs load automatically after a
connection, sign-in, unlock or account switch; stale requests are cancelled.
Catalog discovery does not run inference or select a model. The ChatGPT device
flow uses the existing pinned helper and now explains the required account
Security setting, links to official guidance and offers a fresh-code retry.
At this earlier main-application checkpoint, ChatGPT sign-in completion and
inference were not exercised with user credentials. The current browser flow and
later independent live checks are recorded above.

At that checkpoint, **1,209 Python tests**, **102 frontend tests**, **14 Rust tests**,
frontend production build and Ruff lint/format checks passed. The 36 PowerShell checks
were skipped on this Mac; two upstream TestClient warnings remain. Coverage
includes exact report/material scoping, provenance, coordinate/unit/composition
validation, corrupt caches, lifecycle and persistence, viewer toggle, CSRF,
iframe messages and stale account/report responses. Wheel and source archives
contain the pinned runtime and matching source, licenses and notices; all 1,654
vendor/source files match the checkout and private files remain excluded.

A browser rendered an eight-site structure retrieved anonymously from a live
public NOMAD entry. The source's terminal-system representation and limitations
were displayed. The CIF contents and hash were verified; Materials Project
structure transport was tested with protocol fixtures, without a real API key.
No fixture supplies product search results.

A restricted direct launch of the separate macOS QA bundle aborted during
application registration before the webview initialized. The supplied crash
report identifies that test process. The approved desktop-context retry ran;
the managed app was not involved in that failed launch. GUI testing now uses
a desktop-capable context and a separately identified QA bundle to avoid
confusing its windows with the user's installed app.

Native macOS testing verified actual atoms and the unit cell, rotation/reset,
exact downloaded CIF bytes, and viewer off/on with downloads preserved. The
connection screen showed provider-name defaults, automatic model discovery
guidance and the device-sign-in prerequisite. The separate QA window was closed
afterward. Native Windows/Linux rendering was not tested.

The host preview's missing secure temporary storage now produces a fixed,
actionable setup code instead of a misleading credential-validation error.
The client maps only reviewed codes to local help text; it never displays raw
provider/server messages. A disposable ARM64 Docker API successfully initiated
the real official ChatGPT device flow, returned a pending challenge, cancelled
it and removed its temporary files. No personal account or inference was used.

OpenAI API, Anthropic API, Kimi and supported Bedrock models were verified to
dispatch through the same isolated Goose worker without direct-provider fallback.
Provider tests passed with inert fixtures; this does not establish live account
access or model inference. Bedrock discovery now includes active returned
inference-profile IDs with bounded pagination. Exact pinned Goose models needing
the unsupported Mantle/bearer-token path are excluded and cannot pass readiness.

Final Linux Docker images passed full disposable workspace, export, restart,
credential-isolation and structure HTTP checks, with all installed source,
interface, vendor and license files matching the checkout:

- ARM64: `sha256:f9364892d1b75d1737cf86ebb109bc317f6c48805ec0aa734c0f68159d22e02a`.
- AMD64: `sha256:a87fb155353c38c1c0e3569520037874b7fc5cb991bd69d6d87100d6add5b1a0`.

AMD64 used Docker emulation on this Mac. A stalled desktop-control session and
Docker engine caused earlier build timeouts. Generated native build caches were
removed to free space, Docker Desktop was restarted without resetting data, and
the final builds passed. The full Python suite passed in a separate test
temporary directory after an earlier shared temporary-directory run had SQLite
setup errors. The managed ARM64 update preserved every prior workspace row and
passed database integrity and foreign-key checks after a private backup. All
three services are healthy, Goose is available, and served frontend bytes match.

## Source registration and API guides

Connections and the public-sources setup step now link to Materials Project
registration/API access and its account dashboard. The four supported keyless
source cards link to their official API guides in Connections and Search Criterion
and clearly state that their public lookup requires no account or key.

Native testing identified an external-link routing issue: WebKit can consult the
navigation policy before the new-window handler. The native shell now sends
already approved public/reference and provider sign-in destinations to the system
browser before rejecting their navigation inside the app. The same-origin rule,
existing URL allowlists and absence of frontend native privileges are preserved.

All **83 frontend tests**, **1,144 Python tests**, **12 Rust tests**, production
frontend build and lint/format checks passed. The 36 PowerShell checks were
skipped on this Mac, and two upstream TestClient warnings remain. New Rust checks
cover approved guide URLs, exact provider sign-in, local navigation, spoofed hosts,
credentials in URLs, alternate ports and unsupported schemes.

The rebuilt macOS app passed native checks at normal and 680-pixel widths.
Clicks on Materials Project registration and the Europe PMC guide each opened
one new tab in the system's default browser, while Labcat stayed on Connections
and its credential field and saved preferences remained unchanged. No registration,
sign-in or credential access was performed. Native Windows/Linux were not tested.

Both Linux Docker images passed the full workspace smoke checks and exact matching
of all 53 installed source/config/interface/font files: ARM64
`sha256:065f62b5cbad4b2e794d9ca1e90b4b87d04e0abe39557b568e60c1db05ac1d45`
and AMD64
`sha256:4eb88dfcd6ae5cd375d66e7f33f135992fde7f53aefd9a90e4ea28490f1b287e`.
AMD64 ran under emulation on this Mac. Goose provider workflows were unchanged
and were not rerun. The managed ARM64 update preserved all existing workspace
rows and passed identity, integrity and foreign-key checks after a private backup.

## Chat identity and project assignment

Every saved chat has an immutable workspace number and a display label combining
its editable title with that number. Matching raw titles stay distinguishable
without changing UUID routes, automatic naming or existing history. Numbers
survive moves, renames, removal and restoration and are not reused after purge.
The migration adds identity metadata for active and removed chats in creation
order, transactionally, without rewriting prior records.

The conversation header shows its project or General Chats as a label. Assignment
is available through **Move chat** in the sidebar options menu, including a
keyboard/touch destination dialog; general chats also support drag-to-project.
The language-model and ranking-profile controls remain beside the prompt.

All **1,144 Python tests** passed, with 36 PowerShell tests skipped on this Mac
and two upstream TestClient warnings. New coverage includes legacy migration,
duplicate and Unicode titles, concurrent creation and initialization, rollback,
first-prompt naming, draft reuse, moves, restoration, purge and immutable API
identity fields. A legacy fixture now enforces foreign keys when simulating an
empty project; the production integrity checks remain unchanged.

All **83 frontend tests**, the production interface build and Ruff lint/format
checks passed. Interface checks cover matching chat names, raw-name editing,
numbered report and removed-item attribution, maximum safe-integer labels,
General Chats/project transfers, Cancel, preserved drafts and a single composer.
Moving does not implicitly pin a report. Pending moves block conflicting workspace
mutations, and uncertain responses require checking the saved destination before
retrying. An independent review confirmed the move guards and UUID routing.

Native macOS checks passed in an isolated workspace at 1056- and 680-pixel
window widths. Duplicate names, raw-name editing, moves in both directions,
draft retention, removal/restoration, keyboard navigation and the remaining
model/profile controls behaved correctly. Long titles and a maximum-number
rendering fixture stayed readable without colliding with the options button.
Model setup remained required. Native Windows/Linux were not tested in this
milestone; no personal model credentials or inference were used.

Linux ARM64 image
`sha256:b2be0cb5d40a028309828f5e6397dc15162589d9667df030f2c8e06848d60b21`
and AMD64 image
`sha256:b2a9bbfe508e728fcef66f53a188b7e4f3a3697c608e281c57b30e176f781b00`
passed the full disposable workspace smoke tests, including numbered identities
across both restarts, purged-number non-reuse, report exports and worker isolation.
All 53 installed source/config/interface/font files match the checkout. AMD64
ran under Docker emulation on this Mac. Goose provider workflows were unchanged
and were not rerun for this interface and workspace update.

The managed ARM64 installation was updated after a private backup. All previous
workspace rows were preserved, every chat has a unique positive number, and
SQLite integrity and foreign keys passed. All three services use the tested
image and are healthy; the native shell binary is unchanged.

## Removed items and confirmation preferences

The removal dialog aligns Cancel and Remove actions and can remember a preference
to skip recoverable-removal confirmations. Removed items provides a control to
turn those confirmations back on. The preference is stored with the workspace,
independently of report and scientific settings. Rows and the displayed preference
refresh when removal occurs from the sidebar while the list remains open.

Removed projects and chats can be restored or permanently deleted. Permanent
deletion always requires its own explicit confirmation and a same-origin session
token. The server accepts only already removed items. Project deletion cascades
within the project; chat deletion preserves shared and project-pinned sources.
Transactions, foreign keys and late-research checks prevent partial deletion and
resurrection of a deleted chat. Existing exports and external backups are unaffected.

All **1,136 Python tests** passed, with 36 PowerShell tests skipped on this Mac
and two upstream TestClient warnings. New checks cover strict confirmation,
cross-site protection, preference persistence, actual removed-list response
shapes, restoration, shared sources including archived siblings, moved chats,
internal scopes, rollback and in-flight research. Destructive tests use isolated
fixtures; no existing user project or chat is deleted by validation.

All **81 frontend tests**, the production frontend build and Ruff lint/format
checks passed. UI regressions include removal while Removed items remains open,
preference changes across navigation and reload, Cancel behavior, explicit
permanent-deletion confirmation, authenticated requests and failure handling
without automatic retries.

Native macOS checks passed at normal and 680-pixel window widths using an isolated
workspace: aligned actions, Cancel versus saved removal preference, immediate
list/counter refresh, project and chat restoration, restart persistence and the
separate permanent-deletion warning. The final irreversible GUI action was not
clicked; confirmed deletion was exercised through DOM, API and Docker tests.
Native Windows/Linux were not tested in this milestone.

Final Linux ARM64 image
`sha256:fb34be85b58031246f197737493f8f8cbe17ee04e20cea126aebfbd4a4b6a344`
and AMD64 image
`sha256:45bc5ffef6596eb5009c864e0cfa613451529810d79218d8bca2ed9e793fa7a8`
passed the full disposable workspace smoke tests, including deletion, restoration,
preferences, exports, restart persistence and worker isolation. AMD64 ran under
emulation on this Mac. All 53 installed source/config/interface/font files match
the checkout with no stale assets. Goose provider workflows were unchanged and
were not rerun; their prior milestone results remain below.

The managed ARM64 installation was updated after a private backup. Every existing
workspace row was preserved, and SQLite integrity and foreign keys passed. The
native application binary is unchanged. Fresh Python archives passed private-file
exclusion, exact source/assets/docs checks and an isolated base installation with
networking disabled and the model setup requirement retained.

## Research safeguards and consistent ranked reports

Requests now pass fixed server checks and a closed model suitability assessment
before research retrieval. Clarification and refusal are saved as conversation
messages without report or source artifacts. Same-chat follow-up tests preserve
refused intent while allowing a concrete benign change of scope. Source-screening
checks cover role spoofing, policy overrides, hidden control text, credential
requests, malformed passages and attempts to promote source instructions into
evidence. These are basic defenses, not proof against every harmful prompt.

Summary and Technical View share saved ranking-profile and presentation snapshots.
Tests cover all selected properties, missing and unsupported values, evidence
identity/digest correlation, duplicate records, zero usable evidence, weighted
utilities and fixed score colors. Wide tables retain all properties in the desktop,
PDF, Word, TXT and JSON outputs. The weighting formula and its application limits
are documented in [ranking](ranking.md); intake and evidence boundaries are in
[research safeguards](research-safeguards.md).

All **1,101 Python tests**, **76 frontend tests**, the production interface build
and Ruff checks passed. The 36 PowerShell tests were skipped because PowerShell
is unavailable on this Mac; two upstream TestClient warnings remain. Transport
tests verify complete accepted prompts up to 20,000 characters reach assessment
and oversized requests are rejected without silently dropping text.
Native macOS review used an isolated workspace at 1056 × 768 and 680 × 803. It
covered written summaries, detailed tables, saved weights, explicit horizontal
navigation, sticky material identity, unknown values and conversational intake.
The report fixture was clearly marked test-only and contained no live provider
credentials. All 16 final PDF/Word fixture pages and all three updated design-note
pages were rendered and visually inspected. Native Windows and Linux were not
tested for this milestone.

Final Docker images passed the full isolated workspace and actual Goose checks:

- Linux ARM64: `sha256:1e540a30496a93237ae6f3bda35a98704991eac3f87d7ddb2cbcb4dd1455fce5`.
- Linux AMD64: `sha256:505e0d8c4c4788c0526c536fd18b83f69b0f0e370a7b5494495160a5a4fe6665`.

AMD64 ran under Docker emulation on this Mac. The installed Goose binary used a
simulated provider to exercise intake, public search, ranking, authenticated
callbacks, injected-shell rejection, bounded tools and retained server reports.
The checks caught and corrected an outdated worker proxy that initially rejected
the new intake tool; final tests passed after rebuilding both images. Installed
Python source and interface files match the frozen checkout. Disposable stacks
were removed without altering the managed workspace.

The managed ARM64 installation was updated and the native macOS window reopened.
Every prior workspace row was preserved; SQLite integrity and foreign-key checks
passed. All three services use the tested image and report healthy status. The
native window displayed the updated Summary/Technical View controls and template,
with the required model setup gate still enforced. The native shell binary was
unchanged by this backend and interface update.

Fresh wheel and source archives passed private-file exclusion and exact packaged
Python, interface and font checks. A temporary wheel installation without optional
dependencies or networking passed CLI help/status/config checks and correctly
required model setup for research. The installer allowlist includes the new
ranking and research-safeguards documentation; its 27 tests passed.

No personal model inference or real account login was used for these checks.
Quantitative coverage remains limited to approved adapters and supported fields;
open literature passages remain cited review leads, not automatically scored
measurements. A missing connection or unavailable source does not produce a
fabricated shortlist.

## Compact project sidebar

Project cards now show chats, reports and sources on one dot-separated line.
Large counts use compact notation with exact hover and accessible labels; long
names truncate within the title row. The underlying saved counters are unchanged.

All **70 frontend tests**, **990 Python tests** (36 PowerShell checks skipped),
the production frontend build and Ruff lint/format checks passed. Native macOS
checks at 1056 × 768 and 680 × 800 covered normal and maximum-safe counts, long
names, expanded chats and project options. Browser widths below the native
minimum and native Windows/Linux were not visually tested for this change.

Fresh Python archives passed private-file exclusion and exact frontend/font
checks. Their non-static package bytes match the previously tested wheel; the
isolated base-install test was therefore not repeated.

The updated Linux ARM64 image
`sha256:d22832722ca1f9b1f3f79dd19476cbc225a4736e5b71205b76544f4760531910`
and AMD64 image
`sha256:7ec16007ae925bf29b5231d79aac7623e8146b51fed01ba5654c8662dce228ec`
passed targeted Docker checks: non-root/read-only startup without capabilities or
host mounts, health/runtime responses, and exact final HTML/JS/CSS delivery.
AMD64 ran under emulation on this Mac. Scientific retrieval and Goose integration
were not rerun for this cosmetic change; their previous coverage is recorded below.

The managed ARM64 backend was updated and the native app reopened. Existing
workspace rows, SQLite integrity and foreign keys all passed preservation checks;
the expanded project displayed the new count line with its existing chats.

## Report Format, Search Criterion and developer edition

Current source checks: **990 Python tests passed**, with 36 PowerShell checks
skipped because PowerShell is unavailable on this Mac. Two upstream TestClient
deprecation warnings remain. All **70 frontend tests**, the production build,
Ruff lint/format checks and **10 Rust native-shell tests** passed.

Coverage includes user-edition absence of developer routes, same-origin/CSRF
protection, bounded research controls, CLI use of installed controls, explicit
model-choice preservation, and source credentials changed or revoked while an
agent is planning. Credentialed source selection requires current verification;
keyless sources remain independently selectable. No real model credential or
paid inference was used.

Report settings are snapshotted into new reports. Export tests verify saved-layout
precedence, legacy fallback, all four output formats, safe preview tickets and
fixed rendering choices. Twelve actual PDF/Word pages were rendered and visually
inspected across three appearance variants, including Letter/A4, serif/sans,
font sizes, table styles, accents and page-number choices. The three-page design
note was updated and visually inspected. PDF and Word in-app previews are labeled
representative layouts; downloaded files provide final pagination.

The rebuilt native macOS app was exercised in an isolated workspace at
1056 × 768. Report Format, Search Criterion and Connections showed their intended
controls with no duplicate composers. All four preview downloads were created in
OS Downloads and parsed successfully. Serif appearance survived navigation and
backend restart. Developer-only controls saved and reopened correctly, while the
user edition hid the tab. Source selection remained disabled without a verified
key. A regression test also checks that the Connections model card follows the
selected account and does not confuse selection with verified readiness.
The app-only build succeeded; optional DMG packaging did not complete. The native
application is distributed in the Mac ZIP. Native Windows/Linux and live personal
model inference were not tested in this milestone.

The final Linux ARM64 image
`sha256:147659bd30e1811821e48d7b20580ebbc2b9ca7137773909a7d10a373c94ad90`
passed full isolated workspace tests, actual Goose with a simulated provider,
new-feature API checks, and installed source/font/static-file hash verification.
These checks include source gating, template formats/CSP, developer edition
boundaries and persisted controls after returning to the user edition.

The final AMD64 image
`sha256:36b16e86979841b5c884fd479d38a28c1e2216e9cfdc0519159509cabd8a1bf0`
passed the same complete checks under Docker emulation on this Mac. This is not
native Linux or Windows desktop coverage. All disposable test stacks were removed.

The managed ARM64 installation was then updated and reopened in developer mode.
All previous workspace rows remained, with SQLite integrity and foreign-key
checks passing. The native window displayed Report Format and its styled template
on the updated backend. The model setup requirement remained enforced; no model
account credentials were supplied or inference run.

Fresh wheel and source distributions passed private-file exclusion checks.
An isolated dependency-free wheel installation with networking blocked passed
CLI help/status/config validation and correctly rejected unauthenticated research.
Both archives contain exactly the final compiled interface and bundled fonts.

## Live public API compatibility check

A user-authorized, memory-only credential test identified two integration issues:
the generic connection probe received HTTP 403, while the scientific transport
successfully retrieved data; default alphabetic material IDs then failed the
existing numeric identity validator. Both paths now share the bounded public-source
transport and explicitly request the API's supported `id_format=legacy` response.
See the [provider's identifier update](https://matsci.org/t/updates-to-identifier-systems-in-the-materials-project/67442).
No local identifier conversion or relaxed scientific validation was introduced.

The revised metadata probe checked one public ID. A single exact-formula query
for TiO2 and HfO2 returned 61 validated records with zero rejected records, and
equal band-gap/stability priorities produced a two-composition shortlist with
source provenance and a written summary. Missing data kept the result partial.
This exercised the shared scientific core; it was not a personal model inference
test and did not bypass the application's required model connection. The key was
absent from the complete result and was not written to a repository file, test
fixture or distribution.

Regression checks: 923 Python tests passed, with 36 PowerShell checks skipped on
this Mac and two upstream TestClient warnings. All 62 frontend tests, the
production build, Ruff lint and formatting passed. Focused tests cover the fixed
identifier format, one-record/16 KB probe, malformed identities, request limits,
credential exclusion and safe HTTP error reporting.

Full workspace and actual Goose checks with simulated providers passed on Linux
ARM64 (`sha256:299eb4ef5526399969faed2bf91809b5b42198aae9203b8181cd1709384841e7`)
and locally emulated AMD64
(`sha256:f22386a5f23664a8fe48d1102fc5445a92ab9b2b42e5b1c30d62a62801589680`).
Installed source hashes match the tested checkout. Native Windows/Linux and
personal model inference remain untested for this fix.

The managed ARM64 installation was updated with all three services healthy;
every existing workspace row was retained with valid foreign keys. The reopened
native macOS app accepted the key in session-only storage and showed the public
API connection as Ready. The unconnected model remained correctly unavailable.

## Property catalog and literature follow-up milestone

The catalog is source-neutral, displays each property category directly and starts
new selections at 0.5. Saved weights are retained. The active ranking profile
appears above the editing preview. Repository retrieval precedes targeted searches
for missing selected attributes; public article passages remain unscored review
leads with source locations and content hashes.

| Check                  | Observed result                                                                                                                                                                                                                                                       |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python                 | 913 passed; 36 PowerShell checks skipped on this Mac; two upstream TestClient warnings. Ruff lint and formatting passed                                                                                                                                               |
| Frontend               | 62 tests and production build passed                                                                                                                                                                                                                                  |
| Native macOS           | Actual Tauri app verified direct categories, initial expansion, 0.5 selection defaults, synchronized slider/manual entry, chart order, save/activate and profile reload in a disposable workspace                                                                     |
| Public text adapter    | 32 tests cover fixed destinations, XML identity/entity/size/depth protections, malformed JSON, source selection, bounded queries, missing text and instruction rejection                                                                                              |
| Live public lookup     | One TiO2 band-gap lookup read public article [PMC13412965](https://europepmc.org/articles/PMC13412965) and retained three literal body passages in 1.962 seconds. This verifies retrieval and attribution, not material suitability or numerical evidence for ranking |
| Workflow               | Tests enforce repository-before-literature order in direct and Goose paths, single retrieval, missing attributes only, digest/identity binding, preserved pin provenance and no candidate value/score changes from excerpts                                           |
| Design / distributions | Three-page design note rendered and visually checked. Wheel/source archives passed private-file exclusion checks                                                                                                                                                      |
| Report exports         | Attribute table, excerpt and provenance visually checked in PDF/Word with a labeled test fixture. Short Word provenance blocks stay together; longer blocks still paginate. 43 export tests pass                                                                      |
| Linux ARM64 Docker     | Full workspace smoke, actual Goose with simulated providers and network-disabled packaged literature checks passed on `sha256:145699eaef8758891c153a097da6e7496d1c0fd78a3bd9f4d80714793cb53434`                                                                       |
| Linux AMD64 Docker     | The same checks passed under local emulation on `sha256:25d1021ab2c7b41d375ce5ff5ce889bd32fdf5bc3fd9c7ed92ec2d49b71eefa0`                                                                                                                                             |
| Existing installation  | All three managed ARM64 services healthy after update; every pre-update workspace row retained and foreign keys intact                                                                                                                                                |

The text adapter searches at most three attributes and attempts at most six
article downloads within a 15-second stage budget. Deferred attributes remain
visible. It reads available Europe PMC open-access XML, not arbitrary public
websites. No personal model login, paid inference or AWS deployment was used.
Native Windows/Linux execution remains untested.

## Written report milestone

New reports compile a concise written PI Summary from validated evidence, with a
three-row shortlist preview. Technical Overview retains the full shortlist,
selected-property coverage, missing criteria and provenance. Download format no
longer changes the readable report into JSON. Earlier saved report text remains
unchanged; internal view identifiers remain compatible.

| Check                        | Observed result                                                                                                                                                                                                                                                                                                          |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Python                       | 866 passed; 36 PowerShell checks skipped on this Mac; two upstream TestClient warnings. Ruff lint and formatting passed                                                                                                                                                                                                  |
| Frontend                     | 62 tests and production build passed, including safe table rendering, literal untrusted markup and legacy report compatibility                                                                                                                                                                                           |
| Native macOS                 | Actual Tauri app displayed written paragraphs, three PI rows and six expanded rows from a labeled historical public-source test fixture. JSON selection retained readable prose; Technical Overview labels and fixed header widths were checked. Horizontal table scrolling was not established by the native automation |
| Report documents             | PDF and Word tables render as tables with wrapped cells and repeated headers. All ten pages of each combined fixture export were visually reviewed; 41 export tests passed                                                                                                                                               |
| Linux ARM64 Docker           | Build, full workspace smoke, packaged PDF/Word/JSON table checks and real Goose with simulated provider passed on `sha256:cb5a88460a023ce3c1bbf28bfc47f989b3c51cdf633849bfd727aa1a7092d99e`                                                                                                                              |
| Linux AMD64 Docker           | The same checks passed under local emulation on `sha256:528e9a57523c3a9e2185f4761b85b68e330a9dfb222075c63d03936294754346`                                                                                                                                                                                                |
| Evidence boundary            | Empty or reference-only results retain missing-data reasons; no sample candidate fallback. Tests cover tied/zero scores, selected criteria, source citations, forged table structure and rejected model-generated prose                                                                                                  |
| Design                       | Updated three-page design note rendered and visually reviewed                                                                                                                                                                                                                                                            |
| Installation / distributions | All three managed ARM64 services healthy after update; every pre-update workspace row retained and foreign keys intact. Wheel/source archives passed private-file exclusion checks                                                                                                                                       |

Native layout checks used an isolated test workspace, separate from the user's
history. No personal provider login, paid inference, new scientific search,
AWS deployment or native Windows/Linux execution was performed for this change.

## Required model setup milestone

New research now requires a supported authenticated provider account, a selected
model, explicit hosted-context consent and a successful model metadata check.
First-run setup includes optional AWS Bedrock and public-source connections.
Saved workspace history remains accessible before setup and while credentials are
locked. Earlier no-account research checks below describe previous behavior.

| Check                    | Observed result                                                                                                                                                                                                                                                                                                        |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python                   | 850 tests passed; 36 PowerShell checks skipped because that runtime is absent on this Mac; two upstream TestClient warnings                                                                                                                                                                                            |
| Frontend                 | 57 tests passed, including automatic setup, keyboard/focus handling, optional skips, unsaved connection edits, restart locks, draft preservation, duplicate composer prevention and structured model failures                                                                                                          |
| Native shell             | Nine Rust tests and the Mac Tauri build passed. Actual macOS webview opened first-run setup, retained an unsent draft through close/reopen, rejected keyboard submission without a connection, showed saved history and supported public sources, and reported Goose available                                         |
| Authentication boundary  | Metadata verification checks the exact selected model. Missing, changed, locked and expired credentials fail closed; a persisted setup flag cannot authorize research. Model failures save no report and do not trigger local fallback                                                                                 |
| Headless mode            | Fixed same-container server client verified for session/CSRF, response limits, redacted failures, saved profile selection and no retries; launcher regression checks cover shared-backend use                                                                                                                          |
| Linux ARM64 Docker       | Full workspace smoke passed on `sha256:dc1d4d2a8c6481643463827e820bfd6a5c1b13053e355fade79c743db1118a51`                                                                                                                                                                                                               |
| Linux AMD64 Docker       | The same checks passed under emulation on `sha256:22f5bbab28d210d22ec90df5ded39e967d4c4231b8b88bda60e0ac90e6be1dfb`                                                                                                                                                                                                    |
| Docker research boundary | Unconfigured API, source-search and CLI requests rejected without mutations. Setup progress, encrypted synthetic credentials, hardening, replacement and restart checks passed. Persisted policy-refusal reports exercised report pins and all TXT/JSON/PDF/Word exports; these are not successful scientific searches |
| Goose transport          | The actual isolated Goose worker passed on both architectures using a simulated provider and an explicit historical public-data fixture; only approved tools, verified properties, selected profile and server-owned report survived. This is protocol/isolation coverage, not a live account test                     |
| Existing installation    | Updated the managed ARM64 stack; all three services healthy. Every pre-upgrade workspace row was retained and foreign keys remained intact                                                                                                                                                                             |
| Design / distributions   | Updated three-page design note rendered and visually checked. Wheel/source archives passed private-file exclusion checks, including setup-progress files                                                                                                                                                               |

No personal provider sign-in, paid model inference, AWS deployment or native
Windows/Linux execution was performed for this milestone. Provider transport
checks use explicit simulated credentials, separate from runtime defaults.

## Earlier live-retrieval milestone (before required model setup)

The normal workflow accepts materials questions across classes without loading a
fixed candidate list. Legacy snapshot preferences remain readable but cannot run
a historical shortlist. Existing saved reports and explicit source-off settings
are preserved. The desktop stayed closed for this phase.

| Check                   | Observed result                                                                                                                                                                                                                                                                                     |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python / frontend       | 803 Python tests passed; 35 PowerShell checks skipped on this Mac. 52 frontend tests, production build and Ruff passed                                                                                                                                                                              |
| Native shell            | Nine Rust checks and the Mac Tauri build passed. The final native UI was not reopened; native Windows/Linux remain untested                                                                                                                                                                         |
| Live no-key evidence    | Anonymous NOMAD queries for silicon, oxygen-containing compositions and Al–N returned current public entries. A non-oxide nitride report used retrieved records. Unit conversion, missing/conflicting values, composition validation and provenance were checked                                    |
| Dynamic defaults        | Unit tests enforce no automatic fixture fallback, no prompt-derived properties, class-neutral reference-only output, selected-source enforcement and profile inference without an unintended oxide scope                                                                                            |
| Linux ARM64             | Full Docker workspace smoke passed on `sha256:ca70ea03f61c26693198371d87706cf0db55f5a5522f4491004552d636eb06e0`                                                                                                                                                                                     |
| Linux AMD64             | Full Docker workspace smoke passed under local emulation on `sha256:4da340cd5a3f5c89576c1a5b4965741a7de1affa26e72707d8ac0f425e80a2fe`                                                                                                                                                               |
| Final Goose integration | Real Goose in the isolated ARM64 worker passed the guarded report handoff with an explicit test-only scientific fixture and simulated provider. Fabricated prompt values, an injected shell tool and generated model prose were excluded; only the parent report and selected profile were retained |
| Exports / persistence   | Both Docker architectures passed all TXT/JSON/PDF/Word view combinations, chats/projects/pins, profile selection, CSRF, encrypted synthetic credentials and replacement/restart checks                                                                                                              |
| Design / package        | Three-page design note rendered and visually checked. Wheel/source archives passed private-file exclusion checks; no actual account secrets were used                                                                                                                                               |

These checks establish software behavior and selected public-source integration,
not comprehensive scientific coverage or successful personal account sign-in.
The earlier milestones below are historical, including their former snapshot
workflow and older image identifiers.

Final installation image IDs (after capability/help wording):
`f690b1cea4ec2206a7c55065df90d5b07b256660e06d559cb0343527d4e5d978`
(ARM64) and `545dad472d3c408648aca080a41678d55b967c81650124e5341f26d0fb0efb14`
(AMD64). Both passed additional generic status/help and live non-oxide CLI checks
without accounts or host mounts. The full workspace checks above preceded only
these wording changes; the scientific, credential and isolation code is identical.

The final capability/help wording also passed 55 focused interface and workspace
checks after the complete suite. The native bundle was rebuilt with the online
CLI default and explicit `cli --offline` option.

## Earlier Goose isolation milestone (before broader live retrieval)

The desktop was closed at the user's request while Goose was validated independently.
No personal provider credential, browser login, host Codex account or AWS cache was
imported. Real account authentication and model inference remain untested.

| Check                    | Observed result                                                                                                                                                                                                                                                                                                         |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python                   | 728 passed; 30 PowerShell tests skipped; two upstream TestClient warnings                                                                                                                                                                                                                                               |
| Frontend                 | 51 tests, TypeScript checking and production build passed                                                                                                                                                                                                                                                               |
| Native Mac shell         | Nine Rust tests and Tauri build passed; account setup UI was exercised before the user closed it. The final Downloads restriction still needs a fresh native export check                                                                                                                                               |
| Standalone Goose         | Actual 1.50.0 executable passed in offline, read-only ARM64 and emulated AMD64 containers, with no host mounts or Labcat server. Simulated provider/model setup and the guarded tool loop passed                                                                                                                        |
| Provider configuration   | Actual Goose TTY prompts accepted a synthetic provider credential and selected a model, then made exactly one simulated connection check. Temporary configuration was cleaned; no actual account was used                                                                                                               |
| Agent/report integration | A separate ARM64 test stack exercised real Goose through the authenticated worker and parent callbacks. The explicit ranking profile and genuine MP snapshot properties survived; a fabricated user property, injected shell call and untrusted model report were excluded                                              |
| Network isolation        | Docker tests first found a host-gateway bypass. The replacement internal worker network blocks direct internet, host gateways and private workspace API access. The restricted proxy rejects private and arbitrary destinations. An unauthenticated approved OpenAI request returned the expected 401 without inference |
| Linux ARM64 final image  | Full workspace smoke passed on `sha256:6df8ab91595a18f479913033fe7fe460fb595a9b48ba4e9bbe16f5e174dbf5b0`: CLI, reports/exports, project/chat/profile persistence, credentials, CSRF, hardening and the three-service network boundary                                                                                   |
| Linux AMD64 final image  | Full workspace smoke passed on `sha256:5d24942fa436ad40a8d0f5e2cfd143d860762c741cf9d01b35c4d20663760ce1`, including isolation, exports, credential persistence and restart under emulation; standalone executable/setup checks also passed                                                                              |
| Credential handling      | Tests cover device-flow binding/recovery, encrypted restart, session reset, serialized refresh, cancellation, failed-run refresh recovery and secret redaction. Unsigned account usage explains the missing connection without making a provider request                                                                |
| Packaging/design         | Wheel and source-distribution privacy checks passed. The updated three-page design note was rendered and visually checked                                                                                                                                                                                               |

The agent/report integration used image
`sha256:6e2c2ce05ef79b4ec3e9ecf2be09db6215984e10c178aedf7c53e3660319a133`;
the final image adds the explanatory unsigned-account usage response without
changing its Goose runtime, proxy or research tools. Test token totals are supplied
by protocol fixtures, never represented as a real account balance. The Docker
worker is not given host Downloads access: native exports are a separate user
action. No native Windows/Linux or remote CI run is implied.

Goose worker/proxy health checks allow ten seconds during emulated or slow-host
startup; the original three-second proxy check proved too tight under AMD64
emulation. No sandbox permission or network restriction was relaxed.

Reproduce the independent checks using [the standalone Goose guide](goose-standalone.md).
The earlier validation below describes the previous milestone and its artifacts;
it is retained as history, not proof of live account access in the current build.

## Previous milestone verification

| Check                                                | Result                                                                                                                                                                                                                                                                                                                                                               |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python on macOS 26.6.2, Apple Silicon, Python 3.13.2 | 504 tests passed; 30 PowerShell tests skipped because PowerShell is unavailable; Ruff lint and formatting passed                                                                                                                                                                                                                                                     |
| React/TypeScript                                     | 47 client tests, type checking and the production build passed, including repeated project/New Chat/Connections navigation, account/model selection, source preferences, new/custom ranking-profile saving, chat drag-and-drop and composer controls                                                                                                                 |
| Native shell                                         | macOS Tauri application built; seven Rust tests passed, including public-link and same-origin report-download guards                                                                                                                                                                                                                                                 |
| Public-evidence evaluation                           | Normal oxide query, policy-override query and prompt-supplied false properties passed the checked-in evaluation; evidence remains tied to the public snapshot                                                                                                                                                                                                        |
| Scientific boundaries                                | Tests cover record validation, missing values, conflicting fields, provenance, normalized ranking contributions, model output rejection, blocked requests and bounded network adapters                                                                                                                                                                               |
| Linux ARM64 Docker                                   | Final image built and run on Docker Desktop 28.0.1 on this Mac; offline CLI cited ranking, health/API/assets, all 15 new classes/templates, occupied-port startup, hardening and repeat-start checks passed                                                                                                                                                          |
| Linux AMD64 Docker                                   | Final image passed the same checks under local emulation; this is not a native Windows or Linux desktop test                                                                                                                                                                                                                                                         |
| Ranking profile editor                               | New preset-based and custom ranking profiles can be saved, selected, edited and explicitly activated. DOM tests cover preserving draft names when switching presets, custom attributes and reopening settings; real API tests cover restart persistence. An isolated browser save added the new profile to the selector without changing the active one              |
| Composer controls                                    | Browser checks verified explicit and inferred profiles, saved selection rationale, draft-preserving settings overlays and one composer. Both popups fit a 390px viewport without horizontal overflow. DOM tests cover saved account/model switching without key or consent changes, uncertain-save recovery and stale model catalogs after credential/status changes |
| Per-message ranking                                  | Explicit, inferred and omitted/null selections passed both container architectures. Invalid IDs save no message. Full profile and selection snapshots survive restart/replacement without changing the workspace default; bounded hints cannot supply numeric evidence or weights                                                                                    |
| Workspace persistence                                | Chats, source/report pins, ranking profiles and report settings survived stop/start and container replacement on both architectures; chat moves and project isolation passed                                                                                                                                                                                         |
| Sidebar chat moves                                   | A real browser drag moved a General Chat into a collapsed project, expanded it, updated its count and retained the open draft. DOM regression checks cover duplicate/canceled/external drops, interrupted-save recovery, failed refreshes, independent chat refreshes and in-flight requests across navigation                                                       |
| Expanded sidebar layout                              | Two expanded projects containing 18 chats plus four General Chats stayed in vertical order at 390, 800, 850, 851 and 1280px widths. Desktop history scrolls within the sidebar; narrow layouts stack above the main content. The 761–850px conflict between shared and workspace layout rules was reproduced and fixed                                               |
| Saved report downloads                               | All 12 combinations of TXT/JSON/PDF/Word with PI/audit/both passed on both container architectures, before and after replacement; attachment headers, selected content, saved identity and cross-chat access checked                                                                                                                                                 |
| Credential persistence                               | Named accounts, selected models, encrypted-vault restart, blank-key isolation, failed-save rollback, locking/unlocking and CSRF checks passed. No real provider key or user credential was used                                                                                                                                                                      |
| Existing workspace upgrade                           | A private SQLite backup of the actual Docker v3 workspace migrated to v4 in an isolated container, with startup repeated. The managed app was then upgraded and compared with the backup: every prior row remained; empty projects received exactly one starter; foreign-key integrity passed                                                                        |
| Document layout                                      | The updated three-page design note was rendered and visually reviewed. The report renderer was visually checked in the prior milestone across 25 preview pages: PI PDF 2, combined PDF 10, PI Word 2, combined Word 11; 33 export tests passed, including approved discovery links and untrusted-link exclusion                                                      |

The Python suite emits two upstream TestClient deprecation warnings. Native
Windows/Linux installation and remote CI have **not** been run. The configured
CI matrix covers Python 3.11/3.13 on Mac, Windows and Linux; configuration alone
is not evidence of a passing run. The installed Mac Tauri window was exercised
with the final frontend: project prompt, custom profile selection, model setup
and draft preservation, report generation, pin counts and Technical Audit all
worked. Its PDF download produced a valid 12-page document with both report
views, the selected profile and public references. No real account was used.
The installed app also launched with no arguments, reused the upgraded Docker
service, and displayed the existing workspace and expanded project chats. The
Mac desktop window was open during that milestone; it has since been closed by
the user. No native Windows/Linux run is implied.

The updated browser was checked through Project → New Chat → repeated New Chat
→ Connections → Chat. Exactly one prompt remained in chat/project views and
Connections contained no research prompt. The removed helper sentence was absent.
The browser check also identified sidebar overlap after expanding a project; the
layout was corrected before the final image was frozen. This does not establish
coverage of every responsive size or native download interaction.

The final drag-and-drop frontend was checked in an isolated browser workspace.
The existing Project selector also successfully moved the test chat back to
General Chats before a second drag. No real workspace chats were moved for QA.
The current managed Docker workspace was backed up and compared after the update;
every prior row and foreign-key integrity were preserved.

## Scientific and provider limitations

The current default queries selected live public repositories. Optional database
connections add quantitative coverage. The keyless NOMAD
adapter reads a bounded page of public bulk entries with reported gaps, validates
composition and public access, converts joules to eV, and leaves conflicting gaps
unknown. Results are composition matches, not verified application/class labels.
Database sampling and method comparability limit interpretation. The historical
MP dataset and NOMAD response are test fixtures, never normal-run fallbacks.
Other material classes can receive reference-only reports from HybriD³, NOMAD,
Europe PMC and arXiv. General discovery returns identity/bibliographic metadata.
Targeted missing-attribute follow-up can read available open-access article XML;
its attributed passages require review and never become scored property values.
Missing coverage stays explicit.
Live ChatGPT-hosted inference is verified only for the models and runs recorded
above. No live Materials Project account, other model-provider account, Ollama
service or AWS account was tested. Other provider calls and failure cases have
mocked tests; metadata-only connection tests are distinct from requested inference.
No cloud resources were created and no external release was published.

## Previous milestone artifact checks

Both frozen runtime images passed the full extended container smoke tests:

- ARM64: `sha256:9ded16ff3393d9efb99369ddefa3f8c4a4c1cf6374d1e47cebfae40baa7fa7ae`.
- AMD64: `sha256:92908e94635c9f84c8e3fa934df54766027ed8187fd2afc5ee4505f47055c3bb`.

The Python wheel and source distribution built successfully. Distribution checks
exclude private notes, credentials and runtime databases. The wheel contains the
final compiled React assets, public snapshot and portable report fonts. A fresh
wheel installation outside the repository, without optional web/export packages,
passed offline cited research and TXT/JSON exports. Build isolation was disabled
for this local build; Docker independently built its wheel with pinned build
requirements. Both Docker archives were exported, checksummed and successfully
reloaded to their expected architecture/image IDs. The canonical local tag was
restored to ARM64 afterward. Portable ARM64/AMD64 and native Mac ARM64 install
ZIPs include the verified archives, host launchers and current documentation;
bundle generation checks allowlisted inputs, executable permissions and hashes.
The staged native app matches the final built bundle. The former app bundle and
private workspace backups remain outside distributions for recovery.

Artifacts are generated in ignored `dist/`: ARM64/AMD64 Linux Docker archives,
matching portable install ZIPs, a Mac ARM64 ZIP with the unsigned native app,
SHA-256 checksums, and Python wheel/source distributions. Both Docker archives
use the same version tag; choose the correct CPU architecture. Loading one
changes that local tag, not the image used by an already-running container.

See [deployment](deployment.md) for loading/startup and remaining target-host
checks, and [evaluation](evaluation.md) for reproducible normal/adversarial cases.

### Structure discovery and report organization — 2026-09-23

Offline validation passed 913 Python tests covering public structure lookup,
identity receipts, Materials Project readiness, source-failure isolation,
report/export preservation, experimental precedence, and web boundaries. The
interface run passed 69 tests, including inline structures, retry after an
unresolved name, and separate candidate discussion paragraphs. The frontend
build/typecheck, Ruff, and whitespace checks passed.

An isolated replay of an existing oxide report linked its literature candidate
with an explicit HfO2 formula to the already retained HfO2 database record,
without network access, changing report evidence, or reranking. Browser checks
at 1440, 768 and 390 pixels confirmed six candidate sections, two leading-candidate
comparison paragraphs, one primary shortlist, and collapsed supporting-property
records without document overflow. These are saved-data/layout checks, not new
scientific retrieval results.

The saved model and Materials Project connections passed non-inference checks.
Fresh three-prompt retrieval/CIF checks and installation are prepared but have
not run; their storage-limit approval is pending. No new live prompt success,
newly downloaded structure, or installed fix is claimed by this entry.

### Component structure references — 2026-09-23

The focused structure, identity, discovery and viewer suites passed 411 Python
tests, including 35 component cases. All 326 frontend tests, Ruff and the
production build/typecheck passed. The first build overlapped viewer fixture
cleanup and hit a nonempty output-directory error; a sequential build passed.
Coverage includes separate Materials Project queries and CIF downloads, NOMAD
fallback, multi-shell notation, source outages, selected-source restrictions,
shared deadlines, exact cited records alongside components, cache tampering,
and unchanged saved report/ranking data. These synthetic fixtures are tests,
not scientific evidence.

A live check against retained public-source candidates resolved CuInS2 and ZnS
separately through Materials Project and validated coordinate/CIF retrieval for
mp-22736 and mp-9946. InAs/ZnSe also resolved and downloaded separate structures
(mp-20305 and mp-380). For ZnSeTe/ZnSe/ZnS, ZnSe and ZnS resolved while the bounded
Materials Project search found no exact ZnSeTe match; the available siblings
remained usable. This does not establish that a ZnSeTe structure does not exist.
These checks used existing reports without fresh model inference and preserved
their saved outcomes. Retrieved bulk references do not establish nanoparticle
geometry, phase matching, or device suitability. No Windows or AMD64 runtime
coverage is claimed.

### Create projects from Move chat — 2026-09-23

All 329 frontend tests and 49 focused Python workspace, API and starter-chat
tests passed, along with Ruff and the production build/typecheck. Tests cover
new and existing destinations, trimmed required names, optional descriptions,
preserved conversation/report/draft state, duplicate-submission prevention,
and recovery when project creation succeeds but moving the chat fails. The
saved project list and chat location are refreshed before retry is permitted.
These checks use isolated fixtures; no existing user chat was moved. The built
interface update has not yet been installed in the desktop runtime.

### Sidebar title and activity fit — 2026-09-23

All 329 frontend tests, 49 focused Python workspace tests, Ruff and the
production build/typecheck passed. Nine isolated Chrome layout cases covered
the 238-pixel default, 220-pixel minimum, wider user-resized sidebars, a short
window, responsive breakpoints, and 390/320-pixel mobile layouts. Synthetic
long titles, large chat numbers and running general/project chats stayed within
the sidebar: titles, numbers, flasks and action buttons did not overlap or
produce horizontal overflow. Full hover labels, pointer hit targets, scrolling
to the final action and keyboard menu navigation passed. Focus outlines remain
inside the action buttons. No live workspace requests or data mutations were
used. This verifies the built web interface in Chrome; the desktop runtime
has not yet received this update.

### Quantum-dot names and digit-free structure lookup — 2026-09-23

The focused structure suites passed 435 Python tests; chemical-name and
literature-label suites passed 133. All 331 frontend tests, Ruff, typecheck and
the production build passed. One build attempt encountered an output-directory
cleanup conflict during concurrent test activity; the subsequent sequential
build passed. Tests cover digit-free formulas, ambiguous abbreviations, exact
composition checks, independent component references and names, source selection,
partial retrieval, deadlines, hostile text, and unchanged saved research data.

The structure formula gate had rejected labels such as CdS because they lacked
an explicit atom count. Supported, correctly cased formulas now reach the public
reference adapters. A live check retrieved and validated Materials Project CIFs
for CdS (mp-370), InAs (mp-20305), ZnSe (mp-380), InP (mp-20351), and ZnS
(mp-9946). Independent components remained available when another component
could not be resolved. ZnSeTe remained unresolved in the bounded check; this is
not evidence that no corresponding structure exists. Bulk reference structures
do not establish an assembled quantum dot, interface, morphology or phase match.

The name resolver previously discarded ambiguous broad formula searches, and
component labels had no independent name lookup. Exact public synonym records
and explicit literature name/formula pairs now provide separately cited labels.
Fresh report lookups produced cadmium sulfide, indium arsenide, zinc selenide,
and indium phosphide labels. Zinc sulfide resolved in an earlier check but not
the final combined request; public-source availability can still leave names
missing. No ambiguous hit was selected merely to fill a label. All saved report
outcomes remained unchanged. These checks exercised revised modules in a
separate process; the built changes are not yet installed in the desktop runtime.

### Crystal animation alignment — 2026-09-23

Crystal-only frame transforms register all eight poses to a common table anchor
without editing the sprite image. Per-cell clipping prevents neighboring artwork
from appearing during the corrected second-row positions. Real Chrome checks
passed all 32 pose/size combinations at 208, 104, 72 and 56 CSS pixels, plus the
loop boundary, hidden-state pause and both reduced-motion controls. A visual
contact sheet confirmed the table alignment while retaining intended pose motion.
The reduced-motion stylesheet now takes precedence over scene-specific animation.

All 331 frontend tests, 39 focused Python asset/security tests, Ruff and the
production build passed; 17 mascot/progress tests were rerun after the final
motion-policy adjustment. Build cleanup initially failed with Finder metadata
remaining in generated output directories. Removing only that metadata and the
empty generated directories allowed the rebuild; all 1,655 copied viewer assets
match their source files. This update is built but not installed in the desktop
runtime. No image assets, saved reports or research behavior changed.

### Skip-link visibility — 2026-09-23

The keyboard shortcut is now clipped while unfocused instead of translated
above the viewport. Chrome checks at 1440 and 390 pixels verified hidden paint
and hit areas, pointer scrolling, keyboard reveal, Enter moving focus to the
main landmark, and the next Tab advancing within the content. These are isolated
browser checks, not a reproduction of native macOS elastic scrolling. The
11 focused workspace/sidebar tests, 35 web-security tests, Ruff and production
build passed. The desktop runtime has not yet received this CSS update.
