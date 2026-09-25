"""Offline boundaries for the disposable, standard-library Goose login
harness."""

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlencode


@unittest.skipUnless(os.name == "posix", "The diagnostic runs in a Linux container")
class StandaloneBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parents[1] / "scripts/goose_chatgpt_standalone.py"
        spec = importlib.util.spec_from_file_location("goose_login_probe_test", path)
        cls.harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.harness)

    def authorize_url(self, **changes):
        fields = {
            "client_id": self.harness.CLIENT_ID,
            "redirect_uri": self.harness.REDIRECT,
            "response_type": "code",
            "code_challenge_method": "S256",
            "state": "s" * 32,
            "code_challenge": "c" * 43,
            "scope": "openid profile email offline_access",
            "originator": "goose",
        }
        fields.update(changes)
        return "https://auth.openai.com/oauth/authorize?" + urlencode(fields)

    def result(self, *, content=None, metadata=None, role="assistant"):
        return json.dumps(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "Reply Connected."}],
                    },
                    {
                        "role": role,
                        "content": (
                            content
                            if content is not None
                            else [{"type": "text", "text": "Connected."}]
                        ),
                    },
                ],
                "metadata": metadata or {"status": "completed", "total_tokens": 5},
            }
        ).encode()

    def handler(self, handler_class, path, *, headers=None):
        handler = handler_class.__new__(handler_class)
        handler.path = path
        handler.headers = Message()
        for name, value in headers or [("Host", "localhost:8080")]:
            handler.headers[name] = value
        handler.reply = Mock()
        return handler

    def test_authorization_url_accepts_native_pkce_and_optional_upstream_fields(self):
        value = self.authorize_url(id_token_add_organizations="true")
        self.assertEqual(self.harness.validate_authorize_url(value), value)

    def test_authorization_url_rejects_changed_security_parameters(self):
        for field, value in (
            ("client_id", "other-client"),
            ("redirect_uri", "http://localhost:9999/auth/callback"),
            ("redirect_uri", "https://private.example/callback"),
            ("response_type", "token"),
            ("code_challenge_method", "plain"),
            ("state", "short"),
            ("code_challenge", "c" * 257),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.harness.validate_authorize_url(
                    self.authorize_url(**{field: value})
                )

    def test_authorization_url_rejects_foreign_hosts_paths_fragments_and_controls(self):
        value = self.authorize_url()
        for bad in (
            value.replace("https:", "http:"),
            value.replace("auth.openai.com", "auth.openai.com.evil.example"),
            value.replace("auth.openai.com", "user@auth.openai.com"),
            value.replace("auth.openai.com", "auth.openai.com:443"),
            value.replace("/oauth/authorize", "/oauth/token"),
            value + "#fragment",
            value + "\n",
            value + "\x00",
            "x" * 8193,
        ):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                self.harness.validate_authorize_url(bad)

    def test_authorization_url_rejects_duplicated_required_fields_even_when_blank(self):
        for field in ("client_id", "redirect_uri", "state", "code_challenge"):
            for duplicate in ("", "different"):
                with (
                    self.subTest(field=field, duplicate=duplicate),
                    self.assertRaises(ValueError),
                ):
                    self.harness.validate_authorize_url(
                        self.authorize_url() + f"&{field}={duplicate}"
                    )

    def test_callback_accepts_only_bounded_relative_exact_path(self):
        self.assertTrue(
            self.harness.valid_callback_path("/auth/callback?code=opaque&state=opaque")
        )
        for value in (
            "/",
            "/status",
            "/auth/callback/",
            "/auth/%63allback",
            "/auth/callback#x",
            "https://example.org/auth/callback",
            "//example.org/auth/callback",
            "/auth/callback?code=ok\r\nHost: private",
            "/auth/callback?" + "x" * 8192,
            None,
        ):
            with self.subTest(value=value):
                self.assertFalse(self.harness.valid_callback_path(value))

    def test_result_requires_completed_exact_assistant_reply(self):
        result = self.harness.parse_result(self.result())
        self.assertEqual(
            result,
            {
                "reply": "Connected.",
                "usage": {
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": 5,
                },
            },
        )
        for raw in (
            self.result(role="user"),
            self.result(content=[{"type": "text", "text": "Not Connected."}]),
            self.result(content=[{"type": "text", "text": "Connected. extra text"}]),
            self.result(metadata={"status": "failed"}),
            b"provider error: Connected.",
            b"x" * (self.harness.MAX_OUTPUT + 1),
        ):
            with (
                self.subTest(raw=raw[:100]),
                self.assertRaisesRegex(ValueError, "^unexpected_reply$"),
            ):
                self.harness.parse_result(raw)

    def test_result_rejects_tool_calls_tool_results_and_multiple_assistants(self):
        for kind in ("toolRequest", "toolResponse", "thinking"):
            raw = self.result(
                content=[
                    {"type": "text", "text": "Connected."},
                    {"type": kind, "text": "private-provider-content"},
                ]
            )
            with (
                self.subTest(kind=kind),
                self.assertRaisesRegex(ValueError, "^unexpected_reply$"),
            ):
                self.harness.parse_result(raw)
        value = json.loads(self.result())
        value["messages"].append(
            {"role": "assistant", "content": [{"type": "text", "text": ""}]}
        )
        with self.assertRaisesRegex(ValueError, "^unexpected_reply$"):
            self.harness.parse_result(json.dumps(value).encode())

    def test_result_rejects_duplicate_json_keys(self):
        for raw in (
            self.result().replace(
                b'"status": "completed"', b'"status":"failed","status":"completed"'
            ),
            self.result().replace(
                b'"text": "Connected."', b'"text":"not connected","text":"Connected."'
            ),
        ):
            with (
                self.subTest(raw=raw),
                self.assertRaisesRegex(ValueError, "^unexpected_reply$"),
            ):
                self.harness.parse_result(raw)

    def test_result_rejects_tool_blocks_in_user_messages(self):
        for kind in ("toolRequest", "toolResponse"):
            value = json.loads(self.result())
            value["messages"][0]["content"].append(
                {"type": kind, "text": "private-tool-response"}
            )
            with (
                self.subTest(kind=kind),
                self.assertRaisesRegex(ValueError, "^unexpected_reply$"),
            ):
                self.harness.parse_result(json.dumps(value).encode())

    def test_result_requires_assistant_to_be_the_final_message(self):
        value = json.loads(self.result())
        value["messages"].append(
            {"role": "user", "content": [{"type": "text", "text": "Connected."}]}
        )
        with self.assertRaisesRegex(ValueError, "^unexpected_reply$"):
            self.harness.parse_result(json.dumps(value).encode())

    def test_result_deep_json_returns_safe_validation_error(self):
        raw = b"[" * 2000 + b"0" + b"]" * 2000
        with self.assertRaisesRegex(ValueError, "^unexpected_reply$"):
            self.harness.parse_result(raw)

    def test_result_rejects_malformed_messages_without_reflecting_contents(self):
        for messages in (
            {},
            [],
            ["private-malformed-message"],
            [{"role": "assistant", "content": "Connected."}],
            [{"role": "assistant", "content": ["private-malformed-block"]}],
            [{"role": "tool", "content": [{"type": "text", "text": "Connected."}]}],
        ):
            value = json.loads(self.result())
            value["messages"] = messages
            with (
                self.subTest(messages=messages),
                self.assertRaisesRegex(ValueError, "^unexpected_reply$"),
            ):
                self.harness.parse_result(json.dumps(value).encode())

    def test_result_usage_is_bounded_numeric_or_unavailable(self):
        for number in (True, -1, "3", 1.5, 10**10):
            with (
                self.subTest(number=number),
                self.assertRaisesRegex(ValueError, "^unexpected_reply$"),
            ):
                self.harness.parse_result(
                    self.result(
                        metadata={"status": "completed", "total_tokens": number}
                    )
                )
        result = self.harness.parse_result(
            self.result(metadata={"status": "completed", "total_tokens": 0})
        )
        self.assertTrue(all(value is None for value in result["usage"].values()))

    def test_safe_errors_never_reveal_arbitrary_provider_text(self):
        private = "Bearer private-provider-secret; account private@example.invalid"
        self.assertNotIn(private, self.harness.safe_error(private))
        probe = self.harness.Probe()
        with patch.object(
            self.harness, "seed_config", side_effect=RuntimeError(private)
        ):
            probe.run()
        self.assertEqual(probe.snapshot()["stage"], "failed")
        self.assertNotIn(private, json.dumps(probe.snapshot()))
        self.assertFalse(probe.busy)

    def test_start_clears_busy_when_url_cleanup_or_thread_start_fails(self):
        for fail_cleanup in (True, False):
            probe = self.harness.Probe()
            url = Mock()
            if fail_cleanup:
                url.unlink.side_effect = OSError("private-filesystem-error")
            thread = Mock()
            thread.start.side_effect = RuntimeError("private-thread-error")
            with (
                self.subTest(fail_cleanup=fail_cleanup),
                patch.object(self.harness, "AUTH_URL", url),
                patch.object(self.harness.threading, "Thread", return_value=thread),
            ):
                self.assertFalse(probe.start())
            self.assertFalse(probe.busy)
            self.assertEqual(probe.snapshot()["stage"], "failed")
            self.assertNotIn("private-", json.dumps(probe.snapshot()))

    def test_inference_stops_hidden_browser_reauthentication(self):
        child = Mock()
        url = Mock()
        url.exists.return_value = True
        probe = self.harness.Probe()
        with (
            patch.object(self.harness, "AUTH_URL", url),
            patch.object(self.harness.subprocess, "Popen", return_value=child),
            patch.object(self.harness, "stop_process") as stop,
            patch.object(self.harness.select, "select") as select_io,
            self.assertRaisesRegex(ValueError, "^reauth_required$"),
        ):
            probe.infer()
        stop.assert_called_once_with(child)
        select_io.assert_not_called()
        child.stdout.close.assert_called_once()
        child.stderr.close.assert_called_once()

    def test_expired_login_clears_only_temporary_cache_and_waits_for_user_retry(self):
        probe = self.harness.Probe()
        with tempfile.TemporaryDirectory() as temporary:
            tokens = Path(temporary) / "tokens.json"
            browser = Path(temporary) / "browser-url"
            tokens.write_text("synthetic-expired-token-placeholder")
            browser.write_text(self.authorize_url())
            with (
                patch.object(self.harness, "TOKENS", tokens),
                patch.object(self.harness, "AUTH_URL", browser),
                patch.object(self.harness, "seed_config"),
                patch.object(probe, "configure") as configure,
                patch.object(
                    probe, "infer", side_effect=ValueError("reauth_required")
                ) as infer,
            ):
                probe.run()
            infer.assert_called_once()
            configure.assert_not_called()
            self.assertFalse(tokens.exists())
            self.assertFalse(browser.exists())
        state = probe.snapshot()
        self.assertEqual(state["stage"], "failed")
        self.assertEqual(state["error"], "reauth_required")
        self.assertFalse(state.get("credentials"))
        self.assertEqual(state["runs"], [])
        self.assertFalse(probe.busy)

    def test_cached_file_is_not_authentication_until_first_real_result(self):
        probe = self.harness.Probe()
        snapshots = []
        result = {"reply": "Connected.", "usage": {"total_tokens": 5}}

        def infer():
            snapshots.append(probe.snapshot())
            return result

        tokens = Mock()
        tokens.is_file.return_value = True
        with (
            patch.object(self.harness, "TOKENS", tokens),
            patch.object(self.harness, "seed_config"),
            patch.object(probe, "configure") as configure,
            patch.object(probe, "infer", side_effect=infer),
        ):
            probe.run()
        configure.assert_not_called()
        self.assertEqual(len(snapshots), 2)
        self.assertFalse(snapshots[0].get("credentials"))
        self.assertEqual(snapshots[0]["stage"], "testing_model")
        self.assertEqual(snapshots[1]["credentials"], "temporary_memory_only")
        self.assertEqual(snapshots[1]["stage"], "testing_reuse")
        self.assertEqual(probe.snapshot()["stage"], "passed")

    def test_child_environment_never_inherits_accounts_endpoints_or_extensions(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "private-canary",
                "AWS_PROFILE": "private-canary",
                "HTTPS_PROXY": "private-canary",
                "GOOSE_SEARCH_PATHS": "private-canary",
                "BROWSER": "private-canary",
            },
        ):
            environment = self.harness.environment()
        self.assertNotIn("private-canary", json.dumps(environment))
        self.assertEqual(environment["GOOSE_PATH_ROOT"], str(self.harness.ROOT))
        self.assertEqual(environment["CONTEXT_FILE_NAMES"], "[]")

    def test_callback_relay_uses_one_fixed_loopback_destination_and_no_auth_logging(
        self,
    ):
        handler = self.handler(
            self.harness.CallbackRelay,
            "/auth/callback?code=private-code&state=private-state",
        )
        connection = Mock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = b"accepted"
        with patch.object(
            self.harness.http.client, "HTTPConnection", return_value=connection
        ) as factory:
            with (
                redirect_stdout(io.StringIO()) as out,
                redirect_stderr(io.StringIO()) as err,
            ):
                handler.do_GET()
                handler.log_message("private-code")
        factory.assert_called_once_with("127.0.0.1", 1455, timeout=10)
        connection.request.assert_called_once_with(
            "GET", handler.path, headers={"Host": "localhost:1455"}
        )
        connection.getresponse.return_value.read.assert_called_once_with(64_001)
        connection.close.assert_called_once()
        self.assertEqual(out.getvalue() + err.getvalue(), "")

    def test_callback_relay_rejects_other_paths_before_network(self):
        with patch.object(self.harness.http.client, "HTTPConnection") as factory:
            handler = self.handler(self.harness.CallbackRelay, "/api/private")
            handler.do_GET()
        factory.assert_not_called()
        self.assertEqual(handler.reply.call_args.args[0], 404)

    def test_callback_relay_bounds_response_and_does_not_reflect_network_failure(self):
        for response in (b"private-canary" * 6000, OSError("private-canary")):
            connection = Mock()
            if isinstance(response, Exception):
                connection.request.side_effect = response
            else:
                connection.getresponse.return_value.read.return_value = response
            handler = self.handler(self.harness.CallbackRelay, "/auth/callback")
            with patch.object(
                self.harness.http.client, "HTTPConnection", return_value=connection
            ):
                handler.do_GET()
            self.assertEqual(handler.reply.call_args.args[0], 503)
            self.assertNotIn("private-canary", str(handler.reply.call_args))
            connection.close.assert_called_once()

    def test_start_requires_matching_origin_host_and_csrf(self):
        probe = self.harness.Probe()
        probe.start = Mock(return_value=True)
        headers = [
            ("Host", "localhost:8080"),
            ("Origin", "http://localhost:8080"),
            ("X-Probe-CSRF", probe.csrf),
        ]
        handler_class = self.harness.handler_for(probe)
        for changed in (
            headers[:2],
            [headers[0], ("Origin", "https://evil.example"), headers[2]],
            [("Host", "private.example:8080"), *headers[1:]],
            [*headers, ("X-Probe-CSRF", "duplicate")],
            [*headers, ("Host", "private.example:8080")],
        ):
            with self.subTest(headers=changed):
                handler = self.handler(handler_class, "/start", headers=changed)
                handler.do_POST()
                self.assertEqual(handler.reply.call_args.args[0], 403)
        probe.start.assert_not_called()
        handler = self.handler(handler_class, "/start", headers=headers)
        handler.do_POST()
        self.assertEqual(handler.reply.call_args.args[0], 202)
        probe.start.assert_called_once()

    def test_page_csrf_replacement_preserves_header_name(self):
        probe = self.harness.Probe()
        handler = self.handler(self.harness.handler_for(probe), "/")
        handler.do_GET()
        page = handler.reply.call_args.args[1]
        self.assertIn("'X-Probe-CSRF'", page)
        self.assertIn(probe.csrf, page)
        self.assertIn(
            "frame-ancestors 'none'",
            handler.reply.call_args.kwargs["Content_Security_Policy"],
        )

    def test_authorize_redirect_is_official_and_requires_waiting_state(self):
        probe = self.harness.Probe()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "browser-url"
            path.write_text(self.authorize_url())
            with patch.object(self.harness, "AUTH_URL", path):
                handler = self.handler(self.harness.handler_for(probe), "/authorize")
                handler.do_GET()
                self.assertEqual(handler.reply.call_args.args[0], 409)
                probe.update(stage="waiting_for_browser")
                handler.do_GET()
                self.assertEqual(handler.reply.call_args.args[0], 302)
                self.assertEqual(
                    handler.reply.call_args.kwargs["Location"], self.authorize_url()
                )
                path.write_text("https://evil.example/collect")
                handler.do_GET()
                self.assertEqual(handler.reply.call_args.args[0], 409)


if __name__ == "__main__":
    unittest.main()
