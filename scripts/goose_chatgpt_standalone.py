"""Disposable native Goose browser-login diagnostic; Python standard
library only.

No Labcat imports, API keys, host credentials, model tools, or
persistent data. Run only with the documented hardened Docker options
and loopback port mappings. Goose owns OAuth/PKCE and tokens. This
harness only relays its fixed callback, captures its browser URL, and
checks a fixed, tiny response in two processes.
"""

import http.client
import json
import os
import pty
import re
import secrets
import select
import signal
import stat
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path("/tmp/goose-login-probe")
AUTH_URL = ROOT / "browser-url"
TOKENS = ROOT / "config/chatgpt_codex/tokens.json"
MODEL = "gpt-5.6-luna"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REDIRECT = "http://localhost:1455/auth/callback"
MAX_OUTPUT = 256_000
ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]")
ERRORS = {
    "sign_in_failed": "Goose could not finish sign-in. Retry in a fresh browser tab.",
    "sign_in_timeout": "The five-minute sign-in window expired. Start again.",
    "model_failed": "The model request failed. Check the account connection and retry.",
    "model_unavailable": "This account could not use the selected model.",
    "model_timeout": "The model request exceeded the diagnostic time limit.",
    "unexpected_reply": "Goose did not return the expected completed reply.",
    "reauth_required": (
        "The saved login is no longer valid. Sign in with ChatGPT again."
    ),
}


def validate_authorize_url(value):
    """Accept only a native Goose PKCE URL for the reviewed provider and
    callback."""
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError("Invalid authorization URL")
    if any(ord(char) <= 32 or ord(char) >= 127 for char in value):
        raise ValueError("Invalid authorization URL")
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or url.netloc != "auth.openai.com"
        or url.path != "/oauth/authorize"
        or url.fragment
    ):
        raise ValueError("Invalid authorization URL")
    query = parse_qs(url.query, strict_parsing=True, keep_blank_values=True)
    if any(len(values) != 1 for values in query.values()):
        raise ValueError("Invalid authorization URL")
    expected = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "code_challenge_method": "S256",
    }
    if any(query.get(key) != [value] for key, value in expected.items()):
        raise ValueError("Invalid authorization URL")
    for key in ("state", "code_challenge"):
        items = query.get(key, [])
        if len(items) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{20,256}", items[0]):
            raise ValueError("Invalid authorization URL")
    return value


def valid_callback_path(value):
    if not isinstance(value, str) or len(value) > 8192:
        return False
    if any(ord(char) <= 32 or ord(char) >= 127 for char in value):
        return False
    try:
        url = urlsplit(value)
    except ValueError:
        return False
    return (
        not url.scheme
        and not url.netloc
        and not url.fragment
        and url.path == "/auth/callback"
    )


def parse_result(raw):
    """Export only a validated completion/usage, never arbitrary
    provider output."""
    if len(raw) > MAX_OUTPUT:
        raise ValueError("unexpected_reply")
    try:

        def unique_object(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError
                result[key] = item
            return result

        value = json.loads(raw, object_pairs_hook=unique_object)
        metadata = value["metadata"]
        if metadata.get("status") != "completed":
            raise ValueError
        messages = value["messages"]
        if not isinstance(messages, list) or not 1 <= len(messages) <= 50:
            raise ValueError
        for message in messages:
            if message.get("role") not in {"user", "assistant"}:
                raise ValueError
            content = message.get("content")
            if not isinstance(content, list) or any(
                item.get("type") != "text" or not isinstance(item.get("text"), str)
                for item in content
            ):
                raise ValueError
        assistants = [
            message for message in messages if message.get("role") == "assistant"
        ]
        if len(assistants) != 1 or messages[-1] is not assistants[0]:
            raise ValueError
        text = "".join(item["text"] for item in assistants[0]["content"]).strip()
        if text != "Connected.":
            raise ValueError
        usage = {}
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            number = metadata.get(key)
            if number is not None and (
                type(number) is not int or not 0 <= number <= 10**9
            ):
                raise ValueError
            usage[key] = number
        if not any(usage.values()):
            usage = dict.fromkeys(usage)
        return {"reply": "Connected.", "usage": usage}
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise ValueError("unexpected_reply") from None


def safe_error(code):
    return ERRORS.get(code, ERRORS["sign_in_failed"])


def stop_process(child):
    if child.poll() is None:
        os.killpg(child.pid, signal.SIGKILL)
    child.wait(timeout=5)


def environment():
    # Deliberately do not inherit any provider secrets or configuration.
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "TERM": "xterm-256color",
        "LANG": "C.UTF-8",
        "HOME": str(ROOT),
        "GOOSE_PATH_ROOT": str(ROOT),
        "GOOSE_DISABLE_KEYRING": "1",
        "GOOSE_TELEMETRY_OFF": "1",
        "GOOSE_TELEMETRY_ENABLED": "false",
        "CONTEXT_FILE_NAMES": "[]",
        "CHATGPT_CODEX_REASONING_EFFORT": "none",
        "BROWSER": "/usr/local/bin/capture-browser",
        "NO_PROXY": "127.0.0.1,localhost",
    }


def seed_config():
    (ROOT / "config").mkdir(parents=True, exist_ok=True, mode=0o700)
    (ROOT / "config/config.yaml").write_text(
        f"GOOSE_PROVIDER: chatgpt_codex\nGOOSE_MODEL: {MODEL}\n"
        "CHATGPT_CODEX_REASONING_EFFORT: none\nextensions: {}\n"
    )


class Probe:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"stage": "ready", "model": MODEL, "runs": []}
        self.busy = False
        self.csrf = secrets.token_urlsafe(32)

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def start(self):
        with self.lock:
            if self.busy:
                return False
            self.busy = True
            self.state = {"stage": "starting", "model": MODEL, "runs": []}
        try:
            AUTH_URL.unlink(missing_ok=True)
            threading.Thread(target=self.run, daemon=True).start()
            return True
        except Exception:
            with self.lock:
                self.busy = False
                self.state.update(
                    stage="failed",
                    error="sign_in_failed",
                    message=safe_error("sign_in_failed"),
                )
            return False

    def configure(self):
        master, slave = pty.openpty()
        child = subprocess.Popen(
            ["/usr/local/bin/goose", "configure"],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=ROOT,
            env=environment(),
            start_new_session=True,
        )
        os.close(slave)
        pending = b""
        prompts = [
            b"What would you like to configure?",
            b"Which model provider should we use?",
        ]
        deadline = time.monotonic() + 315
        try:
            while child.poll() is None and time.monotonic() < deadline:
                if AUTH_URL.exists():
                    validate_authorize_url(AUTH_URL.read_text())
                    self.update(stage="waiting_for_browser")
                if not select.select([master], [], [], 0.2)[0]:
                    continue
                try:
                    pending += os.read(master, 8192)
                except OSError:
                    break
                if len(pending) > MAX_OUTPUT:
                    raise ValueError("sign_in_failed")
                clean = ANSI.sub(b"", pending)
                if prompts and prompts[0] in clean:
                    prompts.pop(0)
                    os.write(master, b"\r")
                    pending = b""
                # Stop before configure's own extra (weather-tool) model test.
                if not prompts and b"Select a model:" in clean and TOKENS.is_file():
                    if stat.S_IMODE(TOKENS.stat().st_mode) != 0o600:
                        raise ValueError("sign_in_failed")
                    return
            code = (
                "sign_in_timeout" if time.monotonic() >= deadline else "sign_in_failed"
            )
            raise ValueError(code)
        finally:
            stop_process(child)
            os.close(master)
            AUTH_URL.unlink(missing_ok=True)

    def infer(self):
        child = subprocess.Popen(
            [
                "/usr/local/bin/goose",
                "run",
                "--no-profile",
                "--no-session",
                "--quiet",
                "--output-format",
                "json",
                "--max-turns",
                "1",
                "--max-tool-repetitions",
                "1",
                "--provider",
                "chatgpt_codex",
                "--model",
                MODEL,
                "-t",
                "Reply with exactly: Connected.",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=ROOT,
            env=environment(),
            start_new_session=True,
        )
        # Drain both pipes with strict aggregate bounds; never log their contents.
        streams = {child.stdout: bytearray(), child.stderr: bytearray()}
        deadline = time.monotonic() + 90
        try:
            active = set(streams)
            while active and time.monotonic() < deadline:
                # Goose can attempt browser OAuth after a cached-token refresh
                # fails. Stop this request; only a new user click starts sign-in.
                if AUTH_URL.exists():
                    raise ValueError("reauth_required")
                for pipe in select.select(list(active), [], [], 0.2)[0]:
                    data = os.read(pipe.fileno(), 8192)
                    if not data:
                        active.remove(pipe)
                    else:
                        streams[pipe].extend(data)
                    if sum(map(len, streams.values())) > MAX_OUTPUT:
                        raise ValueError("model_failed")
            if AUTH_URL.exists():
                raise ValueError("reauth_required")
            if active:
                raise ValueError("model_timeout")
            child.wait(timeout=2)
            if child.returncode:
                error = bytes(streams[child.stderr]).lower()
                unavailable = any(
                    part in error
                    for part in (
                        b"model_not_found",
                        b"not supported",
                        b"not have access",
                    )
                )
                raise ValueError("model_unavailable" if unavailable else "model_failed")
            return parse_result(bytes(streams[child.stdout]))
        finally:
            stop_process(child)
            for pipe in streams:
                pipe.close()

    def run(self):
        try:
            seed_config()
            if not TOKENS.is_file():
                self.configure()
            seed_config()
            results = []
            for index in range(2):
                self.update(stage="testing_model" if index == 0 else "testing_reuse")
                results.append(self.infer())
                self.update(runs=results.copy(), credentials="temporary_memory_only")
            self.update(stage="passed", cached_login_reused=True)
        except Exception as error:
            code = str(error) if str(error) in ERRORS else "sign_in_failed"
            if code == "reauth_required":
                try:
                    TOKENS.unlink(missing_ok=True)
                    AUTH_URL.unlink(missing_ok=True)
                except OSError:
                    code = "sign_in_failed"
                self.update(credentials=None)
            self.update(stage="failed", error=code, message=safe_error(code))
        finally:
            with self.lock:
                self.busy = False


class QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Never put auth URLs, callback codes or provider output in Docker logs.

    def reply(self, status, body, content_type="text/plain; charset=utf-8", **headers):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in headers.items():
            self.send_header(key.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(body)


class CallbackRelay(QuietHandler):
    def do_GET(self):
        if not valid_callback_path(self.path):
            self.reply(404, "Not found")
            return
        connection = http.client.HTTPConnection("127.0.0.1", 1455, timeout=10)
        try:
            connection.request("GET", self.path, headers={"Host": "localhost:1455"})
            response = connection.getresponse()
            body = response.read(64_001)
            if len(body) > 64_000:
                raise ValueError
            self.reply(response.status, body, "text/html; charset=utf-8")
        except (OSError, ValueError, http.client.HTTPException):
            self.reply(
                503, "Goose is not waiting for sign-in. Return to the test and retry."
            )
        finally:
            connection.close()


PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Goose · ChatGPT connection test</title>
<style nonce="NONCE">
body{font:17px/1.6 system-ui;background:#f4f5ef;color:#24463d;margin:0}
main{max-width:680px;margin:8vh auto;padding:36px;background:white;border-radius:24px}
h1{font-size:30px;line-height:1.25}button,a{font:inherit}button{background:#315e4a;
color:white;border:0;border-radius:8px;padding:12px 18px;cursor:pointer}
button:disabled{opacity:.5}a{color:#315e4a}pre{white-space:pre-wrap;font-size:14px}
small{color:#64766d}#status{padding:18px;background:#eef2eb;border-radius:12px}
</style><main><small>INDEPENDENT DOCKER DIAGNOSTIC · GOOSE 1.50.0</small>
<h1>Connect Goose to ChatGPT</h1>
<p>Sign in on ChatGPT’s website using your account. This test uses Goose’s own
browser login, with no API key.</p>
<p>After sign-in, Goose will make two tiny requests using <b>gpt-5.6-luna</b>:
one connection check and one check that a new Goose process can reuse the login.
These requests use your account allowance.</p>
<button id="start">Sign in with ChatGPT</button>
<a id="authorize" href="/authorize" target="_blank" rel="noreferrer" hidden>
Open ChatGPT sign-in ↗</a>
<p id="status" role="status">Ready.</p><pre id="results"></pre>
<small>Separate from Labcat. No files from your machine are mounted. No agent
tools are enabled. Login data is temporary and disappears when this container
stops. Account access to this model is checked by the actual requests.</small>
</main><script nonce="NONCE">
const labels={ready:'Ready.',starting:'Starting Goose…',
waiting_for_browser:'Continue on ChatGPT’s sign-in page. Link expires in five minutes.',
authenticated:'Signed in.',testing_model:'Testing a small model request…',
testing_reuse:'Testing login reuse in a new Goose process…',
passed:'Passed: both Goose requests completed using your ChatGPT login.'};
let loginWindow=null;
document.getElementById('start').onclick=async()=>{
  loginWindow=window.open('/waiting','goose-sign-in');
  const response=await fetch('/start',{method:'POST',
    headers:{'X-Probe-CSRF':'__TOKEN__'}});
  if(!response.ok){
    document.getElementById('status').textContent='Could not start. Reload and retry.';
  }
};
async function poll(){try{
  const state=await(await fetch('/status')).json();
  document.getElementById('status').textContent=state.message||labels[state.stage]||state.stage;
  document.getElementById('authorize').hidden=state.stage!=='waiting_for_browser';
  document.getElementById('start').disabled=!['ready','failed','passed'].includes(state.stage);
  document.getElementById('start').textContent=state.stage==='passed'?
    'Repeat connection test':
    state.credentials?'Retry model test':'Sign in with ChatGPT';
  document.getElementById('results').textContent=state.runs.length?JSON.stringify(state.runs,null,2):'';
}catch{document.getElementById('status').textContent='Test container is unavailable.';}}
poll();setInterval(poll,1500);
</script></html>"""


def handler_for(probe):
    class PageHandler(QuietHandler):
        def local_host(self):
            return len(self.headers.get_all("Host", [])) == 1 and bool(
                re.fullmatch(
                    r"(127\.0\.0\.1|localhost):[0-9]{1,5}",
                    self.headers.get("Host", ""),
                )
            )

        def do_POST(self):
            expected_origin = "http://" + self.headers.get("Host", "")
            if (
                not self.local_host()
                or self.path != "/start"
                or len(self.headers.get_all("Origin", [])) != 1
                or len(self.headers.get_all("X-Probe-CSRF", [])) != 1
                or self.headers.get("Origin") != expected_origin
                or self.headers.get("X-Probe-CSRF") != probe.csrf
            ):
                self.reply(403, "Forbidden")
                return
            self.reply(202 if probe.start() else 409, "")

        def do_GET(self):
            if not self.local_host():
                self.reply(403, "Forbidden")
            elif self.path == "/status":
                self.reply(200, json.dumps(probe.snapshot()), "application/json")
            elif self.path == "/authorize":
                try:
                    url = validate_authorize_url(AUTH_URL.read_text())
                    if probe.snapshot()["stage"] != "waiting_for_browser":
                        raise ValueError
                    self.reply(302, "", Location=url)
                except (OSError, ValueError):
                    self.reply(409, "Start sign-in from the diagnostic page first.")
            elif self.path in ("/", "/waiting"):
                nonce = secrets.token_urlsafe(24)
                page = PAGE.replace("NONCE", nonce).replace("__TOKEN__", probe.csrf)
                if self.path == "/waiting":
                    page = (
                        "<!doctype html><title>Opening ChatGPT sign-in</title>"
                        "<p>Waiting for Goose to open ChatGPT sign-in…</p>"
                        f'<script nonce="{nonce}">setInterval(async()=>{{'
                        'const s=await(await fetch("/status")).json();'
                        'if(s.stage==="waiting_for_browser")'
                        'location.replace("/authorize");'
                        'if(s.stage==="failed")document.querySelector("p").textContent='
                        "s.message;"
                        'if(["testing_model","testing_reuse"].includes(s.stage))'
                        'document.querySelector("p").textContent='
                        '"Goose is testing your saved connection…";'
                        'if(s.stage==="passed"){'
                        'document.querySelector("p").textContent='
                        '"Connection confirmed. Return to the diagnostic page.";'
                        "window.close();}"
                        "},700);</script>"
                    )
                policy = (
                    f"default-src 'none'; script-src 'nonce-{nonce}'; "
                    f"style-src 'nonce-{nonce}'; connect-src 'self'; "
                    "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
                )
                self.reply(
                    200,
                    page,
                    "text/html; charset=utf-8",
                    Content_Security_Policy=policy,
                )
            else:
                self.reply(404, "Not found")

    return PageHandler


def main():
    os.umask(0o077)
    if len(sys.argv) == 3 and sys.argv[1] == "capture":
        value = validate_authorize_url(sys.argv[2])
        temporary = AUTH_URL.with_suffix(".tmp")
        temporary.write_text(value)
        temporary.replace(AUTH_URL)
        return
    ROOT.mkdir(mode=0o700, exist_ok=True)
    probe = Probe()
    relay = ThreadingHTTPServer(("0.0.0.0", 1456), CallbackRelay)
    threading.Thread(target=relay.serve_forever, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", 8080), handler_for(probe))
    print("Independent Goose test ready; open the mapped loopback HTTP port.")
    server.serve_forever()


if __name__ == "__main__":
    main()
