from __future__ import annotations

import asyncio
import logging

import pytest

from apps.worker import main as worker_main


class _SessionScope:
    def __init__(self, session: object) -> None:
        self.session = session
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> object:
        self.entered = True
        return self.session

    async def __aexit__(self, *_: object) -> None:
        self.exited = True


@pytest.mark.asyncio
async def test_due_withdraw_refresh_uses_a_dedicated_session_and_counts_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    scope = _SessionScope(session)

    def session_factory() -> _SessionScope:
        return scope

    async def fake_refresh(received_session: object) -> list[object]:
        assert received_session is session
        return [object(), object()]

    monkeypatch.setattr(worker_main, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(worker_main, "run_due_withdraw_order_refreshes", fake_refresh)

    assert await worker_main.process_due_withdraw_order_refreshes() == 2
    assert scope.entered is True
    assert scope.exited is True


@pytest.mark.asyncio
async def test_due_withdraw_refresh_cycle_hides_remote_error_details(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def failing_refresh() -> int:
        raise RuntimeError("Bearer must-not-appear-in-worker-log")

    monkeypatch.setattr(worker_main, "process_due_withdraw_order_refreshes", failing_refresh)

    with caplog.at_level(logging.WARNING, logger="raj-worker"):
        await worker_main.run_due_withdraw_order_refresh_cycle()

    assert "withdraw order refresh cycle failed; retrying later" in caplog.text
    assert "must-not-appear-in-worker-log" not in caplog.text


@pytest.mark.asyncio
async def test_due_data_dictionary_refresh_uses_a_dedicated_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    scope = _SessionScope(session)

    def session_factory() -> _SessionScope:
        return scope

    async def fake_refresh(received_session: object) -> list[object]:
        assert received_session is session
        return [object()]

    monkeypatch.setattr(worker_main, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(worker_main, "run_due_data_dictionary_refreshes", fake_refresh)

    assert await worker_main.process_due_data_dictionary_refreshes() == 1
    assert scope.entered is True
    assert scope.exited is True


@pytest.mark.asyncio
async def test_due_data_dictionary_cycle_hides_remote_error_details(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def failing_refresh() -> int:
        raise RuntimeError("Bearer must-not-appear-in-dictionary-log")

    monkeypatch.setattr(worker_main, "process_due_data_dictionary_refreshes", failing_refresh)

    with caplog.at_level(logging.WARNING, logger="raj-worker"):
        await worker_main.run_due_data_dictionary_refresh_cycle()

    assert "data dictionary refresh cycle failed; retrying later" in caplog.text
    assert "must-not-appear-in-dictionary-log" not in caplog.text


@pytest.mark.asyncio
async def test_account_relogin_worker_closes_session_and_hides_raw_errors(monkeypatch, caplog):
    session = object()
    scope = _SessionScope(session)
    calls = 0

    async def run_cycle(received_session, *, settings):
        nonlocal calls
        assert received_session is session
        calls += 1
        raise RuntimeError("synthetic-sensitive-error-must-not-appear")

    async def finish_after_cycle(seconds):
        assert seconds == 30
        raise asyncio.CancelledError

    monkeypatch.setattr(worker_main, "AsyncSessionLocal", lambda: scope)
    monkeypatch.setattr(worker_main, "run_due_account_relogins", run_cycle)
    monkeypatch.setattr(worker_main.asyncio, "sleep", finish_after_cycle)
    with caplog.at_level(logging.WARNING, logger="raj-worker"):
        with pytest.raises(asyncio.CancelledError):
            await worker_main.run_remote_account_relogin_loop()
    assert calls == 1 and scope.exited
    assert "remote account login cycle unavailable" in caplog.text
    assert "synthetic-sensitive-error-must-not-appear" not in caplog.text
