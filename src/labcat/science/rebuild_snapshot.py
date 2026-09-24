"""Maintainer-only extraction of a checksum-pinned, publicly licensed
dataset.

Run from the repository root with ``python -m
labcat.science.rebuild_snapshot``. This is not an agent tool. It
downloads only the fixed public artifact below.
"""

import gzip
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

UPSTREAM_URL = "https://ndownloader.figshare.com/files/13213475"
UPSTREAM_SHA256 = "8eb24812148732786cd7c657eccfc6b5ee66533429c2cfbcc4f0059c0295e8b6"
COHORT = (
    "Al2O3",
    "BaTiO3",
    "BeO",
    "B2O3",
    "CaO",
    "HfO2",
    "LiAlO2",
    "LiBO2",
    "MgO",
    "MgAl2O4",
    "Nb2O5",
    "Sc2O3",
    "SiO2",
    "SrTiO3",
    "Ta2O5",
    "TiO2",
    "Y2O3",
    "ZnO",
    "ZrO2",
    "ZrSiO4",
)
FIELDS = (
    "material_id",
    "formula",
    "nsites",
    "space_group",
    "band_gap",
    "poly_electronic",
    "poly_total",
    "pot_ferroelectric",
)


def canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def extract(raw: bytes) -> dict:
    """Copy original scalar fields unchanged; omit free text and
    structural files."""
    if hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError(
            "Upstream checksum differs; review before updating the snapshot."
        )
    source = json.loads(gzip.decompress(raw))
    records = []
    for index, values in enumerate(source["data"]):
        row = dict(zip(source["columns"], values, strict=True))
        if row["formula"] not in COHORT:
            continue
        copied = {field: row[field] for field in FIELDS}
        records.append(
            {
                "upstream_row_index": index,
                "upstream_row_sha256": hashlib.sha256(canonical(row)).hexdigest(),
                "fields_sha256": hashlib.sha256(canonical(copied)).hexdigest(),
                "fields": copied,
            }
        )
    records.sort(key=lambda item: item["fields"]["material_id"])
    return {
        "schema_version": 1,
        "dataset": "Materials Project dielectric dataset / matminer public mirror",
        "dataset_version": "Figshare 7108790 version 2 (2018-10-08)",
        "source_url": "https://doi.org/10.6084/m9.figshare.7108790.v2",
        "upstream_url": UPSTREAM_URL,
        "upstream_sha256": UPSTREAM_SHA256,
        "upstream_record_count": len(source["data"]),
        "original_dataset_url": "https://doi.org/10.5061/dryad.ph81h",
        "publication_url": "https://www.nature.com/articles/sdata2016134",
        "mirror_license": "MIT",
        "original_data_license": "CC0-1.0",
        "license_checked_on": "2026-09-09",
        "cohort_formulas": list(COHORT),
        "selection": (
            "All rows whose original formula matches the fixed oxide cohort; "
            "no value-based selection."
        ),
        "absent_cohort_formulas": sorted(
            set(COHORT) - {r["fields"]["formula"] for r in records}
        ),
        "records": records,
    }


if __name__ == "__main__":
    with urlopen(UPSTREAM_URL, timeout=25) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Dataset exceeds the reviewed download size.")
    payload = json.dumps(extract(raw), indent=2, sort_keys=True, allow_nan=False) + "\n"
    target = Path(__file__).parent / "data" / "mp_dielectric_snapshot.json"
    target.write_text(payload, encoding="utf-8")
    print("Snapshot SHA-256:", hashlib.sha256(payload.encode()).hexdigest())
