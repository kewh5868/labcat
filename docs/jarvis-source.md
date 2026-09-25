# JARVIS public dataset feasibility

Status: inspected on September 10, 2026; **not integrated as a source adapter**.
The current release needs a separate bounded ingestion design before it can fit
the application's synchronous public-repository retrieval path. No candidates,
property values, cached fallback dataset or JARVIS source setting were added.

## Reviewed public release

The official JARVIS download documentation identifies its public 3D DFT dataset.
The independently retrieved Figshare version metadata identifies article
6815699, version 11, published May 9, 2026, with a CC BY 4.0 license. The reviewed
file is `jdft_3d-9-24-2025.json.zip`, file 64391379, with 48,447,610 bytes and
provider-reported MD5 `c3179161ef0d029cf1fa70da463aac6e`.
[Official downloads](https://jarvis-materials-design.github.io/dbdocs/thedownloads/),
[version metadata](https://api.figshare.com/v2/articles/6815699/versions/11),
[versioned dataset](https://figshare.com/articles/dataset/jdft_3d-7-7-2018_json/6815699/11).

The fixed anonymous download route is
`https://ndownloader.figshare.com/files/64391379`. Its observed single redirect
targets the exact HTTPS object path
`/pfigshare-u-files/64391379/jdft_3d9242025.json.zip` on
`s3-eu-west-1.amazonaws.com`, with the same six AWS signing parameters already
reviewed for the public dielectric reader. Temporary signed URLs were not saved
in documentation or provenance. No account credentials or proxy were used.

## Observed size and schema

The full anonymous transfer exceeded a 45-second probe cap on this host. This
does not establish typical download speed, and it does not establish that the
source is unavailable. It does establish that this probe could not finish within
the application's existing 30-second shared repository budget.

Two bounded byte-range reads succeeded: the last 131,072 bytes and the first
262,144 bytes. The ZIP directory declares one DEFLATE member,
`jdft_3d-9-24-2025.json`, containing **254,061,560 uncompressed bytes**. No files
were extracted. A bounded in-memory inflate of the beginning of the archive
allowed schema inspection of one JSON record. The full archive checksum was
not verified, so the partial record was not admitted as scientific evidence.

The inspected record includes `jid`, `formula`, `func`, `atoms`, `nat`, `density`,
`optb88vdw_bandgap`, `mbj_bandgap`, `hse_gap`, `bulk_modulus_kv`,
`shear_modulus_gv`, `ehull`, calculation cutoffs and convergence settings. Some
absent property fields are strings rather than numeric values. Direct source
density is available in the schema; a future adapter need not substitute atomic
mass constants merely to populate this property.

The official methodology documentation distinguishes exchange-correlation
methods and reports band gaps in eV and elastic moduli in GPa. Bulk and shear
fields suffixed `kv` and `gv` must retain their source averaging convention;
they must not be labeled as VRH values. Exact field definitions, missing-value
sentinels and dataset-wide consistency still need validation before ingestion.
[JARVIS DFT methodology](https://jarvis-materials-design.github.io/dbdocs/jarvisdft/).

## Conditions for a future adapter

An adapter would need all of the following before enabling retrieval:

- A separately reviewed transfer and memory budget, or streaming ingestion that
  does not construct the entire 254 MB JSON document as a Python object graph.
- Verification of the entire pinned artifact before admitting any row as
  evidence, with a reviewed SHA-256 in addition to the provider's MD5 metadata.
- Fixed-host, public-address-pinned transport with one exact redirect, no
  arbitrary source URLs, no credentials, and an explicit shared deadline.
- A bounded single-member ZIP reader, incremental JSON validation, duplicate-key
  rejection, finite numeric parsing, nesting and row limits, and failure on
  truncation or unsupported archive features. No extraction to paths supplied by
  the archive and no source object/class instantiation.
- Source-issued `jid` identities, exact calculation methods and units, and
  release, artifact, row and selected-field provenance. Source prose and links
  cannot authorize further retrieval or modify policy.
- Tests of malformed and oversized responses, redirects, decompression limits,
  unknown values, duplicate identities, composition filters and deadline failures.

Calculated crystal properties can support preliminary comparison of elemental
and compound phases. They do not establish processed-alloy performance, film
quality, compound safety or experimental metallicity. A calculated zero band gap
must remain a reported calculated value; it must not become a positive
`is_metal` classification without a separately reviewed source indicator.

Until that design and validation are complete, JARVIS remains a prospective
public source. Increasing global limits or silently substituting an older
release would not resolve the current feasibility result.
