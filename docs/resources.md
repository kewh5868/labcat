# Public resources and research evidence

Labcat combines material records with public literature to help compare candidates
for an application. The sources below are supported integrations; availability and
property coverage vary. A model account or API key is separate from a materials
database connection. See the [illustrated setup guide](first-run.md) for connecting
accounts and the [user guide](user-guide.md) for choosing research priorities.

## Accounts and API keys

**Materials Project is optional and requires its own API key.** Obtain it from your
[Materials Project dashboard](https://next-gen.materialsproject.org/dashboard),
following the [official API instructions](https://docs.materialsproject.org/downloading-data/using-the-api/getting-started).
Without a verified key, Labcat can use the selected anonymous sources below.
Connecting a key adds coverage; it does not guarantee a record or structure for
every candidate.

Labcat's other public-source adapters do not require a key in the application.
OpenAlex and ChemRxiv discovery use OpenAlex's
[limited anonymous access](https://help.openalex.org/api/authentication/).
Provider rate limits or outages can reduce results. Model-provider credentials
are used for planning and interpretation, not as credentials for these databases.

## Connected public resources

| Resource                                                                    | What Labcat uses it for                                                                                                                                                                   | Access in Labcat |
| --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| [Materials Project](https://materialsproject.org/)                          | Computed material records, supported properties such as band gap, dielectric response and elastic moduli, and crystal structures.                                                         | API key          |
| [Public dielectric dataset](https://doi.org/10.6084/m9.figshare.7108790.v2) | Calculated band gaps, dielectric scalars and structures from a versioned historical release, retrieved and checked for each search. This is separate from the live Materials Project API. | No key           |
| [HybriD³](https://materials.hybrid3.duke.edu/)                              | Crystalline organic–inorganic materials: compound identities, supported band-gap datasets and available crystallographic files.                                                           | No key           |
| [NOMAD](https://nomad-lab.eu/)                                              | Published, non-embargoed material records; supported composition, band-gap and structure fields.                                                                                          | No key           |
| [Europe PMC](https://europepmc.org/)                                        | Open-access publication discovery and selected article passages relevant to missing properties.                                                                                           | No key           |
| [arXiv](https://arxiv.org/)                                                 | Preprint metadata and abstracts for literature discovery. Preprints are not treated as verified measurements.                                                                             | No key           |
| [OpenAlex](https://openalex.org/)                                           | Scholarly metadata, available abstracts and reported open-access locations. Labcat does not download publisher full text through this adapter.                                            | No key           |
| [ChemRxiv](https://chemrxiv.org/) via OpenAlex                              | Chemistry preprint references with an indexed open location at ChemRxiv.                                                                                                                  | No key           |
| [Wikipedia](https://en.wikipedia.org/)                                      | Background introductions and discovery context; never a source of scored property values.                                                                                                 | No key           |
| [PubChem](https://pubchem.ncbi.nlm.nih.gov/)                                | Public chemical-name and identity checks. This helper does not supply ranked properties or crystal structures.                                                                            | No key           |

Searches are bounded rather than exhaustive. Reports retain source links and
identify missing data. Public availability does not establish peer review or
make results from different phases, samples and measurement conditions comparable.

## Understanding the comparison

A ranking profile expresses the properties you care about and their relative
importance. It cannot create measurements that a source does not report.

- **Screening priority** summarizes cited application evidence and criterion
  assessments. It helps decide what to review next; a percentage is not a
  probability of successful performance.
- **Property evidence** preserves supported source values and their context.
  Calculated and experimental values remain distinguishable. Missing properties
  receive no evidence credit and remain visible.
- **Reference structures** may match composition without matching the phase or
  conditions of a cited device. Component structures in a core–shell system are
  not an assembled interface model. Available CIF files retain their provenance;
  an unsuccessful lookup does not establish that no structure exists.

## JSmol acknowledgement

Labcat uses **JSmol 16.4.23** for its interactive crystal-structure viewer. Following
the project's [citation guidance](https://wiki.jmol.org/index.php/Main_Page#How_to_cite):

> JSmol: an open-source HTML5 viewer for chemical structures in 3D.
> [JSmol project documentation](https://wiki.jmol.org/index.php/JSmol).

The unmodified runtime is distributed under **GNU LGPL 2.1 or later**. The
[attribution notice](https://github.com/kewh5868/labcat/blob/main/third_party/JSMOL-NOTICE),
[license](https://github.com/kewh5868/labcat/blob/main/third_party/JSMOL-LICENSE)
and [source-distribution details](https://github.com/kewh5868/labcat/blob/main/docs/jsmol-source.md) accompany Labcat. JSmol renders
retrieved geometry; its illustrative bonds do not add scientific evidence.
