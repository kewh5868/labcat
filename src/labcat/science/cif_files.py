"""Inert, bounded CIF parsing from an adapter-owned public dataset ZIP.

No archive is extracted and no CIF text is sent to a viewer or model.
Only validated coordinates expanded with the file's explicit symmetry
leave this module as geometry. The original file is retained solely for
an attachment.
"""

import base64
import hashlib
import io
import math
import re
import stat
import zipfile
from collections import Counter
from pathlib import PurePosixPath

from .preferences import composition_key

MAX_CIF_BYTES = 1_000_000
MAX_EXPANDED_BYTES = 4_000_000
MAX_MEMBERS = 24
MAX_CIFS = 6
MAX_BLOCKS = 32
MAX_SITES = 2000
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:\(\d+\))?(?:[eE][+-]?\d{1,3})?")


def _scalar(raw):
    if not isinstance(raw, str) or len(raw) > 40 or not _NUMBER.fullmatch(raw):
        raise ValueError("Missing or nonnumeric CIF coordinate.")
    number = float(re.sub(r"\(\d+\)", "", raw))
    if not math.isfinite(number) or abs(number) > 1_000_000:
        raise ValueError("Unsupported CIF numeric range.")
    return number


def _geometry(block, formula, crystal_system):
    import gemmi

    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", block.name):
        raise ValueError("Unsupported CIF block name.")
    cif_formula = gemmi.cif.as_string(block.find_value("_chemical_formula_sum") or "?")
    if composition_key(cif_formula.replace(" ", "")) != composition_key(formula):
        raise ValueError("CIF block composition differs from the source identity.")
    cell_values = [
        _scalar(block.find_value(tag))
        for tag in (
            "_cell_length_a",
            "_cell_length_b",
            "_cell_length_c",
            "_cell_angle_alpha",
            "_cell_angle_beta",
            "_cell_angle_gamma",
        )
    ]
    if any(not 0.1 <= x <= 1000 for x in cell_values[:3]) or any(
        not 0 < x < 180 for x in cell_values[3:]
    ):
        raise ValueError("Unsupported CIF cell.")
    tags = [
        "_atom_site_type_symbol",
        "_atom_site_fract_x",
        "_atom_site_fract_y",
        "_atom_site_fract_z",
        "_atom_site_occupancy",
    ]
    columns = [list(block.find_values(tag)) for tag in tags]
    count = len(columns[0])
    if not 1 <= count <= MAX_SITES or any(len(c) != count for c in columns):
        raise ValueError("Incomplete CIF atom fields.")
    for element, x, y, z, occupancy in zip(*columns, strict=True):
        # Do not let the library infer an element from an atom label or accept
        # unspecified/partial occupancies as a fully ordered structure.
        if not re.fullmatch(r"[A-Z][a-z]?", element):
            raise ValueError("Unsupported CIF species.")
        if gemmi.Element(element).name != element or element in {"X", "D"}:
            raise ValueError("Unsupported CIF species.")
        for value in (x, y, z):
            _scalar(value)
        if _scalar(occupancy) != 1:
            raise ValueError("Disordered or partially occupied CIF is unsupported.")
    for tag in ("_atom_site_disorder_group", "_atom_site_disorder_assembly"):
        if any(value not in {".", "?", "0"} for value in block.find_values(tag)):
            raise ValueError("Disordered CIF is unsupported.")
    structure = gemmi.make_small_structure_from_block(block)
    # Require explicit source symmetry, a recognized finite group and cell
    # compatibility. No missing symmetry is guessed from a class or formula.
    symops = structure.symops
    if not 1 <= len(symops) <= 192 or len(set(symops)) != len(symops):
        raise ValueError("Missing or ambiguous CIF symmetry.")
    if any(
        len(op) > 100 or not re.fullmatch(r"[xyzXYZ0-9+\-/, .]+", op) for op in symops
    ):
        raise ValueError("Unsupported CIF symmetry expression.")
    group = gemmi.GroupOps([gemmi.Op(op) for op in symops])
    spacegroup = gemmi.find_spacegroup_by_ops(group)
    if spacegroup is None or not structure.cell.is_compatible_with_spacegroup(
        spacegroup
    ):
        raise ValueError("CIF symmetry and unit cell disagree.")
    if crystal_system and spacegroup.crystal_system_str() != crystal_system:
        raise ValueError("CIF crystal system differs from the source subset.")
    declared = gemmi.find_spacegroup_by_name(structure.spacegroup_hm)
    if declared is not None and declared.operations() != group:
        raise ValueError("CIF space-group name disagrees with explicit symmetry.")
    if count * len(symops) > MAX_SITES:
        raise ValueError("CIF symmetry expansion exceeds the viewer budget.")
    if len(structure.sites) != count:
        raise ValueError("CIF atom conversion was incomplete.")
    expanded = structure.get_all_unit_cell_sites()
    sites = [
        (site.element.name, [float(v) % 1 for v in site.fract]) for site in expanded
    ]
    if not 1 <= len(sites) <= MAX_SITES or any(
        not all(math.isfinite(v) for v in fractional) for _, fractional in sites
    ):
        raise ValueError("Unsupported expanded CIF coordinates.")
    counts = Counter(element for element, _ in sites)
    expanded_formula = "".join(f"{el}{n}" for el, n in sorted(counts.items()))
    if composition_key(expanded_formula) != composition_key(formula):
        raise ValueError("Expanded CIF atoms disagree with its formula.")
    cell = [
        list(structure.cell.orthogonalize(gemmi.Fractional(*vector)))
        for vector in ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    ]
    return {"cell": cell, "sites": sites, "block": block.name}


def read_dataset_cif(archive_bytes, formula, crystal_system):
    """Select one supported composition/phase block; ambiguous matches
    fail closed."""
    import gemmi

    if (
        not isinstance(archive_bytes, bytes)
        or not 1 <= len(archive_bytes) <= MAX_CIF_BYTES
    ):
        raise ValueError("Dataset archive exceeds its budget.")
    matches = []
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        members = archive.infolist()
        if not 1 <= len(members) <= MAX_MEMBERS:
            raise ValueError("Too many dataset archive members.")
        total = 0
        cif_members = []
        seen = set()
        for member in members:
            path = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if (
                member.orig_filename != member.filename
                or member.filename in seen
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in member.filename
                or len(member.filename) > 200
                or stat.S_ISLNK(mode)
                or member.flag_bits & 1
                or member.compress_type
                not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
            ):
                raise ValueError("Unsupported dataset archive member.")
            seen.add(member.filename)
            total += member.file_size
            if total > MAX_EXPANDED_BYTES or member.file_size > MAX_CIF_BYTES:
                raise ValueError("Dataset archive expansion exceeds its budget.")
            if path.suffix.lower() == ".cif":
                if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}\.cif", path.name, re.I):
                    raise ValueError("Unsupported CIF filename.")
                cif_members.append(member)
        if not 1 <= len(cif_members) <= MAX_CIFS:
            raise ValueError("No bounded set of CIF files is available.")
        for member in cif_members:
            with archive.open(member) as stream:
                raw = stream.read(MAX_CIF_BYTES + 1)
            if len(raw) != member.file_size or b"\x00" in raw:
                raise ValueError("Invalid CIF file length or encoding.")
            text = raw.decode("utf-8")
            document = gemmi.cif.read_string(text)
            if not 1 <= len(document) <= MAX_BLOCKS:
                raise ValueError("CIF block count exceeds its budget.")
            for block in document:
                try:
                    geometry = _geometry(block, formula, crystal_system)
                except (ValueError, RuntimeError, TypeError):
                    continue
                matches.append(
                    {
                        **geometry,
                        "filename": PurePosixPath(member.filename).name,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
                        "original_base64": base64.b64encode(raw).decode("ascii"),
                    }
                )
    if len(matches) != 1:
        raise ValueError("No unique supported CIF block matches this source subset.")
    return matches[0]
