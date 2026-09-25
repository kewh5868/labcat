# Public sources and discovery

Labcat accepts research questions across material classes. It searches live
public adapters using bounded hints from the question and the selected source
settings. Accepted analyses start with the selected public discovery services;
cited identities and literal formulas can guide independent repository lookups
alongside the broad class search. Optional database connections add coverage;
the property catalog is not tied to one provider.
When selected attributes remain missing, the application tries targeted searches
and skims available open-access article text. A database identity, publication
title or matching passage alone cannot establish a verified measurement.

## Choose sources

New installations enable public reference discovery without account keys. In
**Search Criterion**, choose databases, set a maximum of 1–10 references per source,
or turn discovery off. Queries send search hints to the selected public services.
Existing saved settings remain respected, and changes apply to new reports.

| Source                                                                                  | What the adapter retrieves                                                                                                                             | What it does not establish                                                                                               |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| [Materials Project](https://materialsproject.org/) (optional API)                       | Typed public material records and supported properties when a key is connected                                                                         | Complete property coverage or experimental suitability                                                                   |
| [Public dielectric dataset](https://doi.org/10.6084/m9.figshare.7108790.v2) (anonymous) | All matching rows from a freshly downloaded, checksum-pinned historical release; calculated band gaps, dielectric scalars and exact-release structures | Current database values, hull energies, compound safety or thin-film performance                                         |
| [HybriD³](https://materials.hybrid3.duke.edu/)                                          | Public identities and validated scalar band-gap datasets, with separate method, sample and phase provenance                                            | Complete catalog coverage, solution processability, stability or experimental suitability                                |
| [NOMAD](https://nomad-lab.eu/)                                                          | Published, non-embargoed identities; selected validated band-gap/structure fields for supported bulk-composition queries                               | Complete class/property coverage, stability or application suitability; generic terms may return no quantitative matches |
| [Europe PMC](https://europepmc.org/)                                                    | Open-access publication metadata and bounded article-text passages for missing-attribute review                                                        | Independently verified material-property values or automatic score changes                                               |
| [arXiv](https://arxiv.org/)                                                             | Public preprint titles and links                                                                                                                       | Peer-review status, full-text conclusions or verified material properties                                                |

These are reviewed public adapters, not an unrestricted scraper of every website.
Material classes and property coverage differ across databases. User URLs, pasted
citations and query operators do not become network destinations or evidence.
Adapters use fixed destinations and bounded requests; retrieved instructions
cannot change policy or authorize more tools. Rate limits, failed requests,
omitted properties and incomplete coverage remain visible.

Each repository, discovery service and property follow-up has an independent
failure boundary. Timeouts, rate limits, server errors and malformed responses
mark that source unavailable while retaining validated results from other
sources. Repository calls share a fixed time budget, divided across remaining
providers so an early slow source does not consume every later provider's turn.
A failed later article lookup cannot remove a citation supporting an earlier
passage. If every selected source fails, the answer explains the unavailable
coverage without inventing a shortlist or substituting test data.

If the model connection stops after both the fixed safeguards and the model have
accepted the request, the server can finish the already configured public-source
stages and save their evidence as a partial report. It makes no further model
call, does not invent a successful model trace or usage count, and explains the
interruption in both report views. A model failure before successful assessment
still stops research; this recovery does not bypass required sign-in or safety
checks. The next model request requires connection verification again.

## Repository access

- **Automatic:** query the public Materials Project API when a key is connected.
  Continue through selected anonymous sources if there are too few distinct
  compositions with the application's required evidence and screening minimum.
  For dielectric questions, the public dielectric corpus precedes the bounded
  NOMAD sample. Each source record remains independent; properties are never
  joined across phases or releases. Keyless reference services remain available.
- **API:** use a verified Materials Project key when available. If the key is
  missing, locked or no longer verified, the application skips that API and
  continues with the other selected public sources. An API outage likewise
  leaves selected anonymous repositories and reference services available.
  Reports identify the unavailable source; unverified keys are never used.

Materials Project requests explicitly ask the server for numeric legacy IDs to
retain compatibility with existing evidence records. The one-record connection
probe uses the same bounded transport as scientific retrieval.

Requests use validated formula, chemical-system, element,
metallicity and available-property hints instead of a fixed composition list.
These are query preferences, never evidence supplied by the user.

### Broad discovery and exact comparisons

Examples do not normally close a discovery search to a short formula list.
For example, “Find nitride candidates such as GaN and AlN” searches the nitrogen
compound boundary; “Compare GaN and AlN” retains those exact composition hints.
“Only”, “restrict to”, and “limited to” directly before a composition list also
preserve that restriction. “Use only public sources” is an access instruction,
not a formula restriction. A direct composition question such as “Research GaN”
also retains the formula. This bounded text parser does not extract numerical
property facts or new adapter operators from the question.

Explicit composition classes take precedence over an older profile's oxide
default. Oxides, nitrides, carbides, sulfides and other supported element-defined
inorganic classes use their corresponding element boundary. “Metal oxides” does
not assert metallicity. Generic metals and semiconductors request the separate
metallicity field only where the adapter can verify it; NOMAD's reviewed band-gap
field alone does not establish either class. A selected profile supplies a class
default only when the prompt does not name one.

An explicit alloy request adds a requirement for at least two distinct elements;
an explicit pure or elemental metal request requires one. General metal requests
and comparisons of pure metals with alloys keep both scopes available. Explicit
formula and chemical-system hints remain intact. The Materials Project query
uses the supported `nelements_min` and `nelements_max` bounds documented in its
[summary client](https://materialsproject.github.io/api/_modules/mp_api/client/routes/materials/summary.html).
The application also checks validated returned formulas independently, including
public identity records. Other adapters receive only their supported query fields.
Element count is a necessary composition screen, not proof of an alloy phase,
processing route or mechanical performance.

These boundaries are composition preferences, not proof of oxidation state,
structure type or application suitability. Broad alternatives such as “oxides
or nitrides” cannot be represented by the current element-AND filter and remain
reference-only unless an explicit formula comparison specifies the scope.
Generic ceramics/halides, polymers, composites, perovskites, quantum dots and
other classes requiring richer structure or scale evidence are not relabeled as
oxide bulk materials to produce a quantitative shortlist.

### Quantitative sample size

The quantitative NOMAD adapter requests one page of up to **100 records**,
independently of the **1–10 reference cards per source** setting. It retains the
same fixed public endpoint, 1 MB transport limit, 12-second request deadline and
shared repository time budget. Pagination cursors are not followed. A simple
composition preference orders that page by the repository's distinct-element
count; this is a sampling order, not a performance ranking. Single-element class
boundaries require a compound with at least two distinct elements; explicit
elemental formula queries remain possible.

Audit metadata separates received, rejected and validated records. It also
records the page limit, whether that limit was reached, the provider's total
query matches when supplied, and whether additional matches were omitted.
An absent total leaves completeness unknown. Provider totals count query records,
not validated evidence or distinct materials. A sampled record can still have
missing or conflicting properties; no extra measurements are inferred to fill
the shortlist. The API's public scope and pagination behavior are described in
the [NOMAD API guide](https://docs.nomad-lab.eu/develop/howto/manage/program/api.html).

No normal application mode selects a bundled candidate cohort. The optional
historical dielectric corpus is an explicitly selected public source, fetched
and validated anew; its version and age remain visible. A source outage never
substitutes the bundled historical test fixture. Old saved reports retain their original
content and provenance. Any retained scientific fixtures serve explicit tests,
not new research outputs. See the [API documentation](https://docs.materialsproject.org/downloading-data/using-the-api/querying-data).

The [public dielectric adapter](public-dielectric-dataset.md) scans all 1,056
rows in its approved release before filtering and ranking. It is specialized
coverage, not a general database for polymers or every material family. A
candidate's novelty, experimental adoption and application performance are not
inferred from its name or presence in this corpus; these need independent
public evidence. The [ranking guide](ranking.md) describes the configurable
minimum-gap preference, evidence coverage and twelve-composition shortlist.

## Follow up on missing properties

After repository retrieval, selected attributes without usable evidence become
separate search requests. Retrieved candidate formulas can narrow these searches;
if there are no candidates, bounded topic hints guide discovery without asserting
that any material has a particular property. Zero-weight attributes are not queued.

When selected stability evidence is missing, one of the three bounded follow-up
slots is reserved for it. Ambient phase stability takes precedence, then
operational stability, then thermodynamic stability. Searches cover the
corresponding stability conditions; the returned passages remain unscored review
leads and cannot establish stability without further evidence validation.

When public search and Europe PMC are enabled, the application searches the
open-access collection and reads available article XML. It keeps matching passages
with article links, section locations, retrieval provenance and explicit review
status. Full-text access, relevant text and useful numerical coverage are separate
outcomes: an accessible paper need not contain a usable property value.

If OpenAlex is also selected, a failed Europe PMC search can fall back to its
existing public-abstract adapter. A confirmed outage earlier in the same run
can skip the failed provider. An empty search is not an outage: other requested
criteria get their first search before an empty result uses a remaining slot
for OpenAlex. Selecting OpenAlex alone also permits abstract follow-up. Abstract
queries use bounded plain criterion, target and application terms rather than
Europe PMC query syntax or concatenated candidate alternatives.

Both providers share the original three-search, six-reference and fifteen-second
limits, with at most six article downloads. A fallback consumes a search slot;
it does not add a retry budget or a model call. Only enabled providers run, and
preprint settings still apply. OpenAlex open-access status is index-reported;
its abstracts are explicitly marked as abstracts, with no publisher download or
full-text claim. Previously retained index abstracts stay unchanged when the same
work appears again. Relevant retained text is offered before the second assessment
pass, within the shared document and reply-size limits.

These passages are **review leads**, not values copied automatically into a ranked
record. A paper may describe a different phase, temperature, sample, calculation
method or measurement convention. Values cannot be merged across those contexts
without validation. Unavailable text, unmatched attributes and request limits stay
visible. These adapters are bounded and do not skim every public website.
Other publication services do not supply targeted body-text follow-up. No paywall
is bypassed.

Titles and article passages are screened for instruction-like content, including
role spoofing, hidden formatting controls, tool/credential requests and attempted
evidence promotion. Rejected passages are counted in source metadata; accepted
passages remain literal review text, never agent instructions or scored evidence.
This screen is supplemental: fixed adapters, typed evidence and isolated agent
tools enforce the boundary even when a phrase detector misses an attack.
Repeated database identities are rejected instead of selecting or combining
potentially conflicting versions. Public availability alone does not establish
scientific reliability; method comparability and preprint status stay explicit.

## Read and reuse results

Summaries and Technical Views distinguish scored material evidence from
public references. Discovery records carry `kind: discovery_reference` and
`is_material_evidence: false`; they cannot change measured-property scores or
eligibility. Their exact passages can support separately labeled provisional
literature assessments. Identity,
public URL, retrieval provenance and metadata stay associated when pinned or
moved with a chat. Article records whose text was actually read are marked
separately from metadata-only references. Exact passages are retained in the
Technical View, while the Summary reports the outcome of the follow-up.

A question without verified quantitative records can produce a **provisional
literature shortlist** when retrieved passages support candidate-specific
criterion assessments. The [literature ranking guide](literature-ranking.md)
explains the separate fit calculation, uncertainty and preserved quotations.
Unassessed mentions alone do not receive a performance score. If discovery is
disabled, unavailable or returns no matching resources, the report explains the
gap without inventing evidence. A ranking profile expresses preferences, not
source coverage or scientific truth.

`GET /api/source-settings` and `PUT /api/source-settings` manage the supported
source preferences. They do not accept arbitrary URLs, private sources, paywall
bypasses or inserted scientific evidence. Prompt requests to cross those boundaries
stop before model or public-source calls.
