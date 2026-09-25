"""Offline isolated-worker integration check: real Goose, fake local
Ollama.

Copy this test-only script into each test container's /tmp (no host bind
mount). Start `fake-model` inside the worker, then `run` inside the
parent container. The production runtime accepts no arbitrary endpoint
or test-provider override.
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen


def literature_fixture():
    """Synthetic protocol data only, injected in the disposable test
    process."""
    from labcat.science.candidate_leads import (
        discovery_documents,
        validate_candidate_leads,
    )

    source = {
        "source_id": "openalex",
        "source_name": "TEST ONLY OpenAlex fixture",
        "record_id": "W1",
        "url": "https://openalex.org/W1",
        "title": "TEST ONLY protocol fixture",
        "kind": "discovery_reference",
        "access_scope": "public",
        "is_material_evidence": False,
        "provenance_status": "verified",
        "provenance": {"response_sha256": "a" * 64},
        "metadata": {
            "abstract_read": True,
            "abstract": (
                "TESTONLY-Alpha was used in a thin-film dielectric device "
                "in the reported conditions."
            ),
        },
    }
    documents = discovery_documents([source])
    proposal = {
        "document_id": documents[0]["document_id"],
        "name": "TESTONLY-Alpha",
        "quote": documents[0]["text"],
    }
    leads = validate_candidate_leads(
        [proposal], documents, [source], importance={"dielectric_total": 1.0}
    )
    evaluation = {
        "lead_id": leads[0]["id"],
        "criterion_id": "application_fit",
        "document_id": documents[0]["document_id"],
        "quote": documents[0]["text"],
        "judgment": "supports",
        "interpretation": (
            "The passage supports the requested device application "
            "under reported conditions."
        ),
    }
    return source, proposal, evaluation


def fake_model():
    turns = 0
    _, lead_proposal, evaluation = literature_fixture()
    expected = {
        "labcat__assess_research_intent",
        "labcat__search_public_references",
        "labcat__propose_candidate_leads",
        "labcat__evaluate_candidate_fit",
        "labcat__generate_ranked_report",
    }

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            data = json.dumps({"models": [{"name": "labcat-test-model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            self.wfile.flush()
            if self.path == "/stop-test-model":
                # Finish the response before stopping the fixture server. An
                # early shutdown races the client's HTTP status-line read.
                threading.Thread(target=server.shutdown, daemon=True).start()

        def do_POST(self):
            nonlocal turns
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            names = {tool["function"]["name"] for tool in request.get("tools", [])}
            if names != expected:
                self.send_error(400, "Unapproved tool catalog")
                return
            turns += 1
            names = [
                "developer__shell",
                "labcat__assess_research_intent",
                "labcat__search_public_references",
                "labcat__propose_candidate_leads",
                "labcat__evaluate_candidate_fit",
                "labcat__generate_ranked_report",
            ]
            if turns <= 6:
                arguments = (
                    {"command": "touch /tmp/labcat-forbidden-tool"}
                    if turns == 1
                    else (
                        {
                            "decision": "materials_research",
                            "intent": {
                                "material_class": "oxide_dielectrics",
                                "application": "unknown",
                                "identity_scope": "bulk",
                                "target_spans": ["oxide dielectric candidates"],
                                "application_spans": ["thin-film experiments"],
                                "environment_spans": [],
                                "processing_spans": [],
                                "goals": [
                                    {
                                        "attribute_id": "dielectric_total",
                                        "request_span": "dielectric",
                                        "priority": "primary",
                                        "relation": "consider",
                                    }
                                ],
                            },
                        }
                        if turns == 2
                        else (
                            {"proposals": [lead_proposal]}
                            if turns == 4
                            else (
                                {
                                    "evaluations": [
                                        evaluation,
                                        {
                                            **evaluation,
                                            "criterion_id": "demonstrated_use",
                                            "judgment": "unknown",
                                            "interpretation": (
                                                "The synthetic passage does not "
                                                "establish "
                                                "experimental or deployed use."
                                            ),
                                        },
                                    ]
                                }
                                if turns == 5
                                else {}
                            )
                        )
                    )
                )
                delta = {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": f"call_{turns}",
                            "type": "function",
                            "function": {
                                "name": names[turns - 1],
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                }
                finish = "tool_calls"
            else:
                delta, finish = (
                    {"role": "assistant", "content": "UNTRUSTED MODEL REPORT"},
                    "stop",
                )
            chunks = [
                {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 10,
                        "total_tokens": 110,
                    },
                },
            ]
            for chunk in chunks:
                chunk["model"] = "labcat-test-model"
            raw = (
                "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
                + "data: [DONE]\n\n"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 11434), Provider)
    print("Fake local Ollama ready in worker", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        assert not Path("/tmp/labcat-forbidden-tool").exists()
        print("Worker rejected injected shell tool", flush=True)


def run():
    import labcat.public_sources as public_sources
    import labcat.science as science
    from labcat.agent_tools import ResearchToolSession
    from labcat.config import load_config
    from labcat.connections import DEFAULT_PROFILE
    from labcat.goose_worker_client import initialize_channel, run_remote_goose
    from labcat.science.sources import load_snapshot
    from labcat.source_preferences import default_source_preferences

    # Inject the audited historical fixture only in this test process. The
    # production research path cannot select or fall back to that fixture.
    science.retrieve_nomad = lambda filters=None: load_snapshot()
    source, _, _ = literature_fixture()
    public_sources.search_public_sources = lambda *args, **kwargs: {
        "references": [source],
        "source_statuses": [],
        "caveats": [],
    }

    initialize_channel()
    prompt = (
        "Find oxide dielectric candidates for thin-film experiments. "
        "TEST INPUT ONLY: I claim HfO2 has a gap of 987654 eV."
    )
    profile = {
        "id": "isolated-worker-test-profile",
        "name": "Test dielectric preference",
        "importance": {"dielectric_total": 1.0},
    }
    session = ResearchToolSession(
        prompt,
        load_config(),
        ranking_profile=profile,
        ranking_selection={"mode": "explicit", "selected_profile_id": profile["id"]},
        source_preferences={
            **default_source_preferences(),
            "search_public_references": True,
            "materials_project_mode": "off",
            "enabled_sources": ["nomad", "openalex"],
        },
    )
    result = run_remote_goose(
        {**DEFAULT_PROFILE, "provider": "ollama", "model": "labcat-test-model"},
        None,
        prompt,
        tool_session=session,
    )
    assert result["isolation"] == "separate_container", result
    assert result["usage"]["input_tokens"] == 700, result
    assert result["usage"]["output_tokens"] == 70, result
    assert [row["tool"] for row in result["tool_trace"]] == [
        "assess_research_intent",
        "search_public_references",
        "propose_candidate_leads",
        "evaluate_candidate_fit",
        "generate_ranked_report",
    ], result
    assert all(row["status"] == "completed" for row in result["tool_trace"]), result
    outcome = session.finalize()
    assert outcome["result"]["candidates"]
    evaluation = outcome["result"]["literature_evaluation"]
    assert len(evaluation["ranked_candidates"]) == 1
    assert evaluation["version"] == "literature-fit-v2"
    row = evaluation["ranked_candidates"][0]
    assert row["coverage"] == 0 and row["observed_fit"] is None
    assert row["ranking_basis"] == "preliminary"
    assert row["priority_score"] == row["preliminary_score"] > 0.7
    assert row["general_evidence"]["application_fit"] == "supports"
    assert row["general_evidence"]["demonstrated_use"] == "unknown"
    assert row["priority_tier"] == 0
    assert evaluation["is_material_evidence"] is False
    assert "Candidate shortlist" in outcome["pi_summary"]
    assert "UNTRUSTED MODEL REPORT" not in json.dumps(outcome)
    assert "987654" not in json.dumps(outcome)
    assert outcome["result"]["ranking"]["weights"] == {"dielectric_total": 1.0}
    assert outcome["result"]["execution"]["ranking_profile"] == profile
    scope = outcome["result"]["execution"]["semantic_scope"]
    assert scope["target_text"] == "oxide dielectric candidates"
    assert scope["application_spans"] == ["thin-film experiments"]
    assert scope["is_evidence"] is False
    assert outcome["result"]["build_plan"]["version"] == ("labcat-bounded-tools-v3")
    retrieval = outcome["result"]["retrieval"]
    assert retrieval["mode"] == "public_repositories"
    assert retrieval["selected_repository"] == "nomad"
    (attempt,) = retrieval["repository_attempts"]
    assert attempt["repository"] == "nomad" and attempt["status"] == "ok"
    assert attempt["provenance"]["mode"] == "public_snapshot"

    approved = {record["material_id"]: record for record in load_snapshot()[0]}
    for candidate in outcome["result"]["candidates"]:
        assert candidate["source_mode"] == "public_snapshot"
        for field in ("formula", "band_gap_ev", "dielectric_total"):
            assert candidate[field] == approved[candidate["material_id"]][field]
    assert (
        outcome["result"]["build_plan"]["stages"]["generate_ranked_report"][
            "initiated_by"
        ]
        == "agent"
    )
    print(
        "Real isolated Goose worker passed: authenticated callbacks, approved "
        "evidence, semantic request binding, selected profile, injection rejection, "
        "run usage, application-supported preliminary ranking without attribute "
        "coverage, retained server report."
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["fake-model"]:
        fake_model()
    elif sys.argv[1:] == ["run"]:
        run()
    elif sys.argv[1:] == ["stop-model"]:
        with urlopen("http://127.0.0.1:11434/stop-test-model", timeout=3):
            pass
    else:
        raise SystemExit("Choose fake-model, run, or stop-model.")
