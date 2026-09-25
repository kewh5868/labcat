# Public discovery coverage

Choose public sources in **Search Criterion**. New workspaces enable the eight
supported anonymous services; existing saved selections stay unchanged. No data
API key is required for these bounded searches. The separate language-model
connection is still required for research in the application.

| Service                   | Retrieved content                                                                                                                                           | Limits                                                                                       |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Public dielectric dataset | A freshly retrieved versioned property corpus                                                                                                               | Calculated gaps and dielectric scalars; no measured thin-film performance                    |
| HybriD³                   | Public compound identities and scalar band-gap datasets                                                                                                     | Separate dataset/subset, method and phase provenance; no assumed processability or stability |
| NOMAD                     | Published, non-embargoed material records                                                                                                                   | Only supported validated repository fields can enter ranking                                 |
| Europe PMC                | Open-access references; targeted missing-property follow-up can retrieve bounded article XML passages                                                       | Passages remain unscored review leads; phase and measurement applicability are unverified    |
| arXiv                     | Preprint titles, public abstracts and links                                                                                                                 | No full-text or peer-review verification                                                     |
| Wikipedia                 | Public article introductions                                                                                                                                | Background context only, never scored property evidence                                      |
| OpenAlex                  | Scholarly metadata and available public abstracts for discovery and bounded missing-property follow-up, with reported open locations, versions and licenses | Open-access status is reported by the index; publisher full text is not retrieved            |
| ChemRxiv via OpenAlex     | Records with an open location in the indexed ChemRxiv repository                                                                                            | Preprint leads; no direct ChemRxiv scraping or peer-review verification                      |

The encyclopedia adapter uses the fixed
[MediaWiki search API](https://www.mediawiki.org/wiki/API:Search), requests only
article namespace zero and plain-text introductions, and retains canonical
article links. It does not follow arbitrary links. Scholarly discovery uses
[OpenAlex anonymous queries](https://help.openalex.org/api/authentication/), with
small result limits and fixed filters. Returned
[open locations and versions](https://help.openalex.org/data/locations/) remain
provider-reported metadata, separate from an actually retrieved article body.
ChemRxiv references must identify the exact indexed repository; other open
locations do not meet that adapter's condition.

All three newer adapters keep references outside scientific candidate properties
and scores. A matching title or introductory passage does not prove a material's
suitability. Search hints, source text and pasted URLs cannot grant tool access or
create evidence. Strict relevance checks may omit broad introductions and related
papers; an empty result is reported without substituting invented material data.

Accepted research starts with broad queries to the selected public indexes.
Detailed ranking requirements are not all joined into one restrictive search.
The next stage reads quantitative repositories and validates candidate identities,
units and values; finally, selected missing attributes receive targeted literature
queries. General-reference metadata never becomes a measurement. Publicly
retrieved HybriD³ identities can guide subsequent repository work. Up to six
literal formulas from validated source fields, titles or read Wikipedia excerpts
can also guide short supplemental repository queries. These leads retain their
citations and never supply properties; the original broad query still runs.
Retrieval remains open to other matching systems. An unsupported material class
does not receive unrelated bulk or hybrid candidates.

Goose may choose a bounded class/application search phrase and select literal
material names in the retrieved documents. Labcat revalidates each document's
source identity and each exact name/quote match. The result is a separate
**source-grounded candidate list**, with linked passages, missing criteria and
unverified suitability. Review order is not a performance score. The model
cannot turn its memory, the user's numbers or a source's instructions into
measurements. There is no automatic filling of Goose's candidate list with
arbitrary formula tokens from background text.

OpenAlex abstracts are reconstructed only from bounded, contiguous position
maps using its documented [abstract index format](https://help.openalex.org/data/works/attributes/).
Missing or malformed abstracts remain absent. Article text is still untrusted;
retained passages do not independently verify the article's conclusions.

Disabling **Preprint references** in Developer Settings prevents arXiv and
ChemRxiv requests. OpenAlex and Europe PMC also filter requests and validate the
returned publication type or version. Unknown types are omitted when preprints
are disabled. Europe PMC rechecks the article type before retaining downloaded
passages. These checks do not independently certify peer review.

ResearchGate scraping is unsupported. There is no arbitrary publisher crawler,
closed-account access, paywall bypass or automatic following of external download
links. Unavailable endpoints, rate limits and missing metadata remain explicit.

## Reference structures

The prompt's **Find reference structures** checkbox starts checked. After an
eligible completed or partial report is saved, a bounded lookup can associate
its shortlisted candidates with public repository structures. This automatic
step uses only selected HybriD³ and NOMAD sources: it checks a cited compound's
structure datasets first, then eligible composition references. Up to twelve
leads share an eighteen-second budget. It finds record associations; atomic
coordinates are retrieved when the user opens a candidate's structure.

The lookup requires an unambiguous formula from a validated, cited compound
record. A material name in a publication or the model's proposed formula cannot
authorize a composition search. A cited source match is distinguished from a
composition reference, and neither proves the same phase, sample or device as
the report's evidence. Empty or failed lookups retain the report and any completed
associations; no demonstration structures or fabricated coordinates are supplied.

Use **View structure** within a shortlist row for the inline JSmol viewer and
available CIF downloads. When several records are available, choose one before
retrieving it. Explicit lookup retries remain available.
