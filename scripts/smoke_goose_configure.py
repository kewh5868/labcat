"""Exercise upstream Goose's real interactive configure flow with fake
credentials.

Run in a disposable, network-none container with only /tmp tmpfs. This
test uses no Labcat server, app workspace, actual provider account, or
host credential. The fake endpoint is test-only; it is not an
application setting.
"""

import json
import os
import pty
import re
import select
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Provider(BaseHTTPRequestHandler):
    calls = 0

    def log_message(self, *_):
        pass

    def do_GET(self):
        self.reply({"object": "list", "data": [{"id": "gpt-4o"}]})

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert request["model"] == "gpt-4o"
        assert {tool["function"]["name"] for tool in request.get("tools", [])} == {
            "get_weather"
        }
        type(self).calls += 1
        response = {
            "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": "Connected"}}
            ],
            "model": "gpt-4o",
        }
        raw = ("data: " + json.dumps(response) + "\n\ndata: [DONE]\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def reply(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="goose-configure-test-") as temporary:
            folder = Path(temporary)
            (folder / "config").mkdir(mode=0o700)
            configuration = folder / "config/config.yaml"
            configuration.write_text("GOOSE_PROVIDER: openai\nGOOSE_MODEL: gpt-4o\n")
            env = {
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "TERM": "xterm-256color",
                "LANG": "C.UTF-8",
                "HOME": temporary,
                "GOOSE_PATH_ROOT": temporary,
                "GOOSE_DISABLE_KEYRING": "1",
                "GOOSE_TELEMETRY_OFF": "1",
                "GOOSE_TELEMETRY_ENABLED": "false",
                "CONTEXT_FILE_NAMES": "[]",
                "OPENAI_API_KEY": "fake-test-credential-never-a-real-account",
                "OPENAI_HOST": f"http://127.0.0.1:{server.server_port}",
                "NO_PROXY": "127.0.0.1,localhost",
            }
            master, slave = pty.openpty()
            child = subprocess.Popen(
                ["/usr/local/bin/goose", "configure"],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=env,
                cwd=temporary,
                close_fds=True,
            )
            os.close(slave)
            transcript = b""
            pending = b""
            prompts = [
                ("What would you like to configure?", b"\r"),
                ("Which model provider should we use?", b"\r"),
                ("Would you like to save this value to your keyring?", b"\x1b[C\r"),
                ("Would you like to configure advanced settings?", b"\r"),
                ("Select a model:", b"\r"),
            ]
            deadline = time.monotonic() + 40
            try:
                while child.poll() is None and time.monotonic() < deadline:
                    if not select.select([master], [], [], 0.2)[0]:
                        continue
                    try:
                        chunk = os.read(master, 8192)
                    except OSError:
                        break
                    transcript += chunk
                    pending += chunk
                    if len(transcript) > 100_000:
                        raise AssertionError("Configure output exceeded test budget")
                    clean = re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", pending)
                    if prompts and prompts[0][0].encode() in clean:
                        _, answer = prompts.pop(0)
                        os.write(master, answer)
                        pending = b""
                child.wait(timeout=2)
                if prompts or child.returncode:
                    # This transcript contains only synthetic test values.
                    raise AssertionError(transcript.decode(errors="replace"))
                assert Provider.calls == 1, Provider.calls
                assert "openai" in configuration.read_text()
                assert "gpt-4o" in configuration.read_text()
                assert not (folder / "config/secrets.yaml").exists()
                print(
                    "Actual Goose configure passed: provider selection, synthetic "
                    "credential prompt, model list, one simulated connection test, "
                    "private temporary config, no saved credentials."
                )
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=2)
                os.close(master)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
