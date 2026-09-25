"""Accepted research survives a detached view and publishes its title
promptly."""

from contextlib import ExitStack

import pytest

from labcat.intake import decision, outcome
from labcat.research_progress import ResearchInProgress, ResearchProgress


def clarification():
    # A simulated intake result creates no scientific sources or measurements.
    return outcome(decision("clarification_required", "assessment_missing"))


def test_running_list_is_bounded_copied_and_never_runs_duplicate_acceptance():
    progress = ResearchProgress()
    accepted = []
    with ExitStack() as stack:
        for number in range(256):
            stack.enter_context(progress.track(str(number)))
        with pytest.raises(ResearchInProgress):
            with progress.track("overflow", before_start=lambda: accepted.append(1)):
                pytest.fail("Active entries cannot be evicted")
        with pytest.raises(ResearchInProgress):
            with progress.track("0", before_start=lambda: accepted.append(1)):
                pytest.fail("Duplicate acceptance cannot rename a chat")
        rows = progress.running()
        assert len(rows) == 256
        rows[0]["status"] = "failed"
        assert len(progress.running()) == 256
        assert accepted == []
    assert progress.running() == []
