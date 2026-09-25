"""Exercise the actual embedded Goose CLI against a local fake model.

Run inside the image with --network none. The test-only endpoint
override is installed in this process; production configuration has no
arbitrary-host input. No real provider, credentials, model billing, or
scientific evidence is used.
"""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from labcat import goose_runtime
from labcat.provider_catalog import CHAT_COMPLETION_ROUTES


class TestTools:
    build_plan = {"steps": ["search_public_references", "generate_ranked_report"]}

    def __init__(self):
        self.calls = []

    def tool_definitions(self):
        return [
            {
                "name": name,
                "description": "Return a fixed test completion status.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            }
            for name in self.build_plan["steps"]
        ]

    def call(self, name, arguments):
        assert name in self.build_plan["steps"] and arguments == {}
        self.calls.append(name)
        return {"status": "completed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider", choices=["openai", *CHAT_COMPLETION_ROUTES], default="openai"
    )
    selected = parser.parse_args().provider
    expected_path = CHAT_COMPLETION_ROUTES.get(
        selected, ("https://api.openai.com", "/v1/chat/completions")
    )[1]
    requests = []
    forbidden_file = Path("/tmp/labcat-goose-forbidden-tool")
    assert not forbidden_file.exists()
    expected = {
        "labcat__search_public_references",
        "labcat__generate_ranked_report",
    }

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path != expected_path.replace("chat/completions", "models"):
                self.send_error(400, "Unexpected metadata path")
                return
            body = json.dumps({"object": "list", "data": [{"id": "gpt-4o"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != expected_path:
                self.send_error(400, "Unexpected inference path")
                return
            if self.headers.get("Authorization") != "Bearer test-only-key":
                self.send_error(401, "Unexpected synthetic credential")
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            names = {tool["function"]["name"] for tool in body.get("tools", [])}
            if names != expected:
                self.send_error(400, "Unexpected tools")
                return
            turn = len(requests)
            if turn <= 3:
                name = (
                    "developer__shell"
                    if turn == 1
                    else (
                        "labcat__search_public_references"
                        if turn == 2
                        else "labcat__generate_ranked_report"
                    )
                )
                arguments = (
                    {"command": "touch /tmp/labcat-goose-forbidden-tool"}
                    if turn == 1
                    else {}
                )
                delta = {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": f"call_{turn}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                }
                reason = "tool_calls"
            else:
                delta = {
                    "role": "assistant",
                    "content": "DO NOT TRUST THIS MODEL REPORT",
                }
                reason = "stop"
            chunks = [
                {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": reason}]},
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 10,
                        "total_tokens": 110,
                    },
                },
            ]
            for item in chunks:
                item["model"] = "gpt-4o"
            raw = "".join("data: " + json.dumps(item) + "\n\n" for item in chunks)
            raw = (raw + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original = goose_runtime._environment

    def environment(*args):
        provider, env = original(*args)
        env["OPENAI_HOST"] = f"http://127.0.0.1:{server.server_port}"
        return provider, env

    goose_runtime._environment = environment
    session = TestTools()
    try:
        result = goose_runtime.run_goose(
            {"provider": selected, "model": "gpt-4o", "allow_paid_inference": True},
            "test-only-key",
            "Run the public research Build Plan.",
            tool_session=session,
        )
        assert session.calls == ["search_public_references", "generate_ranked_report"]
        assert len(requests) == 4, len(requests)
        assert not forbidden_file.exists()
        assert result["usage"]["input_tokens"] == 400, result
        assert result["usage"]["output_tokens"] == 40, result
        assert "DO NOT TRUST" not in json.dumps(result)
        assert all(set(item) == {"tool", "status"} for item in result["tool_trace"])
        print(
            f"Actual Goose CLI passed for {selected} at {expected_path}: "
            "only approved MCP tools, blocked shell "
            "request, two research tool calls, run usage, discarded model prose."
        )
    finally:
        goose_runtime._environment = original
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
