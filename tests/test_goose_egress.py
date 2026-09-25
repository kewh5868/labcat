"""The isolated worker proxy cannot route to app controls or arbitrary
hosts."""

import io
import socket
import threading
from contextlib import contextmanager

import pytest

from labcat import goose_egress as proxy


@pytest.mark.parametrize(
    "host", sorted(proxy.HTTPS_HOSTS) + ["bedrock-runtime.us-west-2.amazonaws.com"]
)
def test_only_fixed_provider_https_destinations(host):
    assert proxy._destination("CONNECT", host + ":443") == (host, 443, None)


@pytest.mark.parametrize(
    "method,target",
    [
        ("CONNECT", "labcat:8000"),
        ("CONNECT", "host.docker.internal:443"),
        ("CONNECT", "127.0.0.1:443"),
        ("CONNECT", "api.openai.com:8000"),
        ("CONNECT", "api.openai.com.evil.example:443"),
        ("CONNECT", "api.openai.com@labcat:443"),
        ("CONNECT", "api%2eopenai.com:443"),
        ("CONNECT", "api.openai.com.:443"),
        ("CONNECT", "bedrock-runtime.us-west-2.amazonaws.com.evil.example:443"),
        ("GET", "http://host.docker.internal:8000/api/connections"),
        ("GET", "http://labcat:8000/api/connections"),
        ("GET", "http://127.0.0.1:11434/api/tags"),
        ("GET", "http://host.docker.internal:11434/api/tags?redirect=evil"),
        ("POST", "http://host.docker.internal:11434/api/pull"),
        ("POST", "http://host.docker.internal:11434/api/create"),
        ("DELETE", "http://host.docker.internal:11434/api/delete"),
        ("GET", "http://host.docker.internal:11434/v1/../api/connections"),
        ("GET", "http://host.docker.internal:11434/api/tags#fragment"),
    ],
)
def test_private_api_gateway_ports_installs_and_unapproved_hosts_are_denied(
    method, target
):
    with pytest.raises(proxy.ProxyError):
        proxy._destination(method, target)


@pytest.mark.parametrize("path,method", proxy.OLLAMA_METHODS.items())
def test_local_ollama_is_limited_to_inference_and_model_metadata(path, method):
    assert proxy._destination(method, "http://host.docker.internal:11434" + path) == (
        "host.docker.internal",
        11434,
        path,
    )


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "192.168.65.254",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "fc00::1",
        "::ffff:8.8.8.8",
        "224.0.0.1",
    ],
)
def test_provider_dns_private_rebinding_is_rejected_before_connection(
    monkeypatch, address
):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                0,
                "",
                (address, 443),
            )
        ],
    )
    monkeypatch.setattr(
        socket, "socket", lambda *args, **kwargs: pytest.fail("must not connect")
    )
    with pytest.raises(proxy.ProxyError):
        proxy._connect("api.openai.com", 443)


def test_public_dns_connections_use_the_resolved_ip_not_a_second_dns_lookup(
    monkeypatch,
):
    class Connection:
        def settimeout(self, _):
            pass

        def connect(self, address):
            assert address == ("8.8.8.8", 443)

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 443))
        ],
    )
    monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: Connection())
    assert isinstance(proxy._connect("api.openai.com", 443), Connection)


@pytest.mark.parametrize(
    "raw_request",
    [
        b"POST http://host.docker.internal:11434/api/chat HTTP/1.1\r\n"
        b"Content-Length: 1\r\nContent-Length: 2\r\n\r\nxx",
        b"POST http://host.docker.internal:11434/api/chat HTTP/1.1\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
        b"CONNECT api.openai.com:443 HTTP/1.1\r\nContent-Length: 1\r\n\r\nx",
        b"POST http://host.docker.internal:11434/api/chat HTTP/1.1\r\n"
        b"Content-Length: 2000001\r\n\r\n",
        b"GET http://host.docker.internal:11434/api/tags HTTP/1.1\r\n"
        b" folded: yes\r\n\r\n",
        b"GET /health HTTP/1.1\r\nX-Large: " + b"x" * 17000 + b"\r\n\r\n",
    ],
)
def test_ambiguous_oversized_and_smuggled_requests_are_rejected(raw_request):
    with pytest.raises(proxy.ProxyError):
        proxy._read_request(io.BytesIO(raw_request))


@contextmanager
def running_proxy():
    server = proxy.Server(("127.0.0.1", 0), proxy.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_real_proxy_socket_rejects_forged_host_and_gateway_private_api(monkeypatch):
    monkeypatch.setattr(
        proxy, "_connect", lambda *args: pytest.fail("must not connect")
    )
    with (
        running_proxy() as address,
        socket.create_connection(address, timeout=3) as client,
    ):
        client.sendall(
            b"GET http://host.docker.internal:8000/api/connections HTTP/1.1\r\n"
            b"Host: 127.0.0.1:8000\r\nX-Forwarded-For: 127.0.0.1\r\n\r\n"
        )
        assert client.recv(512).startswith(b"HTTP/1.1 403 Forbidden")


def test_actual_connect_tunnel_only_opens_the_approved_destination(monkeypatch):
    upstream, remote = socket.socketpair()
    destinations = []
    monkeypatch.setattr(
        proxy, "_connect", lambda *args: destinations.append(args) or upstream
    )
    with (
        running_proxy() as address,
        socket.create_connection(address, timeout=3) as client,
    ):
        client.sendall(b"CONNECT api.openai.com:443 HTTP/1.1\r\nHost: bad-host\r\n\r\n")
        assert client.recv(512).startswith(b"HTTP/1.1 200 Connection Established")
        client.sendall(b"test TLS payload")
        remote.settimeout(3)
        assert remote.recv(512) == b"test TLS payload"
        remote.sendall(b"provider TLS reply")
        assert client.recv(512) == b"provider TLS reply"
        remote.close()
    assert destinations == [("api.openai.com", 443)]


def test_tunnel_lifetime_covers_worker_runtime_with_a_finite_shutdown_margin():
    from labcat.goose_runtime import MAX_RUNTIME_SECONDS

    assert MAX_RUNTIME_SECONDS < proxy.MAX_SECONDS <= MAX_RUNTIME_SECONDS + 30


class RelaySocket:
    def __init__(self, clock, payload=b"x"):
        self.clock = clock
        self.payload = payload
        self.sent = []

    def recv(self, maximum):
        return self.payload[:maximum]

    def sendall(self, payload):
        self.sent.append((self.clock[0], payload))


@pytest.mark.parametrize("duplex", [False, True])
def test_active_relay_survives_old_cap_but_stops_at_absolute_deadline(
    monkeypatch, duplex
):
    clock = [0.0]
    client, upstream = RelaySocket(clock), RelaySocket(clock)
    monkeypatch.setattr(proxy.time, "monotonic", lambda: clock[0])

    def readable(sources, write, error, timeout):
        assert not write and not error and 0 < timeout <= 5
        assert sources == ([upstream, client] if duplex else [upstream])
        clock[0] += timeout
        return sources, [], []

    monkeypatch.setattr(proxy.select, "select", readable)
    with pytest.raises(proxy.ProxyError):
        proxy._relay(client, upstream, duplex=duplex)
    from labcat.goose_runtime import MAX_RUNTIME_SECONDS

    assert any(stamp > 120 for stamp, _ in client.sent)
    assert any(stamp >= MAX_RUNTIME_SECONDS for stamp, _ in client.sent)
    assert clock[0] == proxy.MAX_SECONDS
    assert max(stamp for stamp, _ in client.sent) <= proxy.MAX_SECONDS
    assert bool(upstream.sent) is duplex


def test_idle_relay_also_stops_at_the_finite_deadline(monkeypatch):
    clock = [0.0]
    client, upstream = RelaySocket(clock), RelaySocket(clock)
    monkeypatch.setattr(proxy.time, "monotonic", lambda: clock[0])

    def idle(sources, write, error, timeout):
        clock[0] += timeout
        return [], [], []

    monkeypatch.setattr(proxy.select, "select", idle)
    with pytest.raises(proxy.ProxyError):
        proxy._relay(client, upstream, duplex=True)
    assert clock[0] == proxy.MAX_SECONDS
    assert not client.sent and not upstream.sent


def test_traffic_limit_still_ends_relay_before_longer_time_budget(monkeypatch):
    clock = [0.0]
    client, upstream = RelaySocket(clock), RelaySocket(clock, b"xx")
    monkeypatch.setattr(proxy.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(proxy, "MAX_TRAFFIC", 3)
    monkeypatch.setattr(proxy.select, "select", lambda *args: ([upstream], [], []))
    with pytest.raises(proxy.ProxyError):
        proxy._relay(client, upstream, duplex=True)
    assert client.sent == [(0.0, b"xx")]
    assert clock[0] == 0
