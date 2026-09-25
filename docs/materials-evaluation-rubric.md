# Materials research evaluation rubric

Evaluate the application on ordinary research requests across every catalog
family. A source hit, a cited material name, a valid score calculation, and a
useful ranked answer are different outcomes. Report them separately. Tests must
never supply production candidates, measurements, citations, or answer text.

Freeze prompt text, expectations, model IDs, application revision and source
settings before a paired model comparison. After changing the implementation,
use new unseen requests for generalization checks. Keep earlier results as the
baseline; a manual retry is a separate attempt, including the original failure.

## Case expectations

Each material family needs an explicit request, an ordinary-language paraphrase,
and a request with a tradeoff or operating condition. Include mixed classes,
examples that are not exhaustive, explicit restricted comparisons, follow-up
requests, vague requests, contradictions, and refusal controls. `custom` is an
unresolved preference label, not a material family or permission for an arbitrary
repository population.

| Case field                                       | Meaning                                                                                                                                                        |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `class` or `accepted_classes`                    | Legitimate class interpretations, including overlapping or mixed families. Check scope separately; a matching label is insufficient.                           |
| `expected_goals`                                 | Request-grounded criterion IDs and directions. Targets must come from literal requested values. Unsupported scoring goals remain selected review requirements. |
| `expected_role_spans` / `forbidden_target_spans` | Material, application, environment and processing roles. For example, the corrosive environment must not become the target composition.                        |
| `control` and `expected_intake_statuses`         | Expected clarification or refusal. A useful guiding question can be the correct result; such cases must not require a fabricated shortlist.                    |
| `candidates_expected`                            | Whether this request should produce an assessed shortlist under responding sources. This does not authorize padding a weak result.                             |
| Optional minimum count and decision criteria     | Per-case breadth and property coverage expectations; keep these distinct from basic protocol checks.                                                           |

Accept more than one class when the wording permits it. A polymer donor can
legitimately fit both polymer and organic-electronic categories; a mixed-material
comparison may need an unresolved class with preserved target roles. Do not fail
a scientifically appropriate response solely for choosing a different valid
catalog label. Conversely, a correct label does not excuse wrong candidate roles
or an unrelated material population.

Clarification cases should ask a small number of relevant questions and preserve
the known constraints. A contradiction may also be resolved explicitly as two
alternative screens when the request permits that interpretation. An impossible
constraint should produce an explanation or clearly labeled near matches, never
claims that a material satisfies incompatible requirements. Harmful requests and
attempts to bypass the source policy require the appropriate refusal. An honest
empty result caused by a source outage is a degraded run to investigate, not a
reason to invent evidence or silently change the question.

## Acceptance dimensions

Record these dimensions independently. Only call a run scientifically useful
after the scope and evidence review; passing the automated contract is not enough.

| Dimension                          | Required check                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Intake and profile                 | Correct requested material roles; expected criteria are selected with the intended direction or target. Explicit and continued-chat profiles retain their authority. Unknown application or class does not inherit unrelated high-k preferences.                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Candidate scope                    | Each shortlisted row is a specific source-backed material or system relevant to the requested class and application role. Separate material, phase, mixture, device, substrate, shell and matrix identities. Element presence alone does not establish a chemical family.                                                                                                                                                                                                                                                                                                                                                                                                        |
| Quantitative table                 | Actual approved source values, units, methods and conditions survive into the table. Scores and ordering reconcile with the saved profile. Missing measurements stay unknown. At least one request-relevant decision criterion must have usable evidence; an evidence-count score alone is insufficient.                                                                                                                                                                                                                                                                                                                                                                         |
| Provisional literature table       | Revalidate existing lead IDs, criteria, exact source quotes, source identity and the canonical assessment bundle. Interpretations and priorities remain visibly provisional. For `literature-fit-v2`, a source-bound application-fit assessment of supports or mixed can qualify for preliminary screening without measured attributes; an assessed, positively weighted decision criterion can also qualify. Demonstrated use is supplementary and does not establish fit to the requested application on its own. Unknown-prior-only rows establish table presence, not usefulness. Legacy `literature-fit-v1` retains the positively weighted decision-criterion requirement. |
| Breadth and usefulness             | For a broad screening request, target several distinct relevant candidates; three is a reasonable minimum test expectation when justified by the case. Explicit comparisons may require fewer. V2 counts supported or mixed alternatives toward useful breadth, excluding candidates with application or stability concerns; those remain visible in diagnostic counts. Normalize duplicate names before counting and do not add separately rendered numeric and literature counts. Below-target counts are reported as partial coverage, never filled with duplicates or unrelated candidates.                                                                                  |
| Ranking rationale                  | The leading candidates have understandable advantages, tradeoffs and gaps tied to the request. A table of only concerns is an exclusion or partial-search result, not a successful list of suitable recommendations. Ties are acceptable when the evidence does not separate candidates.                                                                                                                                                                                                                                                                                                                                                                                         |
| Stability                          | Always show thermodynamic, ambient-phase and operational stability as distinct evidence scopes. Missing or irrelevant conditions remain unknown. Reported degradation or phase instability must count as a concern under matching conditions. Zero computed hull energy does not prove room-temperature or device stability.                                                                                                                                                                                                                                                                                                                                                     |
| Sources                            | Citations resolve through retained approved public records. Quotes actually discuss the candidate and criterion, including negation and comparison context. Public metadata, preprints and open full text keep their appropriate scope and limitations. A public URL alone does not prove full-text access, credibility, or support for a claim.                                                                                                                                                                                                                                                                                                                                 |
| Experimental and computed evidence | When applicable records exist for the same material, property kind, phase and conditions, prefer the experiment and retain both citations and the discrepancy. Otherwise mark comparison limits. Never pool unrelated phases or convert an unspecified method into an experiment.                                                                                                                                                                                                                                                                                                                                                                                                |
| User-facing reports                | Both Summary and Technical Overview contain readable tables, clean linked references, appropriate chemical subscripts, clear uncertainty and consistent saved formatting. Distinguish measured rankings, provisional assessments and unassessed leads.                                                                                                                                                                                                                                                                                                                                                                                                                           |
| Reliability                        | Preserve responding sources and completed assessments when one source or the model becomes unavailable. Show fixed progress and partial-completion notices. Do not retry paid model calls automatically or invent usage for interrupted runs.                                                                                                                                                                                                                                                                                                                                                                                                                                    |

Class and application fit often need an independent human review. Record that
review as pending, passed or failed rather than treating it as passed because no
automatic checker exists. Useful automatic metrics include distinct relevant
row count, positive-weight decision-criterion coverage, source-bound general
application rows, unknown-prior-only rows, stability concern counts, provisional
versus measured row counts, and source binding failures. Record the literature
evaluation version so a v2 preliminary screen is distinguishable from a legacy
v1 fit table. A successful preliminary table check does not establish measured
performance, correct class inference, or scientific suitability; those require
their respective evidence and independent review.
Navigation-title quality and visual polish should have their own checks; neither
should conceal a scientific failure or invalidate an otherwise correct refusal.

Some application-defining properties, such as adsorption capacity, emission
performance, fracture toughness and biological compatibility, are not present
in the current criterion catalog. A stability-only assessment can establish
partial coverage for those requests; it cannot establish that a candidate fits
the application. Keep the unmet requirement in the report and in the independent
scientific review even when the automated table check passes.

## Structure availability

Test structure retrieval separately from material suitability. For each registered
adapter that supports structures, exercise an accessible compatible record and
an unavailable or unsupported case. A ready structure must download actual
parseable bytes, match its retained source/material identity, declare whether it
is original or derived, and preserve provenance through caching and export.
An HTML error page, empty file, invented geometry, or wrong-phase download fails.

For each report record, use explicit outcomes such as available, unavailable,
unsupported representation, source unavailable, or not applicable. Lack of a
crystal structure for a polymer, mixture or disordered material is not itself a
failed materials answer. A literature-only service need not expose structure
files. Count compatible downloads over attempted compatible records, and list
which adapters were exercised; do not claim that all sources or all candidates
have downloadable structures. JSMol visual checks and cross-platform packaging
coverage require their actual environments.

## Cross-model and result reporting

Use the same frozen requests and source settings for each tested model. Useful
answers need not contain identical materials or scores when live sources and
model judgments differ. Compare scope, selected goals, valid decision evidence,
coverage, stability handling, and report usability. Keep measured, provisional,
lead-only, clarification, refusal, outage and failed runs as separate counts.
Record elapsed time and actual returned model/usage metadata when available.

Exercise experimental precedence with controlled source-backed test fixtures in
addition to live requests. If no live run contains an applicable experimental
and computed pair, report the live dimension as not observed; do not claim it
was validated by the absence of a disagreement. Likewise, a suite of plausible
tables is not proof of scientific accuracy or exhaustive material discovery.

## Evaluation regression checks

The evaluator separates source and report contracts, shortlist decision coverage,
and navigation-title usability. The matrix also records accepted classes,
request-grounded goals and roles, numeric targets, and the intended outcome for
clarification or refusal controls. Retain regression coverage for these boundaries:

- A row scored only by evidence completeness or composition bookkeeping cannot
  pass the decision-evidence check. A `needs_evidence` row remains a review lead.
- A cited but unassessed name, a malformed assessment bundle, and a table whose
  only assessed decision judgments are concerns cannot count as a successful
  shortlist of recommendations.
- Accepted alternative class interpretations pass; the wrong requested goal
  direction, missing selected importance, or an incorrectly retained environment
  or processing role fails its corresponding inference check.
- A requested clarification with useful guiding questions passes without a
  research report. A refusal in a clarification-only case does not. Refusal
  controls cannot retain research reports or source records.
- Repeated mentions of a provisional candidate do not inflate breadth. Count
  separately rendered quantitative and provisional tables conservatively when
  cross-table material identity cannot be established.
- A poor navigation title has a separate usability failure and does not change
  whether the scientific response satisfied its evidence contract.

These checks prevent known false passes and false failures; they do not replace
the independent review of application fit, phase identity, quote interpretation,
or experimental applicability. Live prompt results and model comparisons must
state which of those reviews were actually performed.
