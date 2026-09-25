"""Restricted provider proxy for a Goose worker on a Docker internal
network.

The worker has no external route. This separate, stateless service
forwards only fixed provider HTTPS tunnels or explicitly selected local
Ollama inference. It has no workspace mount, credentials, API controls,
or general web-fetch route.
"""

import ipaddress
import re
import select
import socket
import socketserver
import threading
import time
from urllib.parse import urlsplit

PORT = 8780
MAX_HEADERS = 16_384
MAX_BODY = 2_000_000
MAX_TRAFFIC = 16_000_000
# Keep a bounded tunnel alive through the worker's 180-second run plus shutdown
# margin, including provider connections reused across several model turns.
# A regression test checks this relation without coupling this stateless proxy
# to the credential-aware runtime module.
MAX_SECONDS = 210
HTTPS_HOSTS = frozenset(
    {
        "api.openai.com",
        "auth.openai.com",
        "chatgpt.com",
        "api.anthropic.com",
        "api.moonshot.ai",
        "generativelanguage.googleapis.com",
        "api.deepseek.com",
        "api.x.ai",
        "openrouter.ai",
    }
)
BEDROCK_HOST = re.compile(
    r"bedrock-runtime\.(?:us|eu|ap|ca|sa|me|af|il|mx)"
    r"-(?:north|south|east|west|central|northeast|southeast)"
    r"-[1-9]\.amazonaws\.com"
)
OLLAMA_METHODS = {
    "/api/tags": "GET",
    "/api/version": "GET",
    "/v1/models": "GET",
    "/api/show": "POST",
    "/api/chat": "POST",
    "/api/generate": "POST",
    "/v1/chat/completions": "POST",
}
CONNECTIONS = threading.BoundedSemaphore(8)


class ProxyError(ValueError):
    """An unavailable or disallowed destination; never include request
    details."""


def _destination(method, target):
    if method == "CONNECT":
        match = re.fullmatch(r"([a-z0-9.-]+):443", target)
        if not match:
            raise ProxyError
        host = match.group(1)
        if host not in HTTPS_HOSTS and not BEDROCK_HOST.fullmatch(host):
            raise ProxyError
        return host, 443, None
    if method not in {"GET", "POST"}:
        raise ProxyError
    parsed = urlsplit(target)
    if (
        parsed.scheme != "http"
        or parsed.netloc != "host.docker.internal:11434"
        or parsed.query
        or parsed.fragment
        or OLLAMA_METHODS.get(parsed.path) != method
    ):
        raise ProxyError
    return "host.docker.internal", 11434, parsed.path


def _connect(host, port):
    """Resolve once, validate every address, and connect to the pinned
    IP."""
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not addresses:
            raise ProxyError
        for family, _, _, _, address in addresses:
            ip = ipaddress.ip_address(address[0])
            if family not in {socket.AF_INET, socket.AF_INET6}:
                raise ProxyError
            if host != "host.docker.internal" and (
                not ip.is_global
                or ip.is_multicast
                or ip.is_reserved
                or getattr(ip, "ipv4_mapped", None) is not None
            ):
                raise ProxyError
        for family, kind, protocol, _, address in addresses[:4]:
            connection = socket.socket(family, kind, protocol)
            try:
                connection.settimeout(5)
                connection.connect(address)
                return connection
            except OSError:
                connection.close()
        raise ProxyError
    except (OSError, ValueError):
        raise ProxyError from None


def _read_request(stream, connection=None):
    deadline = time.monotonic() + 10

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise ProxyError
        if connection is not None:
            connection.settimeout(seconds)

    remaining()
    line = stream.readline(MAX_HEADERS + 1)
    used = len(line)
    try:
        method, target, version = line.decode("ascii").rstrip("\r\n").split(" ")
    except (UnicodeError, ValueError):
        raise ProxyError from None
    if version not in {"HTTP/1.0", "HTTP/1.1"} or not line.endswith(b"\r\n"):
        raise ProxyError
    headers = {}
    while used <= MAX_HEADERS:
        remaining()
        line = stream.readline(MAX_HEADERS - used + 1)
        used += len(line)
        if line == b"\r\n":
            break
        if not line.endswith(b"\r\n") or line[:1] in {b" ", b"\t"}:
            raise ProxyError
        try:
            name, value = line[:-2].decode("ascii").split(":", 1)
        except (UnicodeError, ValueError):
            raise ProxyError from None
        name = name.lower()
        if (
            not re.fullmatch(r"[a-z0-9!#$%&'*+.^_`|~-]+", name)
            or name in headers
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise ProxyError
        headers[name] = value.strip()
    else:
        raise ProxyError
    if used > MAX_HEADERS or "transfer-encoding" in headers:
        raise ProxyError
    length_text = headers.get("content-length", "0")
    if not re.fullmatch(r"[0-9]{1,7}", length_text):
        raise ProxyError
    length = int(length_text)
    if length > MAX_BODY or (method in {"CONNECT", "GET"} and length):
        raise ProxyError
    chunks = []
    outstanding = length
    while outstanding:
        remaining()
        chunk = stream.read(outstanding)
        if not chunk:
            raise ProxyError
        chunks.append(chunk)
        outstanding -= len(chunk)
    return method, target, headers, b"".join(chunks)


def _relay(client, upstream, *, duplex):
    deadline = time.monotonic() + MAX_SECONDS
    total = 0
    sources = [upstream, client] if duplex else [upstream]
    while time.monotonic() < deadline:
        ready, _, _ = select.select(
            sources, [], [], min(5, deadline - time.monotonic())
        )
        for source in ready:
            data = source.recv(min(65_536, MAX_TRAFFIC - total + 1))
            if not data:
                return
            total += len(data)
            if total > MAX_TRAFFIC:
                raise ProxyError
            destination = client if source is upstream else upstream
            destination.sendall(data)
    raise ProxyError


class Handler(socketserver.StreamRequestHandler):
    # Unbuffered request input ensures CONNECT does not hide TLS bytes in a buffer.
    rbufsize = 0

    def handle(self):
        if not CONNECTIONS.acquire(blocking=False):
            return
        started = False
        try:
            self.connection.settimeout(5)
            method, target, headers, body = _read_request(self.rfile, self.connection)
            self.connection.settimeout(5)
            if (
                method == "GET"
                and target == "/health"
                and ipaddress.ip_address(self.client_address[0]).is_loopback
            ):
                self.connection.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
                    b"Connection: close\r\n\r\nOK"
                )
                return
            host, port, path = _destination(method, target)
            with _connect(host, port) as upstream:
                if method == "CONNECT":
                    self.connection.sendall(
                        b"HTTP/1.1 200 Connection Established\r\n\r\n"
                    )
                    started = True
                    _relay(self.connection, upstream, duplex=True)
                else:
                    # Never forward the caller's routing, hop-by-hop, or proxy headers.
                    forwarded = {
                        name: value
                        for name, value in headers.items()
                        if name in {"content-type", "accept", "user-agent"}
                    }
                    forwarded.update(
                        {
                            "host": "host.docker.internal:11434",
                            "content-length": str(len(body)),
                            "connection": "close",
                        }
                    )
                    head = f"{method} {path} HTTP/1.1\r\n" + "".join(
                        f"{name}: {value}\r\n" for name, value in forwarded.items()
                    )
                    upstream.sendall(head.encode("ascii") + b"\r\n" + body)
                    started = True
                    _relay(self.connection, upstream, duplex=False)
        except (OSError, ProxyError, ValueError):
            if not started:
                try:
                    self.connection.sendall(
                        b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n"
                        b"Connection: close\r\n\r\n"
                    )
                except OSError:
                    pass
        finally:
            CONNECTIONS.release()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    import sys

    if sys.argv[1:] == ["--health"]:
        with socket.create_connection(("127.0.0.1", PORT), timeout=2) as connection:
            connection.sendall(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
            if not connection.recv(256).startswith(b"HTTP/1.1 200 OK"):
                raise SystemExit(1)
        return
    if sys.argv[1:]:
        raise SystemExit(2)
    with Server(("0.0.0.0", PORT), Handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
