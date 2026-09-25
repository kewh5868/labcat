# Candidate screening with incomplete property evidence

New research uses **`literature-fit-v2`** to produce a candidate shortlist from
retrieved public discussion before all material attributes are available. It
answers: **which candidates should be reviewed next for this application?**
It does not turn a mention into a measured property or an experimental
recommendation. Validated repository measurements still have a separate
[property ranking](ranking.md), with original source identities and units.

The same preliminary rules apply across materials classes. There is no stored
list of preferred materials, prompt-specific answer, or popularity-based
replacement for retrieval. User requests supply search goals and preferences;
only approved public-source adapters supply the evidence being interpreted.

## From retrieval to shortlist

1. Search enabled, approved public sources for the request and its application.
   Current retrieval uses fixed source adapters and bounded searches, not an
   arbitrary web crawler. It does not access paywalled full text. Reported access
   metadata is distinct from verifying a complete article; the report retains
   which source text was actually retrieved.
2. Retain candidate names only when they occur in retrieved passages. A name in
   the prompt, model memory, or an unattested citation cannot create a candidate.
3. Assess application relevance and demonstrated use from the discovery
   passages, completing the general comparison before detailed properties.
4. Before the selected-attribute assessment, use the bounded property follow-up
   to look for selected criteria in available open-access body text or public
   abstracts about those admitted candidates. Explicit
   user goals and their weights take priority, with selected stability criteria
   included in the bounded search. Return eligible source-bound passages to the
   agent before finalization; retrieving them only after evaluation cannot
   affect that evaluation. Preserve each original discovery abstract and its
   document identity when adding separately identified body passages.
5. Interpret selected attributes when suitable passages are available, including
   counterevidence and stability concerns. These are qualitative model
   interpretations, not measurements or scientific validation.
6. Calculate a preliminary score, refine it in proportion to available selected
   attribute evidence, and apply the adverse-evidence tiers below.
7. Present the shortlist, evidence gaps, method, and linked source passages.
   Failed sources do not discard candidates found through healthy sources.

The current body-text assessment route uses approved Europe PMC open-access
articles. It retains the article title, section, exact complete paragraph
(up to 4,000 characters), locator and response hash. A cropped paragraph remains
a review excerpt rather than an assessment document, because omitted words may
qualify the observation.
The XML reader permits one narrowly validated, inert article DOCTYPE in the
prolog. It removes that declaration before parsing and never fetches or resolves
its identifier. Internal subsets and entity declarations remain prohibited.
Article identity, publication policy, encoding, size and tree limits still apply;
provenance hashes the original downloaded bytes, not the sanitized parser input.
An explicit assumed-input section cannot establish a measured property merely
because its paragraph states a number. These checks retain provenance and
method context; they do not certify the scientific interpretation.

An enabled OpenAlex adapter can provide targeted abstracts when Europe PMC is
unavailable, when OpenAlex is the selected follow-up source, or when an empty
search has a spare search slot after other criteria. Abstracts retain their own
source metadata and never claim a full-text read. Earlier discovery snapshots
remain fixed; new follow-up documents cannot add candidates after assessment
begins. Already cited documents take priority under the shared 24-document cap.
The evaluator authenticates the exact document set selected by the parent,
including follow-up abstracts, against the retained approved source snapshots.
It does not compare that set with a separately chosen default subset. Document
IDs only guide bounded selection: every complete snapshot, candidate citation
and assessment quotation must still match. Duplicate, altered or unavailable
documents cannot establish evidence, and the combined document limit is
unchanged. Saved reports without an explicit document set retain their original
reconstruction behavior.

The optional lookup keeps its existing maximum of three searches across both
providers, six retained references, six article downloads and fifteen seconds
inside the research run. A fallback uses the same budget. It runs
once after the first assessment batch and is reused during finalization.
Candidate discovery is completed before evaluation begins. Source failures or
budget exhaustion leave existing candidates and assessments available, with
unresolved criteria disclosed; they do not authorize extra model calls or
invented property values.

New article attempts also retain bounded `article-parse-v1` diagnostics: the
requested PMC identifier, completed-response digest, download and parse states,
and fixed failure/declaration codes. At most six distinct attempts are recorded;
cache reuse adds none. No body text, exception message or declaration identifier
is copied into these diagnostics. An accepted parse remains accepted if later
metadata or passage selection fails. Failed downloads have no response digest.
These records explain retrieval failures; they establish neither scientific
evidence nor useful attribute coverage. Older reports without this optional
diagnostic field retain their existing reconstruction behavior.

When only one assessment batch remains, its instructions combine outstanding
general judgments and corrections with the selected-attribute tasks actually
delivered to the model. There is no separate third property pass. Task priorities
and counts are recomputed after reply trimming; a withheld document or task does
not create an obligation to assess it. These counts describe work, not evidence.
Missing attributes may remain unattempted and unknown. Valid partial assessments
survive format or evidence failures in other rows, within the unchanged call,
row and byte limits.

When discovery documents are available, a premature report request must first
return the model to candidate selection. Before finalization, one bounded
assessment reminder can return outstanding general judgments and selected
attribute reviews. The [assessment workflow](agent-protocol.md) documents these
stage prerequisites, review tasks and actual offered-context counts. The model can
still exhaust its budget or stop; provider completion does not establish that
assessment finished. Rejected worker submissions are recorded separately as
bounded tool/reason counters, without rejected arguments or model prose. These
worker-reported diagnostics cannot establish a successful parent action or a
scientific fact. Older reports without these counters cannot distinguish an
omitted evaluation from one rejected before it reached the main application.

Expected parent tool failures also return fixed repair guidance through both the
local broker and isolated worker callback. Categories distinguish invalid intake
shape, unbound request interpretation, stage order, malformed submissions and
exhausted budgets. Binding failures remain coarse categories; they do not claim
to identify an individual missing span or scientific error. The saved build plan
keeps bounded parent reason counters, separately from worker-reported validation
and assessment-row feedback. Rejected inputs and exception text are never
included. Unexpected failures return a generic rejection. Repair attempts still
consume the original call budget; these messages grant no new tools, retrieval
destinations, evidence permissions or assessment batches.

After a successful report tool call, the server can stop a model process that
continues waiting. It allows a two-second exit grace period within the existing
runtime deadline. A normal exit retains validated final usage metadata; a forced
stop is recorded as `stopped_after_report`, with usage unavailable rather than
zero. The parent process must independently confirm that it retained the report.
This is a report-delivery status, not a claim that all requested assessments or
scientific validation finished. It does not invalidate an otherwise usable
model connection or authorize further inference.

Assessment submission and scientific admission are separate. A bounded transport
envelope may contain up to 96 rows within 24 KB; malformed or oversized envelopes
are rejected as a whole. Within a valid envelope, each row still passes the same
strict format, candidate, criterion and exact-source validation. Invalid rows
receive fixed feedback indexed to their original submitted positions, while
independently valid source-bound rows are retained. A number-containing name in a
qualitative interpretation remains invalid; the model can say “this candidate”
and keep source numbers in its exact quote. No rejected row is repaired or
converted into evidence.

An admitted envelope, even one with no accepted rows, uses one of the existing
two assessment batches. Replaying the same bounded submission reuses its feedback
without adding a batch. Only accepted rows and fixed feedback are retained;
submission fingerprints contain no rejected prose. Previously accepted judgments
survive later rejected rows, and conflicting source-bound judgments remain
visible. Saved assessment metadata counts fixed parent rejection reasons once per
distinct batch; retries of the same submission do not inflate those counts.
Canonical ranking calculations and validation of historical reports are
unchanged. A processed submission does not establish that every requested
criterion was assessed or that its scientific conclusions are correct.

Every retained, eligible candidate can receive a preliminary rank even with
zero assessed attributes. Equally unassessed candidates share the same rank;
alphabetical display order does not imply scientific preference. Useful leads
remain visible without claiming that every requested constraint is satisfied.
If no eligible candidate name can be retrieved, the program must report the
retrieval failure and useful next steps; it cannot fabricate a shortlist.
Explicit exclusions must not be evaded through favorable preliminary scores or
by substituting a different material with a similar name.

## Application-focused discovery and displayed properties

For perovskite/silicon tandem requests, publication searches retain the
perovskite, silicon and tandem context instead of reducing the question to a
generic solar-material query. An authoritative material-target interpretation
prevents the surrounding device from replacing a different requested material.
The enabled Europe PMC adapter can read up to two open-access article bodies
within the existing discovery deadline and shared article-download cap, retaining
up to three complete
composition/device paragraphs per article. These paragraphs keep article,
section, locator and response-hash provenance, and enter the same validated
candidate-selection boundary as abstracts. An unavailable body leaves its
accepted metadata available. Disabling literature follow-up also disables these
body lookups; repeated discovery calls cannot reset the shared download cap.
No candidate list or composition is hardcoded. One informative composition
passage per article is offered before longer abstract queues can exhaust the
model-input limit. New body documents retain their literal section heading
within the quoted text, so device-fabrication and simulation context can be
cited with the paragraph. Historical paragraphs keep their original document
identity and text.

The research instructions distinguish an absorber actually used in a device
from a theoretical proposal, precursor, passivant, transport layer or absorber
for a different device role. A literal fractional composition must be retained
as reported; it is not replaced by an idealized parent formula. A source-bound
mention is still not proof of device use or suitability: those conclusions
require separate cited assessments.

An inferred perovskite photovoltaic profile prioritizes band gap, operational
stability and ambient phase stability. It does not invent a numeric optimal
gap or a property value. Explicit request goals override inferred preferences;
a manually selected saved profile retains its weights. Non-photovoltaic
optoelectronic requests keep their existing defaults.

Technical View displays at most three material properties in its shortlist:
explicit positive-weight goals first, then the application/profile importance.
When one literal request span is interpreted as several overlapping goals
(such as “stable”), one representative receives compact-display priority;
separately requested properties remain distinct. Enabled saved band-gap
targets/minimums remain visible even in manually selected profiles.
The same properties are compared for every candidate, including when evidence
is missing. Each available entry is an exact cited assessment passage, with
longer source context expandable. Values, units, measurement method and device
conditions remain in the quotation; they are not silently converted into
validated numerical fields. Device efficiency is not relabeled as an intrinsic
material property, and no property is transferred between different phases or
compositions. Missing evidence is shown as “Not reported.” Summary retains its
compact coverage column; both views preserve the same ranking and table layout.

## A consistent preliminary score

Two general criteria are independent of the material class:

- **Application relevance:** whether retrieved discussion supports using the
  named candidate for the requested application or role.
- **Demonstrated use:** whether retrieved discussion supports that use having
  been demonstrated, retaining the reported setting and limitations.

Application relevance concerns the requested functional role. Missing lifetime,
processing or performance evidence remains unresolved under its own selected
criterion; it does not cancel source support for that role. A source about a
different component role or a constituent of a composite does not establish the
requested use. Family membership alone is insufficient. A proposal or simulation
may motivate application review, but does not establish fabricated, tested or
deployed use. Prospective-only use stays unknown rather than receiving the
positive increment assigned to mixed demonstration evidence. Mixed means actual
conditional or conflicting evidence, not missing information.

A passage can support the criterion, raise a concern, be mixed, or leave it
unknown. Support maps to `1`, mixed evidence to `0.5`, and concern to `0`. An
unknown **general** criterion uses `0.25` as an explicit prior for review. This
constant is a ranking convention: it is not evidence of suitability, a success
probability, a measured value, or a positive assessment.

```text
R = general application-relevance utility
U = general demonstrated-use utility
D = number of distinct works with supporting or mixed application assessments
C = min(D / 3, 1)
B = 0.70 × R + 0.20 × U + 0.10 × C
```

`B` is the preliminary score. Corroborating works are grouped when either a
normalized DOI or normalized title matches, including linked copies across
indexes where one copy lacks a DOI. Source URL is a fallback only when both
identifiers are missing. An ambiguous shared title conservatively reduces the
bonus; this grouping is not proof of scientific equivalence. Wikipedia does not
contribute to `D`. Multiple copies or quotations of a work do not count as
separate works. This component contributes at most `0.10`; it is not a
citation-popularity score, source-credibility certificate, or proof of independent
experimental replication. Unknown or adverse application passages do not earn it.

Application relevance and demonstrated use do **not** consume selected attribute
weights. Their weights are fixed, versioned method constants, so changing the
material class cannot silently change the preliminary formula.

New model submissions undergo conservative admission checks before this
arithmetic. A positive or mixed demonstration claim needs local evidence of
actual use; a planned experiment does not qualify merely because its quotation
contains the word experimental. A non-unknown attribute claim cannot rely only
on a source title, or on explicit assumed/input-parameter language in the
containing sentence. The original full source remains available for a corrected
quotation. A rejected claim leaves the candidate in the shortlist with that
criterion unresolved; it does not substitute an invented judgment. These checks
detect specific unsupported claim patterns, not all scientific errors, and do
not certify the remaining text as experimental.

Operating-stability review also recognizes condition-scoped wording such as
limited stability in humid or oxidative conditions and stability during
adsorption/desorption, charge/discharge, thermal or mechanical cycles. The
candidate, stability wording and exposure must occur in the same local clause.
This additional path excludes explicit synthesis and equilibrium-only wording;
bare stability, an environment word or a cycle mention alone is insufficient.
It offers the unchanged source passage for model review. It does not choose a
favorable or adverse judgment, establish service conditions, or change scoring.
This bounded vocabulary check can still miss or misinterpret complex prose.

Admission policy applies to new tool submissions. Existing saved v1/v2 bundles
continue to validate against their original accepted interpretations and ranking
arithmetic; their scores, citations and pinned snapshots are not rewritten.

## Refinement using selected attributes

The saved profile determines which attributes matter and their importance.
Normalize positive importances to `w[j]` summing to one. For each assessed
attribute, support has utility `1`, mixed evidence `0.5`, and concern `0`. An
unknown attribute has no observed utility; it does not receive the general
review prior or an invented measurement.

```text
c = sum(w[j] for assessed selected attributes)
A = sum(w[j] × assessed utility[j]) / c, when c > 0
P = (1 − c) × B + c × A
P = B when c = 0; A is then undefined
```

`P` is the displayed **screening priority**. `c` is selected-attribute assessment
coverage, not scientific confidence. With no assessed attributes, a candidate
keeps its preliminary score. As evidence arrives, assessed attributes replace
the corresponding share of the baseline and can raise or lower the result.
At complete coverage the selected attributes determine the numerical score.
Unknown attributes therefore do not count as poor performance, while a known
concern can still lower the score.

Pure arithmetic example, **not material data**: unassessed general criteria and
no corroborating works give `B = 0.225`. If half the selected attribute weight
is assessed as supporting, `c = 0.5`, `A = 1`, and `P = 0.6125`. This is a review
priority under stated rules, not a prediction that the material will work.

### Applying and checking changed weights

Save the edited ranking profile, then select that named profile in the chat's
ranking control for the next request. An explicitly selected profile retains
its saved weights. **Infer from prompt** can choose a different class or
application profile; the active workspace profile is not an unconditional
override of automatic inference. Reports record which profile and weights were
actually used. Changing preferences does not rewrite an existing report or a
pinned snapshot; run a new analysis to apply them.

Increasing a criterion's relative weight increases its contribution when there
is an accepted assessment for it. If every candidate is unassessed on all
selected attributes, changing weights alone cannot create a meaningful
distinction. Such candidates retain an explicitly unassessed review prior.
If all candidates have the same assessed fit, their order can also remain tied.
The application must seek relevant evidence, not manufacture different scores.

For a controlled weight-sensitivity check, freeze candidate identities, source
passages, goals, and accepted judgments, then change only the importances.
Compare scores and ordering within the same adverse tier. Also check the
no-evidence case remains unchanged. Changing the target or criterion direction
changes the question being assessed and requires reassessment; it is not a pure
weight comparison. A reversal establishes that preferences affect the
calculation, not that the underlying scientific interpretation is correct.

The live-prompt evaluator records selected-criterion counts separately for
accepted non-unknown assessments, explicit unknown judgments, and unattempted
candidate/criterion pairs. It also records each candidate's assessed weight
coverage. A completed model run or a nonempty table does not by itself pass
scientific usefulness review.

## Adverse evidence, stability and ties

Ordering first respects the strongest adverse assessment for application
relevance or any of thermodynamic, room-temperature phase, and operational
stability:

| Tier | Meaning                                                      | Ordering                                                  |
| ---- | ------------------------------------------------------------ | --------------------------------------------------------- |
| 0    | No adverse assessment, including unresolved or unknown cases | First for review; not an assurance of safety or stability |
| 1    | At least one mixed assessment, with no explicit concern      | After tier 0                                              |
| 2    | At least one concern assessment                              | After tiers 0 and 1                                       |

The strongest underlying adverse assessment remains even when another passage
is favorable and the aggregate judgment becomes mixed. A large score cannot
override a higher adverse tier. These tiers apply even when a custom profile
gives a stability attribute zero importance; the attribute arithmetic still
uses saved weights. Hard exclusions remain separate from soft review priorities.

Within a tier, sort by descending `P`. The same tier and rounded score receive
the same rank. Name and source identity give tied rows a stable display order,
not a scientific tie-break. Conflicting passages may reflect different phases,
preparation routes or operating conditions; their quotations remain available
for review. Unknown stability is always disclosed. A thermodynamic calculation
does not establish phase persistence at room temperature or device lifetime.
Literature stability assessments remain attributed interpretations, not new
quantitative source fields.

Selected-attribute judgments must address the requested conditions and material
or device scope. Processing survival does not by itself establish operating
lifetime, and favorable behavior in one environment does not establish behavior
in another. If the source cannot establish the requested scope, the assessment
stays unknown and states that limitation. Missing tests or different conditions
alone are not adverse findings and must not create a mixed-evidence tier.
Actual applicable adverse or conflicting evidence is needed for that tier.
These are assessment instructions, not a claim that the server can mechanically
validate every scientific interpretation. Source binding and quote checks cannot
establish equivalent test conditions.

Operational-stability searches cover mechanical and service degradation as well
as environmental and optical aging, including fatigue, cyclic loading, wear,
corrosion resistance, creep and signal drift. These are shared search terms,
not class-specific rankings or evidence that a candidate survives those tests.
The selected goal and requested conditions still determine what a retrieved
observation can support.

The report displays these groups as **First review group**, **Mixed evidence**
and **Reported concerns** when more than one is present. Scores descend within
each group; a higher percentage in a later group does not override its concerns.
Repeated ranks are marked as ties. The display uses whole percentages, so two
rows can show the same percentage even when the stored scores differ. These
labels explain the saved order without reordering or rescoring historical reports.

## Evidence, limits and experimental precedence

The assessment tool accepts an existing candidate, an allowed criterion, an
existing document, an exact candidate-containing quotation, and a bounded
interpretation. The server validates those bindings and criterion context.
It accepts no arbitrary URL, new identity, numerical measurement, user-provided
evidence, model-provided final score, or instruction to change retrieval policy.
Quote validation establishes provenance; it does not prove that the model
interpreted the study correctly. Background discussion must not be presented
as measured material performance.

Public-reference metadata can retain `used_for_ranking: false` because the
reference is not scored material-property evidence. Version 2 stores its
source-bound qualitative interpretations separately in `literature_evaluation`;
those judgments feed screening priority without upgrading the underlying
reference into a measured-property record. Additional unassessed follow-up
excerpts do not change priority merely by being retrieved.

Measured experimental observations take precedence over computed observations
only when an approved adapter verifies compatible identity, phase, property
definition, sample and conditions. A matching formula is insufficient. Current
quantitative precedence supports condition-matched HybriD³ band-gap comparisons;
it does not classify a literature passage as experimental or transfer an
experimental value into an unrelated structure. Comparisons and discrepancies
retain both original sources. See
[Experimental and computed evidence](ranking.md#experimental-and-computed-evidence)
for the supported mapping and conservative selection rules.

The Summary presents **Candidate shortlist** with priority, why each candidate
is considered, attribute coverage, and stability or application caveats.
Technical Overview retains equations, component counts, criterion weights,
interpretations and supporting quotations. Measured-property rankings remain
separate; their scores are not interchangeable with screening priority.
Exports use the same validated calculation and source links. A preliminary
shortlist must not be described as a failed shortlist just because a separate
measured-property ranking is unavailable.

## Historical version 1 and saved reports

Existing **`literature-fit-v1`** reports retain their original rules and
presentation. Version 1 assigns a provisional rank only when at least one
selected criterion has an assessment:

```text
supported fit = sum(weight × assessed utility)
coverage = sum(weights of assessed criteria)
fit on assessed criteria = supported fit / coverage
unknown-criterion range = [supported fit, supported fit + 1 − coverage]
```

Its ranking uses supported fit, with coverage and stable identifiers determining
display order for ties; equal supported fit keeps tied ranks. Missing evidence
reduces supported fit without establishing poor performance. The range allows
unknown criteria to vary between concern and support while holding assessments
fixed. It is not a confidence interval, and citation counts do not increase
version 1 utility. Unassessed mentions remain unranked in saved version 1
reports. The new baseline is never retroactively applied to them.

Saved evaluations are rebound to passages and the saved profile and recalculated
under their recorded version before rendering or export. Tampered scores,
ranks, evidence or preferences are rejected. Opening historical reports never
runs the model again; pinned snapshots retain their captured state.

## Preserving the requested role during follow-up

Optional article follow-up uses validated repository formulas first. When those
are unavailable, it uses source-bound candidate names already retained by the
parent validator, then falls back to validated subject spans from the request.
Application words form a separate query group. The selected criterion's vocabulary
is required in its own query group; operating or processing words cannot substitute
for a property term. Those conditions remain in the saved request and assessment
scope, rather than becoming mandatory search words that could exclude relevant
publications. Query operators, destinations, open-access constraints and retrieval
limits remain server-owned. A literal name match in a
retrieved passage associates it with a lead; it does not establish phase identity
or turn the passage into a measured property. Eligible paragraphs offered before
finalization can support a separate source-bound assessment. Follow-up retained
only after finalization remains review material and does not retroactively change
completed assessments.

Assessment instructions distinguish complete application-role support from a
partial family-level match, and direct demonstrated use from simulation or
proposal alone. They require the model to retain uncertainty when the passage
cannot establish study type. These instructions improve consistency but remain
subject to scientific review; quote binding alone cannot validate interpretation.

## Diagnosing missing evidence and clarification responses

New article follow-ups retain bounded `property-filter-v1` counters per selected
attribute. These separate search failures, downloads, parsing, cached article
reuse, screened paragraphs, criterion matches, candidate-name matches, crop
exclusions and retained passages. Paragraphs not examined because the passage
limit was reached are counted separately. Counters describe the retrieval and
filtering work; they do not establish a material's properties, relax identity
checks or affect a score. Unselected article bodies and raw errors are not saved
in these diagnostics. Older reports without these counters remain supported.

New clarification and refusal messages may also retain a separate
`intake-execution-v1` diagnostic record. It contains only fixed execution states,
the accepted fixed intake decision, bounded parent-observed tool statuses,
classified exception counters and
validated worker-reported rejection counts. Parent exception counts do not
include every structured rejection, and neither trace captures traffic rejected
before an admitted tool callback. Missing historical metadata remains unknown.
These records are excluded from subsequent model context and scientific evidence.

Requested and attempted model identifiers describe the parent's configuration.
An attempted operation can fail before contacting the provider; these identifiers
are not proof of inference or a provider attestation of the resolved model.
The resolved-model field remains unknown. A refusal completed before model access
is explicitly recorded as `not_run`. Diagnostic storage never creates a report,
retries a request or changes a clarification or safety decision.
