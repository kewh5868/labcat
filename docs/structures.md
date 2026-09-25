# Crystal structures in saved reports

Use **View structure** beside a saved shortlist candidate to expand its structure
inside that table row. The inline panel works with Summary and Technical View;
it keeps the candidate and its ranking visible alongside JSmol and available CIF
downloads. Opening the row retrieves its one available record. If several records
are associated, choose one before retrieving its coordinates. **Hide structure**
closes the panel. Sources without a compatible adapter or a required connection
are labeled accordingly. Merely opening the report does not download coordinates.

The prompt composer includes **Find reference structures**, checked by default
in a new composer. This is a per-request choice, not a persistent global setting.
After an eligible completed or partial report has been saved, the optional
discovery step considers up to twelve literature candidates under one shared
eighteen-second budget. It uses selected HybriD³ and NOMAD sources, plus Materials
Project when its connection is verified and its mode permits API requests, and records
associations, without downloading atomic coordinates or changing the ranking.
Refusals do not start this discovery. A source outage preserves the saved report
and completed associations; unfinished or failed lookups remain available for
explicit retry in the candidate's inline panel.

Literature-based shortlists include historical reports without numeric property
rows. A directly cited, validated repository identity can supply a structure
record. A typed formula on an exact cited compound-identity record from NOMAD or
HybriD³ can resolve that record's own material name or alias. A whole literal
formula with multiple elements can also serve as a search hint when it contains
explicit numeric counts or properly cased two-letter element symbols, such as
`CdS`, `InAs`, or `ZnSe`. Implicit counts of one are valid; a digit is not required.
All-capital abbreviations such as `PI` or `NO` still need an independent identity
record. A complete parenthesized formula at the end of a compound label
also supplies a hint, including formulas with implicit counts of one. The name
before those parentheses is not thereby established as an alias. The hint creates
no scientific evidence: a compatible saved
numeric record or a newly returned approved repository record must independently
supply the composition and exact identity before it is attached. Existing numeric
properties and source provenance stay unchanged.

When the cited records provide one unambiguous formula, lookup first checks cited
HybriD³ systems for public crystallography datasets. Eligible composition lookups
can then inspect other HybriD³ systems, Materials Project or NOMAD, returning at
most three new reference records. MP searches retain response digests and the
fixed public request URL; structure retrieval revalidates the exact MP identity,
composition and non-deprecated status before accepting coordinates.
Multiple available records require a choice; the application does not silently
choose a phase among them.

Formula syntax in a publication's material name does not establish composition:
aliases can coincide with element symbols and numeric counts. Search hints never
authorize a phase or molecular-identity claim, and their full atom counts must
match the returned source formula without reducing to another ratio. Explicit atom counts
in a single-element molecular or cluster formula cannot authorize a cross-record
elemental search, even when a typed source formula is available or reports only
the elemental ratio. A composite expression is never flattened into a single
bulk composition, and a typed component formula is not substituted for the
complete target. Exact cited record downloads remain available. Descriptive
names are retained when their own cited compound record supplies a formula, with
morphology still unverified.

For a cited heterostructure label such as `CuInS2/ZnS` or `InP@ZnSe@ZnS`,
Labcat also looks up the individual components. Two or three literal, multi-element
formulas separated by `/`, its typographic variants, or `@` are supported.
Unicode subscripts and spacing before atom counts are normalized for lookup,
so `CuInS 2 /ZnS` works. Implicit-one formulas such as `ZnS` are permitted in
this component context. Alloy variables, fractional expressions, dopant notation,
blend abbreviations, single-element ratios and ambiguous names are not expanded.
The original candidate label, evidence and ranking remain unchanged.

Each component must independently match a public repository record with the
same complete composition before a structure is offered. Component references
appear together in the candidate's inline panel, with individual availability,
source records, JSmol viewing and CIF downloads. They are labelled **Component 1**,
**Component 2**, and so on: notation order alone does not establish core/shell
roles. These bulk reference structures do not represent the assembled interface,
particle shape or nanoparticle geometry, and do not supply new property evidence.
An exact cited candidate record remains available alongside its components.

All component discovery shares the original eighteen-second automatic-search
budget; a slow component gets only a share of the remaining time. Successful
siblings remain available if another component has no match or a source fails.
The panel permits retrying missing components without discarding already loaded
structures. Each component cache key binds the retained parent, citations and
literal component identity; reads and writes rederive that relationship rather
than accepting user- or model-supplied component formulas.
Named compound leads without a usable formula can use a bounded PubChem identity
lookup. It accepts one CID only when the exact requested name also occurs among
that CID's source-returned synonyms. The returned complete formula can then select
existing numeric records or approved repository structures. Public identity URLs,
response hashes and retrieval time are retained in a separate per-report receipt;
every passive read revalidates that receipt against the saved lead. A missing or
ambiguous identity does not supply a composition; no name-to-formula table or
model memory fills the gap. Negative lookups are cached and are not repeated when
opening a report or running automatic discovery. The candidate's inline panel
offers **Retry reference lookup** for an explicit new attempt. Names with explicit
composite, polymer or morphology qualifiers, including `poly(...)` notation,
remain outside this name lookup. This syntax filter is conservative; it does not
classify every chemical or polymer name. Existing exact cited repository records and numeric
shortlist structures remain available independently of literature references.

These are visibly labeled reference structures with **phase match unverified**.
Composition equality does not establish molecular identity, crystal phase,
sample, morphology, device form or measurement conditions. Reference associations
are cached separately for the saved report and revalidated against its retained
source-bound candidates and the current formula eligibility rule. Older
syntax-only lookup caches do not authorize untyped formula-hint associations;
new discovery must pass the current adapter checks. The cached files and saved
reports are not rewritten. Associations
do not add property measurements, alter scores or
update a pinned snapshot. Refreshing availability reads local metadata. The
optional post-report lookup and explicit reference-search actions contact public
repositories; expanding a row with one available record, or selecting a record,
requests its coordinates. A failed or empty search is not evidence that no
structure exists. An empty or failed lookup can be retried explicitly.

Four source-validated adapters are supported:

- Materials Project: one nondeprecated summary record with the same material ID.
  A verified source API connection is required. This uses the existing fixed-host,
  public-IP, TLS-verified, nonredirecting transport.
- NOMAD: one anonymously accessible, published, non-embargoed entry through the
  public archive API. The normalized `structure_original` is preferred. If that
  section is absent, the adapter can use only the specifically requested last
  system of the last recorded run. This choice appears in the structure caveats;
  it is not assumed to represent every calculation in the report.
- Public dielectric dataset: anonymous retrieval of the exact historical release
  and row used for ranking. The release digest, row digest, source formula and
  identity must match the saved provenance. The adapter passes only plain JSON
  into the existing numeric geometry validator; it never instantiates embedded
  object types or substitutes the current Materials Project structure. Missing
  periodicity flags use the release's explicit bulk-cell interpretation with a
  visible caveat. See [dataset scope and attribution](public-dielectric-dataset.md).
- HybriD³: a public atom-list dataset must match the saved system, publication,
  sample, method origin, crystal system and recorded conditions. Ambiguous
  matches, unsupported units and inconsistent composition return unavailable.
  If explicit atoms are absent, the adapter can inspect original CIF attachments
  from public atomic-structure datasets for that same source system and composition.
  Source metadata matches are distinguished from **composition-matched reference
  structures**, which may have different publications, samples, method origins or
  conditions. Neither classification establishes microscopic phase equivalence.
  A calculated band gap paired with experimental crystallography is always a
  reference structure. Public band-gap data alone do not establish a structure.

The other five registered services—Europe PMC, arXiv, Wikipedia, OpenAlex and
ChemRxiv via OpenAlex—supply literature or background records through their
current adapters. They have no approved structure-file retrieval route. This is
an unsupported capability, not evidence that a linked publication has no
supplementary structure files. A bibliographic citation cannot establish the
identity or phase of a downloadable structure, and external attachment links
are not automatically followed.

No arbitrary URL, uploaded file, user assertion, model-generated coordinate or
remote script can supply a structure. Unsupported structures are not replaced
with a familiar phase or demonstration file. Structures are limited to 2,000
sites in an ordered, fully occupied, three-dimensional periodic cell. Invalid
chemical symbols, inconsistent compositions, nonfinite coordinates, disordered
occupancy, degenerate or left-handed lattices and out-of-budget responses fail
closed. Left-handed cells are rejected rather than silently mirrored in a CIF.

The viewer receives only validated atom identities, numeric cell and coordinates.
NOMAD metre values are converted to angstroms and Cartesian positions
to fractional coordinates. The downloaded file is a **derived P1 CIF** containing
the full atom list, not an original source upload or a symmetry determination.
It records a fixed source link, retrieval time and the source-response SHA-256.
Remote prose, embedded scripts, file links and extra fields are discarded.

The opaque JSmol frame and its parent negotiate readiness in either startup
order, so a cached frame cannot permanently lose its initial ready message.
**Retry viewer** creates a new frame with the already validated CIF; it does not
repeat repository retrieval. Source caveats and file provenance remain available
below the viewer, while reference-phase uncertainty stays prominent above it.

For original HybriD³ CIFs, [Gemmi 0.7.5](https://pypi.org/project/gemmi/0.7.5/)
parses the attachment as inert data. Only the fixed numeric dataset `/files/`
endpoint is allowed, with verified public HTTPS and ZIP media type, no redirects
or credentials, and a 1 MB response cap. Archives are read in memory, never
extracted. Limits are 24 archive members, 4 MB declared total expansion, six CIFs,
1 MB per member, 32 blocks per CIF, 192 explicit symmetry operations and 2,000
expanded sites. Unsafe paths, symlinks, encryption and unsupported compression
are rejected. No arbitrary links in a CIF or dataset are followed.

HybriD³ structure matching reads up to four fixed pages of 12 datasets under one
shared 18-second deadline. All pages must be complete, consistent and free of
repeated dataset IDs before choosing a structure; provider pagination links are
never followed. The response digest includes every inspected page. Unsupported
condition expressions cannot establish matching measurement conditions; they
remain a stated difference for an otherwise validated reference CIF.

At most two equally close source subsets are inspected within that same
shared time budget. Closeness counts the explicitly listed metadata differences;
it does not measure scientific phase similarity. One supported CIF block must
uniquely match composition and the crystallography subset's crystal system.
The parser requires explicit atom species, finite cell/fractional values, unit
occupancy and source symmetry consistent with the cell. Unsupported blocks are
not combined or repaired with another structure. Explicit source symmetry is
expanded into the safe P1 viewer representation; no symmetry is inferred.

The original CIF bytes, filename, selected block, original-file digest and archive
digest are retained in the report-scoped cache. A separate **Download original
CIF** attachment preserves the entire source file, which may contain other
blocks. The viewer never loads that original text. **Download displayed structure**
exports only the validated selected block's expanded geometry. Reference structures
display a prominent label, recorded differences and a separate crystallography
source link; they never alter the property report, ranking or pinned snapshot.
Original downloads currently require a uniquely validated geometry block. An
accessible attachment with unsupported geometry or ambiguous composition/phase
does not receive a download link. This differs from switching off the JSmol
viewer, which preserves both supported download types.
Gemmi is pinned in the web extra and hash-locked for the container; its upstream
MPL-2.0 license applies. Platform wheels exist for macOS, Windows and Linux,
including Linux amd64/arm64; wheel availability is not execution-test coverage.

Retrieval is limited to two simultaneous structure operations, with bounded
adapter requests and the existing source byte/time limits. A validated
representation is cached against the report and material ID in the workspace
database. Reopening or downloading it does not repeat research or change scores.
The file is regenerated from validated numeric data on access; a cache checksum
and composition check detect corruption. Moving a chat retains its structures;
removed reports cannot expose them, restoration makes them accessible again,
and permanent report deletion removes the cached rows through foreign keys.

The source may change between report creation and structure retrieval. Matching
the source entry and composition does not prove phase equivalence to every
property in the ranking. The UI preserves this caveat along with the source and
retrieval timestamp. Viewer bonds are illustrative, not additional evidence.

HybriD³ retrieval distinguishes a source with no atomic-structure datasets,
ambiguous matches, an incomplete bounded search, unsupported geometry and a
failed public request. Its transport failures and NOMAD public-request failures
remain retryable and never become a claim that the structure is absent.
Materials Project and the public dielectric adapter retain a combined
unavailable-or-invalid diagnostic for failures not otherwise classified.
NOMAD archive access flags must explicitly
confirm publication and no embargo even when the search index advertises public
access; inconsistent source metadata is refused. These outcomes retain the
saved report and never cache a substitute structure.

Developer Settings can disable the JSmol viewer through `viewer_enabled`.
Structure retrieval and CIF downloads remain available. The user edition applies
the installed setting but does not expose the developer mutation endpoint.

## Viewer isolation

JSmol 16.4.23 is bundled locally and runs in an iframe with scripts enabled but
without same-origin privileges. Its separate content-security policy permits
only the bundled viewer runtime; it cannot contact research sites, application
APIs or credential endpoints. The main application's policy is unchanged. A
narrow, credential-free asset preflight supports the JavaScript runtime in this
isolated frame. Disabling the viewer also disables its asset routes.

The frame accepts only the application's canonical numeric CIF representation.
It checks the parent window and a per-mount channel, strips comments and rejects
arbitrary CIF fields, scripts and URLs. Controls expose fixed reset and rotation
actions. Remote file loading, script entry and the JSmol context menu are not
available. Matching source code, licenses and attribution accompany the bundled
runtime; see [JSmol source packaging](jsmol-source.md).

## Protocol references

- [NOMAD public API ownership and archive queries](https://docs.nomad-lab.eu/develop/howto/manage/program/api.html)
- [NOMAD normalized structure schema and units](https://github.com/FAIRmat-NFDI/nomad/blob/develop/nomad/datamodel/results.py)
- [Materials Project summary queries](https://docs.materialsproject.org/downloading-data/using-the-api/querying-data)
- [JSmol reference](https://chemapps.stolaf.edu/jmol/jsmol/jsmol.htm)

Unit tests use an explicitly identified, anonymously retrieved NOMAD archive
fixture and synthetic MP protocol data. Neither is a product result or fallback.

## Live validation scope

On 2026-09-10, all four implemented structure adapters had successful live
public-source checks. Candidate identities were independently retrieved before
requesting their structures. The checks covered these bounded samples:

| Adapter                   | Successful checks | What was verified                                                                                                                                                        |
| ------------------------- | ----------------: | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Materials Project         |                 3 | Current API coordinates were converted into derived CIFs and parsed in memory. This was not an original-file download or a browser download test.                        |
| Public dielectric dataset |                 3 | Exact-release structures produced saved, parseable derived CIFs.                                                                                                         |
| NOMAD                     |                 1 | A freshly indexed entry and current public archive produced a saved, parseable derived CIF.                                                                              |
| HybriD³                   |                 3 | One public atom list produced a derived CIF; two original CIF attachments were downloaded and preserved, with separate derived exports and composition-reference labels. |

This verifies a successful path for every implemented structure adapter, not
every source record or every accessible file. Other checked records had absent
attachments, ambiguous matches, inconsistent access flags or provider rate
limits. The checks exercised Python adapters and CIF parsing on macOS; they do
not establish browser/native-viewer behavior, container or other-OS coverage.
The five literature/background services listed above have no implemented
structure route and were not counted as failed downloads.

When an unlocked Materials Project key is saved, the first explicit research or
structure request verifies it again after a backend restart. The key is sent
only to the fixed Materials Project API endpoint. Passive report/status reads do
not probe it. Concurrent requests share one bounded verification attempt; a
failed attempt retains other public-source results and can be retried from
Connections. A locked or absent key remains unavailable. Disabling Materials
Project suppresses its automatic lookup.

The report uses one application-based candidate shortlist when literature
assessments are available. Separately scored database rows appear under
**Supporting property records** in the collapsed analysis details. Their ranking
is not a second application recommendation. Compatible records can supply inline
reference structures to the main candidates without copying property values,
merging phases, or silently reranking the saved report. Technical View discusses
each candidate, includes bounded cited source context, and compares the leading
three candidates; source-specific arithmetic remains in the analysis details.

### Written chemical names

Formula-only shortlist rows can show a smaller, source-linked chemical name in
both Summary and Technical View. Validated saved source names are shown first.
An optional lookup checks an exact public PubChem formula synonym and its
separate name record: both records must identify the same single CID and the
same complete, unreduced formula.

Selected Europe PMC or OpenAlex public abstracts provide a fallback only when
they explicitly pair a written chemical name with the complete formula. For
simple binary formulas, lexical chemistry terms narrow the Europe PMC query so
short strings are less likely to retrieve unrelated abbreviations. These query
hints never generate a displayed name or establish scientific evidence. This
literature fallback has priority over a broader PubChem formula search, which is
attempted only with the remaining time and accepted only for a single CID. The
first record from an ambiguous formula search is never selected automatically. Organic
isomers, ambiguous records, mixtures and unsupported names remain unlabelled.
Public abstracts may be indexed even when the full article is not open; this
lookup does not retrieve restricted full text.

A cited two- or three-component formula label such as `InAs/ZnSe` can show each
component's independently validated name and source beneath the original label.
Missing names do not suppress names found for the other components. The display
preserves component order without assigning core/shell roles or inventing a name
for the assembled heterostructure. Ambiguous acronyms and unsupported composition
notation are excluded.

Names identify a composition, not a verified crystal phase or suitability.
This display metadata does not change saved evidence, candidate scores or the
original report. Clicking a name opens its naming source. The process-local
cache is bounded to 256 entries (24 hours for a name; five minutes for a miss).
A report lookup has a 12-second total budget and up to 12 unique formula lookups,
with at most three running at once; repeated component formulas share one lookup.
At most two report lookups can use the network concurrently. A failed lookup
never blocks a report or suppresses other completed names. Selected-source
settings control new literature lookups. Presentation reads alone do not query
sources.
