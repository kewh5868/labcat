"""Actual phase changes are correlated to one chat submission, never
fabricated."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from labcat.research_progress import (
    ResearchInProgress,
    ResearchProgress,
    current_observer,
    progress_observer,
    report_progress,
)
from labcat.web import create_app


def test_tracker_propagates_across_tool_threads_without_prompt_or_exception_text():
    progress = ResearchProgress()
    run_id = str(uuid4())
    with pytest.raises(ValueError, match="PRIVATE TEST DETAIL"):
        with progress.track("chat", run_id):
            observer = current_observer()

            def tool():
                with progress_observer(observer):
                    report_progress("discovery")

            with ThreadPoolExecutor() as pool:
                pool.submit(tool).result()
            state = progress.snapshot("chat", run_id)
            assert state["phase"] == "discovery"
            assert state["sequence"] == 2
            assert progress.snapshot("chat", str(uuid4()))["status"] == "idle"
            with pytest.raises(ResearchInProgress):
                with progress.track("chat"):
                    pytest.fail("Overlapping research must be rejected")
            raise ValueError("PRIVATE TEST DETAIL")
    state = progress.snapshot("chat", run_id)
    assert state["status"] == "failed"
    assert "PRIVATE" not in json.dumps(state)
    with pytest.raises(ResearchInProgress):
        with progress.track("chat", run_id):
            pytest.fail("Replayed request must be rejected")
    with progress.track("chat", str(uuid4())):
        report_progress("saving")
        assert progress.snapshot("chat")["message"] == (
            "Saving this response and any linked sources."
        )
    assert progress.snapshot("chat")["status"] == "completed"


@pytest.mark.parametrize(
    "intake_status,intake_reason",
    [
        ("clarification_required", "assessment_missing"),
        ("refused", "model_declined"),
    ],
)
def test_status_visible_while_request_is_running_and_scoped_to_active_chat(
    tmp_path, monkeypatch, intake_status, intake_reason
):
    from labcat import research
    from labcat.intake import decision, outcome

    started, finish = threading.Event(), threading.Event()

    def slow_research(*args, **kwargs):
        report_progress("discovery")
        started.set()
        assert finish.wait(3)
        return outcome(decision(intake_status, intake_reason))

    monkeypatch.setattr(research, "research", slow_research)
    monkeypatch.setattr(research, "_require_research_setup", lambda *_: None)
    app = create_app(workspace_path=tmp_path / "workspace.sqlite3")
    with TestClient(app, base_url="http://localhost") as client:
        chat = client.post("/api/chats", json={"title": "Progress test"}).json()
        other = client.post("/api/chats", json={"title": "Other chat"}).json()
        run_id = str(uuid4())
        path = f"/api/chats/{chat['id']}"
        with ThreadPoolExecutor() as pool:
            future = pool.submit(
                client.post,
                path + "/messages",
                json={"content": "Find optoelectronic materials", "run_id": run_id},
            )
            try:
                assert started.wait(2)
                state = client.get(
                    path + "/research-status", params={"run_id": run_id}
                ).json()
                assert state["status"] == "running"
                assert state["phase"] == "discovery"
                assert state["run_id"] == run_id
                assert (
                    client.get(f"/api/chats/{other['id']}/research-status").json()[
                        "status"
                    ]
                    == "idle"
                )
                assert (
                    client.post(
                        path + "/messages", json={"content": "Again"}
                    ).status_code
                    == 409
                )
            finally:
                finish.set()
            response = future.result()
            assert response.status_code == 201
            assert response.json()["reports"] == []
            assert response.json()["messages"][-1]["intake"]["status"] == intake_status
        completed = client.get(path + "/research-status").json()
        assert completed["status"] == "completed"
        assert completed["message"] == (
            "Request finished. The response is ready in this chat."
        )
        assert "report" not in completed["message"].casefold()
        assert (
            client.get(
                path + "/research-status", params={"run_id": str(uuid4())}
            ).json()["status"]
            == "idle"
        )
        assert (
            client.post(
                path + "/messages", json={"content": "Again", "run_id": "bad"}
            ).status_code
            == 422
        )
        assert client.get("/api/chats/missing/research-status").status_code == 404
        assert client.delete(path).status_code == 204
        assert client.get(path + "/research-status").status_code == 404


def test_slow_admission_reserves_capacity_without_blocking_other_progress():
    progress = ResearchProgress()
    verifying, verified = threading.Event(), threading.Event()
    accepted = []

    def slow_readiness():
        verifying.set()
        assert verified.wait(5)
        accepted.append("waiting")

    def pending_request():
        with progress.track("waiting", before_start=slow_readiness):
            assert progress.snapshot("waiting")["status"] == "running"

    def inspect_during_verification():
        assert progress.snapshot("active-0")["status"] == "running"
        active = progress.snapshot("active-0")
        progress._update("active-0", active["run_id"], "discovery")
        assert progress.snapshot("active-0")["phase"] == "discovery"
        assert len(progress.running()) == 255
        assert progress.snapshot("waiting")["status"] == "idle"
        for chat_id in ["waiting", "overflow"]:
            with pytest.raises(ResearchInProgress):
                with progress.track(
                    chat_id,
                    before_start=lambda: pytest.fail("Admission was duplicated"),
                ):
                    pytest.fail("Pending admission must reserve its chat and capacity")

    with ExitStack() as active, ThreadPoolExecutor(max_workers=2) as pool:
        for index in range(255):
            active.enter_context(progress.track(f"active-{index}"))
        waiting = pool.submit(pending_request)
        try:
            assert verifying.wait(2)
            # A blocked readiness callback cannot hold the global progress lock.
            pool.submit(inspect_during_verification).result(timeout=2)
            assert accepted == []
        finally:
            verified.set()
        waiting.result(timeout=2)
    assert accepted == ["waiting"]
    assert progress.running() == []


@pytest.mark.parametrize("error_type", [ValueError, KeyboardInterrupt])
def test_failed_admission_releases_reservation_and_preserves_prior_run(error_type):
    progress = ResearchProgress()
    with progress.track("chat"):
        pass
    before = progress.snapshot("chat")
    run_id = str(uuid4())

    def denied():
        raise error_type("Readiness rejected this submission")

    with pytest.raises(error_type, match="Readiness rejected"):
        with progress.track("chat", run_id, before_start=denied):
            pytest.fail("Rejected admission must not enter the running operation")
    assert progress.snapshot("chat") == before
    assert progress.snapshot("chat", run_id)["status"] == "idle"
    with progress.track("chat", run_id):
        assert progress.snapshot("chat")["run_id"] == run_id
    assert progress.snapshot("chat")["status"] == "completed"


def test_pending_replacement_counts_once_and_cannot_be_evicted():
    progress = ResearchProgress()
    with progress.track("replacing"):
        pass
    before = progress.snapshot("replacing")
    verifying, verified = threading.Event(), threading.Event()

    def readiness():
        verifying.set()
        assert verified.wait(5)

    def replacement():
        with progress.track("replacing", before_start=readiness):
            pass

    with ExitStack() as active, ThreadPoolExecutor(max_workers=1) as pool:
        for index in range(254):
            active.enter_context(progress.track(f"active-{index}"))
        pending = pool.submit(replacement)
        try:
            assert verifying.wait(2)
            assert progress.busy("replacing")
            assert progress.snapshot("replacing") == before
            # The completed row and its pending replacement share one slot.
            active.enter_context(progress.track("last-slot"))
            with pytest.raises(ResearchInProgress):
                with progress.track("overflow"):
                    pytest.fail("A pending replacement was evicted")
            assert progress.snapshot("replacing") == before
        finally:
            verified.set()
        pending.result(timeout=2)
    assert not progress.busy("replacing")
