# Historical public evidence test fixture

`mp_dielectric_snapshot.json` contains genuine, unchanged scalar fields from
20 historical Materials Project-derived phase records. It is test input only.
Production research never loads this file or falls back to these candidates;
old saved reports remain readable. It is not a current or comprehensive
Materials Project database export.
No record was invented for the application. No per-material stability values
were joined from another release or inferred from the publication's selection
criteria. Compound hazard and thin-film performance remain unassessed.

The original authors describe the calculated structures and dielectric results
and their integration with Materials Project in [Petousis et al., Scientific
Data 4, 160134 (2017)](https://www.nature.com/articles/sdata2016134).
The paper is freely readable under CC BY 4.0. The data are calculated using
DFPT with GGA/PBE(+U); `poly_total` and `poly_electronic` report means of tensor
eigenvalues, not thin-film measurements. The original dataset is
[Dryad: High-throughput screening of inorganic compounds for the discovery of
novel dielectric and optical materials](https://doi.org/10.5061/dryad.ph81h).

## Reuse and attribution

The [Dryad dataset metadata](https://datadryad.org/api/v2/datasets/doi%3A10.5061%2Fdryad.ph81h)
explicitly lists CC0-1.0 for the original data. The public
[Figshare mirror metadata](https://api.figshare.com/v2/articles/7108790)
explicitly lists MIT for **Dielectric Constant Data**, version 2, published
2018-10-08. These license declarations and the freely readable source paper were
checked on 2026-09-09 before bundling. The [versioned mirror
DOI](https://doi.org/10.6084/m9.figshare.7108790.v2) is the source cited for each
snapshot record. This does not imply a license for unrelated Materials Project
content or future API responses. Live API records are used only for requested
reports; no current API database is redistributed as part of this snapshot.

Attribution: Ioannis Petousis, David Mrdjenovich, Eric Ballouz, Miao Liu,
Donald Winston, Wei Chen, Tanja Graf, Thomas D. Schladt, Kristin Persson,
Fritz B. Prinz, and Hacking Materials, as credited by the source repositories.
The mirror adapts the original data into the matminer dataset format.
The mirror's MIT permission notice is retained in `LICENSE-MIT.txt`.

## Reproduction

The [matminer dataset documentation](https://hackingmaterials.lbl.gov/matminer/dataset_summary.html#dielectric-constant)
and [dataset metadata](https://github.com/hackingmaterials/matminer/blob/master/matminer/datasets/dataset_metadata.json)
identify the downloadable artifact and expected SHA-256:

- Source artifact: `https://ndownloader.figshare.com/files/13213475`
- Source SHA-256: `8eb24812148732786cd7c657eccfc6b5ee66533429c2cfbcc4f0059c0295e8b6`
- Bundled snapshot SHA-256: `4d1d6f4ee3153199822420a6599c80e300052454e71003badf541c3d8dbf8a4e`

From a source checkout, run `python src/labcat/science/rebuild_snapshot.py`
to download that fixed public artifact and reproduce the snapshot. This
maintainer utility is not an agent tool. A mismatched upstream checksum stops
extraction and requires a source review. Extraction selects every original row
whose formula matches the explicit oxide cohort in that file; it does not
select phases by desirable property values. Missing cohort formulas remain
listed as absent. No lattice structures, free-text metadata, or source-provided
instructions are bundled.

Every record retains its original row index, original full-row canonical JSON
SHA-256, copied scalar-field SHA-256, and unchanged copied fields. The snapshot
loader checks its pinned file checksum and every copied-field checksum. The
original compressed file is required to independently recheck full-row hashes;
it is downloaded by the reproduction utility, not bundled. Hashes establish
byte identity and reproducibility, not semantic truth or experimental validity.

## Scoring boundary

Only the adapter creates material facts. User text and model output can choose
bounded intent/preferences, never property values, citations, identities, URLs,
or new tools. Raw importance values are user preferences, normalized over all
selected criteria, including unavailable ones. Missing/unsupported data score
zero without redistribution. The selected implemented utilities and their anchors
are reported in each audit. Cell site count is not formula complexity;
calculated gaps, dielectric response, and hull energy are separate properties.
The element-exclusion list is an incomplete application policy, not a claim
that any surviving compound is non-toxic. This historical test cohort does not constrain current live queries or define
the supported application scope.
