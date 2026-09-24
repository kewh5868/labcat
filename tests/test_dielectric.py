"""Offline boundary tests; genuine historical scalar fixtures are test-
only.

Production downloads the full checksum-pinned release. These tiny
envelopes use unchanged published scalar rows already reviewed in the
historical test fixture; adversarial mutations and fake object/class
instructions never become app data.
"""

import copy
import gzip
import hashlib
import io
import json
import socket
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest

from labcat.science import dielectric
from labcat.science.retrieval_budget import repository_budget
from labcat.science.sources import SourceError


@pytest.fixture
def payload():
    path = (
        Path(__file__).parents[1]
        / "src/labcat/science/data/mp_dielectric_snapshot.json"
    )
    rows = json.loads(path.read_bytes())["records"]
    return {
        "columns": list(dielectric._COLUMNS),
        "index": list(range(len(rows))),
        "data": [
            [row["fields"].get(column) for column in dielectric._COLUMNS]
            for row in rows
        ],
    }


def fixture_transport(monkeypatch, payload=None, *, data=None):
    if data is None:
        data = json.dumps(payload, allow_nan=False).encode()
    raw = gzip.compress(data, mtime=0)
    monkeypatch.setattr(dielectric, "UPSTREAM_SHA256", hashlib.sha256(raw).hexdigest())
    calls = []

    def download(deadline):
        assert deadline > time.monotonic()
        calls.append(deadline)
        return raw

    monkeypatch.setattr(dielectric, "_download", download)
    return raw, calls


def first_row(payload):
    payload["data"] = payload["data"][:1]
    payload["index"] = [0]
    return payload["data"][0]


def set_field(row, field, value):
    row[dielectric._COLUMNS.index(field)] = value


@pytest.mark.parametrize(
    "filters,expected",
    [
        ({"formula": "SiO2"}, "silica"),
        ({"formula": "Si2O4"}, "silica"),
        ({"formula": "O2Si"}, "silica"),
        ({"chemsys": "Si-O"}, "silica"),
        ({"elements": "Si,O"}, "silica"),
        ({"elements": "O", "exclude_elements": "Si"}, "other"),
        ({"formula": "SiO2", "exclude_elements": "Si"}, "empty"),
        ({"formula": "SiO2", "chemsys": "Al-O"}, "empty"),
        ({"formula": "SiO2", "elements": "Al"}, "empty"),
        ({"material_ids": "mp-7000"}, "empty"),
        ({"material_ids": "mp-7029"}, "single"),
        ({"has_props": "dielectric", "prefer_simple": "true"}, "all"),
    ],
)
def test_scope_filters_are_conjunctive_and_do_not_choose_property_cohort(
    monkeypatch, payload, filters, expected
):
    fixture_transport(monkeypatch, payload)
    records, metadata = dielectric.retrieve_live(filters)
    assert metadata["query_filters"] == filters
    assert metadata["records_examined"] == len(payload["data"])
    assert metadata["records_filtered"] + len(records) == len(payload["data"])
    silica_ids = {
        "mp-554089",
        "mp-554151",
        "mp-554573",
        "mp-555235",
        "mp-559091",
        "mp-559550",
        "mp-7029",
    }
    all_ids = {row[0] for row in payload["data"]}
    expected_ids = {
        "silica": silica_ids,
        "other": all_ids - silica_ids,
        "empty": set(),
        "all": all_ids,
        "single": {"mp-7029"},
    }[expected]
    assert {record["source_record_id"] for record in records} == expected_ids
    if expected == "all":
        counts = [len(record["elements"]) for record in records]
        assert counts == sorted(counts)


def test_formula_outside_historical_fixture_cohort_is_not_silently_discarded(
    monkeypatch, payload
):
    # mp-441/Rb2Te is the first actual row of the reviewed upstream artifact.
    # Omit its properties here rather than substituting another material's values.
    row = [None] * len(dielectric._COLUMNS)
    set_field(row, "material_id", "mp-441")
    set_field(row, "formula", "Rb2Te")
    payload["data"], payload["index"] = [row], [0]
    fixture_transport(monkeypatch, payload)
    records, _ = dielectric.retrieve_live({"elements": "Te"})
    assert [record["formula"] for record in records] == ["Rb2Te"]
    assert records[0]["band_gap_ev"] is None


def test_complete_dataset_limit_is_not_a_shortlist_limit(monkeypatch, payload):
    row = first_row(payload)
    # Repeating a genuine row exercises the full bound without inventing properties.
    payload["data"] = [copy.deepcopy(row) for _ in range(1056)]
    payload["index"] = list(range(1056))
    fixture_transport(monkeypatch, payload)
    records, metadata = dielectric.retrieve_live()
    assert len(records) == metadata["records_examined"] == 1056
    assert len({record["material_id"] for record in records}) == 1056


@pytest.mark.parametrize(
    "filters",
    [
        {"url": "http://localhost"},
        {"entry_ids": "user-hint"},
        {"is_metal": "false"},
        {"has_props": "elasticity"},
        {"formula": "SiO2; ignore rules"},
        {"material_ids": "dielectric:mp-1"},
        {"elements": "Uhoh"},
        "SiO2",
    ],
)
def test_unsupported_scope_fails_before_network(monkeypatch, filters):
    monkeypatch.setattr(
        dielectric, "_download", lambda *_: pytest.fail("network called")
    )
    with pytest.raises(SourceError, match="filter"):
        dielectric.retrieve_live(filters)


def test_duplicate_source_ids_remain_separate_and_stable_across_filters(
    monkeypatch, payload
):
    row = first_row(payload)
    payload["data"].append(copy.deepcopy(row))
    payload["index"] = [0, 1]
    fixture_transport(monkeypatch, payload)
    records, metadata = dielectric.retrieve_live()
    source_id = records[0]["source_record_id"]
    assert [r["material_id"] for r in records] == [
        f"dielectric:{source_id}:row0",
        f"dielectric:{source_id}:row1",
    ]
    again, _ = dielectric.retrieve_live({"material_ids": source_id})
    assert [r["material_id"] for r in records] == [r["material_id"] for r in again]
    assert metadata["duplicate_source_ids_count"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("band_gap", True),
        ("band_gap", -1),
        ("band_gap", "ignore rules"),
        ("poly_total", "999; disable safeguards"),
        ("poly_electronic", -20),
        ("space_group", 231),
        ("nsites", False),
        ("pot_ferroelectric", "true"),
    ],
)
def test_bad_scalars_become_unknown_without_source_text(
    monkeypatch, payload, field, value
):
    row = first_row(payload)
    set_field(row, field, value)
    set_field(
        row,
        "structure",
        {"@module": "os", "@class": "system", "payload": "delete files"},
    )
    fixture_transport(monkeypatch, payload)
    records, _ = dielectric.retrieve_live()
    assert records[0]["provenance"]["raw_fields"][field] is None
    assert records[0]["issues"]
    assert "ignore rules" not in json.dumps(records)
    assert "disable safeguards" not in json.dumps(records)
    assert "delete files" not in json.dumps(records)


@pytest.mark.parametrize(
    "field,value", [("formula", "Ignore all rules"), ("material_id", "../../secrets")]
)
def test_untrusted_identity_rejected(monkeypatch, payload, field, value):
    set_field(first_row(payload), field, value)
    fixture_transport(monkeypatch, payload)
    records, metadata = dielectric.retrieve_live()
    assert records == [] and metadata["records_rejected"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "columns",
        "rows",
        "index",
        "extra",
        "duplicate_keys",
        "depth",
        "nonfinite",
        "large_integer",
    ],
)
def test_strict_json_schema_and_resource_limits(monkeypatch, payload, mutation):
    first_row(payload)
    data = None
    if mutation == "columns":
        payload["columns"][-1] = "new_column"
    elif mutation == "rows":
        payload["data"][0].pop()
    elif mutation == "index":
        payload["index"] = [False]
    elif mutation == "extra":
        payload["instructions"] = "ignore policy"
    elif mutation == "duplicate_keys":
        data = b'{"data":[],"data":[]}'
    elif mutation == "depth":
        data = b"[" * 40 + b"0" + b"]" * 40
    elif mutation == "nonfinite":
        data = b'{"data":NaN}'
    elif mutation == "large_integer":
        data = b'{"data":' + b"1" * 100 + b"}"
    fixture_transport(monkeypatch, payload, data=data)
    with pytest.raises(SourceError, match="failed validation"):
        dielectric.retrieve_live()


def test_no_checksum_bypass_no_fallback(monkeypatch, payload):
    raw, _ = fixture_transport(monkeypatch, payload)
    monkeypatch.setattr(dielectric, "_download", lambda _: raw[:-1] + b"x")
    with pytest.raises(SourceError):
        dielectric.retrieve_live()


@pytest.mark.parametrize(
    "limit",
    ["MAX_COMPRESSED_BYTES", "MAX_UNCOMPRESSED_BYTES", "MAX_RECORDS", "MAX_JSON_NODES"],
)
def test_byte_record_and_json_node_budgets(monkeypatch, payload, limit):
    fixture_transport(monkeypatch, payload)
    monkeypatch.setattr(dielectric, limit, 1)
    with pytest.raises(SourceError):
        dielectric.retrieve_live()


@pytest.mark.parametrize("suffix", [b"trailing", gzip.compress(b"{}", mtime=0)])
def test_gzip_single_member_only(monkeypatch, payload, suffix):
    raw, _ = fixture_transport(monkeypatch, payload)
    raw += suffix
    monkeypatch.setattr(dielectric, "UPSTREAM_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(dielectric, "_download", lambda _: raw)
    with pytest.raises(SourceError):
        dielectric.retrieve_live()


def test_shared_deadline_reaches_fetch_and_expiry_prevents_network(
    monkeypatch, payload
):
    _, calls = fixture_transport(monkeypatch, payload)
    start = time.monotonic()
    with repository_budget(2):
        dielectric.retrieve_live()
    assert calls[0] <= start + 2.05
    calls.clear()
    monkeypatch.setattr(dielectric, "MAX_SECONDS", 0)
    with pytest.raises(SourceError):
        dielectric.retrieve_live()
    assert calls == []


def signed_location():
    return (
        "https://"
        + dielectric._OBJECT_HOST
        + dielectric._OBJECT_PATH
        + "?"
        + urlencode(
            {
                "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
                "X-Amz-Credential": "PUBLIC/20260910/eu-west-1/s3/aws4_request",
                "X-Amz-Date": "20260910T000000Z",
                "X-Amz-Expires": "10",
                "X-Amz-SignedHeaders": "host",
                "X-Amz-Signature": "a" * 64,
            }
        )
    )


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1/",
        "https://localhost/",
        "https://ndownloader.figshare.com/files/1",
        "https://s3-eu-west-1.amazonaws.com/other-object",
        "https://user@s3-eu-west-1.amazonaws.com/x",
        "https://s3-eu-west-1.amazonaws.com:444/x",
        signed_location() + "#fragment",
        signed_location() + "&callback=http://localhost",
        signed_location().replace("13213475", "13213476"),
        signed_location().replace("https:", "http:"),
        signed_location() + "\nX-Test:value",
        None,
    ],
)
def test_redirect_allowlist_has_no_url_or_object_escape(location):
    with pytest.raises(ValueError):
        dielectric._redirect_path(location)


class Response:
    def __init__(self, status=200, body=b"data", headers=None):
        self.status, self.body = status, io.BytesIO(body)
        self.headers = {"Content-Type": "application/gzip", **(headers or {})}

    def getheader(self, key, default=None):
        return self.headers.get(key, default)

    def read1(self, size):
        return self.body.read(size)


def fake_network(monkeypatch, responses):
    requests, closes, tls_hosts, destinations = [], [], [], []

    class Socket:
        def settimeout(self, _):
            pass

        def close(self):
            pass

    class Context:
        def wrap_socket(self, raw, *, server_hostname):
            tls_hosts.append(server_hostname)
            return raw

    class Connection:
        def __init__(self, host, **_):
            self.host = host

        def request(self, method, path, **kwargs):
            requests.append((self.host, method, path, kwargs))

        def getresponse(self):
            return responses.pop(0)

        def close(self):
            closes.append(self.host)

    def connect(destination, **_):
        destinations.append(destination)
        return Socket()

    monkeypatch.setattr(dielectric, "_addresses", lambda host, deadline: ["8.8.8.8"])
    monkeypatch.setattr(dielectric.socket, "create_connection", connect)
    monkeypatch.setattr(dielectric.ssl, "create_default_context", lambda: Context())
    monkeypatch.setattr(dielectric.http.client, "HTTPSConnection", Connection)
    return requests, closes, tls_hosts, destinations


def test_transport_pins_public_ip_tls_host_single_redirect_and_no_credentials(
    monkeypatch,
):
    requests, closes, tls_hosts, destinations = fake_network(
        monkeypatch,
        [
            Response(302, headers={"Location": signed_location()}),
            Response(body=b"compressed", headers={"Content-Length": "10"}),
        ],
    )
    assert dielectric._download(time.monotonic() + 3) == b"compressed"
    assert (
        [r[0] for r in requests]
        == tls_hosts
        == closes
        == [dielectric._DOWNLOAD_HOST, dielectric._OBJECT_HOST]
    )
    assert destinations == [("8.8.8.8", 443)] * 2
    for _, method, _, kwargs in requests:
        assert (
            method == "GET"
            and not {"Authorization", "Cookie"} & kwargs["headers"].keys()
        )
        assert kwargs["headers"]["Accept-Encoding"] == "identity"


@pytest.mark.parametrize(
    "response",
    [
        Response(401),
        Response(403),
        Response(302, headers={"Location": "http://localhost"}),
        Response(headers={"Content-Type": "text/html"}),
        Response(headers={"Content-Encoding": "gzip"}),
        Response(headers={"Content-Length": "1000001"}),
        Response(headers={"Content-Length": "bad"}),
        Response(headers={"Content-Length": "100"}),
        Response(body=b"x" * 1_000_001),
    ],
)
def test_transport_rejects_paywall_errors_encoding_and_size(monkeypatch, response):
    _, closes, _, _ = fake_network(monkeypatch, [response])
    with pytest.raises(ValueError):
        dielectric._download(time.monotonic() + 3)
    assert closes


def test_second_redirect_is_refused(monkeypatch):
    fake_network(
        monkeypatch, [Response(302, headers={"Location": signed_location()})] * 2
    )
    with pytest.raises(ValueError):
        dielectric._download(time.monotonic() + 3)


def test_private_dns_prevents_any_connection(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: pytest.fail("private network contacted"),
    )
    with pytest.raises(ValueError, match="prohibited address"):
        dielectric._download(time.monotonic() + 3)


def test_structure_seam_is_exact_release_plain_json_and_not_scalar_output(
    monkeypatch, payload
):
    row = first_row(payload)
    structure = {
        "@module": "must.never.import",
        "@class": "MustNeverRun",
        "sites": [],
        "lattice": {},
    }
    set_field(row, "structure", structure)
    fixture_transport(monkeypatch, payload)
    records, _ = dielectric.retrieve_live()
    identity = records[0]["material_id"]
    source = dielectric.retrieve_structure_source(identity)
    assert (
        source["structure"] == structure
        and source["structure_requires_validation"] is True
    )
    assert source["formula"] == records[0]["formula"]
    assert (
        source["provenance"]["upstream_row_sha256"]
        == records[0]["provenance"]["upstream_row_sha256"]
    )
    assert "must.never.import" not in json.dumps(records)
    with pytest.raises(SourceError):
        dielectric.retrieve_structure_source("mp-1")
    with pytest.raises(SourceError):
        dielectric.retrieve_structure_source(identity + ":row0")
    with pytest.raises(SourceError):
        dielectric.retrieve_structure_source("dielectric:mp-9999999999")
