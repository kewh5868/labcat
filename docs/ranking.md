# How ranking works

New research first provides a **candidate screening priority** using retrieved
public discussion of application relevance and demonstrated use. This
class-independent preliminary ranking keeps legitimate candidates visible even
when discrete material attributes are unavailable. Evidence for the selected
attributes then refines that priority in proportion to its selected weight;
reported application and stability concerns affect ordering. The full formula,
adverse-evidence tiers, missing-data rules and historical behavior are documented
in [Candidate screening with incomplete property evidence](literature-ranking.md).

This preliminary ranking is a priority for source review, not a measurement or
prediction of performance. It uses no hard-coded candidate answers. Validated
material-property records also receive the **separate property ranking** described
below. Keeping these tables distinct prevents literature interpretations from
masquerading as measured properties or transferring values between unmatched
material phases.

The application ranks validated records from a bounded public-source query.
The language model can interpret a research request and request approved
research stages. It cannot supply material properties, scores, weights, citations,
or substitute a written report for the deterministic result. It can separately
interpret cited public passages for a [candidate shortlist](literature-ranking.md);
those qualitative assessments never become measured property fields. User statements
and retrieved instructions are never scientific evidence.

The visible report sections are **Summary** and **Technical Overview**. Existing API
fields and saved report identifiers remain `pi_summary`/`technical_audit` and
`pi`/`audit` for compatibility. Old saved results are not rerun when opened.

## Property-ranking weights and missing evidence

For each selected criterion `j`, its importance `a[j]` must be finite and between
0 and 1. At least one importance must be positive. The algorithm computes the
following score in both `public-materials-utility-v8` (legacy requests) and
`public-materials-utility-v9` (validated semantic request goals):

```text
w[j] = a[j] / sum(a[k] for every selected criterion k)
contribution[j] = w[j] * utility[j]
supported score = sum(contribution[j])
displayed score = round(supported score, 8)
```

The total is calculated with `math.fsum`. Normalization includes unsupported and
missing criteria. Their utility and contribution are zero; their weight is
never redistributed to properties that happen to be available. Zero-importance
criteria do not affect ranking and do not become Technical View columns.

Version 9 also checks whether the utility implements the requested direction or
target. For an inferred profile, a goal that the existing utility cannot score
as requested remains selected but contributes zero; its source values and
citations stay visible as unscored evidence. This differs from missing data.
For example, the current lower-density utility cannot implement a request for
higher density. An explicitly selected or continued profile retains its utility,
and the report explains the conflict with the request. No opposite utility or
new normalization anchors are invented. If no record has any scorable selected
criterion, up to twelve retrieved records may appear as unranked review evidence.
The [semantic intake contract](semantic-intake.md) documents goal interpretation
and fixed priority values. Saved reports keep their original algorithm and scores.

A record must have usable source evidence for at least one positively weighted
criterion to receive a score and shortlist rank. Otherwise it is omitted with
an explicit reason. A known property can legitimately produce zero utility;
that record may still receive an overall score of zero. Source-formula elements
support the composition and element-screen criteria, even when no measured or
computed property is available. The evidence-coverage criterion alone requires
at least one supported property field.

This eligibility rule applies to the property table. It does not remove an
eligible source-grounded candidate from the new preliminary shortlist merely
because measured attributes are missing. The property calculation below and
the coverage-weighted preliminary refinement are distinct versioned methods;
the former is not silently used as the latter's attribute score.

Selected-weight coverage is the sum of normalized weights whose criteria have
usable evidence, clamped to 0–1 to contain floating-point rounding. It is a measure
of data availability, not a confidence estimate.
Missing or unsupported values remain **Unknown** or **Unavailable** in the report.

The report separates three questions:

```text
coverage = sum(w[j] for criteria with usable evidence)
fit on known criteria = supported score / coverage
possible upper score = supported score + (1 - coverage)
```

Each quantity is clamped to 0–1 to contain rounding error. Fit is shown only when
coverage is positive. It describes the available criteria and does not promote
an incompletely characterized candidate by itself. The possible upper score
sets every missing utility to one while holding known utilities fixed. It is a
conditional arithmetic bound, not predicted performance or a confidence interval.
Missing evidence therefore reduces the supported score without asserting that
the material itself performs poorly.

For an arithmetic example, weights of 0.5/0.3/0.2 with only the first criterion
known at utility 0.5 produce supported score 0.25, coverage 0.5, fit 0.5, and upper
score 0.75. These values demonstrate the calculation; they are not material data.

## Current property utilities

These fixed anchors express application preferences. They are not scientific
thresholds, measurements, probabilities, or universal material requirements.
Values are accepted only through an approved adapter's field validation.

| Criterion                        | Utility for a valid source value                                                                                                                                                                                                                                                                       |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Thermodynamic stability          | `max(0, 1 - energy_above_hull / 0.1)` with hull energy in eV/atom. Unknown or contradictory source stability information contributes zero.                                                                                                                                                             |
| Room-temperature phase stability | Currently unavailable: no approved quantitative mapping verifies phase persistence under specified ambient conditions. Selected importance contributes zero.                                                                                                                                           |
| Operational stability            | Currently unavailable: no approved quantitative mapping verifies performance retention under specified operating conditions and duration. Selected importance contributes zero.                                                                                                                        |
| Band gap                         | Without a target: `min(1, band_gap / 8)` with band gap in eV. With a target: `1 / (1 + (abs(source_gap - target_gap) / tolerance)^2)`; prefers closeness to the target.                                                                                                                                |
| Total dielectric scalar          | For `high_k_screening`: zero at or below 4, otherwise `min(1, log(dielectric_total / 4) / log(50 / 4))`. Other applications retain `min(1, dielectric_total / 50)`. Dimensionless, source-reported scalar.                                                                                             |
| Electronic dielectric scalar     | `min(1, dielectric_electronic / 10)`; dimensionless, source-reported scalar.                                                                                                                                                                                                                           |
| Density                          | `1 / (1 + density / 10)` with density in g/cm³; prefers lower density.                                                                                                                                                                                                                                 |
| Bulk modulus                     | `min(1, bulk_modulus / 300)` with the source VRH scalar in GPa; prefers greater stiffness.                                                                                                                                                                                                             |
| Shear modulus                    | `min(1, shear_modulus / 200)` with the source VRH scalar in GPa; prefers greater stiffness.                                                                                                                                                                                                            |
| Cell site count                  | `1 / nsites`; source cell size, not formula complexity.                                                                                                                                                                                                                                                |
| Metallic character               | 1 for source-reported metallic; 0 for nonmetallic. Missing classification remains unknown.                                                                                                                                                                                                             |
| Direct band gap                  | 1 for source-reported direct gap; 0 for indirect. Missing classification remains unknown.                                                                                                                                                                                                              |
| Composition simplicity           | `1 / max(1, number_of_distinct_source_formula_elements - 1)`.                                                                                                                                                                                                                                          |
| Element screening                | 1 when no element in the exclusion preset matches. Matches are excluded only if this criterion has positive importance.                                                                                                                                                                                |
| Supported-field completeness     | Fraction present among seven supported fields: band gap, total and electronic dielectric scalars, hull energy, density, bulk modulus, and shear modulus. This optional criterion uses a fixed field set, distinct from selected-weight coverage; it does not measure source reliability or confidence. |

The high-k curve reaches zero at the screening reference 4, one at 50, and 0.5 at
their geometric mean. Both anchors are explicit application preferences. They
are not user-provided evidence, measured values for a reference material, or
universal boundaries between low-k and high-k materials. No material names,
formula aliases or favored candidate list enter the utility calculation.

## Experimental and computed evidence

Applicable experimental observations take precedence over comparable computed
observations **before** threshold screening and ranking. The selected evidence
remains an intact source record: an experimental value is never patched into a
computed record alongside unrelated properties. If the experiment fails a saved
minimum, a more favorable calculation cannot replace it to rescue the candidate.

The current `experimental-precedence-v1` adapter contract supports HybriD³ band
gaps. A numerical comparison requires matching source system and composition,
gap kind, explicit phase label, crystal system, space group, sample type and
fixed conditions. Missing conditions, optical versus fundamental gaps, different
phases, or a formula match across sources do not establish comparability.
Unclassified methods are labeled unknown; method names, model memory, user
assertions and literature review passages do not establish an experiment.
Other property types need an approved observation/condition mapping before this
preference can be applied to them.

Summary and Technical View show both original values, units and separate source
citations. When comparable, the signed difference is **computed minus
experimental**. Otherwise the report explains missing or differing context and
does not calculate a misleading numerical difference or substitute the values.
Experimental evidence that controls screening remains visible when it leaves
no shortlisted candidate. Report exports share these written views and retained
comparison records; original observations and provenance are preserved.

Multiple comparable experiments are handled conservatively: minimum failures
take precedence, followed by the least favorable active target fit or lowest
reported gap. This is an explicit screening rule, not a judgment that one
experiment is more accurate. No average or uncertainty interval is invented.
All supplied experiments participate in selection before display limits. At
most 24 experiment/calculation pairs and 36 supporting records are retained for
comparison display; the report and audit disclose additional omitted pairs or
experimental ranges. The full report source list permits up to 144 entries,
including comparison provenance and other retained research sources. These
bounds limit presentation, not experimental precedence.

## Stability across material classes

Every shipped class and application profile includes at least 0.3 raw importance
for thermodynamic stability, room-temperature phase stability and operational
stability. These are editable ranking preferences, not physical thresholds.
The same baseline applies to perovskites, organic electronic materials, quantum
dots, metals, and the other catalog classes; it does not expand source coverage.
An explicit custom profile retains its chosen values, including zero weights.

Each new ranked record carries `stability_assessment` with schema
`stability-assessment-v1`. Its `thermodynamic` assessment reports the validated
source energy above hull or **unknown**. Its `ambient_phase` and `operational`
assessments currently remain **unknown** with the missing evidence explained.
These scope-qualified caveats remain visible even when a custom profile gives
stability zero weight. Missing data is not evidence that a material is stable or
unstable.

A positive source hull energy lowers thermodynamic utility. A zero value means
only that the source places the structure on its calculated convex hull under
its calculation assumptions. It does not establish persistence of the desired
phase at room temperature, degradation rate, stability in air or moisture,
illumination tolerance, or device lifetime. Positive hull energy likewise does
not prove that degradation occurs at room temperature. Invalid hull values,
including booleans, negative values and nonfinite numbers, remain unknown.

Reported room-temperature transformations or operating degradation must affect
suitability when supported by an approved mapping of the same material, phase,
conditions and observation. **The current adapters do not provide that mapping.**
Retrieved study passages therefore remain attributed review leads and do not
automatically change scores. Neither a matching keyword, a user assertion, model
memory, a generic stability flag nor an unverified passage can populate a
stability criterion. This is a current coverage limitation, not evidence that
the reviewed materials have no stability problems. A future source-specific
adapter must validate the observation and its conditions before scoring it.

The preceding limitation concerns measured-property scores. In the separate
`literature-fit-v2` shortlist, a validated source-bound qualitative stability
assessment can alter the review tier and selected-attribute interpretation.
That change is explicitly labeled; it neither fills a missing measured value
nor establishes room-temperature or operational stability as a verified fact.

## Default high-k profile and saved preferences

The first-run profile is **Oxide dielectrics · High-k screening**. Its raw
importance values are stability 0.5, band gap 0.6, total dielectric response 1.0,
element screening 0.3 and simplicity 0.2. Electronic dielectric response and
supported-field completeness start at zero. Room-temperature phase stability
and operational stability each start at 0.3 and currently remain unavailable.
Electronic response already
contributes to the total dielectric scalar; selected-weight coverage is reported
separately without rewarding a second completeness weight by default. Scientists
can still include either criterion in a custom profile.

The high-k preset also sets an explicit **minimum band gap preference of 2 eV**.
This is a configurable screening preference, not a physical cutoff, a predicted
experimental gap or evidence that a material is safe. The optional profile field
`minimum_band_gap_ev` accepts finite values from 0 to 100; omission or `null`
disables it. Other presets and existing custom profiles do not acquire a minimum
silently. Known gaps below the selected minimum are excluded with a reason; a
gap equal to the minimum passes. Missing gaps remain unknown review leads, not
assumed failures or successes. This explicit condition prevents a large
dielectric response from compensating for failure to meet the requested gap
preference. Calculation-method and application caveats still apply.

Importance sliders remain independent values between 0 and 1; users need not
make them sum to one. Changing weights changes preference contributions, not
retrieved measurements. Custom application labels retain the generic utility
rules unless they select the defined `high_k_screening` application.

An optional `target_band_gap_ev` changes gap utility from maximizing gap to
matching the requested value. `band_gap_tolerance_ev` is a positive preference
scale: a gap at the target has utility 1, and a gap one tolerance away has utility
0.5. It is a soft score, not a hard acceptance interval, physical error bar or
source uncertainty. When no tolerance is specified, the application uses an
explicitly disclosed, editable 0.2 eV preference. Both fields accept values up
to 100 eV; targets may be zero and tolerances must be positive. Omission or `null`
disables the target. A tolerance without an enabled target is invalid.

A known source gap is always retained unchanged. A missing gap receives no gap
utility and stays **Unknown**; for a positively weighted target it also places
the record in **needs evidence** after candidates with a comparable measured or
computed gap. Target fit never supplies a missing measurement. If a minimum
and target are explicitly saved together, the minimum remains a separate hard
screen before target scoring.

On upgrade, only exact unchanged earlier shipped presets receive the stability
baseline. The earlier high-k migration also handles the intermediate v5 preset
without a minimum-gap field. An explicitly disabled
or edited minimum is preserved. Custom
copies, edited values or labels, reordered property preferences and the active
profile selection are preserved. Migration is idempotent and does not rewrite
ranking-profile snapshots or scores stored in earlier reports. Invalid saved
preferences remain an error to resolve, rather than being silently reset.

Other selectable profile attributes remain visible and receive zero contribution
until an approved quantitative adapter supports them. Public literature passages
are separately attributed review leads. They never silently populate a property
cell, merge phases, or change a score.

## Inferring request preferences

**Infer from prompt** first matches a catalog material class and application to
a saved profile. If the exact pair is absent, it combines the requested class
with the catalog's application priorities for that run. For example, a recognized
optical application uses optical priorities even when its material class has only
an exploration preset. This creates no saved profile, candidate or evidence and
does not change the workspace's active profile. Ambiguous class/application hints
retain an explicitly disclosed fallback; selecting a profile overrides inference.

Narrowly phrased property goals can refine the run's inferred preferences. A
request for a band gap “around” a value creates a target; “at least” creates a
minimum. An explicit target replaces an inherited minimum unless the current
request states both. Claim-bearing sentences, URLs and arbitrary numeric fields
are not accepted as property goals. No prompt value enters a material evidence
record. Requested stability and solution processability retain at least 0.5
importance; processability is currently unscored and must remain visible as a
source-review gap. Hull energy does not establish processing or operating
stability.

An explicit profile choice keeps that profile's preferences. Otherwise, a
continuing chat preserves its previous report's profile and target settings;
an explicit new property goal can refine that run without rewriting earlier
reports, pins or saved profiles. Every applied goal and default tolerance is
recorded in the report's ranking-selection metadata.

## Exclusions, ties, and scope

The conservative element-exclusion preset (`conservative-elements-v2`) contains
Ac, Am, As, At, Be, Bk, Cd, Cf, Cm, Es, Fm, Fr, Hg, Lr, Md, No, Np, Pa, Pb, Pm,
Po, Pu, Ra, Rn, Tc, Th, Tl, and U. This is an application screening preference,
not a measured hazard assessment. It is incomplete and does not establish
compound toxicity or safety. It is active only when element screening has
positive importance. The exact set and version are saved in each ranking;
older reports retain their original policy and scores.

When this screen is selected, the keyless bulk adapter also applies the same
exclusion preference to its public query so excluded elements do not consume
the small retrieval sample. Positive composition-simplicity importance requests
ascending distinct-element count from that adapter. Broad oxide-dielectric
queries require at least two elements. These are sampling preferences, not
evidence of dielectric performance, ambient stability, or film suitability;
for example, an oxygen-containing bulk structure may still be unsuitable.

For high-k screening, positively weighted total dielectric response and band gap
are required for the **comparable** group. Records missing one of these fields
remain **needs evidence** review leads after comparable rows, even if their
supported score is larger. This is a requirement for making the comparison, not
proof of suitability: a known value with zero utility remains known. A criterion
with zero importance does not create an evidence requirement. A positively
weighted band-gap target likewise requires a reported gap for the comparable
group; other applications retain their generic score ordering.

Within each comparison group, records are sorted by supported score descending,
then source record ID lexicographically for exact displayed-score ties. The tie
break is reproducible ordering, not scientific evidence favoring one tied
material. At most **12 distinct reduced elemental compositions** appear, with one
phase per composition; stoichiometrically equivalent spellings such as SiO2 and
O4Si2 compete for the same place. The winning row keeps its original formula,
identity and properties. Lower-ranked phases of selected compositions are
recorded as alternatives; properties are never merged across phases. A smaller
source pool yields a smaller shortlist, with no invented padding. Duplicate
source record identities are rejected rather than scored twice.

The candidate pool is bounded by enabled sources, source filters, query budgets,
and adapter coverage. No fixed shortlist is substituted when retrieval fails.
Follow-up prompts retain the chat's saved ranking preferences unless another
profile is explicitly selected or a new topic is established. Earlier source
identities are re-fetched through the currently selected public adapters and
checked against current composition filters. Up to six identities can be
refreshed within the shared 30-second repository budget; stale report values
are never substituted on failure. These freshly validated rows join the new
search; new rows replace refreshed rows with the same exact source identity.
Bulk composition or calculations do not establish processing, thin-film,
nanoscale, device, safety, or application performance. The current utilities
cannot optimize every material class or application; the selected profile and
unavailable-property list must be reviewed with the report.

## Property tables, colors, and reproducibility

The Summary contains written findings, caveats, citations, and a compact leading
table. Technical View starts with rank, material identity, and numeric supported
score, followed by **every positively weighted property in saved profile order**.
Each property has its source value/unit or explicit unknown status. Record details
retain contributions, fit on known criteria, selected-weight coverage, comparison
status, source method, provenance, and missing-data caveats. Saved Report Format
preferences control how much detail is shown; changing a preview does not
silently overwrite saved reports or frozen pins.

The structured `result.report_tables` contract uses schema `ranking-tables-v1`.
It stores the same column order and rows as the readable text, including raw
property values, normalized weight, component utility, contribution, citation
identifiers, and score color. The original execution settings and ranking
metadata remain attached to the result; later preference edits do not recalculate
an existing report.

Score colors use an **absolute** 0–1 utility scale: red `#F8D7DA` at 0, amber
`#FFF0C2` at 0.5, and green `#D5EDDD` at 1, with linear RGB interpolation.
Low/medium/high utility bands use cutoffs of 1/3 and 2/3. These are application
display conventions, not evidence thresholds. A weak leading candidate remains
red or amber; the best observed candidate is never automatically made green.
Numeric scores and descriptive labels remain available without color.

PDF and Word apply the same backend colors to rank and utility cells. Wide
technical tables repeat identity and utility across groups of four property
columns to preserve readability without dropping properties. TXT and JSON retain
numeric utility, status, citations, and the complete property selection.
