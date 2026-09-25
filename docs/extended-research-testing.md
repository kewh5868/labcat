# Bounded research testing and revision procedure

This procedure tests the real application, preserves failures, and separates
software checks from scientific review. It does not promise that every material
question has a supported answer or that a system is immune to all attacks.
Refusals and useful clarification questions are successful outcomes for the
corresponding controls. Empty or irrelevant ordinary research results remain
failures to investigate; never manufacture a shortlist to make a test pass.

## Before leaving the application unattended

1. Save a private ignored repository snapshot and verify its manifest. Preserve
   the installed image, saved workspace, and a tested rollback. Check actual
   host free space, not merely Docker's reclaimable-image estimate.
2. Finish packaging and offline checks before the user signs in. Start the
   intended desktop instance and verify its current local address and image
   revision. Session-only credentials end when the backend stops. For continued
   backend revisions, configure [encrypted unattended storage](unattended-auth.md)
   and verify the real connection after a controlled replacement before departure.
   Preserve the same data and key volumes on every update. The runner cannot
   guarantee five-day authentication, prevent an account revocation, wake a
   powered-off machine, or bypass renewed login.
3. Freeze this protocol, the acceptance rubric, source settings, development
   prompts, evaluator/validator implementation, bundled scientific JSON/configuration
   and deployed revision. Run the
   same prompt subset on each chosen model before responding to its findings
   with another implementation change.
4. Ask the user to complete normal provider sign-in in Labcat and verify the
   connection. The runner never reads authentication files or imports/exports
   provider tokens. Ordinary local browser-session CSRF values are acquired
   transiently for API requests and never retained.
5. Confirm the scheduler has an end time, account-usage monitoring, and a pause
   condition for lost login, exhausted allowance, low disk or uncertain requests.
   Recurring supervision and this batch runner are separate components. Starting
   a batch does not install a background service or promise continued execution.

## Frozen cases and acceptance

Use `scripts/materials_prompt_matrix.json`: 72 development cases covering 20
material families, three variants per family, and 12 edge cases. Ordinary-language
paraphrases matter as much as explicit class names. The fixture is test input,
never production retrieval data. Its expected classes, criteria and candidate
counts are sent only to the evaluator, never to the model.

Apply the unchanged [materials evaluation rubric](materials-evaluation-rubric.md)
and `evaluate_live_prompts.py` acceptance-v3. Report separately:

- Correct scope, roles, selected criteria, directions and requested targets.
- Source-backed table presence, distinct useful alternatives, application
  assessments, selected-attribute coverage, and unknown-prior-only rows.
- Public evidence linkage, source accessibility/credibility and exact quotation
  context. Freely viewable metadata is not proof of accessible full text.
- Thermodynamic, ambient-phase and operational stability, including adverse
  findings under the relevant conditions. Missing stability is unknown.
- Applicable experimental versus computed discrepancies and experimental
  precedence; incompatible phases/conditions remain separate comparisons.
- Summary and technical-view usability, citations, structure eligibility and
  actual parseable downloads. No crystal structure is expected for every mixture,
  polymer or literature-only record.
- Timeouts, partial completions, source outages, invalid model responses, usage
  availability and pending independent scientific review.

A table of equal unknown priors does not establish a useful ranking. A correctly
calculated score does not establish scientifically appropriate evidence. Class
inference and application fit need independent review of actual source context.

Keep the independently prepared 48-case unseen holdout unopened until the
protocol and implementation are frozen. Check its recorded SHA256 before
initializing a holdout campaign. Once its outputs inform a fix, it is a regression
set; use a newly authored, separately frozen set for another unseen-performance
claim. Preserve earlier results rather than replacing them with successful reruns.

## Campaign runner

`scripts/research_campaign.py` makes no network requests during initialization.
Use one shared parent directory for all campaigns so their incremental artifact
budget is shared. The directory should remain under ignored `.local/`.

```sh
.venv/bin/python scripts/research_campaign.py init \
  --campaign .local/research-campaigns/revision-01 \
  --prompt-set scripts/materials_prompt_matrix.json \
  --prompt-sha256 8e50b3d221f2f5a5a8bea3b653a00428d927a2a8fb1b7ffcaedee45197991dd3 \
  --model gpt-5.6-sol --model gpt-5.6-luna \
  --runtime-revision 'VERIFIED-IMAGE-DIGEST-AND-COMMIT' \
  --project-prefix 'Research validation · revision 01' \
  --ends-at '2026-09-21T18:00:00Z'
```

Replace the revision with the installed image and commit actually verified by
the supervising operator. Verifying this is a required operator preflight. The runner records the
revision as an assertion and explicitly marks it unverified by the runner; it
cannot establish that a container matches the host checkout or verify external
deployment environment variables. Keep those and effective application settings
fixed during a paired comparison. Choose models actually available to
the connected account. A model string in a project title is not evidence that
that model ran; returned research metadata is checked separately.

For an initial development subset, repeat `--case` with exact identifiers from
the matrix. Include perovskites, implicit metals, organic electronic materials,
semiconductor nanocrystals, and controls; then cover all remaining families and
variants. Do not start by opening the unseen fixture. Later holdout initialization
also requires `--holdout --protocol-frozen` and its previously recorded hash.

Select the intended model through the application's existing settings. The
runner intentionally does not change accounts, consent or credentials. Then:

```sh
.venv/bin/python scripts/research_campaign.py run \
  --campaign .local/research-campaigns/revision-01 \
  --server http://127.0.0.1:PORT \
  --model gpt-5.6-sol --batch-size 2
```

Run the identical campaign with its other model selected to obtain a paired
comparison. Models run sequentially. Use the same command to resume the next
unattempted cases. No attempted case is automatically resubmitted. Successful
responses remain visible as chats and reports in a clearly named project for
each model. Failed attempts and their actual chat identifiers remain in the
private campaign journal.

Default limits are two prompts per invocation, an absolute maximum of four,
20 minutes per batch, and 240 seconds per inference HTTP request. A separate
process enforces the request wall-time bound; killing the HTTP client is **not**
proof the server stopped. A shared pending-submission journal blocks later
campaigns until server completion can be established. A process-held lock also
prevents simultaneous batch runners. Other tools must not independently submit
research while a batch is active.

Every inference has a flushed, immutable intent record before submission. On a
transport interruption, keep its original failure, inspect server progress and
saved chat state, and write a separate reconciliation. A still-running request,
unresolved idle state or changed server address pauses the campaign. Never
solve uncertainty by issuing the prompt again. A requested manual retry belongs
in a new campaign/attempt after resolving the prior submission.

The runner stops when the selected model changes, authentication/readiness is
unavailable, a reported allowance window is exhausted, a response reports model
interruption, the frozen implementation or source settings change, the end time
is reached, or resources reach their limits. For a retained report with interrupted model execution, inspect the immutable
failure and check account readiness before resuming. The supervising operator
can acknowledge that exact run with `--reviewed-interruption RUN_UUID`; this
records the review and continues with the next unattempted case. It does not
retry the failed prompt or erase the failure. Never set that flag blindly.

Unknown remaining quota remains unknown; it is not interpreted as an
unlimited balance. The supervisor separately checks actual account-wide usage,
respects rate limits, and never buys credits or cycles accounts. Useful testing
may consume the available allowance; repeating identical tests just to exhaust
it provides no additional validation.

## Disk and artifact limits

The runner requires at least **20 GiB of free host space** before starting and
between cases. All campaigns under the same parent share a **2 GiB incremental
artifact budget**, with space reserved for a bounded next response. Responses
are capped at 8 MiB; structure downloads at 2 MiB. Reports already persist in
the application; the private journal keeps one bounded capture per attempt and
small immutable summaries. It never deletes old evidence to conceal failure.

Inspect host free space and Docker allocation before builds. Avoid repeated
Docker image builds, exported image archives or per-prompt containers. Reuse the
existing tested runtime for a frozen comparison; use targeted host tests during
refinement. Stop expensive builds before the reserve is threatened. No image or
volume pruning, VM reset, disk shrinking, session restart or credential copying
is part of this runner.

The JSON manifest fixes these limits. To change a limit, create a new explicitly
reviewed manifest/campaign and retain the old one; do not mutate a frozen running
campaign. The supervisor must also account for storage written outside the
campaign root, including application databases, Docker logs and build caches.

## Structure download audit

After a batch, perform a separate bounded download audit:

```sh
.venv/bin/python scripts/research_campaign.py structures \
  --campaign .local/research-campaigns/revision-01 \
  --server http://127.0.0.1:PORT
```

Each invocation attempts at most two eligible, exact report-owned records. It
uses the application's approved retrieval endpoint, downloads actual CIF bytes,
checks the saved identity, response/header/content hash and atom count, and
parses the file with Gemmi. Download bytes are checked in memory rather than
creating duplicate structure archives. The journal records the adapter,
original/derived representation, byte count and outcome. The command requires
the web dependency containing Gemmi.

It never guesses a structure from a material name, invents coordinates, or
silently associates a different phase. Unknown/unsupported/key-required records
are reported separately. A transport failure remains a failure, not a successful
coverage check. Repeated invocations continue with remaining unattempted records.
Keep a source-by-source coverage table for Materials Project, NOMAD, HybriD³ and
the supported internal dataset; if a campaign contains no eligible record for an
adapter, that adapter remains **not exercised**. Use a separately identified,
source-verified diagnostic record to cover it, not a hard-coded application
answer. Literature-only providers need not expose structures. JSmol rendering
still requires a separate real desktop/browser check; parsing a download does
not establish viewer or phase correctness.

## Revision loop and release gates

1. Run the representative paired development batch; preserve all outputs.
2. Review the largest generic failure: wrong class/role, poor source query,
   missed candidates, rejected quotations, absent property evidence or incomplete
   assessments. Inspect existing diagnostic counts before increasing budgets.
3. Make a narrowly scoped backend correction. Never special-case a prompt,
   material identity, expected answer, score or citation. Keep current public-only
   adapters, tool restrictions, user profile authority and historical reports.
4. Run relevant offline tests, including source failure isolation, malformed
   neighbors, stability scope, evidence comparison and experimental precedence.
   Add regression examples that test the general boundary, not a memorized answer.
5. Reweight **the same retained approved evidence** across contrasting valid
   profiles. Record changed scores, strict pairwise reversals, tie changes and
   missing criteria independently. No new model call is needed for replay. No
   reversal on evidence lacking competing assessed criteria is a coverage gap,
   not permission to synthesize properties. Use the existing ranking and
   literature evaluation functions; do not recalculate with an alternate formula.
6. Run safety/adversarial controls separately: instruction injection in retrieved
   text, fake authority, private/paywalled access requests, attempts to expose
   credentials or grant tools, and harmful synthesis/weaponization requests.
   Assert refusal and absence of unauthorized tool/network/data side effects.
   Benign materials questions about stability or safety must remain useful.
7. Run Python/Ruff and the frontend production build required by repository
   guidance. Build/install a new container only when needed and when session
   preservation permits it. Record actual host/architecture coverage.
8. Start a new revision campaign; do not mutate the old results. Finish the paired
   development comparison before exposing an unseen holdout. List passes,
   degraded outcomes and remaining scientific reviews without claiming universal
   safety or discovery.

A minimum offline gate can select these existing tests alongside tests for the
changed code:

```sh
.venv/bin/python -m pytest \
  tests/test_research_campaign.py tests/test_live_prompt_evaluator.py \
  tests/test_source_failure_isolation.py tests/test_stability_policy.py \
  tests/test_experimental_evidence_precedence.py \
  tests/test_evidence_comparison_reporting.py tests/test_structures.py \
  tests/test_literature_structures.py tests/test_web_security.py
```

Provider outage tests use controlled local test doubles and fail-closed fixtures;
they do not require deliberately disrupting the user's active account. Live
scientific review must still inspect relevant conditions, source claims and
experimental applicability. Passing an offline fixture is never reported as a
new live model, source-download or scientific-accuracy result.
