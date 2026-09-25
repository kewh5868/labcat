# Public dielectric dataset connection

The anonymous dielectric connection downloads a fixed public release afresh and
examines every row before applying the current composition filters. It does not
load the bundled historical test fixture, select a named material cohort, or
substitute saved candidates when the source is unavailable. The ranker receives
all matching records and applies the selected ranking profile afterward.

## Source and interpretation

The source is **Dielectric Constant Data**, Figshare article 7108790, version 2,
published October 8, 2018. Its metadata identifies file 13213475 and an MIT
license. The original dataset is attributed to Petousis and colleagues; its
Dryad metadata declares CC0. Attribution and the mirror's permission notice are
retained in [the data documentation](../src/labcat/science/data/README.md).
[Versioned mirror](https://doi.org/10.6084/m9.figshare.7108790.v2),
[mirror metadata](https://api.figshare.com/v2/articles/7108790/versions/2),
[original Dryad data](https://doi.org/10.5061/dryad.ph81h).

Matminer documents 1,056 calculated structures and the field definitions. The
adapter copies the reported band gap, total and electronic dielectric scalars,
refractive index, cell volume, site count, space-group number and potential
ferroelectricity flag. The dielectric scalars average tensor eigenvalues;
cell volume is per calculation cell in cubic ångströms.
[Matminer dataset documentation](https://hackingmaterials.lbl.gov/matminer/dataset_summary.html#dielectric-constant).

The study uses DFPT calculations with GGA/PBE(+U). These are historical bulk-phase
calculations, not current database values or experimental thin-film measurements.
Band gaps are reported in eV. The adapter does not infer hull energies, compound
safety or film performance from the publication's selection criteria. Anisotropy,
phase dependence and calculation limitations remain caveats.
[Open-access study](https://pmc.ncbi.nlm.nih.gov/articles/PMC5315501/).

## Transport and validation

Only `https://ndownloader.figshare.com/files/13213475` is requested. One redirect
is permitted to the exact reviewed HTTPS object path on
`s3-eu-west-1.amazonaws.com`; only the expected S3 signing parameters are accepted.
The temporary signed URL is not returned, logged or stored as provenance. No
cookies, account credentials, environmental proxy or arbitrary URL is used.
Every host resolves to public addresses before a socket connects to that checked
address, with certificate verification and TLS hostname validation preserved.

Limits are 1 MB compressed, 8 MB uncompressed, 1,056 rows, 32 JSON nesting levels,
500,000 JSON nodes, and 18 seconds within any shorter shared repository deadline.
The reader validates a single complete gzip stream, an exact column schema,
unique JSON object keys, finite numeric tokens and integer row indices. It treats
serialized structures as plain JSON, never as Python/pickle/MSON objects.

The compressed artifact must match SHA-256
`8eb24812148732786cd7c657eccfc6b5ee66533429c2cfbcc4f0059c0295e8b6`.
A changed upstream file fails closed until reviewed. This expected checksum and
URL are also published in
[matminer's dataset metadata](https://github.com/hackingmaterials/matminer/blob/master/matminer/datasets/dataset_metadata.json).
Hashes identify bytes and release provenance; they do not prove scientific truth.

## Filters, identities and structures

`retrieve_live(filters=None)` returns `(records, metadata)`. Formula, chemical
system, required elements, excluded elements and original `material_ids` filters
are applied together. Formula matching compares composition ratios but leaves
the reported formula and amounts unchanged. `has_props=dielectric` requires a
validated dielectric scalar. `prefer_simple=true` orders the full result by
element count without truncation. Metal classification, elasticity and NOMAD
entry-ID filters are unsupported and fail explicitly. No supplied filter is
silently discarded or treated as factual evidence.

Each identity is `dielectric:mp-N`; its original `mp-N` is retained separately.
It is not interchangeable with a current Materials Project API record. If an
original identifier occurs in multiple rows, all such identities gain their
immutable `:rowINDEX` suffix, independent of filtering. Provenance includes the
dataset version, download hash, row index, canonical full-row hash, and validated
scalar-field hash. Invalid scalar fields become unknown, without copying their
untrusted text into reports. Source prose, CIF text and serialized structures
are excluded from scalar research records.

The separate internal `retrieve_structure_source` helper fetches the same exact
release and returns untrusted plain structure data with matching row provenance.
It does not produce a file or authorize viewing. The structure service must
validate identity, composition and numeric geometry before exposing a viewer or
download, and must not instantiate source-provided classes.
