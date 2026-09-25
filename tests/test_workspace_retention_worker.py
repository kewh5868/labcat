"""Retention lifecycle checks use disposable stores and no live user
data."""

import asyncio
import sqlite3
import threading
import time

from fastapi.testclient import TestClient

from labcat import workspace_retention
from labcat.web import create_app
from labcat.workspace import WorkspaceStore


def test_retention_runs_at_startup_periodically_and_stops(monkeypatch, tmp_path):
    calls = []
    repeated = threading.Event()

    def purge(store):
        calls.append(store)
        if len(calls) >= 2:
            repeated.set()
        return {"projects": 0, "chats": 0}

    monkeypatch.setattr(WorkspaceStore, "purge_expired", purge)
    monkeypatch.setattr(workspace_retention, "RETENTION_SWEEP_SECONDS", 0.01)
    app = create_app(workspace_path=tmp_path / "workspace.sqlite3")
    with TestClient(app, base_url="http://localhost") as client:
        assert calls and calls[0] is app.state.workspace_store
        assert client.get("/health").status_code == 200
        assert repeated.wait(2), "retention must not depend on a removed-items visit"
    completed_calls = len(calls)
    time.sleep(0.04)
    assert len(calls) == completed_calls


def test_failed_sweep_retries_without_logging_data(monkeypatch, tmp_path, caplog):
    calls = 0
    recovered = threading.Event()

    def purge(_store):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise sqlite3.OperationalError("fixture-private-value-not-for-log")
        recovered.set()
        return {"projects": 0, "chats": 0}

    monkeypatch.setattr(WorkspaceStore, "purge_expired", purge)
    monkeypatch.setattr(workspace_retention, "RETENTION_SWEEP_SECONDS", 0.01)
    app = create_app(workspace_path=tmp_path / "workspace.sqlite3")
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/health").status_code == 200
        assert recovered.wait(2)
    assert "OperationalError" in caplog.text
    assert "fixture-private-value-not-for-log" not in caplog.text


def test_shutdown_finishes_an_inflight_sweep(monkeypatch):
    started, release = threading.Event(), threading.Event()

    class Store:
        calls = 0

        def purge_expired(self):
            self.calls += 1
            started.set()
            assert release.wait(2)

    store = Store()
    monkeypatch.setattr(workspace_retention, "RETENTION_SWEEP_SECONDS", 0.001)

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(
            workspace_retention.maintain_removed_items(store, stop)
        )
        try:
            assert await asyncio.to_thread(started.wait, 1)
            stop.set()
            await asyncio.sleep(0.01)
            assert not task.done(), "shutdown must let the transaction finish"
        finally:
            release.set()
            stop.set()
            await asyncio.wait_for(task, timeout=2)
        assert store.calls == 1

    asyncio.run(scenario())
