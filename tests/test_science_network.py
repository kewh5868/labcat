"""The only live source has bounded, public-only, non-redirecting
network access."""

import hashlib
import io
import json
import socket
from urllib.parse import parse_qs, urlsplit

import pytest

from labcat.science import sources

KEY = "public-api-test-key-not-real"


class Response:
    def __init__(self, *, body=b'{"data":[]}', status=200, headers=None):
        self.body = io.BytesIO(body)
        self.status = status
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.reads = 0

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read1(self, count):
        self.reads += 1
        return self.body.read(count)


class FakeSocket:
    def __init__(self):
        self.timeouts = []
        self.closed = False

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def close(self):
        self.closed = True


def _network(monkeypatch, response):
    calls = {"connections": [], "requests": [], "tls_names": []}
    sock = FakeSocket()

    class Connection:
        def __init__(self, host, timeout):
            calls["connections"].append((host, timeout))
            self.sock = None
            self.closed = False

        def request(self, method, path, headers):
            calls["requests"].append((method, path, headers))

        def getresponse(self):
            return response

        def close(self):
            calls["closed"] = True

    class TLSContext:
        def wrap_socket(self, raw, server_hostname):
            calls["tls_names"].append(server_hostname)
            assert raw is sock
            return sock

    def connect(address, timeout):
        calls["address"] = address
        return sock

    monkeypatch.setattr(sources, "_public_addresses", lambda deadline: ["8.8.8.8"])
    monkeypatch.setattr(sources.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(sources.socket, "create_connection", connect)
    monkeypatch.setattr(sources.ssl, "create_default_context", TLSContext)
    return calls, sock


def test_fixed_api_request_tls_identity_no_proxy_or_prompt_url(monkeypatch):
    body = b'{"data": []}'
    calls, sock = _network(monkeypatch, Response(body=body))
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999/")
    payload, digest, url = sources._request_mp(KEY)
    assert payload == {"data": []}
    assert digest == hashlib.sha256(body).hexdigest()
    assert calls["connections"] == [(sources.MP_HOST, sources.NETWORK_SECONDS)]
    assert calls["address"] == ("8.8.8.8", 443)
    assert calls["tls_names"] == [sources.MP_HOST]
    method, path, headers = calls["requests"][0]
    assert method == "GET"
    assert path.startswith("/materials/summary/?")
    assert headers["X-API-KEY"] == KEY
    query = parse_qs(urlsplit(url).query)
    assert "formula" not in query
    assert "has_props" not in query
    assert query["deprecated"] == ["false"]
    assert query["id_format"] == ["legacy"]
    assert query["_limit"] == [str(sources.MAX_RECORDS)]
    assert "origins" in query["_fields"][0]
    assert KEY not in url
    assert all(0 < timeout <= sources.NETWORK_SECONDS for timeout in sock.timeouts)
    assert calls["closed"]


def test_structure_request_is_one_exact_id_with_fixed_fields(monkeypatch):
    calls, _ = _network(monkeypatch, Response())
    _, _, url = sources._request_mp_data(KEY, structure_id="mp-149")
    query = parse_qs(urlsplit(url).query)
    assert query["material_ids"] == ["mp-149"]
    assert query["_limit"] == ["1"]
    assert query["deprecated"] == ["false"]
    assert query["id_format"] == ["legacy"]
    assert query["_fields"] == [
        "material_id,formula_pretty,elements,deprecated,structure,last_updated"
    ]
    assert len(calls["requests"]) == 1 and KEY not in url


def test_internal_composition_preference_does_not_break_provider_query(monkeypatch):
    calls, _ = _network(monkeypatch, Response())
    filters = {"elements": "O", "prefer_simple": "true", "exclude_elements": "Pb"}
    _, _, url = sources._request_mp(KEY, filters)
    query = parse_qs(urlsplit(url).query)
    assert "prefer_simple" not in query
    assert query["_sort_fields"] == ["material_id"]
    assert query["elements"] == ["O"]
    assert query["exclude_elements"] == ["Pb"]
    assert filters["prefer_simple"] == "true"
    assert len(calls["requests"]) == 1 and KEY not in url
    _network(monkeypatch, Response())
    _, _, baseline = sources._request_mp(
        KEY, {"elements": "O", "exclude_elements": "Pb"}
    )
    assert baseline == url


@pytest.mark.parametrize(
    "scope, minimum, maximum",
    [
        ("multi_element", "2", None),
        ("single_element", "1", "1"),
    ],
)
def test_internal_metal_scope_translates_to_official_element_count_bounds(
    monkeypatch, scope, minimum, maximum
):
    _network(monkeypatch, Response())
    filters = {"composition_scope": scope, "is_metal": "true", "formula": "FeNi"}
    _, _, url = sources._request_mp(KEY, filters)
    query = parse_qs(urlsplit(url).query)
    assert "composition_scope" not in query
    assert query["nelements_min"] == [minimum]
    assert query.get("nelements_max") == ([maximum] if maximum else None)
    assert query["formula"] == ["FeNi"] and query["is_metal"] == ["true"]
    assert filters["composition_scope"] == scope


@pytest.mark.parametrize(
    "scope, expected",
    [
        ("multi_element", ["FeNi"]),
        ("single_element", ["Fe"]),
    ],
)
def test_metal_scope_rechecks_returned_formula_even_if_provider_ignores_bounds(
    monkeypatch, scope, expected
):
    rows = [
        {
            "material_id": "mp-1",
            "formula_pretty": "Fe",
            "elements": ["Fe"],
            "deprecated": False,
        },
        {
            "material_id": "mp-2",
            "formula_pretty": "FeNi",
            "elements": ["Fe", "Ni"],
            "deprecated": False,
        },
    ]
    _network(monkeypatch, Response(body=json.dumps({"data": rows}).encode()))
    records, metadata = sources.retrieve_live(KEY, {"composition_scope": scope})
    assert [record["formula"] for record in records] == expected
    assert metadata["records_rejected"] == 1


@pytest.mark.parametrize(
    "options", [{"metadata_only": True}, {"filters": {"formula": "Si"}}]
)
def test_structure_query_cannot_mix_other_source_operations(monkeypatch, options):
    monkeypatch.setattr(
        sources, "_public_addresses", lambda *_: pytest.fail("unexpected network")
    )
    with pytest.raises(sources.SourceError):
        sources._request_mp_data(KEY, structure_id="mp-149", **options)


def test_probe_uses_same_fixed_transport_with_one_legacy_id_and_no_retained_body(
    monkeypatch,
):
    body = json.dumps(
        {
            "data": [{"material_id": "mp-123", "unrequested_narrative": KEY}],
            "unrequested_metadata": KEY,
        }
    ).encode()
    calls, _ = _network(monkeypatch, Response(body=body))
    outcome = sources.probe_connection(KEY)
    assert outcome == {"records_checked": 1, "id_format": "legacy"}
    assert KEY not in json.dumps(outcome)
    method, path, headers = calls["requests"][0]
    query = parse_qs(urlsplit(path).query)
    assert method == "GET"
    assert query == {
        "deprecated": ["false"],
        "id_format": ["legacy"],
        "_fields": ["material_id"],
        "_limit": ["1"],
        "_skip": ["0"],
        "_sort_fields": ["material_id"],
    }
    assert headers["User-Agent"] == "Labcat/0.1 public-materials-triage"
    assert headers["Accept-Encoding"] == "identity"
    assert headers["X-API-KEY"] == KEY
    assert calls["tls_names"] == [sources.MP_HOST]
    assert KEY not in path
    assert calls["closed"]


@pytest.mark.parametrize(
    "payload",
    [
        {"data": [{"material_id": "alpha-id"}]},
        {"data": [{"material_id": "mp-1"}, {"material_id": "mp-2"}]},
        {"data": [{"material_id": KEY}]},
        {"data": [{}]},
        {"data": "injection"},
        {},
    ],
)
def test_probe_rejects_unsupported_record_shape_without_exposing_body(
    monkeypatch, payload
):
    _network(monkeypatch, Response(body=json.dumps(payload).encode()))
    with pytest.raises(sources.SourceError) as caught:
        sources.probe_connection(KEY)
    assert KEY not in str(caught.value)
    assert "alpha-id" not in str(caught.value)


def test_probe_error_status_is_safe_and_does_not_read_error_body_or_retry(monkeypatch):
    response = Response(status=403, body=(KEY + " private error details").encode())
    calls, _ = _network(monkeypatch, response)
    with pytest.raises(sources.SourceError, match="HTTP 403") as caught:
        sources.probe_connection(KEY)
    assert KEY not in str(caught.value)
    assert "private error details" not in str(caught.value)
    assert len(calls["requests"]) == 1
    assert response.reads == 0


def test_probe_has_smaller_byte_budget_and_no_caller_selected_query(monkeypatch):
    response = Response(body=b" " * (sources.MAX_PROBE_BYTES + 1))
    _network(monkeypatch, response)
    with pytest.raises(sources.SourceError, match="size budget"):
        sources.probe_connection(KEY)
    monkeypatch.setattr(
        sources,
        "_public_addresses",
        lambda deadline: pytest.fail("Invalid options reached DNS"),
    )
    with pytest.raises(ValueError):
        sources._request_mp(KEY, {"id_format": "alpha"})
    with pytest.raises(sources.SourceError, match="probe options"):
        sources._request_mp_data(KEY, {"formula": "TiO2"}, metadata_only=True)


@pytest.mark.parametrize("status", [301, 302, 307, 401, 403, 429, 500])
def test_redirects_and_failures_never_follow_or_retain_response_text(
    monkeypatch, status
):
    response = Response(
        status=status,
        body=b"credentials or injected instructions",
        headers={"Location": "http://169.254.169.254/latest/meta-data/"},
    )
    calls, _ = _network(monkeypatch, response)
    with pytest.raises(sources.SourceError) as error:
        sources._request_mp(KEY)
    assert str(status) in str(error.value)
    assert "injected instructions" not in str(error.value)
    assert KEY not in str(error.value)
    assert len(calls["requests"]) == 1
    assert response.reads == 0
    assert calls["closed"]


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Type": "text/html"},
        {"Content-Encoding": "gzip"},
        {"Content-Length": str(sources.MAX_BYTES + 1)},
        {"Content-Length": "nonsense"},
    ],
)
def test_non_json_compressed_or_oversize_responses_rejected(monkeypatch, headers):
    response = Response(headers=headers)
    _network(monkeypatch, response)
    with pytest.raises(sources.SourceError):
        sources._request_mp(KEY)
    assert response.reads == 0


def test_streamed_size_budget_and_malformed_json(monkeypatch):
    calls, _ = _network(monkeypatch, Response(body=b" " * (sources.MAX_BYTES + 1)))
    with pytest.raises(sources.SourceError, match="size budget"):
        sources._request_mp(KEY)
    assert calls["closed"]
    _network(monkeypatch, Response(body=b"<execute_instructions>"))
    with pytest.raises(sources.SourceError, match="request failed"):
        sources._request_mp(KEY)


def test_time_budget_checked_during_stream(monkeypatch):
    calls, _ = _network(monkeypatch, Response())
    moments = iter([0, 1, 2, 3, sources.NETWORK_SECONDS + 1])
    monkeypatch.setattr(sources.time, "monotonic", lambda: next(moments))
    with pytest.raises(sources.SourceError, match="time budget"):
        sources._request_mp(KEY)
    assert calls["closed"]


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "::1",
        "10.0.0.1",
        "169.254.169.254",
        "192.168.1.1",
        "0.0.0.0",
        "::ffff:127.0.0.1",
    ],
)
def test_dns_nonpublic_addresses_rejected_before_connect(monkeypatch, address):
    monkeypatch.setattr(
        sources.socket,
        "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))],
    )
    with pytest.raises(sources.SourceError, match="prohibited network address"):
        sources._public_addresses(sources.time.monotonic() + 1)


def test_dns_mixed_public_private_rejected_and_dns_failure_sanitized(monkeypatch):
    monkeypatch.setattr(
        sources.socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(sources.SourceError, match="prohibited"):
        sources._public_addresses(sources.time.monotonic() + 1)

    def fail(*args, **kwargs):
        raise OSError("internal details")

    monkeypatch.setattr(sources.socket, "getaddrinfo", fail)
    with pytest.raises(sources.SourceError, match="DNS lookup was unavailable"):
        sources._public_addresses(sources.time.monotonic() + 1)


@pytest.mark.parametrize("key", [None, "short", KEY + "\r\nEvil: header", "x" * 257])
def test_invalid_key_never_reaches_network(monkeypatch, key):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid key reached DNS")

    monkeypatch.setattr(sources, "_public_addresses", forbidden)
    with pytest.raises(sources.SourceError, match="key format"):
        sources._request_mp(key)


def test_bounded_record_list_schema(monkeypatch):
    for payload in (
        [],
        {},
        {"data": "injection"},
        {"data": [{}] * (sources.MAX_RECORDS + 1)},
    ):
        monkeypatch.setattr(
            sources,
            "_request_mp",
            lambda key, data=payload: (
                data,
                "digest",
                "https://api.materialsproject.org",
            ),
        )
        with pytest.raises(sources.SourceError):
            sources.retrieve_live(KEY)
    monkeypatch.setattr(
        sources,
        "_request_mp",
        lambda key: (
            {"data": ["not a record"]},
            "digest",
            "https://api.materialsproject.org",
        ),
    )
    records, metadata = sources.retrieve_live(KEY)
    assert records == []
    assert metadata["records_rejected"] == 1
    assert "not a record" not in json.dumps(metadata)
