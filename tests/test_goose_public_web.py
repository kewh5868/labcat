"""Offline, synthetic protocol/evidence tests for the standalone Goose
diagnostic."""

import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit


class PublicWebBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parents[1] / "scripts/smoke_goose_public_web.py"
        spec = importlib.util.spec_from_file_location("goose_web_probe_test", path)
        cls.harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.harness)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.trace = Path(self.directory.name) / "trace.jsonl"
        self.tools = self.harness.PublicTools(self.trace)

    def search(self, entries=None):
        return json.dumps(
            {
                "resultList": {
                    "result": (
                        entries
                        if entries is not None
                        else [
                            {
                                "pmcid": "PMC123",
                                "title": "Explicit synthetic test article",
                                "isOpenAccess": "Y",
                            }
                        ]
                    )
                }
            }
        ).encode()

    def article(self, identifier="123", *, body=True, license=True):
        return (
            '<article><front><article-meta><article-id pub-id-type="pmc">'
            + identifier
            + "</article-id>"
            + (
                "<permissions><license><license-p>"
                "Explicit synthetic open-access license notice."
                "</license-p></license></permissions>"
                if license
                else ""
            )
            + "</article-meta></front>"
            + (
                "<body><sec><p>This is an explicit synthetic passage for testing "
                "literal public text retrieval and citation verification without "
                "making any actual scientific claim or measurement.</p></sec></body>"
                if body
                else ""
            )
            + "</article>"
        ).encode()

    def issued(self):
        with patch.object(self.harness, "fetch", return_value=self.search()):
            return self.tools.call(
                "search_public_articles", {"query": "hydrogel biomaterials"}
            )

    def result(self, response):
        return {
            "metadata": {"status": "completed", "total_tokens": 17},
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": json.dumps(response)}],
                }
            ],
        }

    def test_search_is_fixed_public_endpoint_bounded_and_open_access_only(self):
        entries = [
            {"pmcid": "PMC123", "title": "Synthetic public entry", "isOpenAccess": "Y"},
            {"pmcid": "PMC456", "title": "Synthetic closed entry", "isOpenAccess": "N"},
            {
                "pmcid": "PMC789",
                "title": "Synthetic public entry two",
                "isOpenAccess": "Y",
            },
            {"pmcid": "PMC999", "title": "Beyond requested page", "isOpenAccess": "Y"},
        ]
        with patch.object(
            self.harness, "fetch", return_value=self.search(entries)
        ) as fetch:
            value = self.tools.call(
                "search_public_articles", {"query": "hydrogel biomaterials"}
            )
        self.assertEqual([row["id"] for row in value["results"]], ["PMC123", "PMC789"])
        path = fetch.call_args.args[0]
        self.assertEqual(urlsplit(path).path, "search")
        self.assertEqual(
            parse_qs(urlsplit(path).query),
            {
                "query": ["(hydrogel biomaterials) AND OPEN_ACCESS:Y"],
                "format": ["json"],
                "pageSize": ["3"],
            },
        )

    def test_invalid_urls_commands_extra_arguments_and_unissued_ids_never_fetch(self):
        calls = [
            ("shell", {"command": "cat tokens.json"}),
            ("search_public_articles", {"query": "https://private.invalid"}),
            (
                "search_public_articles",
                {"query": "hydrogel", "url": "https://private.invalid"},
            ),
            ("read_public_article", {"id": "PMC123"}),
            ("read_public_article", {"id": "../../config/chatgpt_codex/tokens.json"}),
            ("read_public_article", {"id": "https://private.invalid"}),
        ]
        with patch.object(self.harness, "fetch") as fetch:
            for name, arguments in calls:
                with (
                    self.subTest(name=name, arguments=arguments),
                    self.assertRaises(ValueError),
                ):
                    self.tools.call(name, arguments)
        fetch.assert_not_called()

    def test_malformed_search_entries_do_not_issue_unchecked_title_or_identifier(self):
        for changed in (
            {"title": 42},
            {"title": "x" * 2001},
            {"title": "Injected\nheader"},
            {"pmcid": []},
        ):
            entry = {
                "pmcid": "PMC123",
                "title": "Synthetic title",
                "isOpenAccess": "Y",
                **changed,
            }
            with (
                self.subTest(changed=changed),
                patch.object(self.harness, "fetch", return_value=self.search([entry])),
            ):
                self.assertEqual(
                    self.tools.call("search_public_articles", {"query": "hydrogel"})[
                        "results"
                    ],
                    [],
                )
        self.assertEqual(self.tools.issued, {})

    def test_fulltext_reads_literal_passage_license_identity_and_response_hash(self):
        self.issued()
        for identifier in ("123", "PMC123"):
            raw = self.article(identifier)
            with patch.object(self.harness, "fetch", return_value=raw) as fetch:
                source = self.tools.call("read_public_article", {"id": "PMC123"})
            fetch.assert_called_once_with("PMC123/fullTextXML")
            self.assertEqual(source["id"], "PMC123")
            self.assertEqual(source["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(source["bytes"], len(raw))
            self.assertEqual(source["url"], "https://europepmc.org/articles/PMC123")
            self.assertIn("synthetic passage", source["body_excerpt"])
            self.assertIn("synthetic open-access license", source["license"])

    def test_wrong_missing_conflicting_article_identity_never_becomes_source(self):
        for raw in (
            self.article("999"),
            self.article("invalid"),
            self.article().replace(b'pub-id-type="pmc"', b'pub-id-type="doi"'),
            self.article().replace(
                b"</article-meta>",
                b'<article-id pub-id-type="pmcid">PMC999</article-id></article-meta>',
            ),
        ):
            self.tools = self.harness.PublicTools(self.trace)
            self.issued()
            with (
                patch.object(self.harness, "fetch", return_value=raw),
                self.assertRaisesRegex(ValueError, "article_identity_mismatch"),
            ):
                self.tools.call("read_public_article", {"id": "PMC123"})
        self.assertNotIn('"source":', self.trace.read_text())

    def test_xml_entities_dtd_utf16_and_nul_rejected_before_parser(self):
        bad = [
            b"<!DOCTYPE article><article/>",
            b'<!ENTITY x "private">',
            "<!DOCTYPE article><article/>".encode("utf-16"),
            b"<article>\x00</article>",
        ]
        for raw in bad:
            self.tools = self.harness.PublicTools(self.trace)
            self.issued()
            with (
                patch.object(self.harness, "fetch", return_value=raw),
                patch.object(self.harness.ET, "fromstring") as parse,
                self.assertRaisesRegex(ValueError, "unsupported_xml"),
            ):
                self.tools.call("read_public_article", {"id": "PMC123"})
            parse.assert_not_called()

    def test_fulltext_requires_body_and_explicit_license_notice(self):
        for raw in (
            self.article(body=False),
            self.article(license=False),
            self.article().replace(
                b"<license-p>Explicit synthetic open-access license notice."
                b"</license-p>",
                b"",
            ),
        ):
            self.tools = self.harness.PublicTools(self.trace)
            self.issued()
            with (
                patch.object(self.harness, "fetch", return_value=raw),
                self.assertRaisesRegex(ValueError, "public_fulltext_unverified"),
            ):
                self.tools.call("read_public_article", {"id": "PMC123"})

    def test_tool_budget_includes_rejected_calls(self):
        self.issued()
        with patch.object(self.harness, "fetch") as fetch:
            for _ in range(3):
                with self.assertRaises(ValueError):
                    self.tools.call("unavailable", {})
            with self.assertRaisesRegex(ValueError, "tool_budget_exceeded"):
                self.tools.call("read_public_article", {"id": "PMC123"})
        fetch.assert_not_called()

    def test_quote_verification_requires_actual_trace_exact_title_url_and_substring(
        self,
    ):
        self.issued()
        with patch.object(self.harness, "fetch", return_value=self.article()):
            source = self.tools.call("read_public_article", {"id": "PMC123"})
        trace = [json.loads(line) for line in self.trace.read_text().splitlines()]
        response = {
            "title": source["title"],
            "url": source["url"],
            "quote": (
                "This is an explicit synthetic passage for testing "
                "literal public text retrieval"
            ),
        }
        self.assertEqual(
            self.harness.verify(self.result(response), trace, True)["response"],
            response,
        )
        for changed in (
            {"title": "Invented title"},
            {"url": "https://private.invalid"},
            {
                "quote": (
                    "This altered passage has enough words "
                    "but was never actually returned"
                )
            },
            {"extra": True},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.harness.verify(self.result({**response, **changed}), trace, True)
        with self.assertRaises(ValueError):
            self.harness.verify(self.result(response), [], True)

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_constants(self):
        for raw in (
            '{"status":"failed","status":"completed"}',
            '{"n":NaN}',
            '{"n":Infinity}',
            '{"x":{"n":1,"n":2}}',
        ):
            with (
                self.subTest(raw=raw),
                self.assertRaisesRegex(ValueError, "invalid_json"),
            ):
                self.harness.strict_json(raw)
        response = self.result(
            {"questions": ["Application?", "Properties?", "Constraints?"]}
        )
        response["messages"][0]["content"][0][
            "text"
        ] = '{"questions":[],"questions":["A?","B?","C?"]}'
        with self.assertRaisesRegex(ValueError, "invalid_json"):
            self.harness.verify(response, [], False)

    def test_mcp_only_advertises_two_tools_and_errors_do_not_echo_input(self):
        directory = Path(self.directory.name) / "web-test-fixture"
        directory.mkdir()
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "shell", "arguments": {"command": "PRIVATE_CANARY"}},
            },
            {"jsonrpc": "2.0", "id": 4, "method": "resources/list"},
        ]
        stream = io.TextIOWrapper(
            io.BytesIO("".join(json.dumps(row) + "\n" for row in messages).encode())
        )
        with (
            patch.object(self.harness, "ROOT", directory.parent),
            patch.dict(os.environ, {"GOOSE_WEB_TEST_DIR": str(directory)}),
            patch.object(self.harness.sys, "stdin", stream),
            patch.object(self.harness, "fetch") as fetch,
            redirect_stdout(io.StringIO()) as output,
        ):
            self.harness.mcp()
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([row["id"] for row in rows], [1, 2, 3, 4])
        self.assertEqual(
            [tool["name"] for tool in rows[1]["result"]["tools"]],
            ["search_public_articles", "read_public_article"],
        )
        self.assertEqual(rows[2]["error"]["message"], "Public source unavailable.")
        self.assertEqual(rows[3]["result"], {"resources": []})
        self.assertNotIn("PRIVATE_CANARY", output.getvalue())
        fetch.assert_not_called()

    def test_fetch_disables_proxies_redirects_and_bounds_bytes(self):
        reply = Mock()
        reply.read.return_value = b"synthetic public response"
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=reply)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch.object(self.harness, "build_opener", return_value=opener) as factory:
            self.assertEqual(
                self.harness.fetch("PMC123/fullTextXML"), reply.read.return_value
            )
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, self.harness.API + "PMC123/fullTextXML")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 25)
        self.assertEqual(factory.call_args.args[0].proxies, {})
        reply.read.assert_called_once_with(self.harness.MAX_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "source_redirect_rejected"):
            factory.call_args.args[1].redirect_request()
        reply.read.return_value = b"x" * (self.harness.MAX_BYTES + 1)
        with (
            patch.object(self.harness, "build_opener", return_value=opener),
            self.assertRaisesRegex(ValueError, "source_response_too_large"),
        ):
            self.harness.fetch("PMC123/fullTextXML")

    def test_model_process_has_only_approved_extension_and_clean_environment(
        self,
    ):
        with (
            patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "PRIVATE_CANARY",
                    "HTTPS_PROXY": "PRIVATE_CANARY",
                    "GOOSE_SEARCH_PATHS": "PRIVATE_CANARY",
                },
            ),
            patch.object(
                self.harness.subprocess, "Popen", side_effect=ValueError("fixture_stop")
            ) as process,
            self.assertRaisesRegex(ValueError, "fixture_stop"),
        ):
            self.harness.run_goose("gpt-5.5", Path(self.directory.name), True)
        arguments = process.call_args.args[0]
        self.assertEqual(arguments[arguments.index("--provider") + 1], "chatgpt_codex")
        self.assertEqual(arguments[arguments.index("--model") + 1], "gpt-5.5")
        self.assertIn("--no-profile", arguments)
        self.assertIn("--no-session", arguments)
        self.assertEqual(arguments.count("--with-extension"), 1)
        self.assertTrue(
            arguments[arguments.index("--with-extension") + 1].startswith(
                "public:python -I "
            )
        )
        self.assertNotIn("PRIVATE_CANARY", json.dumps(process.call_args.kwargs["env"]))
        self.assertEqual(process.call_args.kwargs["env"]["CONTEXT_FILE_NAMES"], "[]")

    def selection_fixture(self):
        self.issued()
        with patch.object(self.harness, "fetch", return_value=self.article()):
            source = self.tools.call("read_public_article", {"id": "PMC123"})
        trace = [json.loads(line) for line in self.trace.read_text().splitlines()]
        return source, trace

    def test_source_spans_are_computed_literal_bounded_nonoverlapping_ranges(self):
        excerpt = " ".join(f"fixture-word-{i}" for i in range(100))
        spans = self.harness.quote_spans(excerpt)
        self.assertEqual([span["quote_id"] for span in spans], ["q1", "q2", "q3"])
        previous_end = 0
        for span in spans:
            self.assertTrue(8 <= len(span["text"].split()) <= 12)
            self.assertEqual(span["text"], excerpt[span["start"] : span["end"]])
            self.assertGreaterEqual(span["start"], previous_end)
            previous_end = span["end"]
        self.assertEqual(
            self.harness.quote_spans("Only seven explicit fixture words are here"), []
        )
        self.assertEqual(
            len(self.harness.quote_spans(" ".join("word" for _ in range(20)))), 2
        )

    def test_selection_compiles_citation_only_from_registered_source_span(self):
        source, trace = self.selection_fixture()
        response = {"source_id": "PMC123", "quote_id": "q2"}
        verified = self.harness.verify(
            self.result(response), trace, True, selection=True
        )
        self.assertEqual(verified["agent_selection"], response)
        citation = verified["source_compiled_citation"]
        self.assertEqual(citation["quote"], source["quote_spans"][1]["text"])
        for field in ("title", "url", "retrieval_url", "retrieved_at"):
            self.assertEqual(citation[field], source[field])
        self.assertEqual(citation["response_sha256"], source["sha256"])
        self.assertNotIn(
            "response",
            verified,
            "selection and literal-copy modes have distinct result fields",
        )

    def test_selection_rejects_unknown_ids_and_all_model_supplied_citation_text(self):
        _source, trace = self.selection_fixture()
        selection = {"source_id": "PMC123", "quote_id": "q1"}
        for changed in (
            {"source_id": "PMC999"},
            {"source_id": "https://private.invalid"},
            {"quote_id": "q9"},
            {"quote_id": []},
            {"title": "Model supplied title"},
            {"quote": "Model supplied text"},
            {"url": "https://private.invalid"},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.harness.verify(
                    self.result({**selection, **changed}), trace, True, selection=True
                )

    def test_selection_rejects_missing_failed_or_ambiguous_tool_evidence(self):
        _source, trace = self.selection_fixture()
        response = self.result({"source_id": "PMC123", "quote_id": "q1"})
        for changed in (
            [],
            trace[1:],
            [trace[0], {**trace[1], "status": "failed"}],
            [trace[0], {**trace[1], "tool": "untrusted_model_output"}],
            [*trace, trace[1]],
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.harness.verify(response, changed, True, selection=True)

    def test_selection_rejects_a_changed_span_registry_instead_of_model_repair(self):
        _source, trace = self.selection_fixture()
        for field, value in (
            ("text", "Invented replacement quote"),
            ("start", 1),
            ("quote_id", "q9"),
        ):
            changed = json.loads(json.dumps(trace))
            changed[1]["source"]["quote_spans"][0][field] = value
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "invalid_span_registry"),
            ):
                self.harness.verify(
                    self.result({"source_id": "PMC123", "quote_id": "q1"}),
                    changed,
                    True,
                    selection=True,
                )

    def test_run_modes_retain_literal_validator_and_allow_one_selected_model(self):
        selection, runs = self.harness.run_options(["run"])
        self.assertTrue(selection)
        self.assertEqual(runs, [(model, True) for model in self.harness.MODELS])
        self.assertEqual(
            self.harness.run_options(["run", "--model", "gpt-5.6-terra"]),
            (True, [("gpt-5.6-terra", True)]),
        )
        literal, old_runs = self.harness.run_options(["runliteral"])
        self.assertFalse(literal)
        self.assertEqual(old_runs, [(self.harness.MODELS[0], False), *runs])
        source, trace = self.selection_fixture()
        copied = {
            "title": source["title"],
            "url": source["url"],
            "quote": "This altered passage has enough words but was never returned",
        }
        with self.assertRaisesRegex(ValueError, "quote_not_in_retrieved_fulltext"):
            self.harness.verify(self.result(copied), trace, True)
        with self.assertRaisesRegex(ValueError, "unexpected_answer_shape"):
            self.harness.verify(self.result(copied), trace, True, selection=True)

    def test_errors_use_fixed_identifiers_not_arbitrary_exception_text(self):
        self.assertEqual(
            self.harness.error_code(ValueError("model_timeout")), "model_timeout"
        )
        for error in (
            ValueError("private_secret"),
            ValueError("TOKEN=private"),
            OSError("model_timeout"),
        ):
            self.assertEqual(self.harness.error_code(error), "diagnostic_failed")


if __name__ == "__main__":
    unittest.main()
